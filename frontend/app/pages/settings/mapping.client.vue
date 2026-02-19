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
    console.log('🔧 [CreateSP] Starting...')
    try {
        const result = await apiStore.createSmartProcess()
        console.log('✅ [CreateSP] Response:', JSON.stringify(result, null, 2))
        const newConfig = result.config
        config.value = newConfig
        selectedSpId.value = newConfig.sp_entity_type_id
        // Reload SP list
        const spRes = await apiStore.getSmartProcesses()
        smartProcesses.value = spRes.types || []
        showStatus('success', `Смарт-процесс создан (ID: ${newConfig.sp_entity_type_id})`)
    } catch (e: any) {
        console.error('❌ [CreateSP] Error:', e)
        console.error('❌ [CreateSP] e.data:', e?.data)
        console.error('❌ [CreateSP] e.message:', e?.message)
        console.error('❌ [CreateSP] e.statusCode:', e?.statusCode)
        console.error('❌ [CreateSP] e.statusMessage:', e?.statusMessage)
        console.error('❌ [CreateSP] e.response:', e?.response)
        const errMsg = e?.data?.error || e?.message || 'Неизвестная ошибка'
        showStatus('error', `Ошибка: ${errMsg}`)
    } finally {
        isCreatingSP.value = false
    }
}

