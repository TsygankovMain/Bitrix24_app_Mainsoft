<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ReportShell from '../../components/reports/ReportShell.vue'
import ReportTotalsStrip from '../../components/reports/ReportTotalsStrip.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { TimeEntryDisciplineReport, TimeDisciplineLagBucket } from '~/types/report'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Дисциплина внесения времени',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('TimeDisciplineReportPage')
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
const reportData = ref<TimeEntryDisciplineReport | null>(null)

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
} = useReportFilters('time-discipline')

const { hasGenerated, syncWarning, generateReport } = useReportGenerator({
  setLoading: (value) => {
    isLoading.value = value
  },
  onError: processErrorGlobal
})

const progress = useProgress()

const maxBucketCount = computed(() =>
  Math.max(...(reportData.value?.lag_buckets || []).map((bucket: TimeDisciplineLagBucket) => bucket.count || 0), 0)
)

function formatPercent(value: number) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

function formatLag(value: number) {
  return `${Number(value || 0).toFixed(1)}д`
}

function bucketWidth(count: number) {
  if (!maxBucketCount.value) return '0%'
  return `${Math.max((count / maxBucketCount.value) * 100, 6)}%`
}

function riskBadgeClass(value: string) {
  if (value === 'Высокий') return 'bg-red-100 text-red-700'
  if (value === 'Средний') return 'bg-amber-100 text-amber-700'
  return 'bg-emerald-100 text-emerald-700'
}

async function fetchReport() {
  const payload = await generateReport({
    reportName: 'Дисциплина внесения',
    syncDateFrom: dateFrom.value,
    syncDateTo: dateTo.value,
    loader: () => apiStore.getReportTimeEntryDiscipline(
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
 * Те же шесть чисел, что раньше лежали карточками `ms-kpi-grid` над отчётом:
 * значения берутся из того же `reportData.summary` и ничем не пересчитаны.
 */
const totals = computed(() => {
  const summary = reportData.value?.summary

  if (!summary) {
    return []
  }

  return [
    { id: 'entries', label: 'Всего записей', value: summary.total_entries },
    { id: 'same-day', label: 'День-в-день', value: formatPercent(summary.same_day_share), tone: 'success' as const },
    { id: 'next-day', label: '+1 день', value: formatPercent(summary.next_day_share), tone: 'info' as const },
    { id: 'two-plus', label: '2+ дней', value: formatPercent(summary.two_plus_share), tone: 'warning' as const },
    { id: 'avg-lag', label: 'Средний лаг', value: formatLag(summary.avg_lag_days), tone: 'danger' as const },
    { id: 'risk', label: 'Красная зона', value: summary.high_risk_employee_count, caption: 'сотрудников' },
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
  progress.begin('Excel: «Дисциплина внесения»', 0, 'Готовим файл выгрузки')
  try {
    const blob = await apiStore.exportReportTimeEntryDiscipline(
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
    a.download = `Report_Time_Discipline_${dateFrom.value}_${dateTo.value}.xlsx`
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
    await $b24.parent.setTitle('Дисциплина внесения времени')
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
    title="Дисциплина внесения времени"
    description="Сравнение даты отражения и реального времени создания записи в Битрикс24"
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
      <div v-if="reportData.summary.fallback_entries > 0" class="ms-panel-warning">
        Для {{ reportData.summary.fallback_entries }} записей использовано локальное время первой синхронизации, потому что `createdTime` ещё не заполнен. После полной синхронизации отчёт станет точнее.
      </div>

      <div class="ms-panel">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-semibold text-slate-900">Распределение по задержке</h3>
          <span class="text-xs text-slate-500">по дням задержки</span>
        </div>

        <div class="space-y-4">
          <div v-for="bucket in reportData.lag_buckets" :key="bucket.label" class="flex items-center gap-4">
            <div class="w-12 text-sm font-medium text-slate-700">{{ bucket.label }}</div>
            <div class="flex-1 h-4 overflow-hidden rounded-full bg-slate-100">
              <div class="h-full rounded-full bg-blue-500" :style="{ width: bucketWidth(bucket.count) }" />
            </div>
            <div class="w-12 text-right text-sm text-slate-500">{{ bucket.count }}</div>
          </div>
        </div>
      </div>

      <div class="ms-table-shell">
        <table class="ms-table">
          <thead>
            <tr>
              <th>Сотрудник</th>
              <th class="text-right">Записей</th>
              <th class="text-right">День-в-день</th>
              <th class="text-right">Ср. лаг</th>
              <th class="text-right">Late 2+</th>
              <th class="text-right">Макс.</th>
              <th>Последняя поздняя запись</th>
              <th class="text-right">Риск</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in reportData.employee_rows" :key="row.employee_id">
              <td class="text-slate-900">{{ row.employee_name }}</td>
              <td class="text-right font-medium text-slate-900">{{ row.entry_count }}</td>
              <td class="text-right text-emerald-700">{{ formatPercent(row.same_day_share) }}</td>
              <td class="text-right">{{ formatLag(row.avg_lag_days) }}</td>
              <td class="text-right text-amber-700">{{ row.late_entries }}</td>
              <td class="text-right">{{ row.max_lag_days }}д</td>
              <td>{{ row.last_late_entry_date || '—' }}</td>
              <td class="text-right">
                <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', riskBadgeClass(row.risk_level)]">
                  {{ row.risk_level }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </ReportShell>
</template>
