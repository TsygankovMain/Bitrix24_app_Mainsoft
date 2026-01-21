<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { B24Frame } from '@bitrix24/b24jssdk'
import { useApiStore } from '~/stores/api'
import { useAppInit } from '~/composables/useAppInit'
import StatCard from '~/components/StatCard.vue'
import HelpModal from '~/components/HelpModal.vue'
import TaskTreeItem from '~/components/TaskTreeItem.vue'
import AddHoursModal from '~/components/AddHoursModal.vue'

definePageMeta({
  layout: 'default'
})

// --- Types ---
interface LogItem {
  id: number
  taskId: string
  employeeId: string
  hours: number
  isBillable: boolean
  description: string
  date: string
}

interface TaskNode {
  id: string
  title: string
  parentId: string | null
  items: LogItem[]
  
  // Local (Own)
  totalConsidered: number
  totalUnconsidered: number

  // Cumulative (Own + Children)
  cumulativeConsidered: number
  cumulativeUnconsidered: number

  children: TaskNode[]
  isOpen?: boolean
  responsibleId?: string
  
  // Legacy stats object (optional for backward compatibility if needed, but we are removing usage)
  stats?: { total: number; billable: number; nonBillable: number }
}

// --- State ---
const { t, locales, setLocale } = useI18n()
const apiStore = useApiStore()
// @ts-ignore
const { initApp } = useAppInit() 

const isLoading = ref(true)
const error = ref<string | null>(null)
const isHelpOpen = ref(false)

// Edit/Add State
const isAddModalOpen = ref(false)
const currentEditItem = ref<any>(null)
const targetTaskForAdd = ref<{ id: string, title: string } | null>(null)

const stats = ref({
  total: 0,
  billable: 0,
  nonBillable: 0
})

const rootTask = ref<TaskNode | null>(null)
const config = ref<any>(null)
const currentTaskId = ref<string>('')
let $b24: B24Frame | null = null

// --- Actions ---
const onHelpClick = () => {
  isHelpOpen.value = true
}

// --- Modal Handlers ---
const openAddModal = (node: TaskNode) => {
  currentEditItem.value = null
  targetTaskForAdd.value = { id: node.id, title: node.title }
  isAddModalOpen.value = true
}

const openEditModal = (item: LogItem, node: TaskNode) => {
  currentEditItem.value = item
  targetTaskForAdd.value = { id: node.id, title: node.title }
  isAddModalOpen.value = true
}

const handleToggleTree = (node: TaskNode) => {
    node.isOpen = !node.isOpen
}

// --- CRUD Operations ---
const handleSave = async (data: any) => {
    isAddModalOpen.value = false
    isLoading.value = true
    error.value = null
    
    try {
        const f = config.value.fields
        const entityTypeId = config.value.sp_entity_type_id
        
        const fields: any = {
            [f.hours]: data.hours,
            [f.description]: data.description,
            [f.isConsidered]: data.isBillable ? 'Y' : 'N',
        }
        
        if (data.date) {
            // Check if f.date exists and is not same as createdTime
            if (f.date && f.date !== 'createdTime') {
                fields[f.date] = data.date
            }
        }

        if (data.id) {
            // Update
            await new Promise((resolve, reject) => {
                // @ts-ignore
                $b24?.callMethod('crm.item.update', {
                    entityTypeId,
                    id: data.id,
                    fields
                // @ts-ignore
                }, (res: any) => res.error() ? reject(res.error()) : resolve(res.data()))
            })
        } else {
            // Create
            if (!targetTaskForAdd.value) throw new Error('Target task not selected')
            fields[f.taskId] = targetTaskForAdd.value.id
            if (f.employee) {
                // Determine user ID ? usually implicit or from user store
                // We'll rely on backend or user ID from context if available
            }
            
            await new Promise((resolve, reject) => {
                // @ts-ignore
                $b24?.callMethod('crm.item.add', {
                    entityTypeId,
                    fields
                // @ts-ignore
                }, (res: any) => res.error() ? reject(res.error()) : resolve(res.data()))
            })
        }

        // Refresh Data
        await loadData()
        
    } catch (e: any) {
        console.error('Save failed:', e)
        error.value = 'Ошибка сохранения: ' + (e.message || e.toString())
    } finally {
        isLoading.value = false
    }
}

const handleToggleBillable = async (item: LogItem, node: TaskNode) => {
    isLoading.value = true
    try {
        const f = config.value.fields
        const entityTypeId = config.value.sp_entity_type_id
        const newVal = !item.isBillable

        await new Promise((resolve, reject) => {
            // @ts-ignore
            $b24?.callMethod('crm.item.update', {
                entityTypeId,
                id: item.id,
                fields: {
                    [f.isConsidered]: newVal ? 'Y' : 'N'
                }
            // @ts-ignore
            }, (res: any) => res.error() ? reject(res.error()) : resolve(res.data()))
        })
        
        // Optimistic update or Reload. Reload is safer for stats recalc.
        await loadData()

    } catch (e: any) {
        console.error('Toggle failed:', e)
        error.value = 'Ошибка обновления: ' + e.message
        isLoading.value = false // only if error, otherwise loadData handles it
    }
}


