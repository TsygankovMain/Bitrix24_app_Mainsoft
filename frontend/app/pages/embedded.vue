<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'

import HelpSidePanel from '@/components/HelpSidePanel.vue'
import { canOpenNativeApplication, resolveTaskPlacementId, useIframeResizeOnToggle } from '@/composables/useTaskPlacement'
import { useTaskTreeLoader } from '@/composables/useTaskTreeLoader'
import { filterTaskTree, findTaskIdForItem, findTaskNodeById, flattenTaskItems } from '@/utils/taskTree'

const { $logger, initApp, processErrorGlobal } = useAppInit('EmbeddedPage')
const { $initializeB24Frame } = useNuxtApp()
const { t, locales: localesI18n, setLocale } = useI18n()

// --- STATE ---
const isHelpOpen = ref(false)


import { requestIframeFullHeight } from '@/utils/iframe-resizer'

// --- Diagnostics & Navigation ---
const isNativeSidePanelAvailable = ref(false)

function openHelp() {
    if (isNativeSidePanelAvailable.value) {
        // Try native slider first
        try {
             /* 
                Using BX24.openApplication to open the guide route in a native slider. 
                This puts the guide OUTSIDE the iframe constraints.
             */
             // @ts-ignore
             window.BX24.openApplication(
                { 
                    url: '/guide?from=slider' 
                },
                {
                    title: 'Справочник',
                    width: 900
                }
             );
             return;
        } catch (e) {
            console.error('Native slider failed, using fallback', e)
        }
    }
    
    // Fallback to local teleported component
    // Request full height to prevent clipping
    requestIframeFullHeight()
    isHelpOpen.value = true
}

useIframeResizeOnToggle(isHelpOpen)


let $b24: null | B24Frame = null
const apiStore = useApiStore()

const rootTaskId = ref<string | null>(null)
const expandedTasks = ref<Set<string>>(new Set())
const currentEditingId = ref<string | null>(null)
const editingItem = ref<any>(null)

const {
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
} = useTaskTreeLoader()

// --- FILTER STATE ---
const filterEmployeeId = ref<string>('')
const filterDateFrom = ref<string>('')
const filterDateTo = ref<string>('')

const projectCardCache = new Map<string, any>()

async function reloadWorkspace() {
    if (!$b24 || !rootTaskId.value) {
        return
    }

    await loadTaskTree($b24, rootTaskId.value)
    expandedTasks.value = new Set([rootTaskId.value])
    
    apiStore.syncTimesheets().then(() => {
        projectCardCache.clear()
    }).catch(e => console.warn('[Embedded] Background sync failed', e))
}

// --- INITIALIZATION ---
onMounted(async () => {

    // Diagnostics
    const isInIframe = window.self !== window.top
    const hasBX24 = typeof (window as any).BX24 !== 'undefined'
    
    console.info('[Diagnostics] Env:', { isInIframe, hasBX24 })
    
    // Check if we can open native slider
    if (hasBX24 && canOpenNativeApplication()) {
        console.info('[Diagnostics] Native SidePanel (openApplication) is AVAILABLE')
        isNativeSidePanelAvailable.value = true
    } else {
        console.warn('[Diagnostics] Native SidePanel is NOT available')
    }

    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)

        const tid = resolveTaskPlacementId($b24)
        if (!tid) {
            error.value = "Не передан ID задачи. Откройте приложение во вкладке задачи."
            isLoading.value = false
            return
        }
        rootTaskId.value = tid

        await loadConfigAndUsers($b24, { includeProfile: true })
        if (config.value?.DEFAULT_SMART_PROCESS_ID) {
            await reloadWorkspace()
        }

    } catch (e: any) {
        processErrorGlobal(e)
        error.value = e.message
        isLoading.value = false
    }
})

// --- COMPUTED ---

const isFilterActive = computed(() =>
    !!filterEmployeeId.value || !!filterDateFrom.value || !!filterDateTo.value
)

const filteredTaskTree = computed(() => {
    return filterTaskTree(taskTree.value, {
        employeeId: filterEmployeeId.value,
        dateFrom: filterDateFrom.value,
        dateTo: filterDateTo.value
    })
})

