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
    const batch: Record<string, { method: string; params?: Record<string, unknown> }> = {
      users: { method: 'user.get', params: { FILTER: { ACTIVE: 'Y' }, sort: 'LAST_NAME', order: 'ASC' } }
    }

    if (options.includeProfile) {
      batch.profile = { method: 'profile' }
    }

    const client = $b24 as unknown as B24BatchClient
    const result = await client.callBatch(batch)
    const data = result.getData()

    const usersResponse = data.users as RawRecord | undefined
    if (usersResponse && !usersResponse.error) {
      const users = extractResult(usersResponse)
      const map: Record<string, TaskWorkspaceUser> = {}
      if (Array.isArray(users)) {
        for (const user of users) {
          map[String(user.ID)] = user
        }
      }
      usersMap.value = map
    }

    if (options.includeProfile) {
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
      const queue = [normalizedRootTaskId]
      let iterations = 0

      while (queue.length > 0 && iterations < 50) {
        const batch: Record<string, { method: string; params: Record<string, unknown> }> = {}
        const currentLevelIds = queue.splice(0, 50)

        for (const parentId of currentLevelIds) {
          batch[`tasks_${parentId}`] = {
            method: 'tasks.task.list',
            params: {
              filter: { PARENT_ID: parentId },
              select: ['ID', 'TITLE', 'PARENT_ID']
            }
          }
        }

        if (!Object.keys(batch).length) {
          break
        }

        const batchResponse = await client.callBatch(batch)
        const batchData = batchResponse.getData()

        for (const response of Object.values(batchData) as RawRecord[]) {
          if (response?.error) {
            continue
          }

          for (const task of extractTaskList(response)) {
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
            queue.push(taskIdValue)
          }
        }

        iterations += 1
      }

      const allTaskIds = allTasks.map(task => task.id)
      const taskItems: Array<{ taskId: string; item: TaskWorkspaceItem }> = []
      const seenItemIds = new Set<string>()

      for (let index = 0; index < allTaskIds.length; index += 50) {
        const chunk = allTaskIds.slice(index, index + 50)
        const batch: Record<string, { method: string; params: Record<string, unknown> }> = {}

        for (const currentTaskId of chunk) {
          batch[`items_${currentTaskId}`] = {
            method: 'crm.item.list',
            params: {
              entityTypeId: smartProcessId,
              filter: { [fieldTaskId]: Number(currentTaskId) },
              select: ['id', 'createdTime', fieldTaskId, fieldEmployee, fieldHours, fieldIsConsidered, fieldDescription, 'TITLE', fieldDate],
              start: 0,
              limit: 50
            }
          }
        }

        const chunkResponse = await client.callBatch(batch)
        const chunkData = chunkResponse.getData()
        const tasksNeedingMore: string[] = []

        for (const [key, response] of Object.entries(chunkData) as Array<[string, RawRecord]>) {
          if (response?.error) {
            continue
          }

          const items = extractItemList(response)
          for (const item of items) {
            const itemId = String(item.id)
            if (seenItemIds.has(itemId)) {
              continue
            }
            seenItemIds.add(itemId)
            const taskIdValue = String(item[fieldTaskId] ?? key.replace('items_', ''))
            const employeeId = String(item[fieldEmployee] || '')
            const user = usersMap.value[employeeId]
            const employeeName = user ? `${user.NAME || ''} ${user.LAST_NAME || ''}`.trim() : `User ${employeeId}`
            const date = (item[fieldDate] || (item.createdTime ? String(item.createdTime).split('T')[0] : '')) as string

            taskItems.push({
              taskId: taskIdValue,
              item: {
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
            })
          }

          if (items.length >= 50) {
            tasksNeedingMore.push(key.replace('items_', ''))
          }
        }

        for (const currentTaskId of tasksNeedingMore) {
          let start = 50
          let pageCount = 0

          while (pageCount < 50) {
            const extraBatch = {
              [`extra_${currentTaskId}_${start}`]: {
                method: 'crm.item.list',
                params: {
                  entityTypeId: smartProcessId,
                  filter: { [fieldTaskId]: Number(currentTaskId) },
                  select: ['id', 'createdTime', fieldTaskId, fieldEmployee, fieldHours, fieldIsConsidered, fieldDescription, 'TITLE', fieldDate],
                  start,
                  limit: 50
                }
              }
            }

            const extraResponse = await client.callBatch(extraBatch)
            const extraData = extraResponse.getData()
            const extraItems = extractItemList(extraData[`extra_${currentTaskId}_${start}`])
            let newCount = 0

            for (const item of extraItems) {
              const itemId = String(item.id)
              if (seenItemIds.has(itemId)) {
                break
              }

              seenItemIds.add(itemId)
              newCount += 1
              const employeeId = String(item[fieldEmployee] || '')
              const user = usersMap.value[employeeId]
              const employeeName = user ? `${user.NAME || ''} ${user.LAST_NAME || ''}`.trim() : `User ${employeeId}`
              const date = (item[fieldDate] || (item.createdTime ? String(item.createdTime).split('T')[0] : '')) as string

              taskItems.push({
                taskId: String(item[fieldTaskId] ?? currentTaskId),
                item: {
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
              })
            }

            pageCount += 1
            if (newCount < 50) {
              break
            }

            start += 50
          }
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
