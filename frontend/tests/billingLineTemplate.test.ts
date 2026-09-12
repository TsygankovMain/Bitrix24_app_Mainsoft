/**
 * Шаблон формулировки строки счёта и описание группировки.
 *
 * Проверяется то, из-за чего вся правка: строка счёта обязана описывать
 * работы. У клиента НУОЛАБ она называлась «НУОЛАБ» — именем карточки проекта.
 *
 * Правила подстановки продублированы на сервере (billing_line_template.py), и
 * расхождение между примером в настройках и настоящим счётом — это молчаливое
 * вранье интерфейса, поэтому набор случаев здесь тот же, что в
 * tests_billing_task_lines.py.
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_LINE_PLACEHOLDERS,
  BILLING_TASK_LEVEL_OPTIONS,
  DEFAULT_BILLING_LINE_TEMPLATE,
  normalizeBillingLineTemplate,
  normalizeBillingTaskLevel,
  previewBillingLineTemplate,
  renderBillingLineTemplate,
  unknownBillingPlaceholders,
} from '../app/utils/billingLineTemplate'
import { describeBillingGrouping } from '../app/utils/billingGrouping'

test('шаблон по умолчанию читается как «задача, месяц»', () => {
  assert.equal(DEFAULT_BILLING_LINE_TEMPLATE, '{задача}, {месяц}')
  assert.equal(
    renderBillingLineTemplate(DEFAULT_BILLING_LINE_TEMPLATE, {
      задача: 'Настройка отчётов',
      месяц: 'август 2026',
    }),
    'Настройка отчётов, август 2026'
  )
})

test('подставляются все пять подстановок', () => {
  assert.equal(
    renderBillingLineTemplate('{задача} · {проект} · {клиент} · {месяц} · {период}', {
      задача: 'Настройка отчётов',
      проект: 'Внедрение CRM',
      клиент: 'ООО НУОЛАБ',
      месяц: 'август 2026',
      период: '01.08.2026—31.08.2026',
    }),
    'Настройка отчётов · Внедрение CRM · ООО НУОЛАБ · август 2026 · 01.08.2026—31.08.2026'
  )
})

test('неизвестная подстановка остаётся видимой, а не исчезает молча', () => {
  assert.equal(
    renderBillingLineTemplate('{задача} — {задание}', { задача: 'Правки' }),
    'Правки — {задание}'
  )
  assert.deepEqual(unknownBillingPlaceholders('{задача} — {задание}'), ['{задание}'])
  assert.deepEqual(unknownBillingPlaceholders('{задача}, {месяц}'), [])
})

test('известная подстановка без значения уходит вместе с разделителем', () => {
  assert.equal(
    renderBillingLineTemplate('{задача}, {месяц}', { задача: 'Правки', месяц: '' }),
    'Правки'
  )
  assert.equal(
    renderBillingLineTemplate('{задача} ({проект}), {месяц}', {
      задача: 'Правки',
      проект: '',
      месяц: 'август 2026',
    }),
    'Правки, август 2026'
  )
  assert.equal(
    renderBillingLineTemplate('{клиент}: {задача}', { клиент: '', задача: 'Правки' }),
    'Правки'
  )
})

test('пустой результат отдаёт предмет строки: счёт без наименования работ не уходит', () => {
  assert.equal(renderBillingLineTemplate('{клиент}', { клиент: '' }, 'Настройка отчётов'), 'Настройка отчётов')
  assert.equal(renderBillingLineTemplate('{клиент}', { клиент: '' }), '')
})

test('пустая настройка означает шаблон по умолчанию', () => {
  assert.equal(normalizeBillingLineTemplate(''), DEFAULT_BILLING_LINE_TEMPLATE)
  assert.equal(normalizeBillingLineTemplate(null), DEFAULT_BILLING_LINE_TEMPLATE)
  assert.equal(normalizeBillingLineTemplate(undefined), DEFAULT_BILLING_LINE_TEMPLATE)
  assert.equal(normalizeBillingLineTemplate('  {задача}  '), '{задача}')
})

test('пример в настройках собирается по тем же правилам', () => {
  assert.equal(previewBillingLineTemplate(''), 'Настройка отчётов, август 2026')
  assert.equal(previewBillingLineTemplate('{задача} для {клиент}'), 'Настройка отчётов для ООО НУОЛАБ')
  // Шаблон из одних неизвестных подстановок не оставляет пример пустым.
  assert.equal(previewBillingLineTemplate('{чепуха}'), '{чепуха}')
})

test('подсказка перечисляет ровно поддерживаемые подстановки', () => {
  assert.deepEqual(
    BILLING_LINE_PLACEHOLDERS.map(item => item.token),
    ['{задача}', '{проект}', '{клиент}', '{месяц}', '{период}']
  )
})

test('уровень задачи: чужое значение читается как «по задаче»', () => {
  for (const option of BILLING_TASK_LEVEL_OPTIONS) {
    assert.equal(normalizeBillingTaskLevel(option.id), option.id)
  }

  assert.equal(normalizeBillingTaskLevel('ROOT'), 'root')
  assert.equal(normalizeBillingTaskLevel('по-настроению'), 'task')
  assert.equal(normalizeBillingTaskLevel(undefined), 'task')
  assert.equal(normalizeBillingTaskLevel(null), 'task')
})

test('описание группировки называет состав строк и что попадёт в счёт', () => {
  const byTask = describeBillingGrouping('task')
  assert.equal(byTask.label, 'По задачам')
  assert.equal(byTask.summary, 'одна строка на задачу')
  assert.equal(byTask.subjectLabel, 'Задача')
  assert.match(byTask.hint, /название задачи/)
  // Про часы без задачи экран говорит прямо: они не теряются.
  assert.match(byTask.hint, /Работы без привязки к задаче/)

  const byRoot = describeBillingGrouping('task', 'root')
  assert.equal(byRoot.summary, 'одна строка на родительскую задачу')
  assert.equal(byRoot.subjectLabel, 'Родительская задача')

  const byProject = describeBillingGrouping('project')
  assert.equal(byProject.summary, 'одна строка на проект')
  assert.equal(byProject.subjectLabel, 'Проект')
  // Та самая ловушка: карточка проекта, названная по клиенту.
  assert.match(byProject.hint, /имя клиента/)

  const byEmployee = describeBillingGrouping('employee')
  assert.equal(byEmployee.summary, 'одна строка на сотрудника')

  const single = describeBillingGrouping('single')
  assert.equal(single.summary, 'весь период одной строкой')
  assert.equal(single.subjectLabel, '')
})

test('уровень задачи не упоминается там, где он ни на что не влияет', () => {
  // Группировка не по задачам: подпись не должна зависеть от уровня.
  assert.deepEqual(
    describeBillingGrouping('project', 'root'),
    describeBillingGrouping('project', 'task')
  )
})
