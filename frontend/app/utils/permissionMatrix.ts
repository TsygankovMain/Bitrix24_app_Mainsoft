/**
 * Редактор прав ролей — экран «Роли и права» (/settings/roles).
 *
 * Матрицу портала хранит и проверяет СЕРВЕР (backends/python/api/main/roles.py,
 * PortalPermissionMatrix): неизменяемые ячейки, зависимости прав и неизвестные
 * права он отклоняет сам. Здесь — черновик на экране и забота о человеке:
 *  - включил зависимое право — базовое включается само, выключил базовое —
 *    зависимые выключаются, и экран говорит, что и почему поменял;
 *  - закреплённые ячейки видны, но не переключаются, с объяснением;
 *  - до сохранения видно, что именно изменится;
 *  - «вернуть по умолчанию» для роли и для всей таблицы меняет черновик, а не
 *    сохраняет сразу: результат тоже сначала виден в предпросмотре.
 *
 * Правила (зависимости, закреплённые ячейки, матрица по умолчанию) приходят с
 * сервера в каталоге /api/roles. Константы ниже — запасной вариант на случай
 * неполного ответа и совпадают с сервером.
 *
 * Работа с часами — списание времени, отчёты, доска проектов, проверка данных —
 * правами не описывается и в таблице не появляется (урок июня 2026).
 *
 * Всё чистыми функциями без Vue: node:test через tsx не резолвит .vue.
 */

import {
  PERMISSION_CODES,
  ROLE_CODES,
  ROLE_TITLES,
  type PermissionCode,
  type RoleCode,
} from './appRoles'

export type PermissionMatrix = Record<RoleCode, PermissionCode[]>

export type MatrixRole = { code: RoleCode, title: string, description: string, customized: boolean }

export type MatrixPermission = {
  code: PermissionCode
  title: string
  description: string
  group: string
  requires: PermissionCode[]
  requiresReason: string
}

export type MatrixGroup = { code: string, title: string, permissions: PermissionCode[] }

export type MatrixLock = { role: RoleCode, permission: PermissionCode, value: boolean, reason: string }

export type MatrixEditorData = {
  roles: MatrixRole[]
  permissions: MatrixPermission[]
  groups: MatrixGroup[]
  locks: MatrixLock[]
  alwaysOpen: string[]
  /** Действующая матрица портала. */
  matrix: PermissionMatrix
  defaultMatrix: PermissionMatrix
  /** Версия сохранённой матрицы: сервер отклонит сохранение поверх чужой правки. */
  revision: number
  updatedAt: string | null
  updatedByName: string
}

export type MatrixChange = { role: RoleCode, permission: PermissionCode, granted: boolean }

export type MatrixLogEntry = {
  revision: number
  changedAt: string | null
  changedByName: string
  resetToDefault: boolean
  changes: Array<MatrixChange & { roleTitle: string, permissionTitle: string }>
}

/** Совпадает с ROLE_PERMISSIONS сервера. */
export const DEFAULT_PERMISSION_MATRIX: PermissionMatrix = {
  admin: [...PERMISSION_CODES],
  accountant: ['money_view', 'rates_edit', 'billing_issue', 'billing_cancel', 'operations_create', 'period_close'],
  project_manager: ['money_view'],
  employee: [],
}

/** Совпадает с PERMISSION_REQUIRES сервера. */
export const PERMISSION_REQUIRES: Partial<Record<PermissionCode, PermissionCode[]>> = {
  rates_edit: ['money_view'],
  billing_issue: ['money_view'],
  billing_cancel: ['money_view'],
  operations_create: ['money_view'],
}

const ROLES_MANAGE_ONLY_ADMIN = 'Назначать роли и менять права может только «Администратор»: с этим правом любая роль '
  + 'назначила бы себе «Администратора» и получила бы всё.'

