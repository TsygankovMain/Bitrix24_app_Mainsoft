<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'

// --- CONSTANTS ---
const HOURS_FIELD_CODE = 'ufCrm87_1761919617'
const IS_CONSIDERED_FIELD_CODE = 'ufCrm87_1763717129'
const PROJECT_ID_FIELD_CODE = 'ufCrm87_1764265626'
const PROJECT_NAME_FIELD_CODE = 'ufCrm87_1764265641'
const TASK_NAME_FIELD_CODE = 'ufCrm87_1764361585'
const REFLECTION_DATE_FIELD_CODE = 'ufCrm87_1764446274'
const EMPLOYEE_FIELD_CODE = 'ufCrm87_1761919601'
const DESCRIPTION_FIELD_CODE = 'ufCrm87_1762026149771'
const TASK_HIERARCHY_ID_FIELD_CODE = 'ufCrm87_1764191110'
const TASK_HIERARCHY_TITLE_FIELD_CODE = 'ufCrm87_1764191133'

// --- STATE ---
const isLoading = ref(true)
const error = ref<string | null>(null)
const items = ref<any[]>([])
const users = ref<Record<string, string>>({})
const currentGroupId = ref<string | null>(null)
const currentUserId = ref<string | null>(null)
const smartProcessId = ref<number>(1164) // Default, ideally from config

const isModalOpen = ref(false)
const modalError = ref<string | null>(null)
const isSaving = ref(false)

useHead({
  script: [
    {
      src: 'https://api.bitrix24.com/api/v1/',
      async: true,
      defer: true
    }
  ]
})

const formData = ref({
    hours: '',
    description: '',
    date: new Date().toISOString().split('T')[0],
    isConsidered: true,
    employeeId: ''
})

// --- LIFECYCLE ---
onMounted(async () => {
    // Wait for BX24
    let attempts = 0;
    while (typeof (window as any).BX24 === 'undefined' && attempts < 50) {
        await new Promise(r => setTimeout(r, 100));
        attempts++;
    }

    // @ts-ignore
    const BX24 = window.BX24;
    
    if (!BX24) {
        error.value = "Не удалось загрузить API Bitrix24. Попробуйте обновить страницу.";
        isLoading.value = false;
        return;
    }
    
    // Check context (Placement)
    const placement = BX24.placement.info();
    // For Project placement, usually options.GROUP_ID or options.ID depending on placement
    // Typical placement for Group App: 'SONET_GROUP_DETAIL_TAB'
    if (placement && placement.options && placement.options.GROUP_ID) {
        currentGroupId.value = placement.options.GROUP_ID;
    } else {
        // Fallback for dev/testing or if opened directly?
        // Maybe try to see if ID is passed
        // For now, if no Group ID, show error or maybe allow selection (but requirement said "embedding")
        // error.value = "Не удалось определить ID проекта (группы). Откройте приложение из группы Bitrix24."
        // return;
        
        // DEV MODE: Hardcode or allow empty
        // currentGroupId.value = '15'; // Dev test
    }

    if (!currentGroupId.value) {
        error.value = "Запустите приложение из группы Bitrix24"
        isLoading.value = false;
        return;
    }

    await loadUser();
    await fetchData();
})

// --- METHODS ---
const callMethodPromise = (method: string, params: any = {}): Promise<any> => {
    return new Promise((resolve, reject) => {
        // @ts-ignore
        const BX24 = window.BX24;
        BX24.callMethod(method, params, (result: any) => {
            if (result.error()) {
                reject(result.error());
            } else {
                resolve(result.data());
            }
        });
    });
};

const callBatchPromise = (calls: any): Promise<any> => {
    return new Promise((resolve, reject) => {
        // @ts-ignore
        const BX24 = window.BX24;
        BX24.callBatch(calls, (result: any) => {
             resolve(result); // Batch doesn't error globally usually
        });
    });
};

async function loadUser() {
    try {
        const res = await callMethodPromise('user.current');
        if (res) {
            currentUserId.value = res.ID;
            formData.value.employeeId = res.ID;
        }
    } catch (e) {
        console.error("User load error", e);
    }
}