const totalClientAmount = computed(() => {
    const allItems = flattenTaskItems(filteredTaskTree.value)
    const total = allItems.filter(item => item.isConsidered).reduce((sum, item) => sum + item.hours, 0)
    return (total * clientHourRate.value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
})

function resetFilter() {
    filterEmployeeId.value = ''
    filterDateFrom.value = ''
    filterDateTo.value = ''
}

function assignMappedField(target: Record<string, any>, fieldCode: string | undefined, value: any) {
    if (!fieldCode || value === undefined) {
        return
    }

    target[fieldCode] = value
}

function resolveInnFieldCode(kind: 'OUR_INN' | 'CLIENT_INN'): string {
    if (!config.value) {
        return ''
    }

    return String(
        config.value.SPA_FIELDS?.[kind]
        || config.value.FIELDS?.[kind]
        || ''
    ).trim()
}

function extractCreatedItemId(rawData: any): string | null {
    const result = rawData?.result
    if (!result) {
        return null
    }

    if (typeof result === 'string' || typeof result === 'number') {
        const normalized = String(result).trim()
        return normalized || null
    }

    if (typeof result === 'object') {
        const directId = String(result.id || result.itemId || '').trim()
        if (directId) {
            return directId
        }

        const nestedItemId = String(result.item?.id || result.item?.ID || '').trim()
        if (nestedItemId) {
            return nestedItemId
        }
    }

    return null
}

function resolveTaskTitle(taskId: string | null | undefined, hierarchy?: { titlePath?: string[] | null } | null) {
    const node = findTaskNodeById(taskId, taskTree.value)
    if (node?.taskTitle) {
        return String(node.taskTitle)
    }

    const hierarchyTitles = hierarchy?.titlePath || []
    if (hierarchyTitles.length > 0) {
        return String(hierarchyTitles[hierarchyTitles.length - 1] || '')
    }

    return ''
}

async function resolveTaskTitleSafe(taskId: string | null | undefined, hierarchy?: { titlePath?: string[] | null } | null) {
    const fromTreeOrHierarchy = resolveTaskTitle(taskId, hierarchy)
    if (fromTreeOrHierarchy.trim().length > 0) {
        return fromTreeOrHierarchy.trim()
    }

    const normalizedTaskId = String(taskId || '').trim()
    if (!normalizedTaskId || !$b24) {
        return ''
    }

    try {
        const taskRes = await ($b24 as any).callMethod('tasks.task.get', {
            taskId: normalizedTaskId,
            select: ['ID', 'TITLE'],
        })
        const taskData = taskRes?.getData?.()
        const taskObj = taskData?.result?.task || taskData?.task || null
        const fetchedTitle = String(
            taskObj?.title || taskObj?.TITLE || taskObj?.Title || ''
        ).trim()
        if (fetchedTitle) {
            console.info('[Embedded][TASK_NAME] Fallback title loaded from tasks.task.get', {
                taskId: normalizedTaskId,
                fetchedTitle,
            })
            return fetchedTitle
        }
    } catch (error) {
        console.warn('[Embedded][TASK_NAME] Failed to load title fallback', {
            taskId: normalizedTaskId,
            error,
        })
    }

    return ''
}

function hasMeaningfulValue(value: unknown): boolean {
    if (value === null || value === undefined) {
        return false
    }
    if (typeof value === 'string') {
        return value.trim().length > 0
    }
    return true
}

function validateProjectBindingForSave(
    fields: Record<string, any>,
    hierarchy?: {
        projectId?: string | null
        projectTitle?: string
    } | null
): string | null {
    if (!config.value) {
        return 'Не удалось загрузить конфигурацию приложения.'
    }

    if (!hierarchy?.projectId) {
        return 'Задача не привязана к проектной группе. Списание без проекта запрещено.'
    }

    const projectItemField = config.value.FIELDS.PROJECT_ITEM_ID
    if (!projectItemField) {
        return 'В настройках не задано поле «ID элемента проекта SPA». Обратитесь к администратору.'
    }

    if (!hasMeaningfulValue(fields[projectItemField])) {
        const projectLabel = hierarchy.projectTitle ? `«${hierarchy.projectTitle}»` : `group_id ${hierarchy.projectId}`
        return `Для задачи не найден связанный проект в Project SPA (${projectLabel}). Проверьте связь group_id → project_item_id в карточке проекта.`
    }

    return null
}

async function getProjectCardByProjectId(projectId?: string | null) {
    const normalizedProjectId = String(projectId || '').trim()
    if (!normalizedProjectId) {
        return null
    }

    if (projectCardCache.has(normalizedProjectId)) {
        return projectCardCache.get(normalizedProjectId)
    }

    try {
        const card = await apiStore.getProjectBoardCard(normalizedProjectId)
        if (card) {
            projectCardCache.set(normalizedProjectId, card)
            console.info('[Embedded][INN] Project card loaded', {
                projectId: normalizedProjectId,
                projectItemId: card.project_item_id,
                companyId: card.company_id,
                companyInn: card.company_inn,
                legalEntityId: card.our_legal_entity_id,
                legalEntityInn: card.our_legal_entity_inn,
            })
        } else {
            console.warn('[Embedded][INN] Project card is empty', { projectId: normalizedProjectId })
        }
        return card
    } catch (error) {
        console.warn('[Embedded] Failed to load project card for timestamp binding:', normalizedProjectId, error)
        return null
    }
}

async function enrichFieldsWithProjectContext(
    fields: Record<string, any>,
    taskId: string | null | undefined,
    hierarchy?: {
        idPath?: string[]
        titlePath?: string[]
        projectId?: string | null
        projectTitle?: string
        ourInn?: string
        clientInn?: string
    } | null
) {
    if (!config.value) {
        return
    }

    const taskNameFieldCode = String(config.value.FIELDS?.TASK_NAME || '').trim()
    if (!taskNameFieldCode) {
        console.warn('[Embedded][TASK_NAME] Missing TASK_NAME field mapping', {
            fields: config.value.FIELDS,
        })
    }

    if (hierarchy) {
        const projectCard = hierarchy.projectId ? await getProjectCardByProjectId(hierarchy.projectId) : null
        const projectOurInn = String(projectCard?.our_legal_entity_inn || '').trim()
        const projectClientInn = String(projectCard?.company_inn || '').trim()
        const resolvedOurInn = projectOurInn || String(hierarchy.ourInn || '').trim()
        const resolvedClientInn = projectClientInn || String(hierarchy.clientInn || '').trim()
        const ourInnFieldCode = resolveInnFieldCode('OUR_INN')
        const clientInnFieldCode = resolveInnFieldCode('CLIENT_INN')

        if (!ourInnFieldCode || !clientInnFieldCode) {
            console.warn('[Embedded][INN] Missing INN field mapping', {
                ourInnFieldCode,
                clientInnFieldCode,
                spaFields: config.value.SPA_FIELDS,
                fields: config.value.FIELDS,
            })
        }

        assignMappedField(fields, config.value.FIELDS.TASK_HIERARCHY, hierarchy.idPath)
        assignMappedField(fields, config.value.FIELDS.TITLE_HIERARCHY, hierarchy.titlePath)

        if (hierarchy.projectId) {
            assignMappedField(fields, config.value.FIELDS.PROJECT_ID, hierarchy.projectId)
            assignMappedField(fields, config.value.FIELDS.PROJECT_TITLE, hierarchy.projectTitle)
        }

        const resolvedTaskName = await resolveTaskTitleSafe(taskId, hierarchy)
        assignMappedField(fields, taskNameFieldCode || undefined, resolvedTaskName)
        assignMappedField(fields, ourInnFieldCode || undefined, resolvedOurInn)
        assignMappedField(fields, clientInnFieldCode || undefined, resolvedClientInn)

        if (hierarchy.projectId) {
            const projectItemId = String(projectCard?.project_item_id || '').trim()
            if (projectItemId) {
                assignMappedField(fields, config.value.FIELDS.PROJECT_ITEM_ID, projectItemId)
            }
            const myCompanyId = String(projectCard?.our_legal_entity_id || '').trim()
            if (myCompanyId) {
                fields.mycompanyId = /^\d+$/.test(myCompanyId) ? Number(myCompanyId) : myCompanyId
            }
        }

        console.info('[Embedded][INN] Prepared fields from project context', {
            taskId,
            projectId: hierarchy.projectId || null,
            projectItemId: String(projectCard?.project_item_id || '').trim(),
            taskNameFieldCode,
            resolvedTaskName,
            payloadTaskName: taskNameFieldCode ? fields[taskNameFieldCode] : undefined,
            ourInnFieldCode,
            clientInnFieldCode,
            resolvedOurInn,
            resolvedClientInn,
            payloadOurInn: ourInnFieldCode ? fields[ourInnFieldCode] : undefined,
            payloadClientInn: clientInnFieldCode ? fields[clientInnFieldCode] : undefined,
            mycompanyId: fields.mycompanyId,
        })
        return
    }

    const resolvedTaskName = await resolveTaskTitleSafe(taskId, hierarchy)
    assignMappedField(fields, taskNameFieldCode || undefined, resolvedTaskName)
    console.info('[Embedded][TASK_NAME] Prepared fields without hierarchy', {
        taskId: String(taskId || '').trim(),
        taskNameFieldCode,
        resolvedTaskName,
        payloadTaskName: taskNameFieldCode ? fields[taskNameFieldCode] : undefined,
    })
}

// --- ACTIONS ---

async function getTaskHierarchy(taskId: string) {
    if (!config.value) return null
    
    const idPath: string[] = []
    const titlePath: string[] = []
    let projectId: string | null = null
    let projectTitle = ''
    let ourInn = ''
    let clientInn = ''
    
    try {
            // 1. Get task info (GROUP_ID and INN fields)
        const taskRes = await ($b24 as any).callMethod('tasks.task.get', {
            taskId: taskId,
            select: ['ID', 'TITLE', 'GROUP_ID', config.value.TASK_FIELDS.OUR_INN, config.value.TASK_FIELDS.CLIENT_INN]
        })
        
        const taskData = taskRes.getData()
        // API can return { task: {...} } OR { result: { task: {...} } }
        const taskObj = taskData?.result?.task || taskData?.task
        console.log(`🔍 [Embedded] Hierarchy: taskData keys:`, taskData ? Object.keys(taskData) : 'null', 'taskObj:', !!taskObj)
        if (taskObj) {
            const debugTask = JSON.stringify(taskObj)
            console.log(`🔍 [Embedded] Hierarchy: Initial task ${taskId} raw data:`, debugTask)
            
            // Try all possible cases for GROUP_ID
            const gid = taskObj.groupId || taskObj.group_id || taskObj.GROUP_ID || taskObj.GroupId
            console.log(`🔍 [Embedded] Hierarchy: GROUP_ID candidates:`, { groupId: taskObj.groupId, group_id: taskObj.group_id, GROUP_ID: taskObj.GROUP_ID, GroupId: taskObj.GroupId, resolved: gid })
            if (gid && gid !== '0') {
                projectId = String(gid)
            }
            // Get INN fields
            ourInn = taskObj[config.value.TASK_FIELDS.OUR_INN] || (taskObj.uf && taskObj.uf[config.value.TASK_FIELDS.OUR_INN]) || ''
            clientInn = taskObj[config.value.TASK_FIELDS.CLIENT_INN] || (taskObj.uf && taskObj.uf[config.value.TASK_FIELDS.CLIENT_INN]) || ''
        } else {
             console.warn(`⚠️ [Embedded] Hierarchy: Task ${taskId} not found or no data`)
        }
        
        // 2. Get project/group name if exists
        if (projectId) {
            try {
                const groupRes = await ($b24 as any).callMethod('sonet_group.get', {
                    FILTER: { ID: projectId }
                })
                const groupData = groupRes.getData()
                if (groupData && groupData[0]) {
                    projectTitle = groupData[0].NAME
                } else if (groupData && groupData.result && groupData.result[0]) {
                     projectTitle = groupData.result[0].NAME
                }
            } catch (e) {
                console.error('[Embedded] Error getting group:', e)
            }
        }
        
        // 3. Collect hierarchy (from task up to root)
        let currentTaskId: string | null = taskId
        let loopCount = 0
        
        while (currentTaskId && loopCount < 20) { // Safety break
            try {
                const result = await ($b24 as any).callMethod('tasks.task.get', {
                    taskId: currentTaskId,
                    select: ['ID', 'TITLE', 'PARENT_ID']
                })
                const data = result.getData()
                const task = data.task || data.result?.task
                
                if (task) {
                    const tid = task.id || task.ID || task.Id
                    const ttitle = task.title || task.TITLE || task.Title
                    const tparent: any = task.parentId || task.parent_id || task.PARENT_ID || task.ParentId
                    
                    if (tid) idPath.unshift(String(tid))
                    if (ttitle) titlePath.unshift(String(ttitle))
                    
                    if (tparent && tparent !== '0') {
                        currentTaskId = String(tparent)
                    } else {
                        currentTaskId = null
                    }
                } else {
                    currentTaskId = null
                }
            } catch (e) {
                console.error(`[Embedded] Error getting task ${currentTaskId}:`, e)
                currentTaskId = null
            }
            // Output current step
            console.log(`🔍 [Embedded] Hierarchy step: path length ${idPath.length}, next parent: ${currentTaskId}`)
            loopCount++
        }
        
        console.log('✅ [Embedded] Hierarchy collected FINAL:', { 
            idPath, 
            titlePath, 
            projectId, 
            projectTitle,
            ourInn: !!ourInn,
            clientInn: !!clientInn
        })

        return {
            idPath,
            titlePath,
            projectId,
            projectTitle,
            ourInn,
            clientInn
        }

    } catch (e) {
        console.error('[Embedded] Error in getTaskHierarchy:', e)
        return null
    }
}

function toggleTask(taskId: string) {
    if (expandedTasks.value.has(taskId)) {
        expandedTasks.value.delete(taskId)
    } else {
        expandedTasks.value.add(taskId)
    }
}

function selectItem(item: any) {
    currentEditingId.value = item.id
    const taskId = findTaskIdForItem(item.id, taskTree.value)
    editingItem.value = { ...item, taskId, splitHours: 0, splitInvert: false }
}

function closeEditor() {
    currentEditingId.value = null
    editingItem.value = null
}

function createNewEntry() {
    if (!rootTaskId.value) return
    
    // Create new entry template
    const newEntry = {
        id: null, // null means it's a new entry
        taskId: rootTaskId.value,
        description: '',
        employeeId: currentUserId.value || usersList.value[0]?.ID || '',
        date: new Date().toISOString().split('T')[0],
        hours: 1,
        isConsidered: true,
        splitHours: 0.5,
        keepOriginalConsidered: false
    }
    
    editingItem.value = newEntry
    currentEditingId.value = 'new'
}



function createEntryForTask(taskId: string) {
    console.log(`🔘 [Embedded] createEntryForTask clicked for taskId: ${taskId}`)
    const newEntry = {
        id: null,
        taskId: taskId,
        description: '',
        employeeId: currentUserId.value || usersList.value[0]?.ID || '',
        date: new Date().toISOString().split('T')[0],
        hours: 1,
        isConsidered: true,
        splitHours: 0.5,
        keepOriginalConsidered: false
    }
    
    editingItem.value = newEntry
    currentEditingId.value = 'new'
}

async function saveCurrentItem() {
    if (!editingItem.value || !config.value) return
    isLoading.value = true
    
    try {
        const taskIdToSave = editingItem.value.taskId ||  rootTaskId.value
        
        // Base fields
        const fields: any = {
            [config.value.FIELDS.HOURS]: editingItem.value.hours,
            [config.value.FIELDS.IS_CONSIDERED]: editingItem.value.isConsidered ? 'Y' : 'N',
            [config.value.FIELDS.DESCRIPTION]: editingItem.value.description,
            [config.value.FIELDS.EMPLOYEE]: editingItem.value.employeeId,
            [config.value.FIELDS.DATE]: editingItem.value.date,
            [config.value.FIELDS.TASK_ID]: taskIdToSave,
            TITLE: editingItem.value.description.substring(0, 255)
        }
        
        // Always collect hierarchy (for both new and existing entries)
        let hierarchy: Awaited<ReturnType<typeof getTaskHierarchy>> | null = null
        if (taskIdToSave) {
            hierarchy = await getTaskHierarchy(taskIdToSave)
            await enrichFieldsWithProjectContext(fields, taskIdToSave, hierarchy)
        }
        const bindingError = validateProjectBindingForSave(fields, hierarchy)
        if (bindingError) {
            alert(`⚠️ ${bindingError}`)
            isLoading.value = false
            return
        }
        
        if (editingItem.value.id) {
            // Update existing
            console.log('💾 [Embedded] Updating item fields:', fields)
            console.info('[Embedded][INN] Save payload summary', {
                mode: 'update',
                itemId: editingItem.value.id,
                taskId: taskIdToSave,
                taskNameFieldCode: String(config.value.FIELDS?.TASK_NAME || '').trim(),
                payloadTaskName: fields[String(config.value.FIELDS?.TASK_NAME || '').trim()],
                ourInnFieldCode: resolveInnFieldCode('OUR_INN'),
                clientInnFieldCode: resolveInnFieldCode('CLIENT_INN'),
                payloadOurInn: fields[resolveInnFieldCode('OUR_INN')],
                payloadClientInn: fields[resolveInnFieldCode('CLIENT_INN')],
                payloadMycompanyId: fields.mycompanyId,
                projectItemFieldCode: config.value.FIELDS.PROJECT_ITEM_ID,
                payloadProjectItemId: fields[config.value.FIELDS.PROJECT_ITEM_ID],
            })
            await ($b24 as any).callMethod('crm.item.update', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                id: editingItem.value.id,
                fields: fields
            })
        } else {
            // Create new
            console.log('💾 [Embedded] Creating new item fields:', fields)
            console.info('[Embedded][INN] Save payload summary', {
                mode: 'create',
                taskId: taskIdToSave,
                taskNameFieldCode: String(config.value.FIELDS?.TASK_NAME || '').trim(),
                payloadTaskName: fields[String(config.value.FIELDS?.TASK_NAME || '').trim()],
                ourInnFieldCode: resolveInnFieldCode('OUR_INN'),
                clientInnFieldCode: resolveInnFieldCode('CLIENT_INN'),
                payloadOurInn: fields[resolveInnFieldCode('OUR_INN')],
                payloadClientInn: fields[resolveInnFieldCode('CLIENT_INN')],
                payloadMycompanyId: fields.mycompanyId,
                projectItemFieldCode: config.value.FIELDS.PROJECT_ITEM_ID,
                payloadProjectItemId: fields[config.value.FIELDS.PROJECT_ITEM_ID],
            })
            const createRes = await ($b24 as any).callMethod('crm.item.add', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                fields: fields
            })
            const createdItemId = extractCreatedItemId(createRes?.getData?.())
            console.info('[Embedded][INN] Create result', {
                createdItemId,
                rawResult: createRes?.getData?.()?.result,
            })

            const ourInnFieldCode = resolveInnFieldCode('OUR_INN')
            const clientInnFieldCode = resolveInnFieldCode('CLIENT_INN')
            if (createdItemId && (ourInnFieldCode || clientInnFieldCode)) {
                try {
                    const verifyRes = await ($b24 as any).callMethod('crm.item.get', {
                        entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                        id: createdItemId,
                    })
                    const verifyItem = verifyRes?.getData?.()?.result?.item || verifyRes?.getData?.()?.item || {}
                    console.info('[Embedded][INN] Verify saved item', {
                        createdItemId,
                        taskNameFieldCode: String(config.value.FIELDS?.TASK_NAME || '').trim(),
                        savedTaskName: verifyItem?.[String(config.value.FIELDS?.TASK_NAME || '').trim()],
                        ourInnFieldCode,
                        clientInnFieldCode,
                        savedOurInn: ourInnFieldCode ? verifyItem?.[ourInnFieldCode] : undefined,
                        savedClientInn: clientInnFieldCode ? verifyItem?.[clientInnFieldCode] : undefined,
                        savedMycompanyId: verifyItem?.mycompanyId,
                    })
                } catch (verifyError) {
                    console.warn('[Embedded][INN] Failed to verify created item', {
                        createdItemId,
                        error: verifyError,
                    })
                }
            }
        }
        
        await reloadWorkspace()
        closeEditor()
    } catch (e: any) {
        alert("Ошибка сохранения: " + e.message)
        isLoading.value = false
    }
}

