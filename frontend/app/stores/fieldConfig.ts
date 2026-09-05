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
    'hourly_rate_snapshot': 'HOURLY_RATE_SNAPSHOT',
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
    hourly_rate_snapshot: {
        labels: ['Ставка часа (снимок)', 'Ставка часа snapshot', 'Hourly rate snapshot'],
        codeHints: ['HOURLY_RATE_SNAPSHOT'],
    },
}

/**
 * Possible shapes returned by app.option.get via $b24.callMethod().getData().
 * Either the raw config string, or an object exposing timestamp_config
 * directly or nested under `result`.
 */
type OptionGetPayload =
    | string
    | {
        result?: { timestamp_config?: string | null }
        timestamp_config?: string | null
    }
    | null
    | undefined

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
                // @ts-expect-error - callMethod typing
                const result = await $b24.callMethod('app.option.get', {})
                const data = result.getData()
                const payload = data as OptionGetPayload
                console.log('[FieldConfig] Raw app.option.get response:', JSON.stringify(data))

                // Try multiple paths to find timestamp_config
                let rawConfigStr: string | null | undefined = null

                if (typeof payload === 'object' && payload !== null) {
                    // Path 1: data.result.timestamp_config (if getData returns whole response)
                    rawConfigStr = payload?.result?.timestamp_config
                    // Path 2: data.timestamp_config (if getData returns result directly)
                    if (!rawConfigStr) rawConfigStr = payload?.timestamp_config
                    // Path 3: data is the config string itself
                    if (!rawConfigStr && typeof payload === 'string') rawConfigStr = payload
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
            } catch (e: unknown) {
                console.error('[FieldConfig] Load error:', e)
                loadError.value = (e as { message?: string })?.message || 'Ошибка загрузки конфигурации'
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

        function extractSpFieldsMap(raw: unknown): Record<string, unknown> {
            const rawObj = raw as { result?: unknown, fields?: unknown } | null | undefined
            const result = rawObj?.result as { fields?: unknown } | null | undefined
            if (result && typeof result === 'object' && result.fields && typeof result.fields === 'object') {
                return result.fields as Record<string, unknown>
            }
            if (rawObj?.fields && typeof rawObj.fields === 'object') {
                return rawObj.fields as Record<string, unknown>
            }
            if (result && typeof result === 'object') {
                return result as Record<string, unknown>
            }
            return {}
        }

        function getFieldMetaTitle(meta: unknown) {
            const metaObj = meta as Record<string, unknown> | null | undefined
            return String(
                metaObj?.title
                || metaObj?.TITLE
                || metaObj?.formLabel
                || metaObj?.FORM_LABEL
                || metaObj?.listLabel
                || metaObj?.LIST_LABEL
                || metaObj?.label
                || metaObj?.LABEL
                || ''
            ).trim()
        }

        function matchFieldByRule(
            spFieldsList: Array<{ id: string; title: string; meta: unknown }>,
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
                const fieldMeta = field.meta as Record<string, unknown> | null | undefined
                const logicalNameNormalized = normalizeLabel(
                    fieldMeta?.name
                    || fieldMeta?.NAME
                    || fieldMeta?.fieldName
                    || fieldMeta?.FIELD_NAME
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
            // app.option.set — метод ТОЛЬКО для администратора портала
            // (https://apidocs.bitrix24.ru/api-reference/common/settings/app-option-set.html).
            // У рядового сотрудника запись падает с AccessException, результат не
            // сохраняется — значит тяжёлый crm.item.fields и заведомо провальный
            // app.option.set повторяются на КАЖДОЙ загрузке в критическом пути
            // (loadFromB24 → до loadTaskTree). Это и тормозило вкладку задачи у всех,
            // кто не админ. Автоопределение полей — разовая админская настройка:
            // выполняет его только тот, кто способен сохранить результат портально
            // (app.option — общее хранилище приложения, видно всем сразу).
            const userStore = useUserStore()
            if (!userStore.isAdmin) {
                console.log('[FieldConfig] Auto-detect skipped: сохранить маппинг полей может только администратор')
                return
            }

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
                // @ts-expect-error - callMethod typing
                const fieldsRes = await $b24.callMethod('crm.item.fields', { entityTypeId: spEntityTypeId })
                const fieldsData = fieldsRes?.getData?.()
                const spFieldsMap = extractSpFieldsMap(fieldsData)
                const spFieldsList = Object.entries(spFieldsMap).map(([fieldId, meta]) => ({
                    id: String(fieldId || ''),
                    title: getFieldMetaTitle(meta),
                    type: String((meta as Record<string, unknown>)?.type || (meta as Record<string, unknown>)?.TYPE || ''),
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
                    // @ts-expect-error - callMethod typing
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
