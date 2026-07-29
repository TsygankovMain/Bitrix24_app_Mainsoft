<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { FocusScope } from 'reka-ui'
import type { ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import {
  classifyCompanySearchError,
  companyCreationActionLabel,
  companySearchNoticeText,
  createCompanySearchGate,
  limitVisibleSuggestions,
  normalizeCompanyQuery,
  pendingCompanyDisplayLabel,
  shouldOfferCompanyCreation,
  shouldSearchCompanies,
  type CompanySearchNotice,
} from '~/utils/companySearch'
import {
  computeDropdownPosition,
  type DropdownPositionResult,
} from '~/utils/dropdownPosition'

/** Задержка перед обращением к серверу после того, как человек перестал печатать. */
const SERVER_SEARCH_DEBOUNCE_MS = 300

/** Результат, который обязана вернуть функция серверного поиска (searchFn). */
type SearchableSelectSearchOutcome = {
  options: ProjectBoardDirectoryOption[]
  truncated?: boolean
  failed?: boolean
}

const props = withDefaults(defineProps<{
  modelValue?: string | number | null
  options: ProjectBoardDirectoryOption[]
  label?: string
  emptyLabel?: string
  searchPlaceholder?: string
  disabled?: boolean
  /**
   * Режим брифа "список компаний перестаёт всплывать" (.superpowers/sdd/
   * 2026-07-28-create-project-button/inline-list-brief.md): список рисуется
   * ОБЫЧНЫМ БЛОКОМ В ПОТОКЕ документа под полем, а не во всплывающей панели.
   * Форма создания проекта (CreateProjectModal.vue) — единственный
   * потребитель, которому это нужно: там список раньше телепортировался в
   * body, и это порождало три независимых дефекта подряд (обрезка модалкой,
   * захват фокуса диалогом, клики мимо телепортированной панели) — см.
   * докстринг ниже про то, что в этом режиме сознательно отсутствует.
   *
   * По умолчанию выключен — компонент ведёт себя ТОЧНО как до этого брифа:
   * кнопка-раскрывашка, всплывающая панель, телепорт в body. Доска проектов
   * и отчёты (frontend/app/pages/projects/index.client.vue,
   * ProjectBoardDrawer.vue) используют именно этот, старый режим, и их
   * поведение этот бриф трогать не должен.
   */
  inline?: boolean
  /**
   * Необязательный режим серверного поиска (сегодня — только для компаний,
   * см. frontend/app/utils/companySearch.ts). Без этого пропа компонент
   * работает ровно как раньше: локальная фильтрация переданного options.
   * С ним — options по-прежнему источник для отображения уже выбранного
   * значения (кнопка), а содержимое открытого списка приходит из searchFn.
   */
  searchFn?: (query: string) => Promise<SearchableSelectSearchOutcome>
  /**
   * Название компании, ожидающее создания (form.company_name формы
   * создания проекта, пока company_id ещё не выбран — см.
   * frontend/app/utils/companySearch.ts::companyFieldsForQuery). Проп
   * одновременно и данные для pendingCompanyDisplayLabel (что показать на
   * закрытой кнопке поля / рядом с полем в режиме inline), и включатель
   * режима "создать компанию с этим названием" в открытом списке (см.
   * showCreateAction/shouldOfferCompanyCreation ниже) — оба поведения нужны
   * только форме создания проекта (CreateProjectModal.vue). Остальные
   * потребители компонента (фильтр "Компания" в ProjectBoardDrawer.vue/
   * pages/projects/index.client.vue, поле "Наше юрлицо", "Куратор") проп не
   * передают — для них компонент ведёт себя ровно как раньше: `undefined`
   * означает "режим создания выключен".
   */
  pendingCompanyName?: string | null
}>(), {
  label: '',
  emptyLabel: 'Не выбрано',
  searchPlaceholder: 'Поиск по названию или ИНН',
  disabled: false,
  inline: false,
  pendingCompanyName: undefined,
})

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'update:selected', option: ProjectBoardDirectoryOption | null): void
  /** Д2 хотфикса 2026-07-29: клик по действию "Создать компанию «...»» (см.
   * showCreateAction ниже). Несёт query, а не полагается на то, что
   * form.company_name у родителя уже синхронизирован — searchCompanyOptions
   * пишет его только на реально стартовавший (прошедший debounce) поиск, а
   * человек мог допечатать текст уже после того, как пришёл пустой ответ. */
  (event: 'create-requested', query: string): void
  /**
   * Требование 3 брифа инлайн-версии — "текст человека и есть значение
   * поля": сырой текст поля на КАЖДОЕ нажатие клавиши, а не только на
   * запросы, прошедшие debounce/гейт серверного поиска. Раньше поле
   * company_name синхронизировалось только в момент реально стартовавшего
   * (после 300ms и через createCompanySearchGate) поиска — если человек
   * печатал и уходил с поля быстрее, чем срабатывал debounce, набранный
   * текст никогда не долетал до формы ("введённое название не сохраняется",
   * исходная жалоба, см. брифа "Зачем"). Эмитится только в серверном режиме
   * поиска (сегодня — только компании; локальному режиму без searchFn
   * применять её некуда) и только в inline-режиме — поп-ап режим этот бриф
   * не трогает, у него своя нетронутая связка через searchFn/debounce. */
  (event: 'query-changed', query: string): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const query = ref('')

