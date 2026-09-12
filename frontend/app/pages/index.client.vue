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
import { computed, onMounted, ref, watch } from 'vue'
import { buildReportRouteLocation, type ReportRouteName, type ReportRoutePayload } from '~/utils/reportNavigation'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import type { PeriodCheckResult } from '~/types/period'
import { openProjectGroup } from '~/utils/openProjectGroup'
import { openCrmItemCard } from '~/utils/openCrmItem'
import CreateProjectDrawer from '~/components/projects/CreateProjectDrawer.vue'
import ProjectBoardDrawer from '~/components/projects/ProjectBoardDrawer.vue'
import { CREATE_PROJECT_BUTTON_ENABLED, TASK_TAB_ROUTE } from '~/utils/featureFlags'
import { NAV_CONTROL_ISSUES_STATE_KEY } from '~/utils/appNavigation'
import {
  buildHomeMetrics,
  buildProjectRows,
  countPeriodBlockers,
  filterProjectRows,
  formatHours,
  formatMonthTitle,
  formatMonthValue,
  parseMonthValue,
  sortProjectRows,
  type ProjectRow,
} from '~/utils/homeDashboard'

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

// --- Показатели месяца ---
const selectedMonth = ref(formatMonthValue(new Date()))
const periodCheck = ref<PeriodCheckResult | null>(null)
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
const metrics = computed(() => buildHomeMetrics(periodCheck.value))

const allProjectRows = computed(() => sortProjectRows(buildProjectRows(portfolioData.value?.cards)))
const projectRows = computed(() => filterProjectRows(allProjectRows.value, projectSearch.value))

const METRIC_TONE_CLASS = {
  neutral: 'text-slate-900',
  warning: 'text-amber-600',
  danger: 'text-rose-600',
} as const

function openReport(target: ReportRouteName | ReportRoutePayload) {
  router.push(buildReportRouteLocation(target))
}

function openGuide() {
  router.push('/guide')
}

function getStageClass(stage?: string | null) {
  const normalized = String(stage || '')
  if (normalized.includes('Нет списаний 3 месяца')) {
    return 'bg-rose-100 text-rose-700'
  }
  if (normalized.includes('Нет списаний 1 месяц')) {
    return 'bg-amber-100 text-amber-700'
  }
  if (normalized.includes('В просчете')) {
    return 'bg-indigo-100 text-indigo-700'
  }
  if (normalized.includes('В работе')) {
    return 'bg-emerald-100 text-emerald-700'
  }
  return 'bg-slate-100 text-slate-700'
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

watch(selectedMonth, () => {
  if (isInit.value) {
    loadPeriodCheck()
  }
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
  openReport({
    report,
    projectId: row.id,
    projectName: row.name,
    autogenerate: true,
  })
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
    ])
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <B24Container>
    <B24PageHeader
      title="Рабочее пространство"
      description="Показатели выбранного месяца и портфель проектов. Разделы приложения — в меню сверху."
    >
      <template #links>
        <B24Button label="Юзергайд" color="default" @click="openGuide" />
        <B24Button v-if="CREATE_PROJECT_BUTTON_ENABLED" label="Создать проект" color="primary" @click="createProjectOpen = true" />
      </template>
    </B24PageHeader>

    <div v-if="isInit" class="mt-6 space-y-6">
      <!-- Показатели выбранного месяца -->
      <B24Card>
        <template #header>
          <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <span class="text-base font-semibold text-slate-900">Месяц: {{ monthTitle }}</span>
              <p class="mt-1 text-sm text-slate-500">
                Данные проверки месяца — те же, по которым закрывается период.
              </p>
            </div>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Выбрать месяц</span>
              <input
                v-model="selectedMonth"
                type="month"
                class="w-full min-w-[180px] rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none transition focus:border-[#0075ff] focus:ring-1 focus:ring-[#0075ff]"
              >
            </label>
          </div>
        </template>

        <p v-if="periodError" class="mb-3 text-sm text-rose-600">{{ periodError }}</p>

        <B24PageGrid>
          <B24Card v-for="metric in metrics" :key="metric.id">
            <div class="text-xs text-slate-400">{{ metric.label }}</div>
            <div class="mt-2 text-3xl font-semibold" :class="METRIC_TONE_CLASS[metric.tone]">
              {{ isPeriodLoading ? '…' : metric.value }}
            </div>
            <div class="mt-1 text-xs text-slate-500">{{ metric.hint }}</div>
          </B24Card>
        </B24PageGrid>

        <template #footer>
          <B24Button label="Закрытие месяца" color="default" @click="router.push('/settings/periods')" />
        </template>
      </B24Card>

      <!-- Таблица проектов с быстрым фильтром -->
      <B24Card>
        <template #header>
          <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <span class="text-base font-semibold text-slate-900">Проекты</span>
              <p class="mt-1 text-sm text-slate-500">
                Показано {{ projectRows.length }} из {{ allProjectRows.length }}. Сверху — те, по кому дольше всех не было списаний.
              </p>
            </div>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Быстрый фильтр</span>
              <input
                v-model="projectSearch"
                type="search"
                placeholder="Название, компания, куратор, стадия, ID"
                class="w-full min-w-[260px] rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none transition focus:border-[#0075ff] focus:ring-1 focus:ring-[#0075ff]"
              >
            </label>
          </div>
        </template>

        <B24Empty v-if="isPortfolioLoading" title="Загружаем портфель проектов…" size="sm" />
        <B24Empty v-else-if="allProjectRows.length === 0" title="Активных проектов нет." size="sm" />
        <B24Empty v-else-if="projectRows.length === 0" title="По этому фильтру проектов не нашлось." size="sm" />

        <div v-else class="ms-table-shell mt-4 max-h-[560px] overflow-y-auto">
          <table class="ms-table">
            <thead>
              <tr>
                <th scope="col">Проект</th>
                <th scope="col">Компания</th>
                <th scope="col">Куратор</th>
                <th scope="col">Стадия</th>
                <th scope="col" class="text-right">Часов</th>
                <th scope="col" class="text-right">Последнее списание</th>
                <th scope="col" class="text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in projectRows" :key="row.id">
                <td>
                  <button
                    type="button"
                    class="text-left text-sm font-semibold text-slate-900 hover:text-[#0075ff]"
                    @click="openProjectCard(row.card)"
                  >
                    {{ row.name }}
                  </button>
                  <div class="text-xs text-slate-400">ID {{ row.id }}</div>
                </td>
                <td>{{ row.companyName }}</td>
                <td>{{ row.curatorName }}</td>
                <td>
                  <span class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold" :class="getStageClass(row.stage)">
                    {{ row.stage }}
                  </span>
                </td>
                <td class="text-right tabular-nums">{{ formatHours(row.actualHours) }}</td>
                <td class="text-right tabular-nums" :class="getWriteoffClass(row.lastWriteoffDays)">
                  {{ row.lastWriteoffDays }} дн.
                </td>
                <td>
                  <div class="flex justify-end gap-2">
                    <B24Button label="Отчёт" color="link" size="xs" @click="openProjectReport(row)" />
                    <B24Button label="Группа" color="link" size="xs" @click="openProject(row.card)" />
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </B24Card>
    </div>

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
  </B24Container>
</template>
