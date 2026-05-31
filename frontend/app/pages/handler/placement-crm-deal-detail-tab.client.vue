<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { FinanceOperationRecord } from '~/stores/api'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import { formatProjectCurrency, formatProjectDate } from '~/utils/projectBoard'
import { openCrmItemCard } from '~/utils/openCrmItem'
import { requestIframeAutoHeight } from '~/utils/iframe-resizer'

definePageMeta({
  layout: 'placement'
})

const { locales: localesI18n, setLocale } = useI18n()
const { initApp, b24Helper, destroyB24Helper, processErrorGlobal } = useAppInit('crm_deal_finance_tab')
const { $initializeB24Frame } = useNuxtApp()
const apiStore = useApiStore()

let $b24: null | B24Frame = null

// --- Финансовый функционал (в планах) изолирован ---
// Бэкенд-эндпоинты finance отключены (см. backends/python/api/main/urls.py).
// Пока флаг === false, страница не делает finance-вызовов и показывает заглушку «в разработке».
// Для восстановления: выставить FINANCE_FEATURE_ENABLED = true (и вернуть регистрацию встройки в install.client.vue).
const FINANCE_FEATURE_ENABLED = false

const isInit = ref(false)
const isLoading = ref(false)
const isSaving = ref(false)
const projectSpaEntityTypeId = ref(0)
const dealId = ref('')
const operations = ref<FinanceOperationRecord[]>([])
const projectCards = ref<ProjectBoardCardRecord[]>([])
const statusMessage = ref<{ type: 'success' | 'warning' | 'error', text: string } | null>(null)

const form = ref({
  project_item_id: '',
  operation_type: 'income',
  amount: null as number | null,
  operation_date: new Date().toISOString().slice(0, 10),
  currency: 'RUB',
  comment: ''
})

const activeProjectOptions = computed(() =>
  projectCards.value
    .filter(card => !card.is_archived && String(card.project_item_id || '').trim().length > 0)
    .map(card => ({
      project_id: card.project_id,
      project_item_id: String(card.project_item_id || ''),
      label: `${card.project_name} (#${card.project_id})`,
      budget_status: card.budget_health_status,
    }))
)

const selectedProject = computed(() =>
  projectCards.value.find(card => String(card.project_item_id || '') === form.value.project_item_id) || null
)

const canSave = computed(() =>
  Boolean(
    form.value.project_item_id
    && form.value.operation_type
    && Number(form.value.amount || 0) > 0
    && form.value.operation_date
  )
)

const statusClass = computed(() => {
  if (!statusMessage.value) {
    return ''
  }
  if (statusMessage.value.type === 'success') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }
  if (statusMessage.value.type === 'warning') {
    return 'border-amber-200 bg-amber-50 text-amber-700'
  }
  return 'border-rose-200 bg-rose-50 text-rose-700'
})

function showStatus(type: 'success' | 'warning' | 'error', text: string) {
  statusMessage.value = { type, text }
  void fitIframeHeight()
}

function getOperationTypeLabel(value?: string | null) {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'expense') {
    return 'Расход'
  }
  if (normalized === 'income') {
    return 'Поступление'
  }
  return value || 'Операция'
}

function extractDealIdFromPlacement(frame: B24Frame | null): string {
  const candidateKeys = ['ID', 'id', 'DEAL_ID', 'deal_id', 'ENTITY_VALUE_ID', 'entityValueId', 'ENTITY_ID', 'entityId']
  const options = (frame as any)?.placement?.options || {}
  for (const key of candidateKeys) {
    const value = String(options?.[key] || '').trim()
    if (value) {
      return value
    }
  }

  try {
    const info = (window as any)?.BX24?.placement?.info?.()
    const infoOptions = info?.options || {}
    for (const key of candidateKeys) {
      const value = String(infoOptions?.[key] || info?.[key] || '').trim()
      if (value) {
        return value
      }
    }
  } catch (error) {
    console.warn('[DealFinanceTab] Failed to read BX24 placement info', error)
  }

  return ''
}

async function loadProjects() {
  const board = await apiStore.getProjectBoard(false)
  projectCards.value = board.cards || []
  await fitIframeHeight()
}

