export interface AppConfigurationPayload {
  sp_entity_type_id?: number | string | null
  project_sp_entity_type_id?: number | string | null
  hourly_rate?: number | string | null
  fields_mapping?: Record<string, string>
  project_fields_mapping?: Record<string, string>
  stage_id?: string | null
  stage?: string | null
  project_stage?: string | null
  manual_stage?: string | null
  effective_stage?: string | null
  task_fields?: Record<string, string>
  spa_fields?: Record<string, string>
  clickableLabelsEnabled?: boolean
  [key: string]: unknown
}

export interface SmartProcessOption {
  id: string | number
  entityTypeId: number
  title: string
  [key: string]: unknown
}

export interface SmartProcessFieldOption {
  id: string | number
  title: string
  type: string
  [key: string]: unknown
}

export interface MappingFieldDefinition {
  key: string
  label: string
  type: string
  desc: string
  allowCreate?: boolean
  acceptedTypes?: string[]
}

export interface ProjectSpaTypeMismatch {
  key: string
  mapped_field: string
  expected_type: string
  actual_type: string
}

export interface ProjectSpaMissingField {
  key: string
  mapped_field: string
}

export interface ProjectSpaDuplicateLink {
  bitrix_group_id: string
  project_item_ids: string[]
}

export interface ProjectSpaDuplicateItemLink {
  project_item_id: string
  bitrix_group_ids: string[]
}

export interface ProjectSpaLinkageIssues {
  total_items: number
  missing_group_link_count: number
  duplicate_group_link_count: number
  duplicate_group_links: ProjectSpaDuplicateLink[]
  duplicate_project_item_link_count: number
  duplicate_project_item_links: ProjectSpaDuplicateItemLink[]
}

export interface ProjectSpaValidationPayload {
  is_configured: boolean
  is_valid: boolean
  entity_type_id: number
  required_mapping_keys: string[]
  missing_mapping_keys: string[]
  missing_fields_in_sp: ProjectSpaMissingField[]
  type_mismatches: ProjectSpaTypeMismatch[]
  access_error?: string | null
  write_access_error?: string | null
  warnings: string[]
  linkage_issues: ProjectSpaLinkageIssues
}

export interface FieldConfigObject {
  DEFAULT_SMART_PROCESS_ID: number
  FIELDS: Record<string, string>
  TASK_FIELDS: Record<string, string>
  SPA_FIELDS: Record<string, string>
  HOURLY_RATE: number
}
