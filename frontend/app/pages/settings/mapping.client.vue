<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'

const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()
const apiStore = useApiStore()

useHead({
  title: 'Настройка полей (Маппинг)'
})

// region Init
const { $logger, initApp, processErrorGlobal } = useAppInit('MappingPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null
// endregion

const isLoading = ref(false)
const isSaving = ref(false)
const isInit = ref(false)
const isCreatingSP = ref(false)
const isCreatingFields = ref(false)
const statusMessage = ref<{ type: 'success' | 'error'; text: string } | null>(null)

// Data
const smartProcesses = ref<any[]>([])
const selectedSpId = ref<number | null>(null)
const spFields = ref<any[]>([]) // Fields of the selected SP
const config = ref<any>({})

// App Fields Definition
const APP_FIELDS = [
  { key: 'id_zadachi', label: 'ID Задачи', type: 'integer', desc: 'ID задачи, к которой относится запись' },
  { key: 'sotrudnik', label: 'Сотрудник', type: 'employee', desc: 'Пользователь, списавший время' },
  { key: 'kolichestvo_chasov', label: 'Количество часов', type: 'double', desc: 'Числовое значение часов' },
  { key: 'uchitivaem', label: 'Учитываем?', type: 'boolean', desc: 'Флаг (Да/Нет), оплачиваемое ли время' },
  { key: 'ne_uchitivaemie_chasi', label: 'Неучитываемые часы', type: 'double', desc: 'Часы, которые не идут в оплату' },
  { key: 'opisanie', label: 'Описание', type: 'string', desc: 'Комментарий к списанию' },
  { key: 'project_title', label: 'Название Проекта', type: 'string', desc: 'Название проекта (из задачи или группы)' },
  { key: 'project_id', label: 'ID Проекта', type: 'integer', desc: 'ID проекта (группы)' },
  { key: 'data', label: 'Дата', type: 'date', desc: 'Дата, за которую списано время' },
  { key: 'id_zadach_ierarhiya', label: 'Иерархия ID', type: 'string (JSON)', desc: 'JSON массив ID родительских задач' },
  { key: 'title_zadach_ierarhiya', label: 'Иерархия Названий', type: 'string (JSON)', desc: 'JSON массив названий родительских задач' },
  { key: 'task_name', label: 'Название задачи', type: 'string', desc: 'Название текущей задачи' },
  { key: 'our_inn', label: 'Наш ИНН', type: 'string', desc: 'ИНН вашей компании (из задачи)' },
  { key: 'client_inn', label: 'ИНН клиента', type: 'string', desc: 'ИНН клиента (из задачи)' },
]

// Mapping State: AppFieldKey -> BitrixFieldID
const mapping = ref<Record<string, string>>({})

async function loadData() {
    isLoading.value = true
    try {
        // 1. Get Config
        const cfg = await apiStore.getConfiguration()
        config.value = cfg
        
        // 2. Get SP List
        const spRes = await apiStore.getSmartProcesses()
        smartProcesses.value = spRes.types || []
        
        // 3. Set Initial State
        if (cfg.sp_entity_type_id) {
            selectedSpId.value = cfg.sp_entity_type_id
            mapping.value = { ...cfg.fields_mapping }
            await loadSpFields(cfg.sp_entity_type_id)
        }
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
        isInit.value = true
    }
}

async function loadSpFields(entityTypeId: number) {
    isLoading.value = true
    try {
        const res = await apiStore.getSpFields(entityTypeId)
        spFields.value = res.fields || []
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}

// Watch removed to require manual "Load" click as requested
// watch(selectedSpId, async (newVal, oldVal) => { ... })

async function handleSave() {
    isSaving.value = true
    try {
        const newConfig = {
            ...config.value,
            sp_entity_type_id: selectedSpId.value,
            fields_mapping: mapping.value,
            is_configured: true
        }
        await apiStore.saveConfiguration(newConfig)
        // alert('Настройки успешно сохранены') // Optional: might be annoying if we redirect immediately.
        // Let's keep a small delay or just redirect. User asked for "exit to settings".
        router.push('/settings')
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isSaving.value = false
    }
}

function getFieldOptions(appFieldType: string) {
    return spFields.value.map(f => ({
        label: `${f.title} (${f.type})`,
        value: f.id
    }))
}

function showStatus(type: 'success' | 'error', text: string) {
    statusMessage.value = { type, text }
    setTimeout(() => { statusMessage.value = null }, 5000)
}

async function handleCreateSmartProcess() {
    isCreatingSP.value = true
    statusMessage.value = null
    try {
        const result = await apiStore.createSmartProcess()
        const newConfig = result.config
        config.value = newConfig
        selectedSpId.value = newConfig.sp_entity_type_id
        // Reload SP list
        const spRes = await apiStore.getSmartProcesses()
        smartProcesses.value = spRes.types || []
        showStatus('success', `Смарт-процесс создан (ID: ${newConfig.sp_entity_type_id})`)
    } catch (e: any) {
        const errMsg = e?.data?.error || e?.message || 'Неизвестная ошибка'
        showStatus('error', `Ошибка: ${errMsg}`)
    } finally {
        isCreatingSP.value = false
    }
}

async function handleCreateFields() {
    if (!selectedSpId.value) return
    isCreatingFields.value = true
    statusMessage.value = null
    try {
        const result = await apiStore.createFields(selectedSpId.value)
        const newConfig = result.config
        config.value = newConfig
        mapping.value = { ...newConfig.fields_mapping }
        // Reload fields list
        await loadSpFields(selectedSpId.value!)
        showStatus('success', `Создано ${Object.keys(newConfig.fields_mapping).length} полей. Маппинг заполнен автоматически.`)
    } catch (e: any) {
        const errMsg = e?.data?.error || e?.message || 'Неизвестная ошибка'
        showStatus('error', `Ошибка: ${errMsg}`)
    } finally {
        isCreatingFields.value = false
    }
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await loadData()
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <div class="flex flex-col gap-4 p-4 min-h-screen bg-gray-50 dark:bg-gray-900">
      <!-- Headers -->
      <div class="flex items-center justify-between mb-4">
          <h1 class="text-2xl font-bold text-gray-900 dark:text-gray-100">Настройка полей (Маппинг)</h1>
          <div class="flex gap-2">
            <B24Button label="Назад" color="link" @click="router.push('/settings')" />
            <B24Button label="Сохранить" color="success" @click="handleSave" :loading="isSaving" />
          </div>
      </div>

      <div v-if="isLoading && !isInit" class="text-center py-10">
          Загрузка...
      </div>

      <div v-else class="flex flex-col gap-6">
          <!-- SP Selector -->
          <B24Card title="Выбор Смарт-Процесса">
              <!-- Status Message -->
              <div v-if="statusMessage" class="mb-4 p-3 rounded-md text-sm font-medium" :class="statusMessage.type === 'success' ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'">
                  {{ statusMessage.text }}
              </div>

              <div class="w-full">
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Смарт-процесс</label>
                  <select 
                    v-model="selectedSpId" 
                    class="block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                  >
                      <option :value="null">-- Не выбрано --</option>
                      <option v-for="sp in smartProcesses" :key="sp.id" :value="sp.entityTypeId">
                          {{ sp.title }} (ID: {{ sp.entityTypeId }})
                      </option>
                  </select>
                  <div class="flex flex-col gap-2 mt-3">
                        <div class="flex flex-wrap gap-2">
                            <B24Button 
                                label="Подгрузить поля" 
                                color="primary" 
                                size="sm"
                                @click="() => { if (selectedSpId) loadSpFields(selectedSpId) }" 
                                :disabled="!selectedSpId || isLoading"
                            />
                            <B24Button 
                                label="Создать смарт-процесс" 
                                color="warning" 
                                size="sm"
                                @click="handleCreateSmartProcess" 
                                :loading="isCreatingSP"
                                :disabled="(!!selectedSpId && selectedSpId !== 0) || isCreatingSP"
                            />
                            <B24Button 
                                label="Создать все поля" 
                                color="danger" 
                                size="sm"
                                @click="handleCreateFields" 
                                :loading="isCreatingFields"
                                :disabled="!selectedSpId || isCreatingFields"
                            />
                        </div>
                        <p class="text-sm text-gray-500">
                            Выберите процесс и нажмите "Подгрузить", чтобы получить список полей.
                            Или создайте новый процесс и поля кнопками выше.
                        </p>
                  </div>
              </div>
          </B24Card>

          <!-- Field List (Read-Only) -->
          <B24Card title="Доступные поля сущности" v-if="selectedSpId">
             <div v-if="spFields.length > 0" class="overflow-x-auto max-h-60 overflow-y-auto">
                 <table class="min-w-full divide-y divide-gray-200">
                     <thead class="bg-gray-50 sticky top-0">
                         <tr>
                             <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Название</th>
                             <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Код (ID)</th>
                             <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Тип</th>
                         </tr>
                     </thead>
                     <tbody class="bg-white divide-y divide-gray-200 text-sm">
                         <tr v-for="field in spFields" :key="field.id">
                             <td class="px-3 py-1 font-medium text-gray-900">{{ field.title }}</td>
                             <td class="px-3 py-1 text-gray-500 font-mono text-xs">{{ field.id }}</td>
                             <td class="px-3 py-1 text-gray-500">{{ field.type }}</td>
                         </tr>
                     </tbody>
                 </table>
             </div>
             <div v-else class="text-gray-500 text-sm italic p-4">
                 Поля еще не загружены. Нажмите "Подгрузить поля".
             </div>
          </B24Card>

          <!-- Mapping Table -->
          <B24Card title="Сопоставление полей" v-if="selectedSpId">
              <div class="overflow-x-auto">
                  <table class="min-w-full divide-y divide-gray-200">
                      <thead class="bg-gray-50">
                          <tr>
                              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/2">
                                  Поле приложения
                              </th>
                              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/2">
                                  Поле в Битрикс24
                              </th>
                          </tr>
                      </thead>
                      <tbody class="bg-white divide-y divide-gray-200">
                          <tr v-for="field in APP_FIELDS" :key="field.key">
                              <td class="px-6 py-4">
                                  <div class="text-sm font-medium text-gray-900">{{ field.label }}</div>
                                  <div class="text-xs text-gray-500">{{ field.desc }}</div>
                                  <div class="text-xs text-blue-500 mt-1">Тип: {{ field.type }}</div>
                              </td>
                              <td class="px-6 py-4">
                                  <select 
                                    v-model="mapping[field.key]"
                                    class="block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                                  >
                                      <option :value="undefined">-- Не сопоставлено --</option>
                                      <option v-for="opt in getFieldOptions(field.type)" :key="opt.value" :value="opt.value">
                                          {{ opt.label }}
                                      </option>
                                  </select>
                              </td>
                          </tr>
                      </tbody>
                  </table>
              </div>
          </B24Card>
      </div>
  </div>
</template>
