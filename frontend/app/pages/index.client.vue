<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted } from 'vue'
import { SettingsIcon } from '@bitrix24/b24icons-vue/main'
import { BugIcon } from '@bitrix24/b24icons-vue/outline'
import { ActivityIcon } from '@bitrix24/b24icons-vue/main'
import { CrmLettersIcon } from '@bitrix24/b24icons-vue/crm'

const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()

useHead({
  title: t('page.index.seo.title')
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('IndexPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
// endregion ////

const isInit = ref(false)

// Meeting Modal State
const isMeetingModalOpen = ref(false)
const isMeetingSaving = ref(false)
const meetingError = ref<string | null>(null)
const groups = ref<any[]>([])
const formData = ref({
    date: new Date().toISOString().split('T')[0],
    hours: '',
    description: 'Встреча',
    projectId: '', 
    isConsidered: true
})
const currentUserId = ref<string>('')

const openMeetingModal = async () => {
    isMeetingModalOpen.value = true
    meetingError.value = null
    // Reset form but keep date if valid? Or reset all
    formData.value = {
        date: new Date().toISOString().split('T')[0],
        hours: '',
        description: 'Встреча',
        projectId: '', 
        isConsidered: true
    }
    
    // Fetch user groups for selector
    try {
        if (groups.value.length === 0) {
            // @ts-ignore
            const BX24 = window.BX24;
            // Get user ID first if needed
            // Actually we need to know who is current user to assign
            BX24.callMethod('user.current', {}, (res: any) => {
                 if(res.data()) currentUserId.value = res.data().ID;
            });
            
            BX24.callMethod('sonet_group.get', {
                ORDER: { NAME: 'ASC' },
                FILTER: { CLOSED: 'N' } // Only open groups? Or all user groups. 
                // Default checks permissions usually.
            }, (res: any) => {
                if (res.data()) {
                    groups.value = res.data();
                }
            })
        }
    } catch (e) {
        console.error(e)
    }
}

const closeMeetingModal = () => {
    isMeetingModalOpen.value = false
}

const handleSaveMeeting = () => {
    meetingError.value = null;
    if (!formData.value.projectId) {
        meetingError.value = "Выберите проект";
        return;
    }
    if (!formData.value.hours || parseFloat(formData.value.hours) <= 0) {
        meetingError.value = "Введите корректное время";
        return;
    }
    
    isMeetingSaving.value = true;
    
    // Find Group Name
    const group = groups.value.find(g => g.ID == formData.value.projectId);
    const groupName = group ? group.NAME : 'Unknown Project';
    
    // Constants (same as in other files)
    const HOURS_FIELD_CODE = 'ufCrm87_1761919617'
    const IS_CONSIDERED_FIELD_CODE = 'ufCrm87_1763717129'
    const PROJECT_ID_FIELD_CODE = 'ufCrm87_1764265626'
    const PROJECT_NAME_FIELD_CODE = 'ufCrm87_1764265641'
    const TASK_NAME_FIELD_CODE = 'ufCrm87_1764361585'
    const REFLECTION_DATE_FIELD_CODE = 'ufCrm87_1764446274'
    const EMPLOYEE_FIELD_CODE = 'ufCrm87_1761919601'
    const DESCRIPTION_FIELD_CODE = 'ufCrm87_1762026149771'
    
    // Smart Process ID 1164
    // @ts-ignore
    const BX24 = window.BX24;
    
    BX24.callMethod('crm.item.add', {
        entityTypeId: 1164,
        fields: {
            title: formData.value.description.substring(0, 255),
            [HOURS_FIELD_CODE]: parseFloat(formData.value.hours),
            [IS_CONSIDERED_FIELD_CODE]: formData.value.isConsidered ? 'Y' : 'N',
            [EMPLOYEE_FIELD_CODE]: currentUserId.value,
            assignedById: currentUserId.value,
            [DESCRIPTION_FIELD_CODE]: formData.value.description,
            createdTime: formData.value.date + 'T00:00:00',
            [PROJECT_ID_FIELD_CODE]: formData.value.projectId,
            [PROJECT_NAME_FIELD_CODE]: groupName,
            [REFLECTION_DATE_FIELD_CODE]: formData.value.date + 'T00:00:00',
            [TASK_NAME_FIELD_CODE]: 'Встреча/Без задачи'
        }
    }, (result: any) => {
        isMeetingSaving.value = false;
        if (result.error()) {
            meetingError.value = result.error().toString();
        } else {
            closeMeetingModal();
            // Optional: Success toast
            alert("Время успешно списано!");
        }
    });
}

// Tiles Configuration
// Tiles Configuration
const tiles = [
    {
        icon: ActivityIcon,
        title: 'Отчет по сотрудникам',
        description: 'Детальный отчет по часам сотрудников',
        action: () => router.push('/reports/employee'),
        color: 'bg-blue-50 text-blue-600'
    },
    {
        icon: CrmLettersIcon,
        title: 'Отчет по проектам',
        description: 'Сводка по проектам',
        action: () => router.push('/reports/project'), 
        color: 'bg-indigo-50 text-indigo-600'
    },
    {
        icon: ActivityIcon,
        title: 'Ежедневная нагрузка',
        description: 'Матрица часов по дням',
        action: () => router.push('/reports/daily'),
        color: 'bg-orange-50 text-orange-600'
    },
    {
        icon: SettingsIcon,
        title: 'Настройки',
        description: 'Настройки приложения',
        action: () => router.push('/settings'),
        color: 'bg-green-50 text-green-600'
    }
]

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle(t('page.index.seo.title'))
    
    // Auto-redirect if in Task Tab
    console.log('DEBUG: $b24.placement:', $b24.placement);
    
    // Check JSSDK wrapper properties
    // Based on logs: PlacementManager has #title: 'TASK_VIEW_TAB'. 
    // Trying public getter .title
    // @ts-ignore
    const placementCode = $b24.placement?.title || $b24.placement?.placement || ($b24.placement?.info && $b24.placement.info.placement);
    
    console.log('DEBUG: Resolved Placement Code:', placementCode);
    
    if (placementCode === 'TASK_VIEW_TAB') {
         console.log('DEBUG: Redirecting to /task-hours via JSSDK');
         router.push('/task-hours')
         return 
    }
    
    if (placementCode === 'SONET_GROUP_DETAIL_TAB') {
         console.log('DEBUG: Redirecting to /reports/project-report via JSSDK');
         router.push('/reports/project-report')
         return 
    }
    
    // Fallback: Use Global BX24 with init (Standard Pattern)
    // @ts-ignore
    if (typeof window.BX24 !== 'undefined') {
        // @ts-ignore
        window.BX24.init(() => {
            // @ts-ignore
            const rawPlacement = window.BX24.placement.info();
            console.log('DEBUG: Window Placement Info:', rawPlacement);
             if (rawPlacement && rawPlacement.placement === 'TASK_VIEW_TAB') {
                  console.log('DEBUG: Redirecting to /task-hours via Window');
                  router.push('/task-hours')
             } else if (rawPlacement && rawPlacement.placement === 'SONET_GROUP_DETAIL_TAB') {
                  console.log('DEBUG: Redirecting to /reports/project-report via Window');
                  router.push('/reports/project-report')
             }
        })
    }

    isInit.value = true
  } catch (error) {
    processErrorGlobal(error)
  }
})
// endregion ////
</script>

