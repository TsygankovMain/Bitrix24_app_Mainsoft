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
const hasGenerated = ref(false)
const reportData = ref<{ summary: any; project_rows: any[]; risk_rows: any[] } | null>(null)
const dateFrom = ref('')
const dateTo = ref('')

const filterOptions = ref<{ employees: any[]; projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string | number)[]>([])
const selectedProjects = ref<(string | number)[]>([])

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
    reportData.value = await apiStore.getReportRevenueLeakage(
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
    rows: reportData.value.risk_rows.map((row: any) => ({
      'Проект': row.project_name,
      'Сотрудник': row.employee_name,
      'Всего часов': row.total_hours,
      'Учтено': row.billable_hours,
      'Не учтено': row.non_billable_hours,
      'Доля потерь %': row.loss_rate,
    })),
    sheetName: 'Потери выручки',
    fileName: `Report_Revenue_Leakage_${dateFrom.value}_${dateTo.value}.xlsx`,
    columnWidths: [28, 24, 14, 14, 16, 12]
  })
}

onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Потери выручки')
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
              <ProseH2>Потери выручки</ProseH2>
              <p class="text-xs text-gray-500 mt-1">Где команда теряет учитываемые часы по проектам и сотрудникам</p>
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
          <ReportMetricCard label="Всего часов" :value="formatHours(reportData.summary.total_hours)" />
          <ReportMetricCard label="Учтено" :value="formatHours(reportData.summary.billable_hours)" tone="success" />
          <ReportMetricCard label="Не учтено" :value="formatHours(reportData.summary.non_billable_hours)" tone="danger" />
          <ReportMetricCard label="Доля потерь" :value="formatPercent(reportData.summary.loss_rate)" tone="warning" />
          <ReportMetricCard label="Проектов" :value="reportData.summary.project_count" caption="с данными за период" />
          <ReportMetricCard label="Зона риска" :value="`${reportData.summary.high_risk_project_count} / ${reportData.summary.high_risk_employee_count}`" caption="проекты / сотрудники" tone="info" />
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <div class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-base font-semibold text-gray-900">Потери по проектам</h3>
              <span class="text-xs text-gray-500">по неучтенным часам</span>
            </div>

            <div class="space-y-4">
              <div v-for="project in reportData.project_rows" :key="project.name" class="space-y-2">
                <div class="flex items-center justify-between gap-3">
                  <div class="min-w-0">
                    <div class="text-sm font-medium text-gray-900 truncate">{{ project.name }}</div>
                    <div class="text-xs text-gray-500">{{ formatHours(project.non_billable_hours) }} не учтено из {{ formatHours(project.total_hours) }}</div>
                  </div>
                  <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', lossBadgeClass(project.loss_rate)]">
                    {{ formatPercent(project.loss_rate) }}
                  </span>
                </div>

                <div class="h-3 rounded-full bg-gray-100 overflow-hidden">
                  <div class="h-full rounded-full bg-red-500" :style="{ width: projectBarWidth(project) }" />
                </div>
              </div>
            </div>
          </div>

          <div class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-base font-semibold text-gray-900">Самые рискованные связки</h3>
              <span class="text-xs text-gray-500">проект × сотрудник</span>
            </div>

            <div class="space-y-3">
              <div v-for="row in topRiskRows" :key="`${row.project_name}-${row.employee_id}`" class="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <div class="text-sm font-semibold text-gray-900">{{ row.employee_name }}</div>
                    <div class="text-xs text-gray-500">{{ row.project_name }}</div>
                  </div>
                  <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', lossBadgeClass(row.loss_rate)]">
                    {{ formatPercent(row.loss_rate) }}
                  </span>
                </div>
                <div class="mt-2 grid grid-cols-3 gap-2 text-xs text-gray-500">
                  <div>Всего: <span class="font-semibold text-gray-700">{{ formatHours(row.total_hours) }}</span></div>
                  <div>Учтено: <span class="font-semibold text-emerald-700">{{ formatHours(row.billable_hours) }}</span></div>
                  <div>Не учтено: <span class="font-semibold text-red-700">{{ formatHours(row.non_billable_hours) }}</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="overflow-x-auto border rounded-lg">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Проект</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Сотрудник</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Всего</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Учтено</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Не учтено</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Потери %</th>
              </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
              <tr v-for="row in reportData.risk_rows" :key="`${row.project_name}-${row.employee_id}`" class="hover:bg-gray-50">
                <td class="px-4 py-3 text-sm text-gray-900">{{ row.project_name }}</td>
                <td class="px-4 py-3 text-sm text-gray-700">{{ row.employee_name }}</td>
                <td class="px-4 py-3 text-sm text-gray-900 text-right font-medium">{{ row.total_hours.toFixed(2) }}</td>
                <td class="px-4 py-3 text-sm text-emerald-700 text-right">{{ row.billable_hours.toFixed(2) }}</td>
                <td class="px-4 py-3 text-sm text-red-700 text-right">{{ row.non_billable_hours.toFixed(2) }}</td>
                <td class="px-4 py-3 text-sm text-right">
                  <span :class="['inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', lossBadgeClass(row.loss_rate)]">
                    {{ formatPercent(row.loss_rate) }}
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
