<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import * as Helper from '@bitrix24/b24jssdk'

// --- ICONS ---
// Using Material Symbols directly via class "material-symbols-outlined" 
// assuming they are loaded via nuxt.config head link.

const { t, locales: localesI18n, setLocale } = useI18n()
const { $logger, initApp, processErrorGlobal } = useAppInit('TaskPage')
const { $initializeB24Frame } = useNuxtApp()

let $b24: null | B24Frame = null

// --- STATE ---
const isInit = ref(false)
const isLoading = ref(true)
const error = ref<string | null>(null)
const initError = ref<string | null>(null)

const config = ref<any>(null)
const clientHourRate = ref(3000)

const rootTaskId = ref<string | null>(null)
const taskTree = ref<any[]>([])

// Modals
const editingItem = ref<any>(null)
const isReportModalOpen = ref(false)
const isReporting = ref(false)

// Users Map
const usersMap = ref<Record<string, any>>({})

// --- CONFIG CONSTANTS (Fallbacks) ---
const BACKEND_MAPPING = {
    'id_zadachi': 'TASK_ID',
    'sotrudnik': 'EMPLOYEE',
    'kolichestvo_chasov': 'HOURS',
    'uchitivaem': 'IS_CONSIDERED',
    'opisanie': 'DESCRIPTION',
    'id_zadach_ierarhiya': 'TASK_HIERARCHY',
    'title_zadach_ierarhiya': 'TITLE_HIERARCHY'
}

// --- INIT LOGIC ---

onMounted(async () => {
    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)
        
        // 1. Get Placement Info
        // @ts-ignore
        const placementInfo = $b24.placement.info()
        const tid = placementInfo.options?.taskId || placementInfo.options?.ID || placementInfo.options?.id

        if (!tid) {
            error.value = "Не передан ID задачи. Откройте приложение во вкладке задачи."
            isLoading.value = false
            return
        }
        rootTaskId.value = tid

        // 2. Load Config & Users
        await loadConfigAndUsers()
        
        // 3. Load Data
        if (config.value && !initError.value) {
            await loadData(rootTaskId.value!)
        }

        isInit.value = true
    } catch (e: any) {
        processErrorGlobal(e)
        error.value = e.message
        isLoading.value = false
    }
})

async function loadConfigAndUsers() {
    return new Promise<void>((resolve) => {
        // @ts-ignore
        $b24.callBatch({
            users: ['user.get', { FILTER: { 'ACTIVE': 'Y' }, 'sort': 'LAST_NAME', 'order': 'ASC' }],
            appParam: ['app.option.get', {}]
        }, (res: any) => {
            // Users
            if (res.users && !res.users.error()) {
                const map: Record<string, any> = {}
                res.users.data().forEach((u: any) => map[u.ID] = u)
                usersMap.value = map
            }

            // Config
            if (res.appParam && !res.appParam.error()) {
                try {
                    const result = res.appParam.data()
                    if (result && result.timestamp_config) {
                        const rawConfig = JSON.parse(result.timestamp_config)
                        
                        const spId = rawConfig.sp_entity_type_id
                        const backendFields = rawConfig.fields_mapping || {}
                        
                        const fields: any = {}
                        Object.entries(BACKEND_MAPPING).forEach(([backendKey, frontendKey]) => {
                            if (backendFields[backendKey]) {
                                fields[frontendKey] = backendFields[backendKey]
                            }
                        })

                        if (!spId || !fields.TASK_ID || !fields.HOURS) {
                            throw new Error("Неполная конфигурация.")
                        }

                        config.value = {
                            DEFAULT_SMART_PROCESS_ID: spId,
                            FIELDS: fields
                        }
                    } else {
                        throw new Error("Конфигурация не найдена. Переустановите приложение.")
                    }
                } catch (e: any) {
                    console.error("Config Error:", e)
                    initError.value = e.message
                }
            } else {
                initError.value = "Ошибка получения настроек приложения."
            }
            resolve()
        })
    })
}


// --- DATA LOADING (BFS) ---

