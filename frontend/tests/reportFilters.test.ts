import test from 'node:test'
import assert from 'node:assert/strict'

import { applyProjectPresetToFilters, buildReportSearchParams, injectReportOption } from '../app/utils/reportFilters'

test('buildReportSearchParams encodes include and exclude filters', () => {
  const params = buildReportSearchParams(
    '2026-04-01',
    '2026-04-30',
    { ids: [1, '2'], mode: 'exclude' },
    { ids: ['15'], mode: 'include' }
  )

  assert.equal(params.get('date_from'), '2026-04-01')
  assert.equal(params.get('date_to'), '2026-04-30')
  assert.deepEqual(params.getAll('employee_ids[]'), ['1', '2'])
  assert.deepEqual(params.getAll('project_ids[]'), ['15'])
  assert.equal(params.get('employee_mode'), 'exclude')
  assert.equal(params.get('project_mode'), null)
})

test('injectReportOption prepends missing option and avoids duplicates', () => {
  const options = [{ id: '10', name: 'Проект 10' }]

  const withInjected = injectReportOption(options, { id: '20', name: 'Проект 20' })
  assert.equal(withInjected.length, 2)
  assert.equal(String(withInjected[0].id), '20')

  const duplicate = injectReportOption(withInjected, { id: '20', name: 'Проект 20' })
  assert.equal(duplicate.length, 2)
})

test('applyProjectPresetToFilters injects preset project and returns autogenerate flag', () => {
  let selectedProjects: string[] = []
  let filterMode = 'exclude'
  let options = [{ id: '1', name: 'Первый проект' }]

  const shouldAutogenerate = applyProjectPresetToFilters(
    {
      project_id: '42',
      project_name: 'Ключевой проект',
      autogenerate: '1'
    },
    options,
    (nextIds) => {
      selectedProjects = nextIds
    },
    (nextMode) => {
      filterMode = nextMode
    },
    (nextOptions) => {
      options = nextOptions
    }
  )

  assert.equal(shouldAutogenerate, true)
  assert.deepEqual(selectedProjects, ['42'])
  assert.equal(filterMode, 'include')
  assert.equal(String(options[0].id), '42')
})
