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
let apiStoreStub: Record<string, unknown>

;(globalThis as unknown as Global).ref = ref
;(globalThis as unknown as Global).computed = computed
;(globalThis as unknown as Global).useFieldConfigStore = () => fieldConfigStub
;(globalThis as unknown as Global).useApiStore = () => apiStoreStub

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

test('loadConfigAndUsers: подгружает больше 50 сотрудников постранично из /api/users', async () => {
  fieldConfigStub = makeConfigStub(87)

  const page1 = Array.from({ length: 200 }, (_, i) => ({
    id: String(i + 1), name: `Имя${i + 1}`, last_name: 'Фамилия', active: true, updated_at: '2026-07-27T00:00:00Z'
  }))
  const page2 = [{ id: '201', name: 'Имя201', last_name: 'Фамилия', active: true, updated_at: '2026-07-27T00:00:00Z' }]

  let callCount = 0
  apiStoreStub = {
    getUsers: async (page: number) => {
      callCount += 1
      if (page === 1) {
        return { items: page1, total: 201, page: 1, pages: 2, has_next: true, has_previous: false }
      }
      return { items: page2, total: 201, page: 2, pages: 2, has_next: false, has_previous: true }
    }
  }

  const loader = useTaskTreeLoader()
  await loader.loadConfigAndUsers({} as never, {})

  assert.equal(loader.usersList.value.length, 201, 'все 201 сотрудник должны загрузиться, а не первые 50')
  assert.equal(callCount, 2, 'должно быть ровно две страницы запроса')
  const lastUser = loader.usersMap.value['201'] as { NAME?: string } | undefined
  assert.equal(lastUser?.NAME, 'Имя201', 'сотрудник со второй страницы должен резолвиться')
})

test('loadConfigAndUsers: сбой /api/users на первой странице — не бросает исключение, конфигурация всё равно грузится', async () => {
  const stub = makeConfigStub(87)
  let loadFromB24Called = false
  stub.loadFromB24 = async () => { loadFromB24Called = true }
  fieldConfigStub = stub

  apiStoreStub = {
    getUsers: async () => {
      throw new Error('Network error')
    }
  }

  const loader = useTaskTreeLoader()
  await assert.doesNotReject(loader.loadConfigAndUsers({} as never, {}), 'сбой справочника сотрудников не должен ронять всё приложение')

  assert.equal(loadFromB24Called, true, 'дерево задачи не должно блокироваться сбоем справочника сотрудников')
  assert.equal(loader.usersList.value.length, 0, 'при падении на первой странице список сотрудников пуст, но не выбрасывает')
})

test('loadConfigAndUsers: сбой /api/users на второй странице — сохраняет уже загруженных сотрудников с первой', async () => {
  fieldConfigStub = makeConfigStub(87)

  const page1 = Array.from({ length: 200 }, (_, i) => ({
    id: String(i + 1), name: `Имя${i + 1}`, last_name: 'Фамилия', active: true, updated_at: '2026-07-27T00:00:00Z'
  }))

  apiStoreStub = {
    getUsers: async (page: number) => {
      if (page === 1) {
        return { items: page1, total: 400, page: 1, pages: 2, has_next: true, has_previous: false }
      }
      throw new Error('Сервер недоступен')
    }
  }

  const loader = useTaskTreeLoader()
  await assert.doesNotReject(loader.loadConfigAndUsers({} as never, {}), 'сбой на второй странице не должен ронять всё приложение')

  assert.equal(loader.usersList.value.length, 200, 'сотрудники с первой (успешной) страницы не должны теряться при сбое второй')
  const firstUser = loader.usersMap.value['1'] as { NAME?: string } | undefined
  assert.equal(firstUser?.NAME, 'Имя1', 'частично собранные до сбоя данные должны попасть в usersMap')
})