async function splitItem() {
    if (!editingItem.value || !config.value) return
    
    const splitHours = parseFloat(editingItem.value.splitHours) || 0
    if (splitHours <= 0 || splitHours >= editingItem.value.hours) {
        alert('⚠️ Некорректное значение для разделения')
        return
    }

    isLoading.value = true
    try {
        // Update original
        const remainingHours = editingItem.value.hours - splitHours
        await ($b24 as any).callMethod('crm.item.update', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: editingItem.value.id,
            fields: { [config.value.FIELDS.HOURS]: remainingHours }
        })

        // Create new split entry with full hierarchy
        const newConsidered = editingItem.value.splitInvert ? !editingItem.value.isConsidered : editingItem.value.isConsidered
        const splitTaskId = findTaskIdForItem(editingItem.value.id, taskTree.value)
        if (!splitTaskId) {
            alert('⚠️ Не удалось определить задачу для разделяемой записи.')
            isLoading.value = false
            return
        }
        
        const splitFields: any = {
            TITLE: editingItem.value.description + ' (разделено)',
            [config.value.FIELDS.HOURS]: splitHours,
            [config.value.FIELDS.IS_CONSIDERED]: newConsidered ? 'Y' : 'N',
            [config.value.FIELDS.DESCRIPTION]: editingItem.value.description + ' (разделено)',
            [config.value.FIELDS.EMPLOYEE]: editingItem.value.employeeId,
            [config.value.FIELDS.DATE]: editingItem.value.date,
            [config.value.FIELDS.TASK_ID]: splitTaskId
        }
        
        // Collect hierarchy for the split entry
        const hierarchy = await getTaskHierarchy(splitTaskId)
        await enrichFieldsWithProjectContext(splitFields, splitTaskId, hierarchy)
        const bindingError = validateProjectBindingForSave(splitFields, hierarchy)
        if (bindingError) {
            alert(`⚠️ ${bindingError}`)
            isLoading.value = false
            return
        }

        await ($b24 as any).callMethod('crm.item.add', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            fields: splitFields
        })
        console.info('[Embedded][INN] Split create payload summary', {
            splitTaskId,
            ourInnFieldCode: resolveInnFieldCode('OUR_INN'),
            clientInnFieldCode: resolveInnFieldCode('CLIENT_INN'),
            payloadOurInn: splitFields[resolveInnFieldCode('OUR_INN')],
            payloadClientInn: splitFields[resolveInnFieldCode('CLIENT_INN')],
            payloadMycompanyId: splitFields.mycompanyId,
            projectItemFieldCode: config.value.FIELDS.PROJECT_ITEM_ID,
            payloadProjectItemId: splitFields[config.value.FIELDS.PROJECT_ITEM_ID],
        })

        await reloadWorkspace()
        closeEditor()
    } catch (e: any) {
        alert("Ошибка разделения: " + e.message)
        isLoading.value = false
    }
}

