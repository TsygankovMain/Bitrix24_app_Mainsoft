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
const hasGenerated = ref(false)
const reportData = ref<{ summary: any; employee_rows: any[] } | null>(null)
const dateFrom = ref('')
const dateTo = ref('')

const filterOptions = ref<{ employees: any[]; projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string | number)[]>([])
const selectedProjects = ref<(string | number)[]>([])

const maxProjectCount = computed(() =>
  Math.max(...(reportData.value?.employee_rows || []).map((row: any) => row.project_count || 0), 1)
)
const maxHours = computed(() =>
  Math.max(...(reportData.value?.employee_rows || []).map((row: any) => row.total_hours || 0), 1)
)
const maxEntries = computed(() =>
  Math.max(...(reportData.value?.employee_rows || []).map((row: any) => row.entry_count || 0), 1)
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

function getBubbleStyle(row: any) {
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
    reportData.value = await apiStore.getReportFocusAnalysis(
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
      'Проектов': row.project_count,
      'Задач': row.task_count,
      'Записей': row.entry_count,
      'Всего часов': row.total_hours,
      'Ср. запись': row.avg_entry_hours,
      'Индекс фокуса': row.focus_index,
      'Часы в top-1 проекте': row.top_project_hours,
      'Риск': row.risk_level,
    })),
    sheetName: 'Фокус и распыление',
    fileName: `Report_Focus_Analysis_${dateFrom.value}_${dateTo.value}.xlsx`,
    columnWidths: [24, 10, 10, 10, 12, 12, 12, 16, 12]
  })
}

onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Фокус и распыление')
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
              <ProseH2>Фокус и распыление</ProseH2>
              <p class="text-xs text-gray-500 mt-1">Как сотрудники распределяют часы между проектами и задачами</p>
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
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <ReportMetricCard label="Индекс фокуса" :value="formatIndex(reportData.summary.avg_focus_index)" tone="info" />
          <ReportMetricCard label="Ср. размер записи" :value="`${reportData.summary.avg_entry_size.toFixed(2)}ч`" tone="success" />
          <ReportMetricCard label="Ср. записей / сотрудник" :value="reportData.summary.avg_entries_per_employee" />
          <ReportMetricCard label="5+ проектов" :value="reportData.summary.high_switch_employee_count" tone="warning" />
          <ReportMetricCard label="Высокий риск" :value="reportData.summary.high_risk_employee_count" tone="danger" />
          <ReportMetricCard label="Сотрудников" :value="reportData.summary.employee_count" />
        </div>

        <div class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-gray-900">Карта фокуса: проекты vs часы</h3>
            <div class="flex items-center gap-3 text-xs text-gray-500">
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-emerald-500" /> Низкий риск</span>
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-amber-400" /> Средний риск</span>
              <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-full bg-red-500" /> Высокий риск</span>
            </div>
          </div>

          <div class="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-4">
            <div class="relative h-[320px]">
              <div class="absolute inset-y-0 left-10 border-l border-gray-300" />
              <div class="absolute bottom-10 inset-x-10 border-b border-gray-300" />

              <div
                v-for="row in reportData.employee_rows"
                :key="row.employee_id"
                :class="['absolute flex items-center justify-center rounded-full text-[10px] font-semibold shadow-md transition-transform hover:scale-105', bubbleClass(row.risk_level)]"
                :style="getBubbleStyle(row)"
                :title="`${row.employee_name}: ${row.project_count} проектов, ${row.total_hours}ч, focus ${formatPercentFromIndex(row.focus_index)}`"
              >
                {{ row.employee_name.slice(0, 2).toUpperCase() }}
              </div>

              <div class="absolute left-0 top-0 bottom-10 flex flex-col justify-between text-xs text-gray-500">
                <span>{{ maxHours.toFixed(0) }}ч</span>
                <span>{{ (maxHours * 0.66).toFixed(0) }}ч</span>
                <span>{{ (maxHours * 0.33).toFixed(0) }}ч</span>
                <span>0ч</span>
              </div>

              <div class="absolute left-10 right-0 bottom-0 flex justify-between px-1 text-xs text-gray-500">
                <span v-for="idx in maxProjectCount" :key="idx">{{ idx }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="overflow-x-auto border rounded-lg">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Сотрудник</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Проектов</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Задач</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Записей</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Всего часов</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Ср. запись</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Focus</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Риск</th>
              </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
              <tr v-for="row in reportData.employee_rows" :key="row.employee_id" class="hover:bg-gray-50">
                <td class="px-4 py-3 text-sm text-gray-900">{{ row.employee_name }}</td>
                <td class="px-4 py-3 text-sm text-gray-900 text-right font-medium">{{ row.project_count }}</td>
                <td class="px-4 py-3 text-sm text-gray-700 text-right">{{ row.task_count }}</td>
                <td class="px-4 py-3 text-sm text-gray-700 text-right">{{ row.entry_count }}</td>
                <td class="px-4 py-3 text-sm text-gray-900 text-right">{{ row.total_hours.toFixed(2) }}</td>
                <td class="px-4 py-3 text-sm text-gray-700 text-right">{{ row.avg_entry_hours.toFixed(2) }}ч</td>
                <td class="px-4 py-3 text-sm text-sky-700 text-right">{{ formatPercentFromIndex(row.focus_index) }}</td>
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
