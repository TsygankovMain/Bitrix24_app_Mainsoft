<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useAppInit } from '../composables/useAppInit' 
import RecursiveTaskGroup from '../components/RecursiveTaskGroup.vue'
import type { B24Frame } from '@bitrix24/b24jssdk'

// --- CONFIGURATION ---
const TASK_ID_FIELD_CODE = 'ufCrm87_1761919581';
const EMPLOYEE_FIELD_CODE = 'ufCrm87_1761919601';
const HOURS_FIELD_CODE = 'ufCrm87_1761919617';
const IS_CONSIDERED_FIELD_CODE = 'ufCrm87_1763717129';
const DESCRIPTION_FIELD_CODE = 'ufCrm87_1762026149771';
const TASK_HIERARCHY_ID_FIELD_CODE = 'ufCrm87_1764191110';
const TASK_HIERARCHY_TITLE_FIELD_CODE = 'ufCrm87_1764191133';

// --- STATE ---
const isLoading = ref(true)
const error = ref<string | null>(null)
const taskTree = ref<any[]>([])
const users = ref<Record<string, string>>({})
const allUsers = ref<any[]>([])
const updatingItemId = ref<string | null>(null)
const mainTaskId = ref<string | null>(null)
const currentUserId = ref<string | null>(null)
// const showModal = ref(false) // Removed
// const showReportModal = ref(false) // Removed
const isCreating = ref(false)
// const isReporting = ref(false) // Removed
const modalError = ref<string | null>(null) // Reused as SidePanel Error
// const reportModalError = ref<string | null>(null) // Removed
const openTaskIds = ref(new Set<string>())
const formData = ref({
    hours: '',
    description: '',
    date: new Date().toISOString().split('T')[0],
    employeeId: '',
    targetTaskId: null as string | null,
    isConsidered: true
})

// Settings
const isSettingsOpen = ref(false)
const clientHourRate = ref(0)
const smartProcessId = ref(1164)

// --- HELPERS ---
// @ts-ignore
const callMethodPromise = (method: string, params: any): Promise<any> => {
    return new Promise((resolve, reject) => {
        // @ts-ignore
        const BX24 = window.BX24;
        BX24.callMethod(method, params, (result: any) => {
            if (result.error()) reject(result.error());
            else resolve(result.data());
        });
    });
};

const callBatchPromise = (commands: any): Promise<any> => {
    return new Promise((resolve) => {
        // @ts-ignore
        const BX24 = window.BX24;
        BX24.callBatch(commands, (result: any) => resolve(result));
    });
};

const getTaskHierarchy = async (initialTaskId: string) => {
    let currentTaskId: string | null = initialTaskId;
    const idPath: string[] = [];
    const titlePath: string[] = [];

    while (currentTaskId) {
        try {
            const result: any = await callMethodPromise('tasks.task.get', {
                taskId: currentTaskId,
                select: ['ID', 'TITLE', 'PARENT_ID']
            });
            const task = result.task;

            if (task) {
                idPath.unshift(task.id);
                titlePath.unshift(task.title);

                if (task.parentId && task.parentId !== '0') {
                    currentTaskId = task.parentId;
                } else {
                    currentTaskId = null;
                }
            } else {
                currentTaskId = null;
            }
        } catch (e) {
            console.error(`Error fetching task ${currentTaskId}:`, e);
            currentTaskId = null;
        }
    }
    return { idPath, titlePath };
}

