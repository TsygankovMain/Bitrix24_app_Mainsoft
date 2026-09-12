<script setup lang="ts">
/**
 * Бюджет проекта: показатели, прогноз, последние операции.
 *
 * В макете это ЧЕТВЁРТАЯ ВКЛАДКА карточки проекта, и так и будет: карточка
 * проекта живёт в дровере доски (components/projects/ProjectBoardDrawer.vue)
 * и открывается поверх доски, а не отдельным адресом. Отдельная страница
 * нужна независимо от вкладки, и вот зачем:
 *  - на неё ведёт ссылка из уведомления о риске и перерасходе (её строит
 *    project_budget_notifier), а уведомление обязано открывать конкретный
 *    проект, а не доску;
 *  - по ней открывается проект из реестра, и адрес можно переслать.
 *
 * Вкладка в дровере на этап 1 не добавлена сознательно: там четыре вкладки
 * уже про карточку проекта, а пятая со своим запросом к серверу — это
 * правка общего для доски компонента, которую сейчас параллельно правит
 * другая задача. Ссылка «Бюджет проекта» из панели реестра эту работу
 * закрывает, а вкладка встанет на этап 2, когда появятся статьи и её
 * содержимое перестанет повторять этот экран.
 *
 * Расчётов в компоненте нет: всё в app/utils/bddsRegistry.ts и
 * app/utils/bddsOperations.ts.
 *
 * БЛОК «ОПЕРАЦИИ» — то, чего в приложении не было вовсе. Серверные ручки
 * операций (GET /api/finance-operations, POST .../create) включены ещё на
 * этапе 1, но звала их только вкладка сделки, выключенная флагом и не
 * регистрируемая при установке. То есть поступления и списания по проектам
 * считались в бюджете, а завести или посмотреть их человек не мог нигде.
 * Здесь они появляются: список постранично, форма добавления и показ того,
 * как операция сказалась на бюджете.
 *
 * Три состояния блока различаются намеренно и по-разному:
 *  - смарт-процесс операций не настроен (сервер отвечает 409
 *    finance_spa_not_configured) — отказ со ссылкой в настройки. Пустой
 *    список здесь был бы ложью: он читается как «операций нет»;
 *  - операций нет — рабочее состояние с объяснением, откуда они берутся;
 *  - права. Смотреть операции может любой, у кого открыт раздел; заводить —
 *    администратор портала или «Бухгалтерия» из настроек, тот же список,
 *    что выставляет счета (гейт на сервере — bdds_operations_manager_required).
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import BddsGate from '~/components/finance/BddsGate.vue'
import { describeBddsError, type BddsErrorView } from '~/utils/bddsErrors'
import {
  BDDS_FORECAST_METHOD_HINT,
  bddsBarPercent,
  bddsProjectSubtitle,
  bddsStatusTone,
  describeBddsForecast,
  describeBddsNoBudget,
  describeBddsRateGap,
  formatBddsRemaining,
  type BddsStatusTone,
} from '~/utils/bddsRegistry'
import {
  formatProjectCurrency,
  formatProjectDate,
  formatProjectHours,
  formatProjectPercent,
  getBudgetStatusBadgeClass,
} from '~/utils/projectBoard'
import { buildBoardUtilization, formatBoardActivity } from '~/utils/projectBoardView'
import BddsOperationForm from '~/components/finance/BddsOperationForm.vue'
import BddsOperationsTable from '~/components/finance/BddsOperationsTable.vue'
import {
  BDDS_OPERATIONS_PAGE_SIZE,
  BDDS_OPERATIONS_SETTINGS_PATH,

  describeBddsBudgetImpact,
  describeBddsOperationDuplicate,
  describeBddsOperationFormBlock,
  describeBddsOperationsEmpty,
  formatBddsOperationAmount,
  formatBddsOperationDelta,
  normalizeBddsOperation,
  parseBddsOperationsPage,
  sumBddsOperations,
  type BddsOperationRow,
} from '~/utils/bddsOperations'
import type { BddsOperationCreatePayload, BddsProjectRecord } from '~/types/bdds'

const route = useRoute()
const router = useRouter()
const apiStore = useApiStore()
const { access } = useBddsFeature()

/**
 * Кто может ЗАВОДИТЬ операции.
 *
 * Тот же список, что выставляет счета: администратор портала или
 * «Бухгалтерия» из настроек приложения (isBillingManager). Своего списка у
 * БДДС не заводится сознательно — операция попадает в финансовый результат
 * проекта ровно так же, как счёт, а второй перечень тех же людей
 * гарантированно разойдётся с первым и заставит клиента заполнять две
 * настройки вместо одной. Настоящая охрана — на сервере
 * (bdds_operations_manager_required); здесь забота о человеке: не показывать
 * форму, которую сервер всё равно отклонит.
 */
