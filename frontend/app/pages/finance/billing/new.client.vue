<script setup lang="ts">
/**
 * Мастер «Выставить»: отбор часов -> предпросмотр -> документ.
 *
 * Два шага, а не одна форма с кнопкой «создать». Между отбором и счётом
 * стоит предпросмотр, потому что выставление НЕОБРАТИМО по смыслу: счёт
 * уходит в CRM портала, списания помечаются потреблёнными, и «отменить и
 * выставить заново» — это уже отдельный документ в истории клиента. Человек
 * обязан увидеть строки и суммы до того, как они станут счётом.
 *
 * Главное правило экрана: НИ ОДИН его тупик не заканчивается погасшей кнопкой
 * без объяснения. Три тупика, найденные на стенде, закрыты здесь:
 *
 *  1. Отбор без клиента собирал часы всех заказчиков сразу, предпросмотр
 *     честно рисовал строки, а «Выставить» гасло блокером mixed_companies.
 *     Теперь клиент — обязательное поле отбора: документ всё равно
 *     выставляется одному (контракт, правило 4), и выбрать его придётся.
 *     Если блокер всё же пришёл (часы клиента разложены по нескольким
 *     компаниям), он показывается списком КНОПОК, а не текстом.
 *  2. Текущий месяц с включённой по умолчанию галочкой «только закрытые
 *     месяцы» давал ноль строк молча: сервер выбрасывает записи открытого
 *     месяца раньше, чем накапливает предупреждения, поэтому period_open в
 *     ответе нет. Причину пустоты экран определяет сам, сверяя период со
 *     списком закрытых месяцев (resolveBillingEmptyReason).
 *  3. no_rate выглядело мягкой пометкой, хотя означает деньги мимо счёта.
 *     Теперь показывает часы и оценку потери и предлагает действие.
 *
 * Предупреждения показываются РАЗДЕЛЬНО: блокеры гасят кнопку, мягкие — нет.
 * Свалить их в один список значит научить людей нажимать «Выставить» не читая
 * — тот же довод, что на экране закрытия месяца.
 *
 * Пересчёт итогов после исключения строки идёт БЕЗ повторного preview
 * (recalcBillingTotals в app/utils/billingPreview.ts): второй круг к серверу
 * поменял бы цифры под руками — часы могли измениться между запросами.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import BillingGate from '~/components/finance/BillingGate.vue'
import BillingErrorNote from '~/components/finance/BillingErrorNote.vue'
import DateRangeFilter from '~/components/common/DateRangeFilter.vue'
import MultiSelectFilter from '~/components/common/MultiSelectFilter.vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import {
  BILLING_GROUPING_OPTIONS,
  buildBillingFilterBody,
  createBillingFilterForm,
  parseTaskIdsInput,
  validateBillingFilter,
} from '~/utils/billingFilter'
import {
  applyDraftRate,
  applyDraftTitle,
  buildBillingLinesPayload,
  createBillingLineDrafts,
  hasDraftEdits,
  recalcBillingTotals,
  toggleDraftExcluded,
  type BillingLineDraft,
} from '~/utils/billingPreview'
import { splitBillingWarnings } from '~/utils/billingWarnings'
import { extractMixedCompanies, type BillingCompanyChoice } from '~/utils/billingCompanies'
import { summarizeBillingNoRate } from '~/utils/billingNoRate'
import {
  resolveBillingEmptyReason,
  type BillingEmptyAction,
  type BillingPeriodState,
} from '~/utils/billingEmptyReason'
import { describeBillingError, type BillingErrorView } from '~/utils/billingErrors'
import {
  formatBillingHours,
  formatBillingHoursWithUnit,
  formatBillingMoney,
  formatRecordsRu,
} from '~/utils/billingFormat'
import type { FilterOption } from '~/types/report'
import type { BillingPreviewResponse } from '~/types/billing'

const router = useRouter()
const apiStore = useApiStore()
const { access, isManager, permissions, allowOpenPeriod, loadBillingSettings } = useBillingFeature()

useHead({ title: 'Выставить счёт' })

const { initApp, processErrorGlobal } = useAppInit('BillingWizardPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const step = ref<'filter' | 'preview'>('filter')
const form = ref(createBillingFilterForm())
const taskIdsInput = ref('')
const validationErrors = ref<string[]>([])
const error = ref<BillingErrorView | null>(null)

const isPreviewLoading = ref(false)
const isIssuing = ref(false)

const preview = ref<BillingPreviewResponse | null>(null)
const drafts = ref<BillingLineDraft[]>([])

const projectOptions = ref<FilterOption[]>([])
const employeeOptions = ref<FilterOption[]>([])
const myCompanies = ref<Array<{ id: string, name: string }>>([])
const companyOptions = ref<Array<{ id: string, name: string }>>([])
/** Состояния месяцев (/api/periods). null — список не загрузился. */
const periods = ref<BillingPeriodState[] | null>(null)

