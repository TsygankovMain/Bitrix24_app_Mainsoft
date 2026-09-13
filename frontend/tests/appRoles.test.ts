import test from 'node:test'
import assert from 'node:assert/strict'

import {
  PERMISSION_CODES,
  ROLES_SETTINGS_PATH,
  buildRoleMatrixRows,
  buildRoleOptions,
  canEditAppSettings,
  describeAssignment,
  describeMoneyAccessDenied,
  describeOperationsNoRights,
  describeRoleAssignError,
  describeRolesMode,
  fallbackAssignableRoles,
  mergeUsersWithRoles,
  parseRoleAssignments,
  parseRolesCatalog,
  parseRolesMe,
  resolveUiPermissions,
  rolesAllowing,
  rolesModeBadge,
} from '../app/utils/appRoles'
import { SETTINGS_NAV_GROUPS } from '../app/utils/appNavigation'

// Ответ сервера (main/roles.py, roles_catalog) — в том виде, в каком он приходит.
const SERVER_CATALOG = {
  roles: [
    { code: 'admin', title: 'Администратор', description: 'Всё' },
    { code: 'accountant', title: 'Бухгалтерия', description: 'Деньги' },
    { code: 'project_manager', title: 'Руководитель проекта', description: 'Видит суммы' },
    { code: 'employee', title: 'Сотрудник', description: 'Часы' },
  ],
  permissions: PERMISSION_CODES.map(code => ({ code, title: `право ${code}` })),
  matrix: {
    admin: [...PERMISSION_CODES],
    accountant: ['billing_cancel', 'billing_issue', 'money_view', 'operations_create', 'period_close', 'rates_edit'],
    project_manager: ['money_view'],
    employee: [],
  },
  legacy_matrix: {
    admin: [...PERMISSION_CODES],
    accountant: ['billing_cancel', 'billing_issue', 'money_view', 'operations_create', 'rates_edit', 'settings_manage'],
    employee: ['money_view', 'rates_edit', 'settings_manage'],
  },
}

function meFor(role: string, enabled: boolean, allowed: string[], subscription = enabled) {
  return parseRolesMe({
    roles_enabled: enabled,
    subscription_active: subscription,
    role,
    role_title: role,
    is_portal_admin: false,
    permissions: Object.fromEntries(PERMISSION_CODES.map(code => [code, allowed.includes(code)])),
    feature: { state: enabled ? 'on' : 'off', trial_until: null },
  })
}

test('parseRolesMe: разбирает ответ и не верит мусору', () => {
  const me = meFor('accountant', true, ['money_view', 'billing_issue'])
  assert.ok(me)
  assert.equal(me.rolesEnabled, true)
  assert.equal(me.permissions.money_view, true)
  assert.equal(me.permissions.settings_manage, false)

  assert.equal(parseRolesMe(null), null)
  assert.equal(parseRolesMe({ role: 'admin' }), null, 'без прав — «неизвестно», а не «ничего нельзя»')
  const strange = parseRolesMe({ role: 'boss', permissions: { money_view: 'yes', billing_issue: true } })
  assert.equal(strange?.role, 'employee')
  assert.equal(strange?.permissions.money_view, false, 'только true — это true')
  assert.deepEqual(strange?.assignableRoles, [], 'без живого Pro роли не меняются')
})

test('resolveUiPermissions: ответ сервера побеждает догадку', () => {
  const me = meFor('project_manager', true, ['money_view'])
  const permissions = resolveUiPermissions({ me, isAdmin: true })
  assert.equal(permissions.known, true)
  assert.equal(permissions.billing_issue, false)
  assert.equal(permissions.money_view, true)
})

test('resolveUiPermissions: без ответа — прежние права по признаку админа', () => {
  const admin = resolveUiPermissions({ me: null, isAdmin: true })
  assert.equal(admin.known, false)
  assert.ok(PERMISSION_CODES.every(code => admin[code]))

  const employee = resolveUiPermissions({ me: null, isAdmin: false })
  assert.equal(employee.money_view, true, 'без ролей суммы видят все')
  assert.equal(employee.billing_issue, false)
  assert.equal(employee.operations_create, false)
  assert.equal(employee.settings_manage, false)
})