async function deleteItem() {
    if (!editingItem.value || !config.value) return
    if (!confirm('❌ Удалить запись?')) return

    isLoading.value = true
    try {
        await ($b24 as any).callMethod('crm.item.delete', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: editingItem.value.id
        })
        await reloadWorkspace()
        closeEditor()
    } catch (e: any) {
        alert("Ошибка удаления: " + e.message)
        isLoading.value = false
    }
}

async function deleteItemDirect(item: any) {
    if (!config.value || !item?.id) return
    const label = item.description ? `«${item.description.substring(0, 60)}»` : `#${item.id}`
    if (!confirm(`Удалить запись ${label}?`)) return

    isLoading.value = true
    try {
        await ($b24 as any).callMethod('crm.item.delete', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: item.id
        })
        // If this item was open in the editor — close it
        if (currentEditingId.value === item.id) closeEditor()
        await reloadWorkspace()
    } catch (e: any) {
        alert("Ошибка удаления: " + e.message)
        isLoading.value = false
    }
}

</script>

<template>
<div class="ms-page-shell embedded-shell">
    <section class="ms-surface embedded-topbar">
        <div class="embedded-topbar__title">
            <div class="embedded-icon">
                <span class="material-symbols-outlined text-[26px]">schedule</span>
            </div>
            <div class="min-w-0">
                <div class="ms-eyebrow">Task Workspace</div>
                <h1 class="mt-2 text-2xl font-semibold text-slate-900">Учет часов</h1>
                <p class="mt-1 text-sm text-slate-500">Учет трудозатрат по иерархии задач.</p>
            </div>
        </div>

        <div class="embedded-topbar__actions">
            <button @click="createNewEntry" class="embedded-primary-btn">
                <span class="material-symbols-outlined">add</span>
                <span>Отразить</span>
            </button>

            <div class="embedded-summary">
                <label class="embedded-summary__card">
                    <span class="embedded-summary__label">Стоимость часа</span>
                    <input type="number" v-model="clientHourRate" class="embedded-rate-input">
                </label>
                <div class="embedded-summary__card embedded-summary__card--accent">
                    <span class="embedded-summary__label">Сумма для клиента</span>
                    <span class="embedded-summary__value">{{ totalClientAmount }} руб.</span>
                </div>
            </div>
        </div>
    </section>

    <section v-if="isLoading" class="ms-surface embedded-state">
        <div class="embedded-state__content">
            <span class="material-symbols-outlined text-5xl animate-spin text-lime-600">progress_activity</span>
            <div class="text-base font-semibold text-slate-900">Загрузка данных</div>
            <p class="text-sm text-slate-500">Получаем задачи и записи времени.</p>
        </div>
    </section>

    <section v-else-if="error" class="ms-surface embedded-state">
        <div class="embedded-state__content">
            <div class="rounded-2xl bg-rose-100 p-3 text-rose-600">
                <span class="material-symbols-outlined text-4xl">error</span>
            </div>
            <div class="text-base font-semibold text-slate-900">Ошибка загрузки</div>
            <p class="max-w-lg text-sm leading-6 text-slate-600">{{ error }}</p>
        </div>
    </section>

    <div v-else class="embedded-grid">
        <section class="ms-surface embedded-left-pane">
            <div class="ms-filter-wrap embedded-filter-bar">
                <div class="flex min-w-[180px] flex-1 flex-col gap-1">
                    <label class="embedded-filter-label">Сотрудник</label>
                    <select v-model="filterEmployeeId">
                        <option value="">Все сотрудники</option>
                        <option v-for="u in usersList" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                    </select>
                </div>
                <div class="flex flex-col gap-1">
                    <label class="embedded-filter-label">Дата от</label>
                    <input type="date" v-model="filterDateFrom">
                </div>
                <div class="flex flex-col gap-1">
                    <label class="embedded-filter-label">Дата до</label>
                    <input type="date" v-model="filterDateTo">
                </div>
                <button
                    v-if="isFilterActive"
                    @click="resetFilter"
                    class="embedded-secondary-btn"
                >
                    <span class="material-symbols-outlined text-base">filter_alt_off</span>
                    Сбросить
                </button>
                <div v-if="isFilterActive" class="embedded-filter-state">
                    <span class="material-symbols-outlined text-sm">filter_alt</span>
                    Фильтр активен
                </div>
            </div>

            <div class="embedded-tree-scroll">
                <TaskGroupComponent 
                    v-for="task in filteredTaskTree" 
                    :key="task.taskId"
                    :task="task"
                    :level="0"
                    :clientHourRate="clientHourRate"
                    :expandedTasks="expandedTasks"
                    :currentEditingId="currentEditingId"
                    @toggle="toggleTask"
                    @select="selectItem"
                    @createForTask="createEntryForTask"
                    @delete="deleteItemDirect"
                />
            </div>
        </section>

        <aside class="ms-surface embedded-editor-pane">
            <div class="embedded-editor-header">
                <div>
                    <h2 class="text-lg font-semibold text-slate-900">Редактирование</h2>
                    <p class="mt-1 text-xs text-slate-500">Поля записи и дополнительные действия.</p>
                </div>
                <button @click="closeEditor" class="embedded-icon-btn">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>

            <div v-if="!editingItem" class="embedded-editor-empty">
                <div class="space-y-2 text-center">
                    <div class="mx-auto inline-flex rounded-2xl bg-slate-100 p-3 text-slate-400">
                        <span class="material-symbols-outlined text-4xl">touch_app</span>
                    </div>
                    <div class="text-sm font-medium text-slate-700">Выберите запись для редактирования</div>
                    <p class="text-xs leading-5 text-slate-500">Левая колонка показывает дерево задач и все связанные записи времени.</p>
                </div>
            </div>

            <div v-else class="embedded-editor-body">
                <div>
                    <label class="embedded-filter-label">Описание</label>
                    <textarea v-model="editingItem.description" rows="2" class="resize-none"></textarea>
                </div>
                <div>
                    <label class="embedded-filter-label">Сотрудник</label>
                    <select v-model="editingItem.employeeId" class="bg-white">
                        <option v-for="u in usersList" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                    </select>
                </div>
                <div class="grid gap-4 sm:grid-cols-2">
                    <div>
                        <label class="embedded-filter-label">Дата</label>
                        <input type="date" v-model="editingItem.date">
                    </div>
                    <div>
                        <label class="embedded-filter-label">Часы</label>
                        <input type="number" v-model.number="editingItem.hours" step="0.25" min="0" class="font-semibold">
                    </div>
                </div>

                <label class="embedded-toggle">
                    <span class="text-sm font-medium text-slate-700">Учитывать в аналитике</span>
                    <input type="checkbox" v-model="editingItem.isConsidered" class="h-4 w-4 accent-lime-600">
                </label>

                <div class="embedded-split-card">
                    <h3 class="flex items-center gap-2 text-sm font-semibold text-slate-900">
                        <span class="material-symbols-outlined text-slate-500">call_split</span>
                        Разделить запись
                    </h3>
                    <p class="mt-2 text-xs leading-5 text-slate-500">Отделите часть времени в новую запись, если нужно разнести ее отдельно.</p>
                    <div class="mt-4 grid grid-cols-[120px_1fr] gap-2">
                        <input type="number" v-model="editingItem.splitHours" step="0.5" placeholder="0">
                        <div class="flex items-center text-xs text-slate-500">часов отделить</div>
                    </div>
                    <label class="mt-3 flex items-center gap-2 text-xs text-slate-600">
                        <input type="checkbox" v-model="editingItem.splitInvert" class="h-3.5 w-3.5 accent-slate-700">
                        <span>Инвертировать признак «Учитывать»</span>
                    </label>
                    <button @click="splitItem" class="embedded-secondary-btn mt-4 w-full justify-center">Выполнить разделение</button>
                </div>

                <button v-if="editingItem.id" @click="deleteItem" class="embedded-danger-btn">
                    <span class="material-symbols-outlined text-base">delete</span>
                    Удалить запись
                </button>
            </div>

            <div v-if="editingItem" class="embedded-editor-footer">
                <button @click="closeEditor" class="embedded-secondary-btn">Отмена</button>
                <button @click="saveCurrentItem" class="embedded-primary-btn">Сохранить</button>
            </div>
        </aside>
    </div>

    <HelpSidePanel v-model="isHelpOpen" />