async function searchCompanyOptions(query: string) {
  const result = await apiStore.searchCompanies(query)

  return { options: result.companies, truncated: result.truncated, failed: result.failed }
}

function rememberCompany(option: { id: string | number, name: string | number } | null) {
  companyOptions.value = option
    ? [{ id: String(option.id), name: String(option.name) }]
    : []
}

/**
 * Справочники. Каждый — независимо: отсутствие списка юрлиц не должно лишать
 * человека фильтра по проектам, а отказ любого из них — всего экрана.
 *
 * Список периодов здесь же и по той же причине. Он нужен ровно для одного:
 * объяснить пустой предпросмотр незакрытым месяцем. Не ответил — экран не
 * станет выдумывать причину и скажет общее «часов нет».
 */
async function loadReferences() {
  const [projects, employees, companies, periodRows] = await Promise.allSettled([
    apiStore.getFilterProjects(),
    apiStore.getFilterEmployees(),
    apiStore.getMyCompanies(),
    apiStore.getPeriods(),
  ])

  projectOptions.value = projects.status === 'fulfilled' ? projects.value : []
  employeeOptions.value = employees.status === 'fulfilled' ? employees.value : []
  myCompanies.value = companies.status === 'fulfilled'
    ? (companies.value.companies || []).map(item => ({ id: String(item.id), name: String(item.name) }))
    : []
  periods.value = periodRows.status === 'fulfilled'
    ? (periodRows.value.periods || [])
    : null
}

const warnings = computed(() => splitBillingWarnings(preview.value?.warnings))
const totals = computed(() => recalcBillingTotals(drafts.value))
const edited = computed(() => hasDraftEdits(drafts.value))

/** Блокер «несколько клиентов» — он один такой, и показывается отдельно. */
const mixedWarning = computed(
  () => warnings.value.blockers.find(warning => warning.code === 'mixed_companies') || null
)
const otherBlockers = computed(
  () => warnings.value.blockers.filter(warning => warning.code !== 'mixed_companies')
)

const rawMixedWarning = computed(
  () => (preview.value?.warnings || []).find(item => String(item?.code || '') === 'mixed_companies') || null
)

/**
 * Клиенты блокера — кнопками.
 *
 * Названия берём из ответа сервера, а если он подставил идентификатор вместо
 * названия (в карточке проекта клиент не назван) — из того, что уже есть на
 * экране. Не нашли — показываем идентификатор как есть.
 */
const mixedCompanies = computed<BillingCompanyChoice[]>(() => extractMixedCompanies({
  warning: rawMixedWarning.value,
  companies: preview.value?.companies || null,
  directory: companyOptions.value,
}))

const hasUnnamedCompany = computed(() => mixedCompanies.value.some(item => !item.named))

/** Предупреждение no_rate показывается своей плашкой, а не в общем списке. */
const rawNoRateWarning = computed(
  () => (preview.value?.warnings || []).find(item => String(item?.code || '') === 'no_rate') || null
)
const noticeWarnings = computed(
  () => warnings.value.notices.filter(warning => warning.code !== 'no_rate')
)

const noRate = computed(() => summarizeBillingNoRate(drafts.value, rawNoRateWarning.value))

/**
 * Текст плашки no_rate.
 *
 * Часы — факт, оценка потери — оценка, и названы они по-разному намеренно:
 * настоящей ставки у этих часов нет нигде, взять её неоткуда, и выдавать
 * среднюю по отбору за точную сумму нельзя.
 */