<template>
  <div class="flex flex-col min-h-screen bg-white w-full justify-center items-center p-6">
      <div v-if="isInit" class="w-full">
          <!-- Header -->
          <div class="mb-10 text-center">
              <h1 class="text-3xl font-bold text-gray-900 mb-2">Выберите отчет</h1>
              <p class="text-gray-500">Доступные отчеты и инструменты управления</p>
              
               <button @click="openMeetingModal" class="mt-6 bg-blue-600 text-white px-6 py-2.5 rounded-full font-medium hover:bg-blue-700 shadow-sm transition-all active:transform active:scale-95 flex items-center gap-2 mx-auto">
                   <svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24" fill="currentColor"><path d="M440-440H200v-80h240v-240h80v240h240v80H520v240h-80v-240Z"/></svg>
                   Списать время на встречи
               </button>
          </div>

          <!-- Grid -->
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              <div 
                  v-for="(tile, index) in tiles" 
                  :key="index"
                  @click="tile.action"
                  class="group relative p-8 rounded-xl border border-gray-100 hover:border-gray-200 bg-white shadow-sm hover:shadow-lg transition-all duration-300 cursor-pointer flex flex-col items-center text-center gap-4 h-full"
              >
                  <!-- Icon Box -->
                  <div :class="['p-4 rounded-full transition-colors duration-300', tile.color]">
                      <component :is="tile.icon" class="w-10 h-10" />
                  </div>
                  
                  <!-- Content -->
                  <div class="flex-grow flex flex-col justify-center">
                      <h3 class="text-xl font-semibold text-gray-900 mb-2 group-hover:text-blue-600 transition-colors">
                          {{ tile.title }}
                      </h3>
                      <p class="text-sm text-gray-500">
                          {{ tile.description }}
                      </p>
                  </div>

                  <!-- Arrow (Visual Hint) -->
                  <div class="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity text-gray-300">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                      </svg>
                  </div>
              </div>
          </div>
      </div>

        <!-- Meeting Modal -->
        <div v-if="isMeetingModalOpen" class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-white w-full max-w-5xl rounded-2xl shadow-xl overflow-hidden transform transition-all scale-100 border border-slate-100">
                 <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                    <h3 class="font-bold text-lg text-slate-800">Списание на встречи</h3>
                    <button @click="closeMeetingModal" class="text-slate-400 hover:text-slate-600 transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24" fill="currentColor"><path d="m256-200-56-56 224-224-224-224 56-56 224 224 224-224 56 56-224 224 224 224-56 56-224-224-224 224Z"/></svg>
                    </button>
                </div>
                
                <div class="p-6 space-y-4">
                     <div v-if="meetingError" class="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4 border border-red-100">
                        {{ meetingError }}
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Проект</label>
                        <select v-model="formData.projectId" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700">
                            <option value="" disabled>Выберите проект...</option>
                            <option v-for="group in groups" :key="group.ID" :value="group.ID">{{ group.NAME }}</option>
                        </select>
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Дата</label>
                            <input type="date" v-model="formData.date" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Часы</label>
                            <input type="number" step="0.5" v-model="formData.hours" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700" placeholder="0.0">
                        </div>
                    </div>
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Описание</label>
                        <textarea v-model="formData.description" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-slate-700 h-24 resize-none" placeholder="Детали встречи..."></textarea>
                    </div>

                     <div class="flex items-center gap-2">
                         <input type="checkbox" id="modalIsConsideredGlobal" v-model="formData.isConsidered" class="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500">
                         <label for="modalIsConsideredGlobal" class="text-sm text-slate-700 font-medium">Учитывать часы (Billable)</label>
                     </div>
                </div>

                <div class="p-6 border-t bg-slate-50 flex gap-3">
                    <button @click="closeMeetingModal" class="flex-1 bg-white text-slate-700 border border-slate-300 font-medium py-2.5 rounded-lg hover:bg-slate-50 transition-colors">
                        Отмена
                    </button>
                    <button @click="handleSaveMeeting" :disabled="isMeetingSaving" class="flex-1 bg-blue-600 text-white font-medium py-2.5 rounded-lg shadow-sm hover:bg-blue-700 active:transform active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                        {{ isMeetingSaving ? 'Сохранение...' : 'Сохранить' }}
                    </button>
                </div>
            </div>
        </div>
        
  </div>
</template>
