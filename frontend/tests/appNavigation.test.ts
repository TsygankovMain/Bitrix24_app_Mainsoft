import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildAppNavigation,
  buildOverflowSection,
  collectSectionRoutes,
  estimateNavSectionWidth,
  isNavLinkActive,
  normalizeNavPath,
  resolveActiveSectionId,
  shouldShowSectionNavigation,
  splitNavigationByWidth,
  toNavigationMenuItems,
  NAV_MORE_LABEL,
  type NavSection,
} from '../app/utils/appNavigation'

const BASE_OPTIONS = {
  financeBddsEnabled: false,
  financeBillingEnabled: false,
}

// --- Состав меню ---
//
// Смысл проверок: ни одна ссылка меню не должна вести туда, где страницы нет.
// Страницы лежат в app/pages/**, и список ниже повторяет их адреса вручную —
// это осознанное дублирование: если кто-то переименует страницу и поправит
// только меню, тест упадёт и заставит переименовать обе стороны.

const EXISTING_ROUTES = new Set([
  '/',
  '/projects',
  '/reports/project',
  '/reports/project-task',
  '/reports/employee',
  '/reports/daily',
  '/reports/revenue-leakage',
  '/reports/time-discipline',
  '/reports/focus-analysis',
  '/settings',
  '/settings/periods',
  '/settings/projects-health',
  '/reports/raw-data',
  '/finance/bdds',
  '/finance/billing',
])

test('buildAppNavigation: пять разделов в рабочем порядке', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)

  assert.deepEqual(
    sections.map(section => section.id),
    ['home', 'projects', 'reports', 'control', 'finance']
  )
  assert.deepEqual(
    sections.map(section => section.label),
    ['Главная', 'Проекты', 'Отчёты', 'Контроль', 'Финансы']
  )
})

test('buildAppNavigation: все ссылки ведут на существующие страницы', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)

  for (const section of sections) {
    for (const route of collectSectionRoutes(section)) {
      assert.ok(
        EXISTING_ROUTES.has(route),
        `маршрут ${route} раздела ${section.id} не найден среди страниц приложения`
      )
    }
  }
})

test('buildAppNavigation: отчётов ровно семь и они разложены двумя группами', () => {
  const reports = buildAppNavigation(BASE_OPTIONS).find(section => section.id === 'reports')

  assert.ok(reports)
  assert.deepEqual(reports.groups?.map(group => group.label), ['Учёт часов', 'Аналитика'])

  const links = (reports.groups || []).flatMap(group => group.links)
  assert.equal(links.length, 7)
  assert.equal(new Set(links.map(link => link.to)).size, 7)
})

test('buildAppNavigation: счётчик Контроля округляется и не уходит в минус', () => {
  assert.equal(
    buildAppNavigation({ ...BASE_OPTIONS, controlIssuesCount: 3 })
      .find(section => section.id === 'control')?.badge,
    3
  )
  assert.equal(
    buildAppNavigation({ ...BASE_OPTIONS, controlIssuesCount: -5 })
      .find(section => section.id === 'control')?.badge,
    0
  )
})

test('buildAppNavigation: без данных проверки счётчика нет — пустой кружок соврал бы «проблем нет»', () => {
  const withoutCount = buildAppNavigation(BASE_OPTIONS).find(section => section.id === 'control')
  const withZero = buildAppNavigation({ ...BASE_OPTIONS, controlIssuesCount: 0 })
    .find(section => section.id === 'control')

  assert.equal(withoutCount?.badge, null)
  assert.equal(withZero?.badge, 0)
})

test('buildAppNavigation: выключенные финансовые функции идут с замком и бейджем', () => {
  const finance = buildAppNavigation(BASE_OPTIONS).find(section => section.id === 'finance')
  const links = finance?.groups?.[0]?.links || []

  assert.equal(links.length, 2)
  assert.deepEqual(links.map(link => link.label), ['БДДС по проектам', 'Счёт и акт'])
  assert.ok(links.every(link => link.locked === true))
  assert.ok(links.every(link => link.badge === 'по подписке'))
})

