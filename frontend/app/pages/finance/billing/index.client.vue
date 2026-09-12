<script setup lang="ts">
/**
 * Реестр выставленных документов «Счёт и акт».
 *
 * Это же и точка входа функции: пункт меню «Финансы → Счёт и акт» ведёт на
 * /finance/billing, и статический маршрут в Nuxt приоритетнее динамического
 * /finance/[feature] — то есть при включённой подписке человек попадает
 * сюда, а при выключенной BillingGate показывает ровно ту заглушку с замком,
 * что была на этом адресе раньше.
 *
 * Реестр видят ВСЕ (контракт, правило 2: чтение реестра разрешено даже при
 * выключенной подписке, и права ограничивают только запись). Кнопка
 * «Выставить» — только у админа портала и списка «Бухгалтерия».
 *
 * Ошибки показываем плашкой, а не фатальным экраном: пока бэкенд функции не
 * поднят, эта страница обязана честно сказать «сервер не знает такого
 * адреса», а не показать белый экран.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import BillingGate from '~/components/finance/BillingGate.vue'
import BillingErrorNote from '~/components/finance/BillingErrorNote.vue'
import DateRangeFilter from '~/components/common/DateRangeFilter.vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import { buildBillingRegistryQuery, createBillingRegistryFilter } from '~/utils/billingFilter'
import { describeBillingError, type BillingErrorView } from '~/utils/billingErrors'
import {
  billingDocumentNumber,
  billingStatusClass,
  billingStatusLabel,
  formatBillingDate,
  formatBillingHoursWithUnit,
  formatBillingMoney,
  formatBillingPeriod,
} from '~/utils/billingFormat'
import type { BillingDocumentPayload, BillingDocumentStatus } from '~/types/billing'

const router = useRouter()
const apiStore = useApiStore()
const { access, permissions, loadBillingSettings } = useBillingFeature()

useHead({ title: 'Счёт и акт' })

const { initApp, processErrorGlobal } = useAppInit('BillingRegistryPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const isReady = ref(false)
const isLoading = ref(false)
const error = ref<BillingErrorView | null>(null)
const documents = ref<BillingDocumentPayload[]>([])
const filter = ref(createBillingRegistryFilter())

const STATUS_OPTIONS: Array<{ id: BillingDocumentStatus | '', label: string }> = [
  { id: '', label: 'Все статусы' },
  { id: 'issued', label: 'Выставленные' },
  { id: 'cancelled', label: 'Отменённые' },
]

/** Серверный поиск компаний — тот же, что на доске проектов. */
async function searchCompanyOptions(query: string) {
  const result = await apiStore.searchCompanies(query)

  return { options: result.companies, truncated: result.truncated, failed: result.failed }
}

const companyOptions = ref<Array<{ id: string, name: string }>>([])

function rememberCompany(option: { id: string | number, name: string | number } | null) {
  if (!option) {
    companyOptions.value = []
    return
  }

  companyOptions.value = [{ id: String(option.id), name: String(option.name) }]
}

/**
 * Ответ реестра принимаем в двух написаниях — documents и items.
 *
 * Контракт не фиксирует имя коллекции в ответе GET /api/billing/documents, а
 * бэкенд пишется параллельно. Цена лишней проверки — одна строка, цена
 * несовпадения — пустой реестр при полной базе.
 */
function readDocuments(payload: { documents?: unknown, items?: unknown } | null | undefined): BillingDocumentPayload[] {
  const list = Array.isArray(payload?.documents)
    ? payload?.documents
    : Array.isArray(payload?.items) ? payload?.items : []

  return (list || []) as BillingDocumentPayload[]
}

async function loadDocuments() {
  if (!access.value.enabled) {
    return
  }

  isLoading.value = true
  error.value = null

  try {
    const response = await apiStore.getBillingDocuments(buildBillingRegistryQuery(filter.value))
    documents.value = readDocuments(response)
  } catch (e) {
    error.value = describeBillingError(e)
    documents.value = []
  } finally {
    isLoading.value = false
  }
}

function resetFilter() {
  filter.value = createBillingRegistryFilter()
  companyOptions.value = []
  void loadDocuments()
}

function openDocument(document: BillingDocumentPayload) {
  const id = String(document?.id ?? '').trim()
  if (!id) {
    return
  }

  void router.push(`/finance/billing/${id}`)
}