/** Совпадает с LOCKED_CELLS сервера. */
export const FALLBACK_LOCKS: MatrixLock[] = [
  {
    role: 'admin',
    permission: 'settings_manage',
    value: true,
    reason: 'У «Администратора» право менять настройки не снимается: иначе на портале не останется никого, '
      + 'кто может их поправить.',
  },
  {
    role: 'admin',
    permission: 'roles_manage',
    value: true,
    reason: 'У «Администратора» право назначать роли не снимается: иначе портал запер бы сам себя — '
      + 'вернуть права было бы некому.',
  },
  { role: 'accountant', permission: 'roles_manage', value: false, reason: ROLES_MANAGE_ONLY_ADMIN },
  { role: 'project_manager', permission: 'roles_manage', value: false, reason: ROLES_MANAGE_ONLY_ADMIN },
  { role: 'employee', permission: 'roles_manage', value: false, reason: ROLES_MANAGE_ONLY_ADMIN },
]

export const FALLBACK_PERMISSION_TITLES: Record<PermissionCode, string> = {
  money_view: 'Видеть суммы: счета и акты, БДДС, начисления и списания',
  rates_edit: 'Менять ставку проекта',
  billing_issue: 'Выставлять счета, печатать счета и акты',
  billing_cancel: 'Отменять счета',
  operations_create: 'Добавлять начисления и списания',
  period_close: 'Закрывать и переоткрывать месяц, исправлять находки проверки',
  settings_manage: 'Менять настройки приложения и сопоставление полей',
  roles_manage: 'Назначать роли',
}

export const FALLBACK_GROUPS: MatrixGroup[] = [
  { code: 'money', title: 'Суммы и ставки', permissions: ['money_view', 'rates_edit'] },
  { code: 'billing', title: 'Счета и акты', permissions: ['billing_issue', 'billing_cancel'] },
  { code: 'operations', title: 'Начисления и списания', permissions: ['operations_create'] },
  { code: 'period', title: 'Закрытие месяца', permissions: ['period_close'] },
  { code: 'admin', title: 'Управление приложением', permissions: ['settings_manage', 'roles_manage'] },
]

export const FALLBACK_ALWAYS_OPEN = [
  'Списание времени в задачах',
  'Отчёты по часам',
  'Доска проектов',
  'Проверка данных (просмотр)',
]

function isRoleCode(value: unknown): value is RoleCode {
  return typeof value === 'string' && (ROLE_CODES as string[]).includes(value)
}