test('buildAppNavigation: включённый флаг снимает замок только со своей функции', () => {
  const finance = buildAppNavigation({ ...BASE_OPTIONS, financeBddsEnabled: true })
    .find(section => section.id === 'finance')
  const links = finance?.groups?.[0]?.links || []

  assert.equal(links[0].locked, false)
  assert.equal(links[0].badge, undefined)
  assert.equal(links[1].locked, true)
})

// --- Активный пункт ---

test('normalizeNavPath: режет query, хвостовой слеш и регистр', () => {
  assert.equal(normalizeNavPath('/Reports/Daily/?x=1#top'), '/reports/daily')
  assert.equal(normalizeNavPath('/'), '/')
  assert.equal(normalizeNavPath(''), '/')
  assert.equal(normalizeNavPath(null), '/')
})

test('resolveActiveSectionId: корень подсвечивает Главную только точным совпадением', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)

  assert.equal(resolveActiveSectionId('/', sections), 'home')
  assert.equal(resolveActiveSectionId('/projects', sections), 'projects')
})

test('resolveActiveSectionId: побеждает самый длинный маршрут, а не первый подходящий', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)

  // /reports/raw-data лежит в «Контроле», хотя адрес начинается с /reports —
  // разбор по префиксу раздела дал бы здесь «Отчёты».
  assert.equal(resolveActiveSectionId('/reports/raw-data', sections), 'control')
  assert.equal(resolveActiveSectionId('/settings/periods', sections), 'control')
  assert.equal(resolveActiveSectionId('/reports/project-task?project_id=42', sections), 'reports')
})

test('resolveActiveSectionId: чужой адрес не подсвечивает ничего', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)

  assert.equal(resolveActiveSectionId('/settings/mapping', sections), null)
  assert.equal(resolveActiveSectionId('/guide', sections), null)
})

test('isNavLinkActive: вложенный адрес подсвечивает свою ссылку', () => {
  const link = { id: 'x', label: 'X', to: '/settings/periods' }

  assert.equal(isNavLinkActive('/settings/periods', link), true)
  assert.equal(isNavLinkActive('/settings/periods/2026', link), true)
  assert.equal(isNavLinkActive('/settings/periodsomething', link), false)
})

// --- Где меню не показываем ---

test('shouldShowSectionNavigation: во фрейме вкладки задачи и в слайдере меню нет', () => {
  assert.equal(shouldShowSectionNavigation('/embedded'), false)
  assert.equal(shouldShowSectionNavigation('/slider/app-options'), false)
  assert.equal(shouldShowSectionNavigation('/handler/placement-crm-deal-detail-tab'), false)
  assert.equal(shouldShowSectionNavigation('/install'), false)
})

test('shouldShowSectionNavigation: на страницах приложения меню есть', () => {
  assert.equal(shouldShowSectionNavigation('/'), true)
  assert.equal(shouldShowSectionNavigation('/projects'), true)
  assert.equal(shouldShowSectionNavigation('/reports/daily'), true)
  assert.equal(shouldShowSectionNavigation('/settings/periods'), true)
})

test('shouldShowSectionNavigation: похожий адрес не считается запрещённым', () => {
  assert.equal(shouldShowSectionNavigation('/tasks-report'), true)
})

// --- Свёртка в «Ещё» ---

function sampleGroup(id: string) {
  return [{ id, label: 'Группа', links: [{ id: `${id}-link`, label: 'Ссылка', to: `/${id}` }] }]
}

const SAMPLE: NavSection[] = [
  { id: 'home', label: 'Главная', to: '/' },
  { id: 'projects', label: 'Проекты', to: '/projects' },
  { id: 'reports', label: 'Отчёты', groups: sampleGroup('reports') },
  { id: 'control', label: 'Контроль', groups: sampleGroup('control'), badge: 2 },
  { id: 'finance', label: 'Финансы', groups: sampleGroup('finance') },
]

test('splitNavigationByWidth: места хватает — прячем ничего', () => {
  const split = splitNavigationByWidth(SAMPLE, 4000)

  assert.equal(split.visible.length, SAMPLE.length)
  assert.equal(split.overflow.length, 0)
})

