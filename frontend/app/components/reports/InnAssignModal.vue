<script setup lang="ts">
import { ref, watch } from 'vue'
import type { InnApplyItem } from '~/types/inn'
import { useProgress } from '~/composables/useProgress'

const props = defineProps<{
  visible: boolean
  projectId: string
  projectName: string
  ourInn: string
  clientInn: string
  dateFrom: string
  dateTo: string
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'applied', updated: number): void }>()

const apiStore = useApiStore()
const globalProgress = useProgress()
const localOur = ref('')
const localClient = ref('')
const overwrite = ref(false)
const applying = ref(false)
const error = ref('')

watch(() => props.visible, (v) => {
  if (v) { localOur.value = props.ourInn || ''; localClient.value = props.clientInn || ''; overwrite.value = false; error.value = '' }
})

async function apply() {
  error.value = ''
  applying.value = true
  try {
    const resolved = await apiStore.resolveInnProjectItems(
      props.projectId, props.dateFrom, props.dateTo, localOur.value.trim(), localClient.value.trim(), overwrite.value
    )
    const items: InnApplyItem[] = resolved.items
    if (!items.length) { error.value = 'Нет карточек для применения'; applying.value = false; return }
    const CHUNK = 25
    let updated = 0
    globalProgress.begin('Простановка ИНН…', items.length)
    for (let i = 0; i < items.length; i += CHUNK) {
      const res = await apiStore.applyInnBackfill(items.slice(i, i + CHUNK))
      updated += res.updated
      globalProgress.update(Math.min(i + CHUNK, items.length))
    }
    emit('applied', updated)
    emit('close')
  } catch (e: any) {
    error.value = e?.data?.error || e?.message || 'Ошибка применения'
  } finally {
    applying.value = false
    globalProgress.end()
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[900] flex items-center justify-center" style="background:rgba(15,23,42,.45)" @click.self="!applying && emit('close')">
      <div class="bg-white rounded-2xl shadow-xl w-[460px] p-5">
        <h3 class="text-lg font-bold text-slate-900">Заполнение ИНН · «{{ projectName }}»</h3>
        <p class="text-xs text-slate-500 mt-1 mb-4">Применится ко всем карточкам проекта за период</p>
        <label class="block text-xs font-semibold text-slate-500 mb-1">Наш ИНН</label>
        <input v-model="localOur" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mb-3" placeholder="наш ИНН">
        <label class="block text-xs font-semibold text-slate-500 mb-1">ИНН клиента</label>
        <input v-model="localClient" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mb-4" placeholder="ИНН клиента">
        <div class="rounded-lg bg-slate-50 border border-slate-200 p-3 mb-4 text-sm">
          <label class="flex items-center gap-2 mb-1 text-slate-700"><input type="radio" :value="false" v-model="overwrite"> Только пустые поля</label>
          <label class="flex items-center gap-2 text-rose-700"><input type="radio" :value="true" v-model="overwrite"> <b>Перезаписать всё</b> (смена юр.лица)</label>
        </div>
        <div v-if="error" class="rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700 mb-3">{{ error }}</div>
        <div class="flex justify-end gap-2">
          <B24Button label="Отмена" color="link" @click="emit('close')" />
          <B24Button label="Применить к проекту" color="success" :loading="applying" @click="apply" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
