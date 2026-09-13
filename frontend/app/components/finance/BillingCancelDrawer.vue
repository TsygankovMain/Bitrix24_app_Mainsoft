<script setup lang="ts">
/**
 * Подтверждение отмены выставленного документа.
 *
 * Было: центрированное окно `.ms-modal-overlay` + `.ms-modal-panel w-full
 * max-w-lg` прямо в разметке карточки. `max-w-lg` в этом проекте НЕ 32rem:
 * Tailwind 4 разрешает `max-w-*` по цепочке тем `--max-width` → `--spacing` →
 * `--container`, а Bitrix24 UI Kit (`@bitrix24/b24ui-nuxt`, air-design-tokens/
 * tw-style/spacing.css) объявляет `--spacing-lg: 20px`. То есть панель
 * получала `max-width: 20px` и сжималась до ширины самого длинного слова —
 * это и есть «кривой слишком узкий попап» из жалобы. Поэтому здесь и дальше
 * в этом компоненте ширины заданы только в явных единицах
 * (`max-w-[520px]`, `max-w-full`), а именованные `max-w-sm/md/lg/xl` не
 * используются вообще.
 *
 * Стало: боковая панель — единственная схема всплывающих слоёв, проверенная
 * в этом приложении в проде (frontend/app/components/projects/ProjectBoardDrawer.vue,
 * CreateProjectDrawer.vue, frontend/app/components/home/ProjectDetailsDrawer.vue):
 * оверлей `fixed inset-0` с `justify-end`, внутри `aside` фиксированной
 * ширины, шапка / прокручиваемое тело / подвал.
 *
 * Почему это безопасно во фрейме с автовысотой. Высоту фрейма приложение
 * просит у портала само (`requestIframeAutoHeight` → `BX24.fitWindow`,
 * layouts/default.vue), но корень лейаута — `h-dvh overflow-hidden` с
 * прокруткой ВНУТРИ контентной области, поэтому `inset-0` накрывает ровно
 * видимую область приложения, а не всю длину страницы. Содержимое панели
 * прокручивается внутри неё самой (`overflow-y-auto` у тела, `h-full` у
 * aside), так что открытая панель не удлиняет документ и фрейм не прыгает.
 *
 * Ширина: 520 px на широком фрейме, во всю ширину — ниже 600 px (портал на
 * ноутбуке с раскрытым меню, окно в половину экрана). Точка ровно та же по
 * смыслу, что у ProjectDetailsDrawer.
 *
 * Отказ сервера показывается ВНУТРИ панели, а не плашкой на карточке под
 * кнопками: панель остаётся открытой с набранной причиной, и человек видит,
 * на что именно сервер ответил отказом, рядом с тем, что он нажимал.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { BillingErrorView } from '~/utils/billingErrors'
import {
  BILLING_CANCEL_CLOSE_LABEL,
  BILLING_CANCEL_CONFIRM_LABEL,
  BILLING_CANCEL_CONSEQUENCE,
  BILLING_CANCEL_CRM_NOTE,
  BILLING_CANCEL_PENDING_HINT,
  BILLING_CANCEL_PENDING_LABEL,
  BILLING_CANCEL_REASON_HINT,
  BILLING_CANCEL_REASON_LABEL,
  BILLING_CANCEL_REASON_MAX_LENGTH,
  BILLING_CANCEL_REASON_PLACEHOLDER,
  BILLING_CANCEL_SUBMIT_LABEL,
  billingCancelBlockReason,
  billingCancelHeading,
  billingCancelReasonLeft,
  canDismissBillingCancel,
  canSubmitBillingCancel,
  normalizeBillingCancelReason,
  validateBillingCancelReason,
} from '~/utils/billingCancel'

const props = defineProps<{
  /** Номер документа для заголовка. Пусто — заголовок без номера. */
  documentNumber?: string | null
  /** Отказ сервера на последнюю попытку отмены. */
  error?: BillingErrorView | null
  /** Ждём ответа сервера. */
  submitting?: boolean
}>()

const emit = defineEmits<{ submit: [reason: string] }>()

const open = defineModel<boolean>('open', { required: true })

const reason = ref('')
/** Поле тронуто — до этого ошибку под пустым полем не показываем. */
const reasonTouched = ref(false)
const confirmed = ref(false)

const reasonField = ref<HTMLTextAreaElement | null>(null)

const heading = computed(() => billingCancelHeading(props.documentNumber))

const state = computed(() => ({
  reason: reason.value,
  confirmed: confirmed.value,
  submitting: Boolean(props.submitting),
}))

const reasonError = computed(() => (reasonTouched.value ? validateBillingCancelReason(reason.value) : null))
const blockReason = computed(() => (reasonTouched.value || confirmed.value ? billingCancelBlockReason(state.value) : null))
const canSubmit = computed(() => canSubmitBillingCancel(state.value))
const reasonLeft = computed(() => billingCancelReasonLeft(reason.value))
const dismissible = computed(() => canDismissBillingCancel(state.value))

