<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import {
  classifyCompanySearchError,
  companyCreationActionLabel,
  companySearchNoticeText,
  createCompanySearchGate,
  pendingCompanyDisplayLabel,
  shouldOfferCompanyCreation,
  shouldSearchCompanies,
  type CompanySearchNotice,
} from '~/utils/companySearch'

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
   * закрытой кнопке поля), и включатель режима "создать компанию с этим
   * названием" в открытом списке (см. showCreateAction/shouldOfferCompanyCreation
   * ниже) — оба поведения нужны только форме создания проекта
   * (CreateProjectModal.vue). Остальные потребители компонента (фильтр
   * "Компания" в ProjectBoardDrawer.vue/pages/projects/index.client.vue,
   * поле "Наше юрлицо", "Куратор") проп не передают — для них компонент
   * ведёт себя ровно как раньше: `undefined` означает "режим создания
   * выключен".
   */
  pendingCompanyName?: string | null
}>(), {
  label: '',
  emptyLabel: 'Не выбрано',
  searchPlaceholder: 'Поиск по названию или ИНН',
  disabled: false,
  pendingCompanyName: undefined,
})

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'update:selected', option: ProjectBoardDirectoryOption | null): void
  /** Д2 хотфикса 2026-07-29: клик по действию "Создать компанию «...»" (см.
   * showCreateAction ниже). Несёт query, а не полагается на то, что
   * form.company_name у родителя уже синхронизирован — searchCompanyOptions
   * пишет его только на реально стартовавший (прошедший debounce) поиск, а
   * человек мог допечатать текст уже после того, как пришёл пустой ответ. */
  (event: 'create-requested', query: string): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const query = ref('')

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

watch(query, (nextQuery) => {
  if (!isServerSearchMode.value) {
    return
  }
  scheduleServerSearch(nextQuery)
})

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
// здесь и передаётся уже готовой строкой.
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

/** Список, который реально показывается в открытом выпадающем окне. */
const visibleOptions = computed(() => (isServerSearchMode.value ? serverResults.value : filteredOptions.value))

// Д2 хотфикса 2026-07-29: режим создания включён, только когда родитель
// передал pendingCompanyName (см. её докстринг выше) — без этого пропа
// действие "создать компанию" не появится никогда, даже в серверном режиме
// поиска (фильтр "Компания" на доске проектов/странице проектов и там
// searchFn есть, а смысла создавать компанию из фильтра — нет).
const canOfferCompanyCreation = computed(() => isServerSearchMode.value && props.pendingCompanyName !== undefined)

const showCreateAction = computed(() => canOfferCompanyCreation.value && shouldOfferCompanyCreation({
  query: query.value,
  isSearching: isSearching.value,
  optionCount: visibleOptions.value.length,
}))

function closeDropdown() {
  isOpen.value = false
  query.value = ''
  if (isServerSearchMode.value) {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = undefined
    }
    resetServerSearchState()
  }
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

function selectOption(option: ProjectBoardDirectoryOption) {
  pinnedOption.value = option
  emit('update:modelValue', String(option.id))
  emit('update:selected', option)
  closeDropdown()
}

/** Клик по действию "Создать компанию «...»" (см. showCreateAction). Отдаёт
 * query наверх ДО closeDropdown() — closeDropdown очищает query, а событию
 * нужно донести значение, каким оно было в момент клика. */
function requestCompanyCreation() {
  emit('create-requested', query.value)
  closeDropdown()
}

function clearValue() {
  pinnedOption.value = null
  emit('update:modelValue', '')
  emit('update:selected', null)
  closeDropdown()
}

function handlePointerDown(event: MouseEvent | TouchEvent) {
  if (!isOpen.value) {
    return
  }

  const target = event.target as Node | null
  if (rootRef.value && target && !rootRef.value.contains(target)) {
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

onMounted(() => {
  document.addEventListener('mousedown', handlePointerDown)
  document.addEventListener('touchstart', handlePointerDown, { passive: true })
  // capture: true — обязателен для Д3, см. докстринг handleEscape выше.
  document.addEventListener('keydown', handleEscape, { capture: true })
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handlePointerDown)
  document.removeEventListener('touchstart', handlePointerDown)
  document.removeEventListener('keydown', handleEscape, { capture: true })
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }
})
</script>

<template>
  <div ref="rootRef" class="relative w-full">
    <label v-if="label" class="mb-1 block text-sm font-medium text-slate-700">{{ label }}</label>

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

    <div
      v-if="isOpen"
      class="absolute left-0 right-0 z-30 mt-2 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
    >
      <div class="border-b border-slate-100 p-3">
        <input
          v-model="query"
          type="search"
          :placeholder="searchPlaceholder"
          class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-[#0075ff]"
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

      <div class="max-h-72 overflow-y-auto p-2">
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
  </div>
</template>
