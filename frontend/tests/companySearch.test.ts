import test from 'node:test'
import assert from 'node:assert/strict'

import {
  classifyCompanySearchError,
  companySearchNoticeText,
  createCompanySearchGate,
  isRateLimitError,
  normalizeCompanyQuery,
  shouldSearchCompanies,
} from '../app/utils/companySearch'

// --- normalizeCompanyQuery ---

test('normalizeCompanyQuery: обрезает пробелы по краям, середину не трогает', () => {
  assert.equal(normalizeCompanyQuery('  Ромашка  '), 'Ромашка')
  assert.equal(normalizeCompanyQuery('Рога и копыта'), 'Рога и копыта')
})

test('normalizeCompanyQuery: не падает на null/undefined', () => {
  assert.equal(normalizeCompanyQuery(null as unknown as string), '')
  assert.equal(normalizeCompanyQuery(undefined as unknown as string), '')
})

// --- shouldSearchCompanies ---

test('shouldSearchCompanies: запрос короче двух символов не идёт на сервер', () => {
  assert.equal(shouldSearchCompanies(''), false)
  assert.equal(shouldSearchCompanies('р'), false)
})

test('shouldSearchCompanies: запрос из одних пробелов не идёт на сервер', () => {
  assert.equal(shouldSearchCompanies('   '), false)
  assert.equal(shouldSearchCompanies('\t\n'), false)
})

test('shouldSearchCompanies: запрос из 10 цифр (похож на ИНН) идёт на сервер', () => {
  assert.equal(shouldSearchCompanies('1234567890'), true)
})

test('shouldSearchCompanies: ровно два непробельных символа — граница, тоже идёт', () => {
  assert.equal(shouldSearchCompanies('оо'), true)
  assert.equal(shouldSearchCompanies('  оо  '), true)
})

// --- createCompanySearchGate ---

test('createCompanySearchGate: повторный тот же запрос в пределах задержки не порождает второй вызов', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  assert.equal(gate.shouldTrigger('Ромашка'), false)
  // тот же запрос после нормализации (пробелы по краям) — тоже повтор
  assert.equal(gate.shouldTrigger('  Ромашка  '), false)
})

test('createCompanySearchGate: другой запрос снова порождает вызов', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  assert.equal(gate.shouldTrigger('Одуванчик'), true)
})

test('createCompanySearchGate: короткий запрос никогда не триггерит и сбрасывает память', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  assert.equal(gate.shouldTrigger('р'), false)
  // после короткого запроса память "последнего запроса" сброшена — тот же
  // валидный запрос, что уже был, снова триггерит, а не считается повтором
  assert.equal(gate.shouldTrigger('Ромашка'), true)
})

test('createCompanySearchGate: reset() возвращает гейт в чистое состояние', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  gate.reset()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
})

// --- isRateLimitError / classifyCompanySearchError / companySearchNoticeText ---
//
// Бэкенд (backends/python/api/main/utils/decorators/rate_limit.py) отвечает
// на превышение лимита HTTP 429 с телом {"error": "..."} — формой, которая
// НЕ совпадает с обычным ответом {companies, truncated, failed}. ofetch на
// не-2xx бросает исключение с `.response.status`/`.status`/`.statusCode` —
// проверяем все три формы, потому что код, который ловит ошибку, не всегда
// заранее знает, какая версия ofetch её создала.

test('isRateLimitError: узнаёт 429 в разных формах ошибки ofetch', () => {
  assert.equal(isRateLimitError({ response: { status: 429 } }), true)
  assert.equal(isRateLimitError({ status: 429 }), true)
  assert.equal(isRateLimitError({ statusCode: 429 }), true)
})

test('isRateLimitError: не путает 429 с другими статусами и обычным сбоем сети', () => {
  assert.equal(isRateLimitError({ response: { status: 500 } }), false)
  assert.equal(isRateLimitError({ response: { status: 403 } }), false)
  assert.equal(isRateLimitError(new Error('network down')), false)
})

test('isRateLimitError: не падает на мусорных значениях', () => {
  assert.equal(isRateLimitError(null), false)
  assert.equal(isRateLimitError(undefined), false)
  assert.equal(isRateLimitError('429'), false)
  assert.equal(isRateLimitError(429), false)
})

test('classifyCompanySearchError: 429 — rate-limited, любая другая ошибка — unavailable', () => {
  assert.equal(classifyCompanySearchError({ response: { status: 429 } }), 'rate-limited')
  assert.equal(classifyCompanySearchError({ response: { status: 500 } }), 'unavailable')
  assert.equal(classifyCompanySearchError(new TypeError('boom')), 'unavailable')
})

test('companySearchNoticeText: у лимитера и недоступности разный текст, не похожий на "ничего не найдено"', () => {
  const rateLimited = companySearchNoticeText('rate-limited')
  const unavailable = companySearchNoticeText('unavailable')

  assert.match(rateLimited, /слишком много запросов/i)
  assert.match(unavailable, /битрикс/i)
  assert.notEqual(rateLimited, unavailable)
})

test('companySearchNoticeText: без причины — пустая строка (нет повода что-то показывать)', () => {
  assert.equal(companySearchNoticeText(null), '')
  assert.equal(companySearchNoticeText(undefined), '')
})
