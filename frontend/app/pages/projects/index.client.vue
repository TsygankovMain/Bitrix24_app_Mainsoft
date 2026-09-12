<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { useB24Helper } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import { useProgress } from '~/composables/useProgress'
import CreateProjectDrawer from '~/components/projects/CreateProjectDrawer.vue'
import ProjectBoardColumn from '~/components/projects/ProjectBoardColumn.vue'
import ProjectBoardDrawer from '~/components/projects/ProjectBoardDrawer.vue'
import ProjectBoardToolbar from '~/components/projects/ProjectBoardToolbar.vue'
import ProjectTimelineLane from '~/components/projects/ProjectTimelineLane.vue'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption, ProjectBoardResponse } from '~/utils/projectBoard'
import { upsertProjectBoardCard, buildProjectBoardSummary, formatProjectDate, getTimelineAnchor, parseProjectDateValue } from '~/utils/projectBoard'
import type { ProjectBoardFilterState, ProjectBoardView } from '~/utils/projectBoardView'
import {
  DEFAULT_PROJECT_BOARD_FILTERS,
  buildBoardColumns,
  buildBoardEmptyState,
  buildBoardViewStorageKey,
  countActiveBoardFilters,
  filterBoardCards,
  isBoardCardAtRisk,
  isBoardCardMine,
  parseBoardViewState,
  serializeBoardViewState,
  sortBoardCards,
} from '~/utils/projectBoardView'
import { openProjectGroup } from '~/utils/openProjectGroup'
import { openCrmItemCard } from '~/utils/openCrmItem'
import { buildReportRouteLocation } from '~/utils/reportNavigation'
import { isRateLimitError, RATE_LIMIT_NOTICE_TEXT } from '~/utils/apiErrors'
import { CREATE_PROJECT_BUTTON_ENABLED } from '~/utils/featureFlags'

const route = useRoute()
const router = useRouter()
const { locales: localesI18n, setLocale } = useI18n()
const fieldConfigStore = useFieldConfigStore()
const userStore = useUserStore()
const { getB24Helper } = useB24Helper()