const fetchData = async (currentTaskId: string) => {
    if (!smartProcessId.value) {
        error.value = "ID Смарт-процесса не указан.";
        isLoading.value = false;
        return;
    }
    
    isLoading.value = true;
    error.value = null;
    
    try {
        // 1. Root Task
        const rootTaskResult = await callMethodPromise('tasks.task.get', { taskId: currentTaskId, select: ['ID', 'TITLE'] });
        const rootTaskData = rootTaskResult.task;
        
        // 2. Subtasks (BFS)
        let allSubTasks = [];
        let queue = [currentTaskId];
        const processedIds = new Set([currentTaskId]);
        
        while (queue.length > 0) {
            const batchCmds = queue.map(id => ['tasks.task.list', {
                filter: { PARENT_ID: id },
                select: ['id', 'title', 'parentId']
            }]);
            const batchResult: any = await callBatchPromise(batchCmds);
            
            queue = [];
            
            for (const res of Object.values(batchResult) as any[]) {
                if (res && !res.error()) {
                    const tasks = res.data().tasks || [];
                    for (const task of tasks) {
                        if (!processedIds.has(task.id)) {
                            allSubTasks.push(task);
                            queue.push(task.id);
                            processedIds.add(task.id);
                        }
                    }
                }
            }
        }
        
        const allTasks = [{ id: rootTaskData.id, title: rootTaskData.title, parentId: null }, ...allSubTasks];
        const allTaskIds = allTasks.map(t => t.id);
        
        // 3. Smart Process Items
        const spBatchCmds = allTaskIds.map(taskId => ['crm.item.list', {
            entityTypeId: smartProcessId.value,
            filter: { [TASK_ID_FIELD_CODE]: taskId },
            select: ['id', 'title', 'createdTime', TASK_ID_FIELD_CODE, EMPLOYEE_FIELD_CODE, HOURS_FIELD_CODE, IS_CONSIDERED_FIELD_CODE, DESCRIPTION_FIELD_CODE]
        }]);
        
        const spResults: any = await callBatchPromise(spBatchCmds);
        const allItems = Object.values(spResults).flatMap((res: any) => (res && !res.error() && res.data().items) ? res.data().items : []);
        
        const itemsByTaskId: Record<string, any[]> = {};
        allItems.forEach((item: any) => {
             const tid = item[TASK_ID_FIELD_CODE];
             if (!itemsByTaskId[tid]) itemsByTaskId[tid] = [];
             itemsByTaskId[tid].push(item);
        });
        
        // 4. Build Tree Nodes
        const nodes: Record<string, any> = {};
        allTasks.forEach((task: any) => {
             const items = itemsByTaskId[task.id] || [];
             nodes[task.id] = {
                 taskId: task.id,
                 taskTitle: task.title,
                 parentId: task.parentId,
                 items: items,
                 totalConsidered: items.reduce((sum: number, item: any) => {
                     const isCons = item[IS_CONSIDERED_FIELD_CODE] === true || item[IS_CONSIDERED_FIELD_CODE] === 'Y';
                     return sum + (isCons ? (parseFloat(item[HOURS_FIELD_CODE]) || 0) : 0);
                 }, 0),
                 totalUnconsidered: items.reduce((sum: number, item: any) => {
                     const isCons = item[IS_CONSIDERED_FIELD_CODE] === true || item[IS_CONSIDERED_FIELD_CODE] === 'Y';
                     return sum + (!isCons ? (parseFloat(item[HOURS_FIELD_CODE]) || 0) : 0);
                 }, 0),
                 children: []
             };
        });
        
        // 5. Assemble Hierarchy
        const tree: any[] = [];
        Object.values(nodes).forEach(node => {
            if (node.parentId && nodes[node.parentId]) {
                nodes[node.parentId].children.push(node);
            } else if (String(node.taskId) === String(currentTaskId)) {
                tree.push(node);
            }
        });
        
        // 6. Cumulative Totals
        const calculateCumulativeTotals = (node: any) => {
            let childCons = 0;
            let childUncons = 0;
            
            if (node.children && node.children.length > 0) {
                node.children.forEach((child: any) => {
                    const totals = calculateCumulativeTotals(child);
                    childCons += totals.considered;
                    childUncons += totals.unconsidered;
                });
            }
            node.cumulativeConsidered = (node.totalConsidered || 0) + childCons;
            node.cumulativeUnconsidered = (node.totalUnconsidered || 0) + childUncons;
            
            return {
                considered: node.cumulativeConsidered,
                unconsidered: node.cumulativeUnconsidered
            };
        };
        
        tree.forEach(calculateCumulativeTotals);
        taskTree.value = tree;
        
        // 7. Users
        const empIds = [...new Set(allItems.map((item: any) => item[EMPLOYEE_FIELD_CODE]).filter(Boolean))];
        if (empIds.length > 0) {
            const userBatch = empIds.reduce((acc: any, id: unknown) => ({...acc, [`user_${id}`]: ['user.get', { ID: id }]}), {});
            const userResult: any = await callBatchPromise(userBatch);
            const usersData: Record<string, string> = {};
            empIds.forEach((id: unknown) => {
                const res = userResult[`user_${id}`];
                if (res && !res.error() && res.data()[0]) {
                    const user = res.data()[0];
                    usersData[String(id)] = `${user.NAME} ${user.LAST_NAME}`;
                } else {
                    usersData[String(id)] = `Пользователь #${id}`;
                }
            });
            users.value = usersData;
        }

    } catch (e: any) {
        console.error("Fetch Error:", e);
        error.value = e.message || "Ошибка загрузки данных";
    } finally {
        isLoading.value = false;
    }
};