/**
 * Хотфикс 2026-07-29 «выпадающий список обрезается и закрывает форму» (см.
 * .superpowers/sdd/2026-07-28-create-project-button/hotfix-dropdown-clipping-brief.md):
 * панель телепортируется в body и позиционируется через position:fixed, чтобы
 * её не мог обрезать ни один отсекающий предок — конкретно B24Modal
 * оборачивает содержимое двумя такими контейнерами (overflow-y-auto тела
 * окна и overflow-hidden обёртки), и список с результатами поиска компаний
 * обрезался примерно на 180px без возможности прокрутить до обрезанного.
 * Решение "куда встать и какой высоты быть" — чистая функция
 * computeDropdownPosition (frontend/app/utils/dropdownPosition.ts, покрыта
 * тестами в tests/dropdownPosition.test.ts); эти ref — то немногое, что
 * обязано жить в компоненте, потому что требует живого DOM.
 *
 * ВСЁ ниже до конца этого блока комментариев (панель, FocusScope, слушатели
 * скролла/resize, клик мимо) — код режима props.inline===false (поп-ап,
 * "как раньше"). Бриф "список перестаёт всплывать" (inline-list-brief.md)
 * прямо требует, чтобы в inline-режиме ничего из этого не выполнялось и не
 * регистрировалось — не "выключено флагом", а буквально не вызывается: нет
 * телепорта, нет position:fixed и вычисления координат, нет FocusScope, нет
 * слушателей scroll/resize, нет обработки "клик мимо" (см. onMounted/
 * onBeforeUnmount и watch(isOpen)/watchEffect ниже — все они гасят себя
 * через `if (props.inline) return`). Причина, по которой этот код тем не
 * менее остаётся в файле: поп-ап режим по-прежнему актуален для доски
 * проектов и отчётов (см. докстринг пропа inline выше) — бриф прямо требует
 * не менять их поведение, значит и вся эта машинерия должна продолжать
 * работать для них в точности как раньше.
 *
 * Панель обёрнута в <FocusScope :trapped="false"> из reka-ui (см. шаблон) —
 * без этого печатать в поле поиска внутри B24Modal физически невозможно.
 * У B24Modal/DialogContent включён FocusScope с trapped:true
 * (node_modules/reka-ui/dist/DialogContentModal... :trap-focus="rootContext.open.value"):
 * он вешает на document слушатель 'focusin' и на КАЖДЫЙ фокус вне
 * контейнера диалога синхронно возвращает фокус обратно внутрь —
 * телепортированная в body панель физически вне этого контейнера, поэтому
 * фокус на search-input не удерживался бы ни на мгновение (проверено вживую:
 * document.activeElement откатывался на кнопку-тоггл сразу после .focus()
 * на input). Стек фокус-скоупов reka-ui (FocusScope/stack.ts,
 * createGlobalState — истинный модульный синглтон) устроен так, что
 * ЛЮБОЙ новый FocusScope при монтировании (даже trapped:false) сам
 * ставит на паузу тот, что был активен до него, и снимает паузу при
 * размонтировании — это официальный приём reka-ui/radix для портального
 * контента (комбобоксы, поповеры) внутри чужого trapped-диалога, а не
 * взлом внутренностей. mount-auto-focus гасится намеренно: без этого
 * реcka-ui сам фокусировал бы search-input при каждом открытии — так
 * компонент никогда не вёл себя раньше (после клика по полю фокус
 * оставался на кнопке), лишнее поведение для хотфикса.
 */
const panelRef = ref<HTMLElement | null>(null)
const headerRef = ref<HTMLElement | null>(null)
const listViewportRef = ref<HTMLElement | null>(null)
const dropdownPos = ref<DropdownPositionResult | null>(null)

/**
 * Пересчитывает координаты открытой панели по текущему прямоугольнику
 * якоря и текущей желаемой высоте содержимого. Вызывается при открытии, при
 * любом изменении того, что рисуется внутри панели (см. watchEffect ниже), и
 * при скролле/resize окна, пока список открыт (требование 4 брифа хотфикса).
 * Только поп-ап режим — см. докстринг блока выше.
 */
