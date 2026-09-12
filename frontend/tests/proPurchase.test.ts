import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildProRequestBody,
  cardPaymentMailto,
  checkProField,
  createProForm,
  daysUntil,
  describeProApiError,
  describeProRequest,
  describeProSubscription,
  formatRub,
  formatRubKop,
  innChecksumOk,
  mapServerFieldErrors,
  monthsText,
  normalizeInnInput,
  normalizeKppInput,
  parseProOffer,
  parseProRequest,
  payerTypeForInn,
  perMonthHint,
  proFormFromRequest,
  proRequestTimeline,
  resolveProNavButton,
  shouldShowFinanceProFooter,
  shouldShowProNavButton,
  termSummaryRows,
  validateProForm,
  type ProForm,
} from '../app/utils/proPurchase'

const NBSP = ' '

const OFFER_PAYLOAD = {
  price_month_rub: 3000,
  vat: { mode: 'included', rate: '22' },
  terms: [
    { months: 1, label: '', price_month: '3000.00', base: '3000.00', discount: '0.00', subtotal: '3000.00', vat_mode: 'included', vat_rate: '22', vat: '540.98', total: '3000.00', per_month: '3000.00', vat_text: 'В т.ч. НДС 22% 540,98 руб.' },
    { months: 3, label: '', price_month: '3000.00', base: '9000.00', discount: '0.00', subtotal: '9000.00', vat_mode: 'included', vat_rate: '22', vat: '1622.95', total: '9000.00', per_month: '3000.00', vat_text: '' },
    { months: 6, label: '−5%', price_month: '3000.00', base: '18000.00', discount: '900.00', subtotal: '17100.00', vat_mode: 'included', vat_rate: '22', vat: '3083.61', total: '17100.00', per_month: '2850.00', vat_text: '' },
    { months: 12, label: '12 по цене 10', price_month: '3000.00', base: '36000.00', discount: '6000.00', subtotal: '30000.00', vat_mode: 'included', vat_rate: '22', vat: '5409.84', total: '30000.00', per_month: '2500.00', vat_text: 'В т.ч. НДС 22% 5409,84 руб.' },
  ],
  default_months: 12,
  due_business_days: 5,
  contact_email: 'timesheet@mainsoft.su',
  offer_url: 'javascript:alert(1)',
  portal: { domain: 'kvarc-int.bitrix24.ru', code: '482137', member_id_short: 'a3f9c2e1…4c7e35' },
  contact: { name: 'Ирина Ковалёва', email: 'i.kovaleva@kvarc-int.ru' },
  subscription: { status: 'trial', access: 'full', paid_until: null, trial_until: '2026-09-21', grace_until: null },
  can_request: true,
  managers: [],
  current_request: null,
  crm_mode: 'manual',
}

const REQUEST_PAYLOAD = {
  id: '8f0c', invoice_number: 'УТ-0047', invoice_date: '2026-09-12', due_date: '2026-09-18',
  status: 'pending', months: 12, months_text: '12 месяцев', total: '30000.00',
  requested_by_name: 'Ирина Ковалёва', created_at: '2026-09-12T11:32:00Z', pro_paid_until: null,
  amounts: { base: '36000.00', discount: '6000.00', subtotal: '30000.00', vat_mode: 'included', vat_rate: '22', vat: '5409.84', total: '30000.00', vat_text: 'В т.ч. НДС 22% 5409,84 руб.' },
  payment_purpose: 'Оплата по счёту № УТ-0047 от 12.09.2026. Подписка Pro «Учёт трудозатрат» на 12 мес., портал kvarc-int.bitrix24.ru, код 482137. В т.ч. НДС 22% 5409,84 руб.',
  portal: { domain: 'kvarc-int.bitrix24.ru', code: '482137', member_id_short: 'a3f9c2e1…4c7e35' },
  payer: { type: 'org', inn: '7325148066', kpp: '732501001', name: 'ООО «Кварц Интеграция»', address: '432017, Ульяновск' },
  contact: { name: 'Ирина Ковалёва', email: 'i@kvarc.ru', cc: '', phone: '' },
  crm_state: 'manual', pdf_available: false, paid_on: null, cancel_reason: '', sequence_number: 47,
}

function validForm(overrides: Partial<ProForm> = {}): ProForm {
  return {
    ...createProForm(),
    contactName: 'Ирина Ковалёва',
    payerInn: '7325148066',
    payerKpp: '732501001',
    payerName: 'Общество с ограниченной ответственностью «Кварц Интеграция»',
    payerAddress: '432017, г. Ульяновск, ул. Спасская, д. 19/9',
    contactEmail: 'i.kovaleva@kvarc-int.ru',
    offerAccepted: true,
    months: 12,
    ...overrides,
  }
}

// --- проверки полей --------------------------------------------------------