const { isManager, loadBillingSettings } = useBillingFeature()

const { initApp, processErrorGlobal } = useAppInit('BddsProjectPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const TONE_TEXT: Record<BddsStatusTone, string> = {
  ok: 'text-emerald-700',
  warning: 'text-amber-700',
  danger: 'text-rose-700',
  neutral: 'text-slate-700',
}

const TONE_BAR: Record<BddsStatusTone, string> = {
  ok: 'bg-emerald-500',
  warning: 'bg-amber-500',
  danger: 'bg-rose-500',
  neutral: 'bg-slate-300',
}

const isReady = ref(false)
const isLoading = ref(false)
const error = ref<BddsErrorView | null>(null)
const project = ref<BddsProjectRecord | null>(null)

// --- Операции ---
const operationRows = ref<BddsOperationRow[]>([])
const operationsLoading = ref(false)
const operationsError = ref<BddsErrorView | null>(null)
const operationsHasMore = ref(false)
const operationsTruncated = ref(false)
const operationsEntityTypeId = ref<number | null>(null)
const authorNames = ref<Record<string, string>>({})
const formOpen = ref(false)
const formSaving = ref(false)
const formServerError = ref('')
const impact = ref<ReturnType<typeof describeBddsBudgetImpact>>(null)
const impactNotice = ref('')

const projectId = computed(() => {
  const raw = Array.isArray(route.params.projectId) ? route.params.projectId[0] : route.params.projectId
  return String(raw || '').trim()
})

async function loadProject() {
  if (!access.value.enabled || !projectId.value) {
    return
  }

  isLoading.value = true
  error.value = null

  try {
    const response = await apiStore.getBddsProject(projectId.value)
    project.value = response.project
  } catch (e) {
    error.value = describeBddsError(e)
    project.value = null
  } finally {
    isLoading.value = false
  }
}

/** project_item_id: операции привязаны к элементу СП, а не к project_id. */
const projectItemId = computed(() => String(project.value?.project_item_id || '').trim())

/**
 * Страница операций.
 *
 * `append` отличает «Показать ещё» от первой загрузки: дописать страницу и
 * перерисовать список — разные вещи, и путать их значит либо терять
 * прокрутку, либо копить дубли строк.
 */
async function loadOperations(options: { append?: boolean } = {}) {
  if (!access.value.enabled || !projectItemId.value) {
    operationRows.value = []
    operationsHasMore.value = false
    return
  }

  const append = Boolean(options.append)
  operationsLoading.value = true
  if (!append) {
    operationsError.value = null
  }

  try {
    const response = await apiStore.getFinanceOperations({
      project_item_id: projectItemId.value,
      limit: BDDS_OPERATIONS_PAGE_SIZE,
      offset: append ? operationRows.value.length : 0,
    })
    const page = parseBddsOperationsPage(response)

    operationRows.value = append ? [...operationRows.value, ...page.rows] : page.rows
    operationsHasMore.value = page.hasMore
    operationsTruncated.value = page.truncated
    operationsEntityTypeId.value = page.entityTypeId
    operationsError.value = null
    await loadAuthorNames()
  } catch (e) {
    operationsError.value = describeBddsError(e)
    if (!append) {
      operationRows.value = []
      operationsHasMore.value = false
    }
  } finally {
    operationsLoading.value = false
  }
}

/**
 * Имена авторов операций.
 *
 * Справочник спрашиваем ОДИН раз на экран и только когда есть кого
 * называть. Страница справочника ограничена сервером (лимит 200), поэтому
 * отсутствующее имя рисуется как «сотрудник #id», а не как пустая ячейка:
 * по id человека находят в портале, по пустоте — нет.
 */
async function loadAuthorNames() {
  const needed = operationRows.value.some(row => row.authorId && !authorNames.value[row.authorId])
  if (!needed || Object.keys(authorNames.value).length > 0) {
    return
  }

  try {
    const response = await apiStore.getUsers(1, 200, false)
    const map: Record<string, string> = {}
    for (const item of response.items || []) {
      map[String(item.id)] = [item.last_name, item.name].filter(Boolean).join(' ').trim()
    }
    authorNames.value = map
  } catch {
    // Справочник — украшение списка, а не его условие: без имён показываем id.
    authorNames.value = {}
  }
}