async function loadData(taskId: string) {
    if (!config.value) return
    isLoading.value = true
    error.value = null

    const FIELDS = config.value.FIELDS
    const SMART_PROCESS_ID = config.value.DEFAULT_SMART_PROCESS_ID

    try {
        // 1. Root Task
        const rootTaskRes = await callMethodPromise('tasks.task.get', { taskId, select: ['ID', 'TITLE'] })
        // @ts-ignore
        const rootTask = rootTaskRes.task

        // 2. BFS Subtasks
        let allTasks = [{ id: rootTask.id, title: rootTask.title, parentId: null }]
        let queue = [rootTask.id]
        let processed = new Set([rootTask.id])
        
        // Safety limit
        let iterations = 0
        while(queue.length > 0 && iterations < 50) {
            const batch: any[] = []
            const currentLevelIds = queue.splice(0, 50)
            
            currentLevelIds.forEach(pid => {
                batch.push(['tasks.task.list', { filter: { PARENT_ID: pid }, select: ['ID', 'TITLE', 'PARENT_ID', 'GROUP_ID'] }])
            })

            if (batch.length === 0) break

            const results = await callBatchPromise(batch)
            
            // @ts-ignore
            Object.values(results).forEach((res: any) => {
                if (!res.error()) {
                    const tasks = res.data().tasks || []
                    tasks.forEach((t: any) => {
                        if (!processed.has(t.id)) {
                            processed.add(t.id)
                            allTasks.push({ id: t.id, title: t.title, parentId: t.parentId })
                            queue.push(t.id)
                        }
                    })
                }
            })
            iterations++
        }

        // 3. Load Items
        const allTaskIds = allTasks.map(t => t.id)
        const CHUNK_SIZE = 50
        let allItems: any[] = []

        for (let i = 0; i < allTaskIds.length; i += CHUNK_SIZE) {
            const chunk = allTaskIds.slice(i, i + CHUNK_SIZE)
            const batchCmds = chunk.map(tid => ['crm.item.list', { 
                entityTypeId: SMART_PROCESS_ID,
                filter: { [FIELDS.TASK_ID]: tid },
                select: ['id', 'createdTime', FIELDS.TASK_ID, FIELDS.EMPLOYEE, FIELDS.HOURS, FIELDS.IS_CONSIDERED, FIELDS.DESCRIPTION, 'TITLE']
            }])
            
            const chunkResults = await callBatchPromise(batchCmds)
             // @ts-ignore
            Object.values(chunkResults).forEach((res: any) => {
                if(!res.error()) allItems.push(...res.data().items)
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
                const u = usersMap.value[empId]
                const empName = u ? `${u.NAME} ${u.LAST_NAME}` : `User ${empId}`

                nodesMap[tid].items.push({
                    id: item.id,
                    title: item.title,
                    createdTime: item.createdTime,
                    hours: hours,
                    isConsidered: isConsidered,
                    description: item[FIELDS.DESCRIPTION] || '',
                    employeeId: empId,
                    employeeName: empName
                })
                
                if (isConsidered) nodesMap[tid].totalConsidered += hours
                else nodesMap[tid].totalUnconsidered += hours
            }
        })

        const roots: any[] = []
        Object.values(nodesMap).forEach(node => {
            // @ts-ignore
            if (node.parentId && nodesMap[node.parentId]) {
                // @ts-ignore
                nodesMap[node.parentId].children.push(node)
            } else if (String(node.taskId) === String(taskId)) {
                roots.push(node) 
            }
        })

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
        isLoading.value = false

    } catch (e: any) {
        console.error(e)
        error.value = e.message || e.toString()
        isLoading.value = false
    }
}

// --- HELPERS ---

function callMethodPromise(method: string, params: any): Promise<any> {
    return new Promise((resolve, reject) => {
        // @ts-ignore
        $b24.callMethod(method, params, (res: any) => {
            if (res.error()) reject(res.error())
            else resolve(res.data())
        })
    })
}

function callBatchPromise(calls: any[]): Promise<any> {
    return new Promise((resolve) => {
         // @ts-ignore
        $b24.callBatch(calls, (res: any) => resolve(res))
    })
}

// --- ACTIONS ---

