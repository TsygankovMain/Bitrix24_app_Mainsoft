<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ReportShell from '../../components/reports/ReportShell.vue'
import ReportTotalsStrip from '../../components/reports/ReportTotalsStrip.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { RevenueLeakageReport, RevenueLeakageProjectRow } from '~/types/report'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Потери выручки',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('RevenueLeakageReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

const isInit = ref(false)
const reportData = ref<RevenueLeakageReport | null>(null)

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
} = useReportFilters('revenue-leakage')

const { hasGenerated, syncWarning, generateReport } = useReportGenerator({
  setLoading: (value) => {
    isLoading.value = value
  },
  onError: processErrorGlobal
})

const progress = useProgress()

const maxLeakageHours = computed(() =>
  Math.max(...(reportData.value?.project_rows || []).map((row: RevenueLeakageProjectRow) => row.non_billable_hours || 0), 0)
)

const topRiskRows = computed(() => (reportData.value?.risk_rows || []).slice(0, 6))

function formatHours(value: number) {
  return `${Number(value || 0).toFixed(1)}ч`
}

function formatPercent(value: number) {
  return `${Number(value || 0).toFixed(1)}%`
}

function projectBarWidth(row: RevenueLeakageProjectRow) {
  if (!maxLeakageHours.value) return '0%'
  return `${Math.max((row.non_billable_hours / maxLeakageHours.value) * 100, 4)}%`
}

function lossBadgeClass(value: number) {
  if (value >= 40) return 'bg-red-100 text-red-700'
  if (value >= 20) return 'bg-amber-100 text-amber-700'
  return 'bg-emerald-100 text-emerald-700'
}

async function fetchReport() {
  const payload = await generateReport({
    reportName: 'Потери выручки',
    syncDateFrom: dateFrom.value,
    syncDateTo: dateTo.value,
    loader: () => apiStore.getReportRevenueLeakage(
      dateFrom.value,
      dateTo.value,
      employeeFilter.value,
      projectFilter.value
    ),
    allowSyncFallback: true
  })

  if (payload) {
    reportData.value = payload
  }
}

// Кнопка «Обновить» синхронизирует read-model; отчёт перестраиваем только если он уже построен,
// чтобы не запускать генерацию за пользователя.
/**
 * Итоги для строки шапки.
 *
 * Те же шесть чисел, что раньше лежали карточками `ms-kpi-grid` над отчётом, —
 * значения берутся из того же `reportData.summary` и ничем не пересчитаны.
 */
const totals = computed(() => {
  const summary = reportData.value?.summary

  if (!summary) {
    return []
  }

  return [
    { id: 'total', label: 'Всего часов', value: formatHours(summary.total_hours) },
    { id: 'billable', label: 'Учтено', value: formatHours(summary.billable_hours), tone: 'success' as const },
    { id: 'non-billable', label: 'Не учтено', value: formatHours(summary.non_billable_hours), tone: 'danger' as const },
    { id: 'loss', label: 'Доля потерь', value: formatPercent(summary.loss_rate), tone: 'warning' as const },
    { id: 'projects', label: 'Проектов', value: summary.project_count, caption: 'с данными за период' },
    {
      id: 'risk',
      label: 'Зона риска',
      value: `${summary.high_risk_project_count} / ${summary.high_risk_employee_count}`,
      caption: 'проекты / сотрудники',
      tone: 'info' as const,
    },
  ]
})

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
  progress.begin('Excel: «Потери выручки»', 0, 'Готовим файл выгрузки')
  try {
    const blob = await apiStore.exportReportRevenueLeakage(
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
    a.download = `Report_Revenue_Leakage_${dateFrom.value}_${dateTo.value}.xlsx`
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

onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Потери выручки')
    isInit.value = true

    await loadFilterOptions()

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
    title="Потери выручки"
    description="Где команда теряет учитываемые часы по проектам и сотрудникам"
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
    :is-empty="!reportData"
    :warning="syncWarning"
    :surface="false"
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
    <template #totals>
      <ReportTotalsStrip v-if="hasGenerated && reportData" :items="totals" />
    </template>

    <template v-if="reportData">
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div class="ms-panel">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-slate-900">Потери по проектам</h3>
            <span class="text-xs text-slate-500">по неучтенным часам</span>
          </div>

          <div class="space-y-4">
            <div v-for="project in reportData.project_rows" :key="project.name" class="space-y-2">
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-sm font-medium text-slate-900 truncate">{{ project.name }}</div>
                  <div class="text-xs text-slate-500">{{ formatHours(project.non_billable_hours) }} не учтено из {{ formatHours(project.total_hours) }}</div>
                </div>
                <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', lossBadgeClass(project.loss_rate)]">
                  {{ formatPercent(project.loss_rate) }}
                </span>
              </div>

              <div class="h-3 overflow-hidden rounded-full bg-slate-100">
                <div class="h-full rounded-full bg-red-500" :style="{ width: projectBarWidth(project) }" />
              </div>
            </div>
          </div>
        </div>

        <div class="ms-panel">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-slate-900">Самые рискованные связки</h3>
            <span class="text-xs text-slate-500">проект × сотрудник</span>
          </div>

          <div class="space-y-3">
            <div v-for="row in topRiskRows" :key="`${row.project_name}-${row.employee_id}`" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <div class="text-sm font-semibold text-slate-900">{{ row.employee_name }}</div>
                  <div class="text-xs text-slate-500">{{ row.project_name }}</div>
                </div>
                <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', lossBadgeClass(row.loss_rate)]">
                  {{ formatPercent(row.loss_rate) }}
                </span>
              </div>
              <div class="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-500">
                <div>Всего: <span class="font-semibold text-slate-700">{{ formatHours(row.total_hours) }}</span></div>
                <div>Учтено: <span class="font-semibold text-emerald-700">{{ formatHours(row.billable_hours) }}</span></div>
                <div>Не учтено: <span class="font-semibold text-red-700">{{ formatHours(row.non_billable_hours) }}</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="ms-table-shell">
        <table class="ms-table">
          <thead>
            <tr>
              <th>Проект</th>
              <th>Сотрудник</th>
              <th class="text-right">Всего</th>
              <th class="text-right">Учтено</th>
              <th class="text-right">Не учтено</th>
              <th class="text-right">Потери %</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in reportData.risk_rows" :key="`${row.project_name}-${row.employee_id}`">
              <td class="text-slate-900">{{ row.project_name }}</td>
              <td>{{ row.employee_name }}</td>
              <td class="text-right font-medium text-slate-900">{{ row.total_hours.toFixed(2) }}</td>
              <td class="text-right text-emerald-700">{{ row.billable_hours.toFixed(2) }}</td>
              <td class="text-right text-red-700">{{ row.non_billable_hours.toFixed(2) }}</td>
              <td class="text-right">
                <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', lossBadgeClass(row.loss_rate)]">
                  {{ formatPercent(row.loss_rate) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </ReportShell>
</template>
