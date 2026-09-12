/**
 * Роли и права в интерфейсе.
 *
 * Права решает СЕРВЕР (backends/python/api/main/roles.py): роли хранятся в
 * нашей БД, а не в app.option портала, потому что app.option пишется токеном
 * приложения, то есть из консоли браузера. Здесь только разбор его ответов
 * (GET /api/roles/me, GET /api/roles) и тексты. Скрытая кнопка — забота о
 * человеке, а не защита: запрос можно послать мимо интерфейса, и сервер
 * ответит 403.
 *
 * Ролевая модель — функция `roles` тарифа Pro. Режим берётся из общего
 * состояния подписки (usePaidFeature('roles'), app/utils/featureAccess.ts):
 *  - restrictionsActive = false (тарифа нет или он выключен) — права те же,
 *    что были до ролей: администратор портала может всё, «Бухгалтерия»
 *    выставляет счета и заводит операции, суммы видят все;
 *  - restrictionsActive && canWrite (Pro действует) — права по ролям,
 *    назначать можно любые роли;
 *  - restrictionsActive && !canWrite (Pro закончился) — права ПО-ПРЕЖНЕМУ по
 *    ролям (иначе все разом увидели бы ставки и суммы), но менять роли нельзя
 *    до продления.
 *
 * Всё чистыми функциями без Vue: node:test через tsx не резолвит .vue.
 */

export type RoleCode = 'admin' | 'accountant' | 'project_manager' | 'employee'

export type PermissionCode =
  | 'money_view'
  | 'rates_edit'
  | 'billing_issue'
  | 'billing_cancel'
  | 'operations_create'
  | 'period_close'
  | 'settings_manage'
  | 'roles_manage'

export const ROLE_CODES: RoleCode[] = ['admin', 'accountant', 'project_manager', 'employee']

export const PERMISSION_CODES: PermissionCode[] = [
  'money_view',
  'rates_edit',
  'billing_issue',
  'billing_cancel',
  'operations_create',
  'period_close',
  'settings_manage',
  'roles_manage',
]

/** Адрес экрана ролей. Один на меню, карточку настроек и тексты отказов. */
export const ROLES_SETTINGS_PATH = '/settings/roles'

/** Где искать экран — словами, для текстов отказа. */
export const ROLES_SETTINGS_PLACE = 'Настройки → Роли и права'

/** Подписи ролей, если сервер не прислал каталог (или прислал не всё). */
export const ROLE_TITLES: Record<RoleCode, string> = {
  admin: 'Администратор',
  accountant: 'Бухгалтерия',
  project_manager: 'Руководитель проекта',
  employee: 'Сотрудник',
}

export type RolesMe = {
  /** Права считаются по ролям (сервер: feature_restrictions_active). */
  rolesEnabled: boolean
  /** Pro действует и роли можно менять. */
  subscriptionActive: boolean
  /** Какие роли сервер сейчас разрешает назначать (при праве roles_manage). */
  assignableRoles: RoleCode[]
  role: RoleCode
  roleTitle: string
  isPortalAdmin: boolean
  permissions: Record<PermissionCode, boolean>
}

export type RoleCatalogRole = { code: RoleCode, title: string, description: string }
export type RoleCatalogPermission = { code: PermissionCode, title: string }

export type RolesCatalog = {
  roles: RoleCatalogRole[]
  permissions: RoleCatalogPermission[]
  matrix: Record<RoleCode, PermissionCode[]>
  legacyMatrix: Partial<Record<RoleCode, PermissionCode[]>>
}

export type RoleAssignment = {
  userId: string
  name: string
  role: RoleCode
  roleTitle: string
  isPortalAdmin: boolean
  source: string
  assignedByName: string
}

function isRoleCode(value: unknown): value is RoleCode {
  return typeof value === 'string' && (ROLE_CODES as string[]).includes(value)
}

function isPermissionCode(value: unknown): value is PermissionCode {
  return typeof value === 'string' && (PERMISSION_CODES as string[]).includes(value)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function emptyPermissions(): Record<PermissionCode, boolean> {
  return Object.fromEntries(PERMISSION_CODES.map(code => [code, false])) as Record<PermissionCode, boolean>
}

/**
 * Ответ /api/roles/me. Мусор -> null («права неизвестны»), а не «ничего нельзя»:
 * неизвестное состояние интерфейс трактует по-старому (см. resolveUiPermissions).
 */
export function parseRolesMe(raw: unknown): RolesMe | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const data = asRecord(raw)
  const rawPermissions = asRecord(data.permissions)
  if (!Object.keys(rawPermissions).length) {
    return null
  }

  const permissions = emptyPermissions()
  for (const code of PERMISSION_CODES) {
    permissions[code] = rawPermissions[code] === true
  }

  const role = isRoleCode(data.role) ? data.role : 'employee'

  const rolesEnabled = data.roles_enabled === true
  const subscriptionActive = data.subscription_active === true
  const assignable = Array.isArray(data.assignable_roles)
    ? data.assignable_roles.filter(isRoleCode)
    : fallbackAssignableRoles(subscriptionActive)

  return {
    rolesEnabled,
    subscriptionActive,
    assignableRoles: assignable,
    role,
    roleTitle: String(data.role_title || ROLE_TITLES[role]),
    isPortalAdmin: data.is_portal_admin === true,
    permissions,
  }
}