</div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

.embedded-shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
    overflow: hidden;
}

.embedded-topbar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 18px 20px;
}

.embedded-topbar__title {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    min-width: 0;
}

.embedded-topbar__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 12px;
}

.embedded-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    border-radius: 18px;
    background: #d9f99d;
    color: #4d7c0f;
}

.embedded-summary {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

.embedded-summary__card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 156px;
    border: 1px solid rgba(216, 226, 238, 0.95);
    border-radius: 18px;
    background: #fff;
    padding: 12px 14px;
}

.embedded-summary__card--accent {
    background: linear-gradient(180deg, rgba(248, 250, 252, 1), rgba(238, 248, 200, 0.55));
}

.embedded-summary__label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #64748b;
}

.embedded-summary__value {
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
}

.embedded-rate-input {
    width: 100%;
    border: 0;
    background: transparent;
    padding: 0;
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
    outline: none;
    box-shadow: none;
}

.embedded-rate-input:focus {
    border: 0;
    box-shadow: none;
    ring: 0;
}

.embedded-primary-btn,
.embedded-secondary-btn,
.embedded-danger-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-radius: 14px;
    padding: 10px 15px;
    font-size: 14px;
    font-weight: 600;
    transition: 180ms ease;
}

.embedded-primary-btn {
    background: #b7ea2c;
    color: #0f172a;
    box-shadow: 0 10px 24px rgba(183, 234, 44, 0.28);
}

