<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import { useApiStore } from '~/stores/api'
import { isRateLimitError, RATE_LIMIT_NOTICE_TEXT } from '~/utils/apiErrors'
import { companyFieldsForQuery, isCreatingNewCompany } from '~/utils/companySearch'
import { isValidInn, validateInn } from '~/utils/innValidation'
import { openCrmItemCard } from '~/utils/openCrmItem'
import { openProjectGroup } from '~/utils/openProjectGroup'
import { formatProjectCurrency } from '~/utils/projectBoard'
import { companyNameMismatchNotice, stepBadgeClass, stepErrorTextClass, stepLabel } from '~/utils/projectCreationLabels'
import {
  missingFieldLabel,
  shouldEmitProjectCreated,
  shouldRefetchLegalEntities,
  shouldResetFormOnOpen,
  shouldShowLegalEntityBlock,
  unslottedMissingFields
} from '~/utils/projectCreationModalState'
import { addOneYear, plannedAmount } from '~/types/project-creation'
import type { ProjectCreationForm, ProjectCreationResult } from '~/types/project-creation'
import type { ProjectBoardDirectoryOption } from '~/types/project-board'

/**
 * Боковая панель кнопки «Создать проект» (§5-6 спеки
 * docs/superpowers/specs/2026-07-28-create-project-button-design.md; оболочка —
 * .superpowers/sdd/2026-07-28-create-project-button/side-panel-brief.md).
 * Компонент общий для доски проектов и главного экрана (подключение кнопок —
 * отдельная задача 9 плана, здесь только форма).
 *
 * До этой правки форма жила в B24Modal и за два дня в проде ломалась четыре
 * раза — каждый раз из-за поведения библиотечного диалога, а не самой формы
 * (обрезающие контейнеры, захват фокуса, закрытие по клику мимо/Escape).
 * Разметка панели — калька с frontend/app/components/projects/ProjectBoardDrawer.vue
 * (fixed-оверлей, aside шириной max-w-[460px], шапка/прокручиваемое тело/подвал
 * с кнопками) — единственная другая боковая панель приложения, работающая без
 * нареканий с первого дня. Одно сознательное отличие от неё: оверлей здесь НЕ
 * закрывает панель по клику — заказчик прямо просил убрать это поведение,
 * форма с введёнными данными не должна пропадать от случайного клика. Escape
 * тоже не обрабатывается (тот же мотив — не изобретать закрытие, которого не
 * просили; ProjectBoardDrawer.vue его тоже не обрабатывает). Закрыть панель
 * можно только явно — крестиком в шапке или кнопкой «Отмена»/«Закрыть» в
 * подвале, обе ведут в closeModal(), которая уже блокирует закрытие во время
 * отправки (раньше это делал проп :close="!submitting" самого B24Modal).
 *
 * Второе требование заказчика — «больше статики»: ни один элемент формы не
 * должен рисовать список в отдельном всплывающем слое. Тип проекта и выбор
 * компании при неоднозначном совпадении (result.company.status === 'ambiguous')
 * раньше были B24Select (Reka UI SelectPortal — тот же класс поведения, что и
 * у диалога), теперь оба — статичные элементы в общем потоке формы. Поля
 * компании и юрлица уже используют SearchableSelect в inline-режиме
 * (inline-list-brief.md) и не тронуты — это единственный режим этого
 * компонента, лично проверенный заказчиком.
 *
 * Правило заказчика: пустых полей не остаётся. У каждого поля источник —
 * либо автоматика (видна и редактируема сотрудником ДО отправки), либо сам
 * сотрудник. Единственное осознанное исключение — бюджет часов и производная
 * от него плановая сумма.
 */

const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ created: [result: ProjectCreationResult] }>()

const apiStore = useApiStore()
const userStore = useUserStore()

/** SearchableSelect в серверном режиме сам показывает найденное; локального
 * списка компаний у формы создания нет и не должно быть (см. предупреждение
 * ниже про getProjectBoardMeta) — константа, а не ref: одна и та же пустая
 * ссылка на каждый рендер, чтобы не дёргать watch(() => props.options) в
 * SearchableSelect понапрасну. */