const noRateText = computed(() => {
  const summary = noRate.value
  const parts: string[] = []

  // Все строки без цены исключены руками — потери больше нет, и пугать
  // человека суммой по строкам, которых в счёте не будет, нельзя.
  if (!summary.lines.length) {
    return 'Строки с нулевой ценой исключены из документа — эти часы в счёт не уйдут '
      + 'и останутся свободными для следующего счёта.'
  }

  const subject = summary.entriesCount
    ? `${formatRecordsRu(summary.entriesCount)} без ставки`
    : `Строк без цены: ${summary.lines.length}`

  parts.push(`${subject} — ${formatBillingHoursWithUnit(summary.zeroHours)} уйдут в счёт с нулевой ценой.`)

  if (summary.estimatedLoss > 0) {
    parts.push(
      `По средней цене отбора ${formatBillingMoney(summary.averageRate, preview.value?.currency)} за час `
      + `это примерно ${formatBillingMoney(summary.estimatedLoss, preview.value?.currency)}, `
      + 'которые в счёт не попадут.'
    )
  } else {
    parts.push('Оценить потерю не по чему: цены нет ни у одной строки отбора.')
  }

  if (summary.projectTitles.length) {
    parts.push(`Ставка берётся из карточки проекта — заполните её у: ${summary.projectTitles.join(', ')}.`)
  }

  return parts.join(' ')
})

const entriesCount = computed(() => {
  const raw = preview.value?.entries_count
  const value = typeof raw === 'number' ? raw : Number(raw)

  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0
})

/** Имя выбранного клиента — для текстов, которые иначе звучат безлико. */
const selectedCompanyName = computed(() => {
  const fromPreview = String(preview.value?.company_name || '').trim()
  if (fromPreview) {
    return fromPreview
  }

  const selected = companyOptions.value.find(item => item.id === String(form.value.companyId || '').trim())

  return selected?.name || ''
})

/** Почему предпросмотр пуст и что с этим делать. */
const emptyReason = computed(() => resolveBillingEmptyReason({
  dateFrom: form.value.dateFrom,
  dateTo: form.value.dateTo,
  onlyClosedPeriods: form.value.onlyClosedPeriods,
  allowOpenPeriod: allowOpenPeriod.value,
  warnings: preview.value?.warnings || null,
  periods: periods.value,
  companyName: selectedCompanyName.value,
  filters: {
    billableOnly: form.value.billableOnly,
    projectIds: form.value.projectIds,
    employeeIds: form.value.employeeIds,
    taskIds: parseTaskIdsInput(taskIdsInput.value),
  },
}))

/**
 * Кнопка «Выставить» гаснет на блокере, отсутствии строк и нехватке прав.
 *
 * Это УДОБСТВО, а не защита: те же проверки делает сервер (контракт,
 * правила 1, 2 и 4), и запрос можно послать мимо интерфейса.
 */
const canIssue = computed(() => permissions.value.canIssue
  && !warnings.value.blockers.length
  && totals.value.issuable
  && !isIssuing.value)

const hasCompany = computed(() => Boolean(String(form.value.companyId || '').trim()))

/**
 * Предпросмотр требует прав и выбранного клиента, но НЕ требует подписки.
 *
 * Подписку так решает сервер: на /api/billing/preview стоит проверка «админ
 * или Бухгалтерия», но нет проверки подписки — предпросмотр это чтение.
 * Клиента требует уже интерфейс: собрать предпросмотр по всем заказчикам
 * сразу можно, но выставить его нельзя, и показывать такие строки значит
 * обещать документ, которого не будет.
 */
const canPreview = computed(() => isManager.value && hasCompany.value && !isPreviewLoading.value)

/** Почему кнопка предпросмотра неактивна. Пусто — она активна. */
const previewBlockedReason = computed(() => {
  if (!isManager.value) {
    return 'Предпросмотр доступен админу портала и сотрудникам из списка «Бухгалтерия».'
  }

  if (!hasCompany.value) {
    return 'Выберите клиента — счёт выставляется одному клиенту.'
  }

  return ''
})

