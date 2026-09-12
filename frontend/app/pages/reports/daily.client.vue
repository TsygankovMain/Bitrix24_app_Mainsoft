<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ReportShell from '../../components/reports/ReportShell.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { DailyWorkloadReport, DailyWorkloadRow, DailyWorkloadItem } from '~/types/report'

const { locales: localesI18n, setLocale } = useI18n()
const apiStore = useApiStore()

useHead({
  title: 'Ежедневная нагрузка',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init
const { initApp, processErrorGlobal } = useAppInit('DailyReportPage')
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
interface DailyModalData {
  employeeName: string
  date: string
  items: DailyWorkloadItem[]
}
const showModal = ref(false)
const modalData = ref<DailyModalData | null>(null) // { employeeName, date, items: [] }

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

function getDayCell(row: DailyWorkloadRow, dateKey: string) {
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

// Кнопка «Обновить» синхронизирует read-model; отчёт перестраиваем только если он уже построен,
// чтобы не запускать генерацию за пользователя.
// Пресет меняет фильтр целиком. Перестраиваем отчёт только если он уже на экране:
// запускать генерацию за человека, который ещё ничего не нажимал, — не наше дело.
function handleFiltersApplied() {
    if (hasGenerated.value) {
        void fetchReport()
    }
}

function handleDataRefreshed() {
    void loadFilterOptions(true)
    if (hasGenerated.value) {
        void fetchReport()
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

function openDetail(employeeName: string, date: string, items: DailyWorkloadItem[]) {
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
    // @ts-expect-error BX24 is injected globally by Bitrix24 and is not typed on window
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
    const b24Any = $b24 as unknown as { auth?: { domain?: string }, getAuthData?: () => { domain?: string } | undefined }
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
  <ReportShell
    v-if="isInit"
    title="Ежедневная нагрузка"
    description="Распределение часов по сотрудникам и дням периода"
    :date-from="dateFrom"
    :date-to="dateTo"
    :employees="selectedEmployees"
    :employee-mode="employeeFilterMode"
    :projects="selectedProjects"
    :project-mode="projectFilterMode"
    :employee-options="filterOptions.employees"
    :project-options="filterOptions.projects"
    :is-loading="isLoading"
    :has-generated="hasGenerated"
    :is-empty="!hasRenderableReport"
    :warning="syncWarning"
    @update:date-from="dateFrom = $event"
    @update:date-to="dateTo = $event"
    @update:employees="selectedEmployees = $event"
    @update:employee-mode="employeeFilterMode = $event"
    @update:projects="selectedProjects = $event"
    @update:project-mode="projectFilterMode = $event"
    @refreshed="handleDataRefreshed"
    @filters-applied="handleFiltersApplied"
    @generate="fetchReport"
    @export="handleExportExcel"
  >
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
                class="h-full w-full rounded py-2 text-xs font-bold transition-colors"
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

    <!-- Детали дня -->
    <Teleport to="body">
      <div v-if="showModal" class="ms-modal-overlay" @click.self="closeModal">
        <div class="ms-modal-panel flex max-h-[90vh] w-3/4 flex-col">
          <div class="ms-modal-header flex items-center justify-between">
            <h3 class="text-lg font-bold text-slate-900">
              {{ modalData.employeeName }} — {{ new Date(modalData.date).toLocaleDateString() }}
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
  </ReportShell>
</template>

<style scoped>
.shadow-r {
    box-shadow: 2px 0 5px -2px rgba(0, 0, 0, 0.1);
}
</style>