const initialize = async () => {
  isLoading.value = true
  error.value = null
  let step = 'START'
  try {
    console.log('Task Module Initializing...')
    const { $initializeB24Frame } = useNuxtApp()
    
    // 1. Init B24 Frame
    step = 'INIT_FRAME'
    // @ts-ignore
    $b24 = await $initializeB24Frame()
    if (!$b24) throw new Error('Failed to initialize Bitrix24 frame')

    // 2. Init App Globals (Lang, User, etc)
    step = 'INIT_APP'
    // @ts-ignore
    await initApp($b24, locales, setLocale)

    // 3. Load Config
    step = 'LOAD_CONFIG'
    try {
        config.value = await apiStore.getConfiguration()
    } catch (e) {
        console.warn('Failed to load config, using defaults:', e)
    }

    if (!config.value || !config.value.sp_entity_type_id) {
        console.warn('Config missing, using fallback 1164');
        config.value = {
            sp_entity_type_id: 1164,
            fields: {
                taskId: 'ufCrm87_1761919581',
                employee: 'ufCrm87_1761919601',
                hours: 'ufCrm87_1761919617',
                isConsidered: 'ufCrm87_1763717129',
                description: 'ufCrm87_1762026149771',
                date: 'createdTime' // Fallback
            }
        }
    }

    // 4. Get Context (Task ID)
    step = 'PLACEMENT_INFO'
    // @ts-ignore
    const placement = $b24.getPlacementInfo()
    let currentTaskIdValue = null;
    
    if (placement.options) {
        let opts = placement.options;
        // Parse if string (common issue in B24 desktop)
        if (typeof opts === 'string') {
            try { opts = JSON.parse(opts); } catch (e) { opts = {}; }
        }
        currentTaskIdValue = opts.taskId || opts.ID || opts.id;
    }

    if (currentTaskIdValue) {
      currentTaskId.value = currentTaskIdValue.toString();
    } else {
       console.warn('No taskId in placement options:', placement);
       // Optional: Try to parse from URL parameters if available?
    }

    if (!currentTaskId.value) {
        throw new Error('Task ID not determined. Open this app from a Task. Placement info: ' + JSON.stringify(placement));
    }

    // 5. Load Data
    step = 'LOAD_DATA'
    await loadData()
    
  } catch (e: any) {
    console.error(`Initialization failed at step [${step}]:`, e)
    
    // DEBUG: Inspecting the "26" error
    let debugInfo = `Failed Step: ${step}\n`;
    try {
        if (typeof e === 'object') {
            debugInfo += JSON.stringify(e, Object.getOwnPropertyNames(e), 2);
        } else {
            debugInfo += String(e);
        }
    } catch (err) {
        debugInfo += 'Error stringifying error: ' + err;
    }

    if (e?.stack) {
        debugInfo += '\nStack: ' + e.stack;
    }

    error.value = `Ошибка (Этап ${step}): ${e.message || e}\n\nDebug Info:\n${debugInfo}`;
  } finally {
    isLoading.value = false
  }
}

