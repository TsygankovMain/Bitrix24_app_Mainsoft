<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import {
  formatProjectDate,
  formatProjectCurrency,
  formatProjectHours,
  formatProjectPercent,
  getBudgetStatusBadgeClass,
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
  (event: 'update:modelValue' | 'archive', value: boolean): void
  (event: 'save', payload: Record<string, unknown>): void
  (event: 'open-project' | 'open-spa', card: ProjectBoardCardRecord): void
}>()

const draft = ref<Record<string, unknown>>({})

const stageBadgeClass = computed(() => getStageBadgeClass(props.card?.stage || ''))
const budgetBadgeClass = computed(() => getBudgetStatusBadgeClass(props.card?.budget_health_status || 'Без лимита'))
const isSupportCard = computed(() => Boolean(props.card?.is_support || String(props.card?.project_type || '').toLowerCase() === 'support'))
const budgetProgressPercent = computed(() => {
  const value = Number(props.card?.budget_utilization_percent)
  if (!Number.isFinite(value)) {
    return 0
  }
  return Math.max(0, Math.min(value, 100))
})

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
      planned_budget_amount: props.card.planned_budget_amount ?? '',
      hourly_rate: props.card.hourly_rate ?? 0,
      is_support: props.card.is_support,
      project_type: props.card.project_type || (props.card.is_support ? 'support' : 'delivery'),
      budget_mode: props.card.budget_mode || (props.card.is_support ? 'support' : 'hours_and_amount'),
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

function getOperationTypeLabel(value?: string | null) {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'income') {
    return 'Поступление'
  }
  if (normalized === 'expense') {
    return 'Расход'
  }
  return value || 'Операция'
}
</script>

