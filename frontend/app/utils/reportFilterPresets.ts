/**
 * Сохранённые пресеты фильтра отчётов — «вариант A: родной портал».
 *
 * В строке фильтра человек каждый раз заново набирает одно и то же: период,
 * пять проектов своего отдела, себя в сотрудниках. Пресет запоминает этот
 * набор целиком и возвращает его одним щелчком — как сохранённый фильтр в CRM
 * Битрикса.
 *
 * ГДЕ ХРАНИМ. В localStorage браузера. Серверного места под настройки
 * отчётов в приложении нет: `/api/configuration` — это НАСТРОЙКА ПРИЛОЖЕНИЯ
 * (смарт-процессы, поля), она одна на портал и правится администратором, а
 * `user.option.*` Битрикса кладёт настройки в портал, но через `$b24`, который
 * этим утилитам недоступен и который на вкладке задачи может быть ещё не
 * поднят. Заводить ради пресетов эндпоинт — менять бэкенд, чего в этой работе
 * делать нельзя. Поэтому пресеты локальные, и это честное ограничение: на
 * другом компьютере их не будет.
 *
 * КЛЮЧ — портал плюс пользователь. Один браузер открывает несколько порталов
 * (демостенд, дев, боевой), и «мои проекты» в них разные; на общем компьютере
 * под одним браузером сидят разные люди. Без обеих частей ключа пресеты одного
 * портала подставлялись бы в другой и молча фильтровали отчёт по чужим ID.
 *
 * ПРЕСЕТ ОБЩИЙ НА ВСЕ СЕМЬ ОТЧЁТОВ. Набор фильтров у них один и тот же
 * (период, сотрудники, проекты), и человек, отобравший свой отдел в «Потерях
 * выручки», ждёт тот же отбор в «Дисциплине». Отдельные списки на отчёт
 * заставляли бы сохранять один и тот же набор семь раз.
 *
 * Здесь только ЧИСТЫЕ функции: node:test через tsx не резолвит .vue, и всё,
 * что осталось бы внутри компонента, ревью проверить не смогло бы. Чтение и
 * запись localStorage — в app/composables/useReportFilterPresets.ts.
 */

import type { FilterMode } from '../types/report'

/** Снимок строки фильтра. Ровно то, что отчёт отправляет на сервер. */
export type ReportFilterSnapshot = {
  dateFrom: string
  dateTo: string
  employees: string[]
  employeeMode: FilterMode
  projects: string[]
  projectMode: FilterMode
}

export type ReportFilterPreset = {
  id: string
  name: string
  /** ISO-время создания. Нужно только для порядка в списке. */
  createdAt: string
  filters: ReportFilterSnapshot
}

/**
 * Сколько пресетов держим.
 *
 * Ограничение не про место в localStorage (пресет весит десятки байт), а про
 * список: в выпадашке из сорока сохранённых фильтров искать дольше, чем
 * выставить фильтр заново. Лишние вытесняются самыми старыми.
 */
export const REPORT_PRESETS_LIMIT = 12

/** Максимальная длина имени. Длиннее не влезет в строку выпадашки. */
export const REPORT_PRESET_NAME_MAX = 60

export const REPORT_PRESETS_STORAGE_PREFIX = 'ms-report-presets-v1'

/**
 * Ключ хранилища.
 *
 * Пустые части заменяются на `unknown`, а не выкидывают ключ целиком: если
 * портал ещё не определился (помощник Битрикса поднимается асинхронно), пресеты
 * должны сохраниться хоть куда-то, а не потеряться. Худшее, что случится, —
 * такие пресеты не подхватятся после того, как портал стал известен.
 */
export function buildPresetsStorageKey(scope: {
  portal?: string | null
  userId?: string | number | null
}): string {
  const portal = String(scope.portal || '').trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/+$/, '')
  const userId = String(scope.userId ?? '').trim()

  return `${REPORT_PRESETS_STORAGE_PREFIX}:${portal || 'unknown'}:${userId || 'unknown'}`
}

function normalizeMode(value: unknown): FilterMode {
  return value === 'exclude' ? 'exclude' : 'include'
}

function normalizeIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  const seen = new Set<string>()
  const result: string[] = []

  for (const item of value) {
    const id = String(item ?? '').trim()

    if (!id || seen.has(id)) {
      continue
    }

    seen.add(id)
    result.push(id)
  }

  return result
}