const EMPTY_OPTIONS: ProjectBoardDirectoryOption[] = []

const PROJECT_TYPE_ITEMS = [
  { label: 'Поставка', value: 'delivery' },
  { label: 'Поддержка', value: 'support' }
]

const legalEntities = ref<ProjectBoardDirectoryOption[]>([])
// Блокер 1 финального ревью: идентификатор смарт-процесса ПРОЕКТОВ (не
// путать с fieldConfigStore.entityTypeId — тот держит смарт-процесс
// СПИСАНИЙ ЧАСОВ, другую сущность). Источник — configuration.project_sp_entity_type_id,
// та же конфигурация, которую loadReferences() уже грузит ради hourly_rate;
// тот же приём, что и в frontend/app/pages/handler/placement-crm-deal-detail-tab.client.vue
// (projectSpaEntityTypeId). 0 — валидное «ещё не загружено/не настроено» и
// специально falsy: v-if кнопки «Открыть карточку» ниже не должен звать
// openCrmItemCard с нулевым entityTypeId (адрес вида /crm/type/0/details/...
// вёл в никуда — тот самый Блокер 1).
const projectEntityTypeId = ref(0)
const submitting = ref(false)
const result = ref<ProjectCreationResult | null>(null)
const loadError = ref('')
const selectedCandidateId = ref('')
// Ручная правка даты окончания не должна затираться пересчётом от даты начала.
const endDateTouched = ref(false)
// true, когда текущее открытие вернуло сотрудника к незавершённой попытке
// прошлого раза (фикс-раунд ревью задачи 8, находка 1), а не начало новую —
// используется только для баннера-подсказки в разметке.
const resumedNotice = ref(false)

function blankForm(): ProjectCreationForm {
  const today = new Date().toISOString().slice(0, 10)
  return {
    project_name: '',
    company_id: null,
    company_name: '',
    inn: '',
    our_legal_entity_id: null,
    project_start_date: today,
    project_end_date: addOneYear(today),
    project_hours_budget: '',
    hourly_rate: '',
    project_type: 'delivery',
    is_support: false
  }
}

const form = ref<ProjectCreationForm>(blankForm())

watch(() => form.value.project_start_date, (start) => {
  if (!endDateTouched.value) form.value.project_end_date = addOneYear(start)
})

const amount = computed(() => plannedAmount(form.value.project_hours_budget, form.value.hourly_rate))

// Юрлицо спрашиваем, только когда своих компаний в CRM больше одной;
// единственную подставляем молча и поле прячем (§5 спеки). При нуле своих
// юрлиц (портал не пометил ни одной компании) поле тоже скрыто и
// необязательно — то же правило, что и на бэкенде (resolve_project_fields:
// `elif legal_entities:` ложно для пустого списка).
const needsLegalEntityChoice = computed(() => legalEntities.value.length > 1)

// inn-frontend-brief.md, §1: поле ИНН появляется только в паре с действием
// «Создать компанию «…»» — то есть когда company_id ещё не выбран, а текст
// уже введён. isCreatingNewCompany вынесена в companySearch.ts именно
// потому, что тем же условием (не дублируя его) ниже проверяется валидность
// ИНН в canSubmit — те же ветки формы, что решают, нужен ли ИНН и на
// бэкенде (resolve_project_fields).
const creatingNewCompany = computed(() => isCreatingNewCompany(form.value.company_id, form.value.company_name))

// Живая подсказка, а не только сообщение из missing_fields после отправки:
// эта форма трижды уезжала в прод сломанной, а молча недоступная кнопка
// «Создать» без единого объяснения — тот же класс проблемы на новом поле.
// Пусто, пока поле не тронуто (не пугаем "ИНН не указан" на ещё чистом
// поле — canSubmit и так держит кнопку недоступной), текст появляется, как
// только в поле есть хоть какой-то текст, который validateInn не принимает.
const innValidationError = computed(() => {
  if (!creatingNewCompany.value) return null
  const typed = form.value.inn.trim()
  if (!typed) return null
  return validateInn(typed)
})