test('валидная форма организации проходит без ошибок', () => {
  assert.deepEqual(validateProForm(validForm(), [1, 3, 6, 12]), [])
})

test('ИНН: пусто, буквы, длина; пробелы убираются', () => {
  assert.equal(checkProField('payerInn', validForm({ payerInn: '' })).error, 'Укажите ИНН плательщика')
  assert.equal(checkProField('payerInn', validForm({ payerInn: '73251480ab' })).error, 'В ИНН только цифры')
  assert.equal(checkProField('payerInn', validForm({ payerInn: '12345' })).error, 'У организации 10 цифр, у ИП — 12. Сейчас 5')
  assert.equal(normalizeInnInput(' 7325 148 066 '), '7325148066')
})

test('ИНН: неверная контрольная цифра — только предупреждение', () => {
  assert.equal(innChecksumOk('7325148066'), true)
  assert.equal(innChecksumOk('7707083893'), true)
  assert.equal(innChecksumOk('7707083894'), false)
  const check = checkProField('payerInn', validForm({ payerInn: '7707083894' }))
  assert.equal(check.error, '')
  assert.match(check.warning, /Контрольная цифра не сходится/)
  assert.deepEqual(validateProForm(validForm({ payerInn: '7707083894' })), [])
})

test('ИП определяется по длине ИНН: КПП не нужен, подпись — ФИО', () => {
  assert.equal(payerTypeForInn('732501947362'), 'ip')
  assert.equal(payerTypeForInn('7325148066'), 'org')
  const ip = validForm({ payerInn: '732501947362', payerKpp: '', payerName: 'ИП' })
  const errors = validateProForm(ip)
  assert.equal(errors.some(item => item.field === 'payerKpp'), false)
  assert.equal(checkProField('payerName', ip).error, 'Укажите ФИО предпринимателя')
  assert.equal(buildProRequestBody({ ...ip, payerKpp: '732501001' }).payer_kpp, '')
})

test('КПП обязателен для организации и проверяется по форме', () => {
  assert.equal(checkProField('payerKpp', validForm({ payerKpp: '' })).error, 'Укажите КПП — у организации он обязателен')
  assert.match(checkProField('payerKpp', validForm({ payerKpp: '7325AB0010' })).error, /9 знаков/)
  assert.equal(checkProField('payerKpp', validForm({ payerKpp: '7325AB001' })).error, '')
  assert.equal(normalizeKppInput(' 7325ab001 '), '7325AB001')
})

test('почта обязательна, копия и телефон проверяются, если заполнены', () => {
  assert.equal(checkProField('contactEmail', validForm({ contactEmail: '' })).error, 'Укажите почту, на которую отправить счёт')
  assert.match(checkProField('contactEmail', validForm({ contactEmail: 'irina@kvarc' })).error, /неполной/)
  assert.equal(checkProField('contactCc', validForm({ contactCc: '' })).error, '')
  assert.match(checkProField('contactCc', validForm({ contactCc: 'buh@' })).error, /копии/)
  assert.equal(checkProField('contactPhone', validForm({ contactPhone: '' })).error, '')
  assert.match(checkProField('contactPhone', validForm({ contactPhone: '12-34' })).error, /10–11 цифр/)
  assert.equal(checkProField('contactPhone', validForm({ contactPhone: '+7 842 250-14-80' })).error, '')
})

test('без согласия с офертой счёт не формируется; адрес без индекса — предупреждение', () => {
  const errors = validateProForm(validForm({ offerAccepted: false }))
  assert.deepEqual(errors.map(item => item.field), ['offerAccepted'])
  const address = checkProField('payerAddress', validForm({ payerAddress: 'г. Ульяновск, ул. Спасская, 19' }))
  assert.equal(address.error, '')
  assert.match(address.warning, /индекса/)
  assert.equal(checkProField('payerAddress', validForm({ payerAddress: 'коротко' })).error, 'Укажите юридический адрес')
})

test('срок должен быть из предложенных', () => {
  assert.equal(checkProField('months', validForm({ months: 7 }), [1, 3, 6, 12]).error, 'Выберите срок подписки')
})

test('тело запроса не содержит портала, домена и member_id', () => {
  const body = buildProRequestBody(validForm({ payerInn: ' 7325 148066 ', payerKpp: '732501001' }))
  assert.equal(body.payer_inn, '7325148066')
  assert.equal(body.offer_accepted, true)
  for (const key of Object.keys(body)) {
    assert.doesNotMatch(key, /portal|domain|member/)
  }
})

