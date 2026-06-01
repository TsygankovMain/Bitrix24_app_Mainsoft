<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import EmployeeProjectTable from '../../components/reports/EmployeeProjectTable.vue'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
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
} = useReportFilters()

const { hasGenerated, generateReport } = useReportGenerator({
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
        )
    })

    if (payload) {
        reportData.value = payload
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
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit" class="ms-surface ms-report-surface">
          <template #header>
            <div class="flex flex-col gap-4 w-full">
                <div class="flex flex-row justify-between items-center w-full">
                    <ProseH2 class="!text-slate-900">Отчет по сотрудникам</ProseH2>
                    <div class="flex gap-2">
                        <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                        <B24Button label="Сформировать" loading-auto @click="fetchReport" />
                    </div>
                </div>
                
                <!-- Filters -->
                <div class="ms-filter-wrap flex flex-wrap gap-4 items-end">
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

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-slate-500">Загрузка...</span>
          </div>
          <div v-else-if="hasGenerated && reportData.length > 0">
              <EmployeeProjectTable :data="reportData" :clickable-labels="clickableLabelsEnabled" :entity-type-id="entityTypeId" />
          </div>
          <div v-else-if="hasGenerated" class="ms-empty-state">
              Нет данных
          </div>
          <div v-else class="ms-empty-state">
              Выберите фильтры и нажмите «Сформировать»
          </div>
      </B24Card>
    </div>
  </div>
</template>
