/**
 * Field Configuration Store
 * 
 * Centralized store for field mapping configuration.
 * Loads config from app.option.get (timestamp_config) and provides
 * typed access to entityTypeId, fields, taskFields, and spaFields.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { B24Frame } from '@bitrix24/b24jssdk'
import type { AppConfigurationPayload, FieldConfigObject } from '~/types/config'

/**
 * Maps backend config keys (from installation_service.py) 
 * to frontend field keys used in components.
 */
const BACKEND_MAPPING: Record<string, string> = {
    'id_zadachi': 'TASK_ID',
    'sotrudnik': 'EMPLOYEE',
    'kolichestvo_chasov': 'HOURS',
    'uchitivaem': 'IS_CONSIDERED',
    'ne_uchitivaemie_chasi': 'NON_BILLABLE_HOURS',
    'opisanie': 'DESCRIPTION',
    'id_zadach_ierarhiya': 'TASK_HIERARCHY',
    'title_zadach_ierarhiya': 'TITLE_HIERARCHY',
    'project_id': 'PROJECT_ID',
    'project_item_id': 'PROJECT_ITEM_ID',
    'project_title': 'PROJECT_TITLE',
    'data': 'DATE',
    'task_name': 'TASK_NAME',
    'our_inn': 'OUR_INN',
    'client_inn': 'CLIENT_INN',
}

const AUTO_DETECT_MAPPING_RULES: Record<string, { labels: string[]; codeHints: string[] }> = {
    task_name: {
        labels: ['Название задачи'],
        codeHints: ['TASK_NAME'],
    },
    our_inn: {
        labels: ['Наш ИНН', 'ИНН нашей компании', 'ИНН исполнителя'],
        codeHints: ['OUR_INN'],
    },
    client_inn: {
        labels: ['ИНН клиента', 'Клиентский ИНН'],
        codeHints: ['CLIENT_INN'],
    },
    project_item_id: {
        labels: ['ID элемента проекта SPA', 'ID элемента проекта', 'Project item id'],
        codeHints: ['PROJECT_ITEM_ID'],
    },
}

export interface FieldConfigState {
    entityTypeId: number
    fields: Record<string, string>  // e.g. { TASK_ID: 'ufCrm87_xxx', HOURS: 'ufCrm87_yyy', ... }
    taskFields: Record<string, string>  // e.g. { OUR_INN: 'UF_TASKS_TASK_xxx' }
    spaFields: Record<string, string>   // e.g. { OUR_INN: 'ufCrm87_xxx' }
    hourlyRate: number
}

