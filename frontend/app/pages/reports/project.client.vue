<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
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
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit" class="ms-surface ms-report-surface">
          <template #header>
            <div class="flex flex-col gap-4 w-full">
                <div class="flex flex-row justify-between items-center w-full">
                    <ProseH2 class="!text-slate-900">Отчет по проектам</ProseH2>
                    <div class="flex gap-2">
                        <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                        <B24Button label="Сформировать" loading-auto @click="fetchReport" />
                    </div>
                </div>
                
                 <!-- Filters -->
                 <div class="ms-filter-wrap flex flex-wrap items-end gap-4">
                    <DateRangeFilter 
                        v-model:date-from="dateFrom" 
                        v-model:date-to="dateTo" 
                    />
                    
                    <!-- For Project Report, it might make sense to filter by Projects first? Or both. User asked for both filters in both reports -->
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

          <div v-if="syncWarning" class="ms-panel-warning">
              {{ syncWarning }}
          </div>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-slate-500">Загрузка...</span>
          </div>
          <div v-else-if="hasGenerated && reportData.length > 0">
              <ProjectEmployeeTable :data="reportData" :clickable-labels="clickableLabelsEnabled" :entity-type-id="entityTypeId" />
          </div>
          <div v-else-if="hasGenerated" class="py-8 text-center text-slate-500">
              Нет данных
          </div>
          <div v-else class="py-8 text-center text-slate-500">
              Выберите фильтры и нажмите «Сформировать»
          </div>
      </B24Card>
    </div>
  </div>
</template>
