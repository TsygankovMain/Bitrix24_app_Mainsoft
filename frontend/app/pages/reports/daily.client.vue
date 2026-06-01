<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { DailyWorkloadReport } from '~/types/report'

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
const reportData = ref<DailyWorkloadReport | null>(null)
const isInit = ref(false)
const domain = ref('') // Store domain for links

// Modal State
const showModal = ref(false)
const modalData = ref<any>(null) // { employeeName, date, items: [] }

const {
    dateFrom,
    dateTo,
    filterOptions,
    selectedEmployees,
    selectedProjects,
    employeeFilterMode,
    projectFilterMode,
    employeeFilter,
    projectFilter,
    loadFilterOptions,
    initCurrentMonthRange,
} = useReportFilters()

const { hasGenerated, syncWarning, generateReport } = useReportGenerator({
    setLoading: (value) => {
        isLoading.value = value
    },
    onError: processErrorGlobal
})

const progress = useProgress()

const normalizedHeaderDays = computed(() =>
    Array.isArray(reportData.value?.header_days) ? reportData.value.header_days : []
)

const normalizedRows = computed(() =>
    Array.isArray(reportData.value?.rows) ? reportData.value.rows : []
)

const hasRenderableReport = computed(() =>
    normalizedHeaderDays.value.length > 0 && normalizedRows.value.length > 0
)

function normalizeDailyReportPayload(payload: DailyWorkloadReport | null | undefined): DailyWorkloadReport {
    return {
        header_days: Array.isArray(payload?.header_days) ? payload.header_days : [],
        rows: Array.isArray(payload?.rows) ? payload.rows : [],
    }
}

function getDayCell(row: any, dateKey: string) {
    const cell = row?.days?.[dateKey]
    return {
        total: Number(cell?.total || 0),
        status: typeof cell?.status === 'string' ? cell.status : 'neutral',
        items: Array.isArray(cell?.items) ? cell.items : [],
    }
}

async function fetchReport() {
    const payload = await generateReport({
        reportName: 'Ежедневная нагрузка',
        syncDateFrom: dateFrom.value,
        syncDateTo: dateTo.value,
        loader: () => apiStore.getReportDailyWorkload(
            dateFrom.value,
            dateTo.value,
            employeeFilter.value,
            projectFilter.value
        ),
        normalize: normalizeDailyReportPayload,
        allowSyncFallback: true,
        syncWarningMessage: 'Не удалось обновить данные из Битрикс24. Отчет построен по последней сохраненной синхронизации.'
    })

    if (payload) {
        reportData.value = payload
    }
}

