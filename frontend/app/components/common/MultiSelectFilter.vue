<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
// Simple implementation of multi-select with checkboxes
// Props: options: {id, name}[], modelValue: string[] (ids)

const props = defineProps<{
    options: { id: string | number, name: string | number }[],
    modelValue: (string | number)[],
    label: string,
    mode?: 'include' | 'exclude'
}>()

const emit = defineEmits(['update:modelValue', 'update:mode'])

const rootRef = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const query = ref('')
const currentMode = computed(() => props.mode === 'exclude' ? 'exclude' : 'include')

const selectedCount = computed(() => props.modelValue.length)
const displayLabel = computed(() => {
    if (currentMode.value === 'exclude') {
        if (selectedCount.value === 0) return 'Без исключений'
        if (selectedCount.value === props.options.length) return 'Исключены все'
        if (selectedCount.value === 1) {
            const item = props.options.find(o => o.id === props.modelValue[0])
            return item ? `Кроме ${item.name}` : 'Кроме 1'
        }

        return `Кроме ${selectedCount.value}`
    }

    if (selectedCount.value === 0) return 'Все'
    if (selectedCount.value === props.options.length) return 'Все'
    if (selectedCount.value === 1) {
        const item = props.options.find(o => o.id === props.modelValue[0])
        return item ? item.name : '1 выбран'
    }
    return `${selectedCount.value} выбрано`
})

const selectAllLabel = computed(() => currentMode.value === 'exclude' ? 'Исключить все' : 'Выбрать все')
const clearLabel = computed(() => currentMode.value === 'exclude' ? 'Без исключений' : 'Сбросить')
const filteredOptions = computed(() => {
    const normalizedQuery = query.value.trim().toLowerCase()
    if (!normalizedQuery) {
        return props.options
    }

    return props.options.filter((option) =>
        `${option.name} ${option.id}`.toLowerCase().includes(normalizedQuery)
    )
})

function toggleOption(id: string | number) {
    const newSelected = [...props.modelValue]
    const idx = newSelected.indexOf(id)
    if (idx >= 0) {
        newSelected.splice(idx, 1)
    } else {
        newSelected.push(id)
    }
    emit('update:modelValue', newSelected)
}

function selectAll() {
    emit('update:modelValue', props.options.map(o => o.id))
}

function deselectAll() {
    emit('update:modelValue', [])
}

function setMode(mode: 'include' | 'exclude') {
    emit('update:mode', mode)
}

function closeDropdown() {
    isOpen.value = false
    query.value = ''
}

function toggleDropdown() {
    isOpen.value = !isOpen.value
    if (!isOpen.value) {
        query.value = ''
    }
}

function handlePointerDown(event: MouseEvent | TouchEvent) {
    if (!isOpen.value) return

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
    <div ref="rootRef" class="relative inline-block w-full max-w-[320px] text-left">
        <label class="mb-1 block text-sm font-medium text-slate-700">{{ label }}</label>
        <button 
            @click="toggleDropdown"
            type="button" 
            class="inline-flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm outline-none transition hover:border-slate-300 focus:border-lime-500"
        >
            <span class="truncate">{{ displayLabel }}</span>
            <svg class="-mr-1 ml-2 h-5 w-5 text-slate-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
        </button>

        <div
            v-if="isOpen"
            class="absolute left-0 right-0 z-30 mt-2 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
        >
                <div class="space-y-3 border-b border-slate-100 p-3">
                    <input
                        v-model="query"
                        type="search"
                        placeholder="Поиск"
                        class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-lime-500"
                    >
                    <div class="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1">
                        <button
                            type="button"
                            @click="setMode('include')"
                            :class="[
                                'rounded-lg px-2 py-1.5 text-xs font-medium transition-colors',
                                currentMode === 'include' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                            ]"
                        >
                            Включить
                        </button>
                        <button
                            type="button"
                            @click="setMode('exclude')"
                            :class="[
                                'rounded-lg px-2 py-1.5 text-xs font-medium transition-colors',
                                currentMode === 'exclude' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                            ]"
                        >
                            Кроме
                        </button>
                    </div>
                    <div class="flex justify-between">
                        <button @click="selectAll" class="text-xs font-medium text-lime-700 transition hover:text-lime-800">{{ selectAllLabel }}</button>
                        <button @click="deselectAll" class="text-xs text-slate-500 transition hover:text-slate-700">{{ clearLabel }}</button>
                    </div>
                </div>
                <div class="max-h-72 overflow-y-auto p-2">
                    <div
                        v-if="!filteredOptions.length"
                        class="rounded-xl px-3 py-3 text-sm text-slate-400"
                    >
                        Ничего не найдено
                    </div>
                    <div
                        v-for="opt in filteredOptions"
                        :key="opt.id" 
                        class="mb-1 flex cursor-pointer items-center rounded-xl px-3 py-3 transition hover:bg-slate-50"
                        @click.stop="toggleOption(opt.id)"
                    >
                        <input 
                            type="checkbox" 
                            :checked="modelValue.includes(opt.id)" 
                            class="h-4 w-4 rounded border-slate-300 text-lime-600 focus:ring-lime-500"
                        >
                        <span class="ml-3 block truncate text-sm text-slate-700" :title="String(opt.name)">
                            {{ opt.name }}
                        </span>
                    </div>
                </div>
            </div>
    </div>
</template>
