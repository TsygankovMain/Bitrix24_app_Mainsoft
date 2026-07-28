import test from 'node:test'
import assert from 'node:assert/strict'

import { isRateLimitError, markRateLimitFatal, RATE_LIMIT_NOTICE_TEXT, shouldTreatAsFatalError } from '../app/utils/apiErrors'

// --- isRateLimitError ---
//
// Контекст (критическая находка ревью, см.
// .superpowers/sdd/2026-07-28-project-references-from-db/critical-429-report.md):
// у /api/project-board/meta (ветка ?refresh=1) и /api/project-board/sync есть
// лимитеры (board_meta_refresh и sync — 6 запросов/60 секунд на аккаунт, см.
// backends/python/api/main/utils/decorators/rate_limit.py и views.py). При
// превышении бэкенд отвечает HTTP 429 с телом {"error": "..."}. ofetch на
// не-2xx бросает исключение — в зависимости от версии статус лежит в
// `.response.status`, `.status` или `.statusCode`, поэтому проверяем все три
// формы (тот же приём, что уже проверен в companySearch.test.ts для
// search_project_board_companies).
//
// frontend/app/pages/projects/index.client.vue (refreshReferenceOptions,
// syncBoard) зовёт именно isRateLimitError(error) в catch, чтобы решить: если
// true — лёгкое самоочищающееся уведомление через showStatus('warning', ...)
// и БЕЗ вызова processErrorGlobal; если false — как раньше, showStatus('error',
// ...) и processErrorGlobal(error) (который единственный в этом приложении
// зовёт showError({..., fatal: true}), рендерящий frontend/app/error.vue —
// экран без пути лёгкого возврата, см. :clear="false" там же). Поэтому сам
// факт, что isRateLimitError(error) === true для формы ошибки 429 от этих
// эндпоинтов, и есть проверяемый здесь инвариант: «429 не приводит к вызову
// showError с признаком фатальности».

test('isRateLimitError: узнаёт 429 в разных формах ошибки ofetch', () => {
  assert.equal(isRateLimitError({ response: { status: 429 } }), true)
  assert.equal(isRateLimitError({ status: 429 }), true)
  assert.equal(isRateLimitError({ statusCode: 429 }), true)
})

test('isRateLimitError: 429 от getProjectBoardMeta (?refresh=1) не приводит к вызову showError с признаком фатальности', () => {
  // Форма ошибки, которую реально бросает $api (ofetch) на теле
  // {"error": "Слишком много запросов, повторите через минуту"} с HTTP 429 —
  // см. backends/python/api/main/utils/decorators/rate_limit.py:64-68 и
  // frontend/app/stores/api.ts::getProjectBoardMeta (ветка forceRefresh
  // добавляет ?refresh=1, за которым стоит лимитер board_meta_refresh).
  const rateLimitedMetaError = {
    response: {
      status: 429,
      _data: { error: 'Слишком много запросов, повторите через минуту' }
    }
  }

  assert.equal(isRateLimitError(rateLimitedMetaError), true)
})