function updateDropdownPosition() {
  if (!isOpen.value || !rootRef.value) {
    return
  }

  // desiredHeight = шапка (натуральная высота, никогда не обрезается) +
  // перечень ЦЕЛИКОМ. listViewportRef.scrollHeight — это полная высота
  // содержимого прокручиваемого блока НЕЗАВИСИМО от уже применённого к нему
  // инлайн max-height (см. panelStyle ниже: сам max-height живёт на этом же
  // элементе, но scrollHeight по определению считает содержимое без учёта
  // собственного ограничения по высоте) — предыдущий пересчёт не искажает
  // следующее измерение.
  const desiredHeight = (headerRef.value?.offsetHeight ?? 0) + (listViewportRef.value?.scrollHeight ?? 0)

  dropdownPos.value = computeDropdownPosition({
    anchor: rootRef.value.getBoundingClientRect(),
    desiredHeight,
    viewportHeight: window.innerHeight,
  })
}

const panelStyle = computed(() => {
  const pos = dropdownPos.value
  if (!pos) {
    // Первый кадр после открытия, пока позиция ещё не посчитана: Teleport
    // монтирует панель последним потомком body, и без top/left она на
    // мгновение мелькнула бы там, где стояла бы в обычном потоке (у нижнего
    // края документа) — прячем, а не показываем в неверном месте.
    return { visibility: 'hidden' as const, top: '0px', left: '0px', width: '0px', maxHeight: '0px' }
  }

  return {
    top: `${pos.top}px`,
    left: `${pos.left}px`,
    width: `${pos.width}px`,
    maxHeight: `${pos.maxHeight}px`,
  }
})

const isServerSearchMode = computed(() => typeof props.searchFn === 'function')
const hasMinQueryLength = computed(() => shouldSearchCompanies(query.value))

// --- Серверный поиск: состояние, актуальное только когда передан searchFn ---
const searchGate = createCompanySearchGate()
let debounceTimer: ReturnType<typeof setTimeout> | undefined
let searchRequestId = 0

const isSearching = ref(false)
const serverResults = ref<ProjectBoardDirectoryOption[]>([])
const serverTruncated = ref(false)
const serverNotice = ref<CompanySearchNotice | null>(null)
// Опция, выбранную через серверный поиск, запоминаем отдельно от options и
// serverResults: оба могут не содержать её на следующий же рендер (options —
// пока форму не сохранили, serverResults — как только запрос в поле поиска
// сменится на другой). Без этого поле выглядело бы пустым сразу после выбора.
const pinnedOption = ref<ProjectBoardDirectoryOption | null>(null)

const serverNoticeText = computed(() => companySearchNoticeText(serverNotice.value))

function resetServerSearchState() {
  serverResults.value = []
  serverTruncated.value = false
  serverNotice.value = null
  isSearching.value = false
  searchGate.reset()
}

async function runServerSearch(rawQuery: string) {
  const searchFn = props.searchFn
  if (!searchFn) {
    return
  }

  const requestId = ++searchRequestId
  isSearching.value = true

  try {
    const outcome = await searchFn(rawQuery)
    if (requestId !== searchRequestId) {
      return // устарело — пока ждали ответ, в поле ввели что-то ещё
    }
    serverResults.value = outcome.options
    serverTruncated.value = Boolean(outcome.truncated)
    serverNotice.value = outcome.failed ? 'unavailable' : null
  } catch (error) {
    if (requestId !== searchRequestId) {
      return
    }
    // serverResults намеренно не трогаем: то, что уже нашли, остаётся на
    // экране — иначе временный сбой (лимитер 429 или сеть) выглядел бы как
    // "компаний нет" и подтолкнул бы создать дубль уже существующей.
    serverNotice.value = classifyCompanySearchError(error)
    console.error('SearchableSelect: server search failed', error)
  } finally {
    if (requestId === searchRequestId) {
      isSearching.value = false
    }
  }
}

function scheduleServerSearch(rawQuery: string) {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = undefined
  }

  if (!shouldSearchCompanies(rawQuery)) {
    resetServerSearchState()
    return
  }

  debounceTimer = setTimeout(() => {
    debounceTimer = undefined
    if (!searchGate.shouldTrigger(rawQuery)) {
      return
    }
    void runServerSearch(rawQuery)
  }, SERVER_SEARCH_DEBOUNCE_MS)
}

function cancelPendingServerSearch() {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = undefined
  }
  if (isServerSearchMode.value) {
    resetServerSearchState()
  }
}

/**
 * Единственная точка, где меняется query из пользовательского ввода (оба
 * режима — см. :value/@input в шаблоне вместо v-model, ровно чтобы такая
 * точка была одна). Программные изменения query (выбор варианта, клик
 * "Создать компанию", сброс) через этот обработчик НЕ идут — им не нужно ни
 * планировать новый поиск, ни сбрасывать hasUserEdited/suggestionsDismissed
 * (см. их использование ниже).
 */
function onQueryInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  query.value = value
  hasUserEdited.value = true
  if (props.inline) {
    suggestionsDismissed.value = false
    if (isServerSearchMode.value) {
      // См. докстринг события 'query-changed' выше — синхронная синхронизация
      // родителя на каждое нажатие, отдельно от debounce-ного серверного
      // поиска ниже.
      emit('query-changed', value)
    }
  }
  if (isServerSearchMode.value) {
    scheduleServerSearch(value)
  }
}

const normalizedModelValue = computed(() => String(props.modelValue || ''))

const selectedOption = computed(() => {
  const fromOptions = props.options.find(option => String(option.id) === normalizedModelValue.value) || null
  if (fromOptions || !isServerSearchMode.value) {
    return fromOptions
  }

  const fromServerResults = serverResults.value.find(option => String(option.id) === normalizedModelValue.value) || null
  if (fromServerResults) {
    return fromServerResults
  }

  if (pinnedOption.value && String(pinnedOption.value.id) === normalizedModelValue.value) {
    return pinnedOption.value
  }

  return null
})

// Д1 хотфикса 2026-07-29: раньше здесь было "нет selectedOption -> emptyLabel",
// без исключений. Теперь решение вынесено в pendingCompanyDisplayLabel — ей
// среди прочего известно и промежуточное состояние "ничего не выбрано, но
// есть текст, ожидающий создания компании" (см. докстринг пропа
// pendingCompanyName выше). Формат "имя + ИНН" для УЖЕ выбранной компании —
// деталь отображения, не относящаяся к тому решению, поэтому считается
// здесь и передаётся уже готовой строкой. Используется и поп-ап кнопкой, и
// inline-подписью под полем (см. шаблон) — решение одно на оба режима.
const displayLabel = computed(() => {
  const selectedName = selectedOption.value
    ? (selectedOption.value.inn ? `${selectedOption.value.name} · ИНН ${selectedOption.value.inn}` : String(selectedOption.value.name))
    : null

  return pendingCompanyDisplayLabel({
    selectedName,
    pendingName: props.pendingCompanyName,
    emptyLabel: props.emptyLabel,
  })
})

const filteredOptions = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase()
  if (!normalizedQuery) {
    return props.options
  }

  return props.options.filter((option) => {
    const searchTarget = [
      option.name,
      option.inn,
      option.search_text,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return searchTarget.includes(normalizedQuery)
  })
})

/** Список, который реально показывается в открытом выпадающем окне /
 * inline-перечне. */
const visibleOptions = computed(() => (isServerSearchMode.value ? serverResults.value : filteredOptions.value))

/** Требование 4 брифа инлайн-версии — не больше MAX_VISIBLE_SUGGESTIONS
 * строк в потоке, остальное одной строкой про остаток (см.
 * frontend/app/utils/companySearch.ts::limitVisibleSuggestions). Только для
 * inline-разметки — поп-ап список показывает visibleOptions целиком в своей
 * прокручиваемой панели, как и раньше. */
const limitedSuggestions = computed(() => limitVisibleSuggestions(visibleOptions.value))

// Д2 хотфикса 2026-07-29: режим создания включён, только когда родитель
// передал pendingCompanyName (см. её докстринг выше) — без этого пропа
// действие "создать компанию" не появится никогда, даже в серверном режиме
// поиска (фильтр "Компания" на доске проектов/странице проектов и там
// searchFn есть, а смысла создавать компанию из фильтра — нет).
const canOfferCompanyCreation = computed(() => isServerSearchMode.value && props.pendingCompanyName !== undefined)

// Ре-ревью хотфикса 2026-07-29: shouldOfferCompanyCreation сравнивает query с
// каждым названием (не считает штуки) — граница "точное совпадение", а не
// "список непуст", см. её докстринг в companySearch.ts.
const showCreateAction = computed(() => canOfferCompanyCreation.value && shouldOfferCompanyCreation({
  query: query.value,
  isSearching: isSearching.value,
  optionNames: visibleOptions.value.map(option => String(option.name)),
}))

/**
 * true, пока в поле есть текст, для которого ни выбор существующей компании,
 * ни клик "Создать компанию" ещё не сделаны — то самое "ожидающее" название
 * (см. pendingCompanyDisplayLabel). Только для inline-подписи под полем —
 * решение, что показать и как, целиком в displayLabel/pendingCompanyDisplayLabel,
 * здесь только условие "есть что показывать".
 */
const hasPendingCompanyText = computed(() => normalizeCompanyQuery(props.pendingCompanyName ?? '').length > 0)

