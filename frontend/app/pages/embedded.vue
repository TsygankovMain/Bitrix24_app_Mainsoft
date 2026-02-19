<script setup lang="ts">
import { useFieldConfigStore } from '@/stores/fieldConfig'
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'

import HelpSidePanel from '@/components/HelpSidePanel.vue'

const { $logger, initApp, processErrorGlobal } = useAppInit('EmbeddedPage')
const { $initializeB24Frame } = useNuxtApp()
const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()

// --- STATE ---
const isHelpOpen = ref(false)


import { requestIframeFullHeight, requestIframeAutoHeight } from '@/utils/iframe-resizer'

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

// Watch for closing to reset height
watch(isHelpOpen, (newVal) => {
    if (!newVal) {
        // Delay slightly to allow transition
        setTimeout(() => requestIframeAutoHeight(), 300)
    }
})


let $b24: null | B24Frame = null
const fieldConfigStore = useFieldConfigStore()

// --- STATE ---
const isLoading = ref(true)
const error = ref<string | null>(null)

// Computed config from store
const config = computed(() => fieldConfigStore.configObject)

const rootTaskId = ref<string | null>(null)
const taskTree = ref<any[]>([])
const expandedTasks = ref<Set<string>>(new Set())
const usersMap = ref<Record<string, any>>({})

// Global hourly rate from store
const clientHourRate = computed(() => fieldConfigStore.hourlyRate)

const currentEditingId = ref<string | null>(null)
const editingItem = ref<any>(null)
const currentUserId = ref<string | null>(null)

// Config mapping is now in stores/fieldConfig.ts

// Computed properties
const usersList = computed(() => Object.values(usersMap.value))

// --- INITIALIZATION ---
onMounted(async () => {

    // Diagnostics
    const isInIframe = window.self !== window.top
    const hasBX24 = typeof (window as any).BX24 !== 'undefined'
    
    console.info('[Diagnostics] Env:', { isInIframe, hasBX24 })
    
    // Check if we can open native slider
    // @ts-ignore
    if (hasBX24 && typeof window.BX24.openApplication === 'function') {
        console.info('[Diagnostics] Native SidePanel (openApplication) is AVAILABLE')
        isNativeSidePanelAvailable.value = true
    } else {
        console.warn('[Diagnostics] Native SidePanel is NOT available')
    }

    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)

        // Get task ID from placement
        let options = ($b24 as any).placement?.options || (($b24 as any).placement?.info && ($b24 as any).placement.info.options)
        
        if (!options && typeof (window as any).BX24 !== 'undefined') {
            try {
                const rawInfo = (window as any).BX24.placement.info()
                if (rawInfo) options = rawInfo.options
            } catch(e) { console.warn('BX24.placement.info failed', e) }
        }

        const tid = options?.taskId || options?.ID || options?.id
        if (!tid) {
            error.value = "Не передан ID задачи. Откройте приложение во вкладке задачи."
            isLoading.value = false
            return
        }
        rootTaskId.value = tid

        await loadConfigAndUsers()
        if (config.value) {
            await loadData(rootTaskId.value!)
        }

    } catch (e: any) {
        processErrorGlobal(e)
        error.value = e.message
        isLoading.value = false
    }
})

async function loadConfigAndUsers() {
    const result = await ($b24 as any).callBatch({
        users: { method: 'user.get', params: { FILTER: { 'ACTIVE': 'Y' }, 'sort': 'LAST_NAME', 'order': 'ASC' } },
        profile: { method: 'profile' }
    })

    const data = result.getData()

    // Users
    if (data.users && !data.users.error) {
        const map: Record<string, any> = {}
        // BX24 user.get returns array in 'result' property
        console.log('📦 [Embedded] Full users response:', data.users)
        const usersData = data.users.result || data.users.data || data.users
        
        console.log('👥 [Embedded] Users data extracted:', usersData)
        if (Array.isArray(usersData)) {
            usersData.forEach((u: any) => {
                // Ensure ID is string
                const uid = String(u.ID)
                map[uid] = u
            })
            usersMap.value = map
            console.log('✅ [Embedded] Users loaded:', Object.keys(map).length)
        }
    } else {
        console.error('❌ [Embedded] Error loading users:', data.users?.error)
    }

    // Profile - get current user ID
    if (data.profile && !data.profile.error) {
        const profileData = data.profile.result || data.profile.data || data.profile
        if (profileData && profileData.ID) {
            currentUserId.value = String(profileData.ID)
            console.log('✅ [Embedded] Current user ID:', currentUserId.value)
        }
    }

    // HARDCODED Config (from Application_Documentation.md)
    // NOW: Dynamic config from app.option.get via fieldConfigStore
    await fieldConfigStore.loadFromB24($b24!)
    
    if (fieldConfigStore.isConfigured) {
        // config is computed now
        console.log('✅ [Embedded] Config loaded from app.option', config.value)
    } else {
        console.error('❌ [Embedded] Config not found or incomplete:', fieldConfigStore.loadError)
        error.value = fieldConfigStore.loadError || 'Конфигурация не найдена. Зайдите в Настройки → Маппинг и настройте поля.'
    }
}