.embedded-primary-btn:hover {
    background: #c7f04f;
}

.embedded-secondary-btn {
    border: 1px solid rgba(203, 213, 225, 0.95);
    background: #fff;
    color: #334155;
}

.embedded-secondary-btn:hover {
    border-color: rgba(148, 163, 184, 0.95);
    color: #0f172a;
}

.embedded-danger-btn {
    justify-content: center;
    border: 1px solid rgba(254, 205, 211, 0.95);
    background: #fff1f2;
    color: #be123c;
}

.embedded-danger-btn:hover {
    background: #ffe4e6;
}

.embedded-state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 300px;
}

.embedded-state__content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    text-align: center;
}

.embedded-grid {
    display: grid;
    flex: 1;
    gap: 12px;
    grid-template-columns: minmax(0, 1fr) 380px;
    min-height: 0;
}

.embedded-left-pane,
.embedded-editor-pane {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
}

.embedded-filter-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 12px;
    margin: 12px;
    margin-bottom: 0;
}

.embedded-filter-label {
    display: block;
    margin-bottom: 6px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #64748b;
}

.embedded-filter-state {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
    font-size: 12px;
    font-weight: 600;
    color: #4d7c0f;
}

.embedded-tree-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 12px;
}

.embedded-editor-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 18px 18px 14px;
    border-bottom: 1px solid rgba(226, 232, 240, 0.95);
    background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.82));
}

