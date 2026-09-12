/**
 * Варианты наполнения счёта: формулировки, пример строки, выбор варианта.
 *
 * Проверяется то же, что на сервере (tests_billing_line_variants.py), потому
 * что правила продублированы: текст строк собирает сервер, а экран настроек
 * показывает живой пример. Расхождение между примером и настоящим счётом —
 * молчаливое вранье интерфейса, и заметят его уже у клиента.
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_LINE_VARIANTS,
  DEFAULT_BILLING_LINE_TEMPLATES,
  DEFAULT_BILLING_SERVICE_NAME,
  billingLineTemplateKey,
  defaultBillingLineTemplate,
  normalizeBillingLineTemplate,
  normalizeBillingLineVariant,
  normalizeBillingServiceName,
  previewBillingLineTemplate,
  renderBillingLineTemplate,
} from '../app/utils/billingLineTemplate'
import { describeBillingGroupingSource } from '../app/utils/billingGrouping'
import {
  applyBillingLineTemplates,
  readBillingLineTemplates,
  readBillingSettings,
} from '../app/utils/billingSettings'

test('варианта ровно четыре, и у каждого своя формулировка', () => {
  assert.deepEqual(
    BILLING_LINE_VARIANTS.map(item => item.id),
    ['task', 'project', 'employee', 'single']
  )
  assert.deepEqual(DEFAULT_BILLING_LINE_TEMPLATES, {
    task: '{задача}, {месяц}',
    project: '{услуга} по проекту „{проект}“, {месяц}',
    employee: 'Работы {сотрудник}, {месяц}',
    single: 'Услуги по разработке и сопровождению за {месяц}',
  })
  // Ни одна формулировка не повторяет другую: смысл вариантов в том, что
  // строка читается по-разному.
  assert.equal(new Set(Object.values(DEFAULT_BILLING_LINE_TEMPLATES)).size, 4)
})

test('чужой вариант читается как «по задачам»', () => {
  for (const variant of BILLING_LINE_VARIANTS) {
    assert.equal(normalizeBillingLineVariant(variant.id), variant.id)
  }

  assert.equal(normalizeBillingLineVariant(' SINGLE '), 'single')
  assert.equal(normalizeBillingLineVariant('одной-строкой'), 'task')
  assert.equal(normalizeBillingLineVariant(''), 'task')
  assert.equal(normalizeBillingLineVariant(undefined), 'task')
})

test('пустая формулировка — значение по умолчанию ЭТОГО варианта', () => {
  // Иначе счёт на одну строку получил бы «{задача}, {месяц}» и прочитался как
  // «Услуги по договору, август 2026».
  for (const variant of BILLING_LINE_VARIANTS) {
    assert.equal(
      normalizeBillingLineTemplate('', variant.id),
      DEFAULT_BILLING_LINE_TEMPLATES[variant.id]
    )
    assert.equal(defaultBillingLineTemplate(variant.id), variant.defaultTemplate)
  }

  assert.equal(normalizeBillingLineTemplate('  {задача}  ', 'single'), '{задача}')
})

test('ключ формулировки варианта «по задачам» остался без суффикса', () => {
  // Под этим ключом формулировка уже лежит в конфигурации порталов: ключ с
  // суффиксом молча вернул бы им текст по умолчанию.
  assert.equal(billingLineTemplateKey('task'), 'billing_line_template')
  assert.equal(billingLineTemplateKey('project'), 'billing_line_template_project')
  assert.equal(billingLineTemplateKey('employee'), 'billing_line_template_employee')
  assert.equal(billingLineTemplateKey('single'), 'billing_line_template_single')
  assert.equal(billingLineTemplateKey('что-то'), 'billing_line_template')
})

test('услуга: пусто — «Разработка», а не пустое место в строке', () => {
  assert.equal(normalizeBillingServiceName(''), DEFAULT_BILLING_SERVICE_NAME)
  assert.equal(normalizeBillingServiceName(null), 'Разработка')
  assert.equal(normalizeBillingServiceName('  Сопровождение '), 'Сопровождение')
})

test('подстановки «сотрудник» и «услуга» работают', () => {
  assert.equal(
    renderBillingLineTemplate(
      'Работы {сотрудник} ({услуга}), {месяц}',
      { сотрудник: 'Петровой Анны', услуга: 'Аналитика', месяц: 'август 2026' }
    ),
    'Работы Петровой Анны (Аналитика), август 2026'
  )
})

test('не переданная известная подстановка не уходит в счёт скобками', () => {
  // Известной она остаётся всегда, даже если вызывающий её не передал:
  // «Работы {сотрудник}» в печатной форме выглядит как сбой приложения.
  assert.equal(
    renderBillingLineTemplate('Работы {сотрудник}, {месяц}', { месяц: 'август 2026' }),
    'Работы август 2026'
  )
})

test('неизвестная подстановка по-прежнему остаётся видимой', () => {
  // Решение принято раньше и не меняется: опечатку надо замечать в примере.
  assert.equal(
    renderBillingLineTemplate('{задача} — {задание}', { задача: 'Правки' }),
    'Правки — {задание}'
  )
})

test('пример строки у каждого варианта свой и читается как настоящая строка', () => {
  const examples = Object.fromEntries(
    BILLING_LINE_VARIANTS.map(
      variant => [variant.id, previewBillingLineTemplate(variant.defaultTemplate, variant.id)]
    )
  )

  assert.equal(examples.task, 'Настройка отчётов, август 2026')
  assert.equal(examples.project, 'Разработка по проекту „Личный кабинет“, август 2026')
  assert.equal(examples.employee, 'Работы Цыганков Егор, август 2026')
  assert.equal(examples.single, 'Услуги по разработке и сопровождению за август 2026')
  assert.equal(new Set(Object.values(examples)).size, 4)
})

test('пример меняется вместе с настройкой услуги', () => {
  assert.equal(
    previewBillingLineTemplate(
      DEFAULT_BILLING_LINE_TEMPLATES.project, 'project', 'Сопровождение'
    ),
    'Сопровождение по проекту „Личный кабинет“, август 2026'
  )
})

test('пример показывает ПУСТЫЕ слоты так же, как их покажет счёт', () => {
  // В строке на сотрудника проекта нет (человек работал в нескольких), и
  // подставить туда правдоподобное название значило бы обещать формулировку,
  // которой в счёте не будет.
  assert.equal(
    previewBillingLineTemplate('Работы {сотрудник} по проекту {проект}, {месяц}', 'employee'),
    'Работы Цыганков Егор по проекту август 2026'
  )
  assert.equal(
    previewBillingLineTemplate('{задача} ({сотрудник}), {месяц}', 'single'),
    'Услуги по договору, август 2026'
  )
})

test('пустой шаблон в примере читается как формулировка по умолчанию варианта', () => {
  assert.equal(
    previewBillingLineTemplate('', 'single'),
    'Услуги по разработке и сопровождению за август 2026'
  )
})

test('формулировки читаются и пишутся по своим ключам конфигурации', () => {
  const config = {
    billing_line_template: '{задача} за {период}',
    billing_line_template_single: 'Услуги за {месяц}',
  }

  const read = readBillingLineTemplates(config)
  assert.equal(read.task, '{задача} за {период}')
  assert.equal(read.single, 'Услуги за {месяц}')
  // Незаданная формулировка — значение по умолчанию своего варианта, а не
  // соседнего.
  assert.equal(read.project, DEFAULT_BILLING_LINE_TEMPLATES.project)
  assert.equal(read.employee, DEFAULT_BILLING_LINE_TEMPLATES.employee)

  assert.deepEqual(applyBillingLineTemplates(read), {
    billing_line_template: '{задача} за {период}',
    billing_line_template_project: DEFAULT_BILLING_LINE_TEMPLATES.project,
    billing_line_template_employee: DEFAULT_BILLING_LINE_TEMPLATES.employee,
    billing_line_template_single: 'Услуги за {месяц}',
  })
})

test('вариант по умолчанию читается из конфигурации портала', () => {
  assert.equal(readBillingSettings({}).lineVariant, 'task')
  assert.equal(readBillingSettings({ billing_line_variant: 'single' }).lineVariant, 'single')
  // Опечатка в настройке не имеет права свернуть счёт в одну строку.
  assert.equal(readBillingSettings({ billing_line_variant: 'как-нибудь' }).lineVariant, 'task')
  assert.equal(readBillingSettings({ billing_service_name: '  Внедрение ' }).serviceName, 'Внедрение')
  assert.equal(readBillingSettings({}).serviceName, DEFAULT_BILLING_SERVICE_NAME)
})

test('источник варианта называется словами, а при молчании сервера молчит', () => {
  assert.equal(
    describeBillingGroupingSource('settings').text,
    'вариант по умолчанию из настроек приложения'
  )
  assert.equal(describeBillingGroupingSource('settings').hint, '')

  const chosen = describeBillingGroupingSource('request')
  assert.equal(chosen.text, 'вариант выбран в этом мастере')
  // Подсказка обязана сказать, где менять вариант навсегда.
  assert.match(chosen.hint, /настройк/i)

  // Старый ответ без источника: врать про настройку приложения нельзя.
  assert.equal(describeBillingGroupingSource(undefined).text, '')
  assert.equal(describeBillingGroupingSource('').text, '')
})
