/** Один из трёх шагов оркестратора кнопки «Создать проект» (компания /
 * группа в Задачах / карточка смарт-процесса). Формат совпадает с
 * StepResult.as_dict() на бэкенде (project_creation_service.py).
 *
 * status:
 * - 'created'   — шаг создал новую сущность.
 * - 'found'     — сущность уже существовала, шаг её переиспользовал
 *                 (нормальный исход при повторном нажатии, id заполнен).
 * - 'ambiguous' — совпадений по названию больше одного; создавать
 *                 автоматически нельзя, нужен выбор пользователя из candidates.
 * - 'skipped'   — шаг НЕ пытался ничего делать, потому что предыдущий шаг
 *                 не дал нужного идентификатора. Это не ошибка: id=null
 *                 ожидаемо, error=null. Показывать по-другому, чем 'error'.
 * - 'error'     — шаг пытался и не смог (сетевая ошибка Битрикса и т.п.),
 *                 подробности в error.
 */
export interface ProjectCreationStep {
  status: 'created' | 'found' | 'ambiguous' | 'skipped' | 'error'
  id: string | null
  name: string
  candidates: Array<{ id: string, name: string }>
  error: string | null
}

/** Ответ POST /api/project-board/create.
 *
 * done не означает «все три шага создали новое» — он означает «карточка не
 * в состоянии ошибки». Шаги вполне могут вернуть 'found' вместо 'created'
 * (повторное нажатие после частичного успеха), и это нормальный успешный
 * исход. missing_fields — обязательные поля формы, которых не хватило для
 * старта (см. project_creation_defaults.resolve_project_fields).
 */
export interface ProjectCreationResult {
  company: ProjectCreationStep
  group: ProjectCreationStep
  card: ProjectCreationStep
  done: boolean
  missing_fields: string[]
}

/** Форма кнопки «Создать проект». CompanySearchResult/MyCompaniesResult для
 * шага выбора компании уже определены в ~/types/project-board — здесь не
 * дублируются. */
export interface ProjectCreationForm {
  project_name: string
  company_id: string | null
  company_name: string
  our_legal_entity_id: string | null
  project_start_date: string
  project_end_date: string
  project_hours_budget: string
  hourly_rate: string
  project_type: string
  is_support: boolean
}

/**
 * Дата + 1 год. 29 февраля переносится на 28-е — в невисокосном году такой
 * даты нет. Те же правила считает бэкенд (project_creation_defaults.add_one_year):
 * форма лишь показывает результат заранее, доверять ей нельзя.
 */
export function addOneYear(iso: string): string {
  if (!iso) return ''
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return ''
  const nextYear = year + 1
  const daysInMonth = new Date(Date.UTC(nextYear, month, 0)).getUTCDate()
  const safeDay = Math.min(day, daysInMonth)
  return `${nextYear}-${String(month).padStart(2, '0')}-${String(safeDay).padStart(2, '0')}`
}

/** Плановая сумма = часы × ставка. Без часов — null, а не ноль: пустой бюджет
 * это «неизвестно», и ноль в отчёте прочитали бы как факт. */
export function plannedAmount(hours: string, rate: string): number | null {
  const parsedHours = parseFloat(String(hours ?? '').replace(',', '.'))
  const parsedRate = parseFloat(String(rate ?? '').replace(',', '.'))
  if (!Number.isFinite(parsedHours)) return null
  if (!Number.isFinite(parsedRate)) return null
  return Math.round(parsedHours * parsedRate * 100) / 100
}
