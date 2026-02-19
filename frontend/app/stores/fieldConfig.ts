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
    'project_title': 'PROJECT_TITLE',
    'data': 'DATE',
    'task_name': 'TASK_NAME',
    'our_inn': 'OUR_INN',
    'client_inn': 'CLIENT_INN',
}

export interface FieldConfigState {
    entityTypeId: number
    fields: Record<string, string>  // e.g. { TASK_ID: 'ufCrm87_xxx', HOURS: 'ufCrm87_yyy', ... }
    taskFields: Record<string, string>  // e.g. { OUR_INN: 'UF_TASKS_TASK_xxx' }
    spaFields: Record<string, string>   // e.g. { OUR_INN: 'ufCrm87_xxx' }
}

export const useFieldConfigStore = defineStore(
    'fieldConfig',
    () => {
        const entityTypeId = ref(0)
        const fields = ref<Record<string, string>>({})
        const taskFields = ref<Record<string, string>>({})
        const spaFields = ref<Record<string, string>>({})
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
                } else {
                    console.warn('[FieldConfig] No timestamp_config found in response. Data keys:', data ? Object.keys(data) : 'null')
                    loadError.value = 'Конфигурация не найдена. Зайдите в Настройки → Маппинг и настройте поля.'
                }
            } catch (e: any) {
                console.error('[FieldConfig] Load error:', e)
                loadError.value = e.message || 'Ошибка загрузки конфигурации'
            } finally {
                isLoaded.value = true
            }
        }

        /**
         * Apply raw config object (from app.option or direct API).
         * Handles the backend→frontend key mapping.
         */
        function applyRawConfig(rawConfig: Record<string, any>) {
            entityTypeId.value = rawConfig.sp_entity_type_id || 0

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

            console.log('[FieldConfig] Config applied:', {
                entityTypeId: entityTypeId.value,
                fields: Object.keys(fields.value).length,
                taskFields: Object.keys(taskFields.value).length,
                spaFields: Object.keys(spaFields.value).length,
            })
        }

        /**
         * Get fields as the config object expected by embedded.vue / task.vue.
         * Backward-compatible format: { DEFAULT_SMART_PROCESS_ID, FIELDS, TASK_FIELDS, SPA_FIELDS }
         */
        const configObject = computed(() => ({
            DEFAULT_SMART_PROCESS_ID: entityTypeId.value,
            FIELDS: fields.value,
            TASK_FIELDS: taskFields.value,
            SPA_FIELDS: spaFields.value,
        }))

        return {
            entityTypeId,
            fields,
            taskFields,
            spaFields,
            isLoaded,
            isConfigured,
            loadError,
            configObject,
            loadFromB24,
            applyRawConfig,
        }
    }
)
