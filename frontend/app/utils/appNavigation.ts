/**
 * Постоянная навигация раздела — «вариант A: родной портал».
 *
 * До редизайна переходы между экранами жили плитками на главной: чтобы из
 * отчёта попасть в другой отчёт, надо было вернуться на главную. Меню в шапке
 * убирает этот возврат и заодно показывает, где человек сейчас находится.
 *
 * Здесь только МОДЕЛЬ меню — чистые функции без Vue и без роутера. Причина
 * та же, по которой в проект пришёл companySearch.ts: node:test через tsx не
 * резолвит .vue, и всё, что осталось внутри компонента, ревью проверить не
 * может. Поэтому состав пунктов, активный пункт и свёртка в «Ещё» лежат
 * тут и покрыты тестами, а components/nav/SectionNavigation.vue только
 * рисует то, что эти функции вернули.
 *
 * Маршруты берутся из существующих страниц (app/pages/**) и из
 * reportNavigation.ts — второго списка адресов отчётов в проекте быть не
 * должно.
 */

import { buildReportRouteLocation, type ReportRouteName } from './reportNavigation'
import { resolveFinanceFeatureStates, type PaidFeatureId } from './paidFeatures'

export type NavLink = {
  id: string
  label: string
  to: string
  /** Короткое пояснение под названием в выпадающем списке. */
  description?: string
  /** Пункт ведёт на выключенную платную функцию: замок и бейдж. */
  locked?: boolean
  /** Текст бейджа рядом с названием («по подписке»). */
  badge?: string
  /** Идентификатор платной функции, если пункт про неё. */
  paidFeature?: PaidFeatureId
}

export type NavGroup = {
  id: string
  /** Заголовок группы внутри выпадающего списка. */
  label: string
  links: NavLink[]
}

export type NavSection = {
  id: string
  label: string
  /** Прямая ссылка. У разделов с выпадающим списком её нет. */
  to?: string
  /** Содержимое выпадающего списка. */
  groups?: NavGroup[]
  /** Счётчик проблем. null — счётчик недоступен, 0 — проблем нет. */
  badge?: number | null
}

export type AppNavigationOptions = {
  /**
   * Сколько находок нашла проверка месяца (`/api/periods/check`).
   * null или undefined — проверка ещё не отвечала, счётчик не рисуем:
   * пустой кружок читается как «проблем нет», а это не одно и то же.
   */
  controlIssuesCount?: number | null
  financeBddsEnabled: boolean
  financeBillingEnabled: boolean
}

function reportPath(report: ReportRouteName): string {
  return buildReportRouteLocation(report).path
}

/**
 * Состав меню.
 *
 * Порядок пунктов — порядок рабочего дня: сначала где я работаю (Главная,
 * Проекты), потом что я смотрю (Отчёты), потом что я проверяю (Контроль),
 * и в конце деньги. Настройки в этот ряд не входят — они уезжают вправо
 * шестерёнкой, отдельно от рабочих разделов.
 */
