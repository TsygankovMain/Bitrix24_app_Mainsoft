<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { formatDataFreshness } from '~/utils/dataFreshness'

interface TimesheetSyncResult {
  status: string
  count: number
  last_synced_at?: string | null
}

const emit = defineEmits<{
  refreshed: [result: TimesheetSyncResult]
}>()

const apiStore = useApiStore()
const toast = useToast()

const lastSyncedAt = ref<string | null>(null)
const isRefreshing = ref(false)

// Вся логика текста — в app/utils/dataFreshness.ts, здесь только рендер.
const freshnessLabel = computed(() => formatDataFreshness(lastSyncedAt.value))

async function loadStatus() {
  try {
    lastSyncedAt.value = (await apiStore.getTimesheetSyncStatus()).last_synced_at
  } catch {
    // индикатор не критичен для работы страницы
  }
}

async function refresh() {
  if (isRefreshing.value) return
  isRefreshing.value = true
  try {
    // Без периода: инкремент по updatedTime глобален, даты ему не нужны.
    // Именно верхняя граница периода давала баги с границами суток (2fcd176, 6c2862c).
    const result = await apiStore.syncTimesheets()
    if (result?.last_synced_at) {
      lastSyncedAt.value = result.last_synced_at
    } else {
      await loadStatus()
    }
    emit('refreshed', result)
  } catch (e: unknown) {
    toast.add({
      title: 'Ошибка обновления данных: ' + ((e as { message?: string })?.message || 'неизвестная ошибка'),
      color: 'air-primary-alert'
    })
  } finally {
    isRefreshing.value = false
  }
}

onMounted(() => {
  void loadStatus()
})

defineExpose({ loadStatus, refresh })
</script>

<template>
  <div class="ms-data-freshness flex shrink-0 items-center gap-2 text-xs text-slate-500">
    <span class="whitespace-nowrap">{{ freshnessLabel }}</span>
    <button
      type="button"
      :disabled="isRefreshing"
      class="whitespace-nowrap rounded-md border border-slate-200 px-2 py-1 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
      @click="refresh"
    >
      {{ isRefreshing ? 'Обновляю…' : 'Обновить' }}
    </button>
  </div>
</template>