test('splitNavigationByWidth: ширина ещё не измерена — показываем всё и ждём следующего замера', () => {
  assert.equal(splitNavigationByWidth(SAMPLE, 0).overflow.length, 0)
  assert.equal(splitNavigationByWidth(SAMPLE, Number.NaN).overflow.length, 0)
})

test('splitNavigationByWidth: узкая полоса уводит хвост в «Ещё» без потерь', () => {
  const split = splitNavigationByWidth(SAMPLE, 260)

  assert.ok(split.visible.length >= 1)
  assert.ok(split.overflow.length >= 1)
  assert.deepEqual(
    [...split.visible, ...split.overflow].map(section => section.id),
    SAMPLE.map(section => section.id)
  )
})

test('splitNavigationByWidth: хотя бы один пункт остаётся видимым всегда', () => {
  const split = splitNavigationByWidth(SAMPLE, 10)

  assert.equal(split.visible.length, 1)
  assert.equal(split.visible[0].id, 'home')
  assert.equal(split.overflow.length, SAMPLE.length - 1)
})

test('splitNavigationByWidth: чем уже полоса, тем меньше видимых пунктов', () => {
  const wide = splitNavigationByWidth(SAMPLE, 520).visible.length
  const narrow = splitNavigationByWidth(SAMPLE, 320).visible.length

  assert.ok(wide >= narrow, `ожидали, что на 520px пунктов не меньше, чем на 320px (${wide} и ${narrow})`)
})

test('estimateNavSectionWidth: шеврон и счётчик добавляют ширины', () => {
  const plain = estimateNavSectionWidth({ id: 'a', label: 'Отчёты' })
  const withChevron = estimateNavSectionWidth({ id: 'a', label: 'Отчёты', groups: sampleGroup('a') })
  const withBadge = estimateNavSectionWidth({ id: 'a', label: 'Отчёты', groups: sampleGroup('a'), badge: 4 })

  assert.ok(withChevron > plain)
  assert.ok(withBadge > withChevron)
})

test('buildOverflowSection: группы свёрнутых разделов сохраняют свои заголовки', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)
  const overflow = buildOverflowSection(sections.slice(2))

  assert.ok(overflow)
  assert.equal(overflow.id, 'more')
  assert.equal(overflow.label, NAV_MORE_LABEL)
  assert.ok(overflow.groups?.some(group => group.label === 'Отчёты · Аналитика'))

  const links = (overflow.groups || []).flatMap(group => group.links)
  assert.ok(links.some(link => link.to === '/reports/focus-analysis'))
  assert.ok(links.some(link => link.to === '/finance/bdds'))
})

test('buildOverflowSection: простые ссылки собираются в одну группу «Разделы»', () => {
  const overflow = buildOverflowSection([
    { id: 'home', label: 'Главная', to: '/' },
    { id: 'projects', label: 'Проекты', to: '/projects' },
  ])

  assert.equal(overflow?.groups?.length, 1)
  assert.equal(overflow?.groups?.[0].label, 'Разделы')
  assert.deepEqual(overflow?.groups?.[0].links.map(link => link.to), ['/', '/projects'])
})

test('buildOverflowSection: счётчики свёрнутых разделов складываются на «Ещё»', () => {
  const overflow = buildOverflowSection([
    { id: 'control', label: 'Контроль', groups: sampleGroup('control'), badge: 3 },
    { id: 'finance', label: 'Финансы', groups: sampleGroup('finance') },
  ])

  assert.equal(overflow?.badge, 3)
})

test('buildOverflowSection: прятать нечего — пункта «Ещё» нет', () => {
  assert.equal(buildOverflowSection([]), null)
})

// --- Пункты для B24NavigationMenu ---

test('toNavigationMenuItems: ссылка получает to, раздел со списком — общий слот', () => {
  const sections = buildAppNavigation(BASE_OPTIONS)
  const items = toNavigationMenuItems(sections, 'reports')

  const home = items[0]
  const reports = items[2]

  assert.equal(home.to, '/')
  assert.equal(home.slot, undefined)
  assert.equal(home.active, false)

  assert.equal(reports.to, undefined)
  assert.equal(reports.slot, 'section')
  assert.equal(reports.active, true)
})