export const useFieldConfigStore = defineStore(
    'fieldConfig',
    () => {
        const entityTypeId = ref(0)
        const fields = ref<Record<string, string>>({})
        const taskFields = ref<Record<string, string>>({})
        const spaFields = ref<Record<string, string>>({})
        const hourlyRate = ref(0)
        const isLoaded = ref(false)
        const loadError = ref<string | null>(null)

        const isConfigured = computed(() => {
            return entityTypeId.value > 0 && !!fields.value.TASK_ID && !!fields.value.HOURS
        })

        /**
         * Load configuration from Bitrix24 app.option.get.
         * Parses timestamp_config JSON and maps backend keys to frontend keys.
         */
        async function loadFromB24($b24: B24Frame) {
            loadError.value = null
            try {
                // @ts-ignore - callMethod typing
                const result = await $b24.callMethod('app.option.get', {})
                const data = result.getData()
                console.log('[FieldConfig] Raw app.option.get response:', JSON.stringify(data))

                // Try multiple paths to find timestamp_config
                let rawConfigStr: string | null = null

                if (typeof data === 'object' && data !== null) {
                    // Path 1: data.result.timestamp_config (if getData returns whole response)
                    rawConfigStr = data?.result?.timestamp_config
                    // Path 2: data.timestamp_config (if getData returns result directly)
                    if (!rawConfigStr) rawConfigStr = data?.timestamp_config
                    // Path 3: data is the config string itself
                    if (!rawConfigStr && typeof data === 'string') rawConfigStr = data
                }

                console.log('[FieldConfig] Found timestamp_config:', rawConfigStr ? rawConfigStr.substring(0, 100) + '...' : 'null')

                if (rawConfigStr) {
                    const rawConfig = JSON.parse(rawConfigStr)
                    console.log('[FieldConfig] Parsed config:', JSON.stringify(rawConfig).substring(0, 200))
                    applyRawConfig(rawConfig)
                    await autoDetectMissingMappings($b24, rawConfig)
                } else {
                    console.warn('[FieldConfig] No timestamp_config found in response. Data keys:', data ? Object.keys(data) : 'null')
                    loadError.value = 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей и настройте поля.'
                }
            } catch (e: any) {
                console.error('[FieldConfig] Load error:', e)
                loadError.value = e.message || 'Ошибка загрузки конфигурации'
            } finally {
                isLoaded.value = true
            }
        }

        function normalizeLabel(value: unknown) {
            return String(value || '')
                .trim()
                .toLowerCase()
                .replace(/\s+/g, ' ')
        }

        function extractSpFieldsMap(raw: any): Record<string, any> {
            const result = raw?.result
            if (result && typeof result === 'object' && result.fields && typeof result.fields === 'object') {
                return result.fields
            }
            if (raw?.fields && typeof raw.fields === 'object') {
                return raw.fields
            }
            if (result && typeof result === 'object') {
                return result
            }
            return {}
        }

        function getFieldMetaTitle(meta: any) {
            return String(
                meta?.title
                || meta?.TITLE
                || meta?.formLabel
                || meta?.FORM_LABEL
                || meta?.listLabel
                || meta?.LIST_LABEL
                || meta?.label
                || meta?.LABEL
                || ''
            ).trim()
        }

        function matchFieldByRule(
            spFieldsList: Array<{ id: string; title: string; meta: any }>,
            backendKey: string,
        ) {
            const rule = AUTO_DETECT_MAPPING_RULES[backendKey]
            if (!rule) {
                return null
            }

            const expectedLabels = rule.labels.map(normalizeLabel).filter(Boolean)
            const codeHints = rule.codeHints.map(hint => normalizeLabel(hint).replace(/_/g, '')).filter(Boolean)

            const exactByLabel = spFieldsList.find((field) => {
                const title = normalizeLabel(field.title)
                return expectedLabels.some((expected) => expected && title === expected)
            })
            if (exactByLabel) {
                return exactByLabel
            }

            const containsByLabel = spFieldsList.find((field) => {
                const title = normalizeLabel(field.title)
                return expectedLabels.some((expected) => expected && title.includes(expected))
            })
            if (containsByLabel) {
                return containsByLabel
            }

            const byHint = spFieldsList.find((field) => {
                const fieldIdNormalized = normalizeLabel(field.id).replace(/_/g, '')
                const titleNormalized = normalizeLabel(field.title).replace(/_/g, '')
                const logicalNameNormalized = normalizeLabel(
                    field.meta?.name
                    || field.meta?.NAME
                    || field.meta?.fieldName
                    || field.meta?.FIELD_NAME
                    || ''
                ).replace(/_/g, '')

                return codeHints.some((hint) =>
                    hint
                    && (
                        fieldIdNormalized.includes(hint)
                        || titleNormalized.includes(hint)
                        || logicalNameNormalized.includes(hint)
                    )
                )
            })
            if (byHint) {
                return byHint
            }

            return null
        }

        async function autoDetectMissingMappings($b24: B24Frame, rawConfig: AppConfigurationPayload) {
            const spEntityTypeId = Number(rawConfig?.sp_entity_type_id || 0)
            if (!spEntityTypeId) {
                console.log('[FieldConfig] Auto-detect skipped: no sp_entity_type_id')
                return
            }

            const rawFieldsMapping = { ...(rawConfig?.fields_mapping || {}) }
            const missingKeys = Object.keys(AUTO_DETECT_MAPPING_RULES).filter((backendKey) => {
                const mappedField = String(rawFieldsMapping[backendKey] || '').trim()
                return mappedField.length === 0
            })

            console.log('[FieldConfig] Auto-detect start', {
                spEntityTypeId,
                missingKeys,
            })

            if (missingKeys.length === 0) {
                return
            }

            try {
                // @ts-ignore - callMethod typing
                const fieldsRes = await $b24.callMethod('crm.item.fields', { entityTypeId: spEntityTypeId })
                const fieldsData = fieldsRes?.getData?.()
                const spFieldsMap = extractSpFieldsMap(fieldsData)
                const spFieldsList = Object.entries(spFieldsMap).map(([fieldId, meta]) => ({
                    id: String(fieldId || ''),
                    title: getFieldMetaTitle(meta),
                    type: String((meta as any)?.type || (meta as any)?.TYPE || ''),
                    meta,
                }))

                const discoveredMapping: Record<string, string> = {}

                for (const backendKey of missingKeys) {
                    const matchedField = matchFieldByRule(spFieldsList, backendKey)
                    if (matchedField?.id) {
                        discoveredMapping[backendKey] = matchedField.id
                    }
                }

                if (!Object.keys(discoveredMapping).length) {
                    console.warn('[FieldConfig] Auto-detect could not resolve missing mappings', {
                        missingKeys,
                        spEntityTypeId,
                        availableFieldTitles: spFieldsList
                            .map(field => field.title || field.id)
                            .filter(Boolean)
                            .slice(0, 60),
                    })
                    return
                }

                const mergedRawMapping = {
                    ...rawFieldsMapping,
                    ...discoveredMapping,
                }
                const mergedFrontendMapping = { ...fields.value }
                for (const [backendKey, fieldId] of Object.entries(discoveredMapping)) {
                    const frontendKey = BACKEND_MAPPING[backendKey]
                    if (frontendKey && fieldId) {
                        mergedFrontendMapping[frontendKey] = String(fieldId)
                    }
                }

                fields.value = mergedFrontendMapping
                console.info('[FieldConfig] Auto-detected missing mappings', {
                    spEntityTypeId,
                    discoveredMapping,
                })

                // Keep config object in sync in runtime
                rawConfig.fields_mapping = mergedRawMapping

                // Persist the auto-detected mappings back to Bitrix
                try {
                    // @ts-ignore - callMethod typing
                    await $b24.callMethod('app.option.set', {
                        options: {
                            timestamp_config: JSON.stringify(rawConfig)
                        }
                    })
                    console.info('[FieldConfig] Persisted auto-detected mappings to app.option', {
                        missingKeys,
                        mergedRawMapping
                    })
                } catch (saveError) {
                    console.warn('[FieldConfig] Failed to persist auto-detected mappings', saveError)
                }
            } catch (error) {
                console.warn('[FieldConfig] Auto-detect missing mappings failed', {
                    spEntityTypeId,
                    missingKeys,
                    error,
                })
            }
        }

        /**
         * Apply raw config object (from app.option or direct API).
         * Handles the backend→frontend key mapping.
         */
        function applyRawConfig(rawConfig: AppConfigurationPayload) {
            entityTypeId.value = rawConfig.sp_entity_type_id ? Number(rawConfig.sp_entity_type_id) : 0

            const backendFields = rawConfig.fields_mapping || {}
            const mappedFields: Record<string, string> = {}

            Object.entries(BACKEND_MAPPING).forEach(([backendKey, frontendKey]) => {
                if (backendFields[backendKey]) {
                    mappedFields[frontendKey] = backendFields[backendKey]
                }
            })

            fields.value = mappedFields

            // Task fields and SPA fields are stored separately in the config
            // These map to UF_TASKS_TASK_xxx and ufCrmXX_xxx respectively
            taskFields.value = rawConfig.task_fields || {}
            spaFields.value = rawConfig.spa_fields || {}
            hourlyRate.value = rawConfig.hourly_rate ? Number(rawConfig.hourly_rate) : 0

            console.log('[FieldConfig] Config applied:', {
                entityTypeId: entityTypeId.value,
                fields: Object.keys(fields.value).length,
                taskFields: Object.keys(taskFields.value).length,
                spaFields: Object.keys(spaFields.value).length,
                hourlyRate: hourlyRate.value,
            })
        }

        /**
         * Get fields as the config object expected by embedded.vue / task.vue.
         * Backward-compatible format: { DEFAULT_SMART_PROCESS_ID, FIELDS, TASK_FIELDS, SPA_FIELDS }
         */
        const configObject = computed<FieldConfigObject>(() => ({
            DEFAULT_SMART_PROCESS_ID: entityTypeId.value,
            FIELDS: fields.value,
            TASK_FIELDS: taskFields.value,
            SPA_FIELDS: spaFields.value,
            HOURLY_RATE: hourlyRate.value,
        }))

        return {
            entityTypeId,
            fields,
            taskFields,
            spaFields,
            hourlyRate,
            isLoaded,
            isConfigured,
            loadError,
            configObject,
            loadFromB24,
            applyRawConfig,
        }
    }
)
