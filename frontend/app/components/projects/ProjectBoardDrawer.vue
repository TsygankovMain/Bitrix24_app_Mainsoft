<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import {
  formatProjectDate,
  getStageBadgeClass
} from '~/utils/projectBoard'

const props = defineProps<{
  modelValue: boolean
  card: ProjectBoardCardRecord | null
  employees: ProjectBoardDirectoryOption[]
  companies: ProjectBoardDirectoryOption[]
  legalEntities: ProjectBoardDirectoryOption[]
  isSaving?: boolean
  isArchiving?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'save', payload: Record<string, any>): void
  (event: 'archive', value: boolean): void
}>()

const draft = ref<Record<string, any>>({})

const stageBadgeClass = computed(() => getStageBadgeClass(props.card?.stage || ''))

watch(
  () => [props.card, props.modelValue],
  () => {
    if (!props.card) {
      draft.value = {}
      return
    }

    draft.value = {
      project_name: props.card.project_name || '',
      project_hours_budget: props.card.project_hours_budget ?? '',
      hourly_rate: props.card.hourly_rate ?? 0,
      is_support: props.card.is_support,
      curator_user_id: props.card.curator_user_id || '',
      curator_name: props.card.curator_name || '',
      project_start_date: props.card.project_start_date || '',
      project_end_date: props.card.project_end_date || '',
      company_id: props.card.company_id || '',
      company_name: props.card.company_name || '',
      our_legal_entity_id: props.card.our_legal_entity_id || '',
      our_legal_entity_name: props.card.our_legal_entity_name || '',
    }
  },
  { immediate: true }
)

function closeDrawer() {
  emit('update:modelValue', false)
}

function handleCompanyChange(selected: ProjectBoardDirectoryOption | null) {
  draft.value.company_name = selected ? String(selected.name) : ''
}

function handleCuratorChange(selected: ProjectBoardDirectoryOption | null) {
  draft.value.curator_name = selected ? String(selected.name) : ''
}

function handleLegalEntityChange(selected: ProjectBoardDirectoryOption | null) {
  draft.value.our_legal_entity_name = selected ? String(selected.name) : ''
}

function handleSave() {
  if (!props.card) {
    return
  }

  emit('save', {
    project_id: props.card.project_id,
    ...draft.value
  })
}
</script>

<template>
  <div
    v-if="modelValue && card"
    class="fixed inset-0 z-50 flex justify-end bg-slate-950/20"
    @click="closeDrawer"
  >
    <aside
      class="flex h-full w-full max-w-[460px] flex-col border-l border-gray-200 bg-white shadow-2xl"
      @click.stop
    >
      <div class="border-b border-gray-200 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="truncate text-lg font-semibold text-gray-900">{{ card.project_name }}</div>
            <div class="mt-2 flex flex-wrap gap-2">
              <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', stageBadgeClass]">
                {{ card.stage }}
              </span>
              <span class="inline-flex rounded-full bg-gray-100 px-2.5 py-1 text-[11px] font-semibold text-gray-700">
                Ручная стадия: {{ card.manual_stage || 'Не задана' }}
              </span>
            </div>
          </div>

          <button
            type="button"
            class="rounded-full p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
            @click="closeDrawer"
          >
            ✕
          </button>
        </div>
      </div>

      <div class="flex-1 space-y-5 overflow-y-auto px-5 py-5">
        <div class="rounded-2xl bg-gray-50 p-4 text-xs text-gray-600">
          Стадия проекта меняется перетаскиванием между колонками.
          Автоматические статусы выставляются по последним списаниям.
        </div>

        <div class="grid gap-4">
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-gray-700">Название проекта</span>
            <input
              v-model="draft.project_name"
              type="text"
              class="rounded-xl border border-gray-200 px-3 py-2 outline-none transition focus:border-lime-500"
            >
          </label>

          <div class="grid grid-cols-2 gap-4">
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Бюджет, часы</span>
              <input
                v-model="draft.project_hours_budget"
                type="number"
                min="0"
                step="0.5"
                class="rounded-xl border border-gray-200 px-3 py-2 outline-none transition focus:border-lime-500"
              >
            </label>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Ставка</span>
              <input
                v-model="draft.hourly_rate"
                type="number"
                min="0"
                step="100"
                class="rounded-xl border border-gray-200 px-3 py-2 outline-none transition focus:border-lime-500"
              >
            </label>
          </div>

          <label class="flex items-center justify-between rounded-2xl border border-gray-200 px-4 py-3 text-sm">
            <span class="font-medium text-gray-700">Проект на поддержке</span>
            <B24Switch v-model="draft.is_support" />
          </label>

          <SearchableSelect
            v-model="draft.curator_user_id"
            label="Куратор"
            empty-label="Не назначен"
            search-placeholder="Поиск куратора"
            :options="employees"
            @update:selected="handleCuratorChange"
          />

          <SearchableSelect
            v-model="draft.company_id"
            label="Компания"
            empty-label="Не выбрана"
            search-placeholder="Поиск по названию или ИНН"
            :options="companies"
            @update:selected="handleCompanyChange"
          />

          <SearchableSelect
            v-model="draft.our_legal_entity_id"
            label="Наше юрлицо"
            empty-label="Не выбрано"
            search-placeholder="Поиск по названию или ИНН"
            :options="legalEntities"
            @update:selected="handleLegalEntityChange"
          />

          <div class="grid grid-cols-2 gap-4">
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Дата старта</span>
              <input
                v-model="draft.project_start_date"
                type="date"
                class="rounded-xl border border-gray-200 px-3 py-2 outline-none transition focus:border-lime-500"
              >
            </label>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Дата завершения</span>
              <input
                v-model="draft.project_end_date"
                type="date"
                class="rounded-xl border border-gray-200 px-3 py-2 outline-none transition focus:border-lime-500"
              >
            </label>
          </div>
        </div>

        <div class="rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
          <div class="font-medium text-gray-800">Текущие данные</div>
          <div class="mt-3 grid gap-2 text-xs">
            <div class="flex items-center justify-between gap-3">
              <span class="text-gray-400">Последнее списание</span>
              <span class="font-medium text-gray-700">
                {{ card.last_writeoff_at ? formatProjectDate(card.last_writeoff_at) : 'Нет данных' }}
              </span>
            </div>
            <div class="flex items-center justify-between gap-3">
              <span class="text-gray-400">Дней без списаний</span>
              <span class="font-medium text-gray-700">{{ card.last_writeoff_days || 0 }}</span>
            </div>
            <div class="flex items-center justify-between gap-3">
              <span class="text-gray-400">Архив</span>
              <span class="font-medium text-gray-700">{{ card.is_archived ? 'Да' : 'Нет' }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="border-t border-gray-200 px-5 py-4">
        <div class="flex flex-wrap gap-2">
          <B24Button label="Сохранить" color="success" :loading="isSaving" @click="handleSave" />
          <B24Button
            :label="card.is_archived ? 'Вернуть из архива' : 'В архив'"
            color="default"
            :loading="isArchiving"
            @click="emit('archive', !card.is_archived)"
          />
          <B24Button label="Закрыть" color="link" @click="closeDrawer" />
        </div>
      </div>
    </aside>
  </div>
</template>
