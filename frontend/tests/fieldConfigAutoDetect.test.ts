/**
 * Регрессия на «зашёл администратор — заработало у всех».
 *
 * Симптом: вкладка задачи и отчёты грузятся по многу минут у рядовых сотрудников,
 * но стоит администратору открыть приложение — отклик у всех становится 1–3 секунды.
 *
 * Причина: при неполном портальном конфиге `autoDetectMissingMappings` на КАЖДОЙ
 * загрузке зовёт тяжёлый `crm.item.fields`, а затем пытается записать результат через
 * `app.option.set`. Метод `app.option.set` доступен ТОЛЬКО администратору
 * (https://apidocs.bitrix24.ru/api-reference/common/settings/app-option-set.html) —
 * у рядового сотрудника он падает с AccessException, результат не сохраняется,
 * и на следующей загрузке всё повторяется. Вызов стоит в критическом пути
 * (loadConfigAndUsers → loadFromB24 → до loadTaskTree), поэтому тормозит вкладку.
 * Когда администратор открывает приложение, запись проходит, конфиг ложится
 * портально (app.option — общее хранилище на приложение), автодетект выключается
 * у всех сразу.
 *
 * Инвариант, который защищаем: автодетект-с-записью выполняется только тем, кто
 * реально может сохранить результат (администратор). Рядовой сотрудник не платит
 * за заведомо провальный цикл.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { setActivePinia, createPinia } from 'pinia'

type Global = Record<string, unknown>

// useUserStore приходит в fieldConfig через авто-импорт Nuxt. В чистом node-окружении
// подставляем заглушку в globalThis ДО импорта модуля стора.
let isAdminStub = false
;(globalThis as unknown as Global).useUserStore = () => ({
  get isAdmin() {
    return isAdminStub
  },
})

const { useFieldConfigStore } = await import('../app/stores/fieldConfig')

/**
 * Конфиг со смарт-процессом, но БЕЗ пяти авто-детектируемых ключей
 * (task_name, our_inn, client_inn, project_item_id, hourly_rate_snapshot) —
 * значит missingKeys непустой и автодетект в принципе запускается.
 */
function makeIncompleteConfigJson(): string {
  return JSON.stringify({
    sp_entity_type_id: 1032,
    fields_mapping: {
      id_zadachi: 'ufCrm1_TASK_ID',
      sotrudnik: 'ufCrm1_EMPLOYEE',
      kolichestvo_chasov: 'ufCrm1_HOURS',
      uchitivaem: 'ufCrm1_CONSIDERED',
      opisanie: 'ufCrm1_DESC',
      data: 'ufCrm1_DATE',
    },
  })
}

/** $b24-заглушка: записывает имена вызванных методов и отдаёт минимальные ответы. */
function makeB24(calledMethods: string[]) {
  return {
    callMethod(method: string) {
      calledMethods.push(method)
      if (method === 'app.option.get') {
        return Promise.resolve({ getData: () => ({ timestamp_config: makeIncompleteConfigJson() }) })
      }
      if (method === 'crm.item.fields') {
        return Promise.resolve({ getData: () => ({ result: { fields: {} } }) })
      }
      // app.option.set и всё прочее
      return Promise.resolve({ getData: () => ({}) })
    },
  }
}

test('рядовой сотрудник: автодетект не зовёт crm.item.fields и app.option.set', async () => {
  setActivePinia(createPinia())
  isAdminStub = false

  const called: string[] = []
  const store = useFieldConfigStore()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await store.loadFromB24(makeB24(called) as any)

  assert.ok(
    !called.includes('crm.item.fields'),
    'у сотрудника без прав не должно быть тяжёлого crm.item.fields в критическом пути',
  )
  assert.ok(
    !called.includes('app.option.set'),
    'у сотрудника без прав не должно быть заведомо провального app.option.set',
  )
})

test('администратор: при неполном конфиге автодетект зовёт crm.item.fields', async () => {
  setActivePinia(createPinia())
  isAdminStub = true

  const called: string[] = []
  const store = useFieldConfigStore()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await store.loadFromB24(makeB24(called) as any)

  assert.ok(
    called.includes('crm.item.fields'),
    'администратор по-прежнему выполняет автоопределение полей',
  )
})