const totalStats = computed(() => {
    let considered = 0, unconsidered = 0;
    taskTree.value.forEach(rootNode => {
        considered += rootNode.cumulativeConsidered || 0;
        unconsidered += rootNode.cumulativeUnconsidered || 0;
    });
    return { 
        totalConsidered: considered, 
        totalUnconsidered: unconsidered, 
        totalHours: considered + unconsidered 
    };
});

// Methods
const selectedTaskTitle = ref('');

const selectTaskForEntry = (taskId: string, title: string) => {
    formData.value.targetTaskId = taskId;
    selectedTaskTitle.value = title;
    // Don't clear form data aggressively, maybe user wants to add multiple entries
    if (!formData.value.hours) formData.value.hours = ''; 
    modalError.value = null; // Reusing this for side panel error
    console.log('DEBUG: Selected Task', taskId);
};

// handleOpenModal removed
// handleTransferToReport removed

const handleToggleHours = async (itemId: string) => {
    updatingItemId.value = itemId;
    let itemToUpdate: any = null;
    const findItem = (nodes: any[]) => {
        for (const node of nodes) {
            const found = node.items.find((i: any) => i.id === itemId);
            if (found) { itemToUpdate = found; return; }
            if (node.children.length > 0) findItem(node.children);
        }
    }
    findItem(taskTree.value);
    
    if (!itemToUpdate) {
        updatingItemId.value = null;
        return;
    }
    
    const currentIsConsidered = itemToUpdate[IS_CONSIDERED_FIELD_CODE] === true || itemToUpdate[IS_CONSIDERED_FIELD_CODE] === 'Y';
    
    // @ts-ignore
    const BX24 = window.BX24;
    BX24.callMethod('crm.item.update', {
        entityTypeId: smartProcessId.value,
        id: itemId,
        fields: {
            [IS_CONSIDERED_FIELD_CODE]: currentIsConsidered ? 'N' : 'Y'
        }
    }, (result: any) => {
        updatingItemId.value = null;
        if (mainTaskId.value) fetchData(mainTaskId.value);
    });
};

const handleCreateHours = async () => {
    modalError.value = null;
    if (!formData.value.hours || parseFloat(formData.value.hours) <= 0) { modalError.value = 'Некорректные часы'; return; }
    if (!formData.value.description.trim()) { modalError.value = 'Нет описания'; return; }
    if (!formData.value.targetTaskId) { modalError.value = 'Выберите задачу из списка'; return; }
    
    isCreating.value = true;
    
    try {
        const hierarchy = await getTaskHierarchy(formData.value.targetTaskId!);
        
        // @ts-ignore
        const BX24 = window.BX24;
        BX24.callMethod('crm.item.add', {
            entityTypeId: smartProcessId.value,
            fields: {
                title: formData.value.description.substring(0, 255),
                [HOURS_FIELD_CODE]: parseFloat(formData.value.hours),
                [IS_CONSIDERED_FIELD_CODE]: formData.value.isConsidered ? 'Y' : 'N',
                [TASK_ID_FIELD_CODE]: formData.value.targetTaskId,
                [EMPLOYEE_FIELD_CODE]: formData.value.employeeId,
                [DESCRIPTION_FIELD_CODE]: formData.value.description,
                createdTime: formData.value.date + 'T00:00:00',
                [TASK_HIERARCHY_ID_FIELD_CODE]: hierarchy.idPath,
                [TASK_HIERARCHY_TITLE_FIELD_CODE]: hierarchy.titlePath,
            }
        }, (result: any) => {
            isCreating.value = false;
            if (result.error()) {
                modalError.value = result.error().toString();
            } else {
                // Success: clear form mostly
                formData.value.hours = '';
                formData.value.description = '';
                // Keep Date and Employee
                // Refresh
                if (mainTaskId.value) fetchData(mainTaskId.value);
            }
        });
        
    } catch (e: any) {
        modalError.value = e.message;
        isCreating.value = false;
    }
};

