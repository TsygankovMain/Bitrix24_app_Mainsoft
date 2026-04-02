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

// Filter state
const filterCreatedFrom = ref('')
const filterCreatedTo = ref('')

async function fetchTimesheetList(page = 1) {
    try {
         const result = await apiStore.getTimesheetsList(
           page,
           itemsLimit,
           filterCreatedFrom.value || undefined,
           filterCreatedTo.value || undefined
         )
         timesheetItems.value = result.items
         itemsTotal.value = result.total
         itemsPage.value = result.page
         itemsPages.value = result.pages
    } catch (e) {
        processErrorGlobal(e)
    }
}

// Export State
const dateType = ref('reflection')
const dateFrom = ref('')
const dateTo = ref('')
const spFields = ref<any[]>([])
const selectedFields = ref<string[]>([])
const isExporting = ref(false)
const isLoadingFields = ref(false)

// Status bar: tracks all loading states with descriptive messages
const isAnyLoading = computed(() =>
  isLoading.value || isSyncing.value || isExporting.value || isLoadingFields.value
)

const statusMessage = computed(() => {
  if (isSyncing.value)      return 'Синхронизация с Битрикс24... Это может занять некоторое время'
  if (isExporting.value)    return 'Формируется Excel: получение данных и имён сотрудников из Битрикс24...'
  if (isLoadingFields.value) return 'Загрузка полей смарт-процесса...'
  if (isLoading.value)      return 'Загрузка данных...'
  return ''
})

const loadSpFields = async () => {
    isLoadingFields.value = true
    try {
        const configResp = await apiStore.getConfiguration()
        // getConfiguration() returns the config object directly (not wrapped in {config: ...})
        const config = configResp || {}
        if (config.sp_entity_type_id) {
            const fieldsResp = await apiStore.getSpFields(config.sp_entity_type_id)
            if (fieldsResp && fieldsResp.fields) {
                // fieldsResp.fields might be object or array, depending on Bitrix API.
                // It's usually an array from our backend: [{id, title, type}, ...]
                if (Array.isArray(fieldsResp.fields)) {
                    spFields.value = fieldsResp.fields
                } else if (typeof fieldsResp.fields === 'object') {
                    const flds: any = fieldsResp.fields
                    spFields.value = Object.keys(flds).map(k => ({
                        id: k,
                        title: flds[k].listLabel || flds[k].formLabel || flds[k].title || k
                    }))
                }
                
                // default: select all fields
                selectAllFields()
            }
        } else {
            console.warn('[RawData] Smart Process not configured — cannot load fields')
        }
    } catch (e) {
         console.warn("Could not load SP fields for export", e)
    } finally {
        isLoadingFields.value = false
    }
}

const toggleSelectAll = (select: boolean) => {
    if (select) {
        selectAllFields()
    } else {
        selectedFields.value = []
    }
}

const selectAllFields = () => {
    selectedFields.value = spFields.value.map(f => f.id)
}

