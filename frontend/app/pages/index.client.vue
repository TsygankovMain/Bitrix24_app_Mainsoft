<script setup lang="ts">
/**
 * Главная приложения.
 *
 * До редизайна («вариант A: родной портал») здесь лежали плитки-кнопки: экран
 * отвечал на вопрос «куда пойти» и ни на один вопрос про работу. Навигацию
 * забрало постоянное меню разделов в шапке (layouts/default.vue), и место
 * освободилось под показатели выбранного месяца и таблицу проектов.
 *
 * Цифры берутся только из существующих ручек — `/api/periods/check` и
 * `/api/homepage-portfolio`; расчёты вынесены в app/utils/homeDashboard.ts и
 * покрыты тестами.
 *
 * Маршрутизация по placement'ам НЕ ТРОНУТА: этот же маршрут служит точкой
 * входа для TASK_VIEW_TAB и SONET_GROUP_DETAIL_TAB, и редирект должен
 * случиться раньше, чем экран начнёт что-либо грузить.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import type { ComponentPublicInstance } from 'vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { buildReportRouteLocation, type ReportRouteName, type ReportRoutePayload } from '~/utils/reportNavigation'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import type { PeriodCheckResult, PeriodRow } from '~/types/period'
import { openProjectGroup } from '~/utils/openProjectGroup'
import { openCrmItemCard } from '~/utils/openCrmItem'
import CreateProjectDrawer from '~/components/projects/CreateProjectDrawer.vue'
import ProjectBoardDrawer from '~/components/projects/ProjectBoardDrawer.vue'
import HomeProjectDetailsDrawer from '~/components/home/ProjectDetailsDrawer.vue'
import { CREATE_PROJECT_BUTTON_ENABLED, FINANCE_BILLING_ENABLED, TASK_TAB_ROUTE } from '~/utils/featureFlags'
import { NAV_CONTROL_ISSUES_STATE_KEY } from '~/utils/appNavigation'
import {
  applyProjectQuickFilter,
  buildHomeMetrics,
  buildProjectPanel,
  buildProjectRows,
  buildProjectUtilization,
  countPeriodBlockers,
  countProjectQuickFilters,
  filterProjectRows,
  findPeriodRow,
  findProjectRowById,
  formatLastWriteoff,
  formatMonthTitle,
  formatMonthValue,
  getProjectStageClass,
  initialsOf,
  parseMonthValue,
  PROJECT_QUICK_FILTERS,
  sortProjectRows,
  type ProjectQuickFilterId,
  type ProjectRow,
} from '~/utils/homeDashboard'
import { PAID_FEATURE_BADGE, paidFeatureRoute } from '~/utils/paidFeatures'

const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()

useHead({
  title: t('page.index.seo.title'),
  script: [
    {
      src: 'https://api.bitrix24.com/api/v1/',
      async: true,
      defer: true
    }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('IndexPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const fieldConfigStore = useFieldConfigStore()

/**
 * Куда вести из placement'а TASK_VIEW_TAB — см. TASK_TAB_ROUTE в utils/featureFlags.ts.
 *
 * installation_service биндит TASK_VIEW_TAB на КОРЕНЬ приложения и рассчитывает,
 * что маршрут выберет клиент (см. комментарий там же). Раньше здесь стоял
 * '/task' — экран, который тогда умел только смотреть дерево и править запись,
 * то есть списать часы из карточки задачи было нельзя. В проде это не
 * проявлялось (placement привязан прямо к /embedded), но ре-бинд placement'ов —
 * штатная операция после смены production-домена, и переустановка молча
 * пересадила бы сотрудников на экран без отражения часов.
 */

type PortfolioSummary = {
  total_count: number
  active_count: number
  archived_count: number
  support_count: number
  inactive_30_count: number
  inactive_90_count: number
}

type PortfolioData = {
  cards?: ProjectBoardCardRecord[]
  summary?: PortfolioSummary
}