/** requirement 3 брифа инлайн-версии: пока человек не тронул поле сам,
 * текст обязан отражать уже выбранное/ожидающее значение снаружи (в т.ч. при
 * возврате к незавершённой попытке — CreateProjectModal.vue::
 * shouldResetFormOnOpen). Once он начал печатать — компонент доверяет только
 * его вводу (см. onQueryInput/hasUserEdited) и больше не переинициализирует
 * query из пропов, иначе редактирование конфликтовало бы само с собой. */
const resolvedInlineText = computed(() => {
  if (selectedOption.value) {
    return String(selectedOption.value.name)
  }
  return normalizeCompanyQuery(props.pendingCompanyName ?? '')
})

const hasUserEdited = ref(false)
/** Только inline: список подсказок скрыт после явного выбора/создания, пока
 * человек не начнёт печатать заново (требование 3 брифа: "исчезают, когда
 * выбор сделан или строка пуста"). Поп-ап режим этим не пользуется — у него
 * есть свой, независимый isOpen. */
const suggestionsDismissed = ref(false)

watch(resolvedInlineText, (text) => {
  if (!props.inline || hasUserEdited.value) {
    return
  }
  query.value = text
  suggestionsDismissed.value = Boolean(text)
}, { immediate: true })

/** Только inline: показывать ли перечень под полем вообще. Локальный режим
 * (без searchFn, напр. "Наше юрлицо") ведёт себя как раньше открытая
 * панель — виден целиком независимо от длины запроса, в т.ч. пустого
 * (обычный список для выбора из небольшого фиксированного набора).
 * Серверный режим (компании) ждёт минимум 2 символа — короче сервер и не
 * искал бы (см. shouldSearchCompanies). */
const showInlineSuggestions = computed(() => {
  if (!props.inline || suggestionsDismissed.value) {
    return false
  }
  return isServerSearchMode.value ? hasMinQueryLength.value : true
})

function closeDropdown() {
  isOpen.value = false
  query.value = ''
  cancelPendingServerSearch()
}

function toggleDropdown() {
  if (props.disabled) {
    return
  }

  isOpen.value = !isOpen.value
  if (!isOpen.value) {
    query.value = ''
  }
}

/** Общая часть "варианта выбрали / компанию создают" для inline-режима:
 * прячет перечень и останавливает всё, что могло бы его снова наполнить
 * фоновым поиском по уже неактуальному запросу. */
function settleInlineSelection() {
  suggestionsDismissed.value = true
  cancelPendingServerSearch()
}

function selectOption(option: ProjectBoardDirectoryOption) {
  pinnedOption.value = option
  emit('update:modelValue', String(option.id))
  emit('update:selected', option)
  hasUserEdited.value = true

  if (props.inline) {
    // Одно поле, один ввод (требование 3 брифа) — после выбора поле
    // показывает имя выбранного варианта, а не очищается (в отличие от
    // поп-ап режима, где это отдельная закрытая кнопка, а вложенный поиск
    // всегда открывается заново пустым).
    query.value = String(option.name)
    settleInlineSelection()
    return
  }

  closeDropdown()
}

/** Клик по действию "Создать компанию «...»" (см. showCreateAction). Отдаёт
 * query наверх ДО closeDropdown()/settleInlineSelection() — оба чистят/
 * трогают query, а событию нужно донести значение, каким оно было в момент
 * клика. */
function requestCompanyCreation() {
  emit('create-requested', query.value)
  hasUserEdited.value = true

  if (props.inline) {
    // query НЕ очищается (в отличие от поп-ап closeDropdown) — требование
    // брифа "введённое название остаётся видно" после клика "Создать
    // компанию «...»": человек напечатал "Лютик", кликнул создать — поле
    // обязано продолжать показывать "Лютик", а не опустеть.
    settleInlineSelection()
    return
  }

  closeDropdown()
}

function clearValue() {
  pinnedOption.value = null
  emit('update:modelValue', '')
  emit('update:selected', null)
  closeDropdown()
}

/**
 * Требование 5 брифа хотфикса 2026-07-29 — ГЛАВНАЯ ловушка этой задачи:
 * панель теперь телепортирована в body и физически лежит вне rootRef. Без
 * проверки panelRef.contains(target) любой клик ВНУТРИ самой панели — по
 * варианту компании, по «Создать компанию «...»», даже по полю поиска или
 * «Сбросить» — считался бы кликом мимо и закрывал список раньше, чем успевал
 * сработать @click на нужной кнопке: mousedown встаёт в очередь раньше
 * click, а closeDropdown снимает v-if="isOpen" — кнопка, по которой целились,
 * исчезает из DOM до того, как до неё вообще дойдёт событие click.
 *
 * Только поп-ап режим — регистрируется в onMounted только когда
 * !props.inline (см. докстринг блока про поп-ап-only код выше). В inline
 * режиме списка-оверлея нет и кликать "мимо" него как способ его закрыть —
 * нечего обрабатывать (требование 2 брифа инлайн-версии).
 */
