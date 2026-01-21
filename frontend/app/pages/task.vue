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
  stats: { total: number; billable: number; nonBillable: number }
  children: TaskNode[]
  isOpen?: boolean
  responsibleId?: string
}

// --- State ---
const { t } = useI18n()
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
  try {
    console.log('Task Module Initializing...')
    const { $initializeB24Frame } = useNuxtApp()
    
    // 1. Init B24 Frame
    // @ts-ignore
    $b24 = await $initializeB24Frame()
    if (!$b24) throw new Error('Failed to initialize Bitrix24 frame')

    // 2. Init App Globals (Lang, User, etc)
    // @ts-ignore
    await initApp($b24, useI18n().locales.value, useI18n().setLocale)

    // 3. Load Config
    config.value = await apiStore.getConfiguration()
    if (!config.value || !config.value.sp_entity_type_id) {
      throw new Error('Configuration not found or invalid SP ID')
    }

    // 4. Get Context (Task ID)
    // @ts-ignore
    const placement = $b24.placement.info()
    if (placement.options && placement.options.taskId) {
      currentTaskId.value = placement.options.taskId.toString()
    } else {
       console.warn('No taskId in placement options.')
    }

    if (!currentTaskId.value) {
        throw new Error('Task ID not determined. Open this app from a Task.')
    }

    // 5. Load Data
    await loadData()
    
  } catch (e: any) {
    console.error('Initialization failed:', e)
    error.value = e.message || 'Unknown error occurred'
  } finally {
    isLoading.value = false
  }
}

const loadData = async () => {
    if (!$b24 || !currentTaskId.value) return
    
    // 1. Fetch Task Info (Root + Subtasks)
    
    const cmd = {
        root: {
            method: 'tasks.task.get',
            params: {
                id: currentTaskId.value,
                select: ['ID', 'TITLE', 'PARENT_ID', 'RESPONSIBLE_ID']
            }
        },
        children: {
            method: 'tasks.task.list',
            params: {
                filter: { PARENT_ID: currentTaskId.value },
                select: ['ID', 'TITLE', 'PARENT_ID', 'RESPONSIBLE_ID']
            }
        }
    }

    const taskResult: any = await new Promise((resolve, reject) => {
        // @ts-ignore
        $b24?.callBatch(cmd, (res: any) => {
             resolve(res)
        })
    })

    // Helper to extract data or throw
    const getResultData = (key: string) => {
        const r = taskResult[key]
        if (!r || r.error()) throw new Error(`Failed to fetch ${key}: ${r ? r.error() : 'No result'}`)
        return r.data()
    }

    // Root Task
    const rootData = getResultData('root')
    const root = rootData && rootData.task ? rootData.task : rootData 
    
    // Children
    const childrenData = getResultData('children')
    const children = childrenData && childrenData.tasks ? childrenData.tasks : childrenData 

    if (!root) throw new Error('Root task not found')

    // 2. Fetch Time Logs (Smart Process Items)
    const allTaskIds = [root.id, ...children.map((c: any) => c.id)]
    
    // Field Mapping
    const f = config.value.fields
    
    const filter = {
        entityTypeId: config.value.sp_entity_type_id,
        filter: {
            [`=${f.taskId}`]: allTaskIds 
        },
        select: ['id', f.taskId, f.employee, f.hours, f.isConsidered, f.description, 'createdTime', f.date || 'createdTime'] 
    }

    const itemsResult: any = await new Promise((resolve) => {
        // @ts-ignore
        $b24?.callMethod('crm.item.list', filter, (res: any) => {
            resolve(res)
        })
    })

    if (itemsResult.error()) throw itemsResult.error()
    
    const rawItems = itemsResult.data().items
    
    // 3. Build Tree
    const logs: LogItem[] = rawItems.map((item: any) => ({
        id: item.id,
        taskId: item[f.taskId],
        employeeId: item[f.employee],
        hours: parseFloat(item[f.hours] || 0),
        isBillable: item[f.isConsidered] === 'Y' || item[f.isConsidered] === true || item[f.isConsidered] === 1, 
        description: item[f.description],
        date: item[f.date] || item.createdTime // TODO: Format date correctly if custom field
    }))

    // Construct Nodes
    const taskMap = new Map<string, TaskNode>()

    // Init Root Node
    const rootNode: TaskNode = {
        id: root.id,
        title: root.title,
        parentId: root.parentId,
        items: [],
        stats: { total: 0, billable: 0, nonBillable: 0 },
        children: [],
        isOpen: true,
        responsibleId: root.responsibleId
    }
    taskMap.set(root.id, rootNode)

    // Init Children Nodes
    children.forEach((c: any) => {
        const node: TaskNode = {
            id: c.id,
            title: c.title,
            parentId: c.parentId,
            items: [],
            stats: { total: 0, billable: 0, nonBillable: 0 },
            children: [],
            responsibleId: c.responsibleId
        }
        taskMap.set(c.id, node)
        // Link to root (since we fetched only direct children)
        if (c.parentId === root.id) {
            rootNode.children.push(node)
        }
    })

    // Distribute Logs
    logs.forEach(log => {
        const node = taskMap.get(log.taskId)
        if (node) {
            node.items.push(log)
        }
    })

    // Calculate Stats (Bottom Up)
    const calcNodeStats = (node: TaskNode) => {
        let total = 0, billable = 0, nonBillable = 0
        
        // Sum items
        node.items.forEach(i => {
            total += i.hours
            if (i.isBillable) billable += i.hours
            else nonBillable += i.hours
        })

        // Sum children
        node.children.forEach(c => {
            calcNodeStats(c) 
            total += c.stats.total
            billable += c.stats.billable
            nonBillable += c.stats.nonBillable
        })

        node.stats = { total, billable, nonBillable }
    }

    calcNodeStats(rootNode)
    
    rootTask.value = rootNode
    stats.value = rootNode.stats
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
        :value="stats.total.toFixed(2)"
        unit="ч"
        color="text-blue-600"
      />
      <StatCard
        icon="attach_money"
        label="Оплачиваемо"
        :value="stats.billable.toFixed(2)"
        unit="ч"
        color="text-green-500"
      />
      <StatCard
        icon="money_off"
        label="Внутренние"
        :value="stats.nonBillable.toFixed(2)"
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
