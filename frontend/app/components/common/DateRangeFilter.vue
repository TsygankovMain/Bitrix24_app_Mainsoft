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
        <label class="block text-sm font-medium text-slate-700">Период</label>
        <div class="flex items-center gap-2">
            <input v-model="localFrom" type="date" class="min-w-[174px]" @change="update" >
            <span class="self-center text-slate-400">-</span>
            <input v-model="localTo" type="date" class="min-w-[174px]" @change="update" >
        </div>
        <div class="flex flex-wrap gap-1.5">
            <button type="button" class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900" @click="setPreset('cur_week')">Эта неделя</button>
            <button type="button" class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900" @click="setPreset('prev_week')">Пред. неделя</button>
            <button type="button" class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900" @click="setPreset('cur_month')">Этот месяц</button>
            <button type="button" class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900" @click="setPreset('prev_month')">Пред. месяц</button>
        </div>
    </div>
</template>