function normalizeDate(value: unknown): string {
  const raw = String(value ?? '').trim()

  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : ''
}

/**
 * Приведение снимка к каноническому виду.
 *
 * Идентификаторы всегда строки: фильтр отдаёт то числа (сотрудники приходят с
 * числовым ID), то строки, и без приведения один и тот же набор не совпал бы
 * сам с собой при сравнении с пресетом.
 */
export function normalizeFilterSnapshot(raw: unknown): ReportFilterSnapshot {
  const source = (raw || {}) as Partial<ReportFilterSnapshot>

  return {
    dateFrom: normalizeDate(source.dateFrom),
    dateTo: normalizeDate(source.dateTo),
    employees: normalizeIds(source.employees),
    employeeMode: normalizeMode(source.employeeMode),
    projects: normalizeIds(source.projects),
    projectMode: normalizeMode(source.projectMode),
  }
}

export function normalizePresetName(value: unknown): string {
  return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, REPORT_PRESET_NAME_MAX)
}

function normalizePreset(raw: unknown): ReportFilterPreset | null {
  const source = (raw || {}) as Partial<ReportFilterPreset>
  const name = normalizePresetName(source.name)
  const id = String(source.id || '').trim()

  if (!name || !id) {
    return null
  }

  return {
    id,
    name,
    createdAt: String(source.createdAt || '').trim(),
    filters: normalizeFilterSnapshot(source.filters),
  }
}

/**
 * Разбор того, что лежит в localStorage.
 *
 * Мусор в хранилище — не ошибка приложения: его могли записать прошлая версия,
 * расширение браузера или человек руками. Возвращаем пустой список, а не
 * падаем: без пресетов отчёт работает, со сломанным экраном — нет.
 */
export function parsePresetsPayload(raw: string | null | undefined): ReportFilterPreset[] {
  if (!raw) {
    return []
  }

  let parsed: unknown

  try {
    parsed = JSON.parse(raw)
  } catch {
    return []
  }

  const list = Array.isArray(parsed)
    ? parsed
    : Array.isArray((parsed as { presets?: unknown })?.presets)
      ? (parsed as { presets: unknown[] }).presets
      : []

  const result: ReportFilterPreset[] = []
  const seenIds = new Set<string>()

  for (const item of list) {
    const preset = normalizePreset(item)

    if (!preset || seenIds.has(preset.id)) {
      continue
    }

    seenIds.add(preset.id)
    result.push(preset)
  }

  return result.slice(0, REPORT_PRESETS_LIMIT)
}

export function serializePresets(presets: ReportFilterPreset[]): string {
  return JSON.stringify(presets.slice(0, REPORT_PRESETS_LIMIT))
}

/**
 * Идентификатор пресета.
 *
 * `seed` параметризован ради теста: `Math.random` в чистой функции сделал бы
 * её непроверяемой, а брать только время нельзя — два пресета, сохранённых в
 * одну миллисекунду, получили бы один ID.
 */
export function buildPresetId(now: Date = new Date(), seed: string = Math.random().toString(36).slice(2, 8)): string {
  return `p${now.getTime().toString(36)}${seed}`
}

export function createPreset(
  name: string,
  snapshot: ReportFilterSnapshot,
  now: Date = new Date(),
  seed?: string
): ReportFilterPreset {
  return {
    id: buildPresetId(now, seed),
    name: normalizePresetName(name),
    createdAt: now.toISOString(),
    filters: normalizeFilterSnapshot(snapshot),
  }
}

/**
 * Добавление пресета в список.
 *
 * Совпадение ИМЕНИ перезаписывает старый пресет на месте — человек, который
 * сохранил «Мой отдел» второй раз, поправил набор, а не завёл второй «Мой
 * отдел». Новые пресеты идут в начало: только что сохранённый нужен сразу.
 */
export function upsertPreset(
  presets: ReportFilterPreset[],
  preset: ReportFilterPreset
): ReportFilterPreset[] {
  const normalizedName = preset.name.toLowerCase()
  const rest = presets.filter(
    item => item.id !== preset.id && item.name.toLowerCase() !== normalizedName
  )

  return [preset, ...rest].slice(0, REPORT_PRESETS_LIMIT)
}

