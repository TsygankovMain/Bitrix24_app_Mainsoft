import test from 'node:test'
import assert from 'node:assert/strict'

import { PERMISSION_CODES } from '../app/utils/appRoles'
import {
  DEFAULT_PERMISSION_MATRIX,
  FALLBACK_LOCKS,
  buildMatrixSections,
  dependentsOf,
  describeLocks,
  describeLogEntry,
  describeMatrixSaveError,
  describeRequirement,
  describeRoleChange,
  diffMatrices,
  formatLogDate,
  isRoleAtDefault,
  matricesEqual,
  matrixCellView,
  matrixEditMode,
  parseMatrixEditor,
  parseMatrixLog,
  parsePermissionMatrix,
  pluralChanges,
  requirementsOf,
  resetAllToDefault,
  resetRoleToDefault,
  summarizeChanges,
  togglePermission,
} from '../app/utils/permissionMatrix'

// Каталог в том виде, в каком его отдаёт сервер (main/roles.py, roles_catalog).
const SERVER_CATALOG = {
  roles: [
    { code: 'admin', title: 'Администратор', description: 'Управляет', customized: false },
    { code: 'accountant', title: 'Бухгалтерия', description: 'Деньги', customized: true },
    { code: 'project_manager', title: 'Руководитель проекта', description: 'Бюджеты', customized: false },
    { code: 'employee', title: 'Сотрудник', description: 'По умолчанию', customized: false },
  ],
  permissions: [
    { code: 'money_view', title: 'Видеть суммы', description: 'Открывает реестр', group: 'money', requires: [], requires_reason: '' },
    { code: 'rates_edit', title: 'Менять ставку', description: 'Ставка', group: 'money', requires: ['money_view'], requires_reason: 'ставка — это деньги' },
    { code: 'billing_issue', title: 'Выставлять счета', description: 'Счёт', group: 'billing', requires: ['money_view'], requires_reason: 'реестр закрыт' },
    { code: 'billing_cancel', title: 'Отменять счета', description: 'Отмена', group: 'billing', requires: ['money_view'], requires_reason: 'реестр закрыт' },
    { code: 'operations_create', title: 'Добавлять операции', description: 'Операции', group: 'operations', requires: ['money_view'], requires_reason: 'БДДС закрыт' },
    { code: 'period_close', title: 'Закрывать месяц', description: 'Месяц', group: 'period', requires: [], requires_reason: '' },
    { code: 'settings_manage', title: 'Менять настройки', description: 'Настройки', group: 'admin', requires: [], requires_reason: '' },
    { code: 'roles_manage', title: 'Назначать роли', description: 'Роли', group: 'admin', requires: [], requires_reason: '' },
  ],
  groups: [
    { code: 'money', title: 'Суммы и ставки', permissions: ['money_view', 'rates_edit'] },
    { code: 'billing', title: 'Счета и акты', permissions: ['billing_issue', 'billing_cancel'] },
    { code: 'operations', title: 'Начисления и списания', permissions: ['operations_create'] },
    { code: 'period', title: 'Закрытие месяца', permissions: ['period_close'] },
    { code: 'admin', title: 'Управление приложением', permissions: ['settings_manage', 'roles_manage'] },
  ],
  locks: [
    { role: 'admin', permission: 'settings_manage', value: true, reason: 'настройки не снимаются' },
    { role: 'admin', permission: 'roles_manage', value: true, reason: 'роли не снимаются' },
    { role: 'accountant', permission: 'roles_manage', value: false, reason: 'только администратор' },
    { role: 'project_manager', permission: 'roles_manage', value: false, reason: 'только администратор' },
    { role: 'employee', permission: 'roles_manage', value: false, reason: 'только администратор' },
  ],
  always_open: ['Списание времени в задачах', 'Отчёты по часам'],
  matrix: {
    admin: [...PERMISSION_CODES],
    accountant: ['money_view', 'billing_issue', 'billing_cancel', 'operations_create'],
    project_manager: ['money_view'],
    employee: [],
  },
  default_matrix: {
    admin: [...PERMISSION_CODES],
    accountant: ['money_view', 'rates_edit', 'billing_issue', 'billing_cancel', 'operations_create', 'period_close'],
    project_manager: ['money_view'],
    employee: [],
  },
  legacy_matrix: {},
  revision: 3,
  updated_at: '2026-09-12T10:00:00+00:00',
  updated_by_name: 'Цыганков Егор',
}

