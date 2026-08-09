import type { B24Frame } from '@bitrix24/b24jssdk'
import type { FieldConfigObject } from '~/types/config'
import type { TaskWorkspaceNode } from '~/types/task-workspace'
import { findTaskNodeById } from '~/utils/taskTree'
import {
  applyProjectContextFields,
  buildBaseEntryFields,
  validateEntryBeforeSave,
  type EntryDraft,
  type ProjectCardLike,
  type TaskHierarchy
} from '~/utils/timesheetEntry'

/**
 * Асинхронная обвязка вокруг сборки полей списания: обход иерархии задач,
 * карточка проекта и название задачи. Чистые решения (что куда писать и что
 * блокирует сохранение) живут в utils/timesheetEntry.ts и покрыты тестами —
 * здесь только походы в Bitrix и на бэкенд.
 */

interface B24Client {
  callMethod: (method: string, params?: object) => Promise<{ getData: () => Record<string, unknown> }>
}

const HIERARCHY_DEPTH_LIMIT = 20

function pick(source: Record<string, unknown> | null | undefined, ...keys: string[]): unknown {
  if (!source) {
    return undefined
  }
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) {
      return source[key]
    }
  }
  return undefined
}

export function useTimesheetEntry() {
  const apiStore = useApiStore()
  const projectCardCache = new Map<string, ProjectCardLike | null>()

  /**
   * Поднимается по цепочке родителей задачи, собирая пути id и названий
   * (корень первым), проектную группу и ИНН с полей задачи.
   *
   * Ограничение глубины — страховка от циклической связи PARENT_ID, при
   * которой обход не завершился бы никогда.
   */
  async function collectTaskHierarchy(
    $b24: B24Frame,
    config: FieldConfigObject,
    taskId: string
  ): Promise<TaskHierarchy | null> {
    const client = $b24 as unknown as B24Client
    const idPath: string[] = []
    const titlePath: string[] = []
    let projectId: string | null = null
    let projectTitle = ''
    let ourInn = ''
    let clientInn = ''

    const ourInnTaskField = String(config.TASK_FIELDS?.OUR_INN || '').trim()
    const clientInnTaskField = String(config.TASK_FIELDS?.CLIENT_INN || '').trim()

    let currentTaskId: string | null = String(taskId || '').trim() || null
    let depth = 0

    while (currentTaskId && depth < HIERARCHY_DEPTH_LIMIT) {
      try {
        const select = ['ID', 'TITLE', 'GROUP_ID', 'PARENT_ID']
        if (ourInnTaskField) select.push(ourInnTaskField)
        if (clientInnTaskField) select.push(clientInnTaskField)

        const response = await client.callMethod('tasks.task.get', { taskId: currentTaskId, select })
        const data = response.getData()
        const task = (data.task || (data.result as Record<string, unknown> | undefined)?.task) as Record<string, unknown> | undefined

        if (!task) {
          break
        }

        const groupId = pick(task, 'groupId', 'group_id', 'GROUP_ID', 'GroupId')
        if (!projectId && groupId && String(groupId) !== '0') {
          projectId = String(groupId)
        }

        const uf = task.uf as Record<string, unknown> | undefined
        if (!ourInn && ourInnTaskField) {
          ourInn = String(task[ourInnTaskField] || uf?.[ourInnTaskField] || '')
        }
        if (!clientInn && clientInnTaskField) {
          clientInn = String(task[clientInnTaskField] || uf?.[clientInnTaskField] || '')
        }

        const id = pick(task, 'id', 'ID', 'Id')
        const title = pick(task, 'title', 'TITLE', 'Title')
        if (id) idPath.unshift(String(id))
        if (title) titlePath.unshift(String(title))

        const parentId = pick(task, 'parentId', 'parent_id', 'PARENT_ID', 'ParentId')
        currentTaskId = parentId && String(parentId) !== '0' ? String(parentId) : null
      } catch (error) {
        console.error('[TimesheetEntry] Не удалось получить задачу иерархии', currentTaskId, error)
        currentTaskId = null
      }
      depth += 1
    }

    if (projectId) {
      try {
        const groupResponse = await client.callMethod('sonet_group.get', { FILTER: { ID: projectId } })
        const groupData = groupResponse.getData() as Record<string, unknown>
        const group = (groupData[0] || (groupData.result as Record<string, unknown>[] | undefined)?.[0]) as Record<string, unknown> | undefined
        projectTitle = String(group?.NAME || '')
      } catch (error) {
        console.error('[TimesheetEntry] Не удалось получить проектную группу', projectId, error)
      }
    }

    return { idPath, titlePath, projectId, projectTitle, ourInn, clientInn }
  }

  /** Карточка проекта с кэшем на время жизни экрана. */
  async function loadProjectCard(projectId?: string | null): Promise<ProjectCardLike | null> {
    const normalized = String(projectId || '').trim()
    if (!normalized) {
      return null
    }
    if (projectCardCache.has(normalized)) {
      return projectCardCache.get(normalized) ?? null
    }

    try {
      const card = await apiStore.getProjectBoardCard(normalized) as ProjectCardLike | null
      projectCardCache.set(normalized, card)
      return card
    } catch (error) {
      console.warn('[TimesheetEntry] Не удалось загрузить карточку проекта', normalized, error)
      return null
    }
  }

  /**
   * Название задачи: сначала из уже загруженного дерева, потом из собранной
   * иерархии, и только в последнюю очередь отдельным запросом.
   */
  async function resolveTaskName(
    $b24: B24Frame,
    taskId: string,
    hierarchy: TaskHierarchy | null,
    taskTree: TaskWorkspaceNode[]
  ): Promise<string> {
    const fromTree = findTaskNodeById(taskId, taskTree)?.taskTitle
    if (fromTree && fromTree.trim()) {
      return fromTree.trim()
    }

    const fromHierarchy = hierarchy?.titlePath?.[hierarchy.titlePath.length - 1]
    if (fromHierarchy && fromHierarchy.trim()) {
      return fromHierarchy.trim()
    }

    const normalized = String(taskId || '').trim()
    if (!normalized) {
      return ''
    }

    try {
      const response = await (($b24 as unknown) as B24Client).callMethod('tasks.task.get', {
        taskId: normalized,
        select: ['ID', 'TITLE']
      })
      const data = response.getData()
      const task = ((data.result as Record<string, unknown> | undefined)?.task || data.task) as Record<string, unknown> | undefined
      return String(pick(task, 'title', 'TITLE', 'Title') || '').trim()
    } catch (error) {
      console.warn('[TimesheetEntry] Не удалось дозагрузить название задачи', normalized, error)
      return ''
    }
  }

  /**
   * Собирает полный набор полей записи и проверяет его.
   * Возвращает поля и результат проверки — решение показывать ошибку
   * принимает экран.
   */
  async function prepareEntryFields(
    $b24: B24Frame,
    config: FieldConfigObject,
    entry: EntryDraft,
    taskTree: TaskWorkspaceNode[]
  ) {
    const taskId = String(entry.taskId || '').trim()
    const fields = buildBaseEntryFields(config, entry, taskId)

    const hierarchy = taskId ? await collectTaskHierarchy($b24, config, taskId) : null
    const projectCard = hierarchy?.projectId ? await loadProjectCard(hierarchy.projectId) : null
    const resolvedTaskName = await resolveTaskName($b24, taskId, hierarchy, taskTree)

    applyProjectContextFields(fields, config, { hierarchy, projectCard, resolvedTaskName })

    return { fields, validation: validateEntryBeforeSave(config, fields, hierarchy) }
  }

  return { collectTaskHierarchy, loadProjectCard, resolveTaskName, prepareEntryFields }
}