/**
 * То же правило, что assignable_roles на сервере, — если сервер поле не прислал:
 * менять роли можно только при живом Pro (@feature_required('roles')).
 */
export function fallbackAssignableRoles(canWrite: boolean): RoleCode[] {
  return canWrite ? [...ROLE_CODES] : []
}

/** Ответ /api/roles -> каталог. Неизвестные коды отбрасываются. */
export function parseRolesCatalog(raw: unknown): RolesCatalog {
  const data = asRecord(raw)

  const roles = (Array.isArray(data.roles) ? data.roles : [])
    .map(asRecord)
    .filter(row => isRoleCode(row.code))
    .map(row => ({
      code: row.code as RoleCode,
      title: String(row.title || ROLE_TITLES[row.code as RoleCode]),
      description: String(row.description || ''),
    }))

  const permissions = (Array.isArray(data.permissions) ? data.permissions : [])
    .map(asRecord)
    .filter(row => isPermissionCode(row.code))
    .map(row => ({ code: row.code as PermissionCode, title: String(row.title || row.code) }))

  const readMatrix = (source: unknown): Partial<Record<RoleCode, PermissionCode[]>> => {
    const result: Partial<Record<RoleCode, PermissionCode[]>> = {}
    for (const [role, list] of Object.entries(asRecord(source))) {
      if (isRoleCode(role) && Array.isArray(list)) {
        result[role] = list.filter(isPermissionCode)
      }
    }
    return result
  }

  const matrix = readMatrix(data.matrix)

  return {
    roles,
    permissions,
    matrix: Object.fromEntries(ROLE_CODES.map(code => [code, matrix[code] || []])) as Record<RoleCode, PermissionCode[]>,
    legacyMatrix: readMatrix(data.legacy_matrix),
  }
}

export function parseRoleAssignments(raw: unknown): RoleAssignment[] {
  return (Array.isArray(raw) ? raw : [])
    .map(asRecord)
    .filter(row => String(row.user_id ?? '').trim() && isRoleCode(row.role))
    .map(row => ({
      userId: String(row.user_id).trim(),
      name: String(row.name || '').trim(),
      role: row.role as RoleCode,
      roleTitle: String(row.role_title || ROLE_TITLES[row.role as RoleCode]),
      isPortalAdmin: row.is_portal_admin === true,
      source: String(row.source || ''),
      assignedByName: String(row.assigned_by_name || ''),
    }))
}

export type UiPermissions = Record<PermissionCode, boolean> & {
  /** Права пришли с сервера, а не угаданы. */
  known: boolean
}

/**
 * Права для кнопок.
 *
 * Ответ /api/roles/me побеждает всё: права считает сервер. Пока его нет,
 * угадываем по режиму подписки (restrictionsActive из usePaidFeature('roles')):
 *  - ограничения не действуют — по-старому: админ портала может всё,
 *    остальные видят суммы и ничего не выставляют;
 *  - действуют — админ портала может всё, про остальных не знаем ничего и
 *    не обещаем ничего (known = false: экраны не закрываются по догадке).
 * Ошибка догадки безопасна: лишнюю кнопку сервер отклонит, недостающая
 * появится после ответа.
 */
export function resolveUiPermissions(options: {
  me: RolesMe | null | undefined
  isAdmin: boolean
  restrictionsActive?: boolean
}): UiPermissions {
  if (options.me) {
    return { ...options.me.permissions, known: true }
  }

  const permissions = emptyPermissions()
  if (options.isAdmin) {
    for (const code of PERMISSION_CODES) {
      permissions[code] = true
    }
  } else if (!options.restrictionsActive) {
    permissions.money_view = true
    permissions.rates_edit = true
  }
  return { ...permissions, known: false }
}

/**
 * Можно ли менять настройки приложения на экране настроек.
 *
 * Пока ограничения ролей не действуют — как было: только администратор
 * портала (сервер при этом настройки не закрывал, прятал их интерфейс).
 * Когда действуют — право settings_manage, то есть роль «Администратор»,
 * которую можно дать и не администратору портала.
 */