function isPermissionCode(value: unknown): value is PermissionCode {
  return typeof value === 'string' && (PERMISSION_CODES as string[]).includes(value)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

/** Права роли — без повторов и в порядке строк таблицы. */
function orderPermissions(list: Iterable<PermissionCode>): PermissionCode[] {
  const set = new Set(list)
  return PERMISSION_CODES.filter(code => set.has(code))
}

export function cloneMatrix(matrix: PermissionMatrix): PermissionMatrix {
  return Object.fromEntries(ROLE_CODES.map(role => [role, orderPermissions(matrix[role] || [])])) as PermissionMatrix
}

/** Матрица из ответа сервера. Неизвестные роли и права отбрасываются. */
export function parsePermissionMatrix(raw: unknown, fallback: PermissionMatrix = DEFAULT_PERMISSION_MATRIX): PermissionMatrix {
  const data = asRecord(raw)
  const hasAny = ROLE_CODES.some(role => Array.isArray(data[role]))
  if (!hasAny) {
    return cloneMatrix(fallback)
  }
  return Object.fromEntries(ROLE_CODES.map((role) => {
    const list = Array.isArray(data[role]) ? (data[role] as unknown[]).filter(isPermissionCode) : []
    return [role, orderPermissions(list)]
  })) as PermissionMatrix
}

/** Каталог /api/roles -> данные редактора. */
export function parseMatrixEditor(raw: unknown): MatrixEditorData {
  const data = asRecord(raw)

  const permissionsRaw = (Array.isArray(data.permissions) ? data.permissions : []).map(asRecord)
  const permissions: MatrixPermission[] = PERMISSION_CODES.map((code) => {
    const row = permissionsRaw.find(item => item.code === code) || {}
    const requires = Array.isArray(row.requires)
      ? row.requires.filter(isPermissionCode)
      : [...(PERMISSION_REQUIRES[code] || [])]
    return {
      code,
      title: String(row.title || FALLBACK_PERMISSION_TITLES[code]),
      description: String(row.description || ''),
      group: String(row.group || FALLBACK_GROUPS.find(group => group.permissions.includes(code))?.code || ''),
      requires,
      requiresReason: String(row.requires_reason || ''),
    }
  })

  const groupsRaw = (Array.isArray(data.groups) ? data.groups : []).map(asRecord)
  const groups: MatrixGroup[] = groupsRaw.length
    ? groupsRaw
        .map(row => ({
          code: String(row.code || ''),
          title: String(row.title || ''),
          permissions: (Array.isArray(row.permissions) ? row.permissions : []).filter(isPermissionCode),
        }))
        .filter(group => group.code && group.permissions.length)
    : FALLBACK_GROUPS.map(group => ({ ...group, permissions: [...group.permissions] }))

  const locksRaw = Array.isArray(data.locks) ? data.locks.map(asRecord) : null
  const locks: MatrixLock[] = locksRaw
    ? locksRaw
        .filter(row => isRoleCode(row.role) && isPermissionCode(row.permission) && typeof row.value === 'boolean')
        .map(row => ({
          role: row.role as RoleCode,
          permission: row.permission as PermissionCode,
          value: row.value as boolean,
          reason: String(row.reason || ''),
        }))
    : FALLBACK_LOCKS.map(lock => ({ ...lock }))

  const defaultMatrix = parsePermissionMatrix(data.default_matrix)
  const matrix = parsePermissionMatrix(data.matrix, defaultMatrix)

  const rolesRaw = (Array.isArray(data.roles) ? data.roles : []).map(asRecord).filter(row => isRoleCode(row.code))
  const roles: MatrixRole[] = (rolesRaw.length ? rolesRaw : ROLE_CODES.map(code => ({ code }) as Record<string, unknown>))
    .map((row) => {
      const code = row.code as RoleCode
      return {
        code,
        title: String(row.title || ROLE_TITLES[code]),
        description: String(row.description || ''),
        customized: typeof row.customized === 'boolean'
          ? row.customized
          : !samePermissions(matrix[code], defaultMatrix[code]),
      }
    })

  const alwaysOpen = Array.isArray(data.always_open) && data.always_open.length
    ? data.always_open.map(item => String(item))
    : [...FALLBACK_ALWAYS_OPEN]

  const revision = Number(data.revision)

  return {
    roles,
    permissions,
    groups,
    locks,
    alwaysOpen,
    matrix,
    defaultMatrix,
    revision: Number.isFinite(revision) && revision >= 0 ? revision : 0,
    updatedAt: typeof data.updated_at === 'string' ? data.updated_at : null,
    updatedByName: String(data.updated_by_name || ''),
  }
}

/** Журнал /api/roles (matrix_log). */
export function parseMatrixLog(raw: unknown): MatrixLogEntry[] {
  return (Array.isArray(raw) ? raw : [])
    .map(asRecord)
    .map(row => ({
      revision: Number(row.revision) || 0,
      changedAt: typeof row.changed_at === 'string' ? row.changed_at : null,
      changedByName: String(row.changed_by_name || ''),
      resetToDefault: row.reset_to_default === true,
      changes: (Array.isArray(row.changes) ? row.changes : [])
        .map(asRecord)
        .filter(change => isRoleCode(change.role) && isPermissionCode(change.permission))
        .map(change => ({
          role: change.role as RoleCode,
          permission: change.permission as PermissionCode,
          granted: change.granted === true,
          roleTitle: String(change.role_title || ROLE_TITLES[change.role as RoleCode]),
          permissionTitle: String(change.permission_title || FALLBACK_PERMISSION_TITLES[change.permission as PermissionCode]),
        })),
    }))
}

function samePermissions(a: PermissionCode[] = [], b: PermissionCode[] = []): boolean {
  const left = orderPermissions(a)
  const right = orderPermissions(b)
  return left.length === right.length && left.every((code, index) => code === right[index])
}

export function matricesEqual(a: PermissionMatrix, b: PermissionMatrix): boolean {
  return ROLE_CODES.every(role => samePermissions(a[role], b[role]))
}

export function hasCell(matrix: PermissionMatrix, role: RoleCode, permission: PermissionCode): boolean {
  return (matrix[role] || []).includes(permission)
}

export function permissionTitle(data: MatrixEditorData | null | undefined, code: PermissionCode): string {
  return data?.permissions.find(row => row.code === code)?.title || FALLBACK_PERMISSION_TITLES[code]
}

export function roleTitle(data: MatrixEditorData | null | undefined, code: RoleCode): string {
  return data?.roles.find(row => row.code === code)?.title || ROLE_TITLES[code]
}

function requiresOf(data: MatrixEditorData, code: PermissionCode): PermissionCode[] {
  return data.permissions.find(row => row.code === code)?.requires || PERMISSION_REQUIRES[code] || []
}

/** Права, которые не работают без данного (прямо или через цепочку). */
export function dependentsOf(data: MatrixEditorData, code: PermissionCode): PermissionCode[] {
  const result = new Set<PermissionCode>()
  const queue: PermissionCode[] = [code]
  while (queue.length) {
    const base = queue.shift() as PermissionCode
    for (const row of data.permissions) {
      if (requiresOf(data, row.code).includes(base) && !result.has(row.code) && row.code !== code) {
        result.add(row.code)
        queue.push(row.code)
      }
    }
  }
  return orderPermissions(result)
}

/** Базовые права, без которых данное не работает (прямо или через цепочку). */
export function requirementsOf(data: MatrixEditorData, code: PermissionCode): PermissionCode[] {
  const result = new Set<PermissionCode>()
  const queue: PermissionCode[] = [...requiresOf(data, code)]
  while (queue.length) {
    const base = queue.shift() as PermissionCode
    if (result.has(base) || base === code) {
      continue
    }
    result.add(base)
    queue.push(...requiresOf(data, base))
  }
  return orderPermissions(result)
}

export function findLock(data: MatrixEditorData, role: RoleCode, permission: PermissionCode): MatrixLock | null {
  return data.locks.find(lock => lock.role === role && lock.permission === permission) || null
}

export type AutoChange = MatrixChange & { reason: string }

export type ToggleResult = {
  matrix: PermissionMatrix
  /** Что поменялось само, кроме нажатой ячейки, и почему. */
  auto: AutoChange[]
  /** Переключение невозможно — объяснение; matrix тогда прежняя. */
  blocked: string
}

/**
 * Переключить ячейку черновика с учётом зависимостей и закреплённых ячеек.
 *
 * Включили зависимое право — включаются базовые. Выключили базовое —
 * выключаются зависимые. Закреплённую ячейку (или если цепочка задела бы
 * закреплённую) переключить нельзя: возвращается объяснение.
 */
export function togglePermission(
  data: MatrixEditorData,
  draft: PermissionMatrix,
  role: RoleCode,
  permission: PermissionCode,
  granted: boolean
): ToggleResult {
  const unchanged = { matrix: cloneMatrix(draft), auto: [] as AutoChange[] }
  const lock = findLock(data, role, permission)
  if (lock && lock.value !== granted) {
    return { ...unchanged, blocked: lock.reason }
  }

  const current = new Set(draft[role] || [])
  const auto: AutoChange[] = []
  const title = (code: PermissionCode) => `«${permissionTitle(data, code)}»`

  if (granted) {
    current.add(permission)
    for (const base of requirementsOf(data, permission)) {
      if (current.has(base)) {
        continue
      }
      const baseLock = findLock(data, role, base)
      if (baseLock && !baseLock.value) {
        return { ...unchanged, blocked: baseLock.reason }
      }
      current.add(base)
      auto.push({
        role,
        permission: base,
        granted: true,
        reason: `${title(permission)} не работает без ${title(base)} — включили и его.`,
      })
    }
  } else {
    current.delete(permission)
    for (const dependent of dependentsOf(data, permission)) {
      if (!current.has(dependent)) {
        continue
      }
      const dependentLock = findLock(data, role, dependent)
      if (dependentLock && dependentLock.value) {
        return { ...unchanged, blocked: dependentLock.reason }
      }
      current.delete(dependent)
      auto.push({
        role,
        permission: dependent,
        granted: false,
        reason: `Без ${title(permission)} не работает ${title(dependent)} — выключили и его.`,
      })
    }
  }

  const matrix = cloneMatrix(draft)
  matrix[role] = orderPermissions(current)
  return { matrix, auto, blocked: '' }
}

/** Ячейки, которые отличаются, — в порядке ролей и строк таблицы. */
export function diffMatrices(before: PermissionMatrix, after: PermissionMatrix): MatrixChange[] {
  const changes: MatrixChange[] = []
  for (const role of ROLE_CODES) {
    for (const permission of PERMISSION_CODES) {
      const was = hasCell(before, role, permission)
      const now = hasCell(after, role, permission)
      if (was !== now) {
        changes.push({ role, permission, granted: now })
      }
    }
  }
  return changes
}

export function resetRoleToDefault(data: MatrixEditorData, draft: PermissionMatrix, role: RoleCode): PermissionMatrix {
  const matrix = cloneMatrix(draft)
  matrix[role] = orderPermissions(data.defaultMatrix[role] || [])
  return matrix
}

export function resetAllToDefault(data: MatrixEditorData): PermissionMatrix {
  return cloneMatrix(data.defaultMatrix)
}

export function isRoleAtDefault(data: MatrixEditorData, draft: PermissionMatrix, role: RoleCode): boolean {
  return samePermissions(draft[role], data.defaultMatrix[role])
}

export type MatrixCellView = {
  checked: boolean
  /** Отличается от сохранённого — подсветка несохранённой правки. */
  changed: boolean
  locked: boolean
  lockReason: string
  /** Отличается от значения по умолчанию. */
  customized: boolean
}

export function matrixCellView(
  data: MatrixEditorData,
  saved: PermissionMatrix,
  draft: PermissionMatrix,
  role: RoleCode,
  permission: PermissionCode
): MatrixCellView {
  const checked = hasCell(draft, role, permission)
  const lock = findLock(data, role, permission)
  return {
    checked,
    changed: checked !== hasCell(saved, role, permission),
    locked: Boolean(lock),
    lockReason: lock?.reason || '',
    customized: checked !== hasCell(data.defaultMatrix, role, permission),
  }
}

export type MatrixSection = { code: string, title: string, rows: MatrixPermission[] }

/** Строки таблицы по группам. Право без группы попадает в последнюю «Прочее». */
export function buildMatrixSections(data: MatrixEditorData): MatrixSection[] {
  const byCode = new Map(data.permissions.map(row => [row.code, row]))
  const placed = new Set<PermissionCode>()
  const sections: MatrixSection[] = data.groups.map((group) => {
    const rows = group.permissions
      .map(code => byCode.get(code))
      .filter((row): row is MatrixPermission => Boolean(row) && !placed.has((row as MatrixPermission).code))
    rows.forEach(row => placed.add(row.code))
    return { code: group.code, title: group.title, rows }
  }).filter(section => section.rows.length)

  const rest = data.permissions.filter(row => !placed.has(row.code))
  if (rest.length) {
    sections.push({ code: 'other', title: 'Прочее', rows: rest })
  }
  return sections
}

/** Подсказка под правом: без чего оно не работает. */
export function describeRequirement(data: MatrixEditorData, code: PermissionCode): string {
  const bases = requirementsOf(data, code)
  if (!bases.length) {
    return ''
  }
  const row = data.permissions.find(item => item.code === code)
  const list = bases.map(base => `«${permissionTitle(data, base)}»`).join(', ')
  const reason = row?.requiresReason ? `: ${row.requiresReason}` : ''
  return `Работает только вместе с ${list}${reason}.`
}

/** Уникальные объяснения закреплённых ячеек — легенда под таблицей. */
export function describeLocks(data: MatrixEditorData): string[] {
  return [...new Set(data.locks.map(lock => lock.reason).filter(Boolean))]
}

export type RoleChangeSummary = { role: RoleCode, title: string, granted: string[], revoked: string[] }

/** Предпросмотр: изменения, сгруппированные по ролям. */
export function summarizeChanges(data: MatrixEditorData, changes: MatrixChange[]): RoleChangeSummary[] {
  return ROLE_CODES
    .map((role) => {
      const own = changes.filter(change => change.role === role)
      return {
        role,
        title: roleTitle(data, role),
        granted: own.filter(change => change.granted).map(change => permissionTitle(data, change.permission)),
        revoked: own.filter(change => !change.granted).map(change => permissionTitle(data, change.permission)),
      }
    })
    .filter(summary => summary.granted.length || summary.revoked.length)
}

export function describeRoleChange(summary: RoleChangeSummary): string {
  const parts: string[] = []
  if (summary.granted.length) {
    parts.push(`получит ${summary.granted.map(title => `«${title}»`).join(', ')}`)
  }
  if (summary.revoked.length) {
    parts.push(`потеряет ${summary.revoked.map(title => `«${title}»`).join(', ')}`)
  }
  return `${summary.title}: ${parts.join('; ')}.`
}

/** Сколько ячеек поменяется — «3 изменения». */
export function pluralChanges(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  const word = mod10 === 1 && mod100 !== 11
    ? 'изменение'
    : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? 'изменения' : 'изменений'
  return `${count} ${word}`
}

/** Дата журнала: 12.09.2026 14:05 по времени браузера. */
export function formatLogDate(value: string | null): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ''
  }
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Строки записи журнала. */
export function describeLogEntry(entry: MatrixLogEntry): { title: string, lines: string[] } {
  const who = entry.changedByName || 'Сотрудник без имени в справочнике'
  const when = formatLogDate(entry.changedAt)
  const title = [when, who].filter(Boolean).join(' · ')
  if (entry.resetToDefault) {
    return { title, lines: ['Все права возвращены к значениям по умолчанию.'] }
  }
  const byRole = new Map<string, { granted: string[], revoked: string[] }>()
  for (const change of entry.changes) {
    const bucket = byRole.get(change.roleTitle) || { granted: [], revoked: [] }
    ;(change.granted ? bucket.granted : bucket.revoked).push(`«${change.permissionTitle}»`)
    byRole.set(change.roleTitle, bucket)
  }
  const lines = [...byRole.entries()].map(([role, bucket]) => {
    const parts: string[] = []
    if (bucket.granted.length) {
      parts.push(`включено ${bucket.granted.join(', ')}`)
    }
    if (bucket.revoked.length) {
      parts.push(`выключено ${bucket.revoked.join(', ')}`)
    }
    return `${role}: ${parts.join('; ')}.`
  })
  return { title, lines }
}

