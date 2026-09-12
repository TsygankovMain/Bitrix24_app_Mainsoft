<script setup lang="ts">
/**
 * Карточка выставленного документа.
 *
 * Три блока данных и три действия. Данные: строки документа (то, что видит
 * клиент), потреблённые списания (то, из чего строки собраны) и расхождения
 * — drift. Действия: детализация XLSX, печать акта, отмена.
 *
 * Про drift. Документ хранит СВОЙ снимок часов, ставки и суммы, потому что
 * синхронизация физически удаляет записи, пропавшие в Битриксе, а само
 * списание уникально только по паре «учётка + bitrix_id» (контракт, «Почему
 * учёт у нас, а не в CRM»). Значит расхождение между снимком и текущими
 * данными — штатное состояние, а не сбой, и человек должен его видеть:
 * именно оно объясняет, почему отчёт за месяц уже не сходится со счётом.
 * Молча пересчитывать документ нельзя — он уже ушёл клиенту.
 *
 * Отмена требует причину и отдельное подтверждение. Отмена освобождает
 * списания (частичный уникальный индекс работает только для действующих
 * документов), то есть после неё те же часы можно выставить снова — это
 * действие с последствиями, а не «закрыть окно». Спрашивается это боковой
 * панелью BillingCancelDrawer.vue: там же разобрано, почему прежнее
 * центрированное окно рисовалось шириной в одно слово.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import BillingGate from '~/components/finance/BillingGate.vue'
import BillingErrorNote from '~/components/finance/BillingErrorNote.vue'
import BillingCancelDrawer from '~/components/finance/BillingCancelDrawer.vue'
import { describeBillingError, type BillingErrorView } from '~/utils/billingErrors'
import { billingCancelledNotice } from '~/utils/billingCancel'
import {
  billingDocumentNumber,
  billingStatusClass,
  billingStatusLabel,
  formatBillingDate,
  formatBillingHours,
  formatBillingHoursWithUnit,
  formatBillingMoney,
  formatBillingPeriod,
  formatRecordsRu,
} from '~/utils/billingFormat'
import { openCrmItemCard } from '~/utils/openCrmItem'
import type {
  BillingDocumentDetail,
  BillingDriftPayload,
  BillingEntryPayload,
  BillingLinePayload,
} from '~/types/billing'

/** Смарт-счёт CRM Битрикс24 — фиксированный тип сущности (контракт, вводная). */
const SMART_INVOICE_ENTITY_TYPE_ID = 31

const route = useRoute()
const router = useRouter()
const apiStore = useApiStore()
const { access, permissions, loadBillingSettings } = useBillingFeature()

const documentId = computed(() => {
  const raw = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id

  return String(raw || '').trim()
})

const isLoading = ref(false)
const detail = ref<BillingDocumentDetail | null>(null)
const error = ref<BillingErrorView | null>(null)
const actionError = ref<BillingErrorView | null>(null)
const notice = ref('')

/**
 * Пришли сюда сразу после выставления (мастер добавляет ?created=1).
 *
 * Плашка нужна не для поздравления: карточка выглядит одинаково и через
 * минуту, и через месяц, и человек, которого сюда переадресовали, не понимает,
 * случилось ли то, чего он ждал, и что делать дальше. Отдельным состоянием, а
 * не общим notice: тот занят результатами действий на самой карточке
 * (отмена, печать), и затирать его нельзя.
 */
const justCreated = ref(false)

const isPrinting = ref(false)
const isDownloading = ref(false)
const isCancelling = ref(false)

/**
 * Отмена спрашивается боковой панелью (BillingCancelDrawer.vue), а не
 * центрированным окном — см. её докстринг: там же причина, по которой
 * прежний попап был шириной в одно слово.
 *
 * Отказ сервера на отмену держим отдельным ref, а не общим actionError:
 * общий рисуется плашкой НА КАРТОЧКЕ, под кнопками, а панель отмены обязана
 * показать отказ у себя внутри — с набранной причиной на месте, чтобы
 * попытку можно было повторить не собирая форму заново.
 */
const showCancelDialog = ref(false)
const cancelError = ref<BillingErrorView | null>(null)