const data = parseMatrixEditor(SERVER_CATALOG)

test('parseMatrixEditor: разбирает каталог, версию и неизменяемые ячейки', () => {
  assert.equal(data.revision, 3)
  assert.equal(data.updatedByName, 'Цыганков Егор')
  assert.equal(data.roles.length, 4)
  assert.equal(data.roles[1]?.customized, true)
  assert.deepEqual(data.matrix.accountant, ['money_view', 'billing_issue', 'billing_cancel', 'operations_create'])
  assert.deepEqual(data.defaultMatrix, DEFAULT_PERMISSION_MATRIX, 'умолчание сервера совпадает с запасным на клиенте')
  assert.equal(data.locks.length, 5)
  assert.deepEqual(data.alwaysOpen, ['Списание времени в задачах', 'Отчёты по часам'])
})

test('parseMatrixEditor: пустой ответ -> правила и умолчания клиента', () => {
  const fallback = parseMatrixEditor(null)
  assert.deepEqual(fallback.matrix, DEFAULT_PERMISSION_MATRIX)
  assert.deepEqual(fallback.locks, FALLBACK_LOCKS)
  assert.equal(fallback.permissions.length, PERMISSION_CODES.length)
  assert.deepEqual(fallback.permissions.find(row => row.code === 'billing_cancel')?.requires, ['money_view'])
  assert.equal(fallback.revision, 0)
  assert.ok(fallback.alwaysOpen.some(item => /часам/.test(item)))
})

test('parsePermissionMatrix: мусор отбрасывается, порядок — как в таблице', () => {
  const matrix = parsePermissionMatrix({
    admin: ['roles_manage', 'money_view', 'money_view', 'reports_view'],
    boss: ['money_view'],
    employee: 'money_view',
  })
  assert.deepEqual(matrix.admin, ['money_view', 'roles_manage'])
  assert.deepEqual(matrix.employee, [])
  assert.deepEqual(matrix.accountant, [])
  assert.equal('boss' in matrix, false)
})

test('работа с часами в редакторе не появляется', () => {
  const codes = buildMatrixSections(data).flatMap(section => section.rows.map(row => row.code))
  assert.deepEqual([...codes].sort(), [...PERMISSION_CODES].sort())
  for (const code of codes) {
    assert.doesNotMatch(code, /hour|report|timesheet|board/)
  }
})

test('buildMatrixSections: группы по порядку, право без группы — в «Прочее»', () => {
  const sections = buildMatrixSections(data)
  assert.deepEqual(sections.map(section => section.code), ['money', 'billing', 'operations', 'period', 'admin'])
  assert.deepEqual(sections[0]?.rows.map(row => row.code), ['money_view', 'rates_edit'])

  const partial = parseMatrixEditor({ ...SERVER_CATALOG, groups: [{ code: 'money', title: 'Суммы', permissions: ['money_view'] }] })
  const partialSections = buildMatrixSections(partial)
  assert.equal(partialSections.at(-1)?.title, 'Прочее')
  assert.equal(partialSections.at(-1)?.rows.length, PERMISSION_CODES.length - 1)
})

test('зависимости: базовые и зависимые права', () => {
  assert.deepEqual(requirementsOf(data, 'billing_cancel'), ['money_view'])
  assert.deepEqual(requirementsOf(data, 'money_view'), [])
  assert.deepEqual(dependentsOf(data, 'money_view'), ['rates_edit', 'billing_issue', 'billing_cancel', 'operations_create'])
  assert.deepEqual(dependentsOf(data, 'period_close'), [])
  assert.match(describeRequirement(data, 'billing_issue'), /Работает только вместе с «Видеть суммы»: реестр закрыт\./)
  assert.equal(describeRequirement(data, 'money_view'), '')
})

test('togglePermission: включили зависимое — базовое включилось само, с объяснением', () => {
  const result = togglePermission(data, data.matrix, 'employee', 'billing_cancel', true)
  assert.equal(result.blocked, '')
  assert.deepEqual(result.matrix.employee, ['money_view', 'billing_cancel'])
  assert.equal(result.auto.length, 1)
  assert.equal(result.auto[0]?.permission, 'money_view')
  assert.equal(result.auto[0]?.granted, true)
  assert.match(result.auto[0]?.reason || '', /«Отменять счета» не работает без «Видеть суммы» — включили и его/)
  assert.deepEqual(data.matrix.employee, [], 'исходная матрица не меняется')
})