const curatorName = computed(() => userStore.login?.trim() || 'вы')

const missing = computed(() => result.value?.missing_fields ?? [])

// §3 брифа ИНН — ГЛАВНОЕ в задаче: непустой result.company.entered_name
// значит, что проект привяжется к УЖЕ СУЩЕСТВУЮЩЕЙ компании под другим
// названием, чем ввёл человек. Текст — чистая функция с тестами (см.
// companyNameMismatchNotice в projectCreationLabels.ts), не строка в разметке.
const companyMismatchNotice = computed(() => (result.value ? companyNameMismatchNotice(result.value.company) : null))

// Блок «Наше юрлицо» показывается всегда — спека §5 требует, чтобы
// автоподставленные значения были ВИДНЫ сотруднику и редактируемы, а не
// работали скрытым дефолтом. Раньше блок прятался, когда юрлицо на портале
// одно, и человек не видел, от кого заводится проект. Подробнее — в
// докстринге shouldShowLegalEntityBlock.
const showLegalEntityBlock = computed(() => shouldShowLegalEntityBlock())

// Запасной путь на случай, если когда-нибудь появится ещё одно поле формы
// без своего слота на экране — тот же класс бага, что и находка 2, просто
// для другого поля (см. unslottedMissingFields). Сегодня список всегда
// пуст: у всех четырёх известных полей есть собственная подсказка.
const unslottedMissing = computed(() => unslottedMissingFields(missing.value))

const canSubmit = computed(() =>
  Boolean(form.value.project_name.trim())
  && Boolean(form.value.company_id || form.value.company_name.trim())
  // inn-brief.md, раздел «Решение»: без валидного ИНН действие создания
  // новой компании недоступно. Для уже выбранной компании (creatingNewCompany
  // === false) условие не участвует — тот же приём, что и ниже для юрлица.
  && (!creatingNewCompany.value || isValidInn(form.value.inn))
  && (!needsLegalEntityChoice.value || Boolean(form.value.our_legal_entity_id))
  // Ставки на форме больше нет (решение заказчика 29.07.2026), поэтому она не
  // может блокировать отправку: сотруднику нечем было бы разблокировать
  // кнопку. Значение подставляется из настроек портала; если его там нет,
  // об этом скажет бэкенд через missing_fields, а не молчащая кнопка.
)

const footerLabel = computed(() => (result.value ? 'Повторить' : 'Создать'))
// Вслепую повторять, пока не разрешена неоднозначность компании, бессмысленно
// (ответ будет тем же ambiguous) и тратит бюджет лимитера (5 запросов/минуту,
// см. бриф) — для этого случая есть отдельный выбор из candidates ниже.
const footerDisabled = computed(() => !canSubmit.value || result.value?.company.status === 'ambiguous')

const companyCandidateItems = computed(() =>
  (result.value?.company.candidates ?? []).map(candidate => ({ label: candidate.name, value: candidate.id }))
)