test('isRateLimitError: 429 от syncProjectCards (лимитер "sync") тоже распознаётся', () => {
  const rateLimitedSyncError = {
    response: {
      status: 429,
      _data: { error: 'Слишком много запросов, повторите через минуту' }
    }
  }

  assert.equal(isRateLimitError(rateLimitedSyncError), true)
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

// --- RATE_LIMIT_NOTICE_TEXT ---

test('RATE_LIMIT_NOTICE_TEXT: упоминает "слишком много запросов" и предлагает подождать минуту', () => {
  assert.match(RATE_LIMIT_NOTICE_TEXT, /слишком много запросов/i)
  assert.match(RATE_LIMIT_NOTICE_TEXT, /минуту/i)
})

// --- shouldTreatAsFatalError / markRateLimitFatal ---
//
// Контекст (см. .superpowers/sdd/2026-07-28-project-references-from-db/critical-429-central-report.md):
// точечная починка 7c0f58f закрыла 429 только в двух местах
// frontend/app/pages/projects/index.client.vue (refreshReferenceOptions,
// syncBoard). Автор коммита сам предупредил: защиты на уровне
// useAppInit.ts нет, следующий лимитированный эндпоинт снова получит
// фатальный экран. Предупреждение сбылось в тот же день: 45e028b добавил
// лимитер config_save_sync на save_configuration, а обработчик
// frontend/app/pages/settings/mapping.client.vue::handleSave на 429 без
// .data.validation падает в processErrorGlobal(e) без своей ветки — то
// есть ДО этой правки фатальный экран (см. следующий тест ниже).
//
// processErrorGlobal (frontend/app/composables/useAppInit.ts) — единственное
// место всего приложения, которое зовёт showError({fatal:true}) (рендерит
// frontend/app/error.vue, :clear="false", без пути лёгкого возврата). Оно
// теперь вызывает именно shouldTreatAsFatalError, поэтому решение
// действует для ЛЮБОГО catch, который просто зовёт processErrorGlobal(e), —
// то есть для settings/mapping.client.vue, и для всех остальных ~20
// экранов с этим же паттерном, включая ещё не написанные.
//
// Не все 429 одинаковы: get_token (@rate_limit("get_token", 10, 60,
// key="ip_domain") — backends/python/api/main/views.py) — единственный
// $api-вызов внутри initApp()/api.init()/reinitToken(); без токена ни один
// другой запрос приложения не пройдёт, так что лёгкий тост оставил бы
// человека на пустом экране без объяснения. initApp() явно помечает эту
// ошибку через markRateLimitFatal, возвращая старое поведение только для
// неё. shouldTreatAsFatalError — единственное место, которое знает про оба
// правила («429 не фатален» и «кроме явно помеченных»), поэтому проверяется
// здесь как чистая функция (frontend/app/composables/useAppInit.ts зовёт
// showError через auto-import Nuxt, а .vue не резолвится через tsx/node:test
// — та же причина, что и в остальном файле).

test('shouldTreatAsFatalError: 429 без явной пометки — НЕ фатальна (безопасное поведение по умолчанию)', () => {
  assert.equal(shouldTreatAsFatalError({ response: { status: 429 } }), false)
  assert.equal(shouldTreatAsFatalError({ status: 429 }), false)
  assert.equal(shouldTreatAsFatalError({ statusCode: 429 }), false)
})

test('shouldTreatAsFatalError: сценарий handleSave — 429 от config_save_sync без .data.validation больше не фатален', () => {
  // Форма ошибки, которую $api реально бросает на 429 от config_save_sync
  // (backends/python/api/main/views.py::_save_configuration_with_project_sync).
  // Именно эта форма раньше долетала до processErrorGlobal(e) в
  // frontend/app/pages/settings/mapping.client.vue::handleSave, потому что
  // errData?.validation ложно (лимитер отвечает {"error": "..."}, без
  // .validation) — см. отдельный тест ниже, что ветка валидации по-прежнему
  // отрабатывает раньше и это поведение не задето.
  const rateLimitedSaveError = {
    response: { status: 429, _data: { error: 'Слишком много запросов, повторите через минуту' } },
    data: { error: 'Слишком много запросов, повторите через минуту' }
  }

  assert.equal(shouldTreatAsFatalError(rateLimitedSaveError), false)
})

test('shouldTreatAsFatalError: ошибка валидации Project SPA (нет статуса 429) остаётся фатальной — ветка errData.validation в handleSave срабатывает раньше и сюда не доходит', () => {
  const validationError = {
    response: { status: 400 },
    data: { validation: { ok: false }, error: 'Конфигурация Project SPA не прошла валидацию.' }
  }

  assert.equal(shouldTreatAsFatalError(validationError), true)
})

test('shouldTreatAsFatalError: явный опт-ин markRateLimitFatal возвращает старое поведение (случай get_token)', () => {
  const error = markRateLimitFatal({ response: { status: 429 } })
  assert.equal(shouldTreatAsFatalError(error), true)
})

test('shouldTreatAsFatalError: 500/403/сеть — как и раньше, всегда фатальны; пометка на них ни на что не влияет', () => {
  assert.equal(shouldTreatAsFatalError({ response: { status: 500 } }), true)
  assert.equal(shouldTreatAsFatalError({ response: { status: 403 } }), true)
  assert.equal(shouldTreatAsFatalError(new Error('network down')), true)
  assert.equal(shouldTreatAsFatalError(markRateLimitFatal({ response: { status: 500 } })), true)
})

test('shouldTreatAsFatalError: не падает на мусорных значениях (ведёт себя как раньше — фатально)', () => {
  assert.equal(shouldTreatAsFatalError(null), true)
  assert.equal(shouldTreatAsFatalError(undefined), true)
  assert.equal(shouldTreatAsFatalError('429'), true)
})

test('markRateLimitFatal: возвращает тот же объект (годится для throw markRateLimitFatal(error) без потери ссылки)', () => {
  const error = { response: { status: 429 } }
  assert.equal(markRateLimitFatal(error), error)
})

test('markRateLimitFatal: не падает на не-объектных значениях, отдаёт их как есть', () => {
  assert.equal(markRateLimitFatal(null), null)
  assert.equal(markRateLimitFatal(undefined), undefined)
  assert.equal(markRateLimitFatal('429'), '429')
})
