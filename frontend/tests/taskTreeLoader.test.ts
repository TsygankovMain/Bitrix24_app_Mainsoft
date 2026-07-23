/**
 * Регрессия на вечный спиннер во вкладке задачи.
 *
 * Симптом у пользователей: «Загрузка данных задачи» крутится бесконечно,
 * сообщения об ошибке нет. Причина — loadTaskTree выходил ранним return'ом
 * до try/finally, поэтому isLoading (стартовое значение true) не сбрасывался
 * ни на одной из ветвей отказа.
 *
 * Инвариант, который защищаем: loadTaskTree ВСЕГДА завершает загрузку —
 * при любом исходе isLoading становится false, а причина отказа попадает в error.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, ref } from 'vue'

// Композабл написан под авто-импорты Nuxt/Pinia: ref/computed/useFieldConfigStore
// приходят глобально. В чистом node-окружении подставляем их руками ДО импорта модуля.
type Global = Record<string, unknown>

let fieldConfigStub: Record<string, unknown>

;(globalThis as unknown as Global).ref = ref
;(globalThis as unknown as Global).computed = computed
;(globalThis as unknown as Global).useFieldConfigStore = () => fieldConfigStub

const { useTaskTreeLoader } = await import('../app/composables/useTaskTreeLoader')

function makeConfigStub(entityTypeId: number, loadError: string | null = null) {
  return {
    configObject: {
      DEFAULT_SMART_PROCESS_ID: entityTypeId,
      FIELDS: entityTypeId
        ? {
            TASK_ID: 'ufCrm87_TASK_ID',
            EMPLOYEE: 'ufCrm87_EMPLOYEE',
            HOURS: 'ufCrm87_HOURS',
            IS_CONSIDERED: 'ufCrm87_IS_CONSIDERED',
            DESCRIPTION: 'ufCrm87_DESCRIPTION',
            DATE: 'ufCrm87_DATE',
          }
        : {},
      TASK_FIELDS: {},
      SPA_FIELDS: {},
      HOURLY_RATE: 0,
    },
    hourlyRate: 0,
    isConfigured: entityTypeId > 0,
    loadError,
    loadFromB24: async () => {},
  }
}

test('loadTaskTree: конфигурация не загрузилась — спиннер гаснет и видна причина', async () => {
  fieldConfigStub = makeConfigStub(0, 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей.')

  const loader = useTaskTreeLoader()
  assert.equal(loader.isLoading.value, true, 'стартовое состояние — загрузка')

  await loader.loadTaskTree({} as never, '123')

  assert.equal(loader.isLoading.value, false, 'спиннер обязан погаснуть, иначе вкладка залипает навсегда')
  assert.ok(loader.error.value, 'пользователь должен увидеть причину, а не пустой экран')
})

test('loadTaskTree: неполный маппинг полей — спиннер гаснет и видна причина', async () => {
  const stub = makeConfigStub(87)
  ;(stub.configObject as Record<string, unknown>).FIELDS = { TASK_ID: 'ufCrm87_TASK_ID' }
  fieldConfigStub = stub

  const loader = useTaskTreeLoader()
  await loader.loadTaskTree({} as never, '123')

  assert.equal(loader.isLoading.value, false)
  assert.match(String(loader.error.value), /маппинг|Конфигурация/i)
})

test('loadTaskTree: Bitrix отдал ошибку — спиннер гаснет и видна причина', async () => {
  fieldConfigStub = makeConfigStub(87)

  const failingB24 = {
    callMethod: async () => {
      throw new Error('Слишком много запросов, повторите через минуту')
    },
    callBatch: async () => {
      throw new Error('unexpected callBatch')
    },
  }

  const loader = useTaskTreeLoader()
  await loader.loadTaskTree(failingB24 as never, '123')

  assert.equal(loader.isLoading.value, false, 'падение REST не должно оставлять спиннер')
  assert.match(String(loader.error.value), /Слишком много запросов/)
})
