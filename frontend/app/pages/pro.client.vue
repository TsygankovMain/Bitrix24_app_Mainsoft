<script setup lang="ts">
/**
 * «Купить Pro»: форма запроса счёта и экран «Счёт сформирован».
 *
 * Макет — 2026-09-12-pro-purchase-mockup.html, экраны 2 и 3. Все кнопки
 * «Купить Pro» (меню, подвал «Финансов», замок функции, карточка «Подписка»)
 * ведут сюда: PRO_ROUTE в app/utils/proPlan.ts.
 *
 * Что решает сервер, а что экран:
 *  - суммы по срокам, НДС, код портала, номер счёта и назначение платежа —
 *    сервер (GET /api/pro/offer, POST /api/pro/requests). Экран только
 *    показывает готовое;
 *  - портал заявки — тоже сервер, из авторизации. В форме портал и код
 *    только для чтения, в запрос они не уходят;
 *  - может ли человек запросить счёт — сервер (can_request, роль
 *    «Администратор» или «Бухгалтерия»). Сотрудник видит, кто подключает Pro.
 *
 * Проверки полей и тексты — app/utils/proPurchase.ts, под тестами.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { isPaidFeatureId, PAID_FEATURES } from '~/utils/paidFeatures'
import { formatPlanDate } from '~/utils/proPlan'
import {
  buildProRequestBody,
  cardPaymentMailto,
  checkProField,
  createProForm,
  describeProApiError,
  describeProRequest,
  errorSummaryTitle,
  formatRub,
  isOpenProRequest,
  monthsText,
  normalizeInnInput,
  normalizeKppInput,
  parseProOffer,
  parseProRequest,
  parseProRequisite,
  PAYMENT_PURPOSE_LIMIT,
  payerTypeForInn,
  perMonthHint,
  PRO_FIELD_LABELS,
  PRO_SUBMIT_LABEL,
  proFormFromRequest,
  proRequestTimeline,
  shortPayerName,
  termCardHint,
  termSummaryRows,
  validateProForm,
  type ProFormErrors,
  type ProFormField,
  type ProOffer,
  type ProRequestView,
  type ProRequisite,
} from '~/utils/proPurchase'

useHead({ title: 'Купить Pro' })

const route = useRoute()
const router = useRouter()
const apiStore = useApiStore()
const { setRequest } = useProPurchase()

const { initApp, processErrorGlobal } = useAppInit('ProPurchasePage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const isLoading = ref(true)
const loadError = ref('')
const offer = ref<ProOffer | null>(null)
const request = ref<ProRequestView | null>(null)
/** Экран: форма или готовый счёт. */
const view = ref<'form' | 'invoice'>('form')

const form = reactive(createProForm())
const touched = reactive<Partial<Record<ProFormField, boolean>>>({})
const serverErrors = ref<ProFormErrors>({})
const submitAttempted = ref(false)
const submitting = ref(false)
const submitError = ref('')
const errorSummaryRef = ref<HTMLElement | null>(null)

const suggestions = ref<ProRequisite[]>([])
const lookup = reactive<{ inn: string, state: 'idle' | 'loading' | 'found' | 'missing' | 'failed', text: string }>({
  inn: '', state: 'idle', text: '',
})
let lookupTimer: ReturnType<typeof setTimeout> | null = null

const notice = ref('')
let noticeTimer: ReturnType<typeof setTimeout> | null = null

const cancelOpen = ref(false)
const cancelling = ref(false)
const cancelError = ref('')
const downloading = ref(false)

const featureId = computed(() => {
  const raw = Array.isArray(route.query.feature) ? route.query.feature[0] : route.query.feature

  return isPaidFeatureId(raw) ? raw : null
})

const includedFeatures = [PAID_FEATURES.bdds, PAID_FEATURES.billing, PAID_FEATURES.roles]

const terms = computed(() => offer.value?.terms || [])
const termMonths = computed(() => terms.value.map(term => term.months))
const selectedTerm = computed(() => terms.value.find(term => term.months === form.months) || terms.value[terms.value.length - 1] || null)
const isIp = computed(() => payerTypeForInn(form.payerInn) === 'ip')
const domain = computed(() => offer.value?.portal.domain || '')
const portalCode = computed(() => offer.value?.portal.code || '')
const openRequest = computed(() => isOpenProRequest(request.value) ? request.value : null)

const mailto = computed(() => cardPaymentMailto({
  email: offer.value?.contactEmail || '',
  domain: domain.value,
  code: portalCode.value,
  term: selectedTerm.value,
}))

// ---------------------------------------------------------------------------
// Загрузка
// ---------------------------------------------------------------------------

async function loadOffer() {
  isLoading.value = true
  loadError.value = ''
  try {
    const parsed = parseProOffer(await apiStore.getProOffer())
    offer.value = parsed
    request.value = parsed.currentRequest
    setRequest(parsed.currentRequest)
    Object.assign(form, createProForm(parsed))
    view.value = openRequest.value && parsed.canRequest ? 'invoice' : 'form'
    if (parsed.canRequest) {
      void loadSuggestions()
    }
  } catch (error) {
    loadError.value = describeProApiError(error).message
  } finally {
    isLoading.value = false
  }
}