async function handleCreateFields() {
    if (!selectedSpId.value) {
        console.warn('⚠️ [CreateFields] No SP selected!')
        return
    }
    if (!$b24) {
        showStatus('error', 'B24 SDK не инициализирован. Обновите страницу.')
        return
    }

    isCreatingFields.value = true
    statusMessage.value = null
    const entityTypeId = selectedSpId.value
    console.log('🔧 [CreateFields] Starting for entityTypeId:', entityTypeId)

    // IMPORTANT: userfieldconfig.add requires the SPA's ordinal `id`, NOT `entityTypeId`
    // e.g. if entityTypeId=1040, the actual id might be 87 (like in ufCrm87_xxx)
    // Find the real id from the smartProcesses list
    const spInfo = smartProcesses.value.find((sp: any) => sp.entityTypeId === entityTypeId)
    const spaOrdinalId = spInfo?.id
    console.log('🔧 [CreateFields] SPA ordinal id:', spaOrdinalId, 'entityTypeId:', entityTypeId)
    console.log('🔧 [CreateFields] Full SP info:', JSON.stringify(spInfo))

    if (!spaOrdinalId) {
        showStatus('error', `Не удалось определить внутренний ID для entityTypeId=${entityTypeId}. Перезагрузите страницу.`)
        isCreatingFields.value = false
        return
    }

    // Field suffix names (Bitrix will create as UF_CRM_{id}_{suffix})
    const FIELDS_TO_CREATE = [
        { key: 'id_zadachi', suffix: 'TASK_ID', label: 'ID Задачи', type: 'integer' },
        { key: 'sotrudnik', suffix: 'EMPLOYEE', label: 'Сотрудник', type: 'employee' },
        { key: 'kolichestvo_chasov', suffix: 'HOURS', label: 'Количество часов', type: 'double' },
        { key: 'uchitivaem', suffix: 'IS_BILLABLE', label: 'Учитываем?', type: 'boolean' },
        { key: 'ne_uchitivaemie_chasi', suffix: 'NON_BILLABLE', label: 'Неучитываемые часы', type: 'double' },
        { key: 'opisanie', suffix: 'DESCRIPTION', label: 'Описание', type: 'string' },
        { key: 'project_title', suffix: 'PROJECT', label: 'Проект', type: 'string' },
        { key: 'project_id', suffix: 'PROJECT_ID', label: 'ID Проекта', type: 'integer' },
        { key: 'data', suffix: 'DATE', label: 'Дата отражения', type: 'date' },
        { key: 'id_zadach_ierarhiya', suffix: 'HIER_IDS', label: 'Иерархия ID', type: 'string', multiple: true },
        { key: 'title_zadach_ierarhiya', suffix: 'HIER_TITLES', label: 'Иерархия Названий', type: 'string', multiple: true },
        { key: 'task_name', suffix: 'TASK_NAME', label: 'Название задачи', type: 'string' },
        { key: 'our_inn', suffix: 'OUR_INN', label: 'Наш ИНН', type: 'string' },
        { key: 'client_inn', suffix: 'CLIENT_INN', label: 'ИНН клиента', type: 'string' },
    ]

    // Convert UF_CRM_10_TASK_ID → ufCrm10TaskId (camelCase for REST API)
    function ufToCamelCase(ufName: string): string {
        // UF_CRM_10_TASK_ID → split by _ → ['UF', 'CRM', '10', 'TASK', 'ID']
        const parts = ufName.split('_')
        return parts.map((part, i) => {
            if (i === 0) return part.toLowerCase() // 'uf'
            // Capitalize first letter, rest lowercase
            return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
        }).join('')
        // Result: ufCrm10TaskId
    }

    const newMapping: Record<string, string> = {}
    const errors: string[] = []
    let created = 0

    for (const field of FIELDS_TO_CREATE) {
        showStatus('success', `Создание поля ${created + 1}/${FIELDS_TO_CREATE.length}: ${field.label}...`)

        // Build full fieldName: UF_CRM_{spaId}_{suffix}
        const fullFieldName = `UF_CRM_${spaOrdinalId}_${field.suffix}`

        try {
            console.log(`📝 [CreateFields] Creating: ${field.key} -> fieldName=${fullFieldName}, type=${field.type}, entityId=CRM_${spaOrdinalId}, multiple=${!!field.multiple}`)

            // Build field params
            const fieldParams: Record<string, any> = {
                entityId: `CRM_${spaOrdinalId}`,
                fieldName: fullFieldName,
                userTypeId: field.type,
                editFormLabel: { ru: field.label, en: field.label },
                listColumnLabel: { ru: field.label, en: field.label },
                filterLabel: { ru: field.label, en: field.label },
            }
            if (field.multiple) {
                fieldParams.multiple = 'Y'
            }

            // @ts-ignore - callMethod typing
            const result = await $b24!.callMethod('userfieldconfig.add', {
                moduleId: 'crm',
                field: fieldParams,
            })

            // Extract created field name from response
            const data = result.getData()
            console.log(`✅ [CreateFields] ${field.key} raw response:`, JSON.stringify(data))

            // Try all possible response structures from b24jssdk
            const createdFieldName = data?.result?.field?.fieldName 
                || data?.field?.fieldName 
                || data?.fieldName
                || (typeof data === 'object' && data !== null ? Object.values(data)?.[0]?.fieldName : null)

            if (createdFieldName) {
                // Convert to camelCase for REST API: UF_CRM_10_TASK_ID → ufCrm10TaskId
                const camelName = ufToCamelCase(createdFieldName)
                newMapping[field.key] = camelName
                console.log(`✅ [CreateFields] ${field.key}: ${createdFieldName} → ${camelName}`)
            } else {
                // Fallback: convert our fullFieldName to camelCase
                const camelName = ufToCamelCase(fullFieldName)
                console.warn(`⚠️ [CreateFields] ${field.key}: fieldName not in response, using fallback: ${fullFieldName} → ${camelName}`)
                console.warn(`⚠️ [CreateFields] Full data keys:`, data ? Object.keys(data) : 'null')
                newMapping[field.key] = camelName
                errors.push(`${field.label}: создано, но нет fieldName в ответе`)
            }
            created++

        } catch (e: any) {
            const errMsg = e?.message || e?.toString() || 'Unknown error'
            console.error(`❌ [CreateFields] ${field.key} FAILED:`, e)
            console.error(`❌ [CreateFields] Error details:`, JSON.stringify(e, null, 2))

            // Check if field already exists
            if (errMsg.includes('already') || errMsg.includes('exist') || errMsg.includes('уже')) {
                console.log(`ℹ️ [CreateFields] ${field.key} already exists, skipping`)
                newMapping[field.key] = ufToCamelCase(fullFieldName)
                errors.push(`${field.label}: уже существует`)
                created++
            } else {
                errors.push(`${field.label}: ${errMsg}`)
                newMapping[field.key] = ufToCamelCase(fullFieldName) // fallback
            }
        }

        // Small delay between API calls to avoid rate limiting
        await new Promise(r => setTimeout(r, 300))
    }

    // Save mapping to config
    try {
        console.log('💾 [CreateFields] Saving mapping:', newMapping)
        const newConfig = {
            ...config.value,
            sp_entity_type_id: entityTypeId,
            fields_mapping: newMapping,
            is_configured: true,
        }
        await apiStore.saveConfiguration(newConfig)
        config.value = newConfig
        mapping.value = { ...newMapping }

        // Reload fields list
        await loadSpFields(entityTypeId)

        if (errors.length === 0) {
            showStatus('success', `✅ Создано ${created} из ${FIELDS_TO_CREATE.length} полей. Маппинг сохранён.`)
        } else {
            showStatus('error', `Создано ${created}/${FIELDS_TO_CREATE.length}. Предупреждения: ${errors.join('; ')}`)
        }
        console.log('✅ [CreateFields] Done! Mapping saved to config.')
    } catch (saveErr: any) {
        console.error('❌ [CreateFields] Failed to save config:', saveErr)
        showStatus('error', `Поля созданы, но не удалось сохранить маппинг: ${saveErr?.message}`)
    }

    isCreatingFields.value = false
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

              <div class="w-full space-y-4">
                  <div>
                      <label class="block text-sm font-semibold text-gray-800 dark:text-gray-200 mb-1">Смарт-процесс</label>
                      <select 
                        v-model="selectedSpId" 
                        class="block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                      >
                          <option :value="null">-- Не выбрано --</option>
                          <option v-for="sp in smartProcesses" :key="sp.id" :value="sp.entityTypeId">
                              {{ sp.title }} (ID: {{ sp.entityTypeId }})
                          </option>
                      </select>
                  </div>

                  <div class="rate-field">
                      <label for="hour-rate" class="rate-field__label">Стоимость часа (по умолчанию)</label>
                      <input 
                        id="hour-rate"
                        type="number" 
                        v-model.number="config.hourly_rate" 
                        class="rate-field__input" 
                        placeholder="Например: 1500"
                      />
                      <p class="mt-1 text-xs text-gray-500">Без ставки расчёт будет неточным. Применяется для новых записей.</p>
                  </div>

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
                                color="primary" 
                                size="sm"
                                @click="handleCreateSmartProcess" 
                                :loading="isCreatingSP"
                                :disabled="(!!selectedSpId && selectedSpId !== 0) || isCreatingSP"
                            />
                            <B24Button 
                                label="Создать все поля" 
                                color="primary" 
                                size="sm"
                                @click="handleCreateFields" 
                                :loading="isCreatingFields"
                                :disabled="!selectedSpId || isCreatingFields"
                            />
                        </div>
                        <p class="text-sm text-gray-700 dark:text-gray-300">
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

<style scoped>
.rate-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 320px;
  width: 100%;
}

.rate-field__label {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  color: #1f2937;
}
.dark .rate-field__label {
  color: #e5e7eb;
}

.rate-field__input {
  width: 100%;
  min-height: 48px;
  padding: 10px 12px;
  border: 1px solid #c7ced8;
  border-radius: 10px;
  background: #fff;
  font-size: 16px;
  line-height: 1.2;
}

.rate-field__input:focus {
  outline: none;
  border-color: #2f6fed;
  box-shadow: 0 0 0 3px rgba(47, 111, 237, 0.18);
}

@media (max-width: 768px) {
  .rate-field {
    max-width: 100%;
  }

  .rate-field__input {
    min-height: 44px;
    font-size: 16px;
  }
}
</style>