const toggleGroup = (taskId: string) => {
    if (openTaskIds.value.has(taskId)) openTaskIds.value.delete(taskId);
    else openTaskIds.value.add(taskId);
};

const formatDate = (d: string) => d ? new Date(d).toLocaleDateString('ru-RU') : '-';

// --- CONFIGURATION ---
useHead({
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// @ts-ignore
const getBX24 = () => window.BX24;

const waitForBX24 = () => {
    return new Promise<void>((resolve, reject) => {
        let attempts = 0;
        const check = () => {
            if (getBX24()) {
                resolve();
            } else {
                attempts++;
                if (attempts > 20) { // 2 seconds (20 * 100ms)
                    reject(new Error("BX24 JS SDK not loaded"));
                } else {
                    setTimeout(check, 100);
                }
            }
        }
        check();
    });
};

// Init
onMounted(async () => {
    try {
        await waitForBX24();
    } catch (e) {
        error.value = "BX24 JS SDK not found. Open inside Bitrix24 or check internet connection.";
        isLoading.value = false;
        return;
    }
    
    // @ts-ignore
    const BX24 = window.BX24;
    
    BX24.init(() => {
        // @ts-ignore
        const placementInfo = BX24.placement.info();
        let tid: string | null = null;
        if (placementInfo && placementInfo.options) {
             let opts = placementInfo.options;
             if (typeof opts === 'string') {
                 try { opts = JSON.parse(opts); } catch(e) { opts = {}; }
             }
             tid = opts.ID || opts.taskId || opts.id || null;
        }
        
        if (!tid) {
            // Try getting from current slider if possible, but usually placement info is best.
            // fallback to see if we can get it from URL or something? 
             // tid = '123'; // Debug
             error.value = "Не удалось определить ID задачи (Placement Options пуст). Откройте как вкладку задачи.";
             isLoading.value = false;
             return;
        }
        
        mainTaskId.value = tid;
        openTaskIds.value.add(tid);
        
        // @ts-ignore
        BX24.callBatch({
            currentUser: ['user.current', {}],
            allUsers: ['user.get', { FILTER: { 'ACTIVE': 'Y' }, 'sort': 'LAST_NAME', 'order': 'ASC' }]
        }, (result: any) => {
             const curUser = result.currentUser && !result.currentUser.error() ? result.currentUser.data() : null;
             if (curUser) {
                 currentUserId.value = curUser.ID;
             }
             const users = result.allUsers && !result.allUsers.error() ? result.allUsers.data() : [];
             allUsers.value = users;
             
             fetchData(tid!);
        });
    });
});

// Watch smartProcessId usage
watch(smartProcessId, () => {
    if (mainTaskId.value) fetchData(mainTaskId.value);
});

// Auto-select main task when loaded
watch([mainTaskId, taskTree], () => {
    if (mainTaskId.value && !formData.value.targetTaskId && taskTree.value.length > 0) {
        // Find title for main task
        const findTitle = (nodes: any[]): string | null => {
            for (const node of nodes) {
                if (String(node.taskId) === String(mainTaskId.value)) return node.taskTitle;
                if (node.children) {
                    const found = findTitle(node.children);
                    if (found) return found;
                }
            }
            return null;
        }
        const title = findTitle(taskTree.value) || 'Текущая задача';
        selectTaskForEntry(mainTaskId.value, title);
    }
}, { immediate: true });

// Helpers for template (format currency)
const formatCurrency = (val: number) => val.toLocaleString('ru-RU', { style: 'currency', currency: 'RUB' });
</script>

<template>
    <div class="h-full flex bg-slate-50 min-h-screen overflow-hidden">
        <!-- LEFT: Task Tree (Scrollable) -->
        <main class="flex-1 flex flex-col min-w-0 border-r border-slate-200">
             <!-- Header Stats -->
             <div class="bg-white border-b p-4 grid grid-cols-2 md:grid-cols-4 gap-4 shrink-0">
                 <div class="px-3 py-2 bg-slate-50 rounded border">
                     <p class="text-xs text-slate-500 uppercase font-semibold">Всего</p>
                     <p class="text-xl font-bold text-blue-600">{{ totalStats.totalHours.toFixed(2) }} ч</p>
                 </div>
                 <div class="px-3 py-2 bg-slate-50 rounded border">
                     <p class="text-xs text-slate-500 uppercase font-semibold">Учитываемые</p>
                     <p class="text-xl font-bold text-green-600">{{ totalStats.totalConsidered.toFixed(2) }} ч</p>
                 </div>
                 <div class="px-3 py-2 bg-slate-50 rounded border">
                     <p class="text-xs text-slate-500 uppercase font-semibold">Не учитываемые</p>
                     <p class="text-xl font-bold text-red-600">{{ totalStats.totalUnconsidered.toFixed(2) }} ч</p>
                 </div>
                 
                 <!-- Settings Toggle -->
                 <div class="flex items-center justify-end">
                    <button @click="isSettingsOpen = !isSettingsOpen" class="text-slate-500 hover:text-slate-700 p-2 rounded hover:bg-slate-100 flex items-center gap-2">
                        <span class="text-sm">Настройки</span>
                        <span>{{ isSettingsOpen ? '▲' : '▼' }}</span>
                    </button>
                 </div>
             </div>
             
             <!-- Settings Panel Inline -->
             <div v-if="isSettingsOpen" class="bg-slate-50 border-b p-4 grid grid-cols-1 md:grid-cols-2 gap-4 shrink-0 transition-all">
                <div>
                    <label class="block text-xs font-semibold text-slate-700 mb-1">Стоимость часа</label>
                    <input type="number" v-model.number="clientHourRate" class="w-full border p-2 rounded bg-white text-sm" />
                </div>
                 <div>
                    <label class="block text-xs font-semibold text-slate-700 mb-1">ID Смарт-процесса</label>
                    <input type="number" v-model.number="smartProcessId" class="w-full border p-2 rounded bg-white text-sm" />
                </div>
            </div>

             <!-- Scrollable List -->
             <div class="flex-1 overflow-y-auto p-4 space-y-4">
                 <div v-if="isLoading" class="text-center py-10 text-slate-400">Загрузка структуры...</div>
                 <div v-else-if="error" class="text-center py-10 text-red-600 bg-red-50 rounded m-4">{{ error }}</div>
                 <template v-else-if="taskTree.length">
                     <div 
                        v-for="node in taskTree" 
                        :key="node.taskId" 
                        class="bg-white border rounded-lg overflow-hidden shadow-sm transition-shadow hover:shadow-md"
                        :class="{'ring-2 ring-blue-500 ring-offset-2': formData.targetTaskId === node.taskId}"
                     >
                        <div class="p-3 bg-slate-50 border-b flex justify-between items-center select-none group">
                            <div @click="toggleGroup(node.taskId)" class="cursor-pointer flex-1 flex items-center gap-2">
                                <span class="text-slate-400 transform transition-transform" :class="{'rotate-180': openTaskIds.has(node.taskId)}">▼</span>
                                <div>
                                    <h3 class="font-bold text-slate-800 text-sm md:text-base group-hover:text-blue-600 transition-colors">{{ node.taskTitle }}</h3>
                                    <p class="text-[10px] text-slate-400">ID: {{ node.taskId }}</p>
                                </div>
                            </div>
                            
                            <!-- Select Button -->
                            <div class="flex items-center gap-3">
                                <div class="text-right hidden sm:block">
                                    <span class="text-green-600 font-bold block text-sm">{{ node.cumulativeConsidered.toFixed(2) }}</span>
                                </div>
                                <button 
                                    @click="selectTaskForEntry(node.taskId, node.taskTitle)" 
                                    class="text-xs px-3 py-1.5 rounded-full border transition-colors"
                                    :class="formData.targetTaskId === node.taskId ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-300 hover:border-blue-400 hover:text-blue-500'"
                                >
                                    {{ formData.targetTaskId === node.taskId ? 'Выбрано' : 'Выбрать' }}
                                </button>
                            </div>
                        </div>
                        
                        <!-- Recursive Content -->
                        <div v-if="openTaskIds.has(node.taskId)">
                            <!-- Items List -->
                            <div v-for="item in node.items" :key="item.id" class="p-3 border-t flex justify-between items-start hover:bg-slate-50 pl-8">
                                <div>
                                    <p class="font-medium text-slate-700 text-sm">{{ item.title || 'Без названия' }}</p>
                                    <p class="text-[10px] text-slate-400">
                                        {{ users[item[EMPLOYEE_FIELD_CODE]] || 'Неизвестно' }} • {{ formatDate(item.createdTime) }}
                                    </p>
                                </div>
                                <div class="flex items-center gap-2">
                                    <span :class="{'text-green-600': item[IS_CONSIDERED_FIELD_CODE] === 'Y', 'text-red-600': item[IS_CONSIDERED_FIELD_CODE] !== 'Y'}" class="font-bold text-sm">
                                        {{ parseFloat(item[HOURS_FIELD_CODE] || 0).toFixed(2) }}
                                    </span>
                                    <button @click="handleToggleHours(item.id)" :disabled="updatingItemId === item.id" class="text-[10px] bg-slate-100 text-slate-600 px-2 py-1 rounded hover:bg-slate-200">
                                        {{ updatingItemId === item.id ? '...' : 'Изменить' }}
                                    </button>
                                </div>
                            </div>

                            <!-- Children Tasks -->
                            <div v-if="node.children && node.children.length" class="pl-4 border-t bg-slate-50/50 p-2 space-y-2">
                                 <RecursiveTaskGroup 
                                    v-for="child in node.children" 
                                    :key="child.taskId" 
                                    :node="child" 
                                    :clientHourRate="clientHourRate" 
                                    :users="users" 
                                    :openTaskIds="openTaskIds" 
                                    @toggle="toggleGroup" 
                                    @toggleHours="handleToggleHours"
                                    @select="selectTaskForEntry"
                                    :selectedTaskId="formData.targetTaskId" 
                                />
                            </div>
                        </div>
                     </div>
                 </template>
                 <div v-else class="text-center py-20 text-slate-400">Нет доступных задач для отображения.</div>
             </div>
        </main>

        <!-- RIGHT: Side Panel (Fixed Width) -->
        <aside class="w-96 bg-white border-l border-slate-200 flex flex-col shrink-0 z-10 shadow-xl">
            <div class="p-6 border-b flex-1 overflow-y-auto">
                <h2 class="text-lg font-bold text-slate-900 mb-1">Новая запись</h2>
                
                <div v-if="!formData.targetTaskId" class="p-4 bg-blue-50 text-blue-800 rounded-lg text-sm mb-6 border border-blue-100">
                    <p>← Выберите задачу из списка слева, чтобы добавить к ней часы.</p>
                </div>
                
                <div v-else class="mb-6">
                    <p class="text-xs text-slate-500 mb-1 uppercase tracking-wide">Задача</p>
                    <p class="font-medium text-slate-800 bg-slate-50 p-3 rounded border border-slate-200">{{ selectedTaskTitle }}</p>
                </div>

                <div class="space-y-5" :class="{'opacity-50 pointer-events-none': !formData.targetTaskId}">
                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1.5">Сотрудник</label>
                        <select v-model="formData.employeeId" class="w-full border-slate-300 rounded-md shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm">
                            <option v-for="u in allUsers" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                        </select>
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1.5">Дата</label>
                            <input type="date" v-model="formData.date" class="w-full border-slate-300 rounded-md shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm" />
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1.5">Часы</label>
                            <input type="number" v-model="formData.hours" step="0.5" min="0" placeholder="0.0" class="w-full border-slate-300 rounded-md shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm" />
                        </div>
                    </div>

                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1.5">Описание работ</label>
                        <textarea v-model="formData.description" rows="4" placeholder="Что было сделано..." class="w-full border-slate-300 rounded-md shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"></textarea>
                    </div>

                    <div class="flex items-center gap-2 pt-2">
                        <input type="checkbox" id="isConsidered" v-model="formData.isConsidered" class="rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                        <label for="isConsidered" class="text-sm text-slate-700 select-none">Учитывать часы (Billable)</label>
                    </div>
                    
                    <div v-if="modalError" class="p-3 bg-red-50 text-red-600 text-sm rounded border border-red-100">
                        {{ modalError }}
                    </div>
                </div>
            </div>
            
            <!-- Footer Actions -->
            <div class="p-6 border-t bg-slate-50">
                <button 
                    @click="handleCreateHours" 
                    :disabled="isCreating || !formData.targetTaskId" 
                    class="w-full bg-blue-600 text-white font-medium py-2.5 rounded-lg shadow-sm hover:bg-blue-700 active:transform active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {{ isCreating ? 'Сохранение...' : 'Сохранить запись' }}
                </button>
            </div>
        </aside>
    </div>
</template>

<script lang="ts">
// Recursive component definition
import { defineComponent } from 'vue';
export default defineComponent({
  name: 'TaskHoursPage',
});
</script>