test('resolveUiPermissions: при действующих ролях догадка ничего не обещает сотруднику', () => {
  const employee = resolveUiPermissions({ me: null, isAdmin: false, restrictionsActive: true })
  assert.equal(employee.known, false)
  assert.equal(employee.money_view, false)
  assert.equal(resolveUiPermissions({ me: null, isAdmin: true, restrictionsActive: true }).money_view, true)
})

test('canEditAppSettings: без ролей — админ портала, с ролями — право settings_manage', () => {
  const legacy = meFor('employee', false, ['money_view', 'rates_edit', 'settings_manage'])
  assert.equal(canEditAppSettings(legacy, false, false), false, 'без ролей интерфейс настроек — только для админа портала, как было')
  assert.equal(canEditAppSettings(null, true, false), true)

  assert.equal(canEditAppSettings(meFor('admin', true, [...PERMISSION_CODES]), false, true), true)
  assert.equal(canEditAppSettings(meFor('accountant', true, ['money_view']), true, true), false)
  assert.equal(canEditAppSettings(null, true, true), true, 'пока права не пришли — по признаку админа')
})

test('parseRolesCatalog: неизвестные роли и права отбрасываются, матрица полная', () => {
  const catalog = parseRolesCatalog({
    ...SERVER_CATALOG,
    roles: [...SERVER_CATALOG.roles, { code: 'boss', title: 'Босс' }],
    matrix: { ...SERVER_CATALOG.matrix, employee: ['fly'] },
  })
  assert.equal(catalog.roles.length, 4)
  assert.deepEqual(catalog.matrix.employee, [])

  const empty = parseRolesCatalog(null)
  assert.deepEqual(empty.roles, [])
  assert.deepEqual(empty.matrix.admin, [])
})

test('buildRoleMatrixRows: с ролями — матрица ролей', () => {
  const rows = buildRoleMatrixRows(parseRolesCatalog(SERVER_CATALOG), true)
  const money = rows.find(row => row.permission === 'money_view')
  assert.deepEqual(money?.cells.map(cell => cell.allowed), [true, true, true, false])
  const settings = rows.find(row => row.permission === 'settings_manage')
  assert.deepEqual(settings?.cells.map(cell => cell.allowed), [true, false, false, false])
})

test('buildRoleMatrixRows: без ролей — права, которые действуют сейчас', () => {
  const rows = buildRoleMatrixRows(parseRolesCatalog(SERVER_CATALOG), false)
  const money = rows.find(row => row.permission === 'money_view')
  assert.deepEqual(money?.cells.map(cell => cell.allowed), [true, true, true, true], 'суммы видят все')
  const issue = rows.find(row => row.permission === 'billing_issue')
  assert.deepEqual(issue?.cells.map(cell => cell.allowed), [true, true, false, false])
  const close = rows.find(row => row.permission === 'period_close')
  assert.deepEqual(close?.cells.map(cell => cell.allowed), [true, false, false, false], 'месяц закрывает только админ портала')
})

test('buildRoleOptions: что назначать — решает сервер, недоступное гаснет, а не пропадает', () => {
  const catalog = parseRolesCatalog(SERVER_CATALOG)

  const all = buildRoleOptions(catalog, ['admin', 'accountant', 'project_manager', 'employee'])
  assert.ok(all.every(option => !option.disabled))
  assert.deepEqual(all.map(option => option.label), ['Администратор', 'Бухгалтерия', 'Руководитель проекта', 'Сотрудник'])

  const none = buildRoleOptions(catalog, [])
  assert.equal(none.length, 4, 'текущая роль человека должна остаться видна')
  assert.ok(none.every(option => option.disabled))

  assert.equal(buildRoleOptions(parseRolesCatalog(null), ['employee']).length, 4, 'без каталога — подписи по умолчанию')
})

test('fallbackAssignableRoles и assignable_roles с сервера', () => {
  assert.equal(fallbackAssignableRoles(true).length, 4)
  assert.deepEqual(fallbackAssignableRoles(false), [])

  const fromServer = parseRolesMe({
    roles_enabled: true, subscription_active: false, assignable_roles: ['accountant', 'boss'],
    permissions: { money_view: true },
  })
  assert.deepEqual(fromServer?.assignableRoles, ['accountant'])
})

