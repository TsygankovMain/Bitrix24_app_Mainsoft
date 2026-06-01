<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch, provide } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectTaskReportTable from '../../components/reports/ProjectTaskReportTable.vue'
import ReportMetricCard from '../../components/reports/ReportMetricCard.vue'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
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
} = useReportFilters()

const { hasGenerated, generateReport, resetGenerated } = useReportGenerator({
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
        )
    })

    if (payload) {
        reportData.value = payload
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
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4">
        <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit" class="ms-surface ms-report-surface">
        <template #header>
          <div class="flex flex-col gap-4 w-full">
            <!-- Title and Actions -->
            <div class="flex flex-row justify-between items-center w-full">
              <div>
                <ProseH2 class="!text-slate-900">Учет по проектам/задачам</ProseH2>
                <p class="mt-1 text-xs text-slate-500">Группировка: Проект → Задача → Подзадача → Сотрудник → Метки времени</p>
              </div>
              <div class="flex gap-2">
                <B24Button label="Скачать Excel" color="success" :disabled="!hasGenerated || reportData.length === 0" loading-auto @click="handleExportExcel" />
                <B24Button label="Сформировать" loading-auto @click="fetchReport" />
              </div>
            </div>

            <!-- Filters -->
            <div class="ms-filter-wrap flex flex-wrap items-end gap-4">
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

        <!-- Loading State -->
        <div v-if="isLoading" class="flex justify-center py-8">
          <span class="text-slate-500">Загрузка...</span>
        </div>

        <!-- Main Content -->
        <div v-else-if="hasGenerated && reportData.length > 0" class="flex flex-col gap-6">
          <!-- KPI Metrics -->
          <div class="ms-kpi-grid">
            <ReportMetricCard
              label="Всего часов"
              :value="kpiMetrics.totalHours"
              tone="default"
            />
            <ReportMetricCard
              label="Учтено"
              :value="kpiMetrics.billableHours"
              tone="success"
            />
            <ReportMetricCard
              label="Не учтено"
              :value="kpiMetrics.nonBillableHours"
              tone="danger"
            />
            <ReportMetricCard
              label="% Учтённости"
              :value="kpiMetrics.billabilityPercent + '%'"
              tone="info"
            />
          </div>

          <!-- Report Table -->
          <ProjectTaskReportTable :rows="reportData" />
        </div>

        <!-- No Data State -->
        <div v-else-if="hasGenerated" class="ms-empty-state">
          Нет данных
        </div>

        <!-- Initial State -->
        <div v-else class="ms-empty-state">
          Выберите фильтры и нажмите «Сформировать»
        </div>
      </B24Card>
    </div>
  </div>
</template>