async function handleSaveItem(data: any) {
    if (!config.value) return
    const { id, hours, isConsidered, description, employeeId } = data
    // Optimistic update omitted for brevity
    
    isLoading.value = true // Show loading strictly? Or just background. Let's do background reload.
    
    // @ts-ignore
    $b24.callMethod('crm.item.update', {
        entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
        id: id,
        fields: {
            [config.value.FIELDS.HOURS]: hours,
            [config.value.FIELDS.IS_CONSIDERED]: isConsidered ? 'Y' : 'N',
            [config.value.FIELDS.DESCRIPTION]: description,
            [config.value.FIELDS.EMPLOYEE]: employeeId
        }
    }, (res: any) => {
        if (rootTaskId.value) loadData(rootTaskId.value) // reload
    })
    
    editingItem.value = null
}

function handleExportExcel() {
    // Basic CSV export for now as no XLSX lib installed in Nuxt deps yet
    // Or we can assume XLSX is available globally if added to head?
    // Let's implement simple CSV to be safe without external deps
    
    let csvContent = "data:text/csv;charset=utf-8," 
    csvContent += "Type,Title,Employee,Date,Hours Total,Hours Billable,Amount,Comment\n"

    const traverse = (node: any, depth = 0) => {
        const indent = "   ".repeat(depth)
        const row = [
            "Task",
            `"${indent}${node.taskTitle.replace(/"/g, '""')}"`,
            "",
            "",
            node.cumulativeConsidered + node.cumulativeUnconsidered,
            node.cumulativeConsidered,
            node.cumulativeConsidered * clientHourRate.value,
            ""
        ]
        csvContent += row.join(",") + "\n"

        node.items.forEach((item: any) => {
            const iRow = [
                "Item",
                `"${indent} - ${item.title}"`,
                item.employeeName,
                new Date(item.createdTime).toLocaleDateString(),
                item.hours,
                item.isConsidered ? item.hours : 0,
                item.isConsidered ? (item.hours * clientHourRate.value) : 0,
                `"${(item.description || '').replace(/"/g, '""')}"`
            ]
            csvContent += iRow.join(",") + "\n"
        })
        node.children.forEach((c: any) => traverse(c, depth + 1))
    }

    taskTree.value.forEach(root => traverse(root))

    const encodedUri = encodeURI(csvContent)
    const link = document.createElement("a")
    link.setAttribute("href", encodedUri)
    link.setAttribute("download", `report_task_${rootTaskId.value}.csv`)
    document.body.appendChild(link)
    link.click()
}

function handleTransferToReport() {
    isReporting.value = true
    const batch: any[] = []
    
    const collect = (nodes: any[]) => {
        nodes.forEach(node => {
            node.items.forEach((item: any) => {
                if (item.isConsidered && item.hours > 0) {
                    batch.push(['task.elapseditem.add', {
                        TASKID: node.taskId,
                        FIELDS: {
                            SECONDS: Math.round(item.hours * 3600),
                            COMMENT_TEXT: item.description || `Отражение часов: ${item.title}`,
                            USER_ID: item.employeeId
                        }
                    }])
                }
            })
            if (node.children) collect(node.children)
        })
    }
    
    collect(taskTree.value)
    
    if (batch.length === 0) {
        alert("Нет данных для переноса (0 учтенных часов).")
        isReporting.value = false
        isReportModalOpen.value = false
        return
    }

     // @ts-ignore
    $b24.callBatch(batch, (res: any) => {
        isReporting.value = false
        isReportModalOpen.value = false
        alert("Часы успешно перенесены в стандартный отчет Битрикс24!")
    })
}

</script>

