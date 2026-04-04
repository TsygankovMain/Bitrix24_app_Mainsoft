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
}

function toggleDropdown() {
    isOpen.value = !isOpen.value
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
    <div ref="rootRef" class="relative inline-block text-left w-64">
        <label class="block text-sm font-medium text-gray-700 mb-1">{{ label }}</label>
        <button 
            @click="toggleDropdown"
            type="button" 
            class="inline-flex justify-between w-full rounded-md border border-gray-300 shadow-sm px-4 py-2 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none"
        >
            <span class="truncate">{{ displayLabel }}</span>
            <svg class="-mr-1 ml-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
        </button>

        <div
            v-if="isOpen"
            class="mt-2 w-full rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none border border-gray-200"
        >
                <div class="p-2 border-b space-y-2">
                    <div class="grid grid-cols-2 gap-1 rounded-md bg-gray-100 p-1">
                        <button
                            type="button"
                            @click="setMode('include')"
                            :class="[
                                'rounded px-2 py-1 text-xs font-medium transition-colors',
                                currentMode === 'include' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                            ]"
                        >
                            Включить
                        </button>
                        <button
                            type="button"
                            @click="setMode('exclude')"
                            :class="[
                                'rounded px-2 py-1 text-xs font-medium transition-colors',
                                currentMode === 'exclude' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                            ]"
                        >
                            Кроме
                        </button>
                    </div>
                    <div class="flex justify-between">
                        <button @click="selectAll" class="text-xs text-blue-600 hover:text-blue-800">{{ selectAllLabel }}</button>
                        <button @click="deselectAll" class="text-xs text-gray-500 hover:text-gray-700">{{ clearLabel }}</button>
                    </div>
                </div>
                <div class="py-1 max-h-72 overflow-y-auto">
                    <div 
                        v-for="opt in options" 
                        :key="opt.id" 
                        class="flex items-center px-4 py-2 hover:bg-gray-100 cursor-pointer"
                        @click.stop="toggleOption(opt.id)"
                    >
                        <input 
                            type="checkbox" 
                            :checked="modelValue.includes(opt.id)" 
                            class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                        >
                        <span class="ml-3 block text-sm text-gray-700 truncate" :title="String(opt.name)">
                            {{ opt.name }}
                        </span>
                    </div>
                </div>
            </div>
    </div>
</template>