type ProjectBoardMetaLike = {
  directories?: {
    employees?: ProjectBoardDirectoryOption[]
    companies?: ProjectBoardDirectoryOption[]
    legal_entities?: ProjectBoardDirectoryOption[]
  }
  employees?: ProjectBoardDirectoryOption[]
  companies?: ProjectBoardDirectoryOption[]
  legal_entities?: ProjectBoardDirectoryOption[]
}

const isInit = ref(false)
const isPortfolioLoading = ref(false)
const portfolioData = ref<PortfolioData | null>(null)
const projectSearch = ref('')
const quickFilter = ref<ProjectQuickFilterId>('active')
const selectedProjectId = ref('')
const userStore = useUserStore()

// --- Показатели месяца ---
const selectedMonth = ref(formatMonthValue(new Date()))
const periodCheck = ref<PeriodCheckResult | null>(null)
const periodRows = ref<PeriodRow[] | null>(null)
const isPeriodLoading = ref(false)
const periodError = ref('')

/**
 * Счётчик проблем для пункта «Контроль» в меню разделов.
 *
 * Меню лежит в лейауте и своего запроса позволить себе не может (оно рисуется
 * раньше, чем приложение получило токен), поэтому число блокеров кладёт сюда
 * главная — она проверку месяца и так спрашивает.
 */
const controlIssues = useState<number | null>(NAV_CONTROL_ISSUES_STATE_KEY, () => null)

/**
 * Боковая панель выбранного проекта.
 *
 * Панель лежит поверх содержимого (components/home/ProjectDetailsDrawer.vue) и
 * открывается только по клику: раньше она была колонкой сетки и на узком
 * фрейме уезжала под таблицу — отсюда жалоба «нажимаешь на проект, а он
 * открывается внизу».
 *
 * `selectedProjectId` живёт дольше самой панели: строка остаётся подсвеченной
 * и после закрытия, чтобы было видно, с чего сотрудник вернулся.
 */
const isProjectPanelOpen = ref(false)

/**
 * Кнопки-строки таблицы, чтобы вернуть фокус туда, откуда панель открыли.
 * Обычный объект, а не ref: на отрисовку эта карта не влияет.
 */
const projectRowTriggers = new Map<string, HTMLButtonElement>()

/** Не возвращать фокус в таблицу, когда панель закрылась ради дровера поверх неё. */
let skipProjectFocusRestore = false

// --- Drawer state ---
const isDrawerOpen = ref(false)
const drawerCard = ref<ProjectBoardCardRecord | null>(null)
const isSaving = ref(false)
const isArchiving = ref(false)
const employeeDirectory = ref<ProjectBoardDirectoryOption[]>([])
const companyDirectory = ref<ProjectBoardDirectoryOption[]>([])
const legalEntityDirectory = ref<ProjectBoardDirectoryOption[]>([])

// --- Create project modal state ---
const createProjectOpen = ref(false)

function mergeSelectOptions(...groups: Array<ProjectBoardDirectoryOption[]>) {
  const seenIds = new Set<string>()
  const result: ProjectBoardDirectoryOption[] = []
  for (const group of groups) {
    for (const option of group || []) {
      const optionId = String(option.id || '').trim()
      const optionName = String(option.name || '').trim()
      if (!optionId || seenIds.has(optionId)) {
        continue
      }
      seenIds.add(optionId)
      result.push({
        ...option,
        id: optionId,
        name: optionName || optionId,
        inn: option.inn || null,
        search_text: [optionName || optionId, option.inn || '', option.search_text || ''].join(' ').trim()
      })
    }
  }
  return result.sort((left, right) => String(left.name).localeCompare(String(right.name), 'ru'))
}

function buildOptionsFromPortfolioCards(
  idGetter: (card: ProjectBoardCardRecord) => string | null | undefined,
  nameGetter: (card: ProjectBoardCardRecord) => string | null | undefined
) {
  const seenIds = new Set<string>()
  const result: ProjectBoardDirectoryOption[] = []
  const cards = (portfolioData.value?.cards || []) as ProjectBoardCardRecord[]
  for (const card of cards) {
    const optionId = String(idGetter(card) || '').trim()
    const optionName = String(nameGetter(card) || '').trim()
    if (!optionId || seenIds.has(optionId)) {
      continue
    }
    seenIds.add(optionId)
    result.push({ id: optionId, name: optionName || optionId, search_text: optionName || optionId })
  }
  return result
}