async function loadOperations() {
  const response = await apiStore.getFinanceOperations({
    deal_id: dealId.value || null,
    limit: 30,
  })
  operations.value = response.operations || []
  await fitIframeHeight()
}

async function fitIframeHeight() {
  await nextTick()
  requestIframeAutoHeight()
  setTimeout(() => requestIframeAutoHeight(), 120)
}

async function saveOperation() {
  if (!canSave.value) {
    showStatus('warning', 'Заполните проект, тип операции, сумму и дату.')
    return
  }

  isSaving.value = true
  try {
    const response = await apiStore.createFinanceOperation({
      project_item_id: form.value.project_item_id,
      deal_id: dealId.value || null,
      operation_type: form.value.operation_type,
      amount: Number(form.value.amount || 0),
      operation_date: form.value.operation_date,
      currency: form.value.currency || 'RUB',
      comment: form.value.comment || null,
      source: dealId.value ? 'deal_embed' : 'manual',
    })

    await Promise.all([
      loadOperations(),
      apiStore.getProjectBoard(true).then(board => { projectCards.value = board.cards || [] }),
    ])

    if (response.status === 'duplicate') {
      showStatus('warning', 'Операция уже существует (идемпотентная защита).')
    } else {
      showStatus('success', 'Операция сохранена.')
    }

    form.value.amount = null
    form.value.comment = ''
  } catch (error) {
    processErrorGlobal(error)
    showStatus('error', 'Не удалось сохранить финансовую операцию.')
  } finally {
    isSaving.value = false
    await fitIframeHeight()
  }
}

function openSelectedProjectSpa() {
  const entityTypeId = Number(projectSpaEntityTypeId.value || 0)
  if (!entityTypeId || !form.value.project_item_id) {
    showStatus('warning', 'Невозможно открыть карточку SPA: не задана привязка проекта.')
    return
  }
  openCrmItemCard(entityTypeId, form.value.project_item_id)
}

onMounted(async () => {
  isLoading.value = true
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)

    // --- Финансовый функционал (в планах) изолирован ---
    // Не выполняем finance-вызовы к отключённым эндпоинтам — показываем заглушку
    // (рендерится по `v-if="!FINANCE_FEATURE_ENABLED"`).
    if (!FINANCE_FEATURE_ENABLED) {
      isInit.value = true
      await fitIframeHeight()
      return
    }

    dealId.value = extractDealIdFromPlacement($b24)
    const configuration = await apiStore.getConfiguration()
    projectSpaEntityTypeId.value = Number(configuration?.project_sp_entity_type_id || 0)

    await Promise.all([
      loadProjects(),
      loadOperations(),
    ])
    isInit.value = true
    await fitIframeHeight()
  } catch (error) {
    processErrorGlobal(error)
    showStatus('error', 'Не удалось инициализировать встройку.')
  } finally {
    isLoading.value = false
    await fitIframeHeight()
  }
})

onUnmounted(() => {
  if (b24Helper.value) {
    destroyB24Helper()
  }
})
</script>