test('togglePermission: выключили базовое — зависимые выключились', () => {
  const result = togglePermission(data, data.matrix, 'accountant', 'money_view', false)
  assert.equal(result.blocked, '')
  assert.deepEqual(result.matrix.accountant, [])
  assert.deepEqual(result.auto.map(change => change.permission), ['billing_issue', 'billing_cancel', 'operations_create'])
  assert.ok(result.auto.every(change => !change.granted && /Без «Видеть суммы»/.test(change.reason)))
})

test('togglePermission: без зависимостей — только сама ячейка', () => {
  const result = togglePermission(data, data.matrix, 'accountant', 'period_close', true)
  assert.deepEqual(result.auto, [])
  assert.ok(result.matrix.accountant.includes('period_close'))
})

test('togglePermission: у администратора настройки и роли не снимаются', () => {
  for (const permission of ['settings_manage', 'roles_manage'] as const) {
    const result = togglePermission(data, data.matrix, 'admin', permission, false)
    assert.ok(result.blocked, permission)
    assert.ok(result.matrix.admin.includes(permission))
  }
  const other = togglePermission(data, data.matrix, 'accountant', 'roles_manage', true)
  assert.equal(other.blocked, 'только администратор')
  assert.equal(other.matrix.accountant.includes('roles_manage'), false)
})

test('togglePermission: у администратора можно снять суммы — настройки и роли остаются', () => {
  const result = togglePermission(data, data.matrix, 'admin', 'money_view', false)
  assert.equal(result.blocked, '')
  assert.deepEqual(result.matrix.admin, ['period_close', 'settings_manage', 'roles_manage'])
})

test('togglePermission: цепочка упирается в закреплённую ячейку — отказ', () => {
  const custom = parseMatrixEditor({
    ...SERVER_CATALOG,
    locks: [{ role: 'employee', permission: 'money_view', value: false, reason: 'суммы сотрудникам закрыты' }],
  })
  const on = togglePermission(custom, custom.matrix, 'employee', 'billing_issue', true)
  assert.equal(on.blocked, 'суммы сотрудникам закрыты')
  assert.deepEqual(on.matrix.employee, [])

  const locked = parseMatrixEditor({
    ...SERVER_CATALOG,
    locks: [{ role: 'accountant', permission: 'billing_issue', value: true, reason: 'счета закреплены' }],
  })
  const off = togglePermission(locked, locked.matrix, 'accountant', 'money_view', false)
  assert.equal(off.blocked, 'счета закреплены')
  assert.ok(off.matrix.accountant.includes('money_view'))
})

test('diffMatrices и предпросмотр изменений', () => {
  const step1 = togglePermission(data, data.matrix, 'employee', 'billing_issue', true).matrix
  const step2 = togglePermission(data, step1, 'project_manager', 'money_view', false).matrix
  const changes = diffMatrices(data.matrix, step2)
  assert.deepEqual(changes, [
    { role: 'project_manager', permission: 'money_view', granted: false },
    { role: 'employee', permission: 'money_view', granted: true },
    { role: 'employee', permission: 'billing_issue', granted: true },
  ])
  const summary = summarizeChanges(data, changes)
  assert.deepEqual(summary.map(row => row.role), ['project_manager', 'employee'])
  assert.equal(describeRoleChange(summary[0]!), 'Руководитель проекта: потеряет «Видеть суммы».')
  assert.equal(describeRoleChange(summary[1]!), 'Сотрудник: получит «Видеть суммы», «Выставлять счета».')
  assert.equal(matricesEqual(data.matrix, step2), false)
  assert.equal(matricesEqual(data.matrix, parsePermissionMatrix(SERVER_CATALOG.matrix)), true)
})

test('вернуть по умолчанию: роль и вся таблица — в черновик', () => {
  assert.equal(isRoleAtDefault(data, data.matrix, 'accountant'), false)
  const role = resetRoleToDefault(data, data.matrix, 'accountant')
  assert.deepEqual(role.accountant, DEFAULT_PERMISSION_MATRIX.accountant)
  assert.equal(isRoleAtDefault(data, role, 'accountant'), true)

  const changed = togglePermission(data, role, 'employee', 'money_view', true).matrix
  const all = resetAllToDefault(data)
  assert.deepEqual(all, DEFAULT_PERMISSION_MATRIX)
  assert.deepEqual(diffMatrices(changed, all), [{ role: 'employee', permission: 'money_view', granted: false }])
})