const drawerEmployeeOptions = computed(() =>
  mergeSelectOptions(
    employeeDirectory.value,
    buildOptionsFromPortfolioCards(
      card => card.curator_user_id,
      card => card.curator_name
    )
  )
)

const drawerCompanyOptions = computed(() =>
  mergeSelectOptions(
    companyDirectory.value,
    buildOptionsFromPortfolioCards(
      card => card.company_id,
      card => card.company_name
    )
  )
)

const drawerLegalEntityOptions = computed(() =>
  mergeSelectOptions(
    legalEntityDirectory.value,
    buildOptionsFromPortfolioCards(
      card => card.our_legal_entity_id,
      card => card.our_legal_entity_name
    )
  )
)

const monthTitle = computed(() => formatMonthTitle(selectedMonth.value))
const selectedPeriodRow = computed(() => findPeriodRow(periodRows.value, parseMonthValue(selectedMonth.value)))

const metrics = computed(() => buildHomeMetrics({
  check: periodCheck.value,
  period: selectedPeriodRow.value,
  periodsLoaded: periodRows.value !== null,
  portfolio: portfolioData.value?.summary || null,
}))

const quickFilterContext = computed(() => ({ currentUserId: userStore.id }))

const allProjectRows = computed(() => sortProjectRows(buildProjectRows(portfolioData.value?.cards)))
const quickFilterCounts = computed(() => countProjectQuickFilters(allProjectRows.value, quickFilterContext.value))
const projectRows = computed(() => filterProjectRows(
  applyProjectQuickFilter(allProjectRows.value, quickFilter.value, quickFilterContext.value),
  projectSearch.value
))

/**
 * Строки таблицы вместе с посчитанным освоением бюджета.
 *
 * Считаем один раз на строку, а не по разу на каждую ячейку: в шаблоне
 * освоение нужно и полосе, и подписи, и цвету, и вызов из разметки повторился
 * бы четырежды на каждый проект.
 */
const decoratedProjectRows = computed(() => projectRows.value.map(row => ({
  row,
  utilization: buildProjectUtilization(row),
})))

/**
 * Строка, о которой рассказывает боковая панель.
 *
 * Подстановки первой строки списка больше нет — см. findProjectRowById: панель
 * открывается по клику и показывает ровно тот проект, который открыли.
 */
const selectedProjectRow = computed<ProjectRow | null>(
  () => findProjectRowById(projectRows.value, selectedProjectId.value)
)

const projectPanel = computed(() => buildProjectPanel(selectedProjectRow.value))

const METRIC_TONE_CLASS = {
  neutral: 'text-slate-900',
  success: 'text-emerald-600',
  warning: 'text-amber-600',
  danger: 'text-rose-600',
} as const

const METRIC_BADGE_CLASS = {
  neutral: 'bg-slate-100 text-slate-700',
  success: 'bg-emerald-100 text-emerald-700',
  warning: 'bg-amber-100 text-amber-700',
  danger: 'bg-rose-100 text-rose-700',
} as const

const UTILIZATION_BAR_CLASS = {
  neutral: 'bg-[#0075ff]',
  warning: 'bg-amber-500',
  danger: 'bg-rose-500',
} as const

const billingFeatureRoute = paidFeatureRoute('billing')

function openReport(target: ReportRouteName | ReportRoutePayload) {
  router.push(buildReportRouteLocation(target))
}

function openGuide() {
  router.push('/guide')
}

function getWriteoffClass(days: number) {
  if (days >= 90) {
    return 'text-rose-600 font-semibold'
  }
  if (days >= 30) {
    return 'text-amber-600 font-semibold'
  }
  return 'text-slate-700'
}

async function loadPortfolio(forceRefresh = false) {
  isPortfolioLoading.value = true
  try {
    portfolioData.value = await apiStore.getHomepagePortfolio(forceRefresh) as PortfolioData
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isPortfolioLoading.value = false
  }
}