export function buildAppNavigation(options: AppNavigationOptions): NavSection[] {
  const finance = resolveFinanceFeatureStates({
    bddsEnabled: options.financeBddsEnabled,
    billingEnabled: options.financeBillingEnabled,
  })

  const rawIssues = options.controlIssuesCount
  const controlBadge = typeof rawIssues === 'number' && Number.isFinite(rawIssues)
    ? Math.max(0, Math.trunc(rawIssues))
    : null

  return [
    {
      id: 'home',
      label: 'Главная',
      to: '/',
    },
    {
      id: 'projects',
      label: 'Проекты',
      to: '/projects',
    },
    {
      id: 'reports',
      label: 'Отчёты',
      groups: [
        {
          id: 'reports-hours',
          label: 'Учёт часов',
          links: [
            { id: 'report-project', label: 'Отчёт по проектам', to: reportPath('project'), description: 'Сводка по проектам' },
            { id: 'report-project-task', label: 'Учёт по проектам и задачам', to: reportPath('project-task'), description: 'Проект → задача → сотрудник' },
            { id: 'report-employee', label: 'Отчёт по сотрудникам', to: reportPath('employee'), description: 'Детальные часы по людям' },
            { id: 'report-daily', label: 'Ежедневная нагрузка', to: reportPath('daily'), description: 'Матрица часов по дням' },
          ],
        },
        {
          id: 'reports-analytics',
          label: 'Аналитика',
          links: [
            { id: 'report-revenue-leakage', label: 'Потери выручки', to: reportPath('revenue-leakage'), description: 'Неоплачиваемые зоны' },
            { id: 'report-time-discipline', label: 'Дисциплина времени', to: reportPath('time-discipline'), description: 'Скорость внесения записей' },
            { id: 'report-focus-analysis', label: 'Фокус и распыление', to: reportPath('focus-analysis'), description: 'Распределение часов' },
          ],
        },
      ],
    },
    {
      id: 'control',
      label: 'Контроль',
      badge: controlBadge,
      groups: [
        {
          id: 'control-period',
          label: 'Период',
          links: [
            { id: 'control-periods', label: 'Закрытие месяца', to: '/settings/periods', description: 'Проверка и заморозка часов' },
          ],
        },
        {
          id: 'control-data',
          label: 'Данные',
          links: [
            { id: 'control-raw-data', label: 'Проверка данных и ИНН', to: '/reports/raw-data', description: 'Исходные записи и подстановка ИНН' },
            { id: 'control-projects-health', label: 'Незаполненные проекты', to: '/settings/projects-health', description: 'Чего не хватает карточкам' },
          ],
        },
      ],
    },
    {
      id: 'finance',
      label: 'Финансы',
      groups: [
        {
          id: 'finance-paid',
          label: 'Платные функции',
          links: finance.map(state => ({
            id: `finance-${state.feature.id}`,
            label: state.feature.label,
            to: state.to,
            description: state.feature.benefit,
            locked: state.locked,
            badge: state.badge ?? undefined,
            paidFeature: state.feature.id,
          })),
        },
      ],
    },
  ]
}

/**
 * Ключ общего состояния со счётчиком проблем для пункта «Контроль».
 *
 * Меню живёт в лейауте и рисуется раньше, чем приложение получило токен, —
 * свой запрос оттуда ушёл бы без авторизации. Поэтому счётчик кладёт туда, кто
 * и так спрашивает проверку месяца (главная), а меню его только читает:
 * useState(NAV_CONTROL_ISSUES_STATE_KEY). null означает «ещё не спрашивали».
 */
export const NAV_CONTROL_ISSUES_STATE_KEY = 'app-nav-control-issues'

/** Шестерёнка справа. Отдельно от рабочих разделов и в «Ещё» не сворачивается. */
export const SETTINGS_NAV_LINK: NavLink = {
  id: 'settings',
  label: 'Настройки',
  to: '/settings',
}

/**
 * Экраны, на которых постоянного меню быть не должно.
 *
 * Вкладка задачи (`/embedded`) и слайдер — это КУСОК чужого
 * интерфейса внутри карточки Битрикса, а не страница приложения: меню разделов
 * там уводит человека из задачи, которую он открыл, и ломает высоту фрейма.
 * Маршрут `/` в этот список не попадает намеренно: он живёт и как главная, и
 * как точка входа placement'а, но в placement'е сам себя тут же редиректит
 * (см. index.client.vue), поэтому меню на нём успевает только не появиться.
 */
const NAVIGATION_HIDDEN_PREFIXES = [
  '/embedded',
  '/install',
  '/slider',
  '/handler',
  '/render',
  '/eula',
]

/** Путь без query, хвостового слеша и регистра — в таком виде его и сравниваем. */
export function normalizeNavPath(path: string | null | undefined): string {
  const raw = String(path || '/').trim()
  const withoutQuery = raw.split('?')[0].split('#')[0]
  const lowered = withoutQuery.toLowerCase()

  if (lowered.length > 1 && lowered.endsWith('/')) {
    return lowered.replace(/\/+$/, '') || '/'
  }

  return lowered || '/'
}