export type MatrixEditMode = { editable: boolean, reason: string }

/**
 * Можно ли править таблицу и почему нет.
 *
 * Условие то же, что у назначения ролей: право roles_manage (роль
 * «Администратор») и живой Pro. После окончания Pro сохранённые права
 * действуют, но не меняются.
 */
export function matrixEditMode(options: {
  canManage: boolean
  restrictionsActive: boolean
  canWrite: boolean
  unknown?: boolean
}): MatrixEditMode {
  if (options.unknown) {
    return { editable: false, reason: '' }
  }
  if (!options.restrictionsActive) {
    return {
      editable: false,
      reason: 'Настраивать права ролей можно после подключения тарифа Pro. Сейчас действуют прежние права.',
    }
  }
  if (!options.canWrite) {
    return {
      editable: false,
      reason: 'Тариф Pro закончился: сохранённые права ролей продолжают действовать, но менять их можно будет '
        + 'после продления.',
    }
  }
  if (!options.canManage) {
    return {
      editable: false,
      reason: 'Менять права ролей может роль «Администратор». Таблица показывает, что действует сейчас.',
    }
  }
  return { editable: true, reason: '' }
}

/** Отказ сервера при сохранении — человеческим текстом. */
export function describeMatrixSaveError(error: unknown): { text: string, conflict: boolean } {
  const data = asRecord(asRecord(error).data)
  const fromError = error instanceof Error && !/^\[[A-Z]+\]/.test(error.message) ? error.message : ''
  const message = String(data.error || fromError || '').trim()
  if (data.code === 'matrix_conflict') {
    return {
      text: message || 'Права ролей уже поменял другой человек. Загрузили свежую таблицу — повторите изменения.',
      conflict: true,
    }
  }
  if (data.code === 'feature_disabled' || /не подключена/i.test(message)) {
    return {
      text: 'Менять права ролей можно при действующем тарифе Pro. Когда он закончился, сохранённые права '
        + 'продолжают действовать, но не меняются до продления.',
      conflict: false,
    }
  }
  return { text: message || 'Не удалось сохранить права. Попробуйте ещё раз.', conflict: false }
}
