<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import { useApiStore } from '~/stores/api'
import { isRateLimitError, RATE_LIMIT_NOTICE_TEXT } from '~/utils/apiErrors'
import { openCrmItemCard } from '~/utils/openCrmItem'
import { openProjectGroup } from '~/utils/openProjectGroup'
import { formatProjectCurrency } from '~/utils/projectBoard'
import { stepBadgeClass, stepErrorTextClass, stepLabel } from '~/utils/projectCreationLabels'
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
 * Модальное окно кнопки «Создать проект» (§5-6 спеки
 * docs/superpowers/specs/2026-07-28-create-project-button-design.md).
 * Компонент общий для доски проектов и главного экрана (подключение кнопок —
 * отдельная задача 9 плана, здесь только форма).
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

const curatorName = computed(() => userStore.login?.trim() || 'вы')

const missing = computed(() => result.value?.missing_fields ?? [])

// Находка 2 фикс-раунда ревью задачи 8: needsLegalEntityChoice — клиентская
// оценка (по факту загрузки своих юрлиц), а бэкенд решает необходимость
// поля независимо на каждой отправке. Если клиентский список не догрузился
// на портале, где юрлиц на самом деле несколько, needsLegalEntityChoice
// молчит, а бэкенд вернёт missing_fields с our_legal_entity_id — блок обязан
// появиться в любом из двух случаев, иначе сотрудник не увидит ни поля, ни
// объяснения (см. shouldShowLegalEntityBlock).
const showLegalEntityBlock = computed(() => shouldShowLegalEntityBlock(needsLegalEntityChoice.value, missing.value))

// Запасной путь на случай, если когда-нибудь появится ещё одно поле формы
// без своего слота на экране — тот же класс бага, что и находка 2, просто
// для другого поля (см. unslottedMissingFields). Сегодня список всегда
// пуст: у всех четырёх известных полей есть собственная подсказка.
const unslottedMissing = computed(() => unslottedMissingFields(missing.value))

const canSubmit = computed(() =>
  Boolean(form.value.project_name.trim())
  && Boolean(form.value.company_id || form.value.company_name.trim())
  && (!needsLegalEntityChoice.value || Boolean(form.value.our_legal_entity_id))
  && Boolean(form.value.hourly_rate.trim())
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
    console.error('CreateProjectModal: failed to load references', error)
  }
}

// Поле компании подключено к уже готовому серверному режиму SearchableSelect
// (frontend/app/utils/companySearch.ts) — тем же способом, что и на доске
// проектов (ProjectBoardDrawer.vue::searchCompanyOptions). Подсказка
// "начните вводить...", отметка "показаны первые 50" и уведомления о сбое/
// лимитере — целиком его забота, здесь ничего не дублируется.
//
// Единственное отличие от ProjectBoardDrawer: форма создания обязана
// использовать введённый, но ничему не сопоставленный текст как имя НОВОЙ
// компании (§5 спеки) — form.company_name синхронизируется с каждым запросом
// поиска, а update:selected перекрывает его каноничным именем найденной.
async function searchCompanyOptions(query: string) {
  form.value.company_name = query.trim()
  const found = await apiStore.searchCompanies(query)
  return { options: found.companies, truncated: found.truncated, failed: found.failed }
}

function handleCompanySelected(option: ProjectBoardDirectoryOption | null) {
  form.value.company_name = option ? String(option.name) : ''
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
    console.error('CreateProjectModal: create failed', error)
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
  if (step === 'company') form.value.company_id = id
  return submit()
}

function closeModal() {
  if (submitting.value) return
  open.value = false
}
</script>

<template>
  <B24Modal v-model:open="open" title="Создать проект" :close="!submitting">
    <template #body>
      <div class="space-y-4">
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
            empty-label="Компания не выбрана"
            search-placeholder="Поиск по названию или ИНН"
            :options="EMPTY_OPTIONS"
            :search-fn="searchCompanyOptions"
            @update:selected="handleCompanySelected"
          />
          <span class="text-xs text-slate-400">Не нашли в поиске — введённое название станет именем новой компании.</span>
          <span v-if="missing.includes('company')" class="text-xs text-rose-600">Выберите компанию или впишите название новой.</span>
        </div>

        <div v-if="showLegalEntityBlock" class="grid gap-1 text-sm">
          <span class="font-medium text-slate-700">Наше юрлицо <span class="text-rose-500">*</span></span>
          <SearchableSelect
            v-model="form.our_legal_entity_id"
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

        <div class="grid grid-cols-3 gap-4">
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
            <span class="font-medium text-slate-700">Ставка, ₽/ч <span class="text-rose-500">*</span></span>
            <input
              v-model="form.hourly_rate"
              type="number"
              min="0"
              step="100"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
            <span v-if="missing.includes('hourly_rate')" class="text-xs text-rose-600">Ставка не задана — введите значение больше нуля.</span>
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
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Тип проекта</span>
            <B24Select v-model="form.project_type" :items="PROJECT_TYPE_ITEMS" class="w-full" />
          </label>
          <label class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm">
            <span class="font-medium text-slate-700">Проект на поддержке</span>
            <B24Switch v-model="form.is_support" />
          </label>
        </div>

        <div v-if="result" class="ms-panel-muted space-y-3">
          <div class="flex flex-wrap gap-2">
            <span :class="['ms-pill', stepBadgeClass(result.company)]">Компания {{ stepLabel(result.company) }}</span>
            <span :class="['ms-pill', stepBadgeClass(result.group)]">Проект {{ stepLabel(result.group) }}</span>
            <span :class="['ms-pill', stepBadgeClass(result.card)]">Карточка {{ stepLabel(result.card) }}</span>
          </div>

          <p v-if="result.company.error" :class="stepErrorTextClass(result.company)">Компания: {{ result.company.error }}</p>
          <p v-if="result.group.error" :class="stepErrorTextClass(result.group)">Проект: {{ result.group.error }}</p>
          <p v-if="result.card.error" :class="stepErrorTextClass(result.card)">Карточка: {{ result.card.error }}</p>

          <div v-if="result.company.status === 'ambiguous'" class="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p class="text-xs text-amber-800">Нашлось несколько компаний с таким названием — выберите нужную:</p>
            <B24Select v-model="selectedCandidateId" :items="companyCandidateItems" placeholder="Выберите компанию" class="w-full" />
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
    </template>

    <template #footer>
      <B24Button :label="result?.done ? 'Закрыть' : 'Отмена'" color="link" :disabled="submitting" @click="closeModal" />
      <B24Button :label="footerLabel" color="success" :loading="submitting" :disabled="footerDisabled" @click="retry" />
    </template>
  </B24Modal>
</template>