/** Вернуть отбор к значениям по умолчанию: прошлый месяц, галочки контракта. */
function resetForm() {
  form.value = createBillingFilterForm()
  taskIdsInput.value = ''
  companyOptions.value = []
  validationErrors.value = []
  error.value = null
}

function currentFilterBody() {
  return buildBillingFilterBody({
    ...form.value,
    taskIds: parseTaskIdsInput(taskIdsInput.value),
  })
}

async function runPreview() {
  if (!canPreview.value) {
    return
  }

  validationErrors.value = validateBillingFilter(form.value)
  error.value = null

  if (validationErrors.value.length) {
    step.value = 'filter'
    return
  }

  isPreviewLoading.value = true

  try {
    const response = await apiStore.previewBillingDocument(currentFilterBody())
    preview.value = response
    drafts.value = createBillingLineDrafts(response?.lines)
    step.value = 'preview'
  } catch (e) {
    error.value = describeBillingError(e)
  } finally {
    isPreviewLoading.value = false
  }
}

function backToFilter() {
  step.value = 'filter'
  error.value = null
}

/**
 * Клиент из блокера — в фильтр, и сразу пересобрать предпросмотр.
 *
 * Имя запоминаем в companyOptions, иначе SearchableSelect покажет пустое
 * поле при выбранном идентификаторе: список опций у него свой.
 */
async function chooseCompany(choice: BillingCompanyChoice) {
  form.value.companyId = choice.id
  companyOptions.value = [{ id: choice.id, name: choice.label }]
  await runPreview()
}

/** Действие из плашки «почему пусто». */
async function runEmptyAction(action: BillingEmptyAction) {
  if (action.id === 'drop-closed-filter') {
    form.value.onlyClosedPeriods = false
    await runPreview()
    return
  }

  if (action.to) {
    await router.push(action.to)
  }
}

/** Исключить все строки с нулевой ценой — чтобы бесплатные часы не ушли в счёт. */
function excludeNoRateLines() {
  const keys = new Set(noRate.value.lines.map(line => line.key))

  drafts.value = drafts.value.map(
    draft => (keys.has(draft.key) ? toggleDraftExcluded(draft, true) : draft)
  )
}

/**
 * Туда, где проставляют ставку.
 *
 * Доска проектов умеет открываться с поиском (?search=), и когда проект без
 * ставки ровно один, отправляем сразу к нему: искать его руками среди всех
 * проектов портала — лишний шаг.
 */
async function openProjectsBoard() {
  const titles = noRate.value.projectTitles

  if (titles.length === 1 && titles[0]) {
    await router.push({ path: '/projects', query: { search: titles[0] } })
    return
  }

  await router.push('/projects')
}

function onToggleLine(index: number, excluded: boolean) {
  const draft = drafts.value[index]
  if (!draft) {
    return
  }

  drafts.value.splice(index, 1, toggleDraftExcluded(draft, excluded))
}

function onEditTitle(index: number, title: string) {
  const draft = drafts.value[index]
  if (!draft) {
    return
  }

  drafts.value.splice(index, 1, applyDraftTitle(draft, title))
}

function onEditRate(index: number, rate: string) {
  const draft = drafts.value[index]
  if (!draft) {
    return
  }

  drafts.value.splice(index, 1, applyDraftRate(draft, rate))
}

/**
 * Выставление.
 *
 * 409 (контракт, правило 8 — идемпотентность) не ошибка приложения: сервер
 * упёрся в частичный уникальный индекс и вернул ссылку на уже существующий
 * документ. Показываем её кнопкой «Открыть документ», а не текстом «ошибка
 * сервера»: человеку нужен готовый счёт, а не повтор попытки.
 *
 * После удачи уходим в карточку с пометкой created — там она превращается в
 * плашку «счёт выставлен, дальше акт и отправка клиенту». Без пометки человек
 * попадает на обычную карточку и не понимает, случилось ли то, чего он ждал.
 */
