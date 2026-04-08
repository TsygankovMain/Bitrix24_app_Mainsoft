export interface AppConfigurationPayload {
  sp_entity_type_id?: number | string | null
  hourly_rate?: number | string | null
  fields_mapping?: Record<string, string>
  task_fields?: Record<string, string>
  spa_fields?: Record<string, string>
  clickableLabelsEnabled?: boolean
  [key: string]: unknown
}

export interface FieldConfigObject {
  DEFAULT_SMART_PROCESS_ID: number
  FIELDS: Record<string, string>
  TASK_FIELDS: Record<string, string>
  SPA_FIELDS: Record<string, string>
  HOURLY_RATE: number
}
