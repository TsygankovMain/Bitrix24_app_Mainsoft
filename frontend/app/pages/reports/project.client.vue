<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'
import ReportShell from '../../components/reports/ReportShell.vue'
import { readProjectReportPreset } from '~/utils/reportNavigation'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { HierarchicalReportNode } from '~/types/report'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Отчет по проектам',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init ////
const { initApp, processErrorGlobal } = useAppInit('ProjectReportPage')
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
const reportData = ref<HierarchicalReportNode[]>([])
const isInit = ref(false)
const entityTypeId = ref<string | number>(0)

const clickableLabelsEnabled = computed(() => userSettings.configSettings.clickableLabelsEnabled ?? false)

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
} = useReportFilters('project')

const { hasGenerated, syncWarning, generateReport, resetGenerated } = useReportGenerator({
    setLoading: (value) => {
        isLoading.value = value
    },
    onError: processErrorGlobal
})

const progress = useProgress()

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
        reportName: 'По проектам',
        syncDateFrom: dateFrom.value,
        syncDateTo: dateTo.value,
        loader: () => apiStore.getReportProjectEmployee(
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
    progress.begin('Excel: «По проектам»', 0, 'Готовим файл выгрузки')
    try {
        const blob = await apiStore.exportReportProjectEmployee(
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
        a.download = `Report_Projects_${dateFrom.value}_${dateTo.value}.xlsx`
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

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Отчет по проектам') 
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
// endregion ////
</script>

<template>
  <ReportShell
    v-if="isInit"
    title="Отчёт по проектам"
    description="Проект → сотрудник → задача: куда ушли часы по каждому проекту"
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
    <ProjectEmployeeTable
      :data="reportData"
      :clickable-labels="clickableLabelsEnabled"
      :entity-type-id="entityTypeId"
    />
  </ReportShell>
</template>