// ВАЖНО: getProjectBoardMeta() здесь звать НЕЛЬЗЯ. Это весь справочник компаний
// портала — на боевом 23 252 записи и около 12,6 МБ даже после хотфикса
// 2026-07-28. Форма грузит только то, что ей нужно: свои юрлица отдельным
// маленьким эндпоинтом, компании — поиском по мере ввода.
//
// Функция вызывается повторно не только на свежее открытие, но и при
// возврате к незавершённой попытке (находка 1) и при самовосстановлении
// после расхождения по юрлицу (находка 2, shouldRefetchLegalEntities) — оба
// раза форма уже может содержать введённые сотрудником значения. Поэтому
// hourly_rate и our_legal_entity_id подставляются, только если поле ещё
// пусто: иначе повторный вызов молча затирал бы переопределённую сотрудником
// ставку значением из настроек портала.
async function loadReferences() {
  try {
    const my = await apiStore.getMyCompanies()
    legalEntities.value = my.companies
    if (my.failed) {
      // MyCompaniesResult.failed=true — Битрикс не ответил (или ответил не в
      // ожидаемой форме); companies при этом обычно пуст, но доверять его
      // полноте нельзя. Предупреждаем заранее: это тот самый разрыв, из-за
      // которого needsLegalEntityChoice может молчать, даже когда юрлиц на
      // портале на самом деле несколько (находка 2).
      loadError.value = 'Не удалось проверить список ваших юрлиц. Если их несколько, форма подскажет об этом при отправке.'
    }
    if (legalEntities.value.length === 1 && !form.value.our_legal_entity_id) {
      form.value.our_legal_entity_id = String(legalEntities.value[0]!.id)
    }
    const config = await apiStore.getConfiguration()
    const rate = Number(config?.hourly_rate ?? 0)
    if (rate > 0 && !form.value.hourly_rate) form.value.hourly_rate = String(rate)
    // Блокер 1: id смарт-процесса проектов — для ссылки «Открыть карточку»
    // на успешном экране ниже. Перезаписываем безусловно (не «если пусто»,
    // как hourly_rate/our_legal_entity_id) — это не пользовательский ввод,
    // который нельзя затирать повторным вызовом, а конфигурация портала.
    projectEntityTypeId.value = Number(config?.project_sp_entity_type_id || 0)
  } catch (error) {
    // Справочники не догрузились — форму всё равно показываем: названия
    // компании и проекта можно ввести руками, бэкенд их найдёт или создаст.
    loadError.value = 'Не удалось загрузить справочники. Заполните поля вручную.'
    console.error('CreateProjectDrawer: failed to load references', error)
  }
}

// Поле компании подключено к уже готовому серверному режиму SearchableSelect
// (frontend/app/utils/companySearch.ts), в inline-режиме брифа "список
// перестаёт всплывать" (.superpowers/sdd/2026-07-28-create-project-button/
// inline-list-brief.md) — тот же серверный поиск, что и на доске проектов
// (ProjectBoardDrawer.vue::searchCompanyOptions), но список рисуется в
// потоке формы, а не во всплывающей панели. Отметка "показаны первые 50" и
// уведомления о сбое/лимитере — целиком забота SearchableSelect, здесь
// ничего не дублируется.
//
// Единственное отличие от ProjectBoardDrawer: форма создания обязана
// использовать введённый, но ничему не сопоставленный текст как имя НОВОЙ
// компании (§5 спеки) — form.company_name синхронизируется с каждым
// нажатием клавиши (см. handleCompanyQueryChanged ниже, событие
// 'query-changed' SearchableSelect.vue), а update:selected перекрывает его
// каноничным именем найденной.
//
// Важное 3 финального ревью: company_id обнуляется той же операцией
// (companyFieldsForQuery, frontend/app/utils/companySearch.ts) — раньше
// оставался от прошлого выбора, пока company_name уже перезаписывался новым
// текстом, и на отправку могла уехать пара id одной компании и имени
// другой (выбрал «АО Ромашка», передумал, набрал «Лютик», не выбирая
// закрыл поле, нажал «Создать»). handleCompanySelected ниже восстанавливает
// согласованную пару, если пользователь всё же выберет вариант из списка.
function syncCompanyFieldsFromQuery(query: string) {
  const fields = companyFieldsForQuery(query)
  form.value.company_id = fields.company_id
  form.value.company_name = fields.company_name
}

async function searchCompanyOptions(query: string) {
  const found = await apiStore.searchCompanies(query)
  return { options: found.companies, truncated: found.truncated, failed: found.failed }
}