/**
 * Проверка выбранного месяца.
 *
 * Ошибку сюда не пускаем в processErrorGlobal: показатели — не единственное,
 * ради чего открывают главную, и уронить из-за них таблицу проектов было бы
 * несоразмерно. Пишем текст рядом с показателями и оставляем прочерки.
 */
async function loadPeriodCheck() {
  const parsed = parseMonthValue(selectedMonth.value)

  if (!parsed) {
    periodCheck.value = null
    controlIssues.value = null
    return
  }

  isPeriodLoading.value = true
  periodError.value = ''
  try {
    periodCheck.value = await apiStore.checkPeriod(parsed.year, parsed.month)
    controlIssues.value = countPeriodBlockers(periodCheck.value)
  } catch (error) {
    periodCheck.value = null
    controlIssues.value = null
    periodError.value = 'Показатели месяца сейчас недоступны.'
    console.warn('[IndexPage] Failed to load period check', error)
  } finally {
    isPeriodLoading.value = false
  }
}

/**
 * Журнал закрытия месяцев.
 *
 * Отдельной ручки «статус одного месяца» нет: `/api/periods` отдаёт все
 * месяцы разом, нужный выбирается на клиенте (findPeriodRow). Ошибку, как и у
 * проверки, глушим: показатель закрытия покажет прочерк, остальной экран
 * работает.
 */
async function loadPeriods() {
  try {
    periodRows.value = (await apiStore.getPeriods()).periods || []
  } catch (error) {
    periodRows.value = null
    console.warn('[IndexPage] Failed to load periods journal', error)
  }
}

/**
 * Запомнить кнопку строки, чтобы вернуть на неё фокус после закрытия панели.
 * Vue зовёт функциональный ref с null, когда строка уходит из отбора.
 */
function setProjectRowTrigger(rowId: string, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLButtonElement) {
    projectRowTriggers.set(rowId, element)
    return
  }

  projectRowTriggers.delete(rowId)
}

function selectProject(row: ProjectRow) {
  selectedProjectId.value = row.id
  isProjectPanelOpen.value = true
}

/**
 * Возврат фокуса.
 *
 * Панель закрывают четырьмя способами (крестик, кнопка «Закрыть», клик по
 * затемнению, Escape) плюс мы сами закрываем её перед дровером карточки, и все
 * они сходятся в одном месте — переключении `isProjectPanelOpen`. Поэтому
 * фокус возвращает watcher, а не каждый обработчик по отдельности.
 */
watch(isProjectPanelOpen, async (isOpen) => {
  if (isOpen) {
    return
  }

  if (skipProjectFocusRestore) {
    skipProjectFocusRestore = false
    return
  }

  await nextTick()
  projectRowTriggers.get(selectedProjectId.value)?.focus()
})

function setQuickFilter(id: ProjectQuickFilterId) {
  quickFilter.value = id
}

function openBillingFeature() {
  // Тоже уход со страницы (или на экран «по подписке») — панель закрываем.
  skipProjectFocusRestore = isProjectPanelOpen.value
  isProjectPanelOpen.value = false
  router.push(billingFeatureRoute)
}

watch(selectedMonth, () => {
  if (isInit.value) {
    loadPeriodCheck()
  }
})

// Смена быстрого фильтра или поиска может выкинуть выбранный проект из списка.
// Панель тогда закрывается: подставлять в неё соседний проект — значит подменить
// сотруднику карточку, которую он открыл.
watch([quickFilter, projectSearch], () => {
  if (projectRows.value.some(row => row.id === selectedProjectId.value)) {
    return
  }

  selectedProjectId.value = ''
  isProjectPanelOpen.value = false
})

async function onProjectCreated() {
  await loadPortfolio(true)
}

function openProject(card?: ProjectBoardCardRecord | null) {
  if (!card) {
    return
  }
  openProjectGroup(card.project_id)
}