export function shouldShowSectionNavigation(path: string | null | undefined): boolean {
  const normalized = normalizeNavPath(path)

  return !NAVIGATION_HIDDEN_PREFIXES.some(
    prefix => normalized === prefix || normalized.startsWith(`${prefix}/`)
  )
}

/** Все маршруты раздела: сам пункт и всё, что лежит в его выпадающем списке. */
export function collectSectionRoutes(section: NavSection): string[] {
  const routes: string[] = []

  if (section.to) {
    routes.push(section.to)
  }

  for (const group of section.groups || []) {
    for (const link of group.links) {
      routes.push(link.to)
    }
  }

  return routes
}

/**
 * Какой пункт подсветить.
 *
 * Совпадение ищем по самому ДЛИННОМУ подходящему маршруту, а не по первому:
 * иначе `/` победит любой вложенный адрес и «Главная» будет гореть всегда.
 * Корень поэтому сравнивается только точно.
 */
export function resolveActiveSectionId(
  path: string | null | undefined,
  sections: NavSection[]
): string | null {
  const normalized = normalizeNavPath(path)
  let bestId: string | null = null
  let bestLength = -1

  for (const section of sections) {
    for (const route of collectSectionRoutes(section)) {
      const candidate = normalizeNavPath(route)
      const matches = candidate === '/'
        ? normalized === '/'
        : normalized === candidate || normalized.startsWith(`${candidate}/`)

      if (matches && candidate.length > bestLength) {
        bestId = section.id
        bestLength = candidate.length
      }
    }
  }

  return bestId
}

/** Активна ли ссылка выпадающего списка (для подсветки внутри меню). */
export function isNavLinkActive(path: string | null | undefined, link: NavLink): boolean {
  const normalized = normalizeNavPath(path)
  const candidate = normalizeNavPath(link.to)

  return candidate === '/'
    ? normalized === '/'
    : normalized === candidate || normalized.startsWith(`${candidate}/`)
}

export type NavWidthMetrics = {
  /** Средняя ширина символа подписи, px. */
  charWidth: number
  /** Горизонтальные отступы внутри пункта, px. */
  itemPadding: number
  /** Шеврон у пункта с выпадающим списком, px. */
  trailingIconWidth: number
  /** Кружок счётчика, px. */
  badgeWidth: number
  /** Зазор между пунктами, px. */
  gap: number
}

/**
 * Ширины прикидочные, и это нормально: цена ошибки — один лишний или один
 * недостающий пункт в «Ещё», а не сломанная вёрстка. Точное измерение
 * потребовало бы рисовать все пункты и читать их ширины из DOM, то есть
 * ровно того переполнения, которое мы предотвращаем.
 */
export const NAV_WIDTH_METRICS: NavWidthMetrics = {
  charWidth: 8,
  itemPadding: 28,
  trailingIconWidth: 16,
  badgeWidth: 26,
  gap: 4,
}

export const NAV_MORE_LABEL = 'Ещё'

export function estimateNavSectionWidth(
  section: NavSection,
  metrics: NavWidthMetrics = NAV_WIDTH_METRICS
): number {
  let width = metrics.itemPadding + section.label.length * metrics.charWidth

  if (section.groups?.length) {
    width += metrics.trailingIconWidth
  }

  if (typeof section.badge === 'number' && section.badge > 0) {
    width += metrics.badgeWidth
  }

  return Math.ceil(width)
}

export type NavigationSplit = {
  visible: NavSection[]
  overflow: NavSection[]
}

/**
 * Что показать, а что убрать в «Ещё».
 *
 * availableWidth <= 0 или не число — контейнер ещё не измерен (первый кадр,
 * сервер, скрытый блок). Прятать в этот момент нечего: показываем всё, а
 * следующий замер поправит. Один пункт остаётся видимым всегда — меню, в
 * котором видно только «Ещё», хуже, чем меню с переполнением.
 */