async function handleExportExcel() {
    progress.begin('Excel: «Ежедневная нагрузка»', 0, 'Готовим файл выгрузки')
    try {
        const blob = await apiStore.exportReportDailyWorkload(
            dateFrom.value,
            dateTo.value,
            employeeFilter.value,
            projectFilter.value
        )
        if (blob.type && blob.type.includes('application/json')) {
            const text = await blob.text()
            let message = 'Не удалось сформировать файл'
            try {
                message = JSON.parse(text).error || message
            } catch {
                // оставляем дефолтное сообщение
            }
            throw new Error(message)
        }
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `Report_Daily_${dateFrom.value}_${dateTo.value}.xlsx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        progress.end()
    }
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
    return 'bg-slate-50 text-slate-400' // neutral
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
    
    await loadFilterOptions()
    
    // Default range: Current Month
    initCurrentMonthRange()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4 flex justify-between items-center">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <div v-if="isInit" class="flex flex-col gap-6">
         <!-- Filters Header -->
         <div class="ms-surface flex flex-col gap-4 p-5">
             <div class="flex flex-row justify-between items-center w-full">
                 <div>
                   <h2 class="text-xl font-bold text-slate-900">Ежедневная нагрузка</h2>
                   <p class="mt-1 text-sm text-slate-500">Распределение часов по сотрудникам и дням периода.</p>
                 </div>
                 <div class="flex gap-2">
                    <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                    <B24Button label="Сформировать" loading-auto @click="fetchReport" />
                 </div>
             </div>
             
             <div class="ms-filter-wrap flex flex-wrap gap-4 items-end">
                 <DateRangeFilter 
                     v-model:date-from="dateFrom" 
                     v-model:date-to="dateTo" 
                 />
                 <MultiSelectFilter 
                     v-model="selectedEmployees" 
                     v-model:mode="employeeFilterMode" 
                     label="Сотрудники" 
                     :options="filterOptions.employees"
                 />
                 <MultiSelectFilter 
                     v-model="selectedProjects" 
                     v-model:mode="projectFilterMode" 
                     label="Проекты" 
                     :options="filterOptions.projects"
                 />
             </div>
         </div>

         <div v-if="syncWarning" class="ms-panel-warning">
             {{ syncWarning }}
         </div>

         <div v-if="!isLoading && hasRenderableReport" class="ms-surface p-4">
             <div class="ms-table-shell">
                 <table class="ms-table">
                     <thead>
                         <tr>
                             <th class="shadow-r sticky left-0 z-10 bg-slate-50">
                                 Сотрудник
                             </th>
                             <th
                                v-for="day in normalizedHeaderDays"
                                :key="day.date"
                                class="min-w-[50px] px-2 py-3 text-center text-xs font-medium uppercase tracking-wider"
                                :class="day.is_weekend ? 'bg-rose-50 text-rose-600' : 'text-slate-500'"
                             >
                                 <div>{{ day.day }}</div>
                                 <div class="text-[10px]">{{ ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][day.weekday] }}</div>
                             </th>
                         </tr>
                     </thead>
                     <tbody>
                         <tr v-for="row in normalizedRows" :key="row.employee.id">
                             <td class="sticky left-0 z-10 whitespace-nowrap border-r border-slate-200 bg-white text-sm font-medium text-slate-900">
                                 {{ row.employee.name }}
                             </td>
                             <td
                                v-for="day in normalizedHeaderDays"
                                :key="day.date"
                                class="px-1 py-1 text-center"
                                :class="day.is_weekend ? 'bg-slate-50' : ''"
                             >
                                 <div
                                    class="w-full h-full py-2 rounded text-xs font-bold transition-colors"
                                    :class="getCellColorClass(getDayCell(row, day.date).status)"
                                    @click="openDetail(row.employee.name, day.date, getDayCell(row, day.date).items)"
                                 >
                                     {{ getDayCell(row, day.date).total > 0 ? getDayCell(row, day.date).total : '-' }}
                                 </div>
                             </td>
                         </tr>
                     </tbody>
                 </table>
             </div>
         </div>
         <div v-else class="ms-surface px-5 py-8">
             <div v-if="isLoading" class="ms-empty-state !py-0">
                 Загрузка данных...
             </div>
             <div v-else-if="!hasGenerated" class="ms-empty-state !py-0">
                 Выберите фильтры и нажмите «Сформировать»
             </div>
             <div v-else class="ms-empty-state !py-0">
                 Нет данных за выбранный период
             </div>
         </div>
      </div>

      <!-- Modal -->
      <Teleport to="body">
          <div v-if="showModal" class="ms-modal-overlay" @click.self="closeModal">
          <div class="ms-modal-panel flex max-h-[90vh] w-3/4 flex-col">
              <div class="ms-modal-header flex justify-between items-center">
                  <h3 class="text-lg font-bold text-slate-900">
                      {{ modalData.employeeName }} - {{ new Date(modalData.date).toLocaleDateString() }}
                  </h3>
                  <button class="text-2xl text-slate-500 transition hover:text-slate-700" @click="closeModal">&times;</button>
              </div>
              <div class="ms-modal-body overflow-y-auto">
                  <table class="ms-table mb-4 min-w-full">
                      <thead>
                          <tr>
                              <th>Проект</th>
                              <th>Задача</th>
                              <th>Описание</th>
                              <th class="text-right">Часы</th>
                          </tr>
                      </thead>
                      <tbody>
                          <tr v-for="(item, idx) in modalData.items" :key="idx">
                              <td class="text-sm text-slate-900">{{ item.project_title || '-' }}</td>
                              <td class="text-sm text-[#0075ff]">
                                <span
                                    v-if="item.task_id"
                                    class="cursor-pointer hover:text-blue-700 hover:underline"
                                    @click="openTask(item.task_id)"
                                >
                                    {{ item.task_title }}
                                </span>
                                <span v-else>{{ item.task_title }}</span>
                              </td>
                              <td class="text-sm text-slate-500">{{ item.description }}</td>
                              <td class="text-right text-sm font-bold text-slate-900">{{ item.hours }}</td>
                          </tr>
                      </tbody>
                  </table>
              </div>
              <div class="ms-modal-footer text-right">
                  <B24Button label="Закрыть" color="default" @click="closeModal" />
              </div>
          </div>
          </div>
      </Teleport>
    </div>
  </div>
</template>

<style scoped>
.shadow-r {
    box-shadow: 2px 0 5px -2px rgba(0, 0, 0, 0.1);
}
</style>
