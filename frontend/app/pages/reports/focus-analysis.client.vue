<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
import ReportMetricCard from '../../components/reports/ReportMetricCard.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { FocusAnalysisReport, FocusAnalysisEmployeeRow } from '~/types/report'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Фокус и распыление',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('FocusAnalysisReportPage')
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
const reportData = ref<FocusAnalysisReport | null>(null)

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
} = useReportFilters('focus-analysis')

const { hasGenerated, syncWarning, generateReport } = useReportGenerator({
  setLoading: (value) => {
    isLoading.value = value
  },
  onError: processErrorGlobal
})

const progress = useProgress()

const maxProjectCount = computed(() =>
  Math.max(...(reportData.value?.employee_rows || []).map((row: FocusAnalysisEmployeeRow) => row.project_count || 0), 1)
)
const maxHours = computed(() =>
  Math.max(...(reportData.value?.employee_rows || []).map((row: FocusAnalysisEmployeeRow) => row.total_hours || 0), 1)
)
const maxEntries = computed(() =>
  Math.max(...(reportData.value?.employee_rows || []).map((row: FocusAnalysisEmployeeRow) => row.entry_count || 0), 1)
)

function formatIndex(value: number) {
  return Number(value || 0).toFixed(2)
}

function formatPercentFromIndex(value: number) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

function riskBadgeClass(value: string) {
  if (value === 'Высокий') return 'bg-red-100 text-red-700'
  if (value === 'Средний') return 'bg-amber-100 text-amber-700'
  return 'bg-emerald-100 text-emerald-700'
}

function bubbleClass(value: string) {
  if (value === 'Высокий') return 'bg-red-500/85 text-white'
  if (value === 'Средний') return 'bg-amber-400/90 text-amber-950'
  return 'bg-emerald-500/85 text-white'
}

function getBubbleStyle(row: FocusAnalysisEmployeeRow) {
  const xRatio = maxProjectCount.value <= 1 ? 0.5 : (row.project_count - 1) / (maxProjectCount.value - 1)
  const yRatio = maxHours.value <= 0 ? 0 : row.total_hours / maxHours.value
  const size = 30 + (row.entry_count / maxEntries.value) * 26

  return {
    width: `${size}px`,
    height: `${size}px`,
    left: `calc(${(xRatio * 78 + 12).toFixed(2)}% - ${size / 2}px)`,
    bottom: `calc(${(yRatio * 72 + 10).toFixed(2)}% - ${size / 2}px)`
  }
}

async function fetchReport() {
  const payload = await generateReport({
    reportName: 'Фокус и распыление',
    syncDateFrom: dateFrom.value,
    syncDateTo: dateTo.value,
    loader: () => apiStore.getReportFocusAnalysis(
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

async function handleExportExcel() {
  progress.begin('Excel: «Фокус и распыление»', 0, 'Готовим файл выгрузки')
  try {
    const blob = await apiStore.exportReportFocusAnalysis(
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
    a.download = `Report_Focus_Analysis_${dateFrom.value}_${dateTo.value}.xlsx`
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
    await $b24.parent.setTitle('Фокус и распыление')
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
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4">
        <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

    <B24Card v-if="isInit" class="ms-surface ms-report-surface">
      <template #header>
        <div class="flex flex-col gap-4 w-full">
          <div class="flex flex-row justify-between items-center w-full gap-4">
            <div>
              <ProseH2 class="!text-slate-900">Фокус и распыление</ProseH2>
              <p class="mt-1 text-xs text-slate-500">Как сотрудники распределяют часы между проектами и задачами</p>
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
      </template>

      <div v-if="syncWarning" class="ms-panel-warning">
        {{ syncWarning }}
      </div>

      <div v-if="isLoading" class="flex justify-center py-8">
        <span class="text-slate-500">Загрузка...</span>
      </div>

      <div v-else-if="!hasGenerated" class="ms-empty-state">
        Выберите фильтры и нажмите «Сформировать»
      </div>

      <div v-else-if="reportData" class="space-y-6">
        <div class="ms-kpi-grid">
          <ReportMetricCard label="Индекс фокуса" :value="formatIndex(reportData.summary.avg_focus_index)" tone="info" />
          <ReportMetricCard label="Ср. размер записи" :value="`${reportData.summary.avg_entry_size.toFixed(2)}ч`" tone="success" />
          <ReportMetricCard label="Ср. записей / сотрудник" :value="reportData.summary.avg_entries_per_employee" />
          <ReportMetricCard label="5+ проектов" :value="reportData.summary.high_switch_employee_count" tone="warning" />
          <ReportMetricCard label="Высокий риск" :value="reportData.summary.high_risk_employee_count" tone="danger" />
          <ReportMetricCard label="Сотрудников" :value="reportData.summary.employee_count" />
        </div>

        <div class="ms-panel">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-slate-900">Карта фокуса: проекты vs часы</h3>
            <div class="flex items-center gap-3 text-xs text-slate-500">
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-emerald-500" /> Низкий риск</span>
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-amber-400" /> Средний риск</span>
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-red-500" /> Высокий риск</span>
            </div>
          </div>

          <div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4">
            <div class="relative h-[320px]">
              <div class="absolute inset-y-0 left-10 border-l border-slate-300" />
              <div class="absolute bottom-10 inset-x-10 border-b border-slate-300" />

              <div
                v-for="row in reportData.employee_rows"
                :key="row.employee_id"
                :class="['absolute flex items-center justify-center rounded-full text-[10px] font-semibold shadow-md transition-transform hover:scale-105', bubbleClass(row.risk_level)]"
                :style="getBubbleStyle(row)"
                :title="`${row.employee_name}: ${row.project_count} проектов, ${row.total_hours}ч, focus ${formatPercentFromIndex(row.focus_index)}`"
              >
                {{ row.employee_name.slice(0, 2).toUpperCase() }}
              </div>

              <div class="absolute left-0 top-0 bottom-10 flex flex-col justify-between text-xs text-slate-500">
                <span>{{ maxHours.toFixed(0) }}ч</span>
                <span>{{ (maxHours * 0.66).toFixed(0) }}ч</span>
                <span>{{ (maxHours * 0.33).toFixed(0) }}ч</span>
                <span>0ч</span>
              </div>

              <div class="absolute left-10 right-0 bottom-0 flex justify-between px-1 text-xs text-slate-500">
                <span v-for="idx in maxProjectCount" :key="idx">{{ idx }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Сотрудник</th>
                <th class="text-right">Проектов</th>
                <th class="text-right">Задач</th>
                <th class="text-right">Записей</th>
                <th class="text-right">Всего часов</th>
                <th class="text-right">Ср. запись</th>
                <th class="text-right">Focus</th>
                <th class="text-right">Риск</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in reportData.employee_rows" :key="row.employee_id">
                <td class="text-slate-900">{{ row.employee_name }}</td>
                <td class="text-right font-medium text-slate-900">{{ row.project_count }}</td>
                <td class="text-right text-slate-700">{{ row.task_count }}</td>
                <td class="text-right text-slate-700">{{ row.entry_count }}</td>
                <td class="text-right text-slate-900">{{ row.total_hours.toFixed(2) }}</td>
                <td class="text-right text-slate-700">{{ row.avg_entry_hours.toFixed(2) }}ч</td>
                <td class="text-right text-sky-700">{{ formatPercentFromIndex(row.focus_index) }}</td>
                <td class="text-right">
                  <span :class="['ms-pill', riskBadgeClass(row.risk_level)]">
                    {{ row.risk_level }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-else class="ms-empty-state">
        Нет данных
      </div>
    </B24Card>
    </div>
  </div>
</template>