async function loadMeta() {
  // Best-effort: справочники для карточки проекта не должны рушить главный экран
  try {
    const meta = await apiStore.getProjectBoardMeta() as ProjectBoardMetaLike
    const directories = meta.directories || {}
    employeeDirectory.value = directories.employees || meta.employees || []
    companyDirectory.value = directories.companies || meta.companies || []
    legalEntityDirectory.value = directories.legal_entities || meta.legal_entities || []
  } catch (error) {
    console.warn('[IndexPage] Failed to load project board meta (drawer directories)', error)
  }
}

async function openProjectCard(project: ProjectBoardCardRecord | null | undefined) {
  if (!project) {
    return
  }
  // Карточка — второй дровер поверх первого: двойное затемнение и два
  // обработчика Escape сразу. Панель проекта уступает ей место, фокус в
  // таблицу при этом не возвращаем — он должен уйти в карточку.
  skipProjectFocusRestore = isProjectPanelOpen.value
  isProjectPanelOpen.value = false
  drawerCard.value = project
  isDrawerOpen.value = true
  try {
    const detailed = await apiStore.getProjectBoardCard(project.project_id)
    if (detailed) {
      drawerCard.value = detailed
    }
  } catch (error) {
    console.warn('[IndexPage] Failed to load detailed card', error)
  }
}

async function handleSaveProjectCard(payload: Record<string, unknown>) {
  isSaving.value = true
  try {
    await apiStore.updateProjectCard(payload)
    isDrawerOpen.value = false
    await loadPortfolio(true)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isSaving.value = false
  }
}

async function handleArchiveProjectCard(nextArchivedState: boolean) {
  if (!drawerCard.value) {
    return
  }
  isArchiving.value = true
  try {
    await apiStore.archiveProject(drawerCard.value.project_id, nextArchivedState)
    isDrawerOpen.value = false
    await loadPortfolio(true)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isArchiving.value = false
  }
}

function openSpa(card?: ProjectBoardCardRecord | null) {
  const targetCard = card || drawerCard.value
  if (!targetCard) {
    return
  }
  const spEntityTypeId = fieldConfigStore.entityTypeId
  const projectItemId = targetCard.project_item_id
  if (spEntityTypeId && projectItemId) {
    openCrmItemCard(spEntityTypeId, projectItemId)
  }
}

function openProjectReport(row: ProjectRow, report: ReportRouteName = 'project') {
  // Уходим со страницы — панель не должна мелькнуть поверх нового экрана.
  skipProjectFocusRestore = isProjectPanelOpen.value
  isProjectPanelOpen.value = false
  openReport({
    report,
    projectId: row.id,
    projectName: row.name,
    autogenerate: true,
  })
}

// Действия боковой панели: она знает только «открыть», а какой именно проект
// открыт — знает страница.
function openSelectedProjectGroup() {
  openProject(selectedProjectRow.value?.card)
}

function openSelectedProjectReport() {
  if (!selectedProjectRow.value) {
    return
  }
  openProjectReport(selectedProjectRow.value)
}

