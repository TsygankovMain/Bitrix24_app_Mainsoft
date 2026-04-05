<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ProjectBoardDirectoryOption } from '~/utils/projectBoard'

const props = withDefaults(defineProps<{
  modelValue?: string | number | null
  options: ProjectBoardDirectoryOption[]
  label?: string
  emptyLabel?: string
  searchPlaceholder?: string
  disabled?: boolean
}>(), {
  label: '',
  emptyLabel: 'Не выбрано',
  searchPlaceholder: 'Поиск по названию или ИНН',
  disabled: false,
})

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'update:selected', option: ProjectBoardDirectoryOption | null): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const query = ref('')

const normalizedModelValue = computed(() => String(props.modelValue || ''))
const selectedOption = computed(() =>
  props.options.find(option => String(option.id) === normalizedModelValue.value) || null
)

const displayLabel = computed(() => {
  if (!selectedOption.value) {
    return props.emptyLabel
  }

  if (selectedOption.value.inn) {
    return `${selectedOption.value.name} · ИНН ${selectedOption.value.inn}`
  }

  return String(selectedOption.value.name)
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

function closeDropdown() {
  isOpen.value = false
  query.value = ''
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
  emit('update:modelValue', String(option.id))
  emit('update:selected', option)
  closeDropdown()
}

function clearValue() {
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

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeDropdown()
  }
}

watch(() => props.options, () => {
  if (!selectedOption.value && props.modelValue) {
    emit('update:selected', null)
  }
})

onMounted(() => {
  document.addEventListener('mousedown', handlePointerDown)
  document.addEventListener('touchstart', handlePointerDown, { passive: true })
  document.addEventListener('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handlePointerDown)
  document.removeEventListener('touchstart', handlePointerDown)
  document.removeEventListener('keydown', handleEscape)
})
</script>

<template>
  <div ref="rootRef" class="relative w-full">
    <label v-if="label" class="mb-1 block text-sm font-medium text-gray-700">{{ label }}</label>

    <button
      type="button"
      class="inline-flex w-full items-center justify-between rounded-xl border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-700 shadow-sm outline-none transition hover:border-gray-300 focus:border-lime-500"
      :disabled="disabled"
      @click="toggleDropdown"
    >
      <span class="min-w-0 truncate">{{ displayLabel }}</span>
      <svg class="ml-3 h-4 w-4 shrink-0 text-gray-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
      </svg>
    </button>

    <div
      v-if="isOpen"
      class="absolute left-0 right-0 z-30 mt-2 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-xl"
    >
      <div class="border-b border-gray-100 p-3">
        <input
          v-model="query"
          type="search"
          :placeholder="searchPlaceholder"
          class="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-lime-500"
        >
        <div class="mt-2 flex items-center justify-between text-xs">
          <button type="button" class="text-gray-500 transition hover:text-gray-700" @click="clearValue">
            Сбросить
          </button>
          <span class="text-gray-400">{{ filteredOptions.length }} знач.</span>
        </div>
      </div>

      <div class="max-h-72 overflow-y-auto p-2">
        <button
          v-if="!filteredOptions.length"
          type="button"
          class="w-full rounded-xl px-3 py-3 text-left text-sm text-gray-400"
          @click="closeDropdown"
        >
          Ничего не найдено
        </button>

        <button
          v-for="option in filteredOptions"
          :key="option.id"
          type="button"
          :class="[
            'mb-1 w-full rounded-xl px-3 py-3 text-left transition',
            String(option.id) === normalizedModelValue
              ? 'bg-lime-50 text-gray-900 ring-1 ring-lime-200'
              : 'text-gray-700 hover:bg-gray-50'
          ]"
          @click="selectOption(option)"
        >
          <div class="truncate text-sm font-medium">{{ option.name }}</div>
          <div v-if="option.inn" class="mt-1 text-xs text-gray-500">ИНН {{ option.inn }}</div>
        </button>
      </div>
    </div>
  </div>
</template>
