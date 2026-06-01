<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
    item: any
    level: number
}>()

defineEmits(['edit'])

const indentStyle = computed(() => ({ paddingLeft: `${(props.level * 1.5) + 2.5}rem` }))
const isConsidered = computed(() => props.item.isConsidered)
const hours = computed(() => parseFloat(props.item.hours).toFixed(2))

</script>

<template>
    <div class="group flex items-center gap-3 border-b border-slate-100 bg-white p-2.5 transition-colors hover:bg-blue-50/30" :style="indentStyle">
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
                 <div class="w-1.5 h-1.5 rounded-full shrink-0" :class="isConsidered ? 'bg-emerald-500' : 'bg-rose-400'"/>
                <span class="text-sm text-slate-700 truncate">{{ item.title || 'Без названия' }}</span>
            </div>
            <div class="text-xs text-slate-400 ml-3.5 mt-0.5 flex gap-2">
                <span>{{ new Date(item.date || item.createdTime).toLocaleDateString('ru-RU') }}</span>
                <span>•</span>
                <span class="truncate max-w-[200px]">{{ item.employeeName }}</span>
            </div>
        </div>

        <div class="flex items-center gap-4 shrink-0">
            <div class="w-16 text-right text-sm font-bold" :class="isConsidered ? 'text-teal-700' : 'text-slate-400'">
                {{ hours }} ч
            </div>
            <button class="rounded-xl p-1.5 text-slate-400 opacity-0 transition-all hover:bg-blue-100 hover:text-[#0075ff] group-hover:opacity-100" @click="$emit('edit', item)">
                <span class="material-symbols-outlined text-lg">edit</span>
            </button>
        </div>
    </div>
</template>