const hasDocuments = computed(() => documents.value.length > 0)

/**
 * Загрузка ждёт ответа о подписке.
 *
 * Спрашивать реестр раньше, чем известно состояние функции, значит гарантированно
 * получить 403 на выключенном портале и показать плашку отказа там, где нужна
 * заглушка с замком.
 */
watch(() => access.value.enabled, (enabled) => {
  if (enabled && isReady.value) {
    void loadDocuments()
  }
})

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    isReady.value = true
  } catch (e) {
    processErrorGlobal(e)
    return
  }

  // Список «Бухгалтерия» и реестр — независимы: отказ конфигурации не должен
  // прятать реестр, а отказ реестра — ломать права.
  await Promise.allSettled([loadBillingSettings(), loadDocuments()])
})
</script>

<template>
  <BillingGate
    title="Счёт и акт"
    description="Выставленные счета и акты по отражённым часам"
  >
    <template #actions>
      <B24Button
        v-if="permissions.canIssue"
        label="Выставить"
        @click="router.push('/finance/billing/new')"
      />
      <B24Button label="Обновить" color="default" :loading="isLoading" @click="loadDocuments" />
    </template>

    <template #filters>
      <div class="ms-filter-wrap flex flex-wrap items-end gap-4">
        <div class="min-w-[260px]">
          <DateRangeFilter
            :date-from="filter.dateFrom"
            :date-to="filter.dateTo"
            @update:date-from="filter.dateFrom = $event"
            @update:date-to="filter.dateTo = $event"
          />
        </div>

        <div class="min-w-[240px]">
          <label class="mb-2 block text-sm font-medium text-slate-700">Клиент</label>
          <SearchableSelect
            :model-value="filter.companyId"
            :options="companyOptions"
            empty-label="Все клиенты"
            :search-fn="searchCompanyOptions"
            @update:model-value="filter.companyId = $event"
            @update:selected="rememberCompany"
          />
        </div>

        <div class="min-w-[180px]">
          <label class="mb-2 block text-sm font-medium text-slate-700" for="billing-status">Статус</label>
          <select id="billing-status" v-model="filter.status" class="w-full">
            <option v-for="option in STATUS_OPTIONS" :key="option.id || 'all'" :value="option.id">
              {{ option.label }}
            </option>
          </select>
        </div>

        <div class="flex gap-2">
          <B24Button label="Показать" :loading="isLoading" @click="loadDocuments" />
          <B24Button label="Сбросить" color="link" @click="resetFilter" />
        </div>
      </div>
    </template>

    <BillingErrorNote :error="error" />

    <div v-if="isLoading" class="ms-surface ms-empty-state">Загрузка…</div>

    <div v-else-if="!hasDocuments && !error" class="ms-surface ms-empty-state">
      Документов по этому отбору нет.
      <template v-if="permissions.canIssue">
        Нажмите «Выставить», чтобы собрать счёт из отражённых часов.
      </template>
    </div>

    <div v-else-if="hasDocuments" class="ms-table-shell">
      <table class="ms-table">
        <thead>
          <tr>
            <th>Номер</th>
            <th>Дата</th>
            <th>Клиент</th>
            <th>Период</th>
            <th class="text-right">Часы</th>
            <th class="text-right">Сумма</th>
            <th>Статус</th>
            <th>Акт</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="document in documents"
            :key="String(document.id)"
            class="cursor-pointer"
            @click="openDocument(document)"
          >
            <td class="font-medium text-slate-900">{{ billingDocumentNumber(document) }}</td>
            <td>{{ formatBillingDate(document.created_at) }}</td>
            <td>{{ document.company_name || '—' }}</td>
            <td>{{ formatBillingPeriod(document.period_from, document.period_to) }}</td>
            <td class="text-right">{{ formatBillingHoursWithUnit(document.total_hours) }}</td>
            <td class="text-right">{{ formatBillingMoney(document.total_amount, document.currency) }}</td>
            <td>
              <span :class="['ms-pill', billingStatusClass(document.status)]">
                {{ billingStatusLabel(document.status) }}
              </span>
            </td>
            <td>{{ document.act_number || (document.act_document_id ? 'есть' : '—') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </BillingGate>
</template>
