<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import type { B24Frame } from '@bitrix24/b24jssdk'
import StatCard from '~/components/StatCard.vue'
import TaskGroup from '~/components/TaskGroup.vue'

// --- Types ---
interface TaskNode {
  taskId: number | string
  taskTitle: string
  parentId: number | string | null
  items: any[]
  totalConsidered: number
  totalUnconsidered: number
  cumulativeConsidered: number
  cumulativeUnconsidered: number
  children: TaskNode[]
}

interface Configuration {
  sp_entity_type_id: number
  fields_mapping: Record<string, string>
}

// --- Init ---
const { t } = useI18n()
const { $logger, initApp, processErrorGlobal } = useAppInit('TaskHoursPage')
const { $initializeB24Frame } = useNuxtApp()
const apiStore = useApiStore()

let $b24: null | B24Frame = null

// --- State ---
const isLoading = ref(true)
const error = ref<string | null>(null)
const taskTree = ref<TaskNode[]>([])
const users = ref<Record<string, string>>({})
const allUsers = ref<any[]>([])

const config = ref<Configuration | null>(null)
const mainTaskId = ref<string | number | null>(null)
const currentUserId = ref<string | number>('')

// UI State
const showModal = ref(false)
const showReportModal = ref(false)
const isCreating = ref(false)
const isReporting = ref(false)
const modalError = ref<string | null>(null)
const reportModalError = ref<string | null>(null)
const openTaskIds = ref(new Set<string | number>())
const updatingItemId = ref<number | string | null>(null)

// Settings State
const isSettingsOpen = ref(false)
const clientHourRate = ref(0) // Could be loaded from local storage or settings

// Form Data
const formData = ref({
  hours: '',
  description: '',
  date: new Date().toISOString().split('T')[0],
  employeeId: '',
  targetTaskId: null as string | number | null,
  isConsidered: true
})

// --- Computed ---
const fields = computed(() => {
  if (!config.value?.fields_mapping) return null
  return {
    hours: config.value.fields_mapping.kolichestvo_chasov || 'B24APP_HOURS',
    isConsidered: config.value.fields_mapping.uchitivaem || 'B24APP_IS_BILLABLE',
    employee: config.value.fields_mapping.sotrudnik || 'B24APP_EMPLOYEE',
    taskId: config.value.fields_mapping.id_zadachi || 'B24APP_TASK_ID',
    description: config.value.fields_mapping.opisanie || 'B24APP_DESCRIPTION',
    hierarchyIds: config.value.fields_mapping.id_zadach_ierarhiya || 'B24APP_TASK_HIERARCHY_IDS',
    hierarchyTitles: config.value.fields_mapping.title_zadach_ierarhiya || 'B24APP_TASK_HIERARCHY_ITLES',
    createdTime: 'createdTime'
  }
})

const totalStats = computed(() => {
  let considered = 0
  let unconsidered = 0
  taskTree.value.forEach(node => {
    considered += node.cumulativeConsidered || 0
    unconsidered += node.cumulativeUnconsidered || 0
  })
  return {
    considered,
    unconsidered,
    total: considered + unconsidered
  }
})

// --- Helpers ---
const callMethodPromise = (method: string, params: any) => new Promise<any>((resolve, reject) => {
  // @ts-ignore
  if (!window.BX24) return reject('BX24 not found')
  // @ts-ignore
  window.BX24.callMethod(method, params, (result: any) => {
    if (result.error()) reject(result.error())
    else resolve(result.data())
  })
})

const callBatchPromise = (commands: any) => new Promise<any>((resolve) => {
  // @ts-ignore
  if (!window.BX24) return resolve({})
  // @ts-ignore
  window.BX24.callBatch(commands, (result: any) => resolve(result))
})

// --- Logic ---
const fetchConfiguration = async () => {
  try {
    const res = await apiStore.getConfiguration()
    if (res && res.config) {
        config.value = res.config
        // Fallback or fix types
        if (!config.value.sp_entity_type_id) {
             console.warn("SP Entity ID missing in config, using default 1260 or checking install response")
             // In a real app we might error out, or use a reliable default if known.
             // We can also try to fetch SP by code 'timesheet_app'
        }
    }
  } catch (e) {
    console.error("Failed to load configuration", e)
    error.value = "Не удалось загрузить настройки приложения. Попробуйте обновить страницу."
  }
}