// Требование 3 брифа инлайн-версии — "текст человека и есть значение поля":
// SearchableSelect эмитит 'query-changed' на КАЖДОЕ нажатие клавиши, не
// дожидаясь debounce серверного поиска (см. её докстринг в
// SearchableSelect.vue). Раньше company_name синхронизировался только в
// момент реально стартовавшего (после 300ms и прошедшего createCompanySearchGate)
// поиска — searchCompanyOptions делал это сам, и если человек печатал и уходил
// с поля быстрее debounce, набранный текст никогда не долетал до формы
// ("введённое название не сохраняется", исходная жалоба, см. брифа "Зачем").
// searchCompanyOptions больше сам поля не трогает (см. выше) — эта функция
// единственная точка синхронизации, вызывается чаще и не привязана к тому,
// действительно ли поиск успел стартовать.
function handleCompanyQueryChanged(query: string) {
  syncCompanyFieldsFromQuery(query)
}

function handleCompanySelected(option: ProjectBoardDirectoryOption | null) {
  form.value.company_name = option ? String(option.name) : ''
  if (option) {
    // Выбрана СУЩЕСТВУЮЩАЯ компания — её реквизиты не наша забота (бриф
    // ИНН, раздел «Решение»), бэкенд и сам безусловно сбрасывает fields.inn
    // на этой ветке (resolve_project_fields). Чистим и на фронте — иначе,
    // если сотрудник передумает и снова начнёт печатать (вернувшись на
    // ветку «новая компания»), поле ИНН всплывёт со значением от уже
    // неактуальной, прошлой попытки.
    form.value.inn = ''
  }
}

// Д2 хотфикса 2026-07-29: SearchableSelect эмитит create-requested по явному
// клику на действие "Создать компанию «...»" (см. showCreateAction/
// shouldOfferCompanyCreation в companySearch.ts) — раньше при пустом
// результате поиска показывалась неактивная надпись "Ничего не найдено", а
// подсказка под полем обещала автоматику, которой не существовало.
//
// Пишем company_id/company_name ОДНОЙ операцией через companyFieldsForQuery —
// тот же приём и по той же причине (Важное 3 финального ревью), что и в
// handleCompanyQueryChanged выше. Берём query из события, а не полагаемся на
// уже имеющийся form.company_name: событие несёт то значение, которое
// человек видел в кнопке действия в момент клика.
function handleCompanyCreationRequested(query: string) {
  syncCompanyFieldsFromQuery(query)
}

function resetForm() {
  form.value = blankForm()
  endDateTouched.value = false
  result.value = null
  loadError.value = ''
  selectedCandidateId.value = ''
  resumedNotice.value = false
}

// Компонент, вероятнее всего, остаётся смонтированным между открытиями
// (v-model:open переключает видимость, а не пересоздаёт SFC) — полный сброс
// здесь оправдан только когда предыдущая попытка ЗАВЕРШЕНА (результата не
// было или он успешен, см. shouldResetFormOnOpen). Если предыдущая попытка
// оборвалась на частичном результате (например, компания создалась, группа —
// нет), второе открытие обязано вернуть сотрудника туда же: форма
// закрываема сразу после ответа (:close="!submitting" в разметке ниже), и
// случайное закрытие мимо/по крестику не должно требовать заново вводить
// уже введённое (фикс-раунд ревью задачи 8, находка 1).
watch(open, (isOpen) => {
  if (isOpen) {
    if (shouldResetFormOnOpen(result.value)) {
      resetForm()
    } else {
      // loadError относится к ПОСЛЕДНЕЙ попытке (транспортный сбой/лимитер),
      // а не к сохраняемому result — переносить его на новое открытие не
      // нужно, loadReferences() ниже расставит актуальный при необходимости.
      loadError.value = ''
      resumedNotice.value = true
    }
    loadReferences()
  }
}, { immediate: true })