async function fetchData() {
    isLoading.value = true;
    error.value = null;
    items.value = [];
    
    try {
        // 1. Fetch Items filtered by PROJECT_ID
        const listRes = await callMethodPromise('crm.item.list', {
            entityTypeId: smartProcessId.value,
            filter: { ['=' + PROJECT_ID_FIELD_CODE]: currentGroupId.value },
            select: [
                'id', 'title', 'createdTime', 
                HOURS_FIELD_CODE, IS_CONSIDERED_FIELD_CODE, 
                EMPLOYEE_FIELD_CODE, DESCRIPTION_FIELD_CODE,
                PROJECT_NAME_FIELD_CODE, TASK_NAME_FIELD_CODE,
                REFLECTION_DATE_FIELD_CODE
            ],
            order: { [REFLECTION_DATE_FIELD_CODE]: 'DESC' }
        });
        
        const rawItems = listRes.items || [];
        items.value = rawItems;
        
        // 2. Fetch Users
        const userIds = [...new Set(rawItems.map((i: any) => i[EMPLOYEE_FIELD_CODE]).filter((id: any) => id))];
        if (userIds.length > 0) {
            const userBatch = userIds.reduce((acc: any, id: unknown) => ({...acc, [`user_${id}`]: ['user.get', { ID: id }]}), {});
            const userResults: any = await callBatchPromise(userBatch);
            const usersData: Record<string, string> = {};
            userIds.forEach((id: unknown) => {
                const res = userResults[`user_${id}`];
                if (res && !res.error() && res.data() && res.data()[0]) {
                   const u = res.data()[0];
                   usersData[String(id)] = `${u.NAME} ${u.LAST_NAME}`.trim();
                }
            });
            users.value = usersData;
        }

    } catch (e: any) {
        error.value = "Ошибка загрузки данных: " + e.message;
    } finally {
        isLoading.value = false;
    }
}

const openModal = () => {
    isModalOpen.value = true;
    // Reset form
    formData.value = {
        hours: '',
        description: 'Встреча',
        date: new Date().toISOString().split('T')[0],
        isConsidered: true,
        employeeId: currentUserId.value || ''
    };
    modalError.value = null;
}

const closeModal = () => {
    isModalOpen.value = false;
}

const handleSaveMeeting = async () => {
    modalError.value = null;
    if (!formData.value.hours || parseFloat(formData.value.hours) <= 0) {
        modalError.value = "Введите корректное время";
        return;
    }
    if (!formData.value.description) {
        modalError.value = "Введите описание";
        return;
    }
    
    isSaving.value = true;
    
    try {
        // We need Project Name. 
        // Can optionally fetch it or just save ID. 
        // Ideally we should have it.
        // Let's rely on backend or ID. 
        // Or fetch it once on mount.
        let groupName = '';
        if (currentGroupId.value) {
             const gRes = await callMethodPromise('sonet_group.get', { ID: currentGroupId.value });
             // sonet_group.get returns array in data usually for list, but for get?
             // Actually sonet_group.get takes ID.
             if (Array.isArray(gRes) && gRes[0]) groupName = gRes[0].NAME;
             else if (gRes && gRes.NAME) groupName = gRes.NAME;
        }

        // @ts-ignore
        const BX24 = window.BX24;
        BX24.callMethod('crm.item.add', {
            entityTypeId: smartProcessId.value,
            fields: {
                title: formData.value.description.substring(0, 255),
                [HOURS_FIELD_CODE]: parseFloat(formData.value.hours),
                [IS_CONSIDERED_FIELD_CODE]: formData.value.isConsidered ? 'Y' : 'N',
                [EMPLOYEE_FIELD_CODE]: formData.value.employeeId,
                assignedById: formData.value.employeeId,
                [DESCRIPTION_FIELD_CODE]: formData.value.description,
                createdTime: formData.value.date + 'T00:00:00',
                [PROJECT_ID_FIELD_CODE]: currentGroupId.value,
                [PROJECT_NAME_FIELD_CODE]: groupName,
                [REFLECTION_DATE_FIELD_CODE]: formData.value.date + 'T00:00:00',
                // No Task ID
                [TASK_NAME_FIELD_CODE]: 'Встреча/Без задачи'
            }
        }, (result: any) => {
            isSaving.value = false;
            if (result.error()) {
                modalError.value = result.error().toString();
            } else {
                closeModal();
                fetchData();
            }
        });
        
    } catch (e: any) {
        isSaving.value = false;
        modalError.value = e.message;
    }
}
</script>