async function loadData(taskId: string) {
    if (!config.value) return
    isLoading.value = true
    error.value = null

    const FIELDS = config.value.FIELDS
    const SMART_PROCESS_ID = config.value.DEFAULT_SMART_PROCESS_ID

    try {
        // 1. Root Task
        console.log('🔍 [Embedded] Loading root task:', taskId)
        const rootTaskRes = await ($b24 as any).callMethod('tasks.task.get', { taskId, select: ['ID', 'TITLE'] })
        console.log('📦 [Embedded] rootTaskRes =', rootTaskRes)
        
        const rootTaskData = rootTaskRes.getData()
        console.log('📦 [Embedded] rootTaskData =', rootTaskData)
        
        // API returns: { result: { task: { id, title } } }
        const rootTask = rootTaskData.result?.task || rootTaskData.task
        console.log('📦 [Embedded] rootTask =', rootTask)
        
        if (!rootTask || !rootTask.id) {
            throw new Error('Не удалось загрузить данные корневой задачи. Ответ API: ' + JSON.stringify(rootTaskData))
        }

        // 2. BFS Subtasks
        let allTasks = [{ id: rootTask.id, title: rootTask.title, parentId: null }]
        let queue = [rootTask.id]
        let processed = new Set([rootTask.id])
        
        let iterations = 0
        while(queue.length > 0 && iterations < 50) {
            const batch: any = {}
            const currentLevelIds = queue.splice(0, 50)
            
            currentLevelIds.forEach(pid => {
                batch[`tasks_${pid}`] = { 
                    method: 'tasks.task.list', 
                    params: { filter: { PARENT_ID: pid }, select: ['ID', 'TITLE', 'PARENT_ID'] } 
                }
            })

            if (Object.keys(batch).length === 0) break

            console.log(`🔄 [Embedded] Calling batch for ${currentLevelIds.length} parent IDs:`, currentLevelIds)
            const batchResult = await ($b24 as any).callBatch(batch)
            const batchData = batchResult.getData()
            console.log(`📦 [Embedded] Full batch response:`, batchData)
            
            Object.entries(batchData).forEach(([key, res]: [string, any]) => {
                console.log(`🔍 [Embedded] Processing batch key: ${key}`)
                console.log(`📋 [Embedded] Response for ${key}:`, res)
                
                if (!res.error) {
                    // API can return: { result: { tasks: [...] } } OR { tasks: [...] } directly
                    const tasks = res.result?.tasks || res.data?.tasks || res.tasks || []
                    console.log(`📋 [Embedded] Found ${tasks.length} tasks in response`)
                    
                    if (tasks.length > 0) {
                        console.log(`📋 [Embedded] First task structure:`, tasks[0])
                    }
                    
                    tasks.forEach((t: any) => {
                        // API fields are UPPERCASE: ID, TITLE, PARENT_ID
                        const taskId = t.ID || t.id
                        const taskTitle = t.TITLE || t.title
                        const taskParentId = t.PARENT_ID || t.parentId
                        
                        if (!processed.has(taskId)) {
                            processed.add(taskId)
                            allTasks.push({ id: taskId, title: taskTitle, parentId: taskParentId })
                            queue.push(taskId)
                            console.log(`➕ [Embedded] Added subtask: ${taskId} - ${taskTitle} (parent: ${taskParentId})`)
                        }
                    })
                } else {
                    console.error(`❌ [Embedded] Error in batch response for ${key}:`, res.error)
                }
            })
            iterations++
        }

        // 3. Load Items
        const allTaskIds = allTasks.map(t => t.id)
        console.log(`⏱️ [Embedded] Loading time entries for ${allTaskIds.length} tasks:`, allTaskIds)
        console.log(`⏱️ [Embedded] Using entityTypeId: ${SMART_PROCESS_ID}, TASK_ID field: ${FIELDS.TASK_ID}`)
        
        const CHUNK_SIZE = 50
        let allItems: any[] = []

        for (let i = 0; i < allTaskIds.length; i += CHUNK_SIZE) {
            const chunk = allTaskIds.slice(i, i + CHUNK_SIZE)
            const batchCmds: any = {}
            
            chunk.forEach(tid => {
                batchCmds[`items_${tid}`] = {
                    method: 'crm.item.list',
                    params: { 
                        entityTypeId: SMART_PROCESS_ID,
                        filter: { [FIELDS.TASK_ID]: tid },
                        select: ['id', 'createdTime', FIELDS.TASK_ID, FIELDS.EMPLOYEE, FIELDS.HOURS, FIELDS.IS_CONSIDERED, FIELDS.DESCRIPTION, 'TITLE', FIELDS.DATE]
                    }
                }
            })
            
            console.log(`⏱️ [Embedded] Batch commands for CRM items:`, batchCmds)
            const chunkResult = await ($b24 as any).callBatch(batchCmds)
            const chunkData = chunkResult.getData()
            console.log(`📦 [Embedded] CRM items batch response:`, chunkData)

            Object.entries(chunkData).forEach(([key, res]: [string, any]) => {
                console.log(`🔍 [Embedded] Processing CRM batch key: ${key}`)
                console.log(`📋 [Embedded] CRM response for ${key}:`, res)
                
                if(!res.error) {
                    // API can return: { result: { items: [...] } } OR { items: [...] } directly
                    const items = res.result?.items || res.data?.items || res.items || []
                    console.log(`📋 [Embedded] Found ${items.length} items in response`)
                    
                    if (items.length > 0) {
                        console.log(`📋 [Embedded] First item structure:`, items[0])
                    }
                    
                    allItems.push(...items)
                } else {
                    console.error(`❌ [Embedded] Error in CRM batch response for ${key}:`, res.error)
                }
            })
        }

        // 4. Build Tree
        const nodesMap: Record<string, any> = {}
        allTasks.forEach(t => {
            nodesMap[t.id] = {
                taskId: t.id,
                taskTitle: t.title,
                parentId: t.parentId,
                children: [],
                items: [],
                totalConsidered: 0, 
                totalUnconsidered: 0,
                cumulativeConsidered: 0,
                cumulativeUnconsidered: 0
            }
        })

        allItems.forEach(item => {
            const tid = item[FIELDS.TASK_ID]
            if (nodesMap[tid]) {
                const hours = parseFloat(item[FIELDS.HOURS]) || 0
                const isConsidered = item[FIELDS.IS_CONSIDERED] === 'Y' || item[FIELDS.IS_CONSIDERED] === true
                const empId = item[FIELDS.EMPLOYEE]
                
                // Force string comparison for user lookup
                const u = usersMap.value[String(empId)]
                const empName = u ? `${u.NAME} ${u.LAST_NAME}` : `User ${empId}`

                let dateVal = item[FIELDS.DATE]
                if (!dateVal && item.createdTime) {
                    dateVal = item.createdTime.split('T')[0]
                }

                nodesMap[tid].items.push({
                    id: item.id,
                    title: item.title,
                    createdTime: item.createdTime,
                    hours: hours,
                    isConsidered: isConsidered,
                    description: item[FIELDS.DESCRIPTION] || '',
                    employeeId: empId,
                    employeeName: empName,
                    date: dateVal
                })
                
                if (isConsidered) nodesMap[tid].totalConsidered += hours
                else nodesMap[tid].totalUnconsidered += hours
            }
        })

        console.log('🌳 [Embedded] All tasks loaded:', allTasks.length)
        console.log('🌳 [Embedded] All items loaded:', allItems.length)

        const roots: any[] = []
        Object.values(nodesMap).forEach(node => {
            if (node.parentId && nodesMap[node.parentId]) {
                nodesMap[node.parentId].children.push(node)
                console.log(`📎 [Embedded] Task ${node.taskId} is child of ${node.parentId}`)
            } else if (String(node.taskId) === String(taskId)) {
                roots.push(node) 
                console.log(`🌲 [Embedded] Task ${node.taskId} is ROOT`)
            }
        })

        console.log('🌲 [Embedded] Roots found:', roots.length)
        console.log('🌲 [Embedded] Root tasks:', roots.map(r => ({ id: r.taskId, title: r.taskTitle, children: r.children.length })))

        const calculateTotals = (node: any) => {
            let childCons = 0
            let childUncons = 0
            node.children.forEach((child: any) => {
                const res = calculateTotals(child)
                childCons += res.cons
                childUncons += res.uncons
            })
            node.cumulativeConsidered = node.totalConsidered + childCons
            node.cumulativeUnconsidered = node.totalUnconsidered + childUncons
            return { cons: node.cumulativeConsidered, uncons: node.cumulativeUnconsidered }
        }
        
        roots.forEach(calculateTotals)

        taskTree.value = roots
        expandedTasks.value = new Set([rootTaskId.value!])
        console.log('✅ [Embedded] Task tree built:', taskTree.value)
        isLoading.value = false

    } catch (e: any) {
        console.error(e)
        error.value = e.message || e.toString()
        isLoading.value = false
    }
}