export function canEditAppSettings(
  me: RolesMe | null | undefined,
  isAdmin: boolean,
  restrictionsActive: boolean
): boolean {
  if (restrictionsActive && me) {
    return me.permissions.settings_manage
  }
  return isAdmin
}

export type RoleMatrixRow = {
  permission: PermissionCode
  title: string
  cells: Array<{ role: RoleCode, allowed: boolean }>
}

/**
 * Таблица «что может роль» — строки права, столбцы роли.
 *
 * Без действующих ограничений показываем то, что ДЕЙСТВУЕТ сейчас (legacy),
 * а не то, что будет после подключения Pro: таблица отвечает на вопрос
 * «почему мне нельзя», и обещание вместо факта сбило бы с толку.
 */
export function buildRoleMatrixRows(catalog: RolesCatalog, restrictionsActive: boolean): RoleMatrixRow[] {
  const source = restrictionsActive ? catalog.matrix : catalog.legacyMatrix
  const roleCodes = catalog.roles.map(role => role.code)

  return catalog.permissions.map(permission => ({
    permission: permission.code,
    title: permission.title,
    cells: roleCodes.map((role) => {
      // Без ролей «Руководитель проекта» ничего не значит — у него права
      // сотрудника. Столбец «Администратор» тогда описывает администраторов
      // портала: назначенная роль без тарифа не действует.
      const effectiveRole: RoleCode = !restrictionsActive && role === 'project_manager' ? 'employee' : role
      const list = source[effectiveRole] || []
      return { role, allowed: list.includes(permission.code) }
    }),
  }))
}

export type RoleOption = { value: RoleCode, label: string, disabled: boolean }

/**
 * Варианты роли в выпадающем списке назначения.
 *
 * Какие роли можно назначать, решает сервер (assignable_roles: при живом Pro —
 * все, иначе — ни одной). Недоступные гаснут, а не пропадают: текущая роль
 * человека должна остаться видна в списке.
 */
export function buildRoleOptions(catalog: RolesCatalog, assignableRoles: RoleCode[]): RoleOption[] {
  const roles = catalog.roles.length
    ? catalog.roles
    : ROLE_CODES.map(code => ({ code, title: ROLE_TITLES[code], description: '' }))

  return roles.map(role => ({
    value: role.code,
    label: role.title,
    disabled: !assignableRoles.includes(role.code),
  }))
}

/** Режим ролевой модели — из общего состояния подписки (FeatureAccess). */
export type RolesModeInput = {
  restrictionsActive: boolean
  canWrite: boolean
  /** Статус тарифа: active | grace | trial | expired | off. */
  status?: string
}

/** Пояснение над экраном ролей: что сейчас действует. */
export function describeRolesMode(mode: RolesModeInput | null | undefined): { tone: 'info' | 'warning', text: string } {
  if (!mode) {
    return {
      tone: 'info',
      text: 'Проверяем тариф портала…',
    }
  }
  if (mode.restrictionsActive && mode.canWrite) {
    const trial = mode.status === 'trial' ? ' Идёт пробный период Pro.' : ''
    return {
      tone: 'info',
      text: 'Ролевая модель действует: права определяются ролями из таблицы ниже. '
        + 'Администраторы портала всегда имеют роль «Администратор», остальным без назначенной роли '
        + 'достаётся «Сотрудник».' + trial,
    }
  }
  if (mode.restrictionsActive) {
    return {
      tone: 'warning',
      text: 'Тариф Pro закончился. Назначенные роли продолжают действовать — сотрудники без роли по-прежнему '
        + 'не видят ставок и сумм, — но менять роли нельзя, пока Pro не продлён.',
    }
  }
  return {
    tone: 'warning',
    text: 'Ролевая модель входит в тариф Pro и на портале не подключена. Сейчас действуют прежние права: '
      + 'администратор портала может всё, «Бухгалтерия» выставляет счета и заводит начисления и списания, '
      + 'суммы видят все сотрудники. Назначать роли можно после подключения Pro.',
  }
}

/** Короткая пометка режима — бейдж рядом с заголовком. */
export function rolesModeBadge(mode: RolesModeInput | null | undefined): string {
  if (!mode) {
    return 'проверяем'
  }
  if (mode.restrictionsActive && mode.canWrite) {
    return mode.status === 'trial' ? 'пробный Pro' : 'действуют'
  }
  return mode.restrictionsActive ? 'Pro закончился' : 'в тарифе Pro'
}

/** Какие роли дают право — словами, для текстов отказа. */
export function rolesAllowing(catalog: RolesCatalog | null | undefined, permission: PermissionCode): string[] {
  const matrix = catalog?.matrix
  const codes = matrix
    ? ROLE_CODES.filter(code => (matrix[code] || []).includes(permission))
    : DEFAULT_ALLOWED_ROLES[permission]
  return codes.map(code => ROLE_TITLES[code])
}