function handlePointerDown(event: MouseEvent | TouchEvent) {
  if (!isOpen.value) {
    return
  }

  const target = event.target as Node | null
  if (!target) {
    return
  }

  const isInsideAnchor = rootRef.value?.contains(target) ?? false
  const isInsidePanel = panelRef.value?.contains(target) ?? false
  if (!isInsideAnchor && !isInsidePanel) {
    closeDropdown()
  }
}

/**
 * Д3 хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
 * hotfix-new-company-brief.md): раньше этот обработчик гасил список, но не
 * останавливал всплытие — то же keydown следом ловил B24Modal (Reka UI
 * DismissableLayer: onKeyStroke('Escape', ...) из @vueuse/core, см.
 * node_modules/reka-ui/dist/DismissableLayer/DismissableLayer.js). У
 * onKeyStroke нет своего target/capture в вызове — действуют дефолты самой
 * функции (node_modules/@vueuse/core/dist/index.js): target=window,
 * capture не задан, то есть слушатель на window в фазе ВСПЛЫТИЯ. Итог —
 * Escape в поле поиска закрывал сразу всё модальное окно вместо одного
 * списка (пользователь: «всё блюрится и форма пропадает»).
 *
 * Приём: этот обработчик регистрируется на document с { capture: true }
 * (см. onMounted ниже) — фаза ПОГРУЖЕНИЯ на document идёт раньше и фазы
 * погружения к самой цели события, и уж тем более раньше фазы всплытия до
 * window, где сидит Reka UI. При открытом списке — stopPropagation()
 * обрывает событию весь дальнейший путь, оно физически не доходит до
 * window — диалог остаётся открытым, закрывается только список.
 *
 * При ЗАКРЫТОМ списке — выходим ДО stopPropagation/closeDropdown: событию
 * ничто не мешает пройти весь путь и дойти до window, поэтому Escape
 * по-прежнему закрывает всё окно штатным механизмом диалога — это поведение
 * этот компонент не трогает и трогать не должен.
 *
 * Только поп-ап режим (регистрируется в onMounted только когда
 * !props.inline). Требование брифа инлайн-версии: "в режиме «в потоке»
 * списка-оверлея нет, гасить нечего. Escape должен вести себя как обычно
 * для модального окна. Не изобретай отдельную обработку" — то есть в inline
 * режиме этот обработчик НЕ регистрируется вообще, а не просто "ничего не
 * находит и молча выходит": Escape в inline-поле идёт сразу штатным путём
 * реka-ui/B24Modal, как будто этого компонента тут нет.
 */
function handleEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !isOpen.value) {
    return
  }
  event.stopPropagation()
  closeDropdown()
}

watch(() => props.options, () => {
  if (!selectedOption.value && props.modelValue) {
    emit('update:selected', null)
  }
})

/**
 * Требование 4 брифа хотфикса 2026-07-29: пока список открыт, координаты
 * пересчитываются при прокрутке и при изменении размера окна браузера.
 * capture:true на scroll — обязателен: событие scroll не всплывает, но
 * capture-слушатель на window всё равно ловит его по пути погружения к цели,
 * а цель может быть вложенным прокручиваемым контейнером (тело B24Modal),
 * а не самим window. Слушатели живут ровно между открытием и закрытием
 * списка — п.4 брифа отдельно просит не забыть снять их.
 *
 * Только поп-ап режим: `if (props.inline) return` — в inline режиме isOpen
 * никогда не становится true (toggleDropdown не вызывается, кнопки-
 * раскрывашки нет), так что этот watch и без явной проверки был бы
 * no-op для inline-экземпляров; проверка оставлена явной ради того же
 * принципа, что и в onMounted/onBeforeUnmount — код поп-ап режима не должен
 * полагаться на побочные обстоятельства, чтобы не выполняться в inline.
 */
watch(isOpen, (open) => {
  if (props.inline) {
    return
  }
  if (open) {
    window.addEventListener('scroll', updateDropdownPosition, { capture: true, passive: true })
    window.addEventListener('resize', updateDropdownPosition, { passive: true })
    return
  }

  window.removeEventListener('scroll', updateDropdownPosition, { capture: true })
  window.removeEventListener('resize', updateDropdownPosition)
  dropdownPos.value = null
})

