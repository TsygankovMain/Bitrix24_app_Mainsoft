import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildPresetId,
  buildPresetsStorageKey,
  createPreset,
  describeFilterSnapshot,
  findMatchingPreset,
  findPreset,
  formatPeriodLabel,
  hasActiveSelection,
  normalizeFilterSnapshot,
  normalizePresetName,
  parsePresetsPayload,
  removePreset,
  REPORT_PRESETS_LIMIT,
  serializePresets,
  snapshotsEqual,
  upsertPreset,
  type ReportFilterSnapshot,
} from '../app/utils/reportFilterPresets'

function makeSnapshot(overrides: Partial<ReportFilterSnapshot> = {}): ReportFilterSnapshot {
  return normalizeFilterSnapshot({
    dateFrom: '2026-09-01',
    dateTo: '2026-09-30',
    employees: ['11', '42'],
    employeeMode: 'include',
    projects: ['101'],
    projectMode: 'include',
    ...overrides,
  })
}

// --- Ключ хранилища ---

test('buildPresetsStorageKey: портал и пользователь попадают в ключ', () => {
  const key = buildPresetsStorageKey({ portal: 'https://mainsoft.bitrix24.ru/', userId: 11 })

  assert.equal(key, 'ms-report-presets-v1:mainsoft.bitrix24.ru:11')
})

test('buildPresetsStorageKey: разные порталы и разные люди не делят один ключ', () => {
  const a = buildPresetsStorageKey({ portal: 'a.bitrix24.ru', userId: 11 })
  const b = buildPresetsStorageKey({ portal: 'b.bitrix24.ru', userId: 11 })
  const c = buildPresetsStorageKey({ portal: 'a.bitrix24.ru', userId: 42 })

  assert.notEqual(a, b)
  assert.notEqual(a, c)
})

test('buildPresetsStorageKey: пустые части не выкидывают ключ целиком', () => {
  assert.equal(buildPresetsStorageKey({}), 'ms-report-presets-v1:unknown:unknown')
})

// --- Нормализация снимка ---

test('normalizeFilterSnapshot: идентификаторы приводятся к строкам и дедуплицируются', () => {
  const snapshot = normalizeFilterSnapshot({
    dateFrom: '2026-09-01',
    dateTo: '2026-09-30',
    employees: [11, '11', 42, '', null],
    projects: ['101', '101'],
  })

  assert.deepEqual(snapshot.employees, ['11', '42'])
  assert.deepEqual(snapshot.projects, ['101'])
})

test('normalizeFilterSnapshot: кривые даты не пролезают в отбор', () => {
  const snapshot = normalizeFilterSnapshot({ dateFrom: '01.09.2026', dateTo: 'вчера' })

  assert.equal(snapshot.dateFrom, '')
  assert.equal(snapshot.dateTo, '')
})

test('normalizeFilterSnapshot: неизвестный режим считается включающим', () => {
  assert.equal(normalizeFilterSnapshot({ employeeMode: 'что-то' }).employeeMode, 'include')
  assert.equal(normalizeFilterSnapshot({ projectMode: 'exclude' }).projectMode, 'exclude')
})

test('normalizePresetName: пробелы схлопываются, длина обрезается', () => {
  assert.equal(normalizePresetName('  Мой   отдел  '), 'Мой отдел')
  assert.equal(normalizePresetName('я'.repeat(200)).length, 60)
})

// --- Хранилище ---

test('parsePresetsPayload: мусор в localStorage не роняет экран', () => {
  assert.deepEqual(parsePresetsPayload(null), [])
  assert.deepEqual(parsePresetsPayload(''), [])
  assert.deepEqual(parsePresetsPayload('{не json'), [])
  assert.deepEqual(parsePresetsPayload('{"presets":"строка"}'), [])
})

test('parsePresetsPayload: пресеты без имени или без ID отбрасываются', () => {
  const raw = JSON.stringify([
    { id: 'p1', name: 'Мой отдел', filters: {} },
    { id: 'p2', name: '   ', filters: {} },
    { name: 'Без ID', filters: {} },
  ])

  assert.deepEqual(parsePresetsPayload(raw).map(preset => preset.id), ['p1'])
})

test('parsePresetsPayload: дубли по ID схлопываются', () => {
  const raw = JSON.stringify([
    { id: 'p1', name: 'Первый', filters: {} },
    { id: 'p1', name: 'Он же', filters: {} },
  ])

  assert.equal(parsePresetsPayload(raw).length, 1)
})

test('serializePresets и parsePresetsPayload переживают полный круг', () => {
  const preset = createPreset('Мой отдел', makeSnapshot(), new Date('2026-09-11T12:00:00Z'), 'abc123')
  const restored = parsePresetsPayload(serializePresets([preset]))

  assert.deepEqual(restored, [preset])
})

test('buildPresetId: один и тот же момент даёт разные ID при разной затравке', () => {
  const now = new Date('2026-09-11T12:00:00Z')

  assert.notEqual(buildPresetId(now, 'aaa'), buildPresetId(now, 'bbb'))
})