/**
 * Сохранение операции и пересчёт бюджета.
 *
 * Бюджет НЕ считается на клиенте: перечитываем карточку проекта у сервера и
 * сравниваем снимок до и после. Любая своя формула здесь была бы вторым
 * ответом на вопрос, на который уже отвечает project_budget_service, — и
 * однажды разошлась бы с ним.
 */
async function saveOperation(payload: BddsOperationCreatePayload) {
  formSaving.value = true
  formServerError.value = ''
  impact.value = null
  impactNotice.value = ''

  const before = project.value

  try {
    const result = await apiStore.createFinanceOperation(payload)

    if (result.status === 'duplicate') {
      impactNotice.value = describeBddsOperationDuplicate(
        result.operation ? normalizeBddsOperation(result.operation) : null
      )
    } else {
      impactNotice.value = 'Операция записана в смарт-процесс портала.'
      formOpen.value = false
    }

    await loadProject()
    await loadOperations()
    impact.value = describeBddsBudgetImpact(before, project.value)
  } catch (e) {
    formServerError.value = [describeBddsError(e).title, describeBddsError(e).hint]
      .filter(Boolean)
      .join(' ')
  } finally {
    formSaving.value = false
  }
}

const forecast = computed(() => project.value ? describeBddsForecast(project.value) : null)
const rateGap = computed(() => project.value ? describeBddsRateGap(project.value) : null)
const utilization = computed(() => project.value ? buildBoardUtilization(project.value) : null)

/** Шесть показателей, как в макете. Тексты — здесь, расчёты — на сервере. */
const kpis = computed(() => {
  const row = project.value
  if (!row) {
    return []
  }

  return [
    {
      id: 'plan',
      label: 'Бюджет проекта, ₽',
      value: row.has_budget ? formatProjectCurrency(row.planned_amount) : 'без лимита',
      hint: row.has_budget
        ? `освоено ${formatProjectPercent(row.budget_utilization_percent)}`
        : describeBddsNoBudget(row),
      tone: 'neutral' as BddsStatusTone,
      source: 'расчёт',
    },
    {
      id: 'fact',
      label: 'Факт выбытий, ₽',
      value: formatProjectCurrency(row.actual_cost_amount),
      hint: `остаток ${formatBddsRemaining(row)}`,
      tone: 'neutral' as BddsStatusTone,
      source: 'списания',
    },
    {
      id: 'hours',
      label: 'Часы',
      value: formatProjectHours(row.actual_hours),
      hint: row.planned_hours === null
        ? 'без лимита'
        : `план ${formatProjectHours(row.planned_hours)} · остаток ${formatProjectHours(row.hours_remaining)}`,
      tone: 'neutral' as BddsStatusTone,
      source: 'списания',
    },
    {
      id: 'income',
      label: 'Поступления, ₽',
      value: formatProjectCurrency(row.actual_income_amount),
      hint: `внешние платежи ${formatProjectCurrency(row.actual_expense_amount)}`,
      tone: 'neutral' as BddsStatusTone,
      source: 'операции',
    },
    {
      id: 'financial-result',
      label: 'Финрезультат, ₽',
      value: formatProjectCurrency(row.actual_financial_result),
      hint: row.actual_financial_result < 0 ? 'минус' : 'плюс',
      tone: (row.actual_financial_result < 0 ? 'danger' : 'ok') as BddsStatusTone,
      source: 'операции',
    },
    {
      id: 'forecast',
      label: 'Прогноз выбытий, ₽',
      value: forecast.value?.value || '—',
      hint: forecast.value?.deviation || forecast.value?.explanation || '',
      tone: forecast.value?.tone || ('neutral' as BddsStatusTone),
      source: 'расчёт',
    },
  ]
})

/** Смарт-процесс не настроен — это отдельное состояние, а не пустой список. */
const operationsNotConfigured = computed(() => Boolean(operationsError.value?.isSmartProcessMissing))

/** Прочие отказы списка операций — обычной плашкой над таблицей. */
const operationsOtherError = computed(
  () => operationsError.value && !operationsError.value.isSmartProcessMissing
    ? operationsError.value
    : null
)

/** Сумма ЗАГРУЖЕННЫХ операций. Подписана в шаблоне именно так. */
const loadedTotals = computed(() => sumBddsOperations(operationRows.value))