async function loadSuggestions() {
  try {
    const payload = await apiStore.getProRequisites() as { suggestions?: unknown[] }
    suggestions.value = (payload?.suggestions || [])
      .map(parseProRequisite)
      .filter((item): item is ProRequisite => item !== null)
  } catch {
    suggestions.value = []
  }
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
  } catch (error) {
    processErrorGlobal(error)
    return
  }
  await loadOffer()
})

onBeforeUnmount(() => {
  if (lookupTimer) {
    clearTimeout(lookupTimer)
  }
  if (noticeTimer) {
    clearTimeout(noticeTimer)
  }
})

// ---------------------------------------------------------------------------
// Поля
// ---------------------------------------------------------------------------

const DEFAULT_HINTS: Partial<Record<ProFormField, string>> = {
  payerInn: 'Остальные реквизиты подставим из CRM портала — проверьте их',
  payerKpp: 'Обязателен для организации',
  contactEmail: 'Из профиля Битрикс24. Можно указать почту бухгалтерии',
  contactCc: 'Необязательно',
  contactPhone: 'Необязательно. Позвоним, только если с оплатой что-то не сойдётся',
  contactName: 'Из профиля. Можно указать бухгалтера',
}

type FieldMessage = { kind: 'error' | 'warning' | 'info' | 'ok', text: string }

function fieldMessage(field: ProFormField): FieldMessage | null {
  const shown = submitAttempted.value || touched[field]
  const server = serverErrors.value[field]
  if (server) {
    return { kind: 'error', text: server }
  }
  const check = checkProField(field, form, termMonths.value)
  if (shown && check.error) {
    return { kind: 'error', text: check.error }
  }
  if (field === 'payerInn' && lookup.state !== 'idle' && lookup.inn === normalizeInnInput(form.payerInn)) {
    if (check.warning && lookup.state !== 'loading') {
      return { kind: 'warning', text: check.warning }
    }

    return { kind: lookup.state === 'found' ? 'ok' : lookup.state === 'loading' ? 'info' : 'warning', text: lookup.text }
  }
  if (shown && check.warning) {
    return { kind: 'warning', text: check.warning }
  }
  const hint = DEFAULT_HINTS[field]

  return hint ? { kind: 'info', text: hint } : null
}

function isInvalid(field: ProFormField): boolean {
  return fieldMessage(field)?.kind === 'error'
}

const MESSAGE_CLASSES: Record<FieldMessage['kind'], string> = {
  error: 'text-rose-700',
  warning: 'text-amber-800',
  info: 'text-slate-500',
  ok: 'text-emerald-700',
}

function inputClasses(field: ProFormField) {
  return [
    'w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-800 transition focus:outline-none focus:ring-2',
    isInvalid(field)
      ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-500/20'
      : 'border-slate-300 focus:border-[#0075ff] focus:ring-[#0075ff]/20',
  ]
}

function touch(field: ProFormField) {
  touched[field] = true
}

function clearServerError(field: ProFormField) {
  if (serverErrors.value[field]) {
    serverErrors.value = Object.fromEntries(
      Object.entries(serverErrors.value).filter(([key]) => key !== field)
    ) as ProFormErrors
  }
}

function onInput(field: ProFormField) {
  clearServerError(field)
  if (field === 'payerKpp') {
    form.payerKpp = normalizeKppInput(form.payerKpp)
  }
}

function onInnInput() {
  clearServerError('payerInn')
  const cleaned = normalizeInnInput(form.payerInn)
  if (cleaned !== form.payerInn) {
    form.payerInn = cleaned
  }
  form.payerCompanyId = ''
  if (lookupTimer) {
    clearTimeout(lookupTimer)
  }
  if (!/^\d+$/.test(cleaned) || (cleaned.length !== 10 && cleaned.length !== 12)) {
    lookup.state = 'idle'
    lookup.inn = ''
    return
  }
  touched.payerInn = true
  if (cleaned === lookup.inn && lookup.state !== 'failed') {
    return
  }
  lookup.inn = cleaned
  lookup.state = 'loading'
  lookup.text = 'Ищем реквизиты в CRM портала…'
  lookupTimer = setTimeout(() => void lookupInn(cleaned), 450)
}

async function lookupInn(inn: string) {
  try {
    const payload = await apiStore.getProRequisites(inn) as { found?: boolean, failed?: boolean, requisite?: unknown }
    if (normalizeInnInput(form.payerInn) !== inn) {
      return
    }
    const found = payload?.found ? parseProRequisite(payload.requisite) : null
    if (found) {
      applyRequisite(found, false)
      lookup.state = 'found'
      lookup.text = `${shortPayerName(found.name) || found.companyTitle} — из CRM вашего портала. Проверьте наименование, КПП и адрес`
    } else if (payload?.failed) {
      lookup.state = 'failed'
      lookup.text = 'CRM портала не ответила — заполните реквизиты вручную'
    } else {
      lookup.state = 'missing'
      lookup.text = 'Не нашли этот ИНН в CRM портала — заполните реквизиты вручную'
    }
  } catch {
    if (normalizeInnInput(form.payerInn) === inn) {
      lookup.state = 'failed'
      lookup.text = 'Реквизиты не подставились — заполните их вручную'
    }
  }
}