/** Совпадает с ROLE_PERMISSIONS сервера — нужен, пока каталог не загружен. */
const DEFAULT_ALLOWED_ROLES: Record<PermissionCode, RoleCode[]> = {
  money_view: ['admin', 'accountant', 'project_manager'],
  rates_edit: ['admin', 'accountant'],
  billing_issue: ['admin', 'accountant'],
  billing_cancel: ['admin', 'accountant'],
  operations_create: ['admin', 'accountant'],
  period_close: ['admin', 'accountant'],
  settings_manage: ['admin'],
  roles_manage: ['admin'],
}

function joinRoles(titles: string[]): string {
  const quoted = titles.map(title => `«${title}»`)
  if (quoted.length <= 1) {
    return quoted.join('')
  }
  return `${quoted.slice(0, -1).join(', ')} или ${quoted[quoted.length - 1]}`
}

/**
 * Почему нет доступа к экрану с суммами. Текст зависит от режима: без ролей
 * такого отказа не бывает (суммы видят все), поэтому он всегда про роли.
 */
export function describeMoneyAccessDenied(catalog?: RolesCatalog | null): string {
  return `Суммы — счета и акты, бюджеты проектов, начисления и списания — видят роли ${joinRoles(rolesAllowing(catalog, 'money_view'))}. `
    + `Если они нужны вам для работы, попросите администратора приложения назначить роль: ${ROLES_SETTINGS_PLACE}.`
}

/** Почему нельзя добавить начисление или списание. */
export function describeOperationsNoRights(restrictionsActive: boolean, catalog?: RolesCatalog | null): string {
  if (restrictionsActive) {
    return `Добавлять начисления и списания могут роли ${joinRoles(rolesAllowing(catalog, 'operations_create'))}. `
      + `Роли назначает администратор приложения: ${ROLES_SETTINGS_PLACE}.`
  }
  return 'Добавлять начисления и списания может администратор портала или сотрудник с ролью «Бухгалтерия» '
    + `(${ROLES_SETTINGS_PLACE}). Смотреть операции может любой, у кого открыт раздел.`
}

export type RoleUserRow = {
  userId: string
  name: string
  role: RoleCode
  roleTitle: string
  isPortalAdmin: boolean
}

/**
 * Строки таблицы назначения: найденные сотрудники с их текущей ролью.
 *
 * Роль берётся из назначений, а не из справочника сотрудников: справочник про
 * роли не знает. Администратор портала узнаётся по назначениям — сервер
 * отдаёт его отдельной строкой, и менять ему роль нельзя.
 */
export function mergeUsersWithRoles(
  users: Array<{ id: string | number, name?: string, last_name?: string }>,
  assignments: RoleAssignment[]
): RoleUserRow[] {
  const byId = new Map(assignments.map(row => [row.userId, row]))

  return users.map((user) => {
    const userId = String(user.id)
    const assignment = byId.get(userId)
    const name = [user.last_name, user.name].filter(Boolean).join(' ').trim() || assignment?.name || `Сотрудник #${userId}`
    const role = assignment?.role || 'employee'
    return {
      userId,
      name,
      role,
      roleTitle: assignment?.roleTitle || ROLE_TITLES[role],
      isPortalAdmin: Boolean(assignment?.isPortalAdmin),
    }
  })
}

/** Подпись назначения в списке «кто в какой роли». */
export function describeAssignment(row: RoleAssignment): string {
  if (row.isPortalAdmin) {
    return 'администратор портала — роль не меняется'
  }
  if (row.source === 'billing_accountants') {
    return 'перенесено из прежнего списка «Бухгалтерия»'
  }
  return row.assignedByName ? `назначил(а) ${row.assignedByName}` : ''
}

/** Отказ сервера при назначении — человеческим текстом. */
export function describeRoleAssignError(error: unknown): string {
  const data = asRecord(asRecord(error).data)
  // Общий клиент $api на 403 подменяет ошибку голым Error с текстом сервера
  // (app/stores/api.ts), поэтому текст берём и из тела, и из сообщения.
  const fromError = error instanceof Error && !/^\[[A-Z]+\]/.test(error.message) ? error.message : ''
  const message = String(data.error || fromError || '').trim()
  if (data.code === 'feature_disabled' || /не подключена/i.test(message)) {
    return 'Менять роли можно при действующем тарифе Pro. Когда он закончился, назначенные роли продолжают '
      + 'действовать, но не меняются до продления.'
  }
  if (message) {
    return message
  }
  return 'Не удалось сохранить роль. Попробуйте ещё раз.'
}
