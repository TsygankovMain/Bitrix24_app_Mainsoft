<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import EmployeeProjectTable from '../../components/reports/EmployeeProjectTable.vue'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: t('page.index.seo.title') // We might want to update the title key, but keep it for now
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('ReportsDebugPage')
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
const activeTab = ref('employee-project')
const reportData = ref<any[]>([])
const dateFrom = ref('') // YYYY-MM-DD
const isInit = ref(false)

const isSyncing = ref(false)
const timesheetItems = ref<any[]>([])
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
    try {
         const result = await apiStore.getTimesheetsList(page, itemsLimit)
         timesheetItems.value = result.items
         itemsTotal.value = result.total
         itemsPage.value = result.page
         itemsPages.value = result.pages
    } catch (e) {
        throw e // caught by fetchReport or called directly
    }
}

async function handleSync() {
    isSyncing.value = true
    try {
        const result = await apiStore.syncTimesheets()
        alert(`Синхронизировано ${result.count} записей!`)
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
    await $b24.parent.setTitle('Debug Report') 
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
  <div class="flex flex-col gap-4 p-4 min-h-screen">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit">
          <template #header>
            <div class="flex flex-row justify-between items-center w-full">
                <ProseH2>Debug Report</ProseH2>
                <div class="flex gap-2 items-center">
                    <B24Button v-if="activeTab === 'raw-data'" label="Синхронизировать с Б24" @click="handleSync" :loading="isSyncing" color="success" class="mr-2" />
                    <input type="date" v-model="dateFrom" class="border rounded px-2 py-1 outline-none focus:ring-2 focus:ring-blue-500" @change="fetchReport" />
                    <B24Button label="Refresh" @click="fetchReport" loading-auto />
                </div>
            </div>
          </template>

          <div class="mb-4 flex gap-2">
              <button 
                @click="activeTab = 'employee-project'"
                :class="['px-4 py-2 rounded transition-colors', activeTab === 'employee-project' ? 'bg-blue-600 text-white' : 'bg-gray-100 hover:bg-gray-200 text-gray-800']"
              >
                Employee / Project
              </button>
              <button 
                @click="activeTab = 'project-employee'"
                :class="['px-4 py-2 rounded transition-colors', activeTab === 'project-employee' ? 'bg-blue-600 text-white' : 'bg-gray-100 hover:bg-gray-200 text-gray-800']"
              >
                Project / Employee
              </button>
              <button 
                @click="activeTab = 'raw-data'"
                :class="['px-4 py-2 rounded transition-colors', activeTab === 'raw-data' ? 'bg-blue-600 text-white' : 'bg-gray-100 hover:bg-gray-200 text-gray-800']"
              >
                Сырые данные (БД)
              </button>
          </div>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-gray-500">Loading...</span>
          </div>
          <div v-else>
              <EmployeeProjectTable v-if="activeTab === 'employee-project'" :data="reportData" />
              <ProjectEmployeeTable v-if="activeTab === 'project-employee'" :data="reportData" />
              
              <div v-if="activeTab === 'raw-data'">
                  <div class="mb-2 text-sm text-gray-500">Всего записей: {{ itemsTotal }}</div>
                  <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200 border">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Дата</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Сотрудник</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Проект</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID Задачи</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Иерархия</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Часы</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Неучт. Часы</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Учит?</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Описание</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Создано</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            <tr v-for="item in timesheetItems" :key="item.id" class="hover:bg-gray-50">
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-900">{{ item.id }}</td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{{ item.date ? new Date(item.date).toLocaleDateString() : '-' }}</td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{{ item.employee_id }}</td>
                                <td class="px-3 py-2 text-sm text-gray-500">{{ item.project_title || '-' }}</td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{{ item.task_id }}</td>
                                <td class="px-3 py-2 text-sm text-gray-500 max-w-xs truncate" :title="item.task_hierarchy_titles ? item.task_hierarchy_titles.join(' > ') : ''">
                                    {{ item.task_hierarchy_titles ? item.task_hierarchy_titles.join(' > ') : '-' }}
                                </td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-900 font-medium">{{ item.hours }}</td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{{ item.non_billable_hours }}</td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                                    <span :class="item.is_billable ? 'text-green-600' : 'text-gray-400'">
                                        {{ item.is_billable ? 'Да' : 'Нет' }}
                                    </span>
                                </td>
                                <td class="px-3 py-2 text-sm text-gray-500 max-w-xs truncate" :title="item.description">{{ item.description || '-' }}</td>
                                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-500">{{ item.created_at ? new Date(item.created_at).toLocaleString() : '-' }}</td>
                            </tr>
                        </tbody>
                    </table>
                  </div>
                  
                  <!-- Pagination -->
                  <div class="mt-4 flex justify-between items-center" v-if="itemsPages > 1">
                      <button 
                        @click="changePage(itemsPage - 1)" 
                        :disabled="itemsPage <= 1"
                        class="px-3 py-1 border rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Prev
                      </button>
                      <span class="text-sm text-gray-600">Page {{ itemsPage }} of {{ itemsPages }}</span>
                      <button 
                        @click="changePage(itemsPage + 1)" 
                        :disabled="itemsPage >= itemsPages"
                        class="px-3 py-1 border rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Next
                      </button>
                  </div>
              </div>
          </div>
      </B24Card>
  </div>
</template>