function openSelectedProjectCard() {
  openProjectCard(selectedProjectRow.value?.card)
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle(t('page.index.seo.title'))

    // @ts-expect-error - placement typing
    const placementCode = $b24.placement?.title || $b24.placement?.placement || ($b24.placement?.info && $b24.placement.info.placement)
    if (placementCode === 'TASK_VIEW_TAB') {
      router.push(TASK_TAB_ROUTE)
      return
    }
    if (placementCode === 'SONET_GROUP_DETAIL_TAB') {
      router.push('/reports/project-report')
      return
    }

    // @ts-expect-error - BX24 global typing
    if (typeof window.BX24 !== 'undefined') {
      // @ts-expect-error - BX24 global typing
      window.BX24.init(() => {
        // @ts-expect-error - BX24 global typing
        const rawPlacement = window.BX24.placement.info()
        if (rawPlacement && rawPlacement.placement === 'TASK_VIEW_TAB') {
          router.push(TASK_TAB_ROUTE)
        } else if (rawPlacement && rawPlacement.placement === 'SONET_GROUP_DETAIL_TAB') {
          router.push('/reports/project-report')
        }
      })
    }

    isInit.value = true
    await Promise.all([
      loadPortfolio(),
      loadMeta(),
      loadPeriodCheck(),
      loadPeriods(),
    ])
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <!-- Шапка экрана: что это и чем управляем -->
      <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight text-slate-900">Главная</h1>
          <p class="mt-1 text-sm text-slate-500">
            Портфель проектов и часы за {{ monthTitle }}. Разделы приложения — в меню сверху.
          </p>
        </div>

        <div class="flex flex-wrap items-end gap-2">
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Месяц</span>
            <input
              v-model="selectedMonth"
              type="month"
              class="h-[38px] w-full min-w-[170px] rounded-lg border border-slate-200 bg-white px-3 outline-none transition focus:border-[#0075ff] focus:ring-1 focus:ring-[#0075ff]"
            >
          </label>
          <B24Button label="Канбан проектов" color="default" @click="router.push('/projects')" />
          <B24Button label="Юзергайд" color="default" @click="openGuide" />
          <B24Button
            v-if="CREATE_PROJECT_BUTTON_ENABLED"
            label="Создать проект"
            color="primary"
            @click="createProjectOpen = true"
          />
        </div>
      </div>

      <div v-if="isInit" class="mt-5 flex flex-col gap-5">
        <p v-if="periodError" class="text-sm text-rose-600">{{ periodError }}</p>

        <!-- Четыре показателя выбранного месяца -->
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="metric in metrics"
            :key="metric.id"
            class="rounded-2xl border border-slate-200 bg-white px-4 py-3.5 shadow-sm"
          >
            <div class="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500">
              {{ metric.label }}
            </div>

            <div v-if="metric.asBadge" class="mt-2.5 flex min-h-[32px] items-center">
              <span
                class="inline-flex rounded-full px-3 py-1 text-sm font-semibold"
                :class="METRIC_BADGE_CLASS[metric.tone]"
              >
                {{ isPeriodLoading ? '…' : metric.value }}
              </span>
            </div>
            <div v-else class="mt-1 text-3xl font-semibold tabular-nums" :class="METRIC_TONE_CLASS[metric.tone]">
              {{ isPeriodLoading ? '…' : metric.value }}
            </div>

            <div class="mt-1 text-xs text-slate-500">{{ metric.hint }}</div>
          </div>
        </div>

        <!--
          Проекты: таблица во всю ширину. Панель выбранного проекта — боковой
          дровер поверх содержимого (HomeProjectDetailsDrawer в конце шаблона),
          поэтому таблица больше не делит строку с колонкой справа и не прыгает
          при выборе.
        -->
        <section class="ms-surface flex min-w-0 flex-col gap-3 p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-base font-semibold text-slate-900">Проекты</h2>
            <B24Button label="Все проекты" color="link" size="xs" @click="router.push('/projects')" />
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <button
              v-for="filter in PROJECT_QUICK_FILTERS"
              :key="filter.id"
              type="button"
              class="rounded-full border px-3 py-1.5 text-xs font-semibold transition"
              :class="quickFilter === filter.id
                ? 'border-[#0075ff] bg-[#0075ff] text-white'
                : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'"
              :aria-pressed="quickFilter === filter.id"
              @click="setQuickFilter(filter.id)"
            >
              {{ filter.label }} · {{ quickFilterCounts[filter.id] }}
            </button>

            <input
              v-model="projectSearch"
              type="search"
              placeholder="Проект, компания, куратор, ID"
              aria-label="Поиск по проектам"
              class="h-[34px] min-w-[200px] grow rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-[#0075ff]"
            >
          </div>

          <B24Empty v-if="isPortfolioLoading" title="Загружаем портфель проектов…" size="sm" />
          <B24Empty v-else-if="allProjectRows.length === 0" title="Активных проектов нет." size="sm" />
          <B24Empty v-else-if="projectRows.length === 0" title="По этому отбору проектов не нашлось." size="sm" />

          <div v-else class="ms-table-shell max-h-[560px] overflow-y-auto">
            <table class="ms-table">
              <thead>
                <tr>
                  <th scope="col">Проект</th>
                  <th scope="col">Куратор</th>
                  <th scope="col">Стадия</th>
                  <th scope="col">Освоение</th>
                  <th scope="col" class="text-right">Списание</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in decoratedProjectRows"
                  :key="item.row.id"
                  class="cursor-pointer"
                  :class="selectedProjectId === item.row.id ? 'bg-blue-50/70' : ''"
                  @click="selectProject(item.row)"
                >
                  <td>
                    <!--
                      Название проекта — настоящая кнопка, а не просто ячейка:
                      панель должна открываться и с клавиатуры, и именно сюда
                      возвращается фокус после её закрытия. Клик по остальной
                      строке работает как раньше, поэтому у кнопки .stop —
                      иначе selectProject позвался бы дважды.
                    -->
                    <button
                      :ref="element => setProjectRowTrigger(item.row.id, element)"
                      type="button"
                      class="block w-full rounded-md text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0075ff]"
                      aria-haspopup="dialog"
                      :aria-expanded="isProjectPanelOpen && selectedProjectId === item.row.id"
                      @click.stop="selectProject(item.row)"
                    >
                      <span class="block text-sm font-semibold text-slate-900">{{ item.row.name }}</span>
                      <span class="block text-xs text-slate-500">{{ item.row.companyName }}</span>
                    </button>
                  </td>
                  <td>
                    <span class="inline-flex items-center gap-2 whitespace-nowrap">
                      <span
                        class="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-semibold text-slate-600"
                        aria-hidden="true"
                      >{{ initialsOf(item.row.curatorName) }}</span>
                      <span class="text-sm text-slate-700">{{ item.row.curatorName }}</span>
                    </span>
                  </td>
                  <td>
                    <span class="ms-pill" :class="getProjectStageClass(item.row.stage)">{{ item.row.stage }}</span>
                  </td>
                  <td>
                    <span v-if="item.utilization.isEmpty" class="text-xs text-slate-500">
                      {{ item.utilization.label }}
                    </span>
                    <span v-else class="inline-flex items-center gap-2">
                      <span class="h-1.5 w-10 overflow-hidden rounded-full bg-slate-200">
                        <span
                          class="block h-full rounded-full"
                          :class="UTILIZATION_BAR_CLASS[item.utilization.tone]"
                          :style="{ width: item.utilization.barPercent + '%' }"
                        />
                      </span>
                      <span class="text-xs font-semibold tabular-nums" :class="METRIC_TONE_CLASS[item.utilization.tone]">
                        {{ item.utilization.label }}
                      </span>
                    </span>
                  </td>
                  <td class="text-right tabular-nums" :class="getWriteoffClass(item.row.lastWriteoffDays)">
                    {{ formatLastWriteoff(item.row.lastWriteoffDays) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <!--
        Панель выбранного проекта. Лежит поверх содержимого и ниже по стопке,
        чем дровер карточки проекта (z-9990 против z-9999), но одновременно они
        не показываются: openProjectCard закрывает панель.
      -->
      <HomeProjectDetailsDrawer
        v-model:open="isProjectPanelOpen"
        :panel="projectPanel"
        :month-title="monthTitle"
        :billing-enabled="FINANCE_BILLING_ENABLED"
        :billing-badge="PAID_FEATURE_BADGE"
        @open-group="openSelectedProjectGroup"
        @open-report="openSelectedProjectReport"
        @open-card="openSelectedProjectCard"
        @open-billing="openBillingFeature"
      />

      <ProjectBoardDrawer
        v-model="isDrawerOpen"
        :card="drawerCard"
        :employees="drawerEmployeeOptions"
        :companies="drawerCompanyOptions"
        :legal-entities="drawerLegalEntityOptions"
        :is-saving="isSaving"
        :is-archiving="isArchiving"
        @save="handleSaveProjectCard"
        @archive="handleArchiveProjectCard"
        @open-project="openProject"
        @open-spa="openSpa"
      />

      <CreateProjectDrawer v-if="CREATE_PROJECT_BUTTON_ENABLED" v-model:open="createProjectOpen" @created="onProjectCreated" />
    </div>
  </div>
</template>
