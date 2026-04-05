<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
import { getCurrentMonthRange } from '~/utils/reportDateRange'
import { readProjectReportPreset } from '~/utils/reportNavigation'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Отчет по проектам',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('ProjectReportPage')
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
const reportData = ref<any[]>([])
const dateFrom = ref('') // YYYY-MM-DD
const dateTo = ref('')   // YYYY-MM-DD
const isInit = ref(false)
const hasGenerated = ref(false)
const entityTypeId = ref<string | number>(0)

const clickableLabelsEnabled = computed(() => userSettings.configSettings.clickableLabelsEnabled ?? false)

// Filters State
const filterOptions = ref<{ employees: any[], projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string|number)[]>([])
const selectedProjects = ref<(string|number)[]>([])
const employeeFilterMode = ref<'include' | 'exclude'>('include')
const projectFilterMode = ref<'include' | 'exclude'>('include')

async function fetchEmployeeOptions() {
    try {
        filterOptions.value.employees = await apiStore.getFilterEmployees()
    } catch (e) {
        processErrorGlobal(e)
    }
}

async function fetchProjectOptions() {
    try {
        filterOptions.value.projects = await apiStore.getFilterProjects()
    } catch (e) {
        processErrorGlobal(e)
    }
}

async function fetchFilterOptions() {
    await Promise.all([
        fetchEmployeeOptions(),
        fetchProjectOptions()
    ])
}

function applyProjectPresetFromRoute() {
    const preset = readProjectReportPreset(route.query as Record<string, unknown>)
    if (!preset.projectIds.length) {
        return false
    }

    selectedProjects.value = preset.projectIds
    projectFilterMode.value = 'include'

    if (preset.projectName && !filterOptions.value.projects.some(option => String(option.id) === preset.projectIds[0])) {
        filterOptions.value.projects = [
            { id: preset.projectIds[0], name: preset.projectName },
            ...filterOptions.value.projects,
        ]
    }

    return preset.autogenerate
}

async function syncWithRoutePreset() {
    const shouldAutogenerate = applyProjectPresetFromRoute()
    if (!shouldAutogenerate) {
        return
    }

    hasGenerated.value = false
    reportData.value = []
    await fetchReport()
}

async function fetchReport() {
    isLoading.value = true
    try {
        await apiStore.syncTimesheets()
        reportData.value = await apiStore.getReportProjectEmployee(
            dateFrom.value, 
            dateTo.value, 
            { ids: selectedEmployees.value, mode: employeeFilterMode.value },
            { ids: selectedProjects.value, mode: projectFilterMode.value }
        )
        hasGenerated.value = true
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
    XLSX.utils.book_append_sheet(workbook, worksheet, "Отчет по проектам");
    XLSX.writeFile(workbook, `Report_Projects_${dateFrom.value}_${dateTo.value}.xlsx`);
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
    const range = getCurrentMonthRange()
    dateFrom.value = range.dateFrom
    dateTo.value = range.dateTo

    await syncWithRoutePreset()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})

watch(
  () => [
    route.query.project_id,
    route.query.project_ids,
    route.query.project_name,
    route.query.autogenerate
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

      <B24Card v-if="isInit" class="ms-surface">
          <template #header>
            <div class="flex flex-col gap-4 w-full">
                <div class="flex flex-row justify-between items-center w-full">
                    <ProseH2 class="!text-slate-900">Отчет по проектам</ProseH2>
                    <div class="flex gap-2">
                        <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                        <B24Button label="Сформировать" @click="fetchReport" loading-auto />
                    </div>
                </div>
                
                 <!-- Filters -->
                 <div class="ms-filter-wrap flex flex-wrap items-end gap-4">
                    <DateRangeFilter 
                        v-model:dateFrom="dateFrom" 
                        v-model:dateTo="dateTo" 
                    />
                    
                    <!-- For Project Report, it might make sense to filter by Projects first? Or both. User asked for both filters in both reports -->
                    <MultiSelectFilter 
                        label="Сотрудники" 
                        :options="filterOptions.employees" 
                        v-model="selectedEmployees" 
                        v-model:mode="employeeFilterMode"
                    />
                    
                    <MultiSelectFilter 
                        label="Проекты" 
                        :options="filterOptions.projects" 
                        v-model="selectedProjects" 
                        v-model:mode="projectFilterMode"
                    />
                </div>
            </div>
          </template>

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