<template>
  <div class="space-y-4">
    <!-- --- Финансовый функционал (в планах) изолирован: заглушка «в разработке» (битых finance-вызовов нет) --- -->
    <B24Card v-if="!FINANCE_FEATURE_ENABLED" title="Финансы проекта" variant="line">
      <template #body>
        <div class="py-6 text-sm">
          <p class="font-semibold text-slate-800">Функционал в разработке</p>
          <p class="mt-1 text-slate-500">
            Финансовые операции по сделке появятся в одном из ближайших обновлений. Раздел временно недоступен.
          </p>
        </div>
      </template>
    </B24Card>

    <template v-else>
    <B24Card title="Финоперации по сделке" variant="line">
      <template #body>
        <div v-if="isLoading && !isInit" class="py-6 text-sm text-slate-500">
          Загрузка данных...
        </div>

        <div v-else class="space-y-4">
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div class="rounded-xl border border-slate-200 px-3 py-2">
              <div class="text-[11px] text-slate-500">ID сделки</div>
              <div class="text-sm font-semibold text-slate-800">{{ dealId || 'Не определен' }}</div>
            </div>
            <div class="rounded-xl border border-slate-200 px-3 py-2">
              <div class="text-[11px] text-slate-500">Проект</div>
              <select v-model="form.project_item_id" class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm">
                <option value="">Выберите проект</option>
                <option
                  v-for="option in activeProjectOptions"
                  :key="`project-${option.project_item_id}`"
                  :value="option.project_item_id"
                >
                  {{ option.label }}
                </option>
              </select>
              <div v-if="activeProjectOptions.length === 0" class="mt-1 text-[11px] text-amber-600">
                Нет активных проектов с привязкой `project_item_id`. Проверьте синхронизацию Project SPA.
              </div>
            </div>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-4">
            <label class="grid gap-1 text-sm">
              <span class="text-[11px] text-slate-500">Тип</span>
              <select v-model="form.operation_type" class="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm">
                <option value="income">Поступление</option>
                <option value="expense">Расход</option>
              </select>
            </label>

            <label class="grid gap-1 text-sm">
              <span class="text-[11px] text-slate-500">Сумма</span>
              <input
                v-model.number="form.amount"
                type="number"
                min="0"
                step="0.01"
                class="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
              >
            </label>

            <label class="grid gap-1 text-sm">
              <span class="text-[11px] text-slate-500">Валюта</span>
              <input
                v-model="form.currency"
                type="text"
                maxlength="3"
                class="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm uppercase"
              >
            </label>

            <label class="grid gap-1 text-sm">
              <span class="text-[11px] text-slate-500">Дата</span>
              <input
                v-model="form.operation_date"
                type="date"
                class="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
              >
            </label>
          </div>

          <label class="grid gap-1 text-sm">
            <span class="text-[11px] text-slate-500">Комментарий</span>
            <textarea
              v-model="form.comment"
              rows="2"
              class="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
              placeholder="Причина или описание операции"
            />
          </label>

          <div
            v-if="selectedProject"
            class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
          >
            <div class="flex items-center justify-between gap-2">
              <span>Статус бюджета проекта</span>
              <span class="font-semibold text-slate-800">{{ selectedProject.budget_health_status || '—' }}</span>
            </div>
            <div class="mt-1 flex items-center justify-between gap-2">
              <span>Факт затрат</span>
              <span class="font-semibold text-slate-800">{{ formatProjectCurrency(selectedProject.actual_cost_amount) }}</span>
            </div>
          </div>

          <div v-if="statusMessage" :class="['rounded-xl border px-3 py-2 text-sm', statusClass]">
            {{ statusMessage.text }}
          </div>

          <div class="flex flex-wrap gap-2">
            <B24Button
              color="success"
              label="Сохранить операцию"
              :loading="isSaving"
              :disabled="!canSave"
              @click="saveOperation"
            />
            <B24Button
              color="default"
              label="Открыть проект SPA"
              :disabled="!form.project_item_id"
              @click="openSelectedProjectSpa"
            />
          </div>
        </div>
      </template>
    </B24Card>

    <B24Card title="Последние операции сделки" variant="line">
      <template #body>
        <div v-if="operations.length === 0" class="py-4 text-sm text-slate-500">
          По текущей сделке операций пока нет.
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="operation in operations"
            :key="`${operation.id || operation.operation_date || ''}-${operation.amount || 0}`"
            class="rounded-xl border border-slate-200 px-3 py-2"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span
                  class="inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold"
                  :class="operation.operation_type === 'expense' ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'"
                >
                  {{ getOperationTypeLabel(operation.operation_type) }}
                </span>
                <span class="text-xs text-slate-500">{{ operation.operation_date ? formatProjectDate(operation.operation_date) : '—' }}</span>
              </div>
              <span class="font-semibold text-slate-800">{{ formatProjectCurrency(operation.amount) }}</span>
            </div>
            <div class="mt-1 text-xs text-slate-500">
              Проект item: {{ operation.project_item_id || '—' }} | Валюта: {{ operation.currency || 'RUB' }}
            </div>
            <div v-if="operation.comment" class="mt-1 text-xs text-slate-500">
              {{ operation.comment }}
            </div>
          </div>
        </div>
      </template>
    </B24Card>
    </template>
  </div>
</template>