const loadData = async () => {
    if (!$b24 || !currentTaskId.value) return
    const f = config.value.fields
    
    // 1. Fetch Root Task
    const rootTaskResult: any = await new Promise((resolve) => {
        // @ts-ignore
        // @ts-ignore
        $b24?.callMethod('tasks.task.get', { 
            taskId: currentTaskId.value, 
            select: ['ID', 'TITLE', 'PARENT_ID', 'RESPONSIBLE_ID'] 
        }, (res: any) => resolve(res))
    })

    if (!rootTaskResult || rootTaskResult.error()) {
        throw new Error(`Root task fetch failed: ${rootTaskResult?.error()}`)
    }
    const rootData = rootTaskResult.data().task

    // 2. Iteratively collect ALL subtasks (BFS)
    let allSubTasks: any[] = []
    let queue = [currentTaskId.value]
    const processedIds = new Set([currentTaskId.value])

    while (queue.length > 0) {
        const batchCmds = queue.map(id => ({
            method: 'tasks.task.list',
            params: {
                filter: { PARENT_ID: id },
                select: ['ID', 'TITLE', 'PARENT_ID', 'RESPONSIBLE_ID']
            }
        }))
        
        // BX24.callBatch in loop
        const batchResult: any = await new Promise((resolve) => {
             // @ts-ignore
             $b24?.callBatch(batchCmds, (res: any) => resolve(res))
        })

        queue = [] // Clear for next level

        // Process batch results (array or object depending on b24jssdk/bitrix response structure)
        // b24jssdk callBatch returns object where keys are indices if array passed? 
        // Actually usually strictly indexed if array passed. 
        // Let's assume standard behavior: result is an object/array corresponding to keys.
        
        const results = Array.isArray(batchResult) ? batchResult : Object.values(batchResult)
        
        for (const res of results as any[]) {
            if (res && !res.error()) {
                const tasks = res.data().tasks || []
                for (const task of tasks) {
                     if (!processedIds.has(task.id)) {
                        allSubTasks.push(task)
                        queue.push(task.id)
                        processedIds.add(task.id)
                    }
                }
            }
        }
    }

    const allTasks = [{ id: rootData.id, title: rootData.title, parentId: null, responsibleId: rootData.responsibleId }, ...allSubTasks]
    const allTaskIds = allTasks.map(t => t.id)

    // 3. Fetch Time Logs (Smart Process Items)
    // Batching logic if too many IDs? index_test.html processes all. Let's do batching of commands if needed, 
    // but index_test.html maps allTaskIds to commands. If tasks > 50, batching is needed for callBatch limits.
    // index_test.html does: allTaskIds.map ... callBatch. This might fail if > 50 tasks. 
    // But let's copy logic first.
    
    // Chunking for safety (Bitrix batch limit is 50)
    const chunkSize = 50
    let allItems: any[] = []
    
    for (let i = 0; i < allTaskIds.length; i += chunkSize) {
        const chunk = allTaskIds.slice(i, i + chunkSize)
        const spBatchCmds = chunk.map(taskId => ({
             method: 'crm.item.list',
             params: {
                entityTypeId: config.value.sp_entity_type_id,
                filter: { [`=${f.taskId}`]: taskId },
                select: ['id', 'title', 'createdTime', f.taskId, f.employee, f.hours, f.isConsidered, f.description]
             }
        }))

        const spResults: any = await new Promise((resolve) => {
             // @ts-ignore
             $b24?.callBatch(spBatchCmds, (res: any) => resolve(res))
        })
        
        const results = Array.isArray(spResults) ? spResults : Object.values(spResults)
        results.forEach((res: any) => {
            if (res && !res.error() && res.data().items) {
                allItems.push(...res.data().items)
            }
        })
    }
    
    const itemsByTaskId = allItems.reduce((acc, item) => {
        const taskId = item[f.taskId]
        if (!acc[taskId]) acc[taskId] = []
        acc[taskId].push(item)
        return acc
    }, {} as Record<string, any[]>)


    // 4. Build Tree Nodes
    const nodes: Record<string, TaskNode> = {}
    
    allTasks.forEach(task => {
        const rawItems = itemsByTaskId[task.id] || []
        
        // Map raw items to LogItem
        const items: LogItem[] = rawItems.map((item: any) => ({
            id: item.id,
            taskId: item[f.taskId],
            employeeId: item[f.employee],
            hours: parseFloat(item[f.hours] || 0),
            isBillable: item[f.isConsidered] === 'Y' || item[f.isConsidered] === true, 
            description: item[f.description],
            date: item.createdTime, // or custom field if used
            title: item.title,
            createdTime: item.createdTime
        }))

        // Calc Local stats
        const totalConsidered = items.reduce((sum, item) => sum + (item.isBillable ? item.hours : 0), 0)
        const totalUnconsidered = items.reduce((sum, item) => sum + (!item.isBillable ? item.hours : 0), 0)

        nodes[task.id] = {
            id: task.id,
            title: task.title,
            parentId: task.parentId,
            items: items,
            totalConsidered,
            totalUnconsidered,
            cumulativeConsidered: 0, // calc later
            cumulativeUnconsidered: 0, // calc later
            children: [],
            isOpen: true, // Default open
            responsibleId: task.responsibleId
        }
    })

    // 5. Assemble Hierarchy
    const tree: TaskNode[] = []
    Object.values(nodes).forEach(node => {
        if (node.parentId && nodes[node.parentId]) {
            nodes[node.parentId]!.children.push(node)
        } else if (String(node.id) === String(currentTaskId.value)) {
            tree.push(node)
        }
    })

    // 6. Recursive Cumulative Calculation
    const calculateCumulativeTotals = (node: TaskNode) => {
        let childConsidered = 0
        let childUnconsidered = 0

        if (node.children && node.children.length > 0) {
            node.children.forEach(child => {
                const childTotals = calculateCumulativeTotals(child)
                childConsidered += childTotals.considered
                childUnconsidered += childTotals.unconsidered
            })
        }
        
        node.cumulativeConsidered = node.totalConsidered + childConsidered
        node.cumulativeUnconsidered = node.totalUnconsidered + childUnconsidered
        
        return {
            considered: node.cumulativeConsidered,
            unconsidered: node.cumulativeUnconsidered
        }
    }

    if (tree.length > 0) {
        calculateCumulativeTotals(tree[0]!)
        rootTask.value = tree[0]!
        
        // Update global stats
        stats.value = {
            total: tree[0]!.cumulativeConsidered + tree[0]!.cumulativeUnconsidered,
            billable: tree[0]!.cumulativeConsidered,
            nonBillable: tree[0]!.cumulativeUnconsidered
        }
    } else {
        rootTask.value = null // Should technically not happen if root found
    }
}

