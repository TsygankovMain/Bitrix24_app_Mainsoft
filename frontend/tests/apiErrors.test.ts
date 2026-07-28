import test from 'node:test'
import assert from 'node:assert/strict'

import { isRateLimitError, RATE_LIMIT_NOTICE_TEXT } from '../app/utils/apiErrors'

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
