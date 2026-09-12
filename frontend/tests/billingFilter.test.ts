import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_COMPANY_REQUIRED_ERROR,
  BILLING_GROUPING_OPTIONS,
  buildBillingFilterBody,
  buildBillingRegistryQuery,
  createBillingFilterForm,
  createBillingRegistryFilter,
  normalizeBillingGrouping,
  parseTaskIdsInput,
  validateBillingFilter,
} from '../app/utils/billingFilter'

test('createBillingFilterForm: по умолчанию прошлый месяц и галочки контракта', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))

  assert.equal(form.dateFrom, '2026-08-01')
  assert.equal(form.dateTo, '2026-08-31')
  assert.equal(form.billableOnly, true)
  assert.equal(form.excludeInvoiced, true)
  assert.equal(form.onlyClosedPeriods, true)
  assert.equal(form.grouping, 'task')
})

test('createBillingFilterForm: январь берёт декабрь предыдущего года', () => {
  const form = createBillingFilterForm(new Date(2026, 0, 15))

  assert.equal(form.dateFrom, '2025-12-01')
  assert.equal(form.dateTo, '2025-12-31')
})

test('normalizeBillingGrouping: чужая группировка превращается в «по задачам»', () => {
  for (const option of BILLING_GROUPING_OPTIONS) {
    assert.equal(normalizeBillingGrouping(option.id), option.id)
  }

  assert.equal(normalizeBillingGrouping('company'), 'task')
  assert.equal(normalizeBillingGrouping(undefined), 'task')
})

test('createBillingFilterForm: группировка по умолчанию — по задачам', () => {
  // Строка счёта обязана описывать работы. Группировка по проектам брала имя
  // карточки проекта, и у клиента НУОЛАБ в счёт ушло «НУОЛАБ».
  assert.equal(createBillingFilterForm(new Date(2026, 8, 12)).grouping, 'task')
  assert.equal(buildBillingFilterBody(createBillingFilterForm(new Date(2026, 8, 12))).grouping, 'task')
})

test('buildBillingFilterBody: в теле только поля контракта', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))
  const body = buildBillingFilterBody(form)

  assert.deepEqual(Object.keys(body).sort(), [
    'billable_only',
    'date_from',
    'date_to',
    'exclude_invoiced',
    'grouping',
    'only_closed_periods',
  ])
})

test('buildBillingFilterBody: пустые списки и пустые id в тело не попадают', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))
  const body = buildBillingFilterBody({
    ...form,
    companyId: '   ',
    ourCompanyId: '',
    projectIds: [],
    employeeIds: ['', '  '],
  })

  assert.equal('company_id' in body, false)
  assert.equal('our_company_id' in body, false)
  assert.equal('project_ids' in body, false)
  assert.equal('employee_ids' in body, false)
})

test('buildBillingFilterBody: заполненные справочники нормализуются к строкам без дублей', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))
  const body = buildBillingFilterBody({
    ...form,
    companyId: ' 42 ',
    ourCompanyId: '7',
    projectIds: ['5', 5 as unknown as string, ' 6 '],
    employeeIds: ['11'],
    taskIds: ['9483'],
    billableOnly: false,
    grouping: 'task',
  })

  assert.equal(body.company_id, '42')
  assert.equal(body.our_company_id, '7')
  assert.deepEqual(body.project_ids, ['5', '6'])
  assert.deepEqual(body.employee_ids, ['11'])
  assert.deepEqual(body.task_ids, ['9483'])
  assert.equal(body.billable_only, false)
  assert.equal(body.grouping, 'task')
})

test('parseTaskIdsInput: принимаем любые разделители — вставляют как скопировали', () => {
  assert.deepEqual(parseTaskIdsInput('9483, 9512'), ['9483', '9512'])
  assert.deepEqual(parseTaskIdsInput('9483 9512;9600\n9700'), ['9483', '9512', '9600', '9700'])
  assert.deepEqual(parseTaskIdsInput('задача 9483'), ['9483'])
  assert.deepEqual(parseTaskIdsInput('9483, 9483'), ['9483'])
  assert.deepEqual(parseTaskIdsInput(''), [])
  assert.deepEqual(parseTaskIdsInput(null), [])
})

test('validateBillingFilter: без дат предпросмотр не запускается', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))

  assert.deepEqual(validateBillingFilter({ ...form, dateFrom: '', companyId: '7' }).length, 1)
  assert.deepEqual(validateBillingFilter({ ...form, dateTo: '', companyId: '7' }).length, 1)
})

test('validateBillingFilter: перевёрнутый период — ошибка с понятным текстом', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))
  const errors = validateBillingFilter({
    ...form,
    companyId: '7',
    dateFrom: '2026-09-30',
    dateTo: '2026-09-01',
  })

  assert.equal(errors.length, 1)
  assert.match(errors[0], /позже/)
})

test('validateBillingFilter: без клиента предпросмотр не запускается', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))
  const errors = validateBillingFilter({ ...form, companyId: '' })

  assert.equal(errors.length, 1)
  assert.equal(errors[0], BILLING_COMPANY_REQUIRED_ERROR)
  assert.match(errors[0], /одному клиенту/)
})

test('validateBillingFilter: с клиентом и нормальным периодом претензий нет', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))

  assert.deepEqual(validateBillingFilter({ ...form, companyId: '1758' }), [])
})

test('validateBillingFilter: пробелы в клиенте за выбор не считаются', () => {
  const form = createBillingFilterForm(new Date(2026, 8, 12))

  assert.deepEqual(validateBillingFilter({ ...form, companyId: '   ' }), [BILLING_COMPANY_REQUIRED_ERROR])
})

test('buildBillingRegistryQuery: пустой фильтр не шлёт ни одного параметра', () => {
  assert.equal(buildBillingRegistryQuery(createBillingRegistryFilter()).toString(), '')
})

test('buildBillingRegistryQuery: заполненный фильтр — имена параметров как в контракте', () => {
  const params = buildBillingRegistryQuery({
    companyId: '42',
    dateFrom: '2026-09-01',
    dateTo: '2026-09-30',
    status: 'issued',
  })

  assert.equal(params.get('company_id'), '42')
  assert.equal(params.get('date_from'), '2026-09-01')
  assert.equal(params.get('date_to'), '2026-09-30')
  assert.equal(params.get('status'), 'issued')
})
