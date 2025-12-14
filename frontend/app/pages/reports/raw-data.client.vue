<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Сырые данные (БД)'
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('RawDataPage')
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
const isInit = ref(false)
const isSyncing = ref(false)
const timesheetItems = ref<any[]>([])
const itemsPage = ref(1)
const itemsTotal = ref(0)
const itemsPages = ref(0)
const itemsLimit = 50

async function fetchTimesheetList(page = 1) {
    try {
         const result = await apiStore.getTimesheetsList(page, itemsLimit)
         timesheetItems.value = result.items
         itemsTotal.value = result.total
         itemsPage.value = result.page
         itemsPages.value = result.pages
    } catch (e) {
        processErrorGlobal(e)
    }
}

async function handleSync() {
    isSyncing.value = true
    try {
        const result = await apiStore.syncTimesheets()
        alert(`Синхронизировано ${result.count} записей!`)
        await fetchTimesheetList()
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

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Сырые данные (БД)') 
    isInit.value = true
    
    // Initial fetch
    await fetchTimesheetList()
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
                <ProseH2>Сырые данные (БД)</ProseH2>
                <div class="flex gap-2 items-center">
                    <B24Button label="Синхронизировать с Б24" @click="handleSync" :loading="isSyncing" color="success" class="mr-2" />
                    <B24Button label="Обновить" @click="() => fetchTimesheetList(itemsPage)" loading-auto />
                </div>
            </div>
          </template>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-gray-500">Загрузка...</span>
          </div>
          <div v-else>
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
      </B24Card>
  </div>
</template>