test('matrixCellView: несохранённая правка, закреплённая ячейка, отличие от умолчания', () => {
  const draft = togglePermission(data, data.matrix, 'accountant', 'period_close', true).matrix
  const cell = matrixCellView(data, data.matrix, draft, 'accountant', 'period_close')
  assert.deepEqual(cell, { checked: true, changed: true, locked: false, lockReason: '', customized: false })

  const rates = matrixCellView(data, data.matrix, draft, 'accountant', 'rates_edit')
  assert.equal(rates.customized, true)
  assert.equal(rates.changed, false)

  const locked = matrixCellView(data, data.matrix, draft, 'admin', 'roles_manage')
  assert.equal(locked.locked, true)
  assert.equal(locked.lockReason, 'роли не снимаются')
  assert.deepEqual(describeLocks(data), ['настройки не снимаются', 'роли не снимаются', 'только администратор'])
})

test('matrixEditMode: править можно только роли «Администратор» при живом Pro', () => {
  assert.deepEqual(matrixEditMode({ canManage: true, restrictionsActive: true, canWrite: true }), { editable: true, reason: '' })
  assert.match(matrixEditMode({ canManage: true, restrictionsActive: true, canWrite: false }).reason, /закончился.*продолжают действовать/)
  assert.match(matrixEditMode({ canManage: true, restrictionsActive: false, canWrite: false }).reason, /после подключения тарифа Pro/)
  assert.match(matrixEditMode({ canManage: false, restrictionsActive: true, canWrite: true }).reason, /«Администратор»/)
  assert.equal(matrixEditMode({ canManage: true, restrictionsActive: true, canWrite: true, unknown: true }).editable, false)
})

test('журнал: разбор и текст записи', () => {
  const log = parseMatrixLog([
    {
      revision: 2,
      changed_at: '2026-09-12T11:05:00',
      changed_by_name: 'Цыганков Егор',
      reset_to_default: false,
      changes: [
        { role: 'accountant', permission: 'period_close', granted: false, role_title: 'Бухгалтерия', permission_title: 'Закрывать месяц' },
        { role: 'employee', permission: 'money_view', granted: true, role_title: 'Сотрудник', permission_title: 'Видеть суммы' },
        { role: 'boss', permission: 'money_view', granted: true },
      ],
    },
    { revision: 1, changed_at: null, changed_by_name: '', reset_to_default: true, changes: [] },
    'мусор',
  ])
  assert.equal(log.length, 3)
  assert.equal(log[0]?.changes.length, 2, 'неизвестная роль отброшена')

  const first = describeLogEntry(log[0]!)
  assert.equal(first.title, '12.09.2026 11:05 · Цыганков Егор')
  assert.deepEqual(first.lines, ['Бухгалтерия: выключено «Закрывать месяц».', 'Сотрудник: включено «Видеть суммы».'])

  const reset = describeLogEntry(log[1]!)
  assert.equal(reset.lines[0], 'Все права возвращены к значениям по умолчанию.')
  assert.match(reset.title, /без имени/)
})

test('formatLogDate и pluralChanges', () => {
  assert.equal(formatLogDate(null), '')
  assert.equal(formatLogDate('не дата'), '')
  assert.equal(pluralChanges(1), '1 изменение')
  assert.equal(pluralChanges(3), '3 изменения')
  assert.equal(pluralChanges(5), '5 изменений')
  assert.equal(pluralChanges(11), '11 изменений')
  assert.equal(pluralChanges(22), '22 изменения')
})

test('describeMatrixSaveError: конфликт, тариф, текст сервера', () => {
  const conflict = describeMatrixSaveError({ data: { code: 'matrix_conflict', error: 'Уже поменяли' } })
  assert.deepEqual(conflict, { text: 'Уже поменяли', conflict: true })

  const expired = describeMatrixSaveError(new Error('Функция «Роли» не подключена'))
  assert.equal(expired.conflict, false)
  assert.match(expired.text, /тарифе Pro/)

  const locked = describeMatrixSaveError({ data: { code: 'permission_locked', error: 'У «Администратора» не снимается' } })
  assert.equal(locked.text, 'У «Администратора» не снимается')

  assert.match(describeMatrixSaveError(new Error('[POST] "/api/roles/matrix": 500')).text, /Не удалось сохранить/)
})