async function submit() {
  if (submitting.value) return
  submitting.value = true
  loadError.value = ''
  resumedNotice.value = false
  try {
    result.value = await apiStore.createProject(form.value)
    selectedCandidateId.value = ''
    // Важное 2 финального ревью: раньше условием было result.value.done —
    // видело только исход шага карточки и пропускало случай «группа
    // создана, карточка упала ошибкой» (строка уже в базе, а доска не
    // перечитывается). shouldEmitProjectCreated смотрит на group.id вместо
    // done — см. её докстринг в projectCreationModalState.ts.
    if (shouldEmitProjectCreated(result.value)) {
      emit('created', result.value)
    } else if (shouldRefetchLegalEntities(result.value.missing_fields, legalEntities.value.length)) {
      // Находка 2: бэкенд посчитал юрлицо обязательным, хотя клиент так не
      // решил — список на клиенте, скорее всего, не догрузился или устарел.
      // Пробуем перезагрузить его молча: если получится, needsLegalEntityChoice
      // сам станет true и поле окажется заполнимым без того, чтобы сотрудник
      // закрывал и открывал окно заново.
      await loadReferences()
    }
  } catch (error) {
    // Эндпоинт создания лимитирован (5 запросов/минуту, см. бриф задачи 8).
    // 429 — ожидаемая, самовосстанавливающаяся ситуация "подождите минуту",
    // а не сбой; тот же приём, что в pages/projects/index.client.vue
    // (syncBoard/refreshReferenceOptions): дружелюбный текст вместо сырого
    // сообщения fetch-ошибки. form.value не трогаем — введённое не теряется.
    loadError.value = isRateLimitError(error)
      ? RATE_LIMIT_NOTICE_TEXT
      : (error instanceof Error ? error.message : 'Не удалось создать проект.')
    console.error('CreateProjectDrawer: create failed', error)
  } finally {
    submitting.value = false
  }
}

/** Повтор отправляет ту же форму: шаги идемпотентны на бэкенде, досоздаётся
 * только недостающее — см. project_creation_service.py. */
function retry() {
  return submit()
}

function chooseCandidate(step: 'company', id: string) {
  if (step === 'company') {
    form.value.company_id = id
    // Та же причина, что и в handleCompanySelected выше: выбор компании из
    // списка кандидатов (ambiguous) — это выбор УЖЕ СУЩЕСТВУЮЩЕЙ компании,
    // ИНН для неё не наша забота и не должен остаться от предыдущей попытки.
    form.value.inn = ''
  }
  return submit()
}

function closeModal() {
  if (submitting.value) return
  open.value = false
}
</script>