// --- Список пресетов ---

test('upsertPreset: новый пресет встаёт первым', () => {
  const first = createPreset('Первый', makeSnapshot(), new Date(), 'a')
  const second = createPreset('Второй', makeSnapshot(), new Date(), 'b')

  assert.deepEqual(upsertPreset([first], second).map(preset => preset.name), ['Второй', 'Первый'])
})

test('upsertPreset: сохранение под тем же именем правит пресет, а не плодит близнеца', () => {
  const old = createPreset('Мой отдел', makeSnapshot(), new Date(), 'a')
  const fresh = createPreset('мой отдел', makeSnapshot({ projects: ['777'] }), new Date(), 'b')
  const list = upsertPreset([old], fresh)

  assert.equal(list.length, 1)
  assert.deepEqual(list[0].filters.projects, ['777'])
})

test('upsertPreset: список не растёт выше предела, вытесняются самые старые', () => {
  let list = [] as ReturnType<typeof createPreset>[]

  for (let index = 0; index < REPORT_PRESETS_LIMIT + 3; index += 1) {
    list = upsertPreset(list, createPreset(`Пресет ${index}`, makeSnapshot(), new Date(), `s${index}`))
  }

  assert.equal(list.length, REPORT_PRESETS_LIMIT)
  assert.equal(list[0].name, `Пресет ${REPORT_PRESETS_LIMIT + 2}`)
})

test('removePreset и findPreset работают по ID', () => {
  const preset = createPreset('Мой отдел', makeSnapshot(), new Date(), 'a')

  assert.equal(findPreset([preset], preset.id)?.name, 'Мой отдел')
  assert.equal(findPreset([preset], 'нет такого'), null)
  assert.deepEqual(removePreset([preset], preset.id), [])
})

// --- Сравнение наборов ---

test('snapshotsEqual: порядок идентификаторов не важен', () => {
  assert.equal(
    snapshotsEqual(makeSnapshot({ employees: ['11', '42'] }), makeSnapshot({ employees: ['42', '11'] })),
    true
  )
})

test('snapshotsEqual: разный период — разные наборы', () => {
  assert.equal(snapshotsEqual(makeSnapshot(), makeSnapshot({ dateTo: '2026-09-15' })), false)
})

test('snapshotsEqual: режим «кроме» при пустом списке ничего не меняет', () => {
  const left = makeSnapshot({ employees: [], employeeMode: 'exclude', projects: [], projectMode: 'exclude' })
  const right = makeSnapshot({ employees: [], employeeMode: 'include', projects: [], projectMode: 'include' })

  assert.equal(snapshotsEqual(left, right), true)
})

test('snapshotsEqual: при непустом списке режим различает наборы', () => {
  const left = makeSnapshot({ projects: ['101'], projectMode: 'exclude' })
  const right = makeSnapshot({ projects: ['101'], projectMode: 'include' })

  assert.equal(snapshotsEqual(left, right), false)
})

test('findMatchingPreset: находит выставленный сейчас пресет', () => {
  const preset = createPreset('Мой отдел', makeSnapshot(), new Date(), 'a')
  const other = createPreset('Другой', makeSnapshot({ projects: ['999'] }), new Date(), 'b')

  assert.equal(findMatchingPreset([other, preset], makeSnapshot())?.id, preset.id)
  assert.equal(findMatchingPreset([other], makeSnapshot()), null)
})

// --- Подписи ---

test('formatPeriodLabel: даты печатаются по-русски', () => {
  assert.equal(formatPeriodLabel('2026-09-01', '2026-09-30'), '01.09.2026 – 30.09.2026')
  assert.equal(formatPeriodLabel('', ''), 'период не выбран')
})

test('describeFilterSnapshot: период и количества, а не перечисление названий', () => {
  const text = describeFilterSnapshot(makeSnapshot())

  assert.match(text, /01\.09\.2026 – 30\.09\.2026/)
  assert.match(text, /сотрудники: 2 человека/)
  assert.match(text, /проекты: 1 проект/)
})

test('describeFilterSnapshot: пустой отбор читается как «все»', () => {
  const text = describeFilterSnapshot(makeSnapshot({ employees: [], projects: [] }))

  assert.match(text, /сотрудники: все/)
  assert.match(text, /проекты: все/)
})

test('describeFilterSnapshot: режим «кроме» так и написан', () => {
  const text = describeFilterSnapshot(makeSnapshot({ projects: ['1', '2', '3', '4', '5'], projectMode: 'exclude' }))

  assert.match(text, /проекты: кроме 5 проектов/)
})

test('hasActiveSelection: кнопка «Сбросить» нужна только при заданном отборе', () => {
  assert.equal(hasActiveSelection(makeSnapshot()), true)
  assert.equal(hasActiveSelection(makeSnapshot({ employees: [], projects: [] })), false)
})
