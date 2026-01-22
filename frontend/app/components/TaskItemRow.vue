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
    <div class="flex items-center gap-3 p-2 border-b border-slate-50 bg-white hover:bg-blue-50/30 transition-colors group" :style="indentStyle">
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
                 <div class="w-1.5 h-1.5 rounded-full shrink-0" :class="isConsidered ? 'bg-emerald-500' : 'bg-rose-400'"></div>
                <span class="text-sm text-slate-700 truncate">{{ item.title || 'Без названия' }}</span>
            </div>
            <div class="text-xs text-slate-400 ml-3.5 mt-0.5 flex gap-2">
                <span>{{ new Date(item.createdTime).toLocaleDateString() }}</span>
                <span>•</span>
                <span class="truncate max-w-[200px]">{{ item.employeeName }}</span>
            </div>
        </div>

        <div class="flex items-center gap-4 shrink-0">
            <div class="text-sm font-bold w-16 text-right" :class="isConsidered ? 'text-emerald-600' : 'text-slate-400'">
                {{ hours }} ч
            </div>
            <button @click="$emit('edit', item)" class="p-1.5 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-100 opacity-0 group-hover:opacity-100 transition-all">
                <span class="material-symbols-outlined text-lg">edit</span>
            </button>
        </div>
    </div>
</template>
