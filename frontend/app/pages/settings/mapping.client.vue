<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref } from 'vue'
import type {
  AppConfigurationPayload,
  MappingFieldDefinition,
  ProjectSpaValidationPayload,
  SmartProcessFieldOption,
  SmartProcessOption,
} from '~/types/config'

const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()
const apiStore = useApiStore()

useHead({
  title: 'Настройка полей'
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
const creatingMappedField = ref<string | null>(null)
const statusMessage = ref<{ type: 'success' | 'error'; text: string } | null>(null)

// Data
const smartProcesses = ref<SmartProcessOption[]>([])
const selectedSpId = ref<number | null>(null)
const spFields = ref<SmartProcessFieldOption[]>([]) // Fields of the selected SP
const config = ref<AppConfigurationPayload>({})

// App Fields Definition
const APP_FIELDS: MappingFieldDefinition[] = [
  { key: 'id_zadachi', label: 'ID Задачи', type: 'integer', desc: 'ID задачи, к которой относится запись' },
  { key: 'sotrudnik', label: 'Сотрудник', type: 'employee', desc: 'Пользователь, списавший время' },
  { key: 'kolichestvo_chasov', label: 'Количество часов', type: 'double', desc: 'Числовое значение часов' },
  { key: 'uchitivaem', label: 'Учитываем?', type: 'boolean', desc: 'Флаг (Да/Нет), оплачиваемое ли время' },
  { key: 'ne_uchitivaemie_chasi', label: 'Неучитываемые часы', type: 'double', desc: 'Часы, которые не идут в оплату' },
  { key: 'opisanie', label: 'Описание', type: 'string', desc: 'Комментарий к списанию' },
  { key: 'project_title', label: 'Название Проекта', type: 'string', desc: 'Название проекта (из задачи или группы)' },
  {
    key: 'project_id',
    label: 'ID Проекта',
    type: 'integer | string',
    desc: 'ID проекта (группы). Можно привязать как числовое, так и строковое поле.',
    acceptedTypes: ['integer', 'string'],
  },
  { key: 'project_item_id', label: 'ID элемента проекта SPA', type: 'integer', desc: 'ID карточки проекта в Smart Process ПРОЕКТ' },
  { key: 'data', label: 'Дата', type: 'date', desc: 'Дата, за которую списано время' },
  { key: 'id_zadach_ierarhiya', label: 'Иерархия ID', type: 'string (JSON)', desc: 'JSON массив ID родительских задач' },
  { key: 'title_zadach_ierarhiya', label: 'Иерархия Названий', type: 'string (JSON)', desc: 'JSON массив названий родительских задач' },
  { key: 'task_name', label: 'Название задачи', type: 'string', desc: 'Название текущей задачи' },
  { key: 'our_inn', label: 'Наш ИНН', type: 'string', desc: 'ИНН вашей компании (из задачи)' },
  { key: 'client_inn', label: 'ИНН клиента', type: 'string', desc: 'ИНН клиента (из задачи)' },
]

const APP_CREATABLE_FIELD_KEYS = new Set(APP_FIELDS.map(field => field.key))

const PROJECT_STAGE_FIELD_KEY = 'stage'
const LEGACY_PROJECT_STAGE_KEYS = ['manual_stage', 'effective_stage'] as const

const PROJECT_FIELDS: MappingFieldDefinition[] = [
  { key: 'title', label: 'Название проекта', type: 'string', desc: 'Название карточки проекта в SPA ПРОЕКТ' },
  {
    key: 'bitrix_group_id',
    label: 'ID группы Bitrix',
    type: 'integer | string',
    desc: 'Связь проекта с Bitrix group/project. Допускается числовое или строковое поле.',
    acceptedTypes: ['integer', 'string'],
  },
  {
    key: PROJECT_STAGE_FIELD_KEY,
    label: 'Стадия проекта',
    type: 'stage',
    desc: 'Единое типовое поле стадии проекта из Smart Process.',
    acceptedTypes: ['crm_status', 'status', 'stage'],
  },
  { key: 'is_support', label: 'Флаг поддержки', type: 'boolean', desc: 'Проект в режиме поддержки' },
  { key: 'project_hours_budget', label: 'Бюджет часов', type: 'double', desc: 'Плановый объем часов проекта' },
  { key: 'hourly_rate', label: 'Ставка часа', type: 'double', desc: 'Коммерческая ставка проекта' },
  { key: 'curator_id', label: 'Куратор', type: 'employee', desc: 'Ответственный пользователь Bitrix24' },
  { key: 'company_id', label: 'Компания', type: 'crm_company', desc: 'Клиентская компания проекта' },
  { key: 'our_legal_entity_id', label: 'Наше юрлицо', type: 'crm_company', desc: 'Наша компания, от которой ведется проект' },
  { key: 'start_date', label: 'Дата старта', type: 'date', desc: 'План/факт старта проекта' },
  { key: 'finish_date', label: 'Дата окончания', type: 'date', desc: 'План/факт завершения проекта' },
  { key: 'is_archived', label: 'Архив', type: 'boolean', desc: 'Флаг архивности проекта' },
]

const PROJECT_CREATABLE_FIELD_KEYS = new Set(PROJECT_FIELDS.filter(field => field.key !== 'title' && field.key !== PROJECT_STAGE_FIELD_KEY).map(field => field.key))
const CREATE_OPTION_PREFIX = '__create__:'

// Mapping State: AppFieldKey -> BitrixFieldID
const mapping = ref<Record<string, string>>({})
const projectMapping = ref<Record<string, string>>({})
const selectedProjectSpId = ref<number | null>(null)
const projectSpFields = ref<SmartProcessFieldOption[]>([])
const projectSpaValidation = ref<ProjectSpaValidationPayload | null>(null)
const isValidatingProjectSpa = ref(false)

function normalizeMappingState(source?: Record<string, string> | null) {
  return Object.entries(source || {}).reduce<Record<string, string>>((acc, [key, value]) => {
    if (!value) {
      return acc
    }

    acc[key] = String(value)
    return acc
  }, {})
}

function getLegacyStageValue(configSource: AppConfigurationPayload) {
  const projectFields = configSource.project_fields_mapping || {}
  const candidates = [
    projectFields.stage_id,
    projectFields[PROJECT_STAGE_FIELD_KEY],
    projectFields.project_stage,
    projectFields.effective_stage,
    projectFields.manual_stage,
    configSource.stage_id,
    configSource[PROJECT_STAGE_FIELD_KEY],
    configSource.project_stage,
    configSource.effective_stage,
    configSource.manual_stage,
  ]

  return candidates.map(value => String(value || '').trim()).find(value => value.length > 0) || ''
}

function normalizeProjectMappingState(configSource: AppConfigurationPayload) {
  const next = normalizeMappingState(configSource.project_fields_mapping || {})
  const stageValue = getLegacyStageValue(configSource)

  for (const legacyKey of ['stage_id', ...LEGACY_PROJECT_STAGE_KEYS, 'project_stage', PROJECT_STAGE_FIELD_KEY]) {
    delete next[legacyKey]
  }

  if (stageValue) {
    next[PROJECT_STAGE_FIELD_KEY] = stageValue
  }

  return next
}

function serializeProjectMappingState(source: Record<string, string>) {
  const next = normalizeMappingState(source)
  const stageValue = String(
    next.stage_id ||
    next[PROJECT_STAGE_FIELD_KEY] ||
    next.project_stage ||
    next.effective_stage ||
    next.manual_stage ||
    ''
  ).trim()

  for (const legacyKey of ['stage_id', ...LEGACY_PROJECT_STAGE_KEYS, 'project_stage', PROJECT_STAGE_FIELD_KEY]) {
    delete next[legacyKey]
  }

  if (stageValue) {
    next.stage_id = stageValue
    next[PROJECT_STAGE_FIELD_KEY] = stageValue
    next.manual_stage = stageValue
    next.effective_stage = stageValue
    next.project_stage = stageValue
  }

  return next
}

function mergeCreatedFieldMapping(
  currentMapping: Record<string, string>,
  serverMapping: Record<string, string> | undefined,
  fieldKey: string,
  fallbackValue?: string | number | null
) {
  const next = { ...normalizeMappingState(currentMapping) }
  const serverValue = serverMapping?.[fieldKey]
  const normalizedFallback = fallbackValue === undefined || fallbackValue === null
    ? ''
    : String(fallbackValue).trim()

  if (serverValue !== undefined && serverValue !== null && String(serverValue).trim()) {
    next[fieldKey] = String(serverValue)
  } else if (normalizedFallback) {
    next[fieldKey] = normalizedFallback
  }

  return next
}

async function loadData() {
    isLoading.value = true
    try {
        const [cfgRes, spRes] = await Promise.allSettled([
            apiStore.getConfiguration(),
            apiStore.getSmartProcesses()
        ])

        if (cfgRes.status !== 'fulfilled') {
            throw cfgRes.reason
        }

        const cfg = cfgRes.value
        config.value = cfg
        smartProcesses.value = spRes.status === 'fulfilled' ? (spRes.value.types || []) : []
        if (spRes.status !== 'fulfilled') {
            showStatus('error', 'Не удалось загрузить список смарт-процессов. Конфигурация загружена, попробуйте обновить страницу.')
        }
        
        // 3. Set Initial State
        if (cfg.sp_entity_type_id) {
            selectedSpId.value = Number(cfg.sp_entity_type_id)
            mapping.value = normalizeMappingState(cfg.fields_mapping || {})
            await loadSpFields(Number(cfg.sp_entity_type_id))
        }
        if (cfg.project_sp_entity_type_id) {
            selectedProjectSpId.value = Number(cfg.project_sp_entity_type_id)
            projectMapping.value = normalizeProjectMappingState(cfg)
            await loadProjectSpFields(Number(cfg.project_sp_entity_type_id))
            await validateProjectSpa()
        }
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
        isInit.value = true
    }
}

async function validateProjectSpa() {
    isValidatingProjectSpa.value = true
    try {
        projectSpaValidation.value = await apiStore.getProjectSpaValidation()
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isValidatingProjectSpa.value = false
    }
}

async function loadProjectSpFields(entityTypeId: number) {
    isLoading.value = true
    try {
        const res = await apiStore.getSpFields(entityTypeId)
        projectSpFields.value = res.fields || []
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
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
    statusMessage.value = null
    try {
        const serializedProjectMapping = serializeProjectMappingState(projectMapping.value)
        const newConfig = {
            ...config.value,
            sp_entity_type_id: selectedSpId.value,
            fields_mapping: mapping.value,
            project_sp_entity_type_id: selectedProjectSpId.value,
            project_fields_mapping: serializedProjectMapping,
            stage_id: serializedProjectMapping.stage_id || null,
            stage: serializedProjectMapping.stage || null,
            project_stage: serializedProjectMapping.stage || null,
            manual_stage: serializedProjectMapping.manual_stage || null,
            effective_stage: serializedProjectMapping.effective_stage || null,
            is_configured: true
        }
        const saveResult = await apiStore.saveConfiguration(newConfig)

        const syncInfo = saveResult?.project_sync
        const backfillInfo = saveResult?.timesheet_backfill
        if (syncInfo && typeof syncInfo === 'object') {
            const syncMode = String((syncInfo as Record<string, unknown>).sync_mode || '')
            const synced = Number((syncInfo as Record<string, unknown>).synced || 0)
            const created = Number((syncInfo as Record<string, unknown>).created || 0)
            const updated = Number((syncInfo as Record<string, unknown>).updated || 0)
            const backfillUpdated = typeof backfillInfo === 'object' ? Number((backfillInfo as Record<string, unknown>).updated || 0) : 0
            const backfillUnresolved = typeof backfillInfo === 'object' ? Number((backfillInfo as Record<string, unknown>).unresolved || 0) : 0
            showStatus(
                'success',
                `Настройки сохранены. Первичный sync (${syncMode || 'n/a'}): ${synced}, создано: ${created}, обновлено: ${updated}. Backfill меток: обновлено ${backfillUpdated}, без связки ${backfillUnresolved}.`
            )
        } else {
            showStatus('success', 'Настройки сохранены.')
        }

        if (selectedProjectSpId.value) {
            await validateProjectSpa()
        }
        router.push('/settings')
    } catch (e: any) {
        const errData = e?.data
        if (errData?.validation) {
            projectSpaValidation.value = errData.validation as ProjectSpaValidationPayload
            const errorText = errData?.error || 'Конфигурация Project SPA не прошла валидацию.'
            showStatus('error', errorText)
            return
        }
        processErrorGlobal(e)
    } finally {
        isSaving.value = false
    }
}

function getCreateOptionValue(mappingType: 'timesheet' | 'project', fieldKey: string) {
    return `${CREATE_OPTION_PREFIX}${mappingType}:${fieldKey}`
}

function canCreateMappedField(mappingType: 'timesheet' | 'project', fieldKey: string) {
    return mappingType === 'timesheet'
        ? APP_CREATABLE_FIELD_KEYS.has(fieldKey)
        : PROJECT_CREATABLE_FIELD_KEYS.has(fieldKey)
}

function normalizeAcceptedType(value?: string | null) {
    return String(value || '').trim().toLowerCase()
}

function isFieldTypeCompatible(field: MappingFieldDefinition, optionType?: string | null) {
    if (!field.acceptedTypes?.length) {
        return true
    }

    const accepted = new Set(field.acceptedTypes.map(type => normalizeAcceptedType(type)))
    const actualType = normalizeAcceptedType(optionType)
    if (!actualType) {
        return false
    }

    if (accepted.has(actualType)) {
        return true
    }

    if (accepted.has('string') && ['text', 'char'].includes(actualType)) {
        return true
    }
    if (accepted.has('integer') && ['int'].includes(actualType)) {
        return true
    }
    if (accepted.has('crm_status') && ['status', 'stage'].includes(actualType)) {
        return true
    }

    return false
}

function getFieldOptions(field: MappingFieldDefinition) {
    const currentValue = String(mapping.value[field.key] || '').trim()
    const options = spFields.value
      .filter(option => isFieldTypeCompatible(field, option.type) || String(option.id || '').trim() === currentValue)
      .map(f => ({
        label: `${f.title} (${f.type})`,
        value: f.id
      }))

    if (canCreateMappedField('timesheet', field.key)) {
        options.push({
            label: `+ Создать поле «${field.label}»`,
            value: getCreateOptionValue('timesheet', field.key)
        })
    }

    return options
}

function getProjectFieldOptions(field: MappingFieldDefinition) {
    const currentValue = String(projectMapping.value[field.key] || '').trim()
    const options = projectSpFields.value
      .filter(option => isFieldTypeCompatible(field, option.type) || String(option.id || '').trim() === currentValue)
      .map(f => ({
        label: `${f.title} (${f.type})`,
        value: f.id
      }))

    if (canCreateMappedField('project', field.key)) {
        options.push({
            label: `+ Создать поле «${field.label}»`,
            value: getCreateOptionValue('project', field.key)
        })
    }

    return options
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
        config.value = { ...config.value, ...newConfig }
        selectedSpId.value = Number(newConfig.sp_entity_type_id)
        mapping.value = normalizeMappingState(newConfig.fields_mapping || {})
        if (newConfig.sp_entity_type_id) {
            await loadSpFields(Number(newConfig.sp_entity_type_id))
        }
        // Reload SP list
        const spRes = await apiStore.getSmartProcesses()
        smartProcesses.value = spRes.types || []
        const warnings = result.field_warnings?.length ? ` Предупреждения: ${result.field_warnings.join('; ')}` : ''
        showStatus(
          'success',
          `Смарт-процесс создан и автоматически заполнен полями (ID: ${newConfig.sp_entity_type_id}, полей: ${result.created_fields_count || 0}).${warnings}`
        )
    } catch (e: any) {
        const errMsg = e?.data?.error || e?.message || 'Неизвестная ошибка'
        showStatus('error', `Ошибка: ${errMsg}`)
    } finally {
        isCreatingSP.value = false
    }
}

async function handleCreateMappedField(mappingType: 'timesheet' | 'project', fieldKey: string, fieldLabel: string) {
    const entityTypeId = mappingType === 'timesheet' ? Number(selectedSpId.value || 0) : Number(selectedProjectSpId.value || 0)
    if (!entityTypeId) {
        showStatus('error', 'Сначала выберите смарт-процесс.')
        return
    }

    creatingMappedField.value = `${mappingType}:${fieldKey}`
    statusMessage.value = null
    try {
        const result = await apiStore.createMappedField(entityTypeId, fieldKey, mappingType)
        config.value = { ...config.value, ...result.config }

        if (mappingType === 'timesheet') {
            mapping.value = mergeCreatedFieldMapping(mapping.value, result.config.fields_mapping, fieldKey, result.field_id)
            config.value.fields_mapping = { ...mapping.value }
            await loadSpFields(entityTypeId)
        } else {
            projectMapping.value = mergeCreatedFieldMapping(
                projectMapping.value,
                result.config.project_fields_mapping,
                fieldKey,
                result.field_id
            )
            config.value.project_fields_mapping = serializeProjectMappingState(projectMapping.value)
            await loadProjectSpFields(entityTypeId)
            await validateProjectSpa()
        }

        const warnings = result.field_warnings?.length ? ` Предупреждения: ${result.field_warnings.join('; ')}` : ''
        showStatus('success', `Поле «${fieldLabel}» создано и сразу привязано к маппингу.${warnings}`)
    } catch (e: any) {
        const errMsg = e?.data?.error || e?.message || 'Неизвестная ошибка'
        showStatus('error', `Ошибка создания поля «${fieldLabel}»: ${errMsg}`)
    } finally {
        creatingMappedField.value = null
    }
}

async function handleMappingSelectChange(
    event: Event,
    mappingType: 'timesheet' | 'project',
    fieldKey: string,
    fieldLabel: string,
) {
    const select = event.target as HTMLSelectElement | null
    const nextValue = select?.value || ''

    if (nextValue === getCreateOptionValue(mappingType, fieldKey)) {
        await handleCreateMappedField(mappingType, fieldKey, fieldLabel)
        return
    }

    if (mappingType === 'timesheet') {
        if (nextValue) {
            mapping.value[fieldKey] = nextValue
        } else {
            delete mapping.value[fieldKey]
        }
        return
    }

    if (nextValue) {
        projectMapping.value[fieldKey] = nextValue
    } else {
        delete projectMapping.value[fieldKey]
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
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="ms-page-header">
        <div>
          <h1 class="ms-title">Настройка полей</h1>
          <p class="ms-subtitle mt-2">Привязка полей приложения к Smart Process и проверка структуры данных.</p>
        </div>
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
          <B24Card title="Выбор Смарт-Процесса" class="ms-surface">
              <!-- Status Message -->
              <div v-if="statusMessage" class="mb-4 ms-note" :class="statusMessage.type === 'success' ? 'ms-note-success' : 'ms-note-danger'">
                  {{ statusMessage.text }}
              </div>

              <div class="w-full space-y-4">
                  <div>
                      <label class="mb-1 block text-sm font-semibold text-slate-800">Смарт-процесс</label>
                      <select 
                        v-model="selectedSpId" 
                        class="block w-full sm:text-sm"
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
                      <p class="mt-1 text-xs text-slate-500">Без ставки расчёт будет неточным. Применяется для новых записей.</p>
                  </div>

                  <div class="ms-panel-muted">
                      <div class="text-sm font-semibold text-slate-900">Источник поля «Наше юрлицо»</div>
                      <p class="mt-1 text-xs text-slate-500">
                          Поле в проектах заполняется автоматически из CRM-компаний, у которых `IS_MY_COMPANY = Y`.
                          Для поиска доступны название компании и ИНН.
                      </p>
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
                        </div>
                        <p class="text-sm text-slate-600">
                            Выберите процесс и нажмите "Подгрузить", чтобы получить список полей.
                            Кнопка создания смарт-процесса сразу создаёт сам процесс, обязательные поля и базовый маппинг.
                        </p>
                  </div>
              </div>
          </B24Card>

          <B24Card title="Смарт-процесс ПРОЕКТ (мастер-данные)" class="ms-surface">
              <div class="w-full space-y-4">
                  <div>
                      <label class="mb-1 block text-sm font-semibold text-slate-800">Смарт-процесс проектов</label>
                      <select
                        v-model="selectedProjectSpId"
                        class="block w-full sm:text-sm"
                      >
                          <option :value="null">-- Не выбрано --</option>
                          <option v-for="sp in smartProcesses" :key="`project-${sp.id}`" :value="sp.entityTypeId">
                              {{ sp.title }} (ID: {{ sp.entityTypeId }})
                          </option>
                      </select>
                      <p class="mt-1 text-xs text-slate-500">
                          Этот процесс используется как source of truth по карточке проекта.
                      </p>
                  </div>

                  <div class="flex flex-wrap gap-2">
                      <B24Button
                        label="Подгрузить поля проекта"
                        color="primary"
                        size="sm"
                        @click="() => { if (selectedProjectSpId) loadProjectSpFields(selectedProjectSpId) }"
                        :disabled="!selectedProjectSpId || isLoading"
                      />
                      <B24Button
                        label="Проверить Project SPA"
                        color="default"
                        size="sm"
                        @click="validateProjectSpa"
                        :loading="isValidatingProjectSpa"
                        :disabled="!selectedProjectSpId || isValidatingProjectSpa"
                      />
                  </div>
              </div>
          </B24Card>

          <B24Card title="Проверка связности Project SPA" v-if="selectedProjectSpId" class="ms-surface">
              <div v-if="projectSpaValidation" class="space-y-3 text-sm">
                  <div class="ms-note" :class="projectSpaValidation.is_valid ? 'ms-note-success' : 'ms-note-danger'">
                      {{ projectSpaValidation.is_valid ? 'Валидация пройдена: контур Project SPA готов.' : 'Есть проблемы конфигурации Project SPA.' }}
                  </div>

                  <div class="grid gap-2 md:grid-cols-4">
                      <div class="ms-panel-muted">
                          <div class="text-xs text-slate-500">Элементов в Project SPA</div>
                          <div class="text-lg font-semibold text-slate-900">{{ projectSpaValidation.linkage_issues.total_items }}</div>
                      </div>
                      <div class="ms-panel-muted">
                          <div class="text-xs text-slate-500">Без связи с группой</div>
                          <div class="text-lg font-semibold text-amber-600">{{ projectSpaValidation.linkage_issues.missing_group_link_count }}</div>
                      </div>
                      <div class="ms-panel-muted">
                          <div class="text-xs text-slate-500">Конфликтов group_id</div>
                          <div class="text-lg font-semibold text-rose-600">{{ projectSpaValidation.linkage_issues.duplicate_group_link_count }}</div>
                      </div>
                      <div class="ms-panel-muted">
                          <div class="text-xs text-slate-500">Конфликтов project_item_id</div>
                          <div class="text-lg font-semibold text-rose-600">{{ projectSpaValidation.linkage_issues.duplicate_project_item_link_count }}</div>
                      </div>
                  </div>

                  <div v-if="projectSpaValidation.access_error" class="ms-note ms-note-danger">
                      Ошибка доступа к Project SPA: {{ projectSpaValidation.access_error }}
                  </div>
                  <div v-if="projectSpaValidation.write_access_error" class="ms-note ms-note-danger">
                      Ошибка прав на обновление Project SPA: {{ projectSpaValidation.write_access_error }}
                  </div>

                  <div v-if="projectSpaValidation.missing_mapping_keys.length > 0" class="ms-panel-muted">
                      <div class="font-semibold text-slate-900">Не заполнены обязательные маппинги</div>
                      <div class="mt-1 text-xs text-slate-600">
                          {{ projectSpaValidation.missing_mapping_keys.join(', ') }}
                      </div>
                  </div>

                  <div v-if="projectSpaValidation.missing_fields_in_sp.length > 0" class="ms-panel-muted">
                      <div class="font-semibold text-slate-900">Сопоставления указывают на несуществующие поля</div>
                      <div class="mt-1 space-y-1 text-xs text-slate-600">
                          <div v-for="row in projectSpaValidation.missing_fields_in_sp" :key="`missing-field-${row.key}`">
                              {{ row.key }} → {{ row.mapped_field }}
                          </div>
                      </div>
                  </div>

                  <div v-if="projectSpaValidation.type_mismatches.length > 0" class="ms-panel-muted">
                      <div class="font-semibold text-slate-900">Несоответствие типов полей</div>
                      <div class="mt-1 space-y-1 text-xs text-slate-600">
                          <div v-for="row in projectSpaValidation.type_mismatches" :key="`type-mismatch-${row.key}`">
                              {{ row.key }} → {{ row.mapped_field }} (ожидалось: {{ row.expected_type }}, фактически: {{ row.actual_type }})
                          </div>
                      </div>
                  </div>

                  <div v-if="projectSpaValidation.linkage_issues.duplicate_project_item_links.length > 0" class="ms-panel-muted">
                      <div class="font-semibold text-slate-900">Конфликты project_item_id → group_id</div>
                      <div class="mt-1 space-y-1 text-xs text-slate-600">
                          <div
                            v-for="row in projectSpaValidation.linkage_issues.duplicate_project_item_links"
                            :key="`dup-item-${row.project_item_id}`"
                          >
                              {{ row.project_item_id }} → {{ row.bitrix_group_ids.join(', ') }}
                          </div>
                      </div>
                  </div>

                  <div v-if="projectSpaValidation.warnings.length > 0" class="ms-panel-muted">
                      <div class="font-semibold text-slate-900">Предупреждения</div>
                      <div class="mt-1 space-y-1 text-xs text-slate-600">
                          <div v-for="(warning, index) in projectSpaValidation.warnings" :key="`project-warning-${index}`">
                              {{ warning }}
                          </div>
                      </div>
                  </div>
              </div>
              <div v-else class="ms-empty-state">
                  Нажмите «Проверить Project SPA», чтобы увидеть статус маппинга и связности.
              </div>
          </B24Card>

          <B24Card title="Доступные поля Project SPA" v-if="selectedProjectSpId" class="ms-surface">
             <div v-if="projectSpFields.length > 0" class="ms-table-shell max-h-60 overflow-y-auto">
                 <table class="ms-table">
                     <thead class="sticky top-0">
                         <tr>
                             <th>Название</th>
                             <th>Код (ID)</th>
                             <th>Тип</th>
                         </tr>
                     </thead>
                     <tbody class="text-sm">
                         <tr v-for="field in projectSpFields" :key="`project-field-${field.id}`">
                             <td class="font-medium text-slate-900">{{ field.title }}</td>
                             <td class="font-mono text-xs text-slate-500">{{ field.id }}</td>
                             <td class="text-slate-500">{{ field.type }}</td>
                         </tr>
                     </tbody>
                 </table>
             </div>
             <div v-else class="ms-empty-state">
                 Поля еще не загружены. Нажмите "Подгрузить поля проекта".
             </div>
          </B24Card>

          <!-- Field List (Read-Only) -->
          <B24Card title="Доступные поля сущности" v-if="selectedSpId" class="ms-surface">
             <div v-if="spFields.length > 0" class="ms-table-shell max-h-60 overflow-y-auto">
                 <table class="ms-table">
                     <thead class="sticky top-0">
                         <tr>
                             <th>Название</th>
                             <th>Код (ID)</th>
                             <th>Тип</th>
                         </tr>
                     </thead>
                     <tbody class="text-sm">
                         <tr v-for="field in spFields" :key="field.id">
                             <td class="font-medium text-slate-900">{{ field.title }}</td>
                             <td class="font-mono text-xs text-slate-500">{{ field.id }}</td>
                             <td class="text-slate-500">{{ field.type }}</td>
                         </tr>
                     </tbody>
                 </table>
             </div>
             <div v-else class="ms-empty-state">
                 Поля еще не загружены. Нажмите "Подгрузить поля".
             </div>
          </B24Card>

          <!-- Mapping Table -->
          <B24Card title="Сопоставление полей" v-if="selectedSpId" class="ms-surface">
              <div class="ms-table-shell">
                  <table class="ms-table">
                      <thead>
                          <tr>
                              <th class="w-1/2">
                                  Поле приложения
                              </th>
                              <th class="w-1/2">
                                  Поле в Битрикс24
                              </th>
                          </tr>
                      </thead>
                      <tbody>
                          <tr v-for="field in APP_FIELDS" :key="field.key">
                              <td>
                                  <div class="text-sm font-medium text-slate-900">{{ field.label }}</div>
                                  <div class="text-xs text-slate-500">{{ field.desc }}</div>
                                  <div class="mt-1 text-xs text-lime-700">Тип: {{ field.type }}</div>
                              </td>
                              <td>
                                  <select 
                                    :value="mapping[field.key] || ''"
                                    class="block w-full sm:text-sm"
                                    :disabled="creatingMappedField === `timesheet:${field.key}`"
                                    @change="(event) => handleMappingSelectChange(event, 'timesheet', field.key, field.label)"
                                  >
                                      <option value="">-- Не сопоставлено --</option>
                                      <option v-for="opt in getFieldOptions(field)" :key="opt.value" :value="opt.value">
                                          {{ opt.label }}
                                      </option>
                                  </select>
                              </td>
                          </tr>
                      </tbody>
                  </table>
              </div>
          </B24Card>

          <B24Card title="Сопоставление полей проекта (Project SPA)" v-if="selectedProjectSpId" class="ms-surface">
              <div class="ms-table-shell">
                  <table class="ms-table">
                      <thead>
                          <tr>
                              <th class="w-1/2">
                                  Поле проекта в приложении
                              </th>
                              <th class="w-1/2">
                                  Поле в Project SPA
                              </th>
                          </tr>
                      </thead>
                      <tbody>
                          <tr v-for="field in PROJECT_FIELDS" :key="`project-map-${field.key}`">
                              <td>
                                  <div class="text-sm font-medium text-slate-900">{{ field.label }}</div>
                                  <div class="text-xs text-slate-500">{{ field.desc }}</div>
                                  <div class="mt-1 text-xs text-lime-700">Тип: {{ field.type }}</div>
                              </td>
                              <td>
                                  <select
                                    :value="projectMapping[field.key] || ''"
                                    class="block w-full sm:text-sm"
                                    :disabled="creatingMappedField === `project:${field.key}`"
                                    @change="(event) => handleMappingSelectChange(event, 'project', field.key, field.label)"
                                  >
                                      <option value="">-- Не сопоставлено --</option>
                                      <option v-for="opt in getProjectFieldOptions(field)" :key="opt.value" :value="opt.value">
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
  color: #0f172a;
}

.rate-field__input {
  width: 100%;
  min-height: 48px;
  padding: 10px 12px;
  border: 1px solid #d8e2ee;
  border-radius: 10px;
  background: #fff;
  font-size: 16px;
  line-height: 1.2;
  color: #334155;
}

.rate-field__input:focus {
  outline: none;
  border-color: #84cc16;
  box-shadow: 0 0 0 4px rgba(190, 242, 100, 0.35);
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