<template>
  <div
    v-if="modelValue && card"
    class="fixed inset-0 z-[9999] flex justify-end bg-slate-900/40 backdrop-blur-sm"
    @click="closeDrawer"
  >
    <aside
      class="flex h-full w-full max-w-[460px] flex-col border-l border-slate-200 bg-white shadow-2xl"
      @click.stop
    >
      <div class="border-b border-slate-200 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="truncate text-lg font-semibold text-slate-900">{{ card.project_name }}</div>
            <div class="mt-2 flex flex-wrap gap-2">
              <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', stageBadgeClass]">
                {{ card.stage }}
              </span>
              <span
                v-if="card.stage_source === 'auto' && card.manual_stage && card.manual_stage !== card.stage"
                class="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700"
              >
                Базовая стадия SPA: {{ card.manual_stage }}
              </span>
            </div>
          </div>

          <button
            type="button"
            class="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            @click="closeDrawer"
          >
            ✕
          </button>
        </div>
      </div>

      <div class="flex-1 space-y-5 overflow-y-auto px-5 py-5">
        <div class="rounded-2xl bg-slate-50 p-4 text-xs text-slate-600">
          Стадия проекта меняется перетаскиванием между колонками.
          Автоматические статусы выставляются по последним списаниям.
        </div>

        <div class="rounded-2xl border border-slate-200 p-4 text-sm">
          <div class="flex items-center justify-between gap-3">
            <div class="font-medium text-slate-800">Бюджет проекта</div>
            <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', budgetBadgeClass]">
              {{ card.budget_health_status || 'Без лимита' }}
            </span>
          </div>
          <div class="mt-3 grid grid-cols-2 gap-3 text-xs">
            <div class="rounded-xl bg-slate-50 px-3 py-2">
              <div class="text-slate-400">План, часы</div>
              <div class="mt-1 font-semibold text-slate-800">{{ formatProjectHours(card.planned_hours ?? card.project_hours_budget) }}</div>
            </div>
            <div class="rounded-xl bg-slate-50 px-3 py-2">
              <div class="text-slate-400">Факт, часы</div>
              <div class="mt-1 font-semibold text-slate-800">{{ formatProjectHours(card.actual_hours) }}</div>
            </div>
            <div class="rounded-xl bg-slate-50 px-3 py-2">
              <div class="text-slate-400">План, ₽</div>
              <div class="mt-1 font-semibold text-slate-800">{{ formatProjectCurrency(card.planned_amount ?? card.planned_budget_amount) }}</div>
            </div>
            <div class="rounded-xl bg-slate-50 px-3 py-2">
              <div class="text-slate-400">Факт, ₽</div>
              <div class="mt-1 font-semibold text-slate-800">{{ formatProjectCurrency(card.actual_cost_amount) }}</div>
            </div>
          </div>
          <div class="mt-3 grid grid-cols-2 gap-3 text-xs">
            <div class="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2">
              <span class="text-slate-400">Остаток, ч</span>
              <span class="font-semibold text-slate-800">{{ formatProjectHours(card.hours_remaining) }}</span>
            </div>
            <div class="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2">
              <span class="text-slate-400">Остаток, ₽</span>
              <span class="font-semibold text-slate-800">{{ formatProjectCurrency(card.budget_remaining) }}</span>
            </div>
          </div>
          <div v-if="!isSupportCard" class="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <div class="flex items-center justify-between gap-2">
              <span>Освоение бюджета</span>
              <span class="font-semibold text-slate-800">{{ formatProjectPercent(card.budget_utilization_percent) }}</span>
            </div>
            <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                class="h-full rounded-full bg-emerald-500 transition-all"
                :class="{
                  'bg-amber-500': card.budget_health_status === 'Риск',
                  'bg-rose-500': card.budget_health_status === 'Перерасход',
                  'bg-slate-400': card.budget_health_status === 'Без лимита',
                }"
                :style="{ width: `${budgetProgressPercent}%` }"
              />
            </div>
            <div v-if="card.budget_health_reason" class="mt-2 text-[11px] text-slate-500">
              {{ card.budget_health_reason }}
            </div>
          </div>
          <div v-else class="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <div class="flex items-center justify-between gap-2">
              <span>Финрезультат поддержки</span>
              <span class="font-semibold text-slate-800">{{ formatProjectCurrency(card.actual_financial_result) }}</span>
            </div>
            <div v-if="card.budget_health_reason" class="mt-2 text-[11px] text-slate-500">
              {{ card.budget_health_reason }}
            </div>
          </div>
        </div>

        <div class="grid gap-4">
          <label class="grid gap-1 text-sm">
            <span class="font-medium text-slate-700">Название проекта</span>
            <input
              v-model="draft.project_name"
              type="text"
            >
          </label>

          <div class="grid grid-cols-2 gap-4">
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Бюджет, часы</span>
              <input
                v-model="draft.project_hours_budget"
                type="number"
                min="0"
                step="0.5"
              >
            </label>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Плановый бюджет, ₽</span>
              <input
                v-model="draft.planned_budget_amount"
                type="number"
                min="0"
                step="1000"
              >
            </label>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Ставка</span>
              <input
                v-model="draft.hourly_rate"
                type="number"
                min="0"
                step="100"
              >
            </label>
          </div>

          <label class="flex items-center justify-between rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <span class="font-medium text-slate-700">Проект на поддержке</span>
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
              <span class="font-medium text-slate-700">Дата старта</span>
              <input
                v-model="draft.project_start_date"
                type="date"
              >
            </label>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Дата завершения</span>
              <input
                v-model="draft.project_end_date"
                type="date"
              >
            </label>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
          <div class="font-medium text-slate-800">Текущие данные</div>
          <div class="mt-3 grid gap-2 text-xs">
            <div class="flex items-center justify-between gap-3">
              <span class="text-slate-400">Последнее списание</span>
              <span class="font-medium text-slate-700">
                {{ card.last_writeoff_at ? formatProjectDate(card.last_writeoff_at) : 'Нет данных' }}
              </span>
            </div>
            <div class="flex items-center justify-between gap-3">
              <span class="text-slate-400">Дней без списаний</span>
              <span class="font-medium text-slate-700">{{ card.last_writeoff_days || 0 }}</span>
            </div>
            <div class="flex items-center justify-between gap-3">
              <span class="text-slate-400">Архив</span>
              <span class="font-medium text-slate-700">{{ card.is_archived ? 'Да' : 'Нет' }}</span>
            </div>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
          <div class="font-medium text-slate-800">Последние финоперации</div>
          <div v-if="!card.recent_finance_operations?.length" class="mt-2 text-xs text-slate-500">
            Финоперации пока не отражены.
          </div>
          <div v-else class="mt-3 space-y-2 text-xs">
            <div
              v-for="operation in card.recent_finance_operations"
              :key="`${operation.id || operation.operation_date || ''}-${operation.amount || 0}`"
              class="rounded-xl border border-slate-200 bg-white px-3 py-2"
            >
              <div class="flex items-center justify-between gap-3">
                <span
                  class="inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold"
                  :class="operation.operation_type === 'expense' ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'"
                >
                  {{ getOperationTypeLabel(operation.operation_type) }}
                </span>
                <span class="font-semibold text-slate-800">
                  {{ formatProjectCurrency(operation.amount) }}
                </span>
              </div>
              <div class="mt-1 flex items-center justify-between gap-3 text-[11px] text-slate-500">
                <span>{{ operation.operation_date ? formatProjectDate(operation.operation_date) : '—' }}</span>
                <span>{{ operation.currency || 'RUB' }}</span>
              </div>
              <div v-if="operation.comment" class="mt-1 truncate text-[11px] text-slate-500">
                {{ operation.comment }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="border-t border-slate-200 px-5 py-4">
        <div class="flex flex-wrap gap-2">
          <B24Button label="Сохранить" color="success" :loading="isSaving" @click="handleSave" />
          <B24Button label="Открыть проект" color="default" @click="emit('open-project', card)" />
          <B24Button label="Открыть SPA" color="default" @click="emit('open-spa', card)" />
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
