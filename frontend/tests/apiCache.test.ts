import test from 'node:test'
import assert from 'node:assert/strict'

import { withRefreshParam } from '../app/utils/apiCache'

// Блокер 2 финального ревью: forceRefresh у getProjectBoard/getHomepagePortfolio
// раньше управлял только браузерным (localStorage) кэшем — сам запрос уходил
// без параметров, и его получал серверный кэш бэкенда. Кэш серверный —
// per-процессный (два процесса за балансировщиком, у каждого своя память):
// сброс в процессе, обработавшем создание проекта, не долетает до другого
// процесса, который может обслужить следующий запрос доски. Симптом:
// "создал и не увидел", примерно через раз. ?refresh=1 — тот же приём, что
// уже есть у getProjectBoardMeta (frontend/app/stores/api.ts) — просит
// бэкенд обойти именно его кэш, а не только браузерный.

test('withRefreshParam: forceRefresh=false — адрес не меняется', () => {
  assert.equal(withRefreshParam('/api/project-board', false), '/api/project-board')
  assert.equal(withRefreshParam('/api/homepage/portfolio', false), '/api/homepage/portfolio')
})

test('withRefreshParam: forceRefresh=true — добавляет ?refresh=1', () => {
  assert.equal(withRefreshParam('/api/project-board', true), '/api/project-board?refresh=1')
  assert.equal(withRefreshParam('/api/homepage/portfolio', true), '/api/homepage/portfolio?refresh=1')
})

test('withRefreshParam: forceRefresh=true на адресе с уже существующим query — дописывает через &', () => {
  assert.equal(withRefreshParam('/api/project-board/meta?foo=1', true), '/api/project-board/meta?foo=1&refresh=1')
})