const { initApp, processErrorGlobal } = useAppInit('BillingDocumentPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const document = computed(() => detail.value?.document || null)
const lines = computed<BillingLinePayload[]>(() => detail.value?.lines || [])
const entries = computed<BillingEntryPayload[]>(() => detail.value?.entries || [])
const drift = computed<BillingDriftPayload[]>(() => detail.value?.drift || [])

const driftChanged = computed(() => drift.value.filter(item => String(item?.kind || '') !== 'deleted'))
const driftDeleted = computed(() => drift.value.filter(item => String(item?.kind || '') === 'deleted'))

const isCancelled = computed(() => String(document.value?.status || '') === 'cancelled')

useHead({
  title: computed(() => document.value
    ? `Счёт ${billingDocumentNumber(document.value)}`
    : 'Документ')
})

async function loadDocument() {
  if (!documentId.value || !access.value.enabled) {
    return
  }

  isLoading.value = true
  error.value = null

  try {
    detail.value = await apiStore.getBillingDocument(documentId.value)
  } catch (e) {
    error.value = describeBillingError(e)
    detail.value = null
  } finally {
    isLoading.value = false
  }
}

/**
 * Детализация XLSX.
 *
 * Скачивание — тот же приём, что у выгрузок отчётов: сервер отдаёт файл, а
 * ссылку на объект в памяти создаём и отзываем сами. Отказ показываем
 * плашкой: «не удалось скачать» не повод рушить открытую карточку.
 */
async function downloadDetail() {
  if (!documentId.value) {
    return
  }

  isDownloading.value = true
  actionError.value = null

  try {
    const blob = await apiStore.exportBillingDetail(documentId.value)
    const url = window.URL.createObjectURL(blob)
    const link = window.document.createElement('a')

    link.href = url
    link.download = `Детализация-${billingDocumentNumber(document.value)}.xlsx`
    window.document.body.appendChild(link)
    link.click()
    window.document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (e) {
    actionError.value = describeBillingError(e)
  } finally {
    isDownloading.value = false
  }
}

/**
 * Печать акта.
 *
 * Два кода отказа разбираются отдельно и понятным текстом
 * (app/utils/billingErrors.ts): act_template_missing — на портале нет шаблона
 * акта, documentgenerator_unavailable — генератор документов недоступен. Это
 * самая непроверенная часть контракта («Непроверенное»: печать по
 * смарт-счёту живьём не проверялась), поэтому текст сразу подсказывает
 * обходной путь — XLSX-детализацию.
 */
async function printAct() {
  if (!documentId.value) {
    return
  }

  isPrinting.value = true
  actionError.value = null
  notice.value = ''

  try {
    detail.value = await apiStore.printBillingAct(documentId.value)
    notice.value = detail.value?.document?.act_number
      ? `Акт ${detail.value.document.act_number} напечатан.`
      : 'Акт напечатан.'
  } catch (e) {
    actionError.value = describeBillingError(e)
  } finally {
    isPrinting.value = false
  }
}

function openCancelDialog() {
  cancelError.value = null
  actionError.value = null
  showCancelDialog.value = true
}

async function submitCancel(reason: string) {
  if (!documentId.value || isCancelling.value) {
    return
  }

  isCancelling.value = true
  cancelError.value = null

  try {
    detail.value = await apiStore.cancelBillingDocument(documentId.value, reason)
    showCancelDialog.value = false
    notice.value = billingCancelledNotice(
      detail.value?.document ? billingDocumentNumber(detail.value.document) : ''
    )
  } catch (e) {
    cancelError.value = describeBillingError(e)
  } finally {
    isCancelling.value = false
  }
}

function openInCrm() {
  const crmId = String(document.value?.crm_entity_id ?? '').trim()
  if (!crmId) {
    return
  }

  openCrmItemCard(SMART_INVOICE_ENTITY_TYPE_ID, crmId)
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
  } catch (e) {
    processErrorGlobal(e)
    return
  }

  justCreated.value = String(route.query.created || '') === '1'

  await Promise.allSettled([loadBillingSettings(), loadDocument()])
})
</script>

