import test from 'node:test'
import assert from 'node:assert/strict'

import {
  describeBillingError,
  readConflictDocumentId,
  readErrorCode,
  readErrorStatus,
} from '../app/utils/billingErrors'

function httpError(status: number, data: Record<string, unknown> = {}) {
  const error = new Error('Request failed') as Error & { status: number, data: Record<string, unknown> }
  error.status = status
  error.data = data

  return error
}

test('readErrorStatus: статус читается во всех трёх формах ofetch', () => {
  assert.equal(readErrorStatus({ status: 409 }), 409)
  assert.equal(readErrorStatus({ statusCode: 403 }), 403)
  assert.equal(readErrorStatus({ response: { status: 500 } }), 500)
  assert.equal(readErrorStatus(new Error('нет статуса')), null)
  assert.equal(readErrorStatus('строка'), null)
})

test('readErrorCode: код берётся из тела ответа', () => {
  assert.equal(readErrorCode(httpError(403, { code: 'feature_disabled' })), 'feature_disabled')
  assert.equal(readErrorCode({ response: { _data: { code: 'act_template_missing' } } }), 'act_template_missing')
  assert.equal(readErrorCode(new Error('без тела')), '')
})

test('readConflictDocumentId: ссылку на документ ищем во всех разумных написаниях', () => {
  assert.equal(readConflictDocumentId(httpError(409, { document_id: 17 })), '17')
  assert.equal(readConflictDocumentId(httpError(409, { documentId: '18' })), '18')
  assert.equal(readConflictDocumentId(httpError(409, { existing_document_id: 19 })), '19')
  assert.equal(readConflictDocumentId(httpError(409, { document: { id: 20 } })), '20')
  assert.equal(readConflictDocumentId(httpError(409, {})), '')
})

test('describeBillingError: 409 — «уже выставлено» со ссылкой, а не «ошибка сервера»', () => {
  const view = describeBillingError(httpError(409, { document_id: 17 }))

  assert.equal(view.title, 'Эти часы уже выставлены')
  assert.equal(view.documentId, '17')
  assert.match(view.text, /откройте его/i)
})

test('describeBillingError: 409 без идентификатора отправляет в реестр', () => {
  const view = describeBillingError(httpError(409, {}))

  assert.equal(view.documentId, '')
  assert.match(view.text, /реестре/)
})

test('describeBillingError: коды печати акта разобраны отдельно', () => {
  const missing = describeBillingError(httpError(400, { code: 'act_template_missing' }))
  assert.match(missing.title, /шаблона акта/)
  assert.match(missing.text, /XLSX/)

  const unavailable = describeBillingError(httpError(503, { code: 'documentgenerator_unavailable' }))
  assert.match(unavailable.title, /Генератор документов/)
  assert.match(unavailable.text, /Счёт при этом выставлен/)
})

test('describeBillingError: feature_disabled объясняет, что реестр и отмена остались', () => {
  const view = describeBillingError(httpError(403, { code: 'feature_disabled' }))

  assert.equal(view.permanent, true)
  assert.match(view.text, /реестр и отмена/i)
})

test('describeBillingError: 403 без кода — это про права', () => {
  const view = describeBillingError(httpError(403, { error: 'Недостаточно прав' }))

  assert.equal(view.title, 'Недостаточно прав')
  assert.match(view.text, /Бухгалтерия/)
})

test('describeBillingError: подменённая клиентом ошибка 403 (без статуса) тоже узнаётся', () => {
  // app/stores/api.ts на 403 подменяет ошибку голым Error с серверным текстом,
  // статус при этом теряется — разбор обязан пережить и такую форму.
  const view = describeBillingError(new Error('Недостаточно прав'))

  assert.equal(view.title, 'Недостаточно прав')
})

test('describeBillingError: 404 говорит, что бэкенда может ещё не быть', () => {
  const view = describeBillingError(httpError(404, {}))

  assert.equal(view.title, 'Не найдено')
  assert.match(view.text, /бэкенд/i)
})

test('describeBillingError: обрыв сети — не «ошибка сервера»', () => {
  const view = describeBillingError(new TypeError('fetch failed'))

  assert.equal(view.title, 'Нет связи с сервером')
  assert.match(view.text, /не изменились/)
})

test('describeBillingError: 429 отдаёт общий текст лимитера', () => {
  const view = describeBillingError(httpError(429, {}))

  assert.match(view.text, /через минуту/)
  assert.equal(view.permanent, false)
})

test('describeBillingError: 500 предлагает повтор и диагностику', () => {
  const view = describeBillingError(httpError(500, { error: 'Сломалось' }))

  assert.equal(view.title, 'Сервер не справился')
  assert.equal(view.text, 'Сломалось')
})

test('describeBillingError: 400 показывает серверное объяснение отбора', () => {
  const view = describeBillingError(httpError(400, { error: 'Период не задан' }))

  assert.equal(view.title, 'Сервер не принял отбор')
  assert.equal(view.text, 'Период не задан')
})

test('describeBillingError: машинное сообщение ofetch человеку не показывается', () => {
  const view = describeBillingError(new Error('[POST] "/api/billing/preview": 404 Not Found'))

  assert.doesNotMatch(view.text, /\[POST\]/)
  assert.match(view.text, /без объяснения/)
})

test('describeBillingError: серверный текст без статуса всё же доходит до человека', () => {
  const view = describeBillingError(new Error('Смарт-процесс не настроен'))

  assert.equal(view.text, 'Смарт-процесс не настроен')
})

test('readConflictDocumentId: сервер отдаёт список document_ids — берём первый', () => {
  assert.equal(readConflictDocumentId(httpError(409, { document_ids: ['21', '22'] })), '21')
  assert.equal(readConflictDocumentId(httpError(409, { document_ids: [] })), '')
})

test('describeBillingError: 409 already_invoiced со списком документов даёт ссылку', () => {
  const view = describeBillingError(httpError(409, {
    code: 'already_invoiced',
    error: 'Эти списания уже выставлены — счёт по ним существует.',
    document_ids: ['21'],
  }))

  assert.equal(view.title, 'Эти часы уже выставлены')
  assert.equal(view.documentId, '21')
})

test('describeBillingError: 409 billing_busy — это «повторите», а не «уже выставлено»', () => {
  const view = describeBillingError(httpError(409, {
    code: 'billing_busy',
    error: 'Кто-то уже выставляет счёт на этом портале. Повторите через несколько секунд.',
  }))

  assert.match(view.title, /кто-то ещё/i)
  assert.equal(view.documentId, '')
  assert.equal(view.permanent, false)
})

test('describeBillingError: 409 already_cancelled не притворяется конфликтом выставления', () => {
  const view = describeBillingError(httpError(409, { code: 'already_cancelled', error: 'Документ уже отменён.' }))

  assert.equal(view.title, 'Документ уже отменён')
  assert.equal(view.documentId, '')
})
