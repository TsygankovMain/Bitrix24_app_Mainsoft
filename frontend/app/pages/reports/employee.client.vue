<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import EmployeeProjectTable from '../../components/reports/EmployeeProjectTable.vue'
import ReportShell from '../../components/reports/ReportShell.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { useReportGenerator } from '~/composables/useReportGenerator'
import { useProgress } from '~/composables/useProgress'
import type { HierarchicalReportNode } from '~/types/report'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Отчет по сотрудникам',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init ////
const { initApp, processErrorGlobal } = useAppInit('EmployeeReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const userSettings = useUserSettingsStore()
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
} = useReportFilters('employee')

const { hasGenerated, syncWarning, generateReport } = useReportGenerator({
  setLoading: (value) => {
    isLoading.value = value
  },
  onError: processErrorGlobal
})

const progress = useProgress()

async function fetchReport() {
    const payload = await generateReport({
        reportName: 'По сотрудникам',
        syncDateFrom: dateFrom.value,
        syncDateTo: dateTo.value,
        loader: () => apiStore.getReportEmployeeProject(
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

// Пресет меняет фильтр целиком. Перестраиваем отчёт только если он уже на экране:
// запускать генерацию за человека, который ещё ничего не нажимал, — не наше дело.
function handleFiltersApplied() {
    if (hasGenerated.value) {
        void fetchReport()
    }
}

async function handleExportExcel() {
    progress.begin('Excel: «По сотрудникам»', 0, 'Готовим файл выгрузки')
    try {
        const blob = await apiStore.exportReportEmployeeProject(
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
        a.download = `Report_Employees_${dateFrom.value}_${dateTo.value}.xlsx`
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
    await $b24.parent.setTitle('Отчет по сотрудникам') 
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
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
// endregion ////
</script>

<template>
  <ReportShell
    v-if="isInit"
    title="Отчёт по сотрудникам"
    description="Сотрудник → проект → задача: сколько часов у кого ушло"
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
    <EmployeeProjectTable
      :data="reportData"
      :clickable-labels="clickableLabelsEnabled"
      :entity-type-id="entityTypeId"
    />
  </ReportShell>
</template>