test('describeRolesMode и rolesModeBadge: режим берётся из доступа к функции roles', () => {
  assert.equal(describeRolesMode(null).tone, 'info')
  assert.equal(rolesModeBadge(null), 'проверяем')

  const none = { restrictionsActive: false, canWrite: false, status: 'off' }
  assert.equal(describeRolesMode(none).tone, 'warning')
  assert.match(describeRolesMode(none).text, /тариф Pro/)
  assert.match(describeRolesMode(none).text, /суммы видят все/)
  assert.equal(rolesModeBadge(none), 'в тарифе Pro')

  const active = { restrictionsActive: true, canWrite: true, status: 'active' }
  assert.equal(describeRolesMode(active).tone, 'info')
  assert.equal(rolesModeBadge(active), 'действуют')
  assert.match(describeRolesMode({ ...active, status: 'trial' }).text, /пробный период/)
  assert.equal(rolesModeBadge({ ...active, status: 'trial' }), 'пробный Pro')

  const expired = { restrictionsActive: true, canWrite: false, status: 'expired' }
  assert.equal(describeRolesMode(expired).tone, 'warning')
  assert.match(describeRolesMode(expired).text, /закончился/)
  assert.match(describeRolesMode(expired).text, /не видят ставок и сумм/)
  assert.equal(rolesModeBadge(expired), 'Pro закончился')
})

test('тексты отказов называют роли и место, где их назначают', () => {
  const catalog = parseRolesCatalog(SERVER_CATALOG)
  assert.deepEqual(rolesAllowing(catalog, 'money_view'), ['Администратор', 'Бухгалтерия', 'Руководитель проекта'])
  assert.deepEqual(rolesAllowing(null, 'settings_manage'), ['Администратор'])

  const money = describeMoneyAccessDenied(catalog)
  assert.match(money, /«Администратор», «Бухгалтерия» или «Руководитель проекта»/)
  assert.match(money, /Настройки → Роли и права/)

  const withRoles = describeOperationsNoRights(true, catalog)
  assert.match(withRoles, /«Администратор» или «Бухгалтерия»/)
  const legacy = describeOperationsNoRights(false)
  assert.match(legacy, /администратор портала/)
  assert.match(legacy, /Роли и права/)
})

test('mergeUsersWithRoles: роль из назначений, имя из справочника, остальным — «Сотрудник»', () => {
  const assignments = parseRoleAssignments([
    { user_id: '1', name: 'Цыганков Егор', role: 'admin', role_title: 'Администратор', is_portal_admin: true, source: 'portal_admin' },
    { user_id: 21, name: 'Бухова Анна', role: 'accountant', source: 'billing_accountants' },
    { user_id: '', role: 'admin' },
    { user_id: '5', role: 'boss' },
  ])
  assert.equal(assignments.length, 2)

  const rows = mergeUsersWithRoles([
    { id: 1, name: 'Егор', last_name: 'Цыганков' },
    { id: '21', name: 'Анна', last_name: 'Бухова' },
    { id: 41 },
  ], assignments)
  assert.deepEqual(rows.map(row => [row.userId, row.role, row.isPortalAdmin]), [
    ['1', 'admin', true],
    ['21', 'accountant', false],
    ['41', 'employee', false],
  ])
  assert.equal(rows[2].name, 'Сотрудник #41')
  assert.equal(rows[2].roleTitle, 'Сотрудник')

  assert.match(describeAssignment(assignments[0]), /администратор портала/)
  assert.match(describeAssignment(assignments[1]), /прежнего списка «Бухгалтерия»/)
})

test('describeRoleAssignError: подписка, текст сервера из тела и из подменённого Error', () => {
  assert.match(describeRoleAssignError({ data: { code: 'feature_disabled', error: 'x' } }), /тарифе Pro/)
  assert.match(describeRoleAssignError(new Error('Функция «Ролевая модель» не подключена на этом портале: она входит в тариф Pro.')), /назначенные роли продолжают/)
  assert.equal(describeRoleAssignError(new Error('Назначать роли может администратор портала.')), 'Назначать роли может администратор портала.')
  assert.equal(describeRoleAssignError({ data: { error: 'Такой роли нет.' } }), 'Такой роли нет.')
  assert.match(describeRoleAssignError(new Error('[POST] "/api/roles/assign": 500')), /Не удалось сохранить роль/)
})

test('экран ролей находится под шестерёнкой', () => {
  const links = SETTINGS_NAV_GROUPS.flatMap(group => group.links)
  const roles = links.find(link => link.to === ROLES_SETTINGS_PATH)
  assert.ok(roles)
  assert.equal(roles.label, 'Роли и права')
})
