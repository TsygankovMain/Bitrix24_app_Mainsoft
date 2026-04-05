<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
import ReportMetricCard from '../../components/reports/ReportMetricCard.vue'
import { exportRowsToXlsx } from '~/utils/exportXlsx'
import { getCurrentMonthRange } from '~/utils/reportDateRange'

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
const hasGenerated = ref(false)
const reportData = ref<{ summary: any; lag_buckets: any[]; employee_rows: any[] } | null>(null)
const dateFrom = ref('')
const dateTo = ref('')

const filterOptions = ref<{ employees: any[]; projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string | number)[]>([])
const selectedProjects = ref<(string | number)[]>([])
const employeeFilterMode = ref<'include' | 'exclude'>('include')
const projectFilterMode = ref<'include' | 'exclude'>('include')

const maxBucketCount = computed(() =>
  Math.max(...(reportData.value?.lag_buckets || []).map((bucket: any) => bucket.count || 0), 0)
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

async function fetchFilterOptions() {
  try {
    const [employees, projects] = await Promise.all([
      apiStore.getFilterEmployees(),
      apiStore.getFilterProjects()
    ])
    filterOptions.value = { employees, projects }
  } catch (error) {
    processErrorGlobal(error)
  }
}

async function fetchReport() {
  isLoading.value = true
  try {
    await apiStore.syncTimesheets()
    reportData.value = await apiStore.getReportTimeEntryDiscipline(
      dateFrom.value,
      dateTo.value,
      { ids: selectedEmployees.value, mode: employeeFilterMode.value },
      { ids: selectedProjects.value, mode: projectFilterMode.value }
    )
    hasGenerated.value = true
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
}

async function handleExportExcel() {
  if (!reportData.value) return

  await exportRowsToXlsx({
    rows: reportData.value.employee_rows.map((row: any) => ({
      'Сотрудник': row.employee_name,
      'Записей': row.entry_count,
      'День-в-день %': `${(row.same_day_share * 100).toFixed(1)}%`,
      'Средний лаг': row.avg_lag_days,
      'Поздние записи (2+д)': row.late_entries,
      'Макс. лаг': row.max_lag_days,
      'Последняя поздняя запись': row.last_late_entry_date || '',
      'Риск': row.risk_level,
    })),
    sheetName: 'Дисциплина времени',
    fileName: `Report_Time_Discipline_${dateFrom.value}_${dateTo.value}.xlsx`,
    columnWidths: [24, 10, 12, 14, 18, 12, 22, 12]
  })
}

onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Дисциплина внесения времени')
    isInit.value = true

    await fetchFilterOptions()

    const range = getCurrentMonthRange()
    dateFrom.value = range.dateFrom
    dateTo.value = range.dateTo
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

      <B24Card v-if="isInit" class="ms-surface">
      <template #header>
        <div class="flex flex-col gap-4 w-full">
          <div class="flex flex-row justify-between items-center w-full gap-4">
            <div>
              <ProseH2 class="!text-slate-900">Дисциплина внесения времени</ProseH2>
              <p class="mt-1 text-xs text-slate-500">Сравнение даты отражения и реального времени создания записи в Bitrix24</p>
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
        <div v-if="reportData.summary.fallback_entries > 0" class="ms-panel-warning">
          Для {{ reportData.summary.fallback_entries }} записей использовано локальное время первой синхронизации, потому что `createdTime` еще не заполнен. После полной синхронизации отчет станет точнее.
        </div>

        <div class="ms-kpi-grid">
          <ReportMetricCard label="Всего записей" :value="reportData.summary.total_entries" />
          <ReportMetricCard label="День-в-день" :value="formatPercent(reportData.summary.same_day_share)" tone="success" />
          <ReportMetricCard label="+1 день" :value="formatPercent(reportData.summary.next_day_share)" tone="info" />
          <ReportMetricCard label="2+ дней" :value="formatPercent(reportData.summary.two_plus_share)" tone="warning" />
          <ReportMetricCard label="Средний лаг" :value="formatLag(reportData.summary.avg_lag_days)" tone="danger" />
          <ReportMetricCard label="Красная зона" :value="reportData.summary.high_risk_employee_count" caption="сотрудников" />
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
      </div>

      <div v-else class="ms-empty-state">
        Нет данных
      </div>
      </B24Card>
    </div>
  </div>
</template>