function applyRequisite(requisite: ProRequisite, setInn = true) {
  if (setInn) {
    form.payerInn = requisite.inn
    lookup.inn = requisite.inn
    lookup.state = 'found'
    lookup.text = `${shortPayerName(requisite.name) || requisite.companyTitle} — из CRM вашего портала. Проверьте наименование, КПП и адрес`
  }
  if (requisite.name) {
    form.payerName = requisite.name
  }
  if (requisite.address) {
    form.payerAddress = requisite.address
  }
  form.payerKpp = requisite.kpp
  form.payerCompanyId = requisite.companyId
  touched.payerInn = true
  for (const field of ['payerInn', 'payerKpp', 'payerName', 'payerAddress'] as ProFormField[]) {
    clearServerError(field)
  }
}

// ---------------------------------------------------------------------------
// Отправка
// ---------------------------------------------------------------------------

const clientErrors = computed(() => validateProForm(form, termMonths.value))

const summaryErrors = computed(() => {
  const list = clientErrors.value.map(item => ({ ...item }))
  for (const [field, error] of Object.entries(serverErrors.value)) {
    if (error && !list.some(item => item.field === field)) {
      list.push({ field: field as ProFormField, error })
    }
  }

  return list
})

function focusField(field: ProFormField) {
  const element = document.getElementById(`pro-${field}`)
  element?.focus()
  element?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

async function submit() {
  submitAttempted.value = true
  submitError.value = ''
  if (clientErrors.value.length) {
    await nextTick()
    errorSummaryRef.value?.focus()
    return
  }

  submitting.value = true
  try {
    const payload = await apiStore.createProRequest(buildProRequestBody(form)) as {
      request?: unknown
      replaced_invoice_number?: string | null
      updated_in_place?: boolean
    }
    const created = parseProRequest(payload?.request)
    if (!created) {
      throw new Error('empty response')
    }
    request.value = created
    setRequest(created)
    serverErrors.value = {}
    submitAttempted.value = false
    view.value = 'invoice'
    if (payload.replaced_invoice_number) {
      showNotice(`Счёт ${payload.replaced_invoice_number} отозван, вместо него — ${created.invoiceNumber}`)
    } else if (payload.updated_in_place) {
      showNotice(`Реквизиты в счёте ${created.invoiceNumber} обновлены, номер прежний`)
    }
    window.scrollTo?.({ top: 0, behavior: 'smooth' })
  } catch (error) {
    const described = describeProApiError(error)
    serverErrors.value = described.fieldErrors
    submitError.value = described.message
    if (Object.keys(described.fieldErrors).length) {
      await nextTick()
      errorSummaryRef.value?.focus()
    }
  } finally {
    submitting.value = false
  }
}

function editRequest() {
  if (request.value) {
    Object.assign(form, proFormFromRequest(request.value, createProForm(offer.value)))
    lookup.state = 'idle'
    lookup.inn = normalizeInnInput(form.payerInn)
  }
  form.offerAccepted = false
  submitAttempted.value = false
  view.value = 'form'
}

function newRequestForm() {
  Object.assign(form, createProForm(offer.value))
  view.value = 'form'
}

// ---------------------------------------------------------------------------
// Счёт: копирование, PDF, отмена
// ---------------------------------------------------------------------------

function showNotice(text: string) {
  notice.value = text
  if (noticeTimer) {
    clearTimeout(noticeTimer)
  }
  noticeTimer = setTimeout(() => {
    notice.value = ''
  }, 4000)
}

async function copyPurpose() {
  const text = request.value?.paymentPurpose || ''
  try {
    await navigator.clipboard.writeText(text)
    showNotice('Назначение платежа скопировано')
  } catch {
    showNotice('Скопируйте текст из блока «Назначение платежа»')
  }
}

async function downloadPdf() {
  if (!request.value) {
    return
  }
  downloading.value = true
  try {
    const blob = await apiStore.downloadProInvoice(request.value.id)
    const url = window.URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = `Счёт-${request.value.invoiceNumber}.pdf`
    window.document.body.appendChild(link)
    link.click()
    window.document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    showNotice(describeProApiError(error).message)
  } finally {
    downloading.value = false
  }
}

async function confirmCancel() {
  if (!request.value) {
    return
  }
  cancelling.value = true
  cancelError.value = ''
  try {
    const payload = await apiStore.cancelProRequest(request.value.id, 'Отменена в приложении') as { request?: unknown }
    const cancelled = parseProRequest(payload?.request)
    request.value = cancelled
    setRequest(cancelled)
    cancelOpen.value = false
    showNotice('Заявка отменена, счёт отозван')
    newRequestForm()
  } catch (error) {
    cancelError.value = describeProApiError(error).message
  } finally {
    cancelling.value = false
  }
}

const requestNote = computed(() => request.value ? describeProRequest(request.value, offer.value?.contactEmail) : null)
const timeline = computed(() => request.value ? proRequestTimeline(request.value) : [])

const NOTE_CLASSES: Record<string, string> = {
  success: 'ms-note-success',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  info: 'ms-note-info',
  danger: 'ms-note-danger',
  muted: 'border-slate-200 bg-slate-50 text-slate-700',
}

const inputBase = 'block text-sm font-medium text-slate-800'

function goBack() {
  const id = featureId.value
  if (id === 'roles') {
    void router.push('/settings/roles')
  } else if (id) {
    void router.push(`/finance/${id}`)
  } else {
    router.back()
  }
}
</script>

<template>
  <B24Container>
    <B24PageHeader title="Купить Pro" :description="offer ? `${formatRub(offer.priceMonthRub)} в месяц за портал` : 'Подписка на Pro'">
      <template #links>
        <B24Button label="Назад" color="link" @click="goBack" />
      </template>
    </B24PageHeader>

    <div
      v-if="notice"
      class="fixed bottom-6 left-1/2 z-[9990] -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg"
      role="status"
      aria-live="polite"
    >
      {{ notice }}
    </div>

    <div class="mt-6 pb-10">
      <div v-if="isLoading" class="ms-note ms-note-info" role="status">Загружаем условия подписки…</div>

      <div v-else-if="loadError" class="ms-note ms-note-danger flex flex-wrap items-center justify-between gap-3" role="alert">
        <span>{{ loadError }}</span>
        <B24Button label="Повторить" color="default" size="sm" @click="loadOffer" />
      </div>

      <template v-else-if="offer">
        <!-- ============ Сотрудник без права ============ -->
        <div v-if="!offer.canRequest" class="flex flex-col gap-4">
          <B24Card>
            <template #header>
              <span class="text-base font-semibold text-slate-900">Pro подключает администратор</span>
            </template>
            <p class="text-sm text-slate-700">
              Счёт выставляется на организацию, поэтому запросить его может администратор портала или сотрудник
              с ролью «Бухгалтерия».
              <template v-if="offer.managers.length">
                Сейчас это {{ offer.managers.join(', ') }}.
              </template>
            </p>
            <div v-if="request" class="mt-3 text-sm text-slate-600">
              <template v-if="openRequest">
                Счёт {{ request.invoiceNumber }} на {{ formatRub(request.total) }} уже запрошен
                <template v-if="request.requestedByName">({{ request.requestedByName }})</template>
                и ждёт оплаты до {{ formatPlanDate(request.dueDate) }}.
              </template>
              <template v-else-if="request.status === 'paid' && request.proPaidUntil">
                Pro оплачен до {{ formatPlanDate(request.proPaidUntil) }}.
              </template>
            </div>
          </B24Card>
          <B24Card>
            <template #header>
              <span class="text-base font-semibold text-slate-900">Что входит в Pro</span>
            </template>
            <ul class="flex flex-col gap-3">
              <li
                v-for="feature in includedFeatures"
                :key="feature.id"
                class="flex flex-col gap-0.5"
                :class="feature.id === featureId ? 'rounded-lg bg-blue-50/60 px-3 py-2' : ''"
              >
                <span class="text-sm font-semibold text-slate-900">{{ feature.label }}</span>
                <span class="text-sm text-slate-600">{{ feature.benefit }}</span>
              </li>
            </ul>
          </B24Card>
        </div>

        <!-- ============ Счёт сформирован ============ -->
        <div v-else-if="view === 'invoice' && request" class="grid gap-4 min-[1100px]:grid-cols-[minmax(0,1fr)_340px]">
          <div class="flex min-w-0 flex-col gap-4">
            <div v-if="requestNote" class="ms-note" :class="NOTE_CLASSES[requestNote.tone]" role="status">
              <p class="font-semibold">{{ requestNote.title }}</p>
              <p class="mt-1">{{ requestNote.text }}</p>
            </div>

            <B24Card>
              <dl class="grid grid-cols-1 gap-x-6 gap-y-3 text-sm min-[640px]:grid-cols-[180px_minmax(0,1fr)]">
                <dt class="text-slate-500">Сумма</dt>
                <dd class="font-semibold text-slate-900">
                  {{ formatRub(request.total) }}
                  <span v-if="request.amounts" class="font-normal text-slate-500">· {{ request.amounts.vatText }}</span>
                </dd>
                <dt class="text-slate-500">Оплатить до</dt>
                <dd class="text-slate-900">
                  {{ formatPlanDate(request.dueDate) }}
                  <span class="text-slate-500">— {{ offer.dueBusinessDays }} рабочих дней</span>
                </dd>
                <template v-if="request.payer">
                  <dt class="text-slate-500">Плательщик</dt>
                  <dd class="text-slate-900">
                    {{ request.payer.name }}<br>
                    <span class="text-slate-500">ИНН {{ request.payer.inn }}<template v-if="request.payer.kpp">, КПП {{ request.payer.kpp }}</template></span>
                  </dd>
                </template>
                <dt class="text-slate-500">Что оплачиваете</dt>
                <dd class="text-slate-900">Pro на {{ request.monthsText }} для портала {{ request.portal?.domain || domain }}</dd>
                <template v-if="request.contact">
                  <dt class="text-slate-500">Счёт пришлём</dt>
                  <dd class="text-slate-900">
                    {{ request.contact.email }}<template v-if="request.contact.cc">, {{ request.contact.cc }}</template>
                  </dd>
                </template>
                <dt class="text-slate-500">Статус</dt>
                <dd class="text-slate-900">{{ requestNote?.title }}</dd>
              </dl>

              <template #footer>
                <div class="flex flex-wrap gap-2">
                  <B24Button
                    v-if="request.pdfAvailable"
                    label="Скачать PDF"
                    color="primary"
                    :loading="downloading"
                    @click="downloadPdf"
                  />
                  <B24Button label="Скопировать назначение платежа" color="default" @click="copyPurpose" />
                  <template v-if="openRequest">
                    <B24Button label="Изменить реквизиты или срок" color="link" @click="editRequest" />
                    <B24Button label="Отменить заявку" color="link" @click="cancelOpen = true" />
                  </template>
                  <B24Button v-else label="Новая заявка" color="link" @click="newRequestForm" />
                </div>
              </template>
            </B24Card>

            <B24Card>
              <template #header>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-base font-semibold text-slate-900">Назначение платежа</span>
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[12px] text-slate-600">
                    {{ request.paymentPurpose.length }} из {{ PAYMENT_PURPOSE_LIMIT }} символов
                  </span>
                </div>
              </template>
              <p class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-mono text-[13px] leading-relaxed text-slate-900">
                {{ request.paymentPurpose }}
              </p>
              <p class="mt-2 text-sm text-slate-500">
                Попросите бухгалтерию не менять текст. Номер счёта и код портала — два независимых ключа: платёж
                найдёт портал даже без номера счёта.
              </p>
            </B24Card>

            <B24Card>
              <template #header>
                <span class="text-base font-semibold text-slate-900">Что будет после оплаты</span>
              </template>
              <p class="text-sm text-slate-700">
                Менеджер Mainsoft увидит поступление, сверит его со счётом по номеру и коду портала и включит Pro.
                Пока это делается вручную, в рабочие дни с 9 до 18 по Москве. Закрывающий документ пришлём на ту же
                почту.
              </p>
              <p class="mt-2 text-sm text-slate-500">
                Оплатили, а Pro не включился за рабочий день — напишите на
                <a :href="`mailto:${offer.contactEmail}`" class="font-semibold text-[#0075ff] underline">{{ offer.contactEmail }}</a>
                и укажите номер счёта.
              </p>
              <details class="mt-3 text-sm text-slate-500">
                <summary class="cursor-pointer text-slate-600">Технические данные для поддержки</summary>
                <p class="mt-2">
                  Заявка № {{ request.sequenceNumber ?? '—' }} · портал {{ request.portal?.domain }} · код
                  {{ request.portal?.code }} · member_id <code>{{ request.portal?.memberIdShort }}</code> (сокращён).
                </p>
              </details>
            </B24Card>
          </div>

          <aside class="flex min-w-0 flex-col gap-4">
            <B24Card>
              <template #header>
                <span class="text-base font-semibold text-slate-900">Статус заявки</span>
              </template>
              <ol class="flex flex-col gap-3">
                <li v-for="step in timeline" :key="step.title" class="flex gap-3">
                  <span
                    class="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                    :class="step.state === 'done'
                      ? 'bg-emerald-500 text-white'
                      : step.state === 'now' ? 'border-2 border-[#0075ff] bg-white' : 'border border-slate-300 bg-white'"
                    aria-hidden="true"
                  >{{ step.state === 'done' ? '✓' : '' }}</span>
                  <span class="min-w-0">
                    <span class="block text-sm font-semibold" :class="step.state === 'todo' ? 'text-slate-500' : 'text-slate-900'">
                      {{ step.title }}
                    </span>
                    <span v-if="step.hint" class="block text-xs text-slate-500">{{ step.hint }}</span>
                  </span>
                </li>
              </ol>
            </B24Card>
          </aside>
        </div>

        <!-- ============ Форма ============ -->
        <form v-else class="grid gap-4 min-[1100px]:grid-cols-[minmax(0,1fr)_340px]" novalidate @submit.prevent="submit">
          <div class="flex min-w-0 flex-col gap-4">
            <div
              v-if="openRequest"
              class="ms-note border-amber-200 bg-amber-50 text-amber-900"
              role="status"
            >
              <p class="font-semibold">Счёт {{ openRequest.invoiceNumber }} уже выставлен и ждёт оплаты.</p>
              <p class="mt-1">
                Новый срок заменит его: старый счёт отзовём, чтобы не оплатили оба. Если нужно только поправить
                реквизиты — оставьте тот же срок, номер счёта останется прежним.
              </p>
              <button type="button" class="mt-2 text-sm font-semibold underline" @click="view = 'invoice'">
                Вернуться к счёту {{ openRequest.invoiceNumber }}
              </button>
            </div>
            <div
              v-else-if="request?.status === 'paid' && request.proPaidUntil"
              class="ms-note ms-note-success"
              role="status"
            >
              Pro оплачен до {{ formatPlanDate(request.proPaidUntil) }}. Новый срок начнётся со следующего дня —
              оплаченные дни не пропадут.
            </div>

            <div
              v-if="submitAttempted && summaryErrors.length"
              ref="errorSummaryRef"
              class="ms-note ms-note-danger"
              tabindex="-1"
              role="alert"
            >
              <p class="font-semibold">{{ errorSummaryTitle(summaryErrors.length) }}</p>
              <ul class="mt-1 list-disc pl-5">
                <li v-for="item in summaryErrors" :key="item.field">
                  <a :href="`#pro-${item.field}`" class="underline" @click.prevent="focusField(item.field)">
                    {{ PRO_FIELD_LABELS[item.field] }}
                  </a>: {{ item.error }}
                </li>
              </ul>
            </div>

            <!-- Портал и контакт -->
            <B24Card>
              <template #header>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-base font-semibold text-slate-900">Портал и контакт</span>
                  <span class="text-xs text-slate-500">подставлено из Битрикс24</span>
                </div>
              </template>

              <dl class="grid grid-cols-1 gap-x-6 gap-y-2 text-sm min-[640px]:grid-cols-[200px_minmax(0,1fr)]">
                <dt class="text-slate-500">Портал</dt>
                <dd class="font-medium text-slate-900">{{ domain }}</dd>
                <dt class="text-slate-500">Код портала для платежа</dt>
                <dd class="font-mono font-semibold text-slate-900">{{ portalCode }} <span class="font-sans text-xs font-normal text-slate-500">попадёт в счёт</span></dd>
              </dl>
              <details class="mt-2 text-sm text-slate-500">
                <summary class="cursor-pointer text-slate-600">Почему в форме нет member_id</summary>
                <p class="mt-2">
                  member_id — 32-значный технический идентификатор портала. Человеку он ничего не говорит, в назначение
                  платежа не влезает, а в поле формы его можно было бы подменить. Поэтому сервер берёт портал из
                  авторизации приложения, а не из формы: запросить счёт на чужой портал нельзя. Людям — домен и
                  короткий код {{ portalCode }}, который не меняется, даже если портал сменит домен.
                </p>
              </details>

              <div class="mt-4 grid grid-cols-1 gap-4 min-[700px]:grid-cols-2">
                <div>
                  <label for="pro-contactPhone" :class="inputBase">Телефон для связи</label>
                  <input
                    id="pro-contactPhone"
                    v-model="form.contactPhone"
                    type="tel"
                    inputmode="tel"
                    autocomplete="tel"
                    placeholder="+7 900 000-00-00"
                    :class="inputClasses('contactPhone')"
                    class="mt-1"
                    :aria-invalid="isInvalid('contactPhone')"
                    aria-describedby="pro-contactPhone-msg"
                    @input="onInput('contactPhone')"
                    @blur="touch('contactPhone')"
                  >
                  <p v-if="fieldMessage('contactPhone')" id="pro-contactPhone-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('contactPhone')!.kind]">
                    {{ fieldMessage('contactPhone')!.text }}
                  </p>
                </div>
                <div>
                  <label for="pro-contactName" :class="inputBase">Кому писать по счёту</label>
                  <input
                    id="pro-contactName"
                    v-model="form.contactName"
                    type="text"
                    autocomplete="name"
                    :class="inputClasses('contactName')"
                    class="mt-1"
                    :aria-invalid="isInvalid('contactName')"
                    aria-describedby="pro-contactName-msg"
                    @input="onInput('contactName')"
                    @blur="touch('contactName')"
                  >
                  <p v-if="fieldMessage('contactName')" id="pro-contactName-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('contactName')!.kind]">
                    {{ fieldMessage('contactName')!.text }}
                  </p>
                </div>
              </div>
            </B24Card>

            <!-- Плательщик -->
            <B24Card>
              <template #header>
                <div class="flex flex-wrap items-baseline gap-2">
                  <span class="text-base font-semibold text-slate-900">Плательщик</span>
                  <span class="text-sm text-slate-500">— организация или ИП, на которую выставить счёт</span>
                </div>
              </template>

              <div v-if="suggestions.length" class="mb-4 flex flex-wrap items-center gap-2 text-sm">
                <span class="text-slate-500">Ваши юрлица из CRM портала:</span>
                <button
                  v-for="item in suggestions"
                  :key="`${item.companyId}-${item.inn}-${item.kpp}`"
                  type="button"
                  class="rounded-full border border-slate-300 bg-white px-3 py-1 text-left text-slate-800 transition hover:border-[#0075ff] hover:bg-[#e8f3ff]"
                  @click="applyRequisite(item)"
                >
                  {{ shortPayerName(item.name) || item.companyTitle }}
                  <span class="text-xs text-slate-500">ИНН {{ item.inn }}</span>
                </button>
              </div>

              <div class="grid grid-cols-1 gap-4 min-[700px]:grid-cols-2">
                <div>
                  <label for="pro-payerInn" :class="inputBase">ИНН <span class="text-rose-600" aria-hidden="true">*</span></label>
                  <input
                    id="pro-payerInn"
                    v-model="form.payerInn"
                    type="text"
                    inputmode="numeric"
                    autocomplete="off"
                    maxlength="14"
                    placeholder="10 или 12 цифр"
                    required
                    :class="inputClasses('payerInn')"
                    class="mt-1"
                    :aria-invalid="isInvalid('payerInn')"
                    aria-describedby="pro-payerInn-msg"
                    @input="onInnInput"
                    @blur="touch('payerInn')"
                  >
                  <p v-if="fieldMessage('payerInn')" id="pro-payerInn-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('payerInn')!.kind]">
                    {{ fieldMessage('payerInn')!.text }}
                  </p>
                </div>
                <div v-if="!isIp">
                  <label for="pro-payerKpp" :class="inputBase">КПП <span class="text-rose-600" aria-hidden="true">*</span></label>
                  <input
                    id="pro-payerKpp"
                    v-model="form.payerKpp"
                    type="text"
                    autocomplete="off"
                    maxlength="9"
                    placeholder="9 знаков"
                    :class="inputClasses('payerKpp')"
                    class="mt-1"
                    :aria-invalid="isInvalid('payerKpp')"
                    aria-describedby="pro-payerKpp-msg"
                    @input="onInput('payerKpp')"
                    @blur="touch('payerKpp')"
                  >
                  <p v-if="fieldMessage('payerKpp')" id="pro-payerKpp-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('payerKpp')!.kind]">
                    {{ fieldMessage('payerKpp')!.text }}
                  </p>
                </div>
              </div>

              <div class="mt-4">
                <label for="pro-payerName" :class="inputBase">
                  {{ isIp ? 'ФИО предпринимателя' : 'Полное наименование' }} <span class="text-rose-600" aria-hidden="true">*</span>
                </label>
                <input
                  id="pro-payerName"
                  v-model="form.payerName"
                  type="text"
                  autocomplete="organization"
                  :placeholder="isIp ? 'Индивидуальный предприниматель Фамилия Имя Отчество' : 'Общество с ограниченной ответственностью «…»'"
                  required
                  :class="inputClasses('payerName')"
                  class="mt-1"
                  :aria-invalid="isInvalid('payerName')"
                  aria-describedby="pro-payerName-msg"
                  @input="onInput('payerName')"
                  @blur="touch('payerName')"
                >
                <p v-if="fieldMessage('payerName')" id="pro-payerName-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('payerName')!.kind]">
                  {{ fieldMessage('payerName')!.text }}
                </p>
              </div>

              <div class="mt-4">
                <label for="pro-payerAddress" :class="inputBase">Юридический адрес <span class="text-rose-600" aria-hidden="true">*</span></label>
                <textarea
                  id="pro-payerAddress"
                  v-model="form.payerAddress"
                  rows="2"
                  placeholder="Индекс, регион, город, улица, дом, офис"
                  required
                  :class="inputClasses('payerAddress')"
                  class="mt-1 resize-y"
                  :aria-invalid="isInvalid('payerAddress')"
                  aria-describedby="pro-payerAddress-msg"
                  @input="onInput('payerAddress')"
                  @blur="touch('payerAddress')"
                />
                <p v-if="fieldMessage('payerAddress')" id="pro-payerAddress-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('payerAddress')!.kind]">
                  {{ fieldMessage('payerAddress')!.text }}
                </p>
              </div>

              <div class="mt-4 grid grid-cols-1 gap-4 min-[700px]:grid-cols-2">
                <div>
                  <label for="pro-contactEmail" :class="inputBase">Почта для счёта <span class="text-rose-600" aria-hidden="true">*</span></label>
                  <input
                    id="pro-contactEmail"
                    v-model="form.contactEmail"
                    type="email"
                    autocomplete="email"
                    required
                    :class="inputClasses('contactEmail')"
                    class="mt-1"
                    :aria-invalid="isInvalid('contactEmail')"
                    aria-describedby="pro-contactEmail-msg"
                    @input="onInput('contactEmail')"
                    @blur="touch('contactEmail')"
                  >
                  <p v-if="fieldMessage('contactEmail')" id="pro-contactEmail-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('contactEmail')!.kind]">
                    {{ fieldMessage('contactEmail')!.text }}
                  </p>
                </div>
                <div>
                  <label for="pro-contactCc" :class="inputBase">Копия счёта</label>
                  <input
                    id="pro-contactCc"
                    v-model="form.contactCc"
                    type="email"
                    autocomplete="off"
                    placeholder="buh@company.ru"
                    :class="inputClasses('contactCc')"
                    class="mt-1"
                    :aria-invalid="isInvalid('contactCc')"
                    aria-describedby="pro-contactCc-msg"
                    @input="onInput('contactCc')"
                    @blur="touch('contactCc')"
                  >
                  <p v-if="fieldMessage('contactCc')" id="pro-contactCc-msg" class="mt-1 text-xs" :class="MESSAGE_CLASSES[fieldMessage('contactCc')!.kind]">
                    {{ fieldMessage('contactCc')!.text }}
                  </p>
                </div>
              </div>
            </B24Card>

            <!-- Срок -->
            <B24Card>
              <template #header>
                <span class="text-base font-semibold text-slate-900">Срок подписки</span>
              </template>
              <div
                id="pro-months"
                class="grid grid-cols-1 gap-3 min-[520px]:grid-cols-2 min-[900px]:grid-cols-4"
                role="radiogroup"
                aria-label="Срок подписки"
                tabindex="-1"
              >
                <label
                  v-for="term in terms"
                  :key="term.months"
                  class="relative flex cursor-pointer flex-col gap-0.5 rounded-xl border px-3 pb-3 pt-4 transition"
                  :class="form.months === term.months
                    ? 'border-[#0075ff] bg-[#e8f3ff] ring-1 ring-[#0075ff]'
                    : 'border-slate-200 bg-white hover:border-slate-300'"
                >
                  <span
                    v-if="term.label"
                    class="absolute -top-2.5 right-2 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    :class="term.label.includes('по цене') ? 'bg-emerald-100 text-emerald-800' : 'bg-[#e8f3ff] text-[#0058c2]'"
                  >{{ term.label }}</span>
                  <input v-model="form.months" class="sr-only" type="radio" name="pro-term" :value="term.months">
                  <span class="text-sm font-semibold text-slate-900">{{ monthsText(term.months) }}</span>
                  <span class="text-base font-semibold text-slate-900">{{ formatRub(term.total) }}</span>
                  <span class="text-xs text-slate-500">{{ termCardHint(term) }}</span>
                </label>
              </div>
              <p class="mt-3 text-sm text-slate-500">
                Срок считается с даты включения Pro. Если Pro уже работает, новый срок начнётся со следующего дня после
                текущего — оплаченные дни не пропадают.
              </p>
            </B24Card>

            <!-- Картой -->
            <div class="ms-note border-slate-200 bg-white text-slate-700">
              <b>Оплата картой.</b> Пока принимаем оплату только по счёту от организации или ИП. Хотите картой — напишите на
              <a :href="mailto" class="font-semibold text-[#0075ff] underline">{{ offer.contactEmail }}</a>, укажите портал
              {{ domain }} и срок. Пришлём ссылку на оплату.
            </div>

            <!-- Оферта -->
            <B24Card>
              <label for="pro-offerAccepted" class="flex cursor-pointer items-start gap-3 text-sm text-slate-800">
                <input
                  id="pro-offerAccepted"
                  v-model="form.offerAccepted"
                  type="checkbox"
                  class="mt-0.5 size-4 shrink-0 rounded border-slate-300"
                  :aria-invalid="isInvalid('offerAccepted')"
                  aria-describedby="pro-offerAccepted-msg"
                  @change="touch('offerAccepted'); clearServerError('offerAccepted')"
                >
                <span>
                  Согласен с
                  <a v-if="offer.offerUrl" :href="offer.offerUrl" target="_blank" rel="noopener" class="text-[#0075ff] underline">условиями оферты</a>
                  <template v-else>условиями оферты</template>: оплата счёта означает согласие с ними
                </span>
              </label>
              <p
                v-if="fieldMessage('offerAccepted')?.kind === 'error'"
                id="pro-offerAccepted-msg"
                class="mt-1 text-xs text-rose-700"
              >
                {{ fieldMessage('offerAccepted')!.text }}
              </p>
            </B24Card>
          </div>

          <!-- Сводка -->
          <aside class="min-w-0">
            <div class="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm min-[1100px]:sticky min-[1100px]:top-4">
              <p class="text-base font-semibold text-slate-900">Pro для портала {{ domain }}</p>
              <template v-if="selectedTerm">
                <div class="flex flex-col gap-1.5 text-sm">
                  <div
                    v-for="row in termSummaryRows(selectedTerm)"
                    :key="row.label"
                    class="flex justify-between gap-3"
                    :class="row.discount ? 'text-emerald-700' : 'text-slate-600'"
                  >
                    <span>{{ row.label }}</span>
                    <span class="whitespace-nowrap">{{ row.value }}</span>
                  </div>
                </div>
                <div class="flex items-baseline justify-between gap-3 border-t border-slate-200 pt-3">
                  <span class="text-sm text-slate-700">К оплате</span>
                  <b class="text-xl text-slate-900">{{ formatRub(selectedTerm.total) }}</b>
                </div>
                <p class="text-xs text-slate-500">{{ perMonthHint(selectedTerm, terms) }}</p>
              </template>

              <ul v-if="featureId" class="flex flex-col gap-1 text-xs text-slate-500">
                <li v-for="feature in includedFeatures" :key="feature.id" :class="feature.id === featureId ? 'font-semibold text-slate-800' : ''">
                  ✓ {{ feature.label }}
                </li>
              </ul>

              <div v-if="submitError && !Object.keys(serverErrors).length" class="ms-note ms-note-danger" role="alert">
                {{ submitError }}
              </div>

              <B24Button
                type="submit"
                :label="submitting ? 'Формируем счёт…' : PRO_SUBMIT_LABEL"
                color="primary"
                :loading="submitting"
                :disabled="submitting"
                class="justify-center"
              />
              <p class="text-xs text-slate-500">
                Счёт действует {{ offer.dueBusinessDays }} рабочих дней. Придёт на почту и останется в «Настройках →
                Подписка». Pro включим после поступления денег — обычно в тот же рабочий день.
              </p>
            </div>
          </aside>
        </form>
      </template>
    </div>

    <!-- Подтверждение отмены -->
    <div
      v-if="cancelOpen && request"
      class="fixed inset-0 z-[9995] flex items-center justify-center bg-slate-900/40 px-4"
      @click.self="cancelling || (cancelOpen = false)"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="pro-cancel-title"
        class="w-full max-w-[460px] rounded-2xl bg-white p-5 shadow-2xl"
      >
        <h2 id="pro-cancel-title" class="text-lg font-semibold text-slate-900">Отменить заявку и счёт?</h2>
        <p class="mt-2 text-sm text-slate-700">
          Счёт {{ request.invoiceNumber }} станет недействительным, сделку в CRM Mainsoft переведём в «Не оплачен».
          Если деньги уже ушли — не отменяйте, напишите на {{ offer?.contactEmail }}.
        </p>
        <p v-if="cancelError" class="mt-2 text-sm text-rose-700" role="alert">{{ cancelError }}</p>
        <div class="mt-4 flex flex-wrap justify-end gap-2">
          <B24Button label="Не отменять" color="default" :disabled="cancelling" @click="cancelOpen = false" />
          <B24Button label="Отменить заявку" color="primary" :loading="cancelling" @click="confirmCancel" />
        </div>
      </div>
    </div>
  </B24Container>
</template>
