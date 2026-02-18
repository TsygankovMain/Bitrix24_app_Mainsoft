<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import EmployeeProjectTable from '../../components/reports/EmployeeProjectTable.vue'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Отчет по сотрудникам',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('EmployeeReportPage')
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
const reportData = ref<any[]>([])
const dateFrom = ref('') // YYYY-MM-DD
const dateTo = ref('')   // YYYY-MM-DD
const isInit = ref(false)
const entityTypeId = ref<string | number>(0)

const clickableLabelsEnabled = computed(() => userSettings.configSettings.clickableLabelsEnabled ?? false)

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
        await apiStore.syncTimesheets()
        reportData.value = await apiStore.getReportEmployeeProject(
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

// Excel Export
import * as XLSX from 'xlsx'


function handleExportExcel() {
    const exportData: any[] = [];
    const rowLevels: number[] = [];
    
    // Recursive function to flatten data
    const processNode = (node: any, level = 0) => {
        const indent = "    ".repeat(level);
        exportData.push({
            "Название": indent + node.name,
            // "Тип": node.type,
            "Всего часов": node.total_hours,
            "Учитываемые": node.billable_hours,
            "Не учитываемые": node.non_billable_hours
        });
        rowLevels.push(level);

        if (node.children && node.children.length > 0) {
            node.children.forEach((child: any) => processNode(child, level + 1));
        }
    };

    reportData.value.forEach(node => processNode(node));

    const worksheet = XLSX.utils.json_to_sheet(exportData);
    
    // Adjust Column Widths
    worksheet['!cols'] = [
        { wch: 50 }, // Name
        { wch: 15 }, // Total Hours
        { wch: 15 }, // Billable
        { wch: 15 }  // Non-billable
    ];

    // Adjust Row Levels (Grouping)
    const rows: any[] = [{ level: 0 }]; // Header row
    rowLevels.forEach(level => {
        rows.push({ level: level, hidden: false });
    });
    worksheet['!rows'] = rows;

    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Отчет по сотрудникам");
    XLSX.writeFile(workbook, `Report_Employees_${dateFrom.value}_${dateTo.value}.xlsx`);
}

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Отчет по сотрудникам') 
    isInit.value = true
    
    await fetchFilterOptions()
    
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
    const now = new Date()
    dateFrom.value = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0] ?? ''
    dateTo.value = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().split('T')[0] ?? ''

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
                    <ProseH2>Отчет по сотрудникам</ProseH2>
                    <div class="flex gap-2">
                        <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                        <B24Button label="Обновить" @click="fetchReport" loading-auto />
                    </div>
                </div>
                
                <!-- Filters -->
                <div class="flex flex-wrap gap-4 items-end bg-gray-50 p-4 rounded-lg">
                    <DateRangeFilter 
                        v-model:dateFrom="dateFrom" 
                        v-model:dateTo="dateTo" 
                        @change="fetchReport"
                    />
                    
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
              <EmployeeProjectTable :data="reportData" :clickable-labels="clickableLabelsEnabled" :entity-type-id="entityTypeId" />
          </div>
      </B24Card>
  </div>
</template>