const handleExport = async () => {
    if (!dateFrom.value || !dateTo.value) {
        alert("Пожалуйста, выберите начальную и конечную даты")
        return
    }
    if (selectedFields.value.length === 0) {
        alert("Выберите хотя бы одно поле для выгрузки")
        return
    }
    
    isExporting.value = true
    try {
        const blob = await apiStore.exportRawData(dateFrom.value, dateTo.value, dateType.value, selectedFields.value)
        
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `raw_data_export_${dateFrom.value}_${dateTo.value}.xlsx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
        
    } catch (e: any) {
        processErrorGlobal(e)
    } finally {
        isExporting.value = false
    }
}

async function applyFilter() {
    isLoading.value = true
    try {
        await fetchTimesheetList(1)
    } catch(e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}

async function resetFilter() {
    filterCreatedFrom.value = ''
    filterCreatedTo.value = ''
    isLoading.value = true
    try {
        await fetchTimesheetList(1)
    } catch(e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
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
    
    // Default dates (current month)
    const today = new Date()
    dateFrom.value = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0] || ''
    dateTo.value = today.toISOString().split('T')[0] || ''
    
    // Load fields for export options
    await loadSpFields()
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

      <!-- ===== GLOBAL STATUS BAR ===== -->
      <Transition name="status-slide">
        <div v-if="isAnyLoading" class="status-bar">
          <!-- animated progress fill -->
          <div class="status-bar-track">
            <div class="status-bar-fill" />
          </div>
          <!-- status message -->
          <div class="status-bar-message">
            <svg class="status-bar-spinner" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-linecap="round"
                stroke-dasharray="31.4 31.4" />
            </svg>
            <span>{{ statusMessage }}</span>
          </div>
        </div>
      </Transition>

      <div class="mb-4">
          <B24Button label="Назад в настройки" color="link" @click="$router.push('/settings')" />
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

          <!-- Filter by creation date -->
          <div class="flex flex-wrap gap-3 items-end mb-4 p-3 bg-gray-50 rounded-lg border">
              <div class="flex flex-col gap-1">
                  <label class="text-xs font-medium text-gray-500">Дата создания — с</label>
                  <UiDatePickerInput v-model="filterCreatedFrom" placeholder="Выберите дату" />
              </div>
              <div class="flex flex-col gap-1">
                  <label class="text-xs font-medium text-gray-500">Дата создания — по</label>
                  <UiDatePickerInput v-model="filterCreatedTo" placeholder="Выберите дату" />
              </div>
              <div class="flex gap-2 items-end">
                  <B24Button label="Применить" @click="applyFilter" color="primary" size="sm" />
                  <B24Button label="Сбросить" @click="resetFilter" color="link" size="sm" />
              </div>
          </div>

          <!-- Inline loader for table refresh -->
          <div v-if="isLoading" class="table-loading-overlay">
            <div class="table-loading-spinner" />
            <span class="table-loading-text">Загружаем данные из базы...</span>
          </div>
          <div v-else>
              <!-- Блок Экспорта -->
              <div class="mb-8 bg-blue-50/30 border border-blue-100 rounded-lg p-6">
                  <h3 class="text-md font-semibold text-gray-700 mb-4 flex items-center gap-2">
                     <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                         <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                     </svg>
                     Настройки динамической выгрузки (Excel)
                  </h3>
                  
                  <!-- Dates -->
                  <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                      <div>
                          <label class="block text-sm text-gray-600 mb-1">Тип даты</label>
                          <select v-model="dateType" class="w-full border-gray-300 border rounded-md shadow-sm py-2 px-3 focus:outline-none focus:border-blue-300 bg-white">
                              <option value="reflection">По дате отражения (data)</option>
                              <option value="creation">По дате создания (createdTime)</option>
                          </select>
                      </div>
                       <div>
                           <label class="block text-sm text-gray-600 mb-1">Период: с</label>
                           <UiDatePickerInput v-model="dateFrom" placeholder="Начало периода" />
                       </div>
                       <div>
                           <label class="block text-sm text-gray-600 mb-1">по</label>
                           <UiDatePickerInput v-model="dateTo" placeholder="Конец периода" />
                       </div>
                  </div>

                  <!-- Fields -->
                  <div class="mb-4">
                      <div class="flex justify-between items-center mb-2">
                          <span class="text-sm font-medium text-gray-700">Поля для экспорта в Excel:</span>
                          <span class="text-xs text-gray-500">Выбрано: {{ selectedFields.length }} из {{ spFields.length }}</span>
                      </div>
                      <div class="mb-3 space-x-4">
                          <button @click="toggleSelectAll(true)" class="text-sm text-blue-600 hover:text-blue-800 font-medium cursor-pointer">Выбрать все</button>
                          <button @click="toggleSelectAll(false)" class="text-sm text-gray-500 hover:text-gray-700 font-medium cursor-pointer">Снять все</button>
                      </div>
                      
                      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-y-3 gap-x-6 bg-white p-4 border border-gray-200 rounded-lg max-h-64 overflow-y-auto shadow-inner">
                          <label v-for="f in spFields" :key="f.id" class="flex items-start gap-2 cursor-pointer group">
                              <!-- custom styling matching mockup -->
                              <input type="checkbox" :value="f.id" v-model="selectedFields" class="mt-1 appearance-none w-4 h-4 border border-gray-300 rounded bg-white checked:bg-blue-600 checked:border-blue-600 focus:ring-1 focus:ring-blue-500 transition-colors bg-center bg-no-repeat 
                              checked:bg-[url('data:image/svg+xml;utf8,%3Csvg%20viewBox=%220%200%2016%2016%22%20fill=%22white%22%20xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cpath%20d=%22M12.207%204.793a1%201%200%20010%201.414l-5%205a1%201%200%2001-1.414%200l-2-2a1%201%200%20011.414-1.414L6.5%209.086l4.293-4.293a1%201%200%20011.414%200z%22/%3E%3C/svg%3E')]">
                              <div class="flex flex-col overflow-hidden">
                                  <span class="text-sm font-medium text-gray-800 group-hover:text-blue-600 transition-colors truncate" :title="f.title">{{ f.title }}</span>
                                  <span class="text-xs text-gray-400 truncate" :title="f.id">{{ f.id }}</span>
                              </div>
                          </label>
                      </div>
                  </div>
                  
                  <div class="flex justify-between items-center mt-6 pt-4 border-t border-blue-200">
                       <span class="text-sm text-gray-500 italic">Скачивание происходит напрямую из Bitrix24 (в обход локальной БД)</span>
                       <B24Button label="Скачать Excel" @click="handleExport" :loading="isExporting" color="primary" />
                  </div>
              </div>

              <!-- Превью закешированных записей -->
              <h3 class="text-lg font-bold text-gray-800 mb-2 mt-8">Превью закешированных записей (БД)</h3>
              <div class="mb-2 text-sm text-gray-500">Всего записей локально: {{ itemsTotal }}</div>
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

<style scoped>
/* ===== STATUS BAR ===== */
.status-bar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.status-bar-track {
  height: 3px;
  background: #e5e7eb;
  overflow: hidden;
}

.status-bar-fill {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, #3b82f6, #6366f1, #3b82f6);
  background-size: 200% 100%;
  animation: status-slide-progress 1.5s ease-in-out infinite;
  border-radius: 0 2px 2px 0;
}

@keyframes status-slide-progress {
  0%   { transform: translateX(-100%); background-position: 0% 0; }
  50%  { background-position: 100% 0; }
  100% { transform: translateX(350%); background-position: 0% 0; }
}

.status-bar-message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  font-size: 13px;
  color: #4b5563;
  font-weight: 500;
}

.status-bar-spinner {
  width: 16px;
  height: 16px;
  color: #3b82f6;
  animation: spin 1s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* Transition: slide down on appear, slide up on leave */
.status-slide-enter-active,
.status-slide-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.status-slide-enter-from,
.status-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ===== INLINE TABLE LOADER ===== */
.table-loading-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px;
  color: #6b7280;
  font-size: 14px;
}

.table-loading-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

.table-loading-text {
  font-weight: 500;
}
</style>