/**
 * Пересчёт координат не только при открытии, но и при любом изменении того,
 * что рисуется внутри уже открытой панели (шапка с подсказками/перечень) —
 * иначе высота и направление оставались бы актуальны только на момент клика
 * по полю, а не на момент, когда придёт ответ сервера и список из "начните
 * вводить" превратится в 50 строк результата (ровно сценарий бага из
 * брифа хотфикса). Каждое значение ниже читается явно, чтобы Vue подписал
 * этот эффект на его изменения — это ровно то, от чего зависят v-if/v-else-if
 * в шаблоне открытой поп-ап панели, то есть её фактическая высота.
 *
 * flush:'post' — эффект перезапускается уже ПОСЛЕ того, как Vue применит
 * связанное изменение к DOM, поэтому updateDropdownPosition видит
 * актуальную разметку (offsetHeight/scrollHeight), а не предыдущий кадр.
 *
 * Только поп-ап режим — см. `if (props.inline) return`.
 */
watchEffect(() => {
  if (props.inline) {
    return
  }

  const trackedState = {
    open: isOpen.value,
    options: visibleOptions.value,
    searching: isSearching.value,
    notice: serverNotice.value,
    truncated: serverTruncated.value,
    hasQuery: hasMinQueryLength.value,
    showCreate: showCreateAction.value,
  }

  if (!trackedState.open) {
    return
  }
  updateDropdownPosition()
}, { flush: 'post' })

onMounted(() => {
  // Требование 2 брифа инлайн-версии: в inline режиме не регистрируем ни
  // "клик мимо" (нечего закрывать кликом мимо — нет оверлея), ни отдельный
  // Escape (см. докстринг handleEscape выше) — не просто выключаем их
  // условием внутри обработчика, а не вешаем на document вовсе.
  if (props.inline) {
    return
  }
  document.addEventListener('mousedown', handlePointerDown)
  document.addEventListener('touchstart', handlePointerDown, { passive: true })
  // capture: true — обязателен для Д3, см. докстринг handleEscape выше.
  document.addEventListener('keydown', handleEscape, { capture: true })
})

onBeforeUnmount(() => {
  if (!props.inline) {
    document.removeEventListener('mousedown', handlePointerDown)
    document.removeEventListener('touchstart', handlePointerDown)
    document.removeEventListener('keydown', handleEscape, { capture: true })
  }
  // На случай, если компонент размонтировался, пока список был открыт
  // (например, родитель убрал его через v-if, минуя toggleDropdown/
  // closeDropdown) — watch(isOpen) выше в этом случае не успеет снять
  // слушатели сам. removeEventListener на не навешенный слушатель — не
  // ошибка, просто ничего не делает, поэтому безусловный вызов ниже
  // безопасен и для inline-экземпляров, которые их никогда не вешали.
  window.removeEventListener('scroll', updateDropdownPosition, { capture: true })
  window.removeEventListener('resize', updateDropdownPosition)
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }
})
</script>