const operationsEmptyText = computed(() => describeBddsOperationsEmpty({
  filtersActive: 0,
  scope: 'project',
}))

const canCreateOperation = computed(() => Boolean(isManager.value))

const formBlockReason = computed(() => describeBddsOperationFormBlock({
  projectItemId: projectItemId.value,
  canCreate: canCreateOperation.value,
}))

function openAllOperations() {
  const query = projectItemId.value ? `?project=${encodeURIComponent(projectItemId.value)}` : ''
  void router.push(`/finance/bdds/operations${query}`)
}

function openFieldSettings() {
  void router.push(BDDS_OPERATIONS_SETTINGS_PATH)
}

useHead({
  title: computed(() => project.value
    ? `${project.value.project_name} — бюджет проекта`
    : 'Бюджет проекта'),
})

watch(() => access.value.enabled, (enabled) => {
  if (enabled && isReady.value) {
    void loadProject().then(() => loadOperations())
  }
})

/** Смена проекта в адресе — новая загрузка: страница одна на все проекты. */
watch(projectId, () => {
  if (isReady.value) {
    formOpen.value = false
    impact.value = null
    impactNotice.value = ''
    void loadProject().then(() => loadOperations())
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

  // Настройки «Бухгалтерии» нужны, чтобы решить, показывать ли форму.
  // Отказ этого запроса не должен мешать чтению операций: без него человек
  // считается не-менеджером, и форма просто не появится.
  void loadBillingSettings()

  await loadProject()
  await loadOperations()
})
</script>

<template>
  <BddsGate
    :title="project?.project_name || 'Бюджет проекта'"
    :description="project ? bddsProjectSubtitle(project) : 'Показатели бюджета одного проекта'"
  >
    <template #actions>
      <B24Button label="Обновить" color="default" :loading="isLoading" @click="loadProject" />
      <B24Button label="К реестру" color="link" @click="router.push('/finance/bdds')" />
    </template>

    <div v-if="error" class="ms-note ms-note-danger">
      <p class="font-medium">{{ error.title }}</p>
      <p v-if="error.hint" class="mt-1 text-sm">{{ error.hint }}</p>
    </div>

    <div v-if="isLoading" class="ms-surface ms-empty-state">Загрузка…</div>

    <template v-else-if="project">
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <div v-for="kpi in kpis" :key="kpi.id" class="ms-surface flex flex-col gap-1 p-4">
          <div class="flex items-center gap-2 text-xs text-slate-500">
            <span>{{ kpi.label }}</span>
            <span class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
              {{ kpi.source }}
            </span>
          </div>
          <div class="text-xl font-semibold" :class="TONE_TEXT[kpi.tone]">{{ kpi.value }}</div>
          <div class="text-xs text-slate-500">{{ kpi.hint }}</div>
        </div>
      </section>

      <section class="ms-surface flex flex-col gap-3 p-5">
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="rounded-full px-2 py-0.5 text-xs font-medium"
            :class="getBudgetStatusBadgeClass(project.budget_health_status)"
          >
            {{ project.budget_health_status }}
          </span>
          <span v-if="project.is_support" class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            поддержка
          </span>
          <span class="text-xs text-slate-500">{{ project.budget_health_reason }}</span>
        </div>

        <div v-if="project.has_budget && utilization">
          <div class="flex items-center gap-2">
            <span class="h-2 grow overflow-hidden rounded-full bg-slate-100">
              <span
                class="block h-full rounded-full"
                :class="TONE_BAR[bddsStatusTone(project.budget_health_status)]"
                :style="{ width: `${bddsBarPercent(project.budget_utilization_percent)}%` }"
              />
            </span>
            <span class="text-sm text-slate-600">
              {{ formatProjectPercent(project.budget_utilization_percent) }}
            </span>
          </div>
          <p class="mt-1 text-xs text-slate-500">{{ utilization.label }}</p>
        </div>
        <p v-else class="ms-note ms-note-info text-sm">{{ describeBddsNoBudget(project) }}</p>

        <p v-if="rateGap" class="ms-note text-sm">{{ rateGap }}</p>

        <dl class="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt class="text-xs text-slate-500">Срок проекта</dt>
            <dd class="text-slate-900">
              {{ formatProjectDate(project.project_start_date) }} — {{ formatProjectDate(project.project_end_date) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-slate-500">Куратор</dt>
            <dd class="text-slate-900">{{ project.curator_name || 'Не задан' }}</dd>
          </div>
          <div>
            <dt class="text-xs text-slate-500">Последнее списание</dt>
            <dd class="text-slate-900">{{ formatBoardActivity(project) }}</dd>
          </div>
        </dl>

        <p class="text-xs text-slate-400">{{ BDDS_FORECAST_METHOD_HINT }}</p>
      </section>

      <section class="ms-surface flex flex-col gap-4 p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-base font-semibold text-slate-900">Операции</h2>
            <p class="mt-1 text-sm text-slate-500">
              Поступления и списания по проекту мимо часов: авансы, этапы договора, подрядчики,
              лицензии. Живут в смарт-процессе «Доходы-расходы» на портале — приложение их читает
              и заводит, но не хранит.
            </p>
          </div>

          <div class="flex flex-wrap items-center justify-end gap-2">
            <B24Button
              v-if="canCreateOperation && projectItemId && !operationsNotConfigured"
              :label="formOpen ? 'Свернуть форму' : 'Добавить операцию'"
              color="success"
              @click="formOpen = !formOpen"
            />
            <B24Button label="Все операции" color="link" @click="openAllOperations" />
          </div>
        </div>

        <p v-if="formBlockReason && !operationsNotConfigured" class="ms-note ms-note-info">
          {{ formBlockReason }}
        </p>

        <div v-if="formOpen" class="ms-panel-muted">
          <BddsOperationForm
            :project-item-id="projectItemId || null"
            :project-name="project.project_name"
            :saving="formSaving"
            :server-error="formServerError"
            @submit="saveOperation"
            @cancel="formOpen = false"
          />
        </div>

        <p v-if="impactNotice" class="ms-note ms-note-success">{{ impactNotice }}</p>

        <!--
          Влияние на бюджет: до -> после по ответам сервера.

          Остаток и факт затрат здесь часто «без изменений», и это не сбой:
          они считаются по списанным часам, а операция идёт в финансовый
          результат. Поясняющая строка под таблицей обязательна — иначе
          человек, добавивший расход, пойдёт искать поломку.
        -->
        <div v-if="impact" class="ms-panel-muted flex flex-col gap-2">
          <p class="text-sm font-medium text-slate-700">Как изменился бюджет проекта</p>
          <div class="ms-table-shell">
            <table class="ms-table min-w-[520px]">
              <thead>
                <tr>
                  <th>Показатель</th>
                  <th class="text-right">До</th>
                  <th class="text-right">После</th>
                  <th class="text-right">Изменение</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in impact.rows" :key="row.id">
                  <td>{{ row.label }}</td>
                  <td class="text-right">{{ formatBddsOperationAmount(row.before) }}</td>
                  <td class="text-right">{{ formatBddsOperationAmount(row.after) }}</td>
                  <td
                    class="text-right"
                    :class="row.changed ? 'font-semibold text-slate-900' : 'text-slate-400'"
                  >
                    {{ formatBddsOperationDelta(row.delta) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="impact.note" class="text-xs text-slate-500">{{ impact.note }}</p>
        </div>

        <div v-if="operationsOtherError" class="ms-note ms-note-danger">
          <p class="font-medium">{{ operationsOtherError.title }}</p>
          <p v-if="operationsOtherError.hint" class="mt-1 text-sm">{{ operationsOtherError.hint }}</p>
        </div>

        <BddsOperationsTable
          :rows="operationRows"
          :author-names="authorNames"
          :entity-type-id="operationsEntityTypeId"
          :loading="operationsLoading"
          :has-more="operationsHasMore"
          :truncated="operationsTruncated"
          :not-configured="operationsNotConfigured"
          :empty-text="operationsEmptyText"
          @load-more="loadOperations({ append: true })"
          @open-settings="openFieldSettings"
        />

        <p v-if="operationRows.length" class="text-xs text-slate-500">
          Загружено {{ loadedTotals.count }} оп.: поступления
          {{ formatBddsOperationAmount(loadedTotals.income) }}, списания
          {{ formatBddsOperationAmount(loadedTotals.expense) }}. Это сумма ПОКАЗАННЫХ строк,
          а не всей истории проекта — итоги по выборке считает реестр операций.
        </p>
      </section>
    </template>

    <div v-else-if="!error" class="ms-surface ms-empty-state">
      Проект не выбран. Откройте его из реестра «БДДС по проектам».
    </div>
  </BddsGate>
</template>
