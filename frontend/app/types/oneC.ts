/** Отправка часов за период в 1С и её построчный результат. */
export interface OneCExportRow {
  entry_id: string
  status: string
  reason: string
  reason_label: string
  text: string
}

export interface OneCExportRun {
  id: string
  period_from: string
  period_to: string
  sending_id: string
  /** ok — принято всё, partial — часть строк отклонена, failed — не принято */
  status: 'ok' | 'partial' | 'failed'
  sent_rows: number
  accepted: number
  rejected: number
  documents: string[]
  rows: OneCExportRow[]
  message: string
  created_at: string | null
}

/** Строки для экрана сопоставления. */
export interface OneCEmployeeRow {
  id: string
  name: string
  /** ФИО физлица в 1С, заданное человеком */
  mapped_to: string
}

export interface OneCCompanyRow {
  id: string
  name: string
  /** ИНН, найденный в Битриксе автоматически */
  inn_auto: string
  /** ИНН, заданный руками; важнее автоматического */
  inn_manual: string
}

export interface OneCMappingPayload {
  employees: OneCEmployeeRow[]
  companies: OneCCompanyRow[]
  legal_entities: OneCCompanyRow[]
}