.embedded-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: 12px;
    color: #94a3b8;
    transition: 180ms ease;
}

.embedded-icon-btn:hover {
    background: #f1f5f9;
    color: #334155;
}

.embedded-editor-empty {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    padding: 24px;
}

.embedded-editor-body {
    display: flex;
    flex: 1;
    min-height: 0;
    flex-direction: column;
    gap: 16px;
    overflow-y: auto;
    padding: 18px;
}

.embedded-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    border: 1px solid rgba(216, 226, 238, 0.95);
    border-radius: 16px;
    background: #f8fafc;
    padding: 12px 14px;
}

.embedded-split-card {
    border: 1px solid rgba(226, 232, 240, 0.95);
    border-radius: 20px;
    background: linear-gradient(180deg, rgba(248, 250, 252, 1), rgba(241, 245, 249, 0.88));
    padding: 16px;
}

.embedded-editor-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 18px;
    border-top: 1px solid rgba(226, 232, 240, 0.95);
    background: #f8fafc;
}

@media (max-width: 1100px) {
    .embedded-shell {
        min-height: 100vh;
        overflow: visible;
    }

    .embedded-grid {
        grid-template-columns: 1fr;
        flex: initial;
    }

    .embedded-left-pane {
        min-height: 420px;
    }

    .embedded-editor-pane {
        min-height: 420px;
    }

    .embedded-tree-scroll {
        flex: initial;
        min-height: 320px;
    }
}
</style>
