import type { B24Frame } from '@bitrix24/b24jssdk'
import type { FieldConfigObject } from '~/types/config'
import type { TaskWorkspaceItem, TaskWorkspaceNode, TaskWorkspaceUser } from '~/types/task-workspace'
import { attachItemsToTaskNodes, buildTaskTree, calculateTaskNodeTotals } from '~/utils/taskTree'

interface LoadTaskTreeOptions {
  includeProfile?: boolean
}

type RawRecord = Record<string, unknown>

interface CrmItemRaw {
  id: string | number
  title?: string
  TITLE?: string
  createdTime?: string
  [key: string]: unknown
}

interface B24BatchResult {
  getData: () => RawRecord
}

// Minimal local view of the B24Frame batch API. Casting through this avoids
// resolving the SDK's heavy generic Result/AjaxResult types at every call site.
interface B24BatchClient {
  callBatch: (calls: object, isHaltOnError?: boolean, returnAjaxResult?: boolean) => Promise<B24BatchResult>
  callMethod: (method: string, params?: object, start?: number) => Promise<B24BatchResult>
}

function extractResult(response: unknown): unknown {
  const record = response as RawRecord | null | undefined
  return record?.result || record?.data || response
}

function extractTaskList(response: unknown): RawRecord[] {
  const result = extractResult(response) as RawRecord | null | undefined
  return (result?.tasks || result || []) as RawRecord[]
}

function extractItemList(response: unknown): CrmItemRaw[] {
  const result = extractResult(response) as RawRecord | null | undefined
  return (result?.items || result || []) as CrmItemRaw[]
}

function extractSingleTask(response: unknown): RawRecord | null {
  const result = extractResult(response) as RawRecord | null | undefined
  const raw = response as RawRecord | null | undefined
  return (result?.task || raw?.task || null) as RawRecord | null
}

