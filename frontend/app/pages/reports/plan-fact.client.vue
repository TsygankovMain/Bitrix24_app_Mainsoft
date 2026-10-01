<script setup lang="ts">
/**
 * Отчёт «План / факт».
 *
 * План — поле «Оценка» в задаче портала, факт — списания приложения. Данные
 * живые: оценки читаются с портала при каждом «Сформировать», поэтому после
 * правки оценки или списания достаточно сформировать отчёт заново.
 *
 * Включён только для порталов из белого списка сервера
 * (main/plan_fact_report.py). Остальным ручка отвечает 404, пункта меню нет, а
 * по прямому адресу эта страница показывает заглушку.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import PlanFactReportTable from '../../components/reports/PlanFactReportTable.vue'
import ReportShell from '../../components/reports/ReportShell.vue'
import ReportTotalsStrip from '../../components/reports/ReportTotalsStrip.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { PlanFactNode, PlanFactReport } from '~/types/report'
import { formatHours } from '~/utils/reportFormat'
import { isPlanFactEnabled, keepPlanned, sumTotals } from '~/utils/planFactReport'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'План / факт',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('PlanFactReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const { features, loadPortalFeatures } = usePortalFeatures()
const isAvailable = computed(() => isPlanFactEnabled(features.value))

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

const report = ref<PlanFactReport>({ projects: [], employees: [] })
const isInit = ref(false)

type Grouping = 'projects' | 'employees'
const grouping = ref<Grouping>('projects')
const onlyPlanned = ref(false)
const search = ref('')
const table = ref<InstanceType<typeof PlanFactReportTable> | null>(null)

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
} = useReportFilters('plan-fact')

const { hasGenerated, syncWarning, generateReport } = useReportGenerator({
  setLoading: (value) => {
    isLoading.value = value
  },
  onError: processErrorGlobal
})

const progress = useProgress()

const sourceRows = computed<PlanFactNode[]>(() => report.value[grouping.value] || [])
const rows = computed<PlanFactNode[]>(() => (onlyPlanned.value ? keepPlanned(sourceRows.value) : sourceRows.value))
const isEmpty = computed(() => report.value.projects.length === 0 && report.value.employees.length === 0)

const totals = computed(() => {
  const sum = sumTotals(rows.value)

  return [
    { id: 'plan', label: 'План', value: sum.plan ? formatHours(sum.plan) : '—', tone: 'info' as const },
    { id: 'total', label: 'Факт всего', value: formatHours(sum.total) },
    { id: 'billable', label: 'Факт учит.', value: formatHours(sum.billable), tone: 'success' as const },
    { id: 'non-billable', label: 'Факт неучит.', value: formatHours(sum.nonBillable), tone: 'danger' as const },
    {
      id: 'remainder',
      label: 'Остаток',
      value: sum.plan ? formatHours(sum.plan - sum.plannedFact) : '—',
      caption: 'по задачам с планом',
      tone: sum.plan - sum.plannedFact < 0 ? 'danger' as const : 'default' as const,
    },
  ]
})

const warning = computed(() => [syncWarning.value, report.value.plan_warning].filter(Boolean).join(' '))

const nameHeader = computed(() => (
  grouping.value === 'projects' ? 'Проект / задача / сотрудник' : 'Сотрудник / проект / задача'
))
const depthLabels = computed(() => (
  grouping.value === 'projects' ? ['проектов', 'этапов', 'всё'] : ['сотрудников', 'проектов', 'всё']
))

function setGrouping(value: Grouping) {
  grouping.value = value
}

function expandTo(depth: number) {
  table.value?.expandToDepth(depth)
}

function handleFiltersApplied() {
  if (hasGenerated.value) {
    void fetchReport()
  }
}

async function fetchReport() {
  const payload = await generateReport({
    reportName: 'План / факт',
    syncDateFrom: dateFrom.value,
    syncDateTo: dateTo.value,
    loader: () => apiStore.getReportPlanFact(
      dateFrom.value,
      dateTo.value,
      employeeFilter.value,
      projectFilter.value
    ),
    allowSyncFallback: true
  })

  if (payload) {
    report.value = {
      projects: payload.projects || [],
      employees: payload.employees || [],
      plan_warning: payload.plan_warning || '',
    }
  }
}

function handleDataRefreshed() {
  void loadFilterOptions(true)
  if (hasGenerated.value) {
    void fetchReport()
  }
}

async function handleExportExcel() {
  progress.begin('Excel: «План / факт»', 0, 'Готовим файл выгрузки')
  try {
    const blob = await apiStore.exportReportPlanFact(
      dateFrom.value,
      dateTo.value,
      employeeFilter.value,
      projectFilter.value
    )
    // Бэк при ошибке отдаёт JSON — не сохраняем его как .xlsx
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
    a.download = `План_факт_${dateFrom.value}_${dateTo.value}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    progress.end()
  }
}

onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('План / факт')
    await loadPortalFeatures()
    isInit.value = true

    if (!isAvailable.value) {
      return
    }

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
  <div v-if="isInit && !isAvailable" class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="ms-surface ms-empty-state">Отчёт «План / факт» недоступен на этом портале.</div>
    </div>
  </div>

  <ReportShell
    v-else-if="isInit"
    title="План / факт"
    description="План — поле «Оценка» в задаче, факт — списанные часы. Оценки читаются с портала при каждом формировании"
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
    :is-empty="isEmpty"
    :export-disabled="!hasGenerated || isEmpty"
    :warning="warning"
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
      <ReportTotalsStrip v-if="hasGenerated && !isEmpty" :items="totals" />
    </template>

    <div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-600">
      <div class="flex gap-1">
        <B24Button
          size="sm"
          label="Проект → задача → сотрудник"
          :color="grouping === 'projects' ? 'air-primary' : 'air-secondary-no-accent'"
          @click="setGrouping('projects')"
        />
        <B24Button
          size="sm"
          label="Сотрудник → проект → задача"
          :color="grouping === 'employees' ? 'air-primary' : 'air-secondary-no-accent'"
          @click="setGrouping('employees')"
        />
      </div>

      <div class="flex items-center gap-1">
        <span class="text-slate-400">Раскрыть до:</span>
        <B24Button
          v-for="(label, index) in depthLabels"
          :key="label"
          size="xs"
          color="air-secondary-no-accent"
          :label="label"
          @click="expandTo(index === 2 ? 99 : index)"
        />
      </div>

      <label class="flex cursor-pointer items-center gap-2">
        <B24Switch v-model="onlyPlanned" />
        <span>только с планом</span>
      </label>

      <input
        v-model="search"
        type="search"
        placeholder="Поиск: проект, задача, сотрудник"
        class="h-8 w-64 max-w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none focus:border-[#0075ff]"
      >
    </div>

    <PlanFactReportTable ref="table" :rows="rows" :search="search" :name-header="nameHeader" />

    <p class="mt-3 text-xs leading-relaxed text-slate-400">
      Если оценка стоит и на этапе, и на подзадачах, в итог идёт оценка этапа — план не удваивается; расхождение
      помечено «≠». Остаток и выполнение считаются только по задачам с планом. В разрезе по сотрудникам план — оценки
      задач, где сотрудник ответственный. Название задачи открывает её карточку: поправьте оценку и сформируйте отчёт заново.
    </p>
  </ReportShell>
</template>
