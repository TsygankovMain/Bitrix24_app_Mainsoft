<script setup lang="ts">
/**
 * Форма операции: тип, сумма, дата, назначение, комментарий.
 *
 * Пять полей и ни одного лишнего. Валюта, источник и сделка в форму не
 * выведены сознательно: валюта у операций портала одна (RUB по умолчанию
 * сервиса), источник у операции с этого экрана всегда `manual` — иначе
 * сервер потребует сделку, — а сделки у операции по проекту нет вовсе.
 * Поле, которое человек не может заполнить осмысленно, — это не гибкость,
 * а лишний клик.
 *
 * Проверка ввода — чистой функцией validateBddsOperationForm: те же
 * правила, что у сервера, плюс обязательное назначение. Компонент только
 * показывает то, что она вернула, и не решает сам.
 *
 * Ширины здесь не задаются вовсе — только сетка и flex. Это не лень:
 * именованные утилиты ширины в этом проекте попадают на шкалу --spacing
 * темы UI Kit и дают десятки пикселей вместо сотен, поэтому там, где ширина
 * действительно нужна, она пишется явным значением в квадратных скобках.
 */
import { computed, ref, watch } from 'vue'
import {
  BDDS_OPERATION_TYPE_OPTIONS,
  defaultBddsOperationForm,
  parseBddsOperationAmount,
  validateBddsOperationForm,
  formatBddsOperationAmount,
  type BddsOperationForm,
  type BddsOperationType,
} from '~/utils/bddsOperations'
import type { BddsOperationCreatePayload } from '~/types/bdds'

const props = withDefaults(defineProps<{
  /** Элемент СП проекта: к нему привязывается операция. */
  projectItemId: string | null
  projectName?: string
  saving?: boolean
  /** Отказ сервера последней попытки — показываем над кнопками. */
  serverError?: string
}>(), {
  projectName: '',
  saving: false,
  serverError: '',
})

const emit = defineEmits<{
  (event: 'submit', payload: BddsOperationCreatePayload): void
  (event: 'cancel'): void
}>()

const form = ref<BddsOperationForm>(defaultBddsOperationForm())
/** Показывать ошибки только после попытки отправки: не ругаться заранее. */
const submitted = ref(false)

const validation = computed(() => validateBddsOperationForm({
  form: form.value,
  projectItemId: props.projectItemId,
}))

const errors = computed(() => submitted.value ? validation.value.errors : {})

/** Что именно уйдёт в портал — подпись под суммой, а не догадка. */
const amountPreview = computed(() => {
  const amount = parseBddsOperationAmount(form.value.amount)
  if (amount === null || amount <= 0) {
    return ''
  }

  const sign = form.value.type === 'income' ? 'поступление' : 'списание'
  return `В портал уйдёт ${sign} на ${formatBddsOperationAmount(amount)}.`
})

function selectType(type: BddsOperationType) {
  form.value = { ...form.value, type }
}

function reset() {
  form.value = defaultBddsOperationForm()
  submitted.value = false
}

function submit() {
  submitted.value = true
  const result = validation.value
  if (!result.valid || !result.payload) {
    return
  }

  emit('submit', result.payload)
}

defineExpose({ reset })

/** Смена проекта — новая операция: суммы прежнего проекта тут ни при чём. */
watch(() => props.projectItemId, () => {
  reset()
})
</script>

<template>
  <form class="flex flex-col gap-4" @submit.prevent="submit">
    <div class="flex flex-col gap-1">
      <span class="text-sm font-medium text-slate-700">Тип операции</span>
      <div class="ms-tabbar">
        <button
          v-for="option in BDDS_OPERATION_TYPE_OPTIONS"
          :key="option.id"
          type="button"
          class="ms-tab-btn"
          :class="form.type === option.id ? 'ms-tab-btn-active' : ''"
          @click="selectType(option.id)"
        >
          {{ option.label }}
        </button>
      </div>
      <p v-if="errors.type" class="text-xs text-rose-700">{{ errors.type }}</p>
    </div>

    <div class="grid gap-4 sm:grid-cols-2">
      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700" for="bdds-operation-amount">Сумма, ₽</label>
        <input
          id="bdds-operation-amount"
          v-model="form.amount"
          type="text"
          inputmode="decimal"
          class="w-full"
          placeholder="15 000,50"
          autocomplete="off"
        >
        <p v-if="errors.amount" class="text-xs text-rose-700">{{ errors.amount }}</p>
        <p v-else-if="amountPreview" class="text-xs text-slate-500">{{ amountPreview }}</p>
      </div>

      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700" for="bdds-operation-date">Дата</label>
        <input
          id="bdds-operation-date"
          v-model="form.date"
          type="date"
          class="w-full"
        >
        <p v-if="errors.date" class="text-xs text-rose-700">{{ errors.date }}</p>
      </div>
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-sm font-medium text-slate-700" for="bdds-operation-purpose">Назначение</label>
      <input
        id="bdds-operation-purpose"
        v-model="form.purpose"
        type="text"
        class="w-full"
        placeholder="Аванс подрядчику по этапу 2"
        autocomplete="off"
      >
      <p v-if="errors.purpose" class="text-xs text-rose-700">{{ errors.purpose }}</p>
      <p v-else class="text-xs text-slate-500">
        Станет названием операции в смарт-процессе — по нему её узнают в CRM.
      </p>
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-sm font-medium text-slate-700" for="bdds-operation-comment">Комментарий</label>
      <textarea
        id="bdds-operation-comment"
        v-model="form.comment"
        rows="2"
        class="w-full"
        placeholder="Договор 14/26, счёт от 01.09"
      />
      <p class="text-xs text-slate-500">
        Необязателен, но входит в проверку на повтор: две операции с одинаковой суммой и датой
        различаются именно комментарием.
      </p>
    </div>

    <p v-if="projectName" class="text-xs text-slate-500">
      Операция привяжется к проекту «{{ projectName }}».
    </p>

    <p v-if="serverError" class="ms-note ms-note-danger">{{ serverError }}</p>

    <div class="flex flex-wrap items-center gap-2">
      <B24Button
        label="Сохранить операцию"
        color="success"
        type="submit"
        :loading="saving"
      />
      <B24Button label="Отмена" color="link" type="button" @click="emit('cancel')" />
    </div>
  </form>
</template>