export function removePreset(presets: ReportFilterPreset[], id: string): ReportFilterPreset[] {
  const target = String(id || '').trim()

  return presets.filter(preset => preset.id !== target)
}

export function findPreset(presets: ReportFilterPreset[], id: string): ReportFilterPreset | null {
  const target = String(id || '').trim()

  return presets.find(preset => preset.id === target) || null
}

function sameIds(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false
  }

  const sortedLeft = [...left].sort()
  const sortedRight = [...right].sort()

  return sortedLeft.every((value, index) => value === sortedRight[index])
}

/**
 * Совпадают ли наборы фильтров.
 *
 * Порядок идентификаторов не важен: в списке их отмечают галочками в разном
 * порядке, а отбор от этого не меняется. Режим «кроме» при пустом списке
 * исключений тоже не различаем — отбор в обоих случаях одинаковый.
 */
export function snapshotsEqual(left: ReportFilterSnapshot, right: ReportFilterSnapshot): boolean {
  const a = normalizeFilterSnapshot(left)
  const b = normalizeFilterSnapshot(right)

  if (a.dateFrom !== b.dateFrom || a.dateTo !== b.dateTo) {
    return false
  }

  if (!sameIds(a.employees, b.employees) || !sameIds(a.projects, b.projects)) {
    return false
  }

  const employeeModeMatters = a.employees.length > 0 || b.employees.length > 0
  const projectModeMatters = a.projects.length > 0 || b.projects.length > 0

  if (employeeModeMatters && a.employeeMode !== b.employeeMode) {
    return false
  }

  return !(projectModeMatters && a.projectMode !== b.projectMode)
}

/** Какой из сохранённых пресетов сейчас выставлен. null — ни один. */
export function findMatchingPreset(
  presets: ReportFilterPreset[],
  snapshot: ReportFilterSnapshot
): ReportFilterPreset | null {
  return presets.find(preset => snapshotsEqual(preset.filters, snapshot)) || null
}

function formatDateLabel(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)

  return match ? `${match[3]}.${match[2]}.${match[1]}` : ''
}

/** Подпись периода для строки фильтра: «01.09.2026 – 30.09.2026». */
export function formatPeriodLabel(dateFrom: string, dateTo: string): string {
  const from = formatDateLabel(normalizeDate(dateFrom))
  const to = formatDateLabel(normalizeDate(dateTo))

  if (from && to) {
    return `${from} – ${to}`
  }

  return from || to || 'период не выбран'
}

function pluralize(count: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(count) % 100
  const mod10 = mod100 % 10

  if (mod100 >= 11 && mod100 <= 14) {
    return many
  }

  if (mod10 === 1) {
    return one
  }

  if (mod10 >= 2 && mod10 <= 4) {
    return few
  }

  return many
}

function describeSelection(count: number, mode: FilterMode, one: string, few: string, many: string): string {
  if (count === 0) {
    return 'все'
  }

  const word = pluralize(count, one, few, many)

  return mode === 'exclude' ? `кроме ${count} ${word}` : `${count} ${word}`
}

/**
 * Человеческое описание пресета — вторая строка в выпадашке.
 *
 * Показываем период и КОЛИЧЕСТВО отобранных, а не их названия: пресет обычно
 * про пять–пятнадцать проектов, перечислить их в строке невозможно, а число
 * сразу отвечает на вопрос «это тот отбор или широкий».
 */
export function describeFilterSnapshot(snapshot: ReportFilterSnapshot): string {
  const normalized = normalizeFilterSnapshot(snapshot)

  return [
    formatPeriodLabel(normalized.dateFrom, normalized.dateTo),
    `сотрудники: ${describeSelection(normalized.employees.length, normalized.employeeMode, 'человек', 'человека', 'человек')}`,
    `проекты: ${describeSelection(normalized.projects.length, normalized.projectMode, 'проект', 'проекта', 'проектов')}`,
  ].join(' · ')
}

/** Выставлен ли хоть один отбор — по нему рисуется кнопка «Сбросить». */
export function hasActiveSelection(snapshot: ReportFilterSnapshot): boolean {
  const normalized = normalizeFilterSnapshot(snapshot)

  return normalized.employees.length > 0 || normalized.projects.length > 0
}
