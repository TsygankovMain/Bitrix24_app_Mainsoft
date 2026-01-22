<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'

const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()
const apiStore = useApiStore()

useHead({
  title: 'Ежедневная нагрузка',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init
const { $logger, initApp, processErrorGlobal } = useAppInit('DailyReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

// Report State
const reportData = ref<{ header_days: any[], rows: any[] } | null>(null)
const dateFrom = ref('')
const dateTo = ref('')
const isInit = ref(false)
const domain = ref('') // Store domain for links

// Filters
const filterOptions = ref<{ employees: any[], projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string|number)[]>([])
const selectedProjects = ref<(string|number)[]>([])

// Modal State
const showModal = ref(false)
const modalData = ref<any>(null) // { employeeName, date, items: [] }

async function fetchFilterOptions() {
    try {
        filterOptions.value = await apiStore.getFilterOptions()
    } catch (e) {
        processErrorGlobal(e)
    }
}

async function fetchReport() {
    isLoading.value = true
    try {
        await apiStore.syncTimesheets()
        reportData.value = await apiStore.getReportDailyWorkload(
            dateFrom.value, 
            dateTo.value, 
            selectedEmployees.value as string[], 
            selectedProjects.value as string[]
        )
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}


// Excel Export
import * as XLSX from 'xlsx'

function handleExportExcel() {
    if (!reportData.value) return;

    const exportData: any[] = [];
    const days = reportData.value.header_days;

    reportData.value.rows.forEach(row => {
        const rowData: any = {
            "Сотрудник": row.employee.name
        };
        
        days.forEach(day => {
            const dayInfo = row.days[day.date];
            rowData[day.date] = dayInfo.total > 0 ? dayInfo.total : '';
        });

        exportData.push(rowData);
    });

    const worksheet = XLSX.utils.json_to_sheet(exportData);

    // Adjust Column Widths
    const cols = [{ wch: 30 }]; // Employee Name column
    // Add width for date columns
    reportData.value.header_days.forEach(() => {
        cols.push({ wch: 5 }); // Minimal width for hours
    });
    worksheet['!cols'] = cols;

    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Ежедневная нагрузка");
    XLSX.writeFile(workbook, `Report_Daily_${dateFrom.value}_${dateTo.value}.xlsx`);
}

function openDetail(employeeName: string, date: string, items: any[]) {
    if (!items || items.length === 0) return
    modalData.value = {
        employeeName,
        date,
        items
    }
    showModal.value = true
}

function closeModal() {
    showModal.value = false
    modalData.value = null
}

const openTask = (id: string | number) => {
    // Attempt to use global BX24 or window.open
    // @ts-ignore
    const BX24 = window.BX24;
    
    if (typeof BX24 !== 'undefined') {
        BX24.openPath(`/company/personal/user/0/tasks/task/view/${id}/`)
    } else {
        window.open(`/company/personal/user/0/tasks/task/view/${id}/`, '_blank')
    }
}

function getCellColorClass(status: string) {
    if (status === 'orange') return 'bg-orange-600 text-white hover:bg-orange-700 cursor-pointer shadow-sm'
    if (status === 'green') return 'bg-green-600 text-white hover:bg-green-700 cursor-pointer shadow-sm'
    if (status === 'yellow') return 'bg-yellow-300 text-yellow-900 hover:bg-yellow-400 cursor-pointer shadow-sm'
    return 'bg-gray-50 text-gray-400' // neutral
}

onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    
    // Extract domain safely
    const b24Any = $b24 as any
    domain.value = b24Any?.auth?.domain || b24Any?.getAuthData?.()?.domain || ''
    
    await $b24.parent.setTitle('Ежедневная нагрузка') 
    isInit.value = true
    
    await fetchFilterOptions()
    
    // Default range: Current Month
    const now = new Date()
    dateFrom.value = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0] ?? ''
    dateTo.value = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().split('T')[0] ?? ''

    await fetchReport()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="flex flex-col gap-4 p-4 min-h-screen bg-white dark:bg-gray-900">
      <div class="mb-4 flex justify-between items-center">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <div class="flex flex-col gap-6" v-if="isInit">
         <!-- Filters Header -->
         <div class="flex flex-col gap-4 bg-gray-50 p-4 rounded-lg">
             <div class="flex flex-row justify-between items-center w-full">
                 <h2 class="text-xl font-bold text-gray-900">Ежедневная нагрузка</h2>
                 <div class="flex gap-2">
                    <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                    <B24Button label="Обновить" @click="fetchReport" loading-auto />
                 </div>
             </div>
             
             <div class="flex flex-wrap gap-4 items-end">
                 <DateRangeFilter 
                     v-model:dateFrom="dateFrom" 
                     v-model:dateTo="dateTo" 
                     @change="fetchReport"
                 />
                 <MultiSelectFilter 
                     label="Сотрудники" 
                     :options="filterOptions.employees" 
                     v-model="selectedEmployees" 
                     @update:modelValue="fetchReport"
                 />
                 <MultiSelectFilter 
                     label="Проекты" 
                     :options="filterOptions.projects" 
                     v-model="selectedProjects" 
                     @update:modelValue="fetchReport"
                 />
             </div>
         </div>

         <!-- GRID -->
         <div class="overflow-x-auto border rounded-lg" v-if="!isLoading && reportData">
             <table class="min-w-full divide-y divide-gray-200">
                 <thead class="bg-gray-50">
                     <tr>
                         <th class="sticky left-0 bg-gray-50 z-10 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider shadow-r">
                             Сотрудник
                         </th>
                         <th 
                            v-for="day in reportData.header_days" 
                            :key="day.date" 
                            class="px-2 py-3 text-center text-xs font-medium uppercase tracking-wider min-w-[50px]"
                            :class="day.is_weekend ? 'bg-red-50 text-red-600' : 'text-gray-500'"
                         >
                             <div>{{ day.day }}</div>
                             <div class="text-[10px]">{{ ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][day.weekday] }}</div>
                         </th>
                     </tr>
                 </thead>
                 <tbody class="bg-white divide-y divide-gray-200">
                     <tr v-for="row in reportData.rows" :key="row.employee.id">
                         <td class="sticky left-0 bg-white z-10 px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 border-r">
                             {{ row.employee.name }}
                         </td>
                         <td 
                            v-for="day in reportData.header_days" 
                            :key="day.date" 
                            class="px-1 py-1 text-center"
                            :class="day.is_weekend ? 'bg-gray-50' : ''"
                         >
                             <div 
                                class="w-full h-full py-2 rounded text-xs font-bold transition-colors"
                                :class="getCellColorClass(row.days[day.date].status)"
                                @click="openDetail(row.employee.name, day.date, row.days[day.date].items)"
                             >
                                 {{ row.days[day.date].total > 0 ? row.days[day.date].total : '-' }}
                             </div>
                         </td>
                     </tr>
                 </tbody>
             </table>
         </div>
         <div v-else-if="isLoading" class="text-center py-10 text-gray-500">
             Загрузка данных...
         </div>
         <div v-else class="text-center py-10 text-gray-500">
             Нет данных
         </div>
      </div>

      <!-- Modal -->
      <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50" @click.self="closeModal">
          <div class="bg-white rounded-lg shadow-xl w-3/4 max-h-[90vh] flex flex-col">
              <div class="p-4 border-b flex justify-between items-center">
                  <h3 class="text-lg font-bold text-gray-900">
                      {{ modalData.employeeName }} - {{ new Date(modalData.date).toLocaleDateString() }}
                  </h3>
                  <button @click="closeModal" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
              </div>
              <div class="p-4 overflow-y-auto">
                  <table class="min-w-full divide-y divide-gray-200 mb-4">
                      <thead class="bg-gray-50">
                          <tr>
                              <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">Проект</th>
                              <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">Задача</th>
                              <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">Описание</th>
                              <th class="px-3 py-2 text-right text-xs font-medium text-gray-500">Часы</th>
                          </tr>
                      </thead>
                      <tbody class="divide-y divide-gray-200">
                          <tr v-for="(item, idx) in modalData.items" :key="idx">
                              <td class="px-3 py-2 text-sm text-gray-900">{{ item.project_title || '-' }}</td>
                              <td class="px-3 py-2 text-sm text-blue-600">
                                <span 
                                    v-if="item.task_id"
                                    @click="openTask(item.task_id)"
                                    class="cursor-pointer hover:underline hover:text-blue-800"
                                >
                                    {{ item.task_title }}
                                </span>
                                <span v-else>{{ item.task_title }}</span>
                              </td>
                              <td class="px-3 py-2 text-sm text-gray-500">{{ item.description }}</td>
                              <td class="px-3 py-2 text-sm font-bold text-right">{{ item.hours }}</td>
                          </tr>
                      </tbody>
                  </table>
              </div>
              <div class="p-4 border-t bg-gray-50 text-right">
                  <B24Button label="Закрыть" color="default" @click="closeModal" />
              </div>
          </div>
      </div>
  </div>
</template>

<style scoped>
.shadow-r {
    box-shadow: 2px 0 5px -2px rgba(0, 0, 0, 0.1);
}
</style>
