<script setup lang="ts">
import { ref, watch } from 'vue'
import { getMonthRange, getWeekRange } from '~/utils/reportDateRange'

const props = defineProps<{
    dateFrom: string,
    dateTo: string
}>()

const emit = defineEmits(['update:dateFrom', 'update:dateTo'])

const localFrom = ref(props.dateFrom)
const localTo = ref(props.dateTo)

watch(() => props.dateFrom, (val) => localFrom.value = val)
watch(() => props.dateTo, (val) => localTo.value = val)

function update() {
    emit('update:dateFrom', localFrom.value)
    emit('update:dateTo', localTo.value)
}

function setPreset(preset: 'prev_month' | 'prev_week' | 'cur_month' | 'cur_week') {
    const range = preset === 'cur_week'
        ? getWeekRange(0)
        : preset === 'prev_week'
            ? getWeekRange(-1)
            : preset === 'cur_month'
                ? getMonthRange(0)
                : getMonthRange(-1)

    localFrom.value = range.dateFrom
    localTo.value = range.dateTo
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
            <button type="button" @click="setPreset('cur_week')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Эта неделя</button>
            <button type="button" @click="setPreset('prev_week')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Пред. неделя</button>
            <button type="button" @click="setPreset('cur_month')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Этот месяц</button>
            <button type="button" @click="setPreset('prev_month')" class="px-2 py-1 text-xs border rounded bg-gray-50 hover:bg-gray-100">Пред. месяц</button>
        </div>
    </div>
</template>
