<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch, provide } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectTaskReportTable from '../../components/reports/ProjectTaskReportTable.vue'
import ReportShell from '../../components/reports/ReportShell.vue'
import ReportTotalsStrip from '../../components/reports/ReportTotalsStrip.vue'
import { readProjectReportPreset } from '~/utils/reportNavigation'
import { openCrmItemCard } from '~/utils/openCrmItem'
import { PROJECT_TASK_LABEL_KEY } from '~/composables/useProjectTaskLabel'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { ProjectTaskReportNode } from '~/types/report'
import { formatHours, formatPercent } from '~/utils/reportFormat'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Учет по проектам/задачам',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init ////
const { initApp, processErrorGlobal } = useAppInit('ProjectTaskReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const userSettings = useUserSettingsStore()
const route = useRoute()
// endregion ////

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

// Report State
const reportData = ref<ProjectTaskReportNode[]>([])
const isInit = ref(false)
const entityTypeId = ref<string | number>(0)

const clickableLabelsEnabled = computed(() => userSettings.configSettings.clickableLabelsEnabled ?? false)

// Кликабельные метки времени → открытие карточки CRM (provide для вложенных строк таблицы)
const labelClickEnabled = computed(() => clickableLabelsEnabled.value && !!entityTypeId.value)
function handleLabelClick(idElem: string | number) {
    if (labelClickEnabled.value) {
        openCrmItemCard(entityTypeId.value, idElem)
    }
}
provide(PROJECT_TASK_LABEL_KEY, {
    enabled: labelClickEnabled,
    onClick: handleLabelClick
})

// Filters State
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
    applyRouteProjectPreset
} = useReportFilters('project-task')

const { hasGenerated, syncWarning, generateReport, resetGenerated } = useReportGenerator({
    setLoading: (value) => {
        isLoading.value = value
    },
    onError: processErrorGlobal
})

const progress = useProgress()

// KPI Metrics (computed from reportData)
const kpiMetrics = computed(() => {
    const totalHours = reportData.value.reduce((sum, node) => sum + (node.total_hours || 0), 0)
    const billableHours = reportData.value.reduce((sum, node) => sum + (node.billable_hours || 0), 0)
    const nonBillableHours = reportData.value.reduce((sum, node) => sum + (node.non_billable_hours || 0), 0)

    return {
        totalHours: formatHours(totalHours),
        billableHours: formatHours(billableHours),
        nonBillableHours: formatHours(nonBillableHours),
        billabilityPercent: formatPercent(billableHours, totalHours)
    }
})

/**
 * Итоги для строки шапки.
 *
 * Цифры те же, что раньше лежали в карточках `ms-kpi-grid`, — считает их
 * kpiMetrics, здесь только раскладка по строке.
 */
const totals = computed(() => [
    { id: 'total', label: 'Всего', value: kpiMetrics.value.totalHours },
    { id: 'billable', label: 'Учтено', value: kpiMetrics.value.billableHours, tone: 'success' as const },
    { id: 'non-billable', label: 'Не учтено', value: kpiMetrics.value.nonBillableHours, tone: 'danger' as const },
    { id: 'billability', label: 'Учтённость', value: kpiMetrics.value.billabilityPercent + '%', tone: 'info' as const },
])

// Пресет меняет фильтр целиком. Перестраиваем отчёт только если он уже на экране:
// запускать генерацию за человека, который ещё ничего не нажимал, — не наше дело.
function handleFiltersApplied() {
    if (hasGenerated.value) {
        void fetchReport()
    }
}

function applyProjectPresetFromRoute() {
    return applyRouteProjectPreset(route.query as Record<string, unknown>)
}

async function syncWithRoutePreset() {
    const shouldAutogenerate = applyProjectPresetFromRoute()
    if (!shouldAutogenerate) {
        return
    }

    resetGenerated()
    reportData.value = []
    await fetchReport()
}

async function fetchReport() {
    const payload = await generateReport({
        reportName: 'По проектам/задачам',
        syncDateFrom: dateFrom.value,
        syncDateTo: dateTo.value,
        loader: () => apiStore.getReportProjectTaskEmployee(
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
function handleDataRefreshed() {
    void loadFilterOptions(true)
    if (hasGenerated.value) {
        void fetchReport()
    }
}

async function handleExportExcel() {
    progress.begin('Excel: «По проектам/задачам»', 0, 'Готовим файл выгрузки')
    try {
        const blob = await apiStore.exportReportProjectTaskEmployee(
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
        a.download = `Учет_по_проектам_${dateFrom.value}_${dateTo.value}.xlsx`
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

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Учет по проектам/задачам')
    isInit.value = true

    await loadFilterOptions()

    // Load entity type ID for clickable labels
    try {
      const cfg = await apiStore.getConfiguration()
      if (cfg?.sp_entity_type_id) {
        entityTypeId.value = cfg.sp_entity_type_id
      }
    } catch (e) {
      console.warn('Could not load entity type ID:', e)
    }

    // Set default range (current month)
    initCurrentMonthRange()

    await syncWithRoutePreset()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
// endregion ////

watch(
  () => [
    readProjectReportPreset(route.query as Record<string, unknown>)
  ],
  async () => {
    if (!isInit.value) {
      return
    }

    await syncWithRoutePreset()
  }
)
</script>

<template>
  <ReportShell
    v-if="isInit"
    title="Учёт по проектам и задачам"
    description="Проект → задача → подзадача → сотрудник → метки времени"
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
    :is-empty="reportData.length === 0"
    :export-disabled="!hasGenerated || reportData.length === 0"
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
    <template #totals>
      <ReportTotalsStrip v-if="hasGenerated && reportData.length > 0" :items="totals" />
    </template>

    <ProjectTaskReportTable :rows="reportData" />
  </ReportShell>
</template>