function closeDrawer() {
  if (props.submitting) {
    return
  }

  open.value = false
}

/** Щелчок по затемнению закрывает панель только пока ничего не набрано. */
function handleOverlayClick() {
  if (dismissible.value) {
    closeDrawer()
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && dismissible.value) {
    closeDrawer()
  }
}

function submit() {
  reasonTouched.value = true

  if (!canSubmit.value) {
    return
  }

  emit('submit', normalizeBillingCancelReason(reason.value))
}

watch(open, async (isOpen) => {
  if (typeof window === 'undefined') {
    return
  }

  if (!isOpen) {
    window.removeEventListener('keydown', handleKeydown)
    return
  }

  // Каждое открытие — чистая форма: причина прошлой попытки к новому
  // документу и новому решению отношения не имеет.
  reason.value = ''
  reasonTouched.value = false
  confirmed.value = false

  window.addEventListener('keydown', handleKeydown)

  // Фокус уводим в поле причины: иначе он остался бы на кнопке «Отменить»
  // под затемнением, и Tab пошёл бы гулять по недоступной карточке.
  await nextTick()
  reasonField.value?.focus()
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleKeydown)
  }
})
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-[9995] flex justify-end bg-slate-900/40 backdrop-blur-sm"
    @click="handleOverlayClick"
  >
    <aside
      role="dialog"
      aria-modal="true"
      :aria-label="heading"
      class="flex h-full w-full max-w-full flex-col border-l border-slate-200 bg-white shadow-2xl min-[600px]:max-w-[520px]"
      @click.stop
    >
      <div class="border-b border-slate-200 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-lg font-semibold text-slate-900">{{ heading }}</div>
            <p class="mt-1 text-xs text-slate-500">Действие с последствиями — прочитайте, что произойдёт.</p>
          </div>

          <button
            type="button"
            aria-label="Закрыть панель отмены"
            class="shrink-0 rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="submitting"
            @click="closeDrawer"
          >
            ✕
          </button>
        </div>
      </div>

      <div class="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        <div class="ms-note ms-note-danger">
          <p class="font-semibold">{{ BILLING_CANCEL_CONSEQUENCE }}</p>
          <p class="mt-1">{{ BILLING_CANCEL_CRM_NOTE }}</p>
        </div>

        <!--
          Отказ сервера живёт здесь, внутри панели: набранная причина
          остаётся на месте, и повторить попытку можно не собирая форму
          заново. Плашка на карточке под кнопками этого не давала — панель
          к тому моменту уже закрывалась.
        -->
        <div v-if="error" class="ms-note ms-note-danger">
          <p class="font-semibold">{{ error.title }}</p>
          <p class="mt-1">{{ error.text }}</p>
        </div>

        <div class="grid gap-1 text-sm">
          <label class="font-medium text-slate-700" for="billing-cancel-reason">
            {{ BILLING_CANCEL_REASON_LABEL }} <span class="text-rose-500">*</span>
          </label>
          <textarea
            id="billing-cancel-reason"
            ref="reasonField"
            v-model="reason"
            rows="4"
            :maxlength="BILLING_CANCEL_REASON_MAX_LENGTH"
            :disabled="submitting"
            :aria-invalid="Boolean(reasonError)"
            class="w-full resize-y disabled:cursor-not-allowed disabled:bg-slate-50"
            :class="reasonError ? 'border-rose-300' : ''"
            :placeholder="BILLING_CANCEL_REASON_PLACEHOLDER"
            @blur="reasonTouched = true"
          />
          <p v-if="reasonError" class="text-xs text-rose-600">{{ reasonError }}</p>
          <p v-else class="text-xs text-slate-500">{{ BILLING_CANCEL_REASON_HINT }}</p>
          <p class="text-xs text-slate-400">Осталось символов: {{ reasonLeft }}</p>
        </div>

        <label class="flex items-start gap-2 text-sm text-slate-700">
          <input
            v-model="confirmed"
            type="checkbox"
            class="mt-0.5"
            :disabled="submitting"
          >
          <span>{{ BILLING_CANCEL_CONFIRM_LABEL }}</span>
        </label>

        <div v-if="submitting" class="ms-note ms-note-info">{{ BILLING_CANCEL_PENDING_HINT }}</div>
      </div>

      <div class="border-t border-slate-200 px-5 py-4">
        <p v-if="blockReason" class="mb-2 text-xs text-slate-500">{{ blockReason }}</p>
        <div class="flex flex-wrap justify-end gap-2">
          <B24Button
            :label="BILLING_CANCEL_CLOSE_LABEL"
            color="link"
            :disabled="submitting"
            @click="closeDrawer"
          />
          <B24Button
            :label="submitting ? BILLING_CANCEL_PENDING_LABEL : BILLING_CANCEL_SUBMIT_LABEL"
            color="danger"
            :disabled="!canSubmit"
            :loading="submitting"
            @click="submit"
          />
        </div>
      </div>
    </aside>
  </div>
</template>
