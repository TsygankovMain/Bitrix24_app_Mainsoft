<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Отчет по проектам'
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('ProjectReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
// endregion ////

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

// Report State
const reportData = ref<any[]>([])
const dateFrom = ref('') // YYYY-MM-DD
const dateTo = ref('')   // YYYY-MM-DD
const isInit = ref(false)

// Filters State
const filterOptions = ref<{ employees: any[], projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string|number)[]>([])
const selectedProjects = ref<(string|number)[]>([])

async function fetchFilterOptions() {
    try {
        const res = await apiStore.getFilterOptions()
        filterOptions.value = res
    } catch (e) {
        processErrorGlobal(e)
    }
}

async function fetchReport() {
    isLoading.value = true
    try {
        reportData.value = await apiStore.getReportProjectEmployee(
            dateFrom.value, 
            dateTo.value, 
            selectedEmployees.value as string[], 
            selectedProjects.value as string[]
        )
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
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
    
    await fetchFilterOptions()

    // Set default range (current month)
    const now = new Date()
    dateFrom.value = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0]
    dateTo.value = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().split('T')[0]
    
    // Initial fetch
    await fetchReport()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
// endregion ////
</script>

<template>
  <div class="flex flex-col gap-4 p-4 min-h-screen">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit">
          <template #header>
            <div class="flex flex-col gap-4 w-full">
                <div class="flex flex-row justify-between items-center w-full">
                    <ProseH2>Отчет по проектам</ProseH2>
                    <B24Button label="Обновить" @click="fetchReport" loading-auto />
                </div>
                
                 <!-- Filters -->
                 <div class="flex flex-wrap gap-4 items-end bg-gray-50 p-4 rounded-lg">
                    <DateRangeFilter 
                        v-model:dateFrom="dateFrom" 
                        v-model:dateTo="dateTo" 
                        @change="fetchReport"
                    />
                    
                    <!-- For Project Report, it might make sense to filter by Projects first? Or both. User asked for both filters in both reports -->
                    <MultiSelectFilter 
                        label="Сотрудники" 
                        :options="filterOptions.employees" 
                        v-model="selectedEmployees" 
                        @update:modelValue="fetchReport"
                    />
                    
                    <MultiSelectFilter 
                        label="Проекты" 
                        :options="filterOptions.projects" 
                        v-model="selectedProjects" 
                        @update:modelValue="fetchReport"
                    />
                </div>
            </div>
          </template>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-gray-500">Загрузка...</span>
          </div>
          <div v-else>
              <ProjectEmployeeTable :data="reportData" />
          </div>
      </B24Card>
  </div>
</template>
