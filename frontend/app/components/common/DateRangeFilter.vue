<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
    dateFrom: string,
    dateTo: string
}>()

const emit = defineEmits(['update:dateFrom', 'update:dateTo', 'change'])

const localFrom = ref(props.dateFrom)
const localTo = ref(props.dateTo)

watch(() => props.dateFrom, (val) => localFrom.value = val)
watch(() => props.dateTo, (val) => localTo.value = val)

function update() {
    emit('update:dateFrom', localFrom.value)
    emit('update:dateTo', localTo.value)
    emit('change') // Optional immediate trigger
}

function setPreset(preset: 'prev_month' | 'prev_week' | 'cur_month' | 'cur_week') {
    const now = new Date()
    let start = new Date()
    let end = new Date()

    if (preset === 'cur_week') {
        const day = now.getDay() || 7 // 1-7 (Mon-Sun)
        start.setDate(now.getDate() - day + 1)
        end = now // current week usually means "up to now" or "end of week"? Let's assume up to end of week for filter range
        end.setDate(now.getDate() - day + 7)
    } else if (preset === 'prev_week') {
        const day = now.getDay() || 7
        start.setDate(now.getDate() - day + 1 - 7)
        end.setDate(now.getDate() - day + 7 - 7)
    } else if (preset === 'cur_month') {
        start.setDate(1)
        end = new Date(now.getFullYear(), now.getMonth() + 1, 0)
    } else if (preset === 'prev_month') {
        start = new Date(now.getFullYear(), now.getMonth() - 1, 1)
        end = new Date(now.getFullYear(), now.getMonth(), 0)
    }

    localFrom.value = start.toISOString().split('T')[0]
    localTo.value = end.toISOString().split('T')[0]
    update()
}
</script>

<template>
    <div class="flex flex-col gap-2">
        <label class="block text-sm font-medium text-gray-700">Период</label>
        <div class="flex gap-2">
            <input type="date" v-model="localFrom" @change="update" class="border rounded px-2 py-1 text-sm bg-white" />
            <span class="self-center">-</span>
            <input type="date" v-model="localTo" @change="update" class="border rounded px-2 py-1 text-sm bg-white" />
        </div>
        <div class="flex gap-1 flex-wrap">
            <button @click="setPreset('cur_week')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Эта неделя</button>
            <button @click="setPreset('prev_week')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Пред. неделя</button>
            <button @click="setPreset('cur_month')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Этот месяц</button>
            <button @click="setPreset('prev_month')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Пред. месяц</button>
        </div>
    </div>
</template>