<template>
<div class="flex flex-col h-full bg-slate-50 min-h-screen text-slate-800">
    
    <!-- HEADER -->
    <div class="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between sticky top-0 z-10 shadow-sm">
        <div class="flex items-center gap-3">
             <div class="bg-blue-600 p-2 rounded-lg text-white">
                <span class="material-symbols-outlined text-xl">schedule</span>
            </div>
            <div>
                <h1 class="text-xl font-bold text-slate-900">Отражение часов</h1>
                <p class="text-xs text-slate-500">Учет трудозатрат по иерархии задач</p>
            </div>
        </div>
        
        <div class="flex items-center gap-3">
            <button @click="handleExportExcel" class="px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-700 hover:bg-slate-50 text-sm font-medium flex items-center gap-2">
                <span class="material-symbols-outlined">download</span>
                <span>Excel (CSV)</span>
            </button>
            <button @click="isReportModalOpen = true" class="px-4 py-2 bg-blue-600 rounded-lg text-white hover:bg-blue-700 text-sm font-medium flex items-center gap-2 shadow-sm shadow-blue-200">
                <span class="material-symbols-outlined">send</span>
                <span>В отчет Битрикс</span>
            </button>
        </div>
    </div>

    <!-- CONTENT -->
    <div class="flex-grow p-6 overflow-auto">
        
        <!-- LOADING -->
        <div v-if="isLoading" class="flex flex-col items-center justify-center h-64 text-slate-400">
             <span class="material-symbols-outlined text-4xl animate-spin text-blue-500 mb-4">progress_activity</span>
             <p>Загрузка данных...</p>
        </div>

        <!-- ERROR -->
        <div v-if="initError || error" class="flex justify-center">
            <div class="bg-red-50 border border-red-200 p-6 rounded-xl max-w-lg text-center">
                <span class="material-symbols-outlined text-4xl text-red-500 mb-2">error</span>
                <h3 class="text-lg font-bold text-red-700 mb-2">Ошибка</h3>
                <p class="text-red-600">{{ initError || error }}</p>
            </div>
        </div>

        <!-- TREE -->
        <div v-if="!isLoading && !initError && !error" class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div class="bg-slate-50 border-b border-slate-200 px-4 py-3 text-xs font-semibold text-slate-500 uppercase flex">
                <div class="flex-1">Задача / Запись</div>
                <div class="w-24 text-right">Сумма</div>
                <div class="w-20 text-right">Учтено</div>
                <div class="w-20 text-right">Не учтено</div>
            </div>
            
            <TaskNode 
                v-for="node in taskTree" 
                :key="node.taskId" 
                :node="node" 
                :rate="clientHourRate"
                @edit="editingItem = $event"
            />
        </div>
    </div>

    <!-- MODAL EDIT -->
    <div v-if="editingItem" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden animate-fade-in">
            <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                <h3 class="font-bold text-slate-800">Редактирование</h3>
                <button @click="editingItem = null" class="text-slate-400 hover:text-slate-600"><span class="material-symbols-outlined">close</span></button>
            </div>
            <div class="p-6 space-y-4">
                 <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">Сотрудник</label>
                    <select v-model="editingItem.employeeId" class="w-full border-slate-300 rounded-lg p-2 border text-sm">
                        <option v-for="u in usersMap" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-4">
                     <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1">Часы</label>
                        <input type="number" v-model="editingItem.hours" class="w-full border-slate-300 rounded-lg p-2 border text-sm" step="0.5">
                    </div>
                    <div class="flex items-end pb-2">
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input type="checkbox" v-model="editingItem.isConsidered" class="w-4 h-4 text-blue-600 rounded">
                            <span class="text-sm font-medium">Учитывать?</span>
                        </label>
                    </div>
                </div>
                 <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">Описание</label>
                    <textarea v-model="editingItem.description" class="w-full border-slate-300 rounded-lg p-2 border text-sm h-24"></textarea>
                </div>
            </div>
            <div class="px-6 py-4 border-t border-slate-100 bg-slate-50 flex justify-end gap-3">
                <button @click="editingItem = null" class="px-4 py-2 border rounded-lg text-slate-600 hover:bg-white bg-white">Отмена</button>
                <button @click="handleSaveItem(editingItem)" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Сохранить</button>
            </div>
        </div>
    </div>
    
     <!-- MODAL REPORT -->
    <div v-if="isReportModalOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-sm overflow-hidden animate-fade-in text-center p-6">
            <span class="material-symbols-outlined text-4xl text-blue-500 mb-4">cloud_upload</span>
            <h3 class="font-bold text-lg mb-2">Отправить в отчет?</h3>
            <p class="text-sm text-slate-500 mb-6">Все "Учтенные" часы будут добавлены в задачи Битрикс24 как отработанное время.</p>
            <div class="flex justify-center gap-3">
                 <button @click="isReportModalOpen = false" class="px-4 py-2 border rounded-lg text-slate-600 hover:bg-slate-50">Отмена</button>
                 <button @click="handleTransferToReport" :disabled="isReporting" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2">
                    <span v-if="isReporting" class="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                    <span>{{ isReporting ? 'Отправка...' : 'Подтвердить' }}</span>
                 </button>
            </div>
        </div>
    </div>

</div>
</template>

<style scoped>
/* Basic Animations */
.animate-fade-in { animation: fadeIn 0.2s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
</style>