test('ошибки сервера ложатся на поля формы', () => {
  assert.deepEqual(
    mapServerFieldErrors({ payer_inn: 'ИНН должен…', offer_accepted: 'Отметьте', unknown: 'x' }),
    { payerInn: 'ИНН должен…', offerAccepted: 'Отметьте' }
  )
  const view = describeProApiError({ status: 400, data: { error: 'Проверьте поля формы.', code: 'validation_failed', errors: { payer_kpp: 'КПП' } } })
  assert.equal(view.code, 'validation_failed')
  assert.deepEqual(view.fieldErrors, { payerKpp: 'КПП' })
  assert.equal(describeProApiError({ statusCode: 403, data: { code: 'pro_request_forbidden' } }).message,
    'Счёт на Pro запрашивает администратор портала или сотрудник с ролью «Бухгалтерия».')
  assert.match(describeProApiError({ status: 429 }).message, /Слишком много запросов/)
})

// --- расчёт и формат ---------------------------------------------------------

test('разбор предложения: суммы с сервера, небезопасная ссылка оферты отброшена', () => {
  const offer = parseProOffer(OFFER_PAYLOAD)
  assert.equal(offer.terms.length, 4)
  assert.equal(offer.terms[3]!.total, 30000)
  assert.equal(offer.terms[3]!.discount, 6000)
  assert.equal(offer.defaultMonths, 12)
  assert.equal(offer.offerUrl, '')
  assert.equal(offer.portal.code, '482137')
  assert.equal(offer.canRequest, true)
  assert.equal(offer.crmMode, 'manual')
  assert.equal(createProForm(offer).contactEmail, 'i.kovaleva@kvarc-int.ru')
  assert.equal(createProForm(offer).months, 12)
})

test('сводка срока: база, скидка «12 по цене 10», НДС в т.ч.', () => {
  const offer = parseProOffer(OFFER_PAYLOAD)
  const rows = termSummaryRows(offer.terms[3]!)
  assert.deepEqual(rows.map(row => row.label), [
    `12 месяцев × 3${NBSP}000${NBSP}₽`,
    'Скидка «12 по цене 10»',
    'НДС 22%',
  ])
  assert.equal(rows[1]!.value, `−6${NBSP}000${NBSP}₽`)
  assert.equal(rows[2]!.value, `в т.ч. 5${NBSP}409,84${NBSP}₽`)
  assert.equal(termSummaryRows(offer.terms[0]!).length, 2)
  assert.equal(perMonthHint(offer.terms[3]!, offer.terms), `Это 2${NBSP}500${NBSP}₽ в месяц за весь портал`)
  assert.equal(perMonthHint(offer.terms[0]!, offer.terms), 'Выгоднее за 12 месяцев: 2 месяца бесплатно')
})

test('формат сумм и месяцев', () => {
  assert.equal(formatRub(30000), `30${NBSP}000${NBSP}₽`)
  assert.equal(formatRub(3660.5), `3${NBSP}660,50${NBSP}₽`)
  assert.equal(formatRubKop(5409.84), `5${NBSP}409,84`)
  assert.equal(monthsText(1), '1 месяц')
  assert.equal(monthsText(3), '3 месяца')
  assert.equal(monthsText(12), '12 месяцев')
})

test('письмо об оплате картой называет портал, код, срок и сумму', () => {
  const offer = parseProOffer(OFFER_PAYLOAD)
  const link = decodeURIComponent(cardPaymentMailto({ email: offer.contactEmail, domain: offer.portal.domain, code: offer.portal.code, term: offer.terms[3]! }))
  assert.match(link, /^mailto:timesheet@mainsoft\.su\?subject=Оплата Pro картой — kvarc-int\.bitrix24\.ru, код 482137/)
  assert.match(link, /Срок: 12 месяцев/)
})

// --- тексты состояний -----------------------------------------------------------

test('заявка в безопасном режиме честно говорит, что счёт готовится вручную', () => {
  const request = parseProRequest(REQUEST_PAYLOAD)!
  assert.equal(request.full, true)
  const note = describeProRequest(request)
  assert.equal(note.tone, 'warning')
  assert.equal(note.title, 'Заявка УТ-0047 сохранена, счёт готовится')
  assert.match(note.text, /ожидает отправки/)
  assert.match(note.text, /вручную/)
})

test('тексты состояний: повтор отправки, выставлен, оплачен, отменён', () => {
  const base = parseProRequest(REQUEST_PAYLOAD)!
  assert.match(describeProRequest({ ...base, crmState: 'retry' }).title, /ожидает отправки в CRM/)
  const sent = describeProRequest({ ...base, status: 'sent', crmState: 'sent' })
  assert.equal(sent.title, 'Счёт № УТ-0047 от 12.09.2026 сформирован')
  assert.equal(sent.text, 'Оплатите до 18.09.2026. Pro включим после поступления денег.')
  assert.equal(describeProRequest({ ...base, status: 'paid', proPaidUntil: '2027-09-11' }).text, 'Pro включён до 11.09.2027.')
  assert.equal(describeProRequest({ ...base, status: 'cancelled', cancelReason: 'Заменена заявкой УТ-0048' }).text,
    'Причина: Заменена заявкой УТ-0048.')
})

