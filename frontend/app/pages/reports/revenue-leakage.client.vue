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
import type { RevenueLeakageReport } from '~/types/report'

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
} = useReportFilters()

const { hasGenerated, generateReport } = useReportGenerator({
  setLoading: (value) => {
    isLoading.value = value
  },
  onError: processErrorGlobal
})

const progress = useProgress()

const maxLeakageHours = computed(() =>
  Math.max(...(reportData.value?.project_rows || []).map((row: any) => row.non_billable_hours || 0), 0)
)

const topRiskRows = computed(() => (reportData.value?.risk_rows || []).slice(0, 6))

function formatHours(value: number) {
  return `${Number(value || 0).toFixed(1)}ч`
}

function formatPercent(value: number) {
  return `${Number(value || 0).toFixed(1)}%`
}

function projectBarWidth(row: any) {
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
    loader: () => apiStore.getReportRevenueLeakage(
      dateFrom.value,
      dateTo.value,
      employeeFilter.value,
      projectFilter.value
    )
  })

  if (payload) {
    reportData.value = payload
  }
}

async function handleExportExcel() {
  progress.begin('Формирование Excel…')
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
              <ProseH2 class="!text-slate-900">Потери выручки</ProseH2>
              <p class="mt-1 text-xs text-slate-500">Где команда теряет учитываемые часы по проектам и сотрудникам</p>
            </div>
            <div class="flex gap-2">
              <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
              <B24Button label="Сформировать" @click="fetchReport" loading-auto />
            </div>
          </div>

          <div class="ms-filter-wrap flex flex-wrap gap-4 items-end">
            <DateRangeFilter
              v-model:dateFrom="dateFrom"
              v-model:dateTo="dateTo"
            />

            <MultiSelectFilter
              label="Сотрудники"
              :options="filterOptions.employees"
              v-model="selectedEmployees"
              v-model:mode="employeeFilterMode"
            />

            <MultiSelectFilter
              label="Проекты"
              :options="filterOptions.projects"
              v-model="selectedProjects"
              v-model:mode="projectFilterMode"
            />
          </div>
        </div>
      </template>

      <div v-if="isLoading" class="flex justify-center py-8">
        <span class="text-slate-500">Загрузка...</span>
      </div>

      <div v-else-if="!hasGenerated" class="ms-empty-state">
        Выберите фильтры и нажмите «Сформировать»
      </div>

      <div v-else-if="reportData" class="space-y-6">
        <div class="ms-kpi-grid">
          <ReportMetricCard label="Всего часов" :value="formatHours(reportData.summary.total_hours)" />
          <ReportMetricCard label="Учтено" :value="formatHours(reportData.summary.billable_hours)" tone="success" />
          <ReportMetricCard label="Не учтено" :value="formatHours(reportData.summary.non_billable_hours)" tone="danger" />
          <ReportMetricCard label="Доля потерь" :value="formatPercent(reportData.summary.loss_rate)" tone="warning" />
          <ReportMetricCard label="Проектов" :value="reportData.summary.project_count" caption="с данными за период" />
          <ReportMetricCard label="Зона риска" :value="`${reportData.summary.high_risk_project_count} / ${reportData.summary.high_risk_employee_count}`" caption="проекты / сотрудники" tone="info" />
        </div>

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
      </div>

      <div v-else class="ms-empty-state">
        Нет данных
      </div>
      </B24Card>
    </div>
  </div>
</template>