export function splitNavigationByWidth(
  sections: NavSection[],
  availableWidth: number,
  metrics: NavWidthMetrics = NAV_WIDTH_METRICS
): NavigationSplit {
  if (!sections.length) {
    return { visible: [], overflow: [] }
  }

  if (!Number.isFinite(availableWidth) || availableWidth <= 0) {
    return { visible: [...sections], overflow: [] }
  }

  const widths = sections.map(section => estimateNavSectionWidth(section, metrics))
  const totalWidth = widths.reduce((sum, width) => sum + width, 0)
    + metrics.gap * Math.max(0, sections.length - 1)

  if (totalWidth <= availableWidth) {
    return { visible: [...sections], overflow: [] }
  }

  const moreWidth = estimateNavSectionWidth(
    { id: 'more', label: NAV_MORE_LABEL, groups: [] },
    metrics
  ) + metrics.trailingIconWidth

  const budget = availableWidth - moreWidth - metrics.gap
  const visible: NavSection[] = []
  let used = 0

  for (let index = 0; index < sections.length; index += 1) {
    const next = used + widths[index] + (visible.length ? metrics.gap : 0)

    if (next > budget) {
      break
    }

    used = next
    visible.push(sections[index])
  }

  if (!visible.length) {
    visible.push(sections[0])
  }

  return {
    visible,
    overflow: sections.slice(visible.length),
  }
}

/**
 * Пункт «Ещё» из свёрнутых разделов.
 *
 * Разделы с выпадающим списком отдают свои группы как есть — человек ищет
 * «Потери выручки» под заголовком «Аналитика» и должен найти её там же,
 * в каком бы меню список ни оказался. Простые ссылки собираются в одну
 * группу «Разделы».
 */
export function buildOverflowSection(overflow: NavSection[]): NavSection | null {
  if (!overflow.length) {
    return null
  }

  const groups: NavGroup[] = []
  const plainLinks: NavLink[] = []
  let badgeTotal: number | null = null

  for (const section of overflow) {
    if (typeof section.badge === 'number') {
      badgeTotal = (badgeTotal ?? 0) + section.badge
    }

    if (section.groups?.length) {
      for (const group of section.groups) {
        groups.push({
          ...group,
          id: `more-${group.id}`,
          label: `${section.label} · ${group.label}`,
        })
      }
      continue
    }

    if (section.to) {
      plainLinks.push({
        id: `more-${section.id}`,
        label: section.label,
        to: section.to,
      })
    }
  }

  if (plainLinks.length) {
    groups.unshift({ id: 'more-sections', label: 'Разделы', links: plainLinks })
  }

  return {
    id: 'more',
    label: NAV_MORE_LABEL,
    groups,
    badge: badgeTotal,
  }
}

/**
 * Пункт B24NavigationMenu из раздела меню.
 *
 * Разделы с выпадающим списком получают `slot: 'section'` — один общий
 * именованный слот на все такие пункты, чтобы содержимое списка (две группы с
 * заголовками, замки, бейджи) рисовалось нашей разметкой: у компонента
 * в горизонтальной ориентации группы внутри списка не предусмотрены.
 */
export function toNavigationMenuItem(
  section: NavSection,
  activeSectionId: string | null
): Record<string, unknown> {
  const isActive = activeSectionId === section.id
  const item: Record<string, unknown> = {
    value: section.id,
    label: section.label,
    active: isActive,
    section,
  }

  if (section.to) {
    item.to = section.to
  }

  if (section.groups?.length) {
    item.slot = 'section'
  }

  if (typeof section.badge === 'number' && section.badge > 0) {
    item.badge = { label: String(section.badge) }
  }

  return item
}

export function toNavigationMenuItems(
  sections: NavSection[],
  activeSectionId: string | null
): Record<string, unknown>[] {
  return sections.map(section => toNavigationMenuItem(section, activeSectionId))
}