// --- COMPUTED ---
const totalClientAmount = computed(() => {
    let total = 0
    const getAllItems = (nodes: any[]): any[] => {
        let result: any[] = []
        nodes.forEach(node => {
            result = result.concat(node.items)
            if (node.children) result = result.concat(getAllItems(node.children))
        })
        return result
    }
    const allItems = getAllItems(taskTree.value)
    total = allItems.filter(i => i.isConsidered).reduce((sum, i) => sum + i.hours, 0)
    return (total * clientHourRate.value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
})

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
    const taskId = findTaskIdForItem(item.id)
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
        if (taskIdToSave) {
            const hierarchy = await getTaskHierarchy(taskIdToSave)
            if (hierarchy) {
                fields[config.value.FIELDS.TASK_HIERARCHY] = hierarchy.idPath
                fields[config.value.FIELDS.TITLE_HIERARCHY] = hierarchy.titlePath
                if (hierarchy.projectId) {
                    fields[config.value.FIELDS.PROJECT_ID] = hierarchy.projectId
                    fields[config.value.FIELDS.PROJECT_TITLE] = hierarchy.projectTitle
                }
                // Task name from hierarchy (last element = current task title)
                if (hierarchy.titlePath && hierarchy.titlePath.length > 0) {
                    fields[config.value.FIELDS.TASK_NAME] = hierarchy.titlePath[hierarchy.titlePath.length - 1]
                }
                if (hierarchy.ourInn) fields[config.value.SPA_FIELDS.OUR_INN] = hierarchy.ourInn
                if (hierarchy.clientInn) fields[config.value.SPA_FIELDS.CLIENT_INN] = hierarchy.clientInn
            }
        }
        
        if (editingItem.value.id) {
            // Update existing
            console.log('💾 [Embedded] Updating item fields:', fields)
            await ($b24 as any).callMethod('crm.item.update', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                id: editingItem.value.id,
                fields: fields
            })
        } else {
            // Create new
            console.log('💾 [Embedded] Creating new item fields:', fields)
            await ($b24 as any).callMethod('crm.item.add', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                fields: fields
            })
        }
        
        if (rootTaskId.value) await loadData(rootTaskId.value)
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
        const splitTaskId = findTaskIdForItem(editingItem.value.id)
        
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
        if (splitTaskId) {
            const hierarchy = await getTaskHierarchy(splitTaskId)
            if (hierarchy) {
                splitFields[config.value.FIELDS.TASK_HIERARCHY] = hierarchy.idPath
                splitFields[config.value.FIELDS.TITLE_HIERARCHY] = hierarchy.titlePath
                if (hierarchy.projectId) {
                    splitFields[config.value.FIELDS.PROJECT_ID] = hierarchy.projectId
                    splitFields[config.value.FIELDS.PROJECT_TITLE] = hierarchy.projectTitle
                }
                if (hierarchy.titlePath && hierarchy.titlePath.length > 0) {
                    splitFields[config.value.FIELDS.TASK_NAME] = hierarchy.titlePath[hierarchy.titlePath.length - 1]
                }
                if (hierarchy.ourInn) splitFields[config.value.SPA_FIELDS.OUR_INN] = hierarchy.ourInn
                if (hierarchy.clientInn) splitFields[config.value.SPA_FIELDS.CLIENT_INN] = hierarchy.clientInn
            }
        }

        await ($b24 as any).callMethod('crm.item.add', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            fields: splitFields
        })

        if (rootTaskId.value) await loadData(rootTaskId.value)
        closeEditor()
    } catch (e: any) {
        alert("Ошибка разделения: " + e.message)
        isLoading.value = false
    }
}