useHead({
  title: 'Управление проектами',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('ProjectBoardPage')
const { $initializeB24Frame } = useNuxtApp()
const progress = useProgress()

let $b24: null | B24Frame = null

const apiStore = useApiStore()

const isInit = ref(false)
const isLoading = ref(false)
const isSyncing = ref(false)
const isRefreshingMeta = ref(false)
const isSaving = ref(false)
const isArchiving = ref(false)

const boardData = ref<ProjectBoardResponse | null>(null)
const employeeDirectory = ref<ProjectBoardDirectoryOption[]>([])
const companyDirectory = ref<ProjectBoardDirectoryOption[]>([])
const legalEntityDirectory = ref<ProjectBoardDirectoryOption[]>([])
const curatorFilters = ref<ProjectBoardDirectoryOption[]>([])
const companyFilters = ref<ProjectBoardDirectoryOption[]>([])
const legalEntityFilters = ref<ProjectBoardDirectoryOption[]>([])

const activeView = ref<ProjectBoardView>('board')
const filters = ref<ProjectBoardFilterState>({
  ...DEFAULT_PROJECT_BOARD_FILTERS,
  search: typeof route.query.search === 'string' ? route.query.search : '',
})

const selectedCard = ref<ProjectBoardCardRecord | null>(null)
const isDrawerOpen = ref(false)
const createProjectOpen = ref(false)
const draggedProjectId = ref<string | null>(null)
const statusMessage = ref<{ type: 'success' | 'warning' | 'error', text: string } | null>(null)

/**
 * Выбранные фильтры и вид переживают уход со страницы.
 *
 * Руководитель отбирает своё («Мои», «Под риском», куратор) один раз, уходит
 * в отчёт по проекту и возвращается на доску — и до этой правки возвращался
 * к полному списку всех проектов портала, каждый раз собирая отбор заново.
 * Хранилище — localStorage браузера, ключ включает портал и пользователя;
 * почему так, а не на сервере, расписано в utils/projectBoardView.ts.
 *
 * Флаг нужен, чтобы наблюдатель ниже не записал состояние по умолчанию
 * ПОВЕРХ сохранённого до того, как оно прочитано.
 */
const isViewStateReady = ref(false)

function viewStateStorageKey() {
  let portal = ''

  try {
    portal = getB24Helper()?.hostName || ''
  } catch {
    // Помощник Битрикса ещё не поднялся — это штатное состояние первых кадров.
    portal = ''
  }

  return buildBoardViewStorageKey({ portal, userId: userStore.id })
}

function restoreViewState() {
  if (typeof window === 'undefined') {
    isViewStateReady.value = true
    return
  }

  try {
    const stored = parseBoardViewState(window.localStorage.getItem(viewStateStorageKey()))
    activeView.value = stored.view
    filters.value = {
      ...stored.filters,
      // Адрес сильнее хранилища: если на доску пришли со строкой поиска в
      // query (например, из другого экрана), показать надо именно её.
      search: typeof route.query.search === 'string' && route.query.search
        ? route.query.search
        : stored.filters.search,
    }
  } catch {
    // Приватный режим или запрещённое хранилище: живём с фильтрами по умолчанию.
  } finally {
    isViewStateReady.value = true
  }
}

function persistViewState() {
  if (typeof window === 'undefined' || !isViewStateReady.value) {
    return
  }

  try {
    window.localStorage.setItem(
      viewStateStorageKey(),
      serializeBoardViewState({ view: activeView.value, filters: filters.value })
    )
  } catch {
    // Квота или приватный режим: отбор проживёт до перезагрузки страницы.
  }
}

watch([filters, activeView], persistViewState, { deep: true })

function resetFilters() {
  filters.value = { ...DEFAULT_PROJECT_BOARD_FILTERS }
}

const messageClass = computed(() => {
  if (!statusMessage.value) {
    return ''
  }

  if (statusMessage.value.type === 'success') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }

  if (statusMessage.value.type === 'warning') {
    return 'border-amber-200 bg-amber-50 text-amber-700'
  }

  return 'border-red-200 bg-red-50 text-red-700'
})

const allCards = computed(() => boardData.value?.cards || [])

function buildOptionsFromCards(
  idGetter: (card: ProjectBoardCardRecord) => string | null | undefined,
  nameGetter: (card: ProjectBoardCardRecord) => string | null | undefined
) {
  const seenIds = new Set<string>()
  const result: ProjectBoardDirectoryOption[] = []

  for (const card of allCards.value) {
    const optionId = String(idGetter(card) || '').trim()
    const optionName = String(nameGetter(card) || '').trim()
    if (!optionId || seenIds.has(optionId)) {
      continue
    }

    seenIds.add(optionId)
    result.push({
      id: optionId,
      name: optionName || optionId,
      search_text: optionName || optionId,
    })
  }

  return result
}

function mergeSelectOptions(
  ...groups: Array<ProjectBoardDirectoryOption[]>
) {
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

const drawerEmployeeOptions = computed(() =>
  mergeSelectOptions(
    employeeDirectory.value,
    buildOptionsFromCards(
      card => card.curator_user_id,
      card => card.curator_name
    )
  )
)

const drawerCompanyOptions = computed(() =>
  mergeSelectOptions(
    companyDirectory.value,
    buildOptionsFromCards(
      card => card.company_id,
      card => card.company_name
    )
  )
)

const drawerLegalEntityOptions = computed(() =>
  mergeSelectOptions(
    legalEntityDirectory.value,
    buildOptionsFromCards(
      card => card.our_legal_entity_id,
      card => card.our_legal_entity_name
    )
  )
)

const curatorFilterOptions = computed(() =>
  mergeSelectOptions(
    curatorFilters.value,
    buildOptionsFromCards(
      card => card.curator_user_id,
      card => card.curator_name
    )
  )
)

const companyFilterOptions = computed(() =>
  mergeSelectOptions(
    companyFilters.value,
    buildOptionsFromCards(
      card => card.company_id,
      card => card.company_name
    )
  )
)

// Серверный поиск компаний по мере ввода — то же самое, чем заведена
// SearchableSelect в ProjectBoardDrawer.vue (см. frontend/app/utils/companySearch.ts).
// companyFilterOptions выше — только компании, уже встречавшиеся в карточках
// на доске; полный справочник портала (23 252 записи) больше не выгружается.
async function searchCompanyOptions(query: string) {
  const result = await apiStore.searchCompanies(query)
  return { options: result.companies, truncated: result.truncated, failed: result.failed }
}

const legalEntityFilterOptions = computed(() =>
  mergeSelectOptions(
    legalEntityFilters.value,
    buildOptionsFromCards(
      card => card.our_legal_entity_id,
      card => card.our_legal_entity_name
    )
  )
)

const filteredCards = computed(() =>
  filterBoardCards(allCards.value, filters.value, { currentUserId: userStore.id })
)

const activeCards = computed(() => filteredCards.value.filter(card => !card.is_archived))

const archivedCards = computed(() => sortBoardCards(filteredCards.value.filter(card => card.is_archived), 'name'))

/** Все неархивные карточки — база для счётчиков на чипах: они не должны обнуляться сами о себя. */
const activeCardsUnfiltered = computed(() => allCards.value.filter(card => !card.is_archived))

const mineCount = computed(() =>
  activeCardsUnfiltered.value.filter(card => isBoardCardMine(card, userStore.id)).length
)

const riskCount = computed(() => activeCardsUnfiltered.value.filter(isBoardCardAtRisk).length)

const boardColumns = computed(() =>
  buildBoardColumns(boardData.value?.stages || [], activeCards.value, filters.value.sort)
)

const scopeCount = computed(() =>
  activeView.value === 'archive'
    ? allCards.value.filter(card => card.is_archived).length
    : activeCardsUnfiltered.value.length
)

const visibleCount = computed(() =>
  activeView.value === 'archive' ? archivedCards.value.length : activeCards.value.length
)

const emptyState = computed(() => buildBoardEmptyState({
  view: activeView.value,
  totalCards: allCards.value.length,
  visibleCount: visibleCount.value,
  scopeCount: scopeCount.value,
  activeFilters: countActiveBoardFilters(filters.value),
}))

const canOpenSpa = computed(() => Boolean(fieldConfigStore.entityTypeId))

const timelineCards = computed(() =>
  activeCards.value
    .slice()
    .sort((left, right) => {
      const leftAnchor = normalizeDate(getTimelineAnchor(left))
      const rightAnchor = normalizeDate(getTimelineAnchor(right))

      if (leftAnchor && rightAnchor) {
        return leftAnchor.getTime() - rightAnchor.getTime()
      }

      return left.project_name.localeCompare(right.project_name, 'ru')
    })
)

const timelineRange = computed(() => {
  const anchors: Date[] = []

  for (const card of timelineCards.value) {
    const start = normalizeDate(card.project_start_date || card.last_writeoff_at || card.created_at)
    const end = normalizeDate(card.project_end_date || card.updated_at || card.last_writeoff_at)

    if (start) {
      anchors.push(start)
    }
    if (end) {
      anchors.push(end)
    }
  }

  if (anchors.length === 0) {
    const today = new Date()
    return {
      start: toLocalDateString(new Date(today.getFullYear(), today.getMonth(), 1)),
      end: toLocalDateString(today)
    }
  }

  anchors.sort((left, right) => left.getTime() - right.getTime())
  return {
    start: toLocalDateString(anchors[0]),
    end: toLocalDateString(anchors[anchors.length - 1])
  }
})

function normalizeDate(value?: string | null) {
  if (!value) {
    return null
  }

  const parsed = parseProjectDateValue(value)
  if (Number.isNaN(parsed.getTime())) {
    return null
  }

  return parsed
}

function toLocalDateString(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function showStatus(type: 'success' | 'warning' | 'error', text: string) {
  statusMessage.value = { type, text }
  setTimeout(() => {
    if (statusMessage.value?.text === text) {
      statusMessage.value = null
    }
  }, 5000)
}

function applyUpdatedCard(updatedCard: ProjectBoardCardRecord) {
  if (!boardData.value) {
    return
  }

  const cards = upsertProjectBoardCard(boardData.value.cards, updatedCard)

  boardData.value = {
    ...boardData.value,
    cards,
    summary: buildProjectBoardSummary(cards)
  }

  if (selectedCard.value?.project_id === updatedCard.project_id) {
    selectedCard.value = updatedCard
  }
}

async function loadBoard(forceRefresh = false) {
  boardData.value = await apiStore.getProjectBoard(forceRefresh)

  if (boardData.value?.warning) {
    showStatus('warning', boardData.value.warning)
  }
}

async function onProjectCreated() {
  // Локальная строка уже записана write-through'ом на бэкенде,
  // поэтому доске достаточно перечитать себя — фоновый синк ждать не нужно.
  await loadBoard(true)
}

async function loadMeta(forceRefresh = false) {
  const meta = await apiStore.getProjectBoardMeta(forceRefresh)
  const directories = meta.directories || {}
  const filterDirectories = meta.filters || {}

  employeeDirectory.value = directories.employees || meta.employees || []
  companyDirectory.value = directories.companies || meta.companies || []
  legalEntityDirectory.value = directories.legal_entities || meta.legal_entities || []
  curatorFilters.value = filterDirectories.curators || directories.employees || meta.employees || []
  companyFilters.value = filterDirectories.companies || directories.companies || meta.companies || []
  legalEntityFilters.value = filterDirectories.legal_entities || directories.legal_entities || meta.legal_entities || []
  return meta
}

function isMetaSparse(meta?: {
  employees?: Array<unknown>
  companies?: Array<unknown>
  directories?: {
    employees?: Array<unknown>
    companies?: Array<unknown>
  }
}) {
  const directories = meta?.directories || meta
  return !directories?.employees?.length || !directories?.companies?.length
}

async function refreshReferenceOptions(showToast = true) {
  isRefreshingMeta.value = true
  try {
    const meta = await loadMeta(true)
    if (showToast) {
      if (isMetaSparse(meta)) {
        showStatus('warning', 'Справочники обновлены частично. Недостающие компании и кураторы показаны по уже сохраненным карточкам проектов.')
      } else {
        showStatus('success', 'Справочники компаний и кураторов обновлены.')
      }
    }
  } catch (error) {
    // HTTP 429 от board_meta_refresh (6 запросов/60 секунд на аккаунт, см.
    // backends/python/api/main/utils/decorators/rate_limit.py) — это ожидаемая,
    // самовосстанавливающаяся ситуация «подождите минуту», а не сбой
    // приложения.
    //
    // После централизации (см. shouldTreatAsFatalError в
    // frontend/app/utils/apiErrors.ts и processErrorGlobal в
    // frontend/app/composables/useAppInit.ts) простой вызов
    // processErrorGlobal(error) для 429 САМ ПО СЕБЕ уже не уронит страницу —
    // он покажет глобальный тост и вернётся. Эта ветка тем не менее
    // осталась не как дубль, а потому что даёт то, чего у централизованного
    // пути нет:
    //  1. Уважает контракт параметра showToast: при showToast === false
    //     здесь нужна полная тишина. Сегодня ни один вызывающий код не
    //     передаёт false (это исторический параметр — раньше так тихо
    //     дёргался автовызов refreshReferenceOptions(false) в onMounted; сам
    //     автовызов убран коммитом 7c0f58f, сигнатура осталась ради обратной
    //     совместимости), и processErrorGlobal об этом параметре знать не
    //     может — показал бы тост безусловно, даже если бы такой вызов
    //     появился вновь.
    //  2. Текст и место контекстные — тот же showStatus-баннер, что и у
    //     success/warning этой же кнопки «Обновить справочники», а не общий
    //     плавающий тост в отрыве от места клика.
    //  3. Без этой ветки else-путь ниже показал бы вводящее в заблуждение
    //     showStatus('error', 'Не удалось обновить...') ПЕРЕД тем, как
    //     processErrorGlobal(error) покажет верный текст отдельным тостом —
    //     то есть заменил бы один дубль на другой, а не убрал его.
    // Остальные ошибки (не 429) — как раньше, без изменений.
    if (isRateLimitError(error)) {
      if (showToast) {
        showStatus('warning', RATE_LIMIT_NOTICE_TEXT)
      }
    } else {
      if (showToast) {
        showStatus('error', 'Не удалось обновить справочники компаний и кураторов.')
      }
      processErrorGlobal(error)
    }
  } finally {
    isRefreshingMeta.value = false
  }
}

async function syncBoard(showToast = true) {
  progress.begin('Синхронизация проектов', 0, 'Обновляем доску проектов')
  isSyncing.value = true
  try {
    const result = await apiStore.syncProjectCards()
    await Promise.all([
      loadMeta(true),
      loadBoard(true)
    ])

    if (showToast) {
      const baseMessage = `Синхронизировано ${result.synced || 0} проектов. Новых: ${result.created || 0}, обновлено: ${result.updated || 0}.`
      if (result.warning) {
        showStatus('warning', `${baseMessage} ${result.warning}`)
      } else {
        showStatus('success', baseMessage)
      }
    }
  } catch (error) {
    try {
      await loadBoard(true)
    } catch {
      // keep original sync error for global handler
    }

    // См. пояснение в catch у refreshReferenceOptions выше (включая то, почему
    // эта ветка не дубль централизованного processErrorGlobal, а нужна
    // отдельно): HTTP 429 от лимитера "sync" (или от board_meta_refresh —
    // один клик «Синхронизировать» тратит бюджет обоих, см.
    // Promise.all([loadMeta(true), loadBoard(true)]) выше) не должен уводить
    // на фатальный экран и должен остаться в контекстном showStatus-баннере
    // этой кнопки, а не в общем тосте.
    if (isRateLimitError(error)) {
      showStatus('warning', RATE_LIMIT_NOTICE_TEXT)
    } else {
      showStatus('error', 'Не удалось синхронизировать проекты. Попробуйте еще раз или проверьте права приложения в Битрикс24.')
      processErrorGlobal(error)
    }
  } finally {
    isSyncing.value = false
    progress.end()
  }
}

async function runDailyCheck() {
  isSyncing.value = true
  try {
    const result = await apiStore.runProjectBoardDailyCheck()
    await loadBoard(true)
    showStatus(
      'success',
      `Проверено ${result.checked || 0} проектов. В 30 дней: ${result.moved_to_30_days || 0}, в 90 дней: ${result.moved_to_90_days || 0}, возвращено в работу: ${result.returned_to_work || 0}.`
    )
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isSyncing.value = false
  }
}

async function openCard(card: ProjectBoardCardRecord) {
  selectedCard.value = card
  isDrawerOpen.value = true

  try {
    const detailedCard = await apiStore.getProjectBoardCard(card.project_id)
    if (detailedCard) {
      applyUpdatedCard(detailedCard)
      selectedCard.value = detailedCard
    }
  } catch (error) {
    // Keep fallback card state if detail loading fails.
    console.warn('[ProjectBoard] Failed to load detailed card', error)
  }
}

function openProject(card?: ProjectBoardCardRecord | null) {
  const targetCard = card || selectedCard.value
  if (!targetCard) {
    return
  }

  openProjectGroup(targetCard.project_id)
}

function openSpa(card?: ProjectBoardCardRecord | null) {
  const targetCard = card || selectedCard.value
  if (!targetCard) {
    return
  }

  const spEntityTypeId = fieldConfigStore.entityTypeId
  const projectItemId = targetCard.project_item_id

  if (spEntityTypeId && projectItemId) {
    openCrmItemCard(spEntityTypeId, projectItemId)
  } else {
    showStatus('warning', 'Нет привязки к элементу SPA.')
  }
}

/**
 * «Отчёт» на карточке — тот же отчёт по проекту, что и в меню раздела, но уже
 * отобранный по этому проекту и сразу построенный (autogenerate). Раньше путь
 * от доски к цифрам проекта был: открыть дровер, запомнить название, уйти в
 * отчёт, найти проект в списке фильтра, нажать «Построить».
 */
function openProjectReport(card: ProjectBoardCardRecord) {
  router.push(buildReportRouteLocation({
    report: 'project',
    projectId: card.project_id,
    projectName: card.project_name,
    autogenerate: true,
  }))
}

function handleDragStart(projectId: string) {
  draggedProjectId.value = projectId
}

function handleDragEnd() {
  draggedProjectId.value = null
}

async function handleDropCard(payload: { projectId: string, stage: string }) {
  if (!payload.projectId || !payload.stage) {
    return
  }

  const currentCard = allCards.value.find(card => card.project_id === payload.projectId)
  const resolvedStageTitle = boardData.value?.stages.find(stage => String(stage.id) === payload.stage)?.title || payload.stage
  draggedProjectId.value = null

  if (!currentCard || currentCard.stage === payload.stage || currentCard.stage === resolvedStageTitle) {
    return
  }

  try {
    const response = await apiStore.updateProjectStage(payload.projectId, payload.stage)
    if (response.card) {
      applyUpdatedCard(response.card)
      showStatus('success', `Проект переведен в статус «${resolvedStageTitle}».`)
    }
  } catch (error) {
    processErrorGlobal(error)
  }
}

async function handleSaveProject(payload: Record<string, unknown>) {
  isSaving.value = true
  try {
    const response = await apiStore.updateProjectCard(payload)
    if (response.card) {
      applyUpdatedCard(response.card)
    }

    if (response.warning) {
      showStatus('warning', response.warning)
    } else {
      showStatus('success', 'Карточка проекта обновлена.')
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isSaving.value = false
  }
}

async function handleArchiveProject(nextArchivedState: boolean) {
  if (!selectedCard.value) {
    return
  }

  isArchiving.value = true
  try {
    const response = await apiStore.archiveProject(selectedCard.value.project_id, nextArchivedState)
    if (response.card) {
      applyUpdatedCard(response.card)
    }

    if (response.warning) {
      showStatus('warning', response.warning)
    } else {
      showStatus('success', nextArchivedState ? 'Проект отправлен в архив.' : 'Проект возвращен из архива.')
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isArchiving.value = false
  }
}

onMounted(async () => {
  isLoading.value = true
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Управление проектами')
    isInit.value = true

    // Фильтры читаем после initApp: до него неизвестны ни портал, ни
    // пользователь, а они оба входят в ключ хранилища.
    restoreViewState()

    // Раньше здесь при скудном справочнике (isMetaSparse) автоматически
    // запускался refreshReferenceOptions(false) — тихий форс-рефреш без ведома
    // человека. Убрано намеренно: на портале, где в CRM действительно мало
    // компаний, isMetaSparse истинна ПОСТОЯННО, а не изредка, — значит каждое
    // открытие страницы, каждая вкладка и каждая перезагрузка молча тратили
    // единицу общего бюджета лимитера board_meta_refresh (6 запросов/60 секунд
    // на аккаунт, см. backends/python/api/main/utils/decorators/rate_limit.py),
    // конкурируя за тот же бюджет с сознательными кликами по кнопкам
    // «Синхронизировать проекты» и «Обновить справочники». Именно это превращало
    // «пару лишних кликов» в исчерпанный лимит без единого сознательного действия
    // человека — например, у того, кто просто открыл приложение в трёх вкладках.
    // Автоматическое действие, которое молча тратит ограниченный бюджет без
    // ведома человека, — плохая идея сама по себе, независимо от лимита.
    // Справочник и так подтягивается обычным путём (loadMeta() выше, из
    // серверного или браузерного кэша); сознательное обновление остаётся за
    // кнопкой «Обновить справочники».
    await Promise.all([
      loadMeta(),
      loadBoard()
    ])
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <B24Card v-if="isInit" class="ms-surface">
        <template #header>
          <div class="flex w-full flex-col gap-3">
            <div class="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
              <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                <ProseH2 class="!text-slate-900">Проекты</ProseH2>
                <!--
                  Сводка раньше занимала пять карточек-плиток во всю ширину
                  над доской. Это те же числа бэкенда (boardData.summary),
                  собранные в одну строку: на доске важнее видеть саму доску.
                -->
                <div v-if="boardData" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span><b class="text-sm font-semibold text-slate-900">{{ boardData.summary.active_count }}</b> активных</span>
                  <span><b class="text-sm font-semibold text-slate-900">{{ boardData.summary.support_count }}</b> поддержка</span>
                  <span
                    :class="riskCount > 0 ? 'text-amber-700' : ''"
                    title="Нет списаний 30+ дней или перерасход бюджета"
                  ><b class="text-sm font-semibold" :class="riskCount > 0 ? 'text-amber-700' : 'text-slate-900'">{{ riskCount }}</b> под риском</span>
                  <span><b class="text-sm font-semibold text-slate-900">{{ boardData.summary.archived_count }}</b> в архиве</span>
                </div>
              </div>

              <div class="flex flex-wrap gap-2">
                <B24Button v-if="CREATE_PROJECT_BUTTON_ENABLED" label="Создать проект" color="primary" @click="createProjectOpen = true" />
                <B24Button label="Синхронизировать" color="success" :loading="isSyncing" @click="syncBoard()" />
                <B24Button label="Обновить справочники" color="default" :loading="isRefreshingMeta" @click="refreshReferenceOptions()" />
                <B24Button label="Проверить статусы" color="default" :loading="isSyncing" @click="runDailyCheck" />
              </div>
            </div>

            <div class="ms-segmented flex flex-wrap gap-2 self-start">
              <button
                type="button"
                :class="['ms-segmented-btn', activeView === 'board' ? 'ms-segmented-btn-active-dark' : '']"
                @click="activeView = 'board'"
              >
                Канбан
              </button>
              <button
                type="button"
                :class="['ms-segmented-btn', activeView === 'timeline' ? 'ms-segmented-btn-active-dark' : '']"
                @click="activeView = 'timeline'"
              >
                Хронология
              </button>
              <button
                type="button"
                :class="['ms-segmented-btn', activeView === 'archive' ? 'ms-segmented-btn-active-dark' : '']"
                @click="activeView = 'archive'"
              >
                Архив
              </button>
            </div>

            <ProjectBoardToolbar
              v-model="filters"
              :curator-options="curatorFilterOptions"
              :company-options="companyFilterOptions"
              :legal-entity-options="legalEntityFilterOptions"
              :company-search-fn="searchCompanyOptions"
              :shown-count="visibleCount"
              :total-count="scopeCount"
              :mine-count="mineCount"
              :risk-count="riskCount"
              :is-user-known="Boolean(userStore.id)"
              @reset="resetFilters"
            />

            <div
              v-if="statusMessage"
              :class="['rounded-2xl border px-4 py-3 text-sm', messageClass]"
            >
              {{ statusMessage.text }}
            </div>
          </div>
        </template>

        <!--
          Загрузка — скелет доски, а не строка «Загружаем проекты...»: человек
          сразу видит, что придёт доска и сколько примерно места она займёт.
        -->
        <div v-if="isLoading" class="flex gap-3 overflow-hidden" aria-busy="true">
          <div v-for="skeleton in 4" :key="skeleton" class="w-[264px] shrink-0 rounded-2xl border border-slate-200 bg-slate-50 p-2">
            <div class="mb-3 h-4 w-2/3 animate-pulse rounded bg-slate-200" />
            <div v-for="row in 3" :key="row" class="mb-2 h-[88px] animate-pulse rounded-xl bg-white" />
          </div>
        </div>

        <div
          v-else-if="emptyState"
          class="space-y-3 rounded-2xl border border-dashed border-slate-200 py-10 text-center"
        >
          <div class="text-sm font-medium text-slate-700">{{ emptyState.title }}</div>
          <!-- Ширина явным значением, не max-w-md: см. предупреждение в app/assets/css/main.css. -->
          <p class="mx-auto max-w-[28rem] text-xs text-slate-500">{{ emptyState.hint }}</p>
          <B24Button
            v-if="emptyState.showSync"
            label="Синхронизировать сейчас"
            color="success"
            :loading="isSyncing"
            @click="syncBoard()"
          />
          <B24Button
            v-if="emptyState.showReset"
            label="Сбросить фильтры"
            color="default"
            @click="resetFilters"
          />
        </div>

        <!--
          Доска прокручивается по горизонтали своим контейнером: у фрейма
          приложения собственной прокрутки нет, его высота подгоняется под
          контент (requestIframeAutoHeight в layouts/default.vue). Поэтому
          длинные колонки сворачиваются внутри ProjectBoardColumn, а не
          растягивают фрейм на тысячи пикселей.
        -->
        <div
          v-else-if="activeView === 'board'"
          class="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2"
          @dragend="handleDragEnd"
        >
          <ProjectBoardColumn
            v-for="column in boardColumns"
            :key="column.id"
            :column="column"
            :can-open-spa="canOpenSpa"
            :is-dragging="Boolean(draggedProjectId)"
            @edit="openCard"
            @dragstart="handleDragStart"
            @drop-card="handleDropCard"
            @open-spa="openSpa"
            @open-report="openProjectReport"
            @open-group="openProject"
          />
        </div>

        <div v-else-if="activeView === 'timeline'" class="space-y-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            Диапазон: {{ formatProjectDate(timelineRange.start) }} - {{ formatProjectDate(timelineRange.end) }}
          </div>

          <ProjectTimelineLane
            v-for="card in timelineCards"
            :key="card.project_id"
            :card="card"
            :range-start="timelineRange.start"
            :range-end="timelineRange.end"
            @open="openCard"
          />
        </div>

        <div v-else class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <button
            v-for="card in archivedCards"
            :key="card.project_id"
            type="button"
            class="rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
            @click="openCard(card)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="truncate text-sm font-semibold text-slate-900">{{ card.project_name }}</div>
                <div class="mt-1 text-xs text-slate-500">
                  {{ card.company_name || 'Без компании' }} · {{ card.curator_name || 'Без куратора' }}
                </div>
                <div class="mt-1 text-xs text-slate-400">
                  {{ card.our_legal_entity_name || 'Юрлицо не выбрано' }}
                </div>
              </div>
              <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
                Архив
              </span>
            </div>
            <div class="mt-4 text-xs text-slate-500">
              Перенесен в архив: {{ card.archived_at ? formatProjectDate(card.archived_at) : 'локально' }}
            </div>
          </button>
        </div>
      </B24Card>

      <ProjectBoardDrawer
        v-model="isDrawerOpen"
        :card="selectedCard"
        :employees="drawerEmployeeOptions"
        :companies="drawerCompanyOptions"
        :legal-entities="drawerLegalEntityOptions"
        :is-saving="isSaving"
        :is-archiving="isArchiving"
        @save="handleSaveProject"
        @archive="handleArchiveProject"
        @open-project="openProject"
        @open-spa="openSpa"
      />

      <CreateProjectDrawer v-if="CREATE_PROJECT_BUTTON_ENABLED" v-model:open="createProjectOpen" @created="onProjectCreated" />
    </div>
  </div>
</template>