test('toNavigationMenuItems: нулевой счётчик кружка не рисует', () => {
  const withZero = toNavigationMenuItems(
    buildAppNavigation({ ...BASE_OPTIONS, controlIssuesCount: 0 }),
    null
  )
  const withTwo = toNavigationMenuItems(
    buildAppNavigation({ ...BASE_OPTIONS, controlIssuesCount: 2 }),
    null
  )

  assert.equal(withZero[3].badge, undefined)
  assert.deepEqual(withTwo[3].badge, { label: '2' })
})

// --- Бейдж пробного периода у «Счёта и акта» ---
//
// Состояние платной функции решает сервер (GET /api/features), а меню только
// рисует. Проверки ниже фиксируют два требования: включённая функция теряет
// замок, а пробный период показывает остаток дней рядом с пунктом.

function billingLink(options: Parameters<typeof buildAppNavigation>[0]) {
  const finance = buildAppNavigation(options).find(section => section.id === 'finance')

  return finance?.groups?.[0].links.find(link => link.paidFeature === 'billing')
}

test('buildAppNavigation: выключенная подписка оставляет «Счёту и акту» замок', () => {
  const link = billingLink(BASE_OPTIONS)

  assert.equal(link?.locked, true)
  assert.equal(link?.badge, 'по подписке')
  assert.equal(link?.to, '/finance/billing')
})

test('buildAppNavigation: включённая подписка снимает замок и бейдж', () => {
  const link = billingLink({ ...BASE_OPTIONS, financeBillingEnabled: true })

  assert.equal(link?.locked, false)
  assert.equal(link?.badge, undefined)
})

test('buildAppNavigation: пробный период показывает остаток дней рядом с пунктом', () => {
  const link = billingLink({
    ...BASE_OPTIONS,
    financeBillingEnabled: true,
    financeBillingBadge: 'пробный, осталось 5 дней',
  })

  assert.equal(link?.locked, false)
  assert.equal(link?.badge, 'пробный, осталось 5 дней')
})

test('buildAppNavigation: бейдж «Счёта и акта» не протекает в соседнюю платную функцию', () => {
  const finance = buildAppNavigation({
    ...BASE_OPTIONS,
    financeBillingEnabled: true,
    financeBillingBadge: 'пробный, осталось 5 дней',
  }).find(section => section.id === 'finance')

  const bdds = finance?.groups?.[0].links.find(link => link.paidFeature === 'bdds')

  assert.equal(bdds?.locked, true)
  assert.equal(bdds?.badge, 'по подписке')
})

function bddsLink(options: Parameters<typeof buildAppNavigation>[0]) {
  const finance = buildAppNavigation(options).find(section => section.id === 'finance')

  return finance?.groups?.[0].links.find(link => link.paidFeature === 'bdds')
}

test('buildAppNavigation: выключенная подписка оставляет БДДС замок', () => {
  const link = bddsLink(BASE_OPTIONS)

  assert.equal(link?.locked, true)
  assert.equal(link?.badge, 'по подписке')
  assert.equal(link?.to, '/finance/bdds')
})

test('buildAppNavigation: включённая подписка снимает у БДДС замок и бейдж', () => {
  const link = bddsLink({ ...BASE_OPTIONS, financeBddsEnabled: true })

  assert.equal(link?.locked, false)
  assert.equal(link?.badge, undefined)
})

test('buildAppNavigation: пробный период БДДС показывает остаток дней', () => {
  const link = bddsLink({
    ...BASE_OPTIONS,
    financeBddsEnabled: true,
    financeBddsBadge: 'пробный, осталось 3 дня',
  })

  assert.equal(link?.locked, false)
  assert.equal(link?.badge, 'пробный, осталось 3 дня')
})

test('buildAppNavigation: бейдж БДДС не протекает в «Счёт и акт»', () => {
  const finance = buildAppNavigation({
    ...BASE_OPTIONS,
    financeBddsEnabled: true,
    financeBddsBadge: 'пробный, осталось 3 дня',
  }).find(section => section.id === 'finance')

  const billing = finance?.groups?.[0].links.find(link => link.paidFeature === 'billing')

  assert.equal(billing?.locked, true)
  assert.equal(billing?.badge, 'по подписке')
})