function findTaskIdForItem(itemId: string): string | null {
    const search = (nodes: any[]): string | null => {
        for (let node of nodes) {
            if (node.items.find((i: any) => i.id === itemId)) return node.taskId
            const result = search(node.children)
            if (result) return result
        }
        return null
    }
    return search(taskTree.value)
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
        if (rootTaskId.value) await loadData(rootTaskId.value)
        closeEditor()
    } catch (e: any) {
        alert("Ошибка удаления: " + e.message)
        isLoading.value = false
    }
}

</script>

<template>
<div class="flex flex-col h-screen bg-slate-50 overflow-hidden">
    
    <!-- HEADER -->
    <header class="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between shrink-0">
        <div class="flex items-center gap-3">
            <div class="bg-blue-500 p-2 rounded-lg">
                <span class="material-symbols-outlined text-white text-2xl">schedule</span>
            </div>
            <div>
                <h1 class="text-xl font-bold text-slate-900">Учет часов</h1>
                <p class="text-xs text-slate-500">Учет трудозатрат по иерархии задач</p>
            </div>
        </div>

        <div class="flex items-center gap-4 bg-slate-50 border border-slate-200 rounded-lg p-3">
            <button @click="createNewEntry" class="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 font-semibold transition-colors">
                <span class="material-symbols-outlined">add</span>
                <span>Отразить</span>
            </button>
            <div class="h-8 w-px bg-slate-300"></div>
            <div class="flex flex-col">
                <label class="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Стоимость часа (руб.)</label>
                <input type="number" v-model="clientHourRate" class="bg-transparent font-bold text-slate-900 focus:outline-none w-24 mt-1">
            </div>
            <div class="h-8 w-px bg-slate-300"></div>
            <div class="flex flex-col text-right">
                <span class="text-[10px] uppercase font-bold text-blue-600 tracking-wider">Сумма для клиента</span>
                <span class="font-bold text-lg text-slate-900 mt-1">{{ totalClientAmount }} руб.</span>
            </div>
            <div class="h-8 w-px bg-slate-300"></div>
            <button @click="openHelp" class="flex flex-col items-center justify-center text-slate-400 hover:text-blue-600 transition-colors px-2" title="Инструкция">
                 <span class="material-symbols-outlined text-2xl">help</span>
                 <span class="text-[10px] uppercase font-bold mt-1">Help</span>
            </button>
        </div>
    </header>

    <!-- LOADING -->
    <div v-if="isLoading" class="flex-1 flex items-center justify-center">
        <div class="text-center">
            <span class="material-symbols-outlined text-5xl text-blue-500 animate-spin mb-4">progress_activity</span>
            <p class="text-slate-600">Загрузка данных...</p>
        </div>
    </div>

    <!-- ERROR -->
    <div v-else-if="error" class="flex-1 flex items-center justify-center p-6">
        <div class="bg-red-50 border border-red-200 p-6 rounded-xl max-w-lg text-center">
            <span class="material-symbols-outlined text-5xl text-red-500 mb-2">error</span>
            <h3 class="text-lg font-bold text-red-700 mb-2">Ошибка</h3>
            <p class="text-red-600">{{ error }}</p>
        </div>
    </div>

    <!-- MAIN SPLIT -->
    <div v-else class="flex-1 flex overflow-hidden">
        
        <!-- LEFT: TREE -->
        <div class="w-[70%] flex flex-col bg-white">
            <div class="flex-1 overflow-y-auto p-4">
                <TaskGroupComponent 
                    v-for="task in taskTree" 
                    :key="task.taskId"
                    :task="task"
                    :level="0"
                    :clientHourRate="clientHourRate"
                    :expandedTasks="expandedTasks"
                    :currentEditingId="currentEditingId"
                    @toggle="toggleTask"
                    @select="selectItem"
                    @createForTask="createEntryForTask"
                />
            </div>
        </div>

        <!-- RIGHT: EDITOR -->
        <div class="w-[30%] flex flex-col bg-slate-50 border-l border-slate-200">
            <div class="px-5 py-4 bg-white border-b border-slate-200 flex items-center justify-between">
                <h2 class="font-bold text-slate-800">Редактирование</h2>
                <button @click="closeEditor" class="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>

            <div v-if="!editingItem" class="flex-1 flex items-center justify-center text-center text-slate-400 p-8">
                <div>
                    <span class="material-symbols-outlined text-5xl mb-2">touch_app</span>
                    <p class="text-sm">Выберите запись для редактирования</p>
                </div>
            </div>

            <div v-else class="flex-1 overflow-y-auto p-5 space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-2">Описание</label>
                    <textarea v-model="editingItem.description" rows="2" class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none resize-none"></textarea>
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-2">Сотрудник</label>
                    <select v-model="editingItem.employeeId" class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none bg-white">
                        <option v-for="u in usersList" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-2">Дата</label>
                        <input type="date" v-model="editingItem.date" class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none">
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-2">Часы</label>
                        <input type="number" v-model.number="editingItem.hours" step="0.25" min="0" class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none font-bold">
                    </div>
                </div>
                <div>
                    <label class="flex items-center gap-3 p-3 border border-slate-200 rounded-lg bg-white cursor-pointer hover:border-slate-300">
                        <input type="checkbox" v-model="editingItem.isConsidered" class="w-4 h-4 accent-blue-600">
                        <span class="text-sm font-medium">Учитывать?</span>
                    </label>
                </div>

                <hr class="border-slate-200 my-6">

                <div class="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                    <h3 class="flex items-center gap-2 font-bold text-purple-900 mb-3 text-sm">
                        <span class="material-symbols-outlined">call_split</span>
                        Разделить запись
                    </h3>
                    <p class="text-xs text-slate-600 mb-3">Отделить часть времени в новую запись</p>
                    <div class="grid grid-cols-2 gap-2 mb-3">
                        <input type="number" v-model="editingItem.splitHours" step="0.5" placeholder="0" class="px-2 py-1.5 border border-purple-300 rounded text-center font-bold text-sm">
                        <span class="text-xs text-slate-600 flex items-center">часов отделить</span>
                    </div>
                    <label class="flex items-center gap-2 mb-3 text-xs cursor-pointer">
                        <input type="checkbox" v-model="editingItem.splitInvert" class="w-3 h-3 accent-purple-600">
                        <span>Инвертировать "Учитывать?"</span>
                    </label>
                    <button @click="splitItem" class="w-full py-2 bg-white border border-purple-300 text-purple-700 font-medium rounded-lg hover:bg-purple-100 text-sm">Выполнить разделение</button>
                </div>

                <button v-if="editingItem.id" @click="deleteItem" class="w-full py-2 bg-red-50 border border-red-200 text-red-700 font-medium rounded-lg hover:bg-red-100 text-sm flex items-center justify-center gap-2">
                    <span class="material-symbols-outlined text-base">delete</span>
                    Удалить запись
                </button>
            </div>

            <div v-if="editingItem" class="p-5 bg-white border-t border-slate-200 flex justify-end gap-3">
                <button @click="closeEditor" class="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg">Отмена</button>
                <button @click="saveCurrentItem" class="px-6 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm">Сохранить</button>
            </div>
        </div>
    </div>

</div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}
</style>
