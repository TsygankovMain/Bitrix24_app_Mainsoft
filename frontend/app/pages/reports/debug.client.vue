<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import EmployeeProjectTable from '../../components/reports/EmployeeProjectTable.vue'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'
import type { HierarchicalReportNode } from '~/types/report'

interface DebugTimesheetRow {
  id: string | number
  date?: string | null
  employee_id?: string | number
  project_title?: string | null
  task_id?: string | number
  task_hierarchy_titles?: string[]
  hours?: number
  non_billable_hours?: number
}

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Диагностика отчетов'
})

// region Init ////
const { initApp, processErrorGlobal } = useAppInit('ReportsDebugPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const toast = useToast()
// endregion ////

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

// Report State
const activeTab = ref('employee-project')
const reportData = ref<HierarchicalReportNode[]>([])
const dateFrom = ref('') // YYYY-MM-DD
const isInit = ref(false)

const isSyncing = ref(false)
const timesheetItems = ref<DebugTimesheetRow[]>([])
const itemsPage = ref(1)
const itemsTotal = ref(0)
const itemsPages = ref(0)
const itemsLimit = 50

async function fetchReport() {
    isLoading.value = true
    try {
        if (activeTab.value === 'employee-project') {
            reportData.value = await apiStore.getReportEmployeeProject(dateFrom.value)
        } else if (activeTab.value === 'project-employee') {
            reportData.value = await apiStore.getReportProjectEmployee(dateFrom.value)
        } else if (activeTab.value === 'raw-data') {
            await fetchTimesheetList()
        }
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}

async function fetchTimesheetList(page = 1) {
    // specialized fetch for raw data that supports pagination
    // we don't set global isLoading to full blocking if we just change pages, but consistency is key
    // ошибки пробрасываются вызывающему (fetchReport ловит их в своём try/catch)
    const result = await apiStore.getTimesheetsList(page, itemsLimit)
    timesheetItems.value = result.items as DebugTimesheetRow[]
    itemsTotal.value = result.total
    itemsPage.value = result.page
    itemsPages.value = result.pages
}

async function handleSync() {
    isSyncing.value = true
    try {
        const result = await apiStore.syncTimesheets()
        toast.add({ title: `Синхронизировано ${result.count} записей!`, color: 'air-primary-success' })
        if (activeTab.value === 'raw-data') {
            await fetchTimesheetList()
        }
    } catch (e) {
         processErrorGlobal(e)
    } finally {
        isSyncing.value = false
    }
}

async function changePage(newPage: number) {
    if (newPage < 1 || newPage > itemsPages.value) return
    isLoading.value = true
    try {
        await fetchTimesheetList(newPage)
    } catch(e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}

watch(activeTab, () => fetchReport())

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    // Don't set title here to avoid overwriting the main one if navigating back/forth rapidly?
    // Actually, setting title is fine.
    await $b24.parent.setTitle('Диагностика отчетов') 
    isInit.value = true
    
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
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit" class="ms-surface ms-report-surface">
          <template #header>
            <div class="flex flex-row justify-between items-center w-full">
                <div>
                  <ProseH2 class="!text-slate-900">Диагностика отчетов</ProseH2>
                  <p class="mt-1 text-sm text-slate-500">Технический экран для сверки агрегатов и локальных данных.</p>
                </div>
                <div class="flex gap-2 items-center">
                    <B24Button v-if="activeTab === 'raw-data'" label="Синхронизировать с Б24" :loading="isSyncing" color="success" class="mr-2" @click="handleSync" />
                    <input v-model="dateFrom" type="date" class="px-2 py-1" @change="fetchReport" >
                    <B24Button label="Refresh" loading-auto @click="fetchReport" />
                </div>
            </div>
          </template>

          <div class="ms-tabbar mb-4">
              <button 
                :class="['ms-tab-btn', activeTab === 'employee-project' ? 'ms-tab-btn-active' : '']"
                @click="activeTab = 'employee-project'"
              >
                Employee / Project
              </button>
              <button 
                :class="['ms-tab-btn', activeTab === 'project-employee' ? 'ms-tab-btn-active' : '']"
                @click="activeTab = 'project-employee'"
              >
                Project / Employee
              </button>
              <button 
                :class="['ms-tab-btn', activeTab === 'raw-data' ? 'ms-tab-btn-active' : '']"
                @click="activeTab = 'raw-data'"
              >
                Проверка данных
              </button>
          </div>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-slate-500">Loading...</span>
          </div>
          <div v-else>
              <EmployeeProjectTable v-if="activeTab === 'employee-project'" :data="reportData" />
              <ProjectEmployeeTable v-if="activeTab === 'project-employee'" :data="reportData" />
              
              <div v-if="activeTab === 'raw-data'">
                  <div class="mb-2 text-sm text-slate-500">Всего записей: {{ itemsTotal }}</div>
                  <div class="ms-table-shell">
                    <table class="ms-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Дата</th>
                                <th>Сотрудник</th>
                                <th>Проект</th>
                                <th>ID Задачи</th>
                                <th>Иерархия</th>
                                <th>Часы</th>
                                <th>Неучт. Часы</th>
                                <th>Учит?</th>
                                <th>Описание</th>
                                <th>Создано</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="item in timesheetItems" :key="item.id">
                                <td class="whitespace-nowrap text-sm text-slate-900">{{ item.id }}</td>
                                <td class="whitespace-nowrap text-sm text-slate-500">{{ item.date ? new Date(item.date).toLocaleDateString() : '-' }}</td>
                                <td class="whitespace-nowrap text-sm text-slate-500">{{ item.employee_id }}</td>
                                <td class="text-sm text-slate-500">{{ item.project_title || '-' }}</td>
                                <td class="whitespace-nowrap text-sm text-slate-500">{{ item.task_id }}</td>
                                <td class="max-w-xs truncate text-sm text-slate-500" :title="item.task_hierarchy_titles ? item.task_hierarchy_titles.join(' > ') : ''">
                                    {{ item.task_hierarchy_titles ? item.task_hierarchy_titles.join(' > ') : '-' }}
                                </td>
                                <td class="whitespace-nowrap text-sm font-medium text-slate-900">{{ item.hours }}</td>
                                <td class="whitespace-nowrap text-sm text-slate-500">{{ item.non_billable_hours }}</td>
                                <td class="whitespace-nowrap text-sm text-slate-500">
                                    <span :class="item.is_billable ? 'text-green-600' : 'text-slate-400'">
                                        {{ item.is_billable ? 'Да' : 'Нет' }}
                                    </span>
                                </td>
                                <td class="max-w-xs truncate text-sm text-slate-500" :title="item.description">{{ item.description || '-' }}</td>
                                <td class="whitespace-nowrap text-sm text-slate-500">{{ item.created_at ? new Date(item.created_at).toLocaleString() : '-' }}</td>
                            </tr>
                        </tbody>
                    </table>
                  </div>
                  
                  <!-- Pagination -->
                  <div v-if="itemsPages > 1" class="mt-4 flex justify-between items-center">
                      <button 
                        :disabled="itemsPage <= 1" 
                        class="rounded-xl border border-slate-200 px-3 py-1 text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                        @click="changePage(itemsPage - 1)"
                      >
                        Prev
                      </button>
                      <span class="text-sm text-slate-600">Page {{ itemsPage }} of {{ itemsPages }}</span>
                      <button 
                        :disabled="itemsPage >= itemsPages" 
                        class="rounded-xl border border-slate-200 px-3 py-1 text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                        @click="changePage(itemsPage + 1)"
                      >
                        Next
                      </button>
                  </div>
              </div>
          </div>
      </B24Card>
    </div>
  </div>
</template>