const handleTransfer = async () => {
    if (!confirm('Вы уверены, что хотите перенести все оплачиваемые часы в отчет?')) return
    
    isLoading.value = true
    try {
        const res = await apiStore.syncTimesheets()
        await loadData() // Refresh to see changes if any
        alert(`Успешно перенесено записей: ${res.count}`)
    } catch (e: any) {
        console.error('Transfer failed:', e)
        error.value = 'Ошибка переноса: ' + (e.message || e.toString())
    } finally {
        isLoading.value = false
    }
}

// --- Lifecycle ---
onMounted(() => {
  initialize()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 p-4">
    <!-- Modals -->
    <HelpModal :open="isHelpOpen" @close="isHelpOpen = false" />
    
    <AddHoursModal 
      :open="isAddModalOpen" 
      :taskId="targetTaskForAdd?.id"
      :taskTitle="targetTaskForAdd?.title"
      :editItem="currentEditItem"
      @close="isAddModalOpen = false"
      @save="handleSave"
    />

    <!-- Header Stats -->
    <div class="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-4">
      <StatCard
        icon="schedule"
        label="Всего часов"
        :value="rootTask ? (rootTask.cumulativeConsidered + rootTask.cumulativeUnconsidered).toFixed(2) : '0.00'"
        unit="ч"
        color="text-blue-600"
      />
      <StatCard
        icon="attach_money"
        label="Оплачиваемо"
        :value="rootTask ? rootTask.cumulativeConsidered.toFixed(2) : '0.00'"
        unit="ч"
        color="text-green-500"
      />
      <StatCard
        icon="money_off"
        label="Внутренние"
        :value="rootTask ? rootTask.cumulativeUnconsidered.toFixed(2) : '0.00'"
        unit="ч"
        color="text-slate-400"
      />
      
      <!-- Help Button Area -->
      <div class="flex items-center justify-end">
        <button 
          @click="onHelpClick"
          class="p-2 text-slate-400 hover:text-indigo-600 transition-colors rounded-full hover:bg-white hover:shadow-sm"
          title="Справка"
        >
          <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        </button>
      </div>
    </div>

    <!-- Main Content -->
    <div v-if="error" class="rounded-md bg-red-50 p-4 mb-4">
      <div class="flex">
        <div class="ml-3">
          <h3 class="text-sm font-medium text-red-800">Ошибка инициализации</h3>
          <div class="mt-2 text-sm text-red-700">
            <p>{{ error }}</p>
          </div>
          <div class="mt-4">
            <button @click="initialize" type="button" class="rounded-md bg-red-50 px-2 py-1.5 text-sm font-medium text-red-800 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-600 focus:ring-offset-2 focus:ring-offset-red-50">Повторить</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="isLoading" class="flex justify-center items-center py-12">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
    </div>

    <div v-else-if="!rootTask" class="bg-white rounded-lg shadow-sm p-8 text-center text-slate-500">
      <p>Задачи не найдены или доступ запрещен.</p>
    </div>

    <div v-else>
      <div class="bg-white shadow-sm rounded-lg overflow-hidden border border-gray-200">
        <div class="p-4 border-b border-gray-100 bg-gray-50/50">
          <h2 class="text-lg font-medium text-gray-900">Структура задач</h2>
        </div>
        <div>
           <TaskTreeItem 
             :node="rootTask" 
             :level="0" 
             @add="openAddModal"
             @edit="openEditModal"
             @toggle="handleToggleTree"
             @toggle-billable="handleToggleBillable"
           />
        </div>
      </div>
    </div>

    <!-- Actions Footer -->
    <div class="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 p-4 flex justify-between items-center shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.1)] z-40 transition-transform duration-300" 
         :class="{'translate-y-full': !(!isLoading && rootTask)}" 
         v-if="!isLoading && rootTask">
       <div>
         <!-- Optional left content -->
       </div>
       <button 
         @click="handleTransfer"
         class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
       >
         Перенести в отчет
       </button>
    </div>
    
    <!-- Spacer for footer -->
    <div class="h-24" v-if="!isLoading && rootTask"></div>

  </div>
</template>