<template>
  <!-- Оверлей намеренно без @click-закрытия — см. докстринг компонента выше:
       заказчик прямо просил убрать закрытие по клику мимо. -->
  <div v-if="open" class="fixed inset-0 z-[9999] flex justify-end bg-slate-900/40 backdrop-blur-sm">
    <aside class="flex h-full w-full max-w-[460px] flex-col border-l border-slate-200 bg-white shadow-2xl">
      <div class="border-b border-slate-200 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="truncate text-lg font-semibold text-slate-900">Создать проект</div>
          </div>
          <button
            type="button"
            class="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="submitting"
            @click="closeModal"
          >
            ✕
          </button>
        </div>
      </div>

      <div class="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        <div v-if="resumedNotice" class="ms-note ms-note-info">
          Это незавершённая попытка с прошлого раза, не новая форма — данные и статус шагов ниже сохранены.
        </div>
        <div v-if="loadError" class="ms-panel-warning">{{ loadError }}</div>
        <div v-if="unslottedMissing.length" class="ms-panel-warning">
          Не хватает данных для отправки: {{ unslottedMissing.map(missingFieldLabel).join(', ') }}.
        </div>

        <label class="grid gap-1 text-sm">
          <span class="font-medium text-slate-700">Название проекта <span class="text-rose-500">*</span></span>
          <input
            v-model="form.project_name"
            type="text"
            placeholder="Например, Портал АО Ромашка"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
          <span v-if="missing.includes('project_name')" class="text-xs text-rose-600">Заполните название проекта.</span>
        </label>

        <div class="grid gap-1 text-sm">
          <span class="font-medium text-slate-700">Компания <span class="text-rose-500">*</span></span>
          <SearchableSelect
            v-model="form.company_id"
            inline
            empty-label="Компания не выбрана"
            search-placeholder="Поиск по названию или ИНН"
            :options="EMPTY_OPTIONS"
            :search-fn="searchCompanyOptions"
            :pending-company-name="form.company_name"
            @update:selected="handleCompanySelected"
            @create-requested="handleCompanyCreationRequested"
            @query-changed="handleCompanyQueryChanged"
          />
          <span class="text-xs text-slate-400">Не нашли компанию в поиске — нажмите «Создать компанию» в списке, чтобы завести новую с введённым названием.</span>
          <span v-if="missing.includes('company')" class="text-xs text-rose-600">Выберите компанию или впишите название новой.</span>
        </div>

        <div v-if="creatingNewCompany" class="grid gap-1 text-sm">
          <span class="font-medium text-slate-700">ИНН новой компании <span class="text-rose-500">*</span></span>
          <input
            v-model="form.inn"
            type="text"
            inputmode="numeric"
            autocomplete="off"
            placeholder="10 цифр (юрлицо) или 12 (ИП)"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
          <span v-if="innValidationError" class="text-xs text-rose-600">{{ innValidationError }}</span>
          <span v-else-if="missing.includes('inn')" class="text-xs text-rose-600">Введите корректный ИНН — без него новую компанию создать нельзя.</span>
          <span v-else class="text-xs text-slate-400">Нужен, чтобы не завести в CRM дубль уже существующей компании.</span>
        </div>

        <div v-if="showLegalEntityBlock" class="grid gap-1 text-sm">
          <span class="font-medium text-slate-700">Наше юрлицо <span class="text-rose-500">*</span></span>
          <SearchableSelect
            v-model="form.our_legal_entity_id"
            inline
            empty-label="Не выбрано"
            search-placeholder="Поиск юрлица"
            :options="legalEntities"
          />
          <span v-if="missing.includes('our_legal_entity_id')" class="text-xs text-rose-600">На портале несколько ваших юрлиц — выберите одно.</span>
        </div>

        <div class="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          Куратор — {{ curatorName }} (текущий сотрудник; можно изменить позже в карточке проекта).
        </div>

        <div class="grid grid-cols-2 gap-4">
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Дата начала</span>
            <input
              v-model="form.project_start_date"
              type="date"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
          </label>
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Дата окончания</span>
            <input
              v-model="form.project_end_date"
              type="date"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              @change="endDateTouched = true"
            >
          </label>
        </div>

        <!--
          Поле «Ставка, ₽/ч» убрано с формы по решению заказчика 29.07.2026.
          Ставка по-прежнему уходит в карточку: loadReferences() подставляет её
          из настроек портала в form.hourly_rate, поле просто не показывается.
          Если в настройках портала ставки нет, бэкенд вернёт её в
          missing_fields, и сотрудник увидит это общим сообщением о нехватке
          данных (см. unslottedMissingFields) — точечной подсказки у поля
          больше нет, потому что нет и самого поля.
        -->
        <div class="grid grid-cols-2 gap-4">
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Бюджет, часы</span>
            <input
              v-model="form.project_hours_budget"
              type="number"
              min="0"
              step="0.5"
              placeholder="не задан"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
          </label>
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Плановая сумма</span>
            <input
              :value="formatProjectCurrency(amount)"
              type="text"
              disabled
              class="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500"
            >
          </label>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Тип проекта</span>
            <!-- Было B24Select (Reka UI SelectPortal, всплывающий слой) —
                 вариантов всего два, статичный переключатель в потоке формы
                 вместо списка (side-panel-brief.md, §2). -->
            <div class="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Тип проекта">
              <button
                v-for="item in PROJECT_TYPE_ITEMS"
                :key="item.value"
                type="button"
                role="radio"
                :aria-checked="form.project_type === item.value"
                :class="[
                  'rounded-lg border px-3 py-2 text-sm font-medium transition',
                  form.project_type === item.value
                    ? 'border-[#0075ff] bg-blue-50 text-[#0075ff]'
                    : 'border-slate-300 text-slate-600 hover:border-slate-400'
                ]"
                @click="form.project_type = item.value"
              >
                {{ item.label }}
              </button>
            </div>
          </div>
          <label class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm">
            <span class="font-medium text-slate-700">Проект на поддержке</span>
            <B24Switch v-model="form.is_support" />
          </label>
        </div>

        <div v-if="result" class="ms-panel-muted space-y-3">
          <div class="flex flex-wrap gap-2">
            <span :class="['ms-pill', stepBadgeClass(result.company)]">Компания {{ stepLabel(result.company) }}</span>
            <span :class="['ms-pill', stepBadgeClass(result.requisite)]">Реквизит {{ stepLabel(result.requisite) }}</span>
            <span :class="['ms-pill', stepBadgeClass(result.group)]">Проект {{ stepLabel(result.group) }}</span>
            <span :class="['ms-pill', stepBadgeClass(result.card)]">Карточка {{ stepLabel(result.card) }}</span>
          </div>

          <p v-if="companyMismatchNotice" class="ms-panel-warning">{{ companyMismatchNotice }}</p>

          <p v-if="result.company.error" :class="stepErrorTextClass(result.company)">Компания: {{ result.company.error }}</p>
          <p v-if="result.requisite.error" :class="stepErrorTextClass(result.requisite)">Реквизит: {{ result.requisite.error }}</p>
          <p v-if="result.group.error" :class="stepErrorTextClass(result.group)">Проект: {{ result.group.error }}</p>
          <p v-if="result.card.error" :class="stepErrorTextClass(result.card)">Карточка: {{ result.card.error }}</p>

          <div v-if="result.company.status === 'ambiguous'" class="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p class="text-xs text-amber-800">Нашлось несколько компаний с таким названием — выберите нужную:</p>
            <!-- Было B24Select — та же причина, что и у "Тип проекта" выше:
                 конечный список кандидатов, всплывающая панель ему не нужна. -->
            <div class="grid gap-1" role="radiogroup" aria-label="Выберите компанию">
              <button
                v-for="candidate in companyCandidateItems"
                :key="candidate.value"
                type="button"
                role="radio"
                :aria-checked="selectedCandidateId === candidate.value"
                :class="[
                  'w-full rounded-lg border px-3 py-2 text-left text-sm transition',
                  selectedCandidateId === candidate.value
                    ? 'border-[#0075ff] bg-blue-50 text-slate-900'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                ]"
                @click="selectedCandidateId = candidate.value"
              >
                {{ candidate.label }}
              </button>
            </div>
            <B24Button
              label="Повторить с выбранной компанией"
              color="primary"
              :loading="submitting"
              :disabled="!selectedCandidateId"
              @click="chooseCandidate('company', selectedCandidateId)"
            />
          </div>
          <p v-else-if="result.group.status === 'ambiguous'" class="text-xs text-amber-800">
            Нашлось несколько проектов в Задачах с именем «{{ form.project_name }}»:
            {{ result.group.candidates.map(candidate => candidate.name).join(', ') }}.
            Измените название проекта выше и нажмите «Повторить».
          </p>

          <div v-if="result.done" class="ms-note ms-note-success space-y-2">
            <p>Готово.</p>
            <div class="flex flex-wrap gap-2">
              <B24Button v-if="result.group.id" label="Открыть проект" color="link" @click="openProjectGroup(result.group.id)" />
              <B24Button
                v-if="result.card.id && projectEntityTypeId"
                label="Открыть карточку"
                color="link"
                @click="openCrmItemCard(projectEntityTypeId, result.card.id)"
              />
            </div>
          </div>
        </div>
      </div>

      <div class="border-t border-slate-200 px-5 py-4">
        <div class="flex flex-wrap gap-2">
          <B24Button :label="result?.done ? 'Закрыть' : 'Отмена'" color="link" :disabled="submitting" @click="closeModal" />
          <B24Button :label="footerLabel" color="success" :loading="submitting" :disabled="footerDisabled" @click="retry" />
        </div>
      </div>
    </aside>
  </div>
</template>
