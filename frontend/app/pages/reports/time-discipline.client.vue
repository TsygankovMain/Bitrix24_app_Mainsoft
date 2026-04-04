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
    filterOptions.value = await apiStore.getFilterOptions()
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
      selectedEmployees.value as string[],
      selectedProjects.value as string[]
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
  <div class="flex flex-col gap-4 p-4 min-h-screen">
    <div class="mb-4">
      <B24Button label="Назад" color="link" @click="$router.push('/')" />
    </div>

    <B24Card v-if="isInit">
      <template #header>
        <div class="flex flex-col gap-4 w-full">
          <div class="flex flex-row justify-between items-center w-full gap-4">
            <div>
              <ProseH2>Дисциплина внесения времени</ProseH2>
              <p class="text-xs text-gray-500 mt-1">Сравнение даты отражения и реального времени создания записи в Bitrix24</p>
            </div>
            <div class="flex gap-2">
              <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
              <B24Button label="Сформировать" @click="fetchReport" loading-auto />
            </div>
          </div>

          <div class="flex flex-wrap gap-4 items-end bg-gray-50 p-4 rounded-lg">
            <DateRangeFilter
              v-model:dateFrom="dateFrom"
              v-model:dateTo="dateTo"
            />

            <MultiSelectFilter
              label="Сотрудники"
              :options="filterOptions.employees"
              v-model="selectedEmployees"
            />

            <MultiSelectFilter
              label="Проекты"
              :options="filterOptions.projects"
              v-model="selectedProjects"
            />
          </div>
        </div>
      </template>

      <div v-if="isLoading" class="flex justify-center py-8">
        <span class="text-gray-500">Загрузка...</span>
      </div>

      <div v-else-if="!hasGenerated" class="py-8 text-center text-gray-500">
        Выберите фильтры и нажмите «Сформировать»
      </div>

      <div v-else-if="reportData" class="space-y-6">
        <div v-if="reportData.summary.fallback_entries > 0" class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Для {{ reportData.summary.fallback_entries }} записей использовано локальное время первой синхронизации, потому что `createdTime` еще не заполнен. После полной синхронизации отчет станет точнее.
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <ReportMetricCard label="Всего записей" :value="reportData.summary.total_entries" />
          <ReportMetricCard label="День-в-день" :value="formatPercent(reportData.summary.same_day_share)" tone="success" />
          <ReportMetricCard label="+1 день" :value="formatPercent(reportData.summary.next_day_share)" tone="info" />
          <ReportMetricCard label="2+ дней" :value="formatPercent(reportData.summary.two_plus_share)" tone="warning" />
          <ReportMetricCard label="Средний лаг" :value="formatLag(reportData.summary.avg_lag_days)" tone="danger" />
          <ReportMetricCard label="Красная зона" :value="reportData.summary.high_risk_employee_count" caption="сотрудников" />
        </div>

        <div class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-gray-900">Распределение по задержке</h3>
            <span class="text-xs text-gray-500">по дням задержки</span>
          </div>

          <div class="space-y-4">
            <div v-for="bucket in reportData.lag_buckets" :key="bucket.label" class="flex items-center gap-4">
              <div class="w-12 text-sm font-medium text-gray-700">{{ bucket.label }}</div>
              <div class="flex-1 h-4 rounded-full bg-gray-100 overflow-hidden">
                <div class="h-full rounded-full bg-blue-500" :style="{ width: bucketWidth(bucket.count) }" />
              </div>
              <div class="w-12 text-right text-sm text-gray-500">{{ bucket.count }}</div>
            </div>
          </div>
        </div>

        <div class="overflow-x-auto border rounded-lg">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Сотрудник</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Записей</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">День-в-день</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Ср. лаг</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Late 2+</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Макс.</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Последняя поздняя запись</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Риск</th>
              </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
              <tr v-for="row in reportData.employee_rows" :key="row.employee_id" class="hover:bg-gray-50">
                <td class="px-4 py-3 text-sm text-gray-900">{{ row.employee_name }}</td>
                <td class="px-4 py-3 text-sm text-gray-900 text-right font-medium">{{ row.entry_count }}</td>
                <td class="px-4 py-3 text-sm text-emerald-700 text-right">{{ formatPercent(row.same_day_share) }}</td>
                <td class="px-4 py-3 text-sm text-gray-700 text-right">{{ formatLag(row.avg_lag_days) }}</td>
                <td class="px-4 py-3 text-sm text-amber-700 text-right">{{ row.late_entries }}</td>
                <td class="px-4 py-3 text-sm text-gray-700 text-right">{{ row.max_lag_days }}д</td>
                <td class="px-4 py-3 text-sm text-gray-500">{{ row.last_late_entry_date || '—' }}</td>
                <td class="px-4 py-3 text-sm text-right">
                  <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', riskBadgeClass(row.risk_level)]">
                    {{ row.risk_level }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-else class="py-8 text-center text-gray-500">
        Нет данных
      </div>
    </B24Card>
  </div>
</template>