export function useTaskTreeLoader() {
  const fieldConfigStore = useFieldConfigStore()

  const isLoading = ref(true)
  const error = ref<string | null>(null)
  const usersMap = ref<Record<string, TaskWorkspaceUser>>({})
  const currentUserId = ref<string | null>(null)
  const taskTree = ref<TaskWorkspaceNode[]>([])

  const usersList = computed(() => Object.values(usersMap.value))
  const config = computed<FieldConfigObject>(() => fieldConfigStore.configObject as FieldConfigObject)
  const clientHourRate = computed(() => fieldConfigStore.hourlyRate)

  async function loadConfigAndUsers($b24: B24Frame, options: LoadTaskTreeOptions = {}) {
    const apiStore = useApiStore()
    const client = $b24 as unknown as B24BatchClient

    // Сотрудники — из локальной БД через /api/users (пагинированно), а не прямым
    // user.get у Bitrix: user.get без курсора отдавал только первые 50 (баг «только
    // 50 сотрудников» / «User <id>» в дереве задачи). БД держит полную актуальную
    // копию (Фаза 2 sync-offload).
    //
    // activeOnly=false: списания часов в дереве задачи сплошь и рядом относятся
    // к уже уволенным сотрудникам — их имена обязаны резолвиться, а не
    // показывать "User <id>" (хотфикс 2026-07-28).
    const map: Record<string, TaskWorkspaceUser> = {}
    const USERS_PAGE_LIMIT = 200
    const USERS_MAX_PAGES = 25 // защита от зацикливания; 25*200 = 5000 сотрудников с запасом
    let page = 1
    let hitPageCap = false
    try {
      while (page <= USERS_MAX_PAGES) {
        const response = await apiStore.getUsers(page, USERS_PAGE_LIMIT, false)
        for (const item of response.items) {
          map[String(item.id)] = { ID: item.id, NAME: item.name, LAST_NAME: item.last_name }
        }
        if (!response.has_next) {
          break
        }
        if (page === USERS_MAX_PAGES) {
          hitPageCap = true
        }
        page += 1
      }
    } catch (usersError) {
      // Деградация должна быть мягкой: сбой справочника сотрудников (сеть, 5xx,
      // бэкенд ещё не поднялся после деплоя) не должен ронять всю вкладку задачи —
      // profile-батч и fieldConfigStore.loadFromB24 ниже обязаны отработать. Уже
      // накопленные до сбоя страницы не выбрасываются (частичный usersMap лучше пустого).
      console.error('Failed to load users directory from /api/users', usersError)
    }
    if (hitPageCap) {
      console.warn(`useTaskTreeLoader: достигнут лимит страниц (${USERS_MAX_PAGES}) при загрузке /api/users, но есть ещё данные — часть сотрудников может отображаться как "User <id>"`)
    }
    usersMap.value = map

    if (options.includeProfile) {
      const batch: Record<string, { method: string; params?: Record<string, unknown> }> = {
        profile: { method: 'profile' }
      }
      const result = await client.callBatch(batch)
      const data = result.getData()
      const profile = extractResult(data.profile) as RawRecord | null
      if (profile?.ID) {
        currentUserId.value = String(profile.ID)
      }
    }

    await fieldConfigStore.loadFromB24($b24)
    if (!fieldConfigStore.isConfigured) {
      error.value = fieldConfigStore.loadError || 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей и настройте поля.'
    }
  }

  async function loadTaskTree($b24: B24Frame, taskId: string) {
    if (!config.value?.DEFAULT_SMART_PROCESS_ID) {
      // Терминальный отказ: грузить нечего. Выходить молча нельзя — isLoading
      // стартует как true и гасится только в finally ниже, поэтому ранний return
      // оставлял вкладку задачи навсегда на «Загрузка данных задачи» без причины.
      error.value = error.value
        || fieldConfigStore.loadError
        || 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей и настройте поля.'
      isLoading.value = false
      return
    }

    isLoading.value = true
    error.value = null

    const fields = config.value.FIELDS || {}
    const fieldTaskId = String(fields.TASK_ID || '').trim()
    const fieldEmployee = String(fields.EMPLOYEE || '').trim()
    const fieldHours = String(fields.HOURS || '').trim()
    const fieldIsConsidered = String(fields.IS_CONSIDERED || '').trim()
    const fieldDescription = String(fields.DESCRIPTION || '').trim()
    const fieldDate = String(fields.DATE || '').trim()

    if (!fieldTaskId || !fieldEmployee || !fieldHours || !fieldIsConsidered || !fieldDescription || !fieldDate) {
      error.value = 'Конфигурация полей для дерева задач неполная. Проверьте маппинг в настройках.'
      isLoading.value = false
      return
    }

    const smartProcessId = config.value.DEFAULT_SMART_PROCESS_ID
    const client = $b24 as unknown as B24BatchClient

    try {
      const rootTaskResponse = await client.callMethod('tasks.task.get', {
        taskId,
        select: ['ID', 'TITLE']
      })

      const rootTask = extractSingleTask(rootTaskResponse.getData())
      if (!rootTask?.id && !rootTask?.ID) {
        throw new Error('Не удалось загрузить корневую задачу.')
      }

      const normalizedRootTaskId = String(rootTask?.id || rootTask?.ID)
      const allTasks: Array<{ id: string; title: string; parentId: string | null }> = [{
        id: normalizedRootTaskId,
        title: String(rootTask?.title || rootTask?.TITLE || ''),
        parentId: null
      }]

      const processed = new Set<string>([normalizedRootTaskId])

      // Обход подзадач с ПАГИНАЦИЕЙ. tasks.task.list отдаёт максимум 50 записей
      // за вызов и листается смещением `start` (у метода нет поля next, только
      // total). Раньше `start` не передавался и признак «есть ещё» не
      // проверялся — у родителя с более чем 50 подзадачами часть дерева просто
      // молча пропадала вместе со списанными на неё часами. Это была потеря
      // данных, а не только вопрос скорости.
      //
      // Очередь хранит не просто id родителя, а пару (родитель, смещение):
      // недочитанная страница возвращается в ту же очередь и уезжает следующим
      // батчем вместе с новыми родителями, без отдельного последовательного
      // цикла на каждую задачу.
      interface SubtaskPage { parentId: string, start: number }
      const TASKS_PAGE_SIZE = 50
      const REQUESTS_PER_BATCH = 50
      const MAX_BATCHES = 200 // страховка: до 10 000 запросов на дерево

      const pending: SubtaskPage[] = [{ parentId: normalizedRootTaskId, start: 0 }]
      let iterations = 0

      while (pending.length > 0 && iterations < MAX_BATCHES) {
        const currentPages = pending.splice(0, REQUESTS_PER_BATCH)
        const batch: Record<string, { method: string; params: Record<string, unknown> }> = {}

        currentPages.forEach((page, position) => {
          batch[`tasks_${position}`] = {
            method: 'tasks.task.list',
            params: {
              filter: { PARENT_ID: page.parentId },
              select: ['ID', 'TITLE', 'PARENT_ID'],
              start: page.start
            }
          }
        })

        const batchResponse = await client.callBatch(batch)
        const batchData = batchResponse.getData()

        currentPages.forEach((page, position) => {
          const response = batchData[`tasks_${position}`] as RawRecord | undefined
          if (!response || response.error) {
            return
          }

          const tasks = extractTaskList(response)
          for (const task of tasks) {
            const taskIdValue = String(task.ID || task.id)
            if (processed.has(taskIdValue)) {
              continue
            }

            processed.add(taskIdValue)
            allTasks.push({
              id: taskIdValue,
              title: String(task.TITLE || task.title || ''),
              parentId: task.PARENT_ID || task.parentId ? String(task.PARENT_ID || task.parentId) : null
            })
            pending.push({ parentId: taskIdValue, start: 0 })
          }

          // Пришла полная страница — у этого родителя есть ещё подзадачи.
          if (tasks.length >= TASKS_PAGE_SIZE) {
            pending.push({ parentId: page.parentId, start: page.start + TASKS_PAGE_SIZE })
          }
        })

        iterations += 1
      }

      if (iterations >= MAX_BATCHES) {
        console.warn('useTaskTreeLoader: достигнут предел обхода подзадач — дерево может быть неполным')
      }

      const allTaskIds = allTasks.map(task => task.id)
      const taskItems: Array<{ taskId: string; item: TaskWorkspaceItem }> = []
      const seenItemIds = new Set<string>()
      // Сотрудники, которых нет в usersMap (не попали в /api/users — справочник
      // ещё не досинкался или портал новый). Дорезолвливаются одним
      // Bitrix-батчем после сбора всех элементов дерева (см. ниже).
      const missingEmployeeIds = new Set<string>()
      const pendingFallbackItems: TaskWorkspaceItem[] = []

      const itemSelect = ['id', 'createdTime', fieldTaskId, fieldEmployee, fieldHours, fieldIsConsidered, fieldDescription, 'TITLE', fieldDate]

      const appendItem = (item: CrmItemRaw) => {
        const itemId = String(item.id)
        if (seenItemIds.has(itemId)) {
          return
        }
        seenItemIds.add(itemId)

        // Задача берётся из самого элемента: мы фильтровали по этому полю, значит
        // оно заполнено. Раньше здесь был запасной вариант «взять из ключа батча»,
        // но ключ больше не соответствует одной задаче — фильтр общий на пачку.
        const taskIdValue = String(item[fieldTaskId] ?? '')
        const employeeId = String(item[fieldEmployee] || '')
        const user = usersMap.value[employeeId]
        const employeeName = user ? `${user.NAME || ''} ${user.LAST_NAME || ''}`.trim() : `User ${employeeId}`
        const date = (item[fieldDate] || (item.createdTime ? String(item.createdTime).split('T')[0] : '')) as string

        const taskItem: TaskWorkspaceItem = {
          id: itemId,
          title: item.title || item.TITLE || '',
          createdTime: item.createdTime,
          hours: parseFloat(item[fieldHours] as string) || 0,
          isConsidered: item[fieldIsConsidered] === 'Y' || item[fieldIsConsidered] === true,
          description: (item[fieldDescription] || '') as string,
          employeeId,
          employeeName,
          date
        }
        if (!user && employeeId) {
          missingEmployeeIds.add(employeeId)
          pendingFallbackItems.push(taskItem)
        }
        taskItems.push({ taskId: taskIdValue, item: taskItem })
      }

      // Списания забираются ОДНИМ crm.item.list на пачку задач через IN-фильтр
      // (`@поле: [id, ...]`, apidocs.bitrix24.ru/api-reference/crm/universal/crm-item-list.html),
      // а не по вызову на каждую задачу.
      //
      // Зачем: операционный лимит Bitrix (480 с на скользящие 10 минут) считается
      // ОТДЕЛЬНО ПО КАЖДОМУ методу и общий на всё приложение, причём внешний batch
      // в него не входит — то есть T вложенных crm.item.list стоили как T вызовов,
      // сколько их ни упаковывай. Фильтр по UF-полю смарт-процесса идёт по
      // b_uts_crm_dynamic_* без индекса, поэтому цена каждого росла с объёмом
      // списаний на портале. Дерево из 20 задач съедало ~6 с общего бюджета, то
      // есть ~80 открытий вкладки на весь портал за 10 минут — дальше метод
      // блокировался у всех сразу (инцидент 2026-07-27).
      //
      // Пагинация — keyset (order id asc + фильтр `>id`), как в бэкендовом синке:
      // offset-пагинация на больших выборках дорожает с ростом start, а страницы
      // могут «поехать» при параллельной записи. Прежний код листал каждую задачу
      // отдельно и строго последовательно.
      const TASK_IDS_PER_QUERY = 50
      const PAGE_SIZE = 50
      const MAX_PAGES_PER_CHUNK = 200 // страховка от бесконечного цикла: 10 000 списаний на пачку

      for (let index = 0; index < allTaskIds.length; index += TASK_IDS_PER_QUERY) {
        const chunk = allTaskIds.slice(index, index + TASK_IDS_PER_QUERY).map(Number)
        let lastId = 0
        let pageCount = 0

        while (pageCount < MAX_PAGES_PER_CHUNK) {
          const response = await client.callMethod('crm.item.list', {
            entityTypeId: smartProcessId,
            filter: {
              [`@${fieldTaskId}`]: chunk,
              '>id': lastId
            },
            order: { id: 'ASC' },
            select: itemSelect
          })

          const items = extractItemList(response.getData())
          if (!items.length) {
            break
          }

          for (const item of items) {
            appendItem(item)
          }

          const lastItem = items[items.length - 1]
          const nextId = Number(lastItem?.id)
          if (!Number.isFinite(nextId) || nextId <= lastId) {
            break // защита от зацикливания, если Bitrix вернул неожиданный порядок
          }
          lastId = nextId
          pageCount += 1

          if (items.length < PAGE_SIZE) {
            break
          }
        }

        if (pageCount >= MAX_PAGES_PER_CHUNK) {
          console.warn('useTaskTreeLoader: достигнут предел страниц списаний для пачки задач — часть данных может быть не показана')
        }
      }

      // Bitrix-фоллбэк для сотрудников вне usersMap (/api/users справочник ещё
      // не досинкался / портал новый). Раньше такой батч уже был в этом файле
      // до перехода на локальный справочник (см. git-историю), тот же паттерн
      // используется и сейчас в reports/project-report.client.vue. Сбой здесь
      // мягко деградирует до плейсхолдера "User <id>" — как и сбой /api/users
      // выше — и не должен ронять дерево задачи (хотфикс 2026-07-28).
      if (missingEmployeeIds.size > 0) {
        try {
          const idsToResolve = Array.from(missingEmployeeIds)
          const resolvedUsers: Record<string, TaskWorkspaceUser> = {}

          for (let i = 0; i < idsToResolve.length; i += 50) {
            const chunk = idsToResolve.slice(i, i + 50)
            const userBatch: Record<string, { method: string; params: Record<string, unknown> }> = {}
            for (const id of chunk) {
              userBatch[`user_${id}`] = { method: 'user.get', params: { ID: id } }
            }

            const userBatchResponse = await client.callBatch(userBatch)
            const userBatchData = userBatchResponse.getData()

            for (const id of chunk) {
              const response = userBatchData[`user_${id}`] as RawRecord | undefined
              if (!response || response.error) {
                continue
              }
              const raw = extractResult(response)
              const record = (Array.isArray(raw) ? raw[0] : raw) as RawRecord | null | undefined
              if (record && record.ID !== undefined) {
                resolvedUsers[id] = {
                  ID: record.ID as string | number,
                  NAME: record.NAME as string | undefined,
                  LAST_NAME: record.LAST_NAME as string | undefined
                }
              }
            }
          }

          if (Object.keys(resolvedUsers).length > 0) {
            usersMap.value = { ...usersMap.value, ...resolvedUsers }
            for (const taskItem of pendingFallbackItems) {
              const resolved = resolvedUsers[String(taskItem.employeeId)]
              if (resolved) {
                taskItem.employeeName = `${resolved.NAME || ''} ${resolved.LAST_NAME || ''}`.trim() || taskItem.employeeName
              }
            }
          }
        } catch (fallbackError) {
          console.error('Failed to resolve missing employee names via Bitrix user.get fallback', fallbackError)
        }
      }

      const { roots, nodesMap } = buildTaskTree(normalizedRootTaskId, allTasks)
      attachItemsToTaskNodes(nodesMap, taskItems)

      for (const root of roots) {
        calculateTaskNodeTotals(root)
      }

      taskTree.value = roots
    } catch (caughtError) {
      console.error(caughtError)
      error.value = (caughtError as Error)?.message || String(caughtError)
    } finally {
      isLoading.value = false
    }
  }

  return {
    isLoading,
    error,
    usersMap,
    usersList,
    currentUserId,
    taskTree,
    config,
    clientHourRate,
    loadConfigAndUsers,
    loadTaskTree
  }
}
