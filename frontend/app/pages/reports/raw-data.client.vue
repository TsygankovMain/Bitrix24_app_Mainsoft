<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import InnBackfillPanel from '../../components/reports/InnBackfillPanel.vue'
import { useProgress } from '~/composables/useProgress'

const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Проверка данных'
})

// region Init ////
const { initApp, processErrorGlobal } = useAppInit('RawDataPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const progress = useProgress()
const toast = useToast()
// endregion ////

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

interface TimesheetItem {
  id: number | string
  date?: string | null
  employee_id?: number | string | null
  project_title?: string | null
  task_id?: number | string | null
  task_hierarchy_titles?: string[] | null
  hours?: number | string | null
  non_billable_hours?: number | string | null
  is_billable?: boolean | null
  description?: string | null
  created_at?: string | null
}

interface SpField {
  id: string
  title: string
}

// Report State
const activeTab = ref<'export' | 'inn'>('export')
const isInit = ref(false)
const isSyncing = ref(false)
const timesheetItems = ref<TimesheetItem[]>([])
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
const spFields = ref<SpField[]>([])
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
        console.log('[RawData] loadSpFields: calling getConfiguration()')
        const configResp = await apiStore.getConfiguration()
        console.log('[RawData] loadSpFields: configResp =', configResp)
        // getConfiguration() returns the config object directly (not wrapped in {config: ...})
        const config = configResp || {}
        console.log('[RawData] loadSpFields: sp_entity_type_id =', config.sp_entity_type_id)
        if (config.sp_entity_type_id) {
            console.log('[RawData] loadSpFields: calling getSpFields(', config.sp_entity_type_id, ')')
            const fieldsResp = await apiStore.getSpFields(config.sp_entity_type_id)
            console.log('[RawData] loadSpFields: fieldsResp =', fieldsResp)
            if (fieldsResp && fieldsResp.fields) {
                console.log('[RawData] loadSpFields: fields count =', fieldsResp.fields.length ?? Object.keys(fieldsResp.fields).length)
                // fieldsResp.fields might be object or array, depending on Bitrix API.
                // It's usually an array from our backend: [{id, title, type}, ...]
                if (Array.isArray(fieldsResp.fields)) {
                    spFields.value = fieldsResp.fields
                } else if (typeof fieldsResp.fields === 'object') {
                    const flds: Record<string, { listLabel?: string, formLabel?: string, title?: string }> = fieldsResp.fields
                    spFields.value = Object.keys(flds).map(k => ({
                        id: k,
                        title: flds[k].listLabel || flds[k].formLabel || flds[k].title || k
                    }))
                }

                // default: select all fields
                console.log('[RawData] loadSpFields: spFields loaded =', spFields.value.length)
                selectAllFields()
            } else {
                console.warn('[RawData] loadSpFields: fieldsResp.fields is missing or empty!', fieldsResp)
            }
        } else {
            console.warn('[RawData] Smart Process not configured — cannot load fields. sp_entity_type_id =', config.sp_entity_type_id)
        }
    } catch (e) {
         console.error('[RawData] loadSpFields ERROR:', e)
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
        toast.add({ title: 'Пожалуйста, выберите начальную и конечную даты', color: 'air-primary-alert' })
        return
    }
    if (selectedFields.value.length === 0) {
        toast.add({ title: 'Выберите хотя бы одно поле для выгрузки', color: 'air-primary-alert' })
        return
    }

    isExporting.value = true
    progress.begin('Excel: «Сырые данные»', 0, 'Готовим файл выгрузки')
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

    } catch (e: unknown) {
        processErrorGlobal(e)
    } finally {
        isExporting.value = false
        progress.end()
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
    progress.begin('Синхронизация с Bitrix24', 0, 'Обновляем списания времени')
    isSyncing.value = true
    try {
        const result = await apiStore.syncTimesheets()
        toast.add({ title: `Синхронизировано ${result.count} записей!`, color: 'air-primary-success' })
        await fetchTimesheetList()
    } catch (e) {
         processErrorGlobal(e)
    } finally {
        isSyncing.value = false
        progress.end()
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
    await $b24.parent.setTitle('Проверка данных')
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
  <B24Container>

    <!-- ===== GLOBAL STATUS BAR ===== -->
    <Transition name="status-slide">
      <div v-if="isAnyLoading" class="status-bar mb-4">
        <!-- animated progress fill -->
        <div class="status-bar-track">
          <div class="status-bar-fill" />
        </div>
        <!-- status message -->
        <div class="status-bar-message">
          <svg class="status-bar-spinner" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle
cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-linecap="round"
              stroke-dasharray="31.4 31.4" />
          </svg>
          <span>{{ statusMessage }}</span>
        </div>
      </div>
    </Transition>

    <!-- ms-page-header: заголовок страницы + кнопки действий -->
    <B24PageHeader
      title="Проверка данных"
      description="Локальная база, ручная синхронизация и Excel-выгрузка по выбранным полям."
    >
      <template #links>
        <template v-if="activeTab === 'export'">
          <B24Button label="Синхронизировать с Б24" :loading="isSyncing" color="success" @click="handleSync" />
          <B24Button label="Обновить" loading-auto @click="() => fetchTimesheetList(itemsPage)" />
        </template>
        <B24Button label="Назад в настройки" color="link" @click="$router.push('/settings')" />
      </template>
    </B24PageHeader>

    <!-- ms-surface: основная карточка-контейнер контента -->
    <B24Card v-if="isInit" class="mt-6">

      <!-- Вкладки: сохраняем activeTab-ref механизм, убираем lime -->
      <div class="mb-4 flex gap-1 border-b border-slate-200">
        <button
          class="px-4 py-2 text-sm font-medium transition"
          :class="activeTab === 'export'
            ? 'border-b-2 border-[#0075ff] text-[#0075ff]'
            : 'text-slate-500 hover:text-slate-700'"
          @click="activeTab = 'export'"
        >Выгрузка</button>
        <button
          class="px-4 py-2 text-sm font-medium transition"
          :class="activeTab === 'inn'
            ? 'border-b-2 border-[#0075ff] text-[#0075ff]'
            : 'text-slate-500 hover:text-slate-700'"
          @click="activeTab = 'inn'"
        >Дозаполнение ИНН</button>
      </div>

      <!-- Вкладка: Выгрузка -->
      <div v-show="activeTab === 'export'">

        <!-- ms-filter-wrap: фильтр по дате создания -->
        <B24Card class="mb-4">
          <div class="flex flex-wrap items-end gap-3">
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-slate-500">Дата создания — с</label>
              <UiDatePickerInput v-model="filterCreatedFrom" placeholder="Выберите дату" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-slate-500">Дата создания — по</label>
              <UiDatePickerInput v-model="filterCreatedTo" placeholder="Выберите дату" />
            </div>
            <div class="flex gap-2 items-end">
              <B24Button label="Применить" color="primary" size="sm" @click="applyFilter" />
              <B24Button label="Сбросить" color="link" size="sm" @click="resetFilter" />
            </div>
          </div>
        </B24Card>

        <!-- Inline loader for table refresh -->
        <div v-if="isLoading" class="table-loading-overlay">
          <div class="table-loading-spinner" />
          <span class="table-loading-text">Загружаем данные из базы...</span>
        </div>
        <div v-else>

          <!-- ms-panel: настройки динамической выгрузки -->
          <B24Card class="mb-8">
            <template #header>
              <div class="flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                </svg>
                <span class="text-md font-semibold text-slate-900">Настройки динамической выгрузки (Excel)</span>
              </div>
            </template>

            <!-- Dates -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
              <div>
                <label class="mb-1 block text-sm text-slate-600">Тип даты</label>
                <select v-model="dateType" class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-[#0075ff]">
                  <option value="reflection">По дате отражения (data)</option>
                  <option value="creation">По дате создания (createdTime)</option>
                </select>
              </div>
              <div>
                <label class="mb-1 block text-sm text-slate-600">Период: с</label>
                <UiDatePickerInput v-model="dateFrom" placeholder="Начало периода" />
              </div>
              <div>
                <label class="mb-1 block text-sm text-slate-600">по</label>
                <UiDatePickerInput v-model="dateTo" placeholder="Конец периода" />
              </div>
            </div>

            <!-- Fields -->
            <div class="mb-4">
              <div class="flex justify-between items-center mb-2">
                <span class="text-sm font-medium text-slate-700">Поля для экспорта в Excel:</span>
                <span class="text-xs text-slate-500">Выбрано: {{ selectedFields.length }} из {{ spFields.length }}</span>
              </div>
              <div class="mb-3 space-x-4">
                <button class="cursor-pointer text-sm font-medium text-[#0075ff] hover:text-blue-700" @click="toggleSelectAll(true)">Выбрать все</button>
                <button class="cursor-pointer text-sm font-medium text-slate-500 hover:text-slate-700" @click="toggleSelectAll(false)">Снять все</button>
              </div>

              <div class="grid max-h-64 grid-cols-1 gap-x-6 gap-y-3 overflow-y-auto rounded-2xl border border-slate-200 bg-slate-50 p-4 shadow-inner sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
                <label v-for="f in spFields" :key="f.id" class="flex items-start gap-2 cursor-pointer group">
                  <input
                    v-model="selectedFields"
                    type="checkbox"
                    :value="f.id"
                    class="mt-1 h-4 w-4 appearance-none rounded border border-slate-300 bg-white bg-center bg-no-repeat transition-colors checked:border-[#0075ff] checked:bg-[#0075ff] focus:ring-1 focus:ring-[#0075ff] checked:bg-[url('data:image/svg+xml;utf8,%3Csvg%20viewBox=%220%200%2016%2016%22%20fill=%22white%22%20xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cpath%20d=%22M12.207%204.793a1%201%200%20010%201.414l-5%205a1%201%200%2001-1.414%200l-2-2a1%201%200%20011.414-1.414L6.5%209.086l4.293-4.293a1%201%200%20011.414%200z%22/%3E%3C/svg%3E')]"
                  >
                  <div class="flex flex-col overflow-hidden">
                    <span class="truncate text-sm font-medium text-slate-800 transition-colors group-hover:text-[#0075ff]" :title="f.title">{{ f.title }}</span>
                    <span class="truncate text-xs text-slate-400" :title="f.id">{{ f.id }}</span>
                  </div>
                </label>
              </div>
            </div>

            <template #footer>
              <div class="flex items-center justify-between w-full">
                <span class="text-sm italic text-slate-500">Скачивание происходит напрямую из Bitrix24 (в обход локальной БД)</span>
                <B24Button label="Скачать Excel" :loading="isExporting" color="primary" @click="handleExport" />
              </div>
            </template>
          </B24Card>

          <!-- Превью закешированных записей -->
          <h3 class="mb-2 mt-8 text-lg font-bold text-slate-800">Превью закешированных записей (БД)</h3>
          <div class="mb-2 text-sm text-slate-500">Всего записей локально: {{ itemsTotal }}</div>
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
      </div><!-- /tab: Выгрузка -->

      <!-- Вкладка: Дозаполнение ИНН — не трогаем -->
      <div v-if="activeTab === 'inn'">
        <InnBackfillPanel />
      </div>

    </B24Card>
  </B24Container>
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