<template>
  <div ref="rootRef" class="relative w-full">
    <label v-if="label" class="mb-1 block text-sm font-medium text-slate-700">{{ label }}</label>

    <template v-if="inline">
      <input
        type="search"
        :value="query"
        :placeholder="searchPlaceholder"
        :disabled="disabled"
        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm outline-none transition focus:border-[#0075ff]"
        @input="onQueryInput"
      >

      <p
        v-if="isServerSearchMode && !selectedOption && hasPendingCompanyText"
        class="mt-1 text-xs text-slate-500"
      >
        {{ displayLabel }}
      </p>

      <div
        v-if="showInlineSuggestions"
        class="mt-2 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
      >
        <div
          v-if="isServerSearchMode && serverNotice"
          class="m-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700"
        >
          {{ serverNoticeText }}
        </div>

        <!--
          Найденные компании и действие «создать» — НЕ взаимоисключающие.

          До 29.07.2026 они стояли в одной цепочке v-if/v-else-if, и это было
          безобидно, пока showCreateAction означал «не нашлось ничего»: список
          в этот момент и так был пуст. После перевода правила на «нет ТОЧНОГО
          совпадения названия» условие стало истинным почти всегда — и цепочка
          начала прятать все найденные компании за кнопкой создания. Человек
          вводил «ЗИ», в портале было 50 совпадений, а на экране была одна
          кнопка «Создать компанию «ЗИ»»: выбрать существующую можно было
          только набрав её название дословно.

          Поэтому здесь два независимых блока, а не ветки одного условия:
          сверху найденное, снизу создание. Решение остаётся за человеком —
          он видит и то, и другое.
        -->
        <div class="p-2">
          <div
            v-if="!visibleOptions.length && isServerSearchMode && isSearching"
            class="px-3 py-3 text-left text-sm text-slate-400"
          >
            Идёт поиск…
          </div>

          <template v-else-if="visibleOptions.length">
            <button
              v-for="option in limitedSuggestions.visible"
              :key="option.id"
              type="button"
              :class="[
                'mb-1 w-full rounded-xl px-3 py-3 text-left transition',
                String(option.id) === normalizedModelValue
                  ? 'bg-blue-50 text-slate-900 ring-1 ring-blue-200'
                  : 'text-slate-700 hover:bg-slate-50'
              ]"
              @click="selectOption(option)"
            >
              <div class="truncate text-sm font-medium">{{ option.name }}</div>
              <div v-if="option.inn" class="mt-1 text-xs text-slate-500">ИНН {{ option.inn }}</div>
            </button>
            <p v-if="limitedSuggestions.remainderText" class="px-3 py-2 text-xs text-slate-400">
              {{ limitedSuggestions.remainderText }}
            </p>
          </template>

          <!-- «Ничего не найдено» — только когда и создавать нечего:
               иначе кнопка создания сама по себе и есть ответ. -->
          <div
            v-else-if="!showCreateAction"
            class="px-3 py-3 text-left text-sm text-slate-400"
          >
            Ничего не найдено
          </div>

          <button
            v-if="showCreateAction"
            type="button"
            :class="[
              'w-full rounded-xl px-3 py-3 text-left text-sm font-medium text-[#0075ff] transition hover:bg-blue-50',
              visibleOptions.length ? 'mt-1 border-t border-slate-100 pt-3' : ''
            ]"
            @click="requestCompanyCreation"
          >
            {{ companyCreationActionLabel(query) }}
          </button>
        </div>
      </div>
    </template>

    <template v-else>
      <button
        type="button"
        class="inline-flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-left text-sm text-slate-700 shadow-sm outline-none transition hover:border-slate-300 focus:border-[#0075ff]"
        :disabled="disabled"
        @click="toggleDropdown"
      >
        <span class="min-w-0 truncate">{{ displayLabel }}</span>
        <svg class="ml-3 h-4 w-4 shrink-0 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
        </svg>
      </button>

      <Teleport to="body">
        <FocusScope
          v-if="isOpen"
          as-child
          :trapped="false"
          @mount-auto-focus="(event: Event) => event.preventDefault()"
        >
          <div
            ref="panelRef"
            class="fixed z-[1000] flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
            :style="panelStyle"
          >
            <div ref="headerRef" class="shrink-0 border-b border-slate-100 p-3">
              <input
                :value="query"
                type="search"
                :placeholder="searchPlaceholder"
                class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-[#0075ff]"
                @input="onQueryInput"
              >
              <div class="mt-2 flex items-center justify-between text-xs">
                <button type="button" class="text-slate-500 transition hover:text-slate-700" @click="clearValue">
                  Сбросить
                </button>
                <span class="text-slate-400">
                  <template v-if="isServerSearchMode">
                    <span v-if="isSearching">Идёт поиск…</span>
                    <span v-else-if="hasMinQueryLength">{{ visibleOptions.length }} знач.</span>
                  </template>
                  <template v-else>{{ visibleOptions.length }} знач.</template>
                </span>
              </div>

              <div
                v-if="isServerSearchMode && hasMinQueryLength && serverNotice"
                class="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700"
              >
                {{ serverNoticeText }}
              </div>
              <div
                v-if="isServerSearchMode && hasMinQueryLength && serverTruncated"
                class="mt-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs text-slate-500"
              >
                Показаны первые 50, уточните запрос
              </div>
            </div>

            <div ref="listViewportRef" class="min-h-0 flex-1 overflow-y-auto p-2">
              <div
                v-if="isServerSearchMode && !hasMinQueryLength"
                class="px-3 py-3 text-left text-sm text-slate-400"
              >
                Начните вводить название или ИНН
              </div>

              <button
                v-else-if="showCreateAction"
                type="button"
                class="w-full rounded-xl px-3 py-3 text-left text-sm font-medium text-[#0075ff] transition hover:bg-blue-50"
                @click="requestCompanyCreation"
              >
                {{ companyCreationActionLabel(query) }}
              </button>

              <button
                v-else-if="!visibleOptions.length && !(isServerSearchMode && isSearching)"
                type="button"
                class="w-full rounded-xl px-3 py-3 text-left text-sm text-slate-400"
                @click="closeDropdown"
              >
                Ничего не найдено
              </button>

              <button
                v-for="option in visibleOptions"
                :key="option.id"
                type="button"
                :class="[
                  'mb-1 w-full rounded-xl px-3 py-3 text-left transition',
                  String(option.id) === normalizedModelValue
                    ? 'bg-blue-50 text-slate-900 ring-1 ring-blue-200'
                    : 'text-slate-700 hover:bg-slate-50'
                ]"
                @click="selectOption(option)"
              >
                <div class="truncate text-sm font-medium">{{ option.name }}</div>
                <div v-if="option.inn" class="mt-1 text-xs text-slate-500">ИНН {{ option.inn }}</div>
              </button>
            </div>
          </div>
        </FocusScope>
      </Teleport>
    </template>
  </div>
</template>