async function issueDocument() {
  if (!canIssue.value) {
    return
  }

  isIssuing.value = true
  error.value = null

  try {
    const response = await apiStore.createBillingDocument(
      currentFilterBody(),
      buildBillingLinesPayload(drafts.value)
    )
    const id = String(response?.document?.id ?? '').trim()

    if (id) {
      await router.push({ path: `/finance/billing/${id}`, query: { created: '1' } })
      return
    }

    // Документ создан, но сервер не назвал его идентификатор — уводим в
    // реестр, а не оставляем на экране мастера с утверждёнными строками:
    // повторное нажатие создало бы вторую попытку выставить то же самое.
    await router.push('/finance/billing')
  } catch (e) {
    error.value = describeBillingError(e)
  } finally {
    isIssuing.value = false
  }
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
  } catch (e) {
    processErrorGlobal(e)
    return
  }

  await Promise.allSettled([loadBillingSettings(), loadReferences()])
})
</script>

<template>
  <BillingGate
    title="Выставить счёт"
    :description="step === 'filter'
      ? 'Шаг 1 из 2: отбор часов'
      : 'Шаг 2 из 2: проверьте строки и суммы'"
  >
    <template #actions>
      <B24Button label="Реестр документов" color="link" @click="router.push('/finance/billing')" />
    </template>

    <div v-if="!isManager && access.enabled" class="ms-note ms-note-info">
      <p class="font-semibold">Этот экран вам недоступен</p>
      <p class="mt-1">
        Собирать счёт могут админ портала и сотрудники из списка «Бухгалтерия» — список задаётся в
        настройках приложения. Предпросмотр сервер тоже закрывает: он показывает суммы к
        выставлению, а не отчёт. Реестр выставленных документов при этом открыт всем.
      </p>
    </div>

    <BillingErrorNote :error="error" />

    <!-- Шаг 1: отбор -->
    <section v-if="step === 'filter'" class="ms-surface flex flex-col gap-5 p-5">
      <div v-if="validationErrors.length" class="ms-note ms-note-danger">
        <p v-for="(message, index) in validationErrors" :key="index">{{ message }}</p>
      </div>

      <div class="grid gap-5 lg:grid-cols-2">
        <DateRangeFilter
          :date-from="form.dateFrom"
          :date-to="form.dateTo"
          @update:date-from="form.dateFrom = $event"
          @update:date-to="form.dateTo = $event"
        />

        <div>
          <label class="mb-2 block text-sm font-medium text-slate-700">
            Клиент
            <span class="text-red-600" aria-hidden="true">*</span>
          </label>
          <SearchableSelect
            :model-value="form.companyId"
            :options="companyOptions"
            empty-label="Выберите клиента"
            :search-fn="searchCompanyOptions"
            @update:model-value="form.companyId = $event"
            @update:selected="rememberCompany"
          />
          <p
            v-if="!hasCompany"
            class="mt-1 text-xs font-medium text-amber-700"
          >
            Счёт выставляется одному клиенту — выберите его, иначе предпросмотр соберёт часы разных
            заказчиков и документ из них не получится.
          </p>
          <p v-else class="mt-1 text-xs text-slate-500">
            В счёт попадут только часы по проектам этого клиента.
          </p>
        </div>

        <div>
          <label class="mb-2 block text-sm font-medium text-slate-700" for="billing-our-company">
            Наше юрлицо
          </label>
          <select id="billing-our-company" v-model="form.ourCompanyId" class="w-full">
            <option value="">Как в настройках портала</option>
            <option v-for="company in myCompanies" :key="company.id" :value="company.id">
              {{ company.name }}
            </option>
          </select>
        </div>

        <div>
          <label class="mb-2 block text-sm font-medium text-slate-700" for="billing-grouping">
            Строки документа
          </label>
          <select id="billing-grouping" v-model="form.grouping" class="w-full">
            <option v-for="option in BILLING_GROUPING_OPTIONS" :key="option.id" :value="option.id">
              {{ option.label }}
            </option>
          </select>
          <p class="mt-1 text-xs text-slate-500">
            {{ BILLING_GROUPING_OPTIONS.find(option => option.id === form.grouping)?.hint }}
          </p>
        </div>

        <div>
          <MultiSelectFilter
            label="Проекты"
            :options="projectOptions"
            :model-value="form.projectIds"
            @update:model-value="form.projectIds = ($event as string[])"
          />
        </div>

        <div>
          <MultiSelectFilter
            label="Сотрудники"
            :options="employeeOptions"
            :model-value="form.employeeIds"
            @update:model-value="form.employeeIds = ($event as string[])"
          />
        </div>

        <div class="lg:col-span-2">
          <label class="mb-2 block text-sm font-medium text-slate-700" for="billing-tasks">
            Задачи
          </label>
          <input
            id="billing-tasks"
            v-model="taskIdsInput"
            type="text"
            class="w-full"
            placeholder="Например: 9483, 9512"
          >
          <p class="mt-1 text-xs text-slate-500">
            Номера задач через запятую. Справочника задач в приложении нет — они живут в Битриксе,
            и номер проще взять из ссылки на задачу. Пусто — задачи не ограничиваем.
          </p>
        </div>
      </div>

      <div class="grid gap-3 md:grid-cols-3">
        <label class="flex items-start gap-2 text-sm text-slate-700">
          <input v-model="form.billableOnly" type="checkbox" class="mt-0.5">
          <span>
            Только оплачиваемые
            <span class="block text-xs text-slate-500">Часы, отмеченные как оплачиваемые</span>
          </span>
        </label>

        <label class="flex items-start gap-2 text-sm text-slate-700">
          <input v-model="form.onlyClosedPeriods" type="checkbox" class="mt-0.5">
          <span>
            Только закрытые месяцы
            <span class="block text-xs text-slate-500">Часы за закрытый период уже не изменятся</span>
          </span>
        </label>

        <label class="flex items-start gap-2 text-sm text-slate-700">
          <input v-model="form.excludeInvoiced" type="checkbox" class="mt-0.5">
          <span>
            Исключить уже выставленное
            <span class="block text-xs text-slate-500">Один час не уходит в счёт дважды</span>
          </span>
        </label>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <B24Button
          label="Показать предпросмотр"
          :disabled="!canPreview"
          :loading="isPreviewLoading"
          @click="runPreview"
        />
        <B24Button label="Сбросить отбор" color="link" @click="resetForm" />
        <p v-if="previewBlockedReason" class="text-sm text-amber-700">
          {{ previewBlockedReason }}
        </p>
      </div>
    </section>

    <!-- Шаг 2: предпросмотр -->
    <template v-else>
      <!-- Блокер «несколько клиентов»: список клиентов кнопками, а не текстом -->
      <div v-if="mixedWarning" class="ms-note ms-note-danger">
        <p class="font-semibold">{{ mixedWarning.title }}</p>
        <p class="mt-1">{{ mixedWarning.text }}</p>
        <div v-if="mixedCompanies.length" class="mt-3 flex flex-wrap gap-2">
          <B24Button
            v-for="company in mixedCompanies"
            :key="company.id"
            :label="company.label"
            color="default"
            size="sm"
            @click="chooseCompany(company)"
          />
        </div>
        <p v-if="mixedCompanies.length" class="mt-2 text-xs">
          Нажмите клиента — он подставится в отбор, и предпросмотр пересоберётся по нему одному.
        </p>
        <p v-if="hasUnnamedCompany" class="mt-1 text-xs">
          У части клиентов в карточках проектов не заполнено название — показан идентификатор
          компании в CRM.
        </p>
      </div>

      <div v-for="warning in otherBlockers" :key="warning.code" class="ms-note ms-note-danger">
        <p class="font-semibold">{{ warning.title }}</p>
        <p class="mt-1">{{ warning.text }}</p>
      </div>

      <!-- no_rate: не пометка, а деньги мимо счёта -->
      <div v-if="noRate.present" class="ms-note ms-note-danger">
        <p class="font-semibold">Часть часов уйдёт в счёт бесплатно</p>
        <p class="mt-1">{{ noRateText }}</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <B24Button
            v-if="noRate.lines.length"
            label="Исключить строки без цены"
            color="default"
            size="sm"
            @click="excludeNoRateLines"
          />
          <B24Button
            v-if="noRate.projectTitles.length"
            label="Проставить ставку в проекте"
            color="link"
            size="sm"
            @click="openProjectsBoard"
          />
        </div>
        <p v-if="noRate.lines.length" class="mt-2 text-xs">
          Выставить можно и так — счёт просто не досчитает эти часы.
        </p>
      </div>

      <div v-for="warning in noticeWarnings" :key="warning.code" class="ms-panel-warning">
        <p class="font-semibold">{{ warning.title }}</p>
        <p class="mt-1">{{ warning.text }}</p>
      </div>

      <section class="ms-surface flex flex-col gap-4 p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="text-sm text-slate-600">
            <span v-if="preview?.company_name" class="font-medium text-slate-900">
              {{ preview.company_name }}
            </span>
            <span v-if="entriesCount"> · в отборе {{ formatRecordsRu(entriesCount) }}</span>
            <span v-if="totals.excludedCount"> · исключено строк: {{ totals.excludedCount }}</span>
          </div>

          <div class="flex flex-wrap gap-2">
            <B24Button label="Назад к отбору" color="link" @click="backToFilter" />
            <B24Button
              label="Выставить"
              :disabled="!canIssue"
              :loading="isIssuing"
              @click="issueDocument"
            />
          </div>
        </div>

        <!-- Пусто — всегда с причиной и с действием -->
        <div v-if="!drafts.length" class="ms-note ms-note-info">
          <p class="font-semibold">{{ emptyReason.title }}</p>
          <p class="mt-1">{{ emptyReason.text }}</p>
          <div v-if="emptyReason.actions.length" class="mt-3 flex flex-wrap gap-2">
            <B24Button
              v-for="action in emptyReason.actions"
              :key="action.id"
              :label="action.label"
              color="default"
              size="sm"
              @click="runEmptyAction(action)"
            />
          </div>
        </div>

        <div v-else class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th class="w-10">В счёт</th>
                <th>Наименование работ</th>
                <th class="text-right">Часы</th>
                <th class="w-40 text-right">Цена</th>
                <th class="text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(draft, index) in drafts"
                :key="draft.key"
                :class="draft.excluded ? 'opacity-50' : ''"
              >
                <td>
                  <input
                    type="checkbox"
                    :checked="!draft.excluded"
                    :aria-label="`Включить строку «${draft.title}» в счёт`"
                    @change="onToggleLine(index, !(($event.target as HTMLInputElement).checked))"
                  >
                </td>
                <td>
                  <input
                    type="text"
                    class="w-full"
                    :value="draft.title"
                    :disabled="draft.excluded"
                    @change="onEditTitle(index, ($event.target as HTMLInputElement).value)"
                  >
                  <p v-if="draft.titleEdited" class="mt-1 text-xs text-slate-500">
                    было: {{ draft.originalTitle }}
                  </p>
                </td>
                <td class="text-right">{{ formatBillingHours(draft.hours) }}</td>
                <td class="text-right">
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    class="w-full text-right"
                    :value="draft.rate"
                    :disabled="draft.excluded"
                    @change="onEditRate(index, ($event.target as HTMLInputElement).value)"
                  >
                  <p v-if="draft.rateEdited" class="mt-1 text-xs text-slate-500">
                    было: {{ formatBillingMoney(draft.originalRate) }}
                  </p>
                  <p v-else-if="!draft.excluded && draft.rate <= 0" class="mt-1 text-xs font-medium text-red-700">
                    цены нет — строка уйдёт с нулевой суммой
                  </p>
                </td>
                <td class="text-right font-medium text-slate-900">
                  {{ formatBillingMoney(draft.amount) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="flex flex-wrap items-center justify-end gap-6 border-t border-slate-200 pt-4">
          <div class="text-sm text-slate-500">
            Строк в документе: <span class="font-semibold text-slate-900">{{ totals.linesCount }}</span>
          </div>
          <div class="text-sm text-slate-500">
            Часы: <span class="font-semibold text-slate-900">{{ formatBillingHoursWithUnit(totals.totalHours) }}</span>
          </div>
          <div class="text-base text-slate-500">
            Итого: <span class="text-lg font-semibold text-slate-900">{{ formatBillingMoney(totals.totalAmount, preview?.currency) }}</span>
          </div>
        </div>

        <p v-if="edited" class="text-xs text-slate-500">
          Строки изменены вручную: исключённые строки и новые цены уходят на сервер вместе с
          отбором. Часы при этом не меняются — они остаются такими, какими их отразили сотрудники.
        </p>
      </section>
    </template>
  </BillingGate>
</template>