test('таймлайн заявки: до выставления счёта «Счёт готовится» — текущий шаг', () => {
  const request = parseProRequest(REQUEST_PAYLOAD)!
  assert.deepEqual(proRequestTimeline(request).map(step => step.state), ['done', 'now', 'todo', 'todo', 'todo'])
  const paid = proRequestTimeline({ ...request, status: 'paid', crmState: 'sent', proPaidUntil: '2027-09-11' })
  assert.deepEqual(paid.map(step => step.state), ['done', 'done', 'done', 'done', 'done'])
  assert.equal(paid[4]!.hint, 'до 11.09.2027')
})

test('сотруднику без права сервер присылает заявку без реквизитов', () => {
  const limited = parseProRequest({ id: '1', invoice_number: 'УТ-0001', status: 'sent', months: 1, total: '3000.00' })!
  assert.equal(limited.full, false)
  assert.equal(limited.payer, null)
  const fallback = createProForm()
  assert.equal(proFormFromRequest(limited, fallback), fallback)
  const full = proFormFromRequest(parseProRequest(REQUEST_PAYLOAD)!, fallback)
  assert.equal(full.payerInn, '7325148066')
  assert.equal(full.months, 12)
})

test('кнопка в меню по состояниям подписки', () => {
  const today = '2026-09-12'
  assert.deepEqual(resolveProNavButton({ subscription: null, openRequest: false, today }),
    { badge: null, badgeTone: 'info', label: 'Купить Pro', tone: 'outline' })
  const trial = resolveProNavButton({ subscription: { status: 'trial', paidUntil: null, trialUntil: '2026-09-21', graceUntil: null }, openRequest: false, today })
  assert.equal(trial.badge, 'Пробный Pro · 9 дн.')
  assert.equal(trial.label, 'Купить Pro')
  const active = resolveProNavButton({ subscription: { status: 'active', paidUntil: '2027-09-18', trialUntil: null, graceUntil: null }, openRequest: false, today })
  assert.equal(active.label, null)
  assert.equal(active.badge, 'Pro до 18.09.2027')
  const soon = resolveProNavButton({ subscription: { status: 'active', paidUntil: '2026-09-18', trialUntil: null, graceUntil: null }, openRequest: false, today })
  assert.equal(soon.label, 'Продлить Pro · 6 дн.')
  assert.equal(soon.tone, 'warning')
  const expired = resolveProNavButton({ subscription: { status: 'expired', paidUntil: '2026-09-05', trialUntil: null, graceUntil: null }, openRequest: false, today })
  assert.equal(expired.label, 'Pro истёк · продлить')
  assert.equal(expired.tone, 'danger')
  assert.equal(resolveProNavButton({ subscription: null, openRequest: true, today }).label, 'Счёт ждёт оплаты')
})

test('кнопки нет на отчётах, во вкладке задачи и на самой форме', () => {
  assert.equal(shouldShowProNavButton('/'), true)
  assert.equal(shouldShowProNavButton('/finance/billing'), true)
  assert.equal(shouldShowProNavButton('/settings'), true)
  assert.equal(shouldShowProNavButton('/reports/project'), false)
  assert.equal(shouldShowProNavButton('/embedded'), false)
  assert.equal(shouldShowProNavButton('/pro?feature=bdds'), false)
  assert.equal(shouldShowFinanceProFooter(null), true)
  assert.equal(shouldShowFinanceProFooter({ status: 'active', paidUntil: null, trialUntil: null, graceUntil: null }), false)
})

test('карточка «Подписка» в настройках', () => {
  const today = '2026-09-12'
  assert.equal(describeProSubscription({ subscription: null, request: null, today }).badge, 'Pro не подключён')
  const pending = describeProSubscription({ subscription: null, request: parseProRequest(REQUEST_PAYLOAD), today })
  assert.equal(pending.badge, 'Счёт УТ-0047 ждёт оплаты до 18.09.2026')
  assert.equal(pending.action, 'Открыть счёт')
  const trial = describeProSubscription({ subscription: { status: 'trial', paidUntil: null, trialUntil: '2026-09-21', graceUntil: null }, request: null, today })
  assert.equal(trial.badge, 'Пробный Pro до 21.09.2026 · осталось 9 дней')
  const soon = describeProSubscription({ subscription: { status: 'active', paidUntil: '2026-09-18', trialUntil: null, graceUntil: null }, request: null, today })
  assert.equal(soon.badge, 'Pro до 18.09.2026 · осталось 6 дней')
  assert.equal(soon.action, 'Продлить Pro')
  assert.equal(daysUntil('2026-09-18', today), 6)
  assert.equal(daysUntil('мусор', today), null)
})