<template>
    <div class="h-screen flex flex-col bg-slate-50 font-sans text-slate-800">
        <!-- Header -->
        <header class="bg-white border-b px-6 py-4 flex items-center justify-between shrink-0 shadow-sm z-10">
            <div>
                <h1 class="text-xl font-bold flex items-center gap-2 text-slate-800">
                    <span class="material-symbols-outlined text-purple-600">topic</span>
                    Отчет по проекту
                </h1>
                <p class="text-xs text-slate-500 mt-1" v-if="currentGroupId">ID Проекта: {{ currentGroupId }}</p>
            </div>
            <div class="flex gap-2">
                 <button @click="fetchData" class="p-2 text-slate-500 hover:text-blue-600 transition-colors rounded-full hover:bg-blue-50">
                    <span class="material-symbols-outlined">refresh</span>
                </button>
            </div>
        </header>

        <!-- Content -->
        <main class="flex-1 overflow-auto p-6">
            <div v-if="isLoading" class="flex justify-center items-center h-64">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
            
            <div v-else-if="error" class="bg-red-50 text-red-600 p-4 rounded-lg flex items-center gap-3 border border-red-100 shadow-sm">
                <span class="material-symbols-outlined">error</span>
                {{ error }}
            </div>
            
            <div v-else>
                 <div class="flex justify-between items-center mb-6">
                    <div class="flex gap-4">
                        <div class="bg-white px-4 py-3 rounded-xl shadow-sm border border-slate-100">
                            <div class="text-xs text-slate-400 uppercase tracking-wider font-medium mb-1">Всего часов</div>
                            <div class="text-2xl font-bold text-slate-700">
                                {{ items.reduce((sum, i) => sum + (parseFloat(i[HOURS_FIELD_CODE]) || 0), 0).toFixed(2) }}
                            </div>
                        </div>
                    </div>
                    <button @click="openModal" class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium flex items-center gap-2 shadow-sm transition-all active:transform active:scale-95">
                        <span class="material-symbols-outlined text-[20px]">add_circle</span>
                        Списать на встречи
                    </button>
                </div>

                <div class="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-slate-500 uppercase text-xs font-semibold border-b border-slate-200">
                            <tr>
                                <th class="px-6 py-4">Дата</th>
                                <th class="px-6 py-4">Сотрудник</th>
                                <th class="px-6 py-4">Задача / Описание</th>
                                <th class="px-6 py-4 text-right">Часы</th>
                                <th class="px-6 py-4 text-center">Учет</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            <tr v-for="item in items" :key="item.id" class="hover:bg-slate-50 transition-colors">
                                <td class="px-6 py-4 whitespace-nowrap text-slate-600">
                                    {{ item[REFLECTION_DATE_FIELD_CODE] ? new Date(item[REFLECTION_DATE_FIELD_CODE]).toLocaleDateString() : (item.createdTime ? new Date(item.createdTime).toLocaleDateString() : '-') }}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap font-medium text-slate-700">
                                    <div class="flex items-center gap-2">
                                        <div class="w-6 h-6 rounded-full bg-slate-200 text-slate-500 flex items-center justify-center text-[10px] font-bold">
                                            {{ (users[item[EMPLOYEE_FIELD_CODE]] || '?')[0] }}
                                        </div>
                                        {{ users[item[EMPLOYEE_FIELD_CODE]] || 'Неизвестный' }}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                     <div class="font-medium text-slate-800">{{ item[TASK_NAME_FIELD_CODE] || 'Без задачи' }}</div>
                                     <div class="text-xs text-slate-500 mt-1 line-clamp-1">{{ item.title }}</div>
                                </td>
                                <td class="px-6 py-4 text-right font-bold text-slate-700">
                                    {{ parseFloat(item[HOURS_FIELD_CODE] || 0).toFixed(2) }}
                                </td>
                                <td class="px-6 py-4 text-center">
                                     <span 
                                        :class="(item[IS_CONSIDERED_FIELD_CODE] === 'Y' || item[IS_CONSIDERED_FIELD_CODE] === true) ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'"
                                        class="px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider"
                                     >
                                        {{ (item[IS_CONSIDERED_FIELD_CODE] === 'Y' || item[IS_CONSIDERED_FIELD_CODE] === true) ? 'Да' : 'Нет' }}
                                     </span>
                                </td>
                            </tr>
                            <tr v-if="items.length === 0">
                                <td colspan="5" class="px-6 py-12 text-center text-slate-400">
                                    Нет записей для этого проекта
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </main>

        <!-- Modal -->
        <div v-if="isModalOpen" class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-white w-full max-w-5xl rounded-2xl shadow-xl overflow-hidden transform transition-all scale-100 border border-slate-100">
                 <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                    <h3 class="font-bold text-lg text-slate-800">Списание на встречи</h3>
                    <button @click="closeModal" class="text-slate-400 hover:text-slate-600 transition-colors">
                        <span class="material-symbols-outlined">close</span>
                    </button>
                </div>
                
                <div class="p-6 space-y-4">
                     <div v-if="modalError" class="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4 border border-red-100">
                        {{ modalError }}
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Дата</label>
                        <input type="date" v-model="formData.date" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700">
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Часы</label>
                        <input type="number" step="0.5" v-model="formData.hours" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700" placeholder="0.0">
                    </div>
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Описание</label>
                        <textarea v-model="formData.description" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-slate-700 h-24 resize-none" placeholder="Детали встречи..."></textarea>
                    </div>

                     <div class="flex items-center gap-2">
                         <input type="checkbox" id="modalIsConsidered" v-model="formData.isConsidered" class="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500">
                         <label for="modalIsConsidered" class="text-sm text-slate-700 font-medium">Учитывать часы (Billable)</label>
                     </div>
                </div>

                <div class="p-6 border-t bg-slate-50 flex gap-3">
                    <button @click="closeModal" class="flex-1 bg-white text-slate-700 border border-slate-300 font-medium py-2.5 rounded-lg hover:bg-slate-50 transition-colors">
                        Отмена
                    </button>
                    <button @click="handleSaveMeeting" :disabled="isSaving" class="flex-1 bg-blue-600 text-white font-medium py-2.5 rounded-lg shadow-sm hover:bg-blue-700 active:transform active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                        {{ isSaving ? 'Сохранение...' : 'Сохранить' }}
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>