const getTaskHierarchy = async (initialTaskId: string | number) => {
  let currentTaskId = initialTaskId
  const idPath: any[] = []
  const titlePath: any[] = []

  while (currentTaskId) {
    try {
      const result = await callMethodPromise('tasks.task.get', {
        taskId: currentTaskId,
        select: ['ID', 'TITLE', 'PARENT_ID']
      })
      const task = result.task
      if (task) {
        idPath.unshift(task.id)
        titlePath.unshift(task.title)
        if (task.parentId && task.parentId !== '0') {
          currentTaskId = task.parentId
        } else {
          currentTaskId = null
        }
      } else {
        currentTaskId = null
      }
    } catch (e) {
      console.error(`Error fetching task ${currentTaskId}`, e)
      currentTaskId = null
    }
  }
  return { idPath, titlePath }
}

const fetchData = async (currentTaskId: string | number) => {
  if (!config.value?.sp_entity_type_id) {
    // Try to fetch config first if not ready
    await fetchConfiguration()
    if (!config.value?.sp_entity_type_id) {
         setError("ID Смарт-процесса не настроен.")
         return
    }
  }

  setIsLoading(true)
  setError(null)

  try {
     // 1. Get Root Task
     const rootTaskRes = await callMethodPromise('tasks.task.get', { taskId: currentTaskId, select: ['ID', 'TITLE'] })
     const rootTaskData = rootTaskRes.task

     // 2. BFS for Subtasks
     let allSubTasks: any[] = []
     let queue = [currentTaskId]
     const processedIds = new Set([currentTaskId])

     const MAX_DEPTH_SAFEGUARD = 50 
     let loops = 0

     while (queue.length > 0 && loops < MAX_DEPTH_SAFEGUARD) {
         loops++
         const batchCmds = queue.map(id => ['tasks.task.list', {
             filter: { PARENT_ID: id },
             select: ['id', 'title', 'parentId']
         }])
         
         const batchResult = await callBatchPromise(batchCmds)
         queue = []

         for (const res of Object.values(batchResult) as any[]) {
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

     const allTasks = [{ id: rootTaskData.id, title: rootTaskData.title, parentId: null }, ...allSubTasks]
     const allTaskIds = allTasks.map(t => t.id)

     // 3. Get SP Items
     const f = fields.value!
     const spBatchCmds = allTaskIds.map(taskId => ['crm.item.list', {
         entityTypeId: config.value!.sp_entity_type_id,
         filter: { [f.taskId]: taskId },
         select: ['id', 'title', 'createdTime', f.taskId, f.employee, f.hours, f.isConsidered, f.description]
     }])

     const spResults = await callBatchPromise(spBatchCmds)
     const allItems = Object.values(spResults).flatMap((res: any) => (res && !res.error() && res.data().items) ? res.data().items : [])

     const itemsByTaskId = allItems.reduce((acc: any, item: any) => {
         const tid = item[f.taskId]
         if (!acc[tid]) acc[tid] = []
         acc[tid].push(item)
         return acc
     }, {})

     // 4. Build Nodes
     const nodes: Record<string, TaskNode> = {}
     allTasks.forEach(task => {
         const items = itemsByTaskId[task.id] || []
         // Calculate local totals
         let totalConsidered = 0
         let totalUnconsidered = 0
         
         items.forEach((item: any) => {
             const isCons = item[f.isConsidered] === true || item[f.isConsidered] === 'Y'
             const h = parseFloat(item[f.hours]) || 0
             if (isCons) totalConsidered += h
             else totalUnconsidered += h
         })

         nodes[task.id] = {
             taskId: task.id,
             taskTitle: task.title,
             parentId: task.parentId,
             items: items,
             totalConsidered,
             totalUnconsidered,
             cumulativeConsidered: 0,
             cumulativeUnconsidered: 0,
             children: []
         }
     })

     // 5. Build Tree & hierarchy
     const tree: TaskNode[] = []
     Object.values(nodes).forEach(node => {
         if (node.parentId && nodes[node.parentId]) {
             nodes[node.parentId].children.push(node)
         } else if (String(node.taskId) === String(currentTaskId)) {
             tree.push(node)
         }
     })

     // 6. Cumulative Totals
     const calculateCumulative = (node: TaskNode) => {
         let childCons = 0
         let childUncons = 0
         
         if (node.children.length > 0) {
             node.children.forEach(child => {
                 const childTotals = calculateCumulative(child)
                 childCons += childTotals.considered
                 childUncons += childTotals.unconsidered
             })
         }
         
         node.cumulativeConsidered = node.totalConsidered + childCons
         node.cumulativeUnconsidered = node.totalUnconsidered + childUncons
         
         return { considered: node.cumulativeConsidered, unconsidered: node.cumulativeUnconsidered }
     }

     tree.forEach(calculateCumulative)
     taskTree.value = tree

     // 7. Load Users
     const employeeIds = [...new Set(allItems.map((item: any) => item[f.employee]).filter(Boolean))] as string[]
     if (employeeIds.length > 0) {
         // Check which we don't have
         const missingIds = employeeIds.filter(id => !users.value[id])
         if (missingIds.length > 0) {
             const userBatch = missingIds.reduce((acc: any, id) => ({...acc, [`user_${id}`]: ['user.get', { ID: id }]}), {})
             const userResult = await callBatchPromise(userBatch)
             
             missingIds.forEach(id => {
                 const res = userResult[`user_${id}`]
                 if (res && !res.error() && res.data()[0]) {
                     const user = res.data()[0]
                     users.value[id] = `${user.NAME} ${user.LAST_NAME}`
                 } else {
                     users.value[id] = `Пользователь #${id}`
                 }
             })
         }
     }

  } catch (e: any) {
      console.error("Data fetch error", e)
      setError(e.message || "Ошибка загрузки данных")
  } finally {
      setIsLoading(false)
  }
}

// --- Actions ---

const setIsLoading = (val: boolean) => isLoading.value = val
const setError = (msg: string | null) => error.value = msg

const handleToggleHours = (itemId: number | string) => {
    updatingItemId.value = itemId
    // Find item
    let itemToUpdate: any = null
    const findItem = (nodes: TaskNode[]) => {
        for (const node of nodes) {
            const found = node.items.find(i => i.id === itemId)
            if (found) { itemToUpdate = found; return }
            if (node.children.length > 0) findItem(node.children)
        }
    }
    findItem(taskTree.value)

    if (!itemToUpdate) {
        updatingItemId.value = null
        return
    }

    const f = fields.value!
    const currentIsConsidered = itemToUpdate[f.isConsidered] === true || itemToUpdate[f.isConsidered] === 'Y'

    callMethodPromise('crm.item.update', {
        entityTypeId: config.value!.sp_entity_type_id,
        id: itemId,
        fields: {
             [f.isConsidered]: currentIsConsidered ? 'N' : 'Y'
        }
    }).then(() => {
        updatingItemId.value = null
        if (mainTaskId.value) fetchData(mainTaskId.value)
    }).catch(e => {
        console.error(e)
        // Show error notification?
        updatingItemId.value = null
    })
}

const handleCreateHours = async () => {
    modalError.value = null
    if (!formData.value.hours || parseFloat(formData.value.hours) <= 0) return modalError.value = 'Укажите количество часов'
    if (!formData.value.description) return modalError.value = 'Укажите описание'
    if (!formData.value.employeeId) return modalError.value = 'Выберите сотрудника'
    
    isCreating.value = true

    try {
        const hierarchy = await getTaskHierarchy(formData.value.targetTaskId!)
        const f = fields.value!
        
        await callMethodPromise('crm.item.add', {
            entityTypeId: config.value!.sp_entity_type_id,
            fields: {
                title: formData.value.description.substring(0, 255),
                [f.hours]: parseFloat(formData.value.hours),
                [f.isConsidered]: formData.value.isConsidered ? 'Y' : 'N',
                [f.taskId]: formData.value.targetTaskId,
                [f.employee]: formData.value.employeeId,
                [f.description]: formData.value.description,
                'createdTime': formData.value.date + 'T00:00:00',
                [f.hierarchyIds]: JSON.stringify(hierarchy.idPath), // Or plain array if field supports it? Usually string for text field
                [f.hierarchyTitles]: JSON.stringify(hierarchy.titlePath)
            }
        })
        
        isCreating.value = false
        showModal.value = false
        if (mainTaskId.value) fetchData(mainTaskId.value)

    } catch (e: any) {
        console.error(e)
        modalError.value = `Ошибка: ${e.message || e}`
        isCreating.value = false
    }
}

const handleTransferToReport = () => {
    reportModalError.value = null
    if (totalStats.value.considered <= 0) return reportModalError.value = 'Нет часов для переноса'
    
    isReporting.value = true
    const f = fields.value!
    
    const itemsToTransfer: any[] = []
    const collect = (nodes: TaskNode[]) => {
        nodes.forEach(node => {
            node.items.forEach(item => {
                // Should we check if already transferred? Field for that?
                // For now assuming we just transfer what is currently considered
                const isCons = item[f.isConsidered] === true || item[f.isConsidered] === 'Y'
                if (isCons && (parseFloat(item[f.hours]) || 0) > 0) {
                    itemsToTransfer.push(item)
                }
            })
            if (node.children.length > 0) collect(node.children)
        })
    }
    collect(taskTree.value)
    
    if (itemsToTransfer.length === 0) {
        isReporting.value = false
        showReportModal.value = false
        return
    }

    const batchCommands = itemsToTransfer.map(item => {
        const h = parseFloat(item[f.hours]) || 0
        return ['task.elapseditem.add', {
            TASKID: item[f.taskId],
            FIELDS: {
                SECONDS: Math.round(h * 3600),
                USER_ID: item[f.employee] || currentUserId.value,
                COMMENT_TEXT: item[f.description] || `Списание ${h} ч.`
            }
        }]
    })

    callBatchPromise(batchCommands).then(() => {
        isReporting.value = false
        showReportModal.value = false
        alert("Часы успешно перенесены") // Use UI notification
    })
}

const handleOpenModal = (targetId: string | number) => {
    // Reset form
    formData.value = {
        hours: '',
        description: '',
        date: new Date().toISOString().split('T')[0],
        employeeId: String(currentUserId.value),
        targetTaskId: targetId,
        isConsidered: true
    }
    modalError.value = null
    showModal.value = true
}

const toggleGroup = (id: string | number) => {
    if (openTaskIds.value.has(id)) openTaskIds.value.delete(id)
    else openTaskIds.value.add(id)
}

const handleOpenItem = (id: string | number) => {
    // @ts-ignore
    if (window.BX24) window.BX24.openPath(`/crm/type/${config.value?.sp_entity_type_id}/details/${id}/`)
}

// --- Lifecycle ---
onMounted(async () => {
  try {
    try {
        $b24 = await $initializeB24Frame()
    } catch (e) {
        console.error('B24 Init Failed', e)
    }
    // @ts-ignore
    await initApp($b24!, useI18n().locales.value, useI18n().setLocale)
    
    // Load config first
    await fetchConfiguration()

    // Determin Context
    // @ts-ignore
    if (typeof window.BX24 !== 'undefined') {
        // @ts-ignore
        window.BX24.init(() => {
            // @ts-ignore
            const placementInfo = window.BX24.placement.info()
            let tid: any = null
            if (placementInfo?.options) {
                 // Options can be JSON string or object
                 let opts = placementInfo.options
                 if (typeof opts === 'string') {
                     try { opts = JSON.parse(opts) } catch {}
                 }
                 tid = opts.ID || opts.taskId || opts.id
            }

            // Fallback for dev mode without placement (hardcode for testing?)
            // if (!tid && import.meta.dev) tid = 1

            if (!tid) {
                setError("Не удалось определить ID задачи. Откройте приложение через вкладку задачи.")
                isLoading.value = false
                return
            }

            mainTaskId.value = tid
            openTaskIds.value.add(tid)

            // Load Users
            // @ts-ignore
            window.BX24.callBatch({
                currentUser: ['user.current', {}],
                allUsers: ['user.get', { FILTER: { ACTIVE: 'Y' }, sort: 'LAST_NAME', order: 'ASC'}]
            }, (res: any) => {
                 const cur = res.currentUser
                 if (cur && !cur.error()) {
                     currentUserId.value = cur.data().ID
                     formData.value.employeeId = String(cur.data().ID)
                 }
                 const all = res.allUsers
                 if (all && !all.error()) {
                     allUsers.value = all.data()
                 }
                 
                 fetchData(tid)
            })
        })
    } else {
        setError("B24 context not found")
        isLoading.value = false
    }

  } catch (e) {
    processErrorGlobal(e)
  }
})
</script>

<template>
  <div class="h-full flex flex-col bg-slate-50">
      
      <!-- Loading / Error -->
      <div v-if="isLoading" class="flex items-center justify-center h-full">
          <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500"></div>
          <p class="ml-4 text-slate-500">Загрузка данных...</p>
      </div>

      <div v-else-if="error" class="flex items-center justify-center h-full p-4">
          <div class="bg-red-50 text-red-700 p-4 rounded-lg flex items-center">
              <span class="material-symbols-outlined mr-2">error</span>
              {{ error }}
          </div>
      </div>

      <!-- Content -->
      <div v-else class="flex flex-col h-full">
          <!-- Header -->
          <header class="p-4 bg-white border-b shrink-0 space-y-4">
              <!-- Settings Toggle -->
              <div class="border rounded-lg bg-slate-50 overflow-hidden">
                   <button @click="isSettingsOpen = !isSettingsOpen" class="w-full flex justify-between items-center p-3 text-left hover:bg-slate-100">
                       <div class="flex items-center">
                           <span class="material-symbols-outlined text-slate-600 mr-2">tune</span>
                           <span class="font-semibold text-slate-800">Настройки расчета</span>
                       </div>
                       <span :class="`material-symbols-outlined text-slate-500 transition-transform ${isSettingsOpen ? 'rotate-180' : ''}`">expand_more</span>
                   </button>
                   <div v-if="isSettingsOpen" class="p-4 border-t bg-white grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                             <label class="block text-sm font-medium text-slate-700 mb-1">Стоимость часа для клиента (руб.)</label>
                             <input type="number" v-model.number="clientHourRate" class="w-full px-3 py-2 border rounded-lg" placeholder="3000" />
                        </div>
                        <div>
                             <p class="text-sm text-slate-500 mt-6">ID Смарт-процесса: {{ config?.sp_entity_type_id }}</p>
                        </div>
                   </div>
              </div>

              <!-- Dash -->
              <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <StatCard icon="schedule" label="Всего по задаче" :value="totalStats.total.toFixed(2)" unit="ч" color="text-blue-500" />
                  <StatCard icon="task_alt" label="Учитываемые" :value="totalStats.considered.toFixed(2)" unit="ч" color="text-green-500" />
                  <StatCard icon="block" label="Не учитываемые" :value="totalStats.unconsidered.toFixed(2)" unit="ч" color="text-red-500" />
                  
                  <div class="col-span-2 md:col-span-1 flex gap-2">
                      <button @click="handleOpenModal(mainTaskId!)" class="w-full flex items-center justify-center gap-2 bg-green-500 text-white rounded-lg hover:bg-green-600 font-semibold px-3 py-2 text-sm">
                          <span class="material-symbols-outlined">add</span> Отразить
                      </button>
                      <button @click="showReportModal = true" :disabled="totalStats.considered <= 0" class="w-full flex items-center justify-center gap-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-semibold px-3 py-2 text-sm disabled:bg-slate-300 disabled:cursor-not-allowed">
                          <span class="material-symbols-outlined">send</span> В отчет
                      </button>
                  </div>
              </div>
          </header>

          <!-- Tree -->
          <main class="flex-1 overflow-y-auto p-4">
               <div class="max-w-7xl mx-auto space-y-4">
                   <div v-if="taskTree.length === 0" class="text-center py-10 text-slate-500">
                       Нет данных для отображения.
                   </div>
                   <TaskGroup 
                       v-for="rootTask in taskTree" 
                       :key="rootTask.taskId" 
                       :task="rootTask"
                       :level="0"
                       :clientHourRate="clientHourRate"
                       :openTaskIds="openTaskIds"
                       :users="users"
                       :updatingItemId="updatingItemId"
                       :fields="fields!"
                       @toggle-group="toggleGroup"
                       @open-modal="handleOpenModal"
                       @toggle-hours="handleToggleHours"
                       @open-item="handleOpenItem"
                   />
               </div>
          </main>
      </div>

      <!-- Modals (Simplified Inline or Components) -->
      <!-- Add Hours Modal -->
      <div v-if="showModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
           <div class="bg-white rounded-lg shadow-lg max-w-md w-full p-6">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-bold">Отразить часы (Задача #{{ formData.targetTaskId }})</h3>
                    <button @click="showModal = false" class="text-slate-500"><span class="material-symbols-outlined">close</span></button>
                </div>
                
                <div v-if="modalError" class="mb-4 bg-red-50 text-red-700 p-2 rounded text-sm">{{ modalError }}</div>

                <div class="space-y-4">
                     <div>
                         <label class="block text-sm font-medium mb-1">Сотрудник</label>
                         <select v-model="formData.employeeId" class="w-full border rounded px-3 py-2 bg-white">
                             <option value="">Выберите сотрудника</option>
                             <option v-for="u in allUsers" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                         </select>
                     </div>
                     <div>
                         <label class="block text-sm font-medium mb-1">Часы</label>
                         <input type="number" v-model="formData.hours" step="0.5" class="w-full border rounded px-3 py-2" />
                     </div>
                     <div>
                         <label class="block text-sm font-medium mb-1">Описание</label>
                         <textarea v-model="formData.description" rows="3" class="w-full border rounded px-3 py-2"></textarea>
                     </div>
                     <div>
                         <label class="block text-sm font-medium mb-1">Дата</label>
                         <input type="date" v-model="formData.date" class="w-full border rounded px-3 py-2" />
                     </div>
                     <div class="flex items-center">
                         <input type="checkbox" v-model="formData.isConsidered" id="isCons" class="mr-2" />
                         <label for="isCons" class="text-sm">Учитываемые часы</label>
                     </div>
                </div>

                <div class="flex gap-3 mt-6">
                    <button @click="showModal = false" class="flex-1 px-4 py-2 bg-slate-100 rounded hover:bg-slate-200">Отмена</button>
                    <button @click="handleCreateHours" :disabled="isCreating" class="flex-1 px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50">
                        {{ isCreating ? 'Сохранение...' : 'Сохранить' }}
                    </button>
                </div>
           </div>
      </div>

      <!-- Report Modal -->
      <div v-if="showReportModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
           <div class="bg-white rounded-lg shadow-lg max-w-md w-full p-6">
                <h3 class="text-lg font-bold mb-4">Перенос в отчет</h3>
                <div class="bg-blue-50 p-4 rounded mb-4">
                    <p class="text-sm text-blue-900">Сумма к переносу: <strong>{{ totalStats.considered.toFixed(2) }} ч</strong></p>
                </div>
                <p class="text-sm text-slate-600 mb-6">Это создаст записи времени в штатном отчете Битрикс24.</p>
                <div class="flex gap-3">
                    <button @click="showReportModal = false" class="flex-1 px-4 py-2 bg-slate-100 rounded hover:bg-slate-200">Отмена</button>
                    <button @click="handleTransferToReport" :disabled="isReporting" class="flex-1 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50">
                        {{ isReporting ? 'Перенос...' : 'Перенести' }}
                    </button>
                </div>
           </div>
      </div>

  </div>
</template>