<template>
  <BillingGate
    :title="document ? `Счёт ${billingDocumentNumber(document)}` : 'Документ'"
    description="Строки документа, потреблённые списания и расхождения"
  >
    <template #actions>
      <B24Button label="Реестр документов" color="link" @click="router.push('/finance/billing')" />
      <B24Button label="Обновить" color="default" :loading="isLoading" @click="loadDocument" />
    </template>

    <BillingErrorNote :error="error" />
    <BillingErrorNote :error="actionError" />

    <div v-if="justCreated && !isCancelled" class="ms-note ms-note-success">
      <p class="font-semibold">Счёт выставлен</p>
      <p class="mt-1">
        Он создан в CRM портала, а часы из него помечены выставленными — второй раз они в счёт не
        уйдут. Дальше: откройте счёт в CRM и отправьте клиенту, напечатайте акт или скачайте
        детализацию. Если счёт собран неверно, отмените документ — списания снова станут свободными.
      </p>
    </div>

    <div v-if="notice" class="ms-note ms-note-success">{{ notice }}</div>

    <div v-if="isLoading" class="ms-surface ms-empty-state">Загрузка…</div>

    <template v-else-if="document">
      <!-- Шапка документа -->
      <section class="ms-surface flex flex-col gap-4 p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-lg font-semibold text-slate-900">
                {{ billingDocumentNumber(document) }}
              </span>
              <span :class="['ms-pill', billingStatusClass(document.status)]">
                {{ billingStatusLabel(document.status) }}
              </span>
            </div>
            <p class="mt-1 text-sm text-slate-500">
              от {{ formatBillingDate(document.created_at) }}
              · период {{ formatBillingPeriod(document.period_from, document.period_to) }}
            </p>
          </div>

          <div class="flex flex-wrap gap-2">
            <B24Button
              v-if="document.crm_entity_id"
              label="Счёт в CRM"
              color="link"
              @click="openInCrm"
            />
            <B24Button
              label="Скачать детализацию"
              color="success"
              :loading="isDownloading"
              @click="downloadDetail"
            />
            <B24Button
              v-if="permissions.canPrintAct && !isCancelled"
              label="Напечатать акт"
              :loading="isPrinting"
              @click="printAct"
            />
            <B24Button
              v-if="permissions.canCancel && !isCancelled"
              label="Отменить"
              color="danger"
              @click="openCancelDialog"
            />
          </div>
        </div>

        <div class="grid gap-4 text-sm md:grid-cols-2 xl:grid-cols-4">
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-400">Клиент</p>
            <p class="mt-1 font-medium text-slate-900">{{ document.company_name || '—' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-400">Наше юрлицо</p>
            <p class="mt-1 font-medium text-slate-900">{{ document.our_company_name || '—' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-400">Часы</p>
            <p class="mt-1 font-medium text-slate-900">
              {{ formatBillingHoursWithUnit(document.total_hours) }}
            </p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-400">Сумма</p>
            <p class="mt-1 font-medium text-slate-900">
              {{ formatBillingMoney(document.total_amount, document.currency) }}
              <span v-if="document.vat_mode === 'included'" class="block text-xs font-normal text-slate-500">
                НДС включён в цену
              </span>
            </p>
          </div>
        </div>

        <div v-if="document.act_number" class="ms-note ms-note-info">
          <p>Акт {{ document.act_number }} напечатан: номер и дата совпадают со счётом.</p>
          <!--
            Ссылки открываем как есть, новой вкладкой: файл лежит на портале и
            отдаётся его же авторизацией. Скачивать акт через приложение
            незачем — оно бы только переложило байты.
          -->
          <p v-if="document.act_pdf_url || document.act_download_url" class="mt-2 flex flex-wrap gap-3">
            <a
              v-if="document.act_pdf_url"
              :href="document.act_pdf_url"
              target="_blank"
              rel="noopener"
              class="font-medium text-[#0075ff] underline"
            >Открыть PDF</a>
            <a
              v-if="document.act_download_url"
              :href="document.act_download_url"
              target="_blank"
              rel="noopener"
              class="font-medium text-[#0075ff] underline"
            >Скачать DOCX</a>
          </p>
        </div>
        <div v-else-if="document.act_error" class="ms-panel-warning">
          Последняя попытка напечатать акт не удалась: {{ document.act_error }}
        </div>

        <div v-if="isCancelled" class="ms-note ms-note-danger">
          <p class="font-semibold">
            Документ отменён {{ formatBillingDate(document.cancelled_at) }}
          </p>
          <p class="mt-1">
            Причина: {{ document.cancel_reason || 'не указана' }}. Списания освобождены — эти часы
            можно выставить заново.
          </p>
        </div>
      </section>

      <!-- Строки документа -->
      <section class="ms-surface flex flex-col gap-3 p-5">
        <h2 class="text-base font-semibold text-slate-900">Строки документа</h2>

        <div v-if="!lines.length" class="ms-empty-state">Строк нет.</div>

        <div v-else class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Наименование работ</th>
                <th class="text-right">Часы</th>
                <th class="text-right">Цена</th>
                <th class="text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, index) in lines" :key="String(line.id ?? index)">
                <td>{{ line.title || line.project_name || '—' }}</td>
                <td class="text-right">{{ formatBillingHours(line.hours) }}</td>
                <td class="text-right">{{ formatBillingMoney(line.rate, document.currency) }}</td>
                <td class="text-right font-medium text-slate-900">
                  {{ formatBillingMoney(line.amount, document.currency) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Расхождения -->
      <section v-if="drift.length" class="ms-surface flex flex-col gap-3 p-5">
        <h2 class="text-base font-semibold text-slate-900">Расхождения со снимком</h2>
        <p class="text-sm text-slate-500">
          Документ хранит свой снимок часов и ставок. Здесь то, что изменилось в учёте ПОСЛЕ
          выставления: суммы счёта от этого не меняются, но отчёт за период со счётом уже не сойдётся.
        </p>

        <div v-if="driftChanged.length" class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Сотрудник</th>
                <th>Дата</th>
                <th class="text-right">Часы в снимке</th>
                <th class="text-right">Часы сейчас</th>
                <th class="text-right">Ставка в снимке</th>
                <th class="text-right">Ставка сейчас</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in driftChanged" :key="`changed-${item.timesheet_bitrix_id ?? index}`">
                <td>{{ item.employee_name || '—' }}</td>
                <td>{{ formatBillingDate(item.date_reflection) }}</td>
                <td class="text-right">{{ formatBillingHours(item.hours) }}</td>
                <td class="text-right">{{ formatBillingHours(item.current_hours) }}</td>
                <td class="text-right">{{ formatBillingMoney(item.rate_snapshot, document.currency) }}</td>
                <td class="text-right">{{ formatBillingMoney(item.current_rate, document.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="driftDeleted.length" class="ms-panel-warning">
          <p class="font-semibold">
            Удалено после выставления: {{ formatRecordsRu(driftDeleted.length) }}
          </p>
          <ul class="mt-2 space-y-1">
            <li v-for="(item, index) in driftDeleted" :key="`deleted-${item.timesheet_bitrix_id ?? index}`">
              {{ item.employee_name || 'Сотрудник неизвестен' }},
              {{ formatBillingDate(item.date_reflection) }},
              {{ formatBillingHours(item.hours) }} ч
              <span v-if="item.description">— {{ item.description }}</span>
            </li>
          </ul>
        </div>
      </section>

      <!-- Потреблённые списания -->
      <section class="ms-surface flex flex-col gap-3 p-5">
        <h2 class="text-base font-semibold text-slate-900">
          Потреблённые списания
          <span v-if="entries.length" class="text-sm font-normal text-slate-500">
            · {{ formatRecordsRu(entries.length) }}
          </span>
        </h2>
        <p class="text-sm text-slate-500">
          Снимок часов, из которых собран документ. Пока документ действует, эти списания не могут
          попасть в другой счёт.
        </p>

        <div v-if="!entries.length" class="ms-empty-state">Списаний нет.</div>

        <div v-else class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>Сотрудник</th>
                <th>Проект</th>
                <th>Описание</th>
                <th class="text-right">Часы</th>
                <th class="text-right">Ставка</th>
                <th class="text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(entry, index) in entries" :key="String(entry.id ?? entry.timesheet_bitrix_id ?? index)">
                <td>{{ formatBillingDate(entry.date_reflection) }}</td>
                <td>{{ entry.employee_name || '—' }}</td>
                <td>{{ entry.project_name || '—' }}</td>
                <td class="max-w-[320px] truncate" :title="entry.description || ''">
                  {{ entry.description || '—' }}
                </td>
                <td class="text-right">{{ formatBillingHours(entry.hours) }}</td>
                <td class="text-right">{{ formatBillingMoney(entry.rate_snapshot, document.currency) }}</td>
                <td class="text-right">{{ formatBillingMoney(entry.amount, document.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <div v-else-if="!error && access.enabled" class="ms-surface ms-empty-state">
      Документ не найден. Возможно, его удалили — вернитесь в реестр.
    </div>

    <!-- Отмена: причина обязательна, подтверждение отдельным действием -->
    <BillingCancelDrawer
      v-model:open="showCancelDialog"
      :document-number="document ? billingDocumentNumber(document) : ''"
      :error="cancelError"
      :submitting="isCancelling"
      @submit="submitCancel"
    />
  </BillingGate>
</template>
