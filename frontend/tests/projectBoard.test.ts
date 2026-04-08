import test from 'node:test'
import assert from 'node:assert/strict'

import { buildProjectBoardSummary, upsertProjectBoardCard } from '../app/utils/projectBoard'
import type { ProjectBoardCardRecord } from '../app/types/project-board'

const baseCard: ProjectBoardCardRecord = {
  id: '1',
  project_id: '101',
  project_name: 'Проект 101',
  stage: 'В работе',
  manual_stage: 'В работе',
  is_archived: false,
  archived_at: null,
  project_hours_budget: null,
  hourly_rate: 3000,
  is_support: false,
  curator_user_id: '7',
  curator_name: 'Иван',
  project_start_date: null,
  project_end_date: null,
  company_id: null,
  company_name: null,
  our_legal_entity_id: null,
  our_legal_entity_name: null,
  last_writeoff_at: null,
  last_writeoff_days: 0,
  stage_source: 'manual',
  created_at: null,
  updated_at: null
}

test('upsertProjectBoardCard updates existing card in place by project_id', () => {
  const nextCards = upsertProjectBoardCard(
    [baseCard],
    { ...baseCard, id: '2', project_name: 'Обновленный проект' }
  )

  assert.equal(nextCards.length, 1)
  assert.equal(nextCards[0].id, '2')
  assert.equal(nextCards[0].project_name, 'Обновленный проект')
})

test('buildProjectBoardSummary derives counters from cards', () => {
  const summary = buildProjectBoardSummary([
    baseCard,
    { ...baseCard, id: '2', project_id: '102', is_support: true },
    { ...baseCard, id: '3', project_id: '103', stage: 'Нет списаний 1 месяц' },
    { ...baseCard, id: '4', project_id: '104', stage: 'Нет списаний 3 месяца' },
    { ...baseCard, id: '5', project_id: '105', is_archived: true, archived_at: '2026-04-08' }
  ])

  assert.deepEqual(summary, {
    total_count: 5,
    active_count: 4,
    archived_count: 1,
    support_count: 1,
    inactive_30_count: 1,
    inactive_90_count: 1
  })
})
