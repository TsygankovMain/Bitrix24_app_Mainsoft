<script setup lang="ts">
/**
 * «Начисления и списания» — реестр всех операций поступлений и списаний.
 *
 * Отдельный пункт меню «Финансы» (appNavigation.ts), а не только ссылка из
 * реестра БДДС: запрос пользователя от 12.09.2026 — «нужен раздел по
 * начислению и списанию». Экран тот же, что был под адресом
 * /finance/bdds/operations; второй экран с той же таблицей не заводился.
 * Здесь же добавляется операция — той же формой, что на карточке проекта
 * (BddsOperationForm), с выбором проекта. Добавлять может право
 * operations_create ролевой модели; сервер проверяет его сам
 * (@bdds_operations_manager_required).
 *
 * ПОЧЕМУ ОТДЕЛЬНЫЙ ЭКРАН, А НЕ ТАБЛИЦА НА РЕЕСТРЕ БДДС. У этих двух
 * реестров разная единица строки. На /finance/bdds строка — проект: план,
 * факт, остаток, прогноз, статус; фильтры там про портфель (статус
 * бюджета, «только с лимитом», «прогноз выходит за план»). Здесь строка —
 * документ: дата, тип, сумма, назначение, автор; фильтры про период и тип.
 * Свести их на один экран значит поставить рядом два набора фильтров,
 * каждый из которых меняет чужую таблицу, и человек перестанет понимать,
 * что он видит. В макете это тоже разные места: портфель — экран 1,
 * операции — подвкладка карточки проекта.
 *
 * Что этот экран добавляет к блоку операций на карточке: разрез по ВСЕМ
 * проектам сразу, период и итоги по выборке. Именно за этим сюда приходят —
 * «сколько всего пришло и ушло за август», а не «что было по проекту N».
 *
 * Маршрут статический, поэтому Nuxt отдаёт приоритет ему, а не
 * /finance/bdds/[projectId]: адрес /finance/bdds/operations не будет понят
 * как проект с id «operations».
 *
 * Итоги приходят С СЕРВЕРА (totals=1) и считаются по всей выборке, а не по
 * видимой странице. Считать их на клиенте по загруженным строкам нельзя:
 * «итого» по первой странице — не итого, и человек, сложивший его с
 * бюджетом, ошибётся, не заметив этого.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import BddsGate from '~/components/finance/BddsGate.vue'
import BddsOperationForm from '~/components/finance/BddsOperationForm.vue'
import BddsOperationsTable from '~/components/finance/BddsOperationsTable.vue'
import { describeOperationsNoRights } from '~/utils/appRoles'
import { describeBddsError, type BddsErrorView } from '~/utils/bddsErrors'
import {
  BDDS_OPERATIONS_PAGE_SIZE,
  BDDS_OPERATIONS_SETTINGS_PATH,
  BDDS_OPERATION_TYPE_OPTIONS,
  DEFAULT_BDDS_OPERATION_FILTERS,
  buildBddsOperationsQuery,
  countActiveBddsOperationFilters,
  describeBddsOperationPeriodError,
  describeBddsOperationDuplicate,
  describeBddsOperationTotals,
  describeBddsOperationsEmpty,
  firstDayOfMonth,
  formatBddsOperationAmount,
  normalizeBddsOperation,
  parseBddsOperationsPage,
  toIsoDate,
  type BddsOperationFilterState,
  type BddsOperationRow,
  type BddsOperationsPage,
} from '~/utils/bddsOperations'
import type { BddsOperationCreatePayload, BddsProjectRecord } from '~/types/bdds'

const route = useRoute()
const router = useRouter()
const apiStore = useApiStore()
const { access } = useBddsFeature()
const { permissions, moneyDenied, restrictionsActive, loadPermissions } = useAppPermissions()

useHead({ title: 'Начисления и списания' })

const { initApp, processErrorGlobal } = useAppInit('BddsOperationsRegistryPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const isReady = ref(false)
const isLoading = ref(false)
const error = ref<BddsErrorView | null>(null)
const rows = ref<BddsOperationRow[]>([])
const page = ref<BddsOperationsPage | null>(null)
const filters = ref<BddsOperationFilterState>({ ...DEFAULT_BDDS_OPERATION_FILTERS })
const projects = ref<BddsProjectRecord[]>([])
const authorNames = ref<Record<string, string>>({})

/** Форма добавления: открыта ли, к какому проекту, что ответил сервер. */
const formOpen = ref(false)
const formProjectItemId = ref('')
const formSaving = ref(false)
const formServerError = ref('')
const formNotice = ref('')

/** Роль без права видеть суммы: запросы не шлём, экран объясняет (BddsGate). */
// Запись: нужны и право operations_create, и живой Pro (после окончания — только чтение).
const canCreateOperation = computed(() => Boolean(permissions.value.operations_create) && access.value.canWrite)
const noRightsText = computed(() => describeOperationsNoRights(restrictionsActive.value))
const formProjectName = computed(() => projectNames.value[formProjectItemId.value] || '')

/**
 * project_item_id -> название проекта.
 *
 * Берём из реестра БДДС, а не из отдельного справочника: это те же
 * карточки проектов, что считают бюджет, и второго их списка в приложении
 * быть не должно. Проекта без элемента СП в карте нет — у его операций и
 * не может быть привязки.
 */
const projectNames = computed(() => {
  const map: Record<string, string> = {}
  for (const project of projects.value) {
    const itemId = String(project.project_item_id || '').trim()
    if (itemId) {
      map[itemId] = project.project_name
    }
  }
  return map
})

const projectOptions = computed(() => projects.value
  .filter(project => String(project.project_item_id || '').trim())
  .map(project => ({
    id: String(project.project_item_id),
    label: project.project_name,
  })))

const activeFilters = computed(() => countActiveBddsOperationFilters(filters.value))
const periodError = computed(() => describeBddsOperationPeriodError(filters.value))
const notConfigured = computed(() => Boolean(error.value?.isSmartProcessMissing))
const otherError = computed(() => error.value && !error.value.isSmartProcessMissing ? error.value : null)

const emptyText = computed(() => describeBddsOperationsEmpty({
  filtersActive: activeFilters.value,
  scope: 'registry',
}))

const totalsHint = computed(() => page.value ? describeBddsOperationTotals(page.value) : '')

/** Сколько всего в выборке — либо честное «сервер не считал». */
const totalLabel = computed(() => {
  if (!page.value) {
    return ''
  }
  if (page.value.total === null) {
    return `Загружено ${rows.value.length} оп.`
  }
  return `Показано ${rows.value.length} из ${page.value.total} оп.`
})

async function loadProjects() {
  if (!access.value.enabled || moneyDenied.value) {
    return
  }

  try {
    const response = await apiStore.getBddsProjects()
    projects.value = response.projects || []
  } catch {
    // Названия проектов — подпись строки, а не её условие: без реестра
    // операции покажем с «элемент #id». Ронять экран из-за этого нельзя.
    projects.value = []
  }
}

async function loadOperations(options: { append?: boolean } = {}) {
  if (!access.value.enabled || moneyDenied.value) {
    return
  }
  if (periodError.value) {
    // Перевёрнутый период не отправляем вовсе: сервер честно вернёт пусто, и
    // человек прочитает это как «операций нет», а не как свою опечатку.
    return
  }

  const append = Boolean(options.append)
  isLoading.value = true
  if (!append) {
    error.value = null
  }

  try {
    const query = buildBddsOperationsQuery({
      filters: filters.value,
      offset: append ? rows.value.length : 0,
      limit: BDDS_OPERATIONS_PAGE_SIZE,
      withTotals: true,
    })
    const response = await apiStore.getFinanceOperations({
      project_item_id: query.project_item_id || null,
      date_from: query.date_from || null,
      date_to: query.date_to || null,
      operation_type: query.operation_type || null,
      limit: Number(query.limit),
      offset: Number(query.offset),
      totals: true,
    })

    const parsed = parseBddsOperationsPage(response)
    rows.value = append ? [...rows.value, ...parsed.rows] : parsed.rows
    page.value = parsed
    error.value = null
    await loadAuthorNames()
  } catch (e) {
    error.value = describeBddsError(e)
    if (!append) {
      rows.value = []
      page.value = null
    }
  } finally {
    isLoading.value = false
  }
}

/** Имена авторов — одной страницей справочника, см. карточку проекта. */
async function loadAuthorNames() {
  if (Object.keys(authorNames.value).length > 0) {
    return
  }
  if (!rows.value.some(row => row.authorId)) {
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
    authorNames.value = {}
  }
}

function applyFilters() {
  void loadOperations()
}

function resetFilters() {
  filters.value = { ...DEFAULT_BDDS_OPERATION_FILTERS }
  void loadOperations()
}

/** Пресет «этот месяц»: самый частый вопрос к реестру операций. */
function selectCurrentMonth() {
  const today = new Date()
  filters.value = {
    ...filters.value,
    dateFrom: firstDayOfMonth(today),
    dateTo: toIsoDate(today),
  }
  void loadOperations()
}

/**
 * Открыть форму. Проект подставляется из фильтра: человек, отфильтровавший
 * реестр по проекту, почти всегда добавляет операцию именно к нему.
 */
function toggleForm() {
  formOpen.value = !formOpen.value
  formServerError.value = ''
  formNotice.value = ''
  if (formOpen.value && !formProjectItemId.value) {
    formProjectItemId.value = filters.value.projectItemId || ''
  }
}

/**
 * Сохранение и перечитывание реестра с сервера: итоги по выборке считает
 * сервер, и дописывать строку в таблицу руками значило бы показать итог,
 * который с ней не сходится.
 */
async function saveOperation(payload: BddsOperationCreatePayload) {
  formSaving.value = true
  formServerError.value = ''
  formNotice.value = ''

  try {
    const result = await apiStore.createFinanceOperation(payload)
    if (result.status === 'duplicate') {
      formNotice.value = describeBddsOperationDuplicate(
        result.operation ? normalizeBddsOperation(result.operation) : null
      )
    } else {
      const projectName = formProjectName.value
      formNotice.value = projectName
        ? `Операция записана в смарт-процесс портала и привязана к проекту «${projectName}».`
        : 'Операция записана в смарт-процесс портала.'
      formOpen.value = false
    }
    await loadOperations()
  } catch (e) {
    const view = describeBddsError(e)
    formServerError.value = [view.title, view.hint].filter(Boolean).join(' ')
  } finally {
    formSaving.value = false
  }
}

function openFieldSettings() {
  void router.push(BDDS_OPERATIONS_SETTINGS_PATH)
}

watch(() => access.value.enabled, (enabled) => {
  if (enabled && isReady.value) {
    void loadProjects()
    void loadOperations()
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

  // Переход «Все операции» с карточки проекта приносит его элемент СП:
  // реестр открывается уже отфильтрованным по тому проекту, с которого
  // пришли, иначе человек теряет контекст на первом же клике.
  const requestedProject = String(route.query.project || '').trim()
  if (requestedProject) {
    filters.value = { ...filters.value, projectItemId: requestedProject }
  }

  // Права — до данных: и кнопка «Добавить», и сам доступ к суммам решаются
  // ответом сервера, а не догадкой.
  await loadPermissions()

  await loadProjects()
  await loadOperations()
})
</script>

<template>
  <BddsGate
    title="Начисления и списания"
    description="Поступления и списания по проектам мимо часов: авансы, этапы договора, подрядчики, лицензии. Элементы смарт-процесса «Доходы-расходы» портала, из которых считается финансовый результат проектов."
  >
    <template #actions>
      <B24Button
        v-if="canCreateOperation && !notConfigured"
        :label="formOpen ? 'Свернуть форму' : 'Добавить операцию'"
        color="success"
        @click="toggleForm"
      />
      <B24Button label="Обновить" color="default" :loading="isLoading" @click="loadOperations()" />
      <B24Button label="К реестру БДДС" color="link" @click="router.push('/finance/bdds')" />
    </template>

    <template #filters>
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-end gap-4">
          <div class="min-w-[240px] grow">
            <label class="mb-2 block text-sm font-medium text-slate-700" for="bdds-ops-project">Проект</label>
            <select
              id="bdds-ops-project"
              v-model="filters.projectItemId"
              class="w-full"
              @change="applyFilters"
            >
              <option value="">Все проекты</option>
              <option v-for="option in projectOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </div>

          <div class="min-w-[150px]">
            <label class="mb-2 block text-sm font-medium text-slate-700" for="bdds-ops-from">С даты</label>
            <input
              id="bdds-ops-from"
              v-model="filters.dateFrom"
              type="date"
              class="w-full"
              @change="applyFilters"
            >
          </div>

          <div class="min-w-[150px]">
            <label class="mb-2 block text-sm font-medium text-slate-700" for="bdds-ops-to">По дату</label>
            <input
              id="bdds-ops-to"
              v-model="filters.dateTo"
              type="date"
              class="w-full"
              @change="applyFilters"
            >
          </div>

          <div class="min-w-[180px]">
            <label class="mb-2 block text-sm font-medium text-slate-700" for="bdds-ops-type">Тип</label>
            <select
              id="bdds-ops-type"
              v-model="filters.type"
              class="w-full"
              @change="applyFilters"
            >
              <option value="all">Поступления и списания</option>
              <option v-for="option in BDDS_OPERATION_TYPE_OPTIONS" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </div>

          <B24Button label="Этот месяц" color="default" @click="selectCurrentMonth" />

          <B24Button
            v-if="activeFilters > 0"
            :label="`Сбросить (${activeFilters})`"
            color="link"
            @click="resetFilters"
          />
        </div>

        <p v-if="periodError" class="ms-note ms-note-danger">{{ periodError }}</p>
      </div>
    </template>

    <!--
      Форма добавления. Проект выбирается здесь же: на карточке проекта он
      задан адресом, а в общем реестре его надо указать. Проекты без элемента
      в смарт-процессе проектов в списке не показываются — операцию к ним
      привязать не к чему (сервер отказал бы).
    -->
    <section v-if="formOpen && canCreateOperation" class="ms-surface flex flex-col gap-4 p-5">
      <div class="flex flex-col gap-1">
        <label class="text-sm font-medium text-slate-700" for="bdds-ops-form-project">Проект</label>
        <select
          id="bdds-ops-form-project"
          v-model="formProjectItemId"
          class="w-full"
        >
          <option value="">Выберите проект</option>
          <option v-for="option in projectOptions" :key="option.id" :value="option.id">
            {{ option.label }}
          </option>
        </select>
        <p v-if="!projectOptions.length" class="text-xs text-amber-700">
          Нет проектов, связанных со смарт-процессом проектов: откройте «Проекты» и обновите доску.
        </p>
        <p v-else-if="!formProjectItemId" class="text-xs text-slate-500">
          Операция всегда относится к проекту — без него её не сохранить.
        </p>
      </div>

      <BddsOperationForm
        :project-item-id="formProjectItemId || null"
        :project-name="formProjectName"
        :saving="formSaving"
        :server-error="formServerError"
        :reset-on-project-change="false"
        @submit="saveOperation"
        @cancel="formOpen = false"
      />
    </section>

    <p v-if="formNotice" class="ms-note ms-note-success">{{ formNotice }}</p>

    <div v-if="otherError" class="ms-note ms-note-danger">
      <p class="font-medium">{{ otherError.title }}</p>
      <p v-if="otherError.hint" class="mt-1 text-sm">{{ otherError.hint }}</p>
    </div>

    <div v-if="isLoading && !rows.length" class="ms-surface ms-empty-state">Загрузка…</div>

    <template v-else>
      <!--
        Итоги по выборке. Три числа, а не одно: «пришло», «ушло» и разница
        между ними. Разница подписана как «поступления минус списания», а НЕ
        как финансовый результат проекта: в финрезультат входит ещё и
        стоимость списанных часов, которой на этом экране нет вовсе.
      -->
      <section v-if="page?.totals" class="grid gap-3 sm:grid-cols-3">
        <div class="ms-surface flex flex-col gap-1 p-4">
          <span class="text-xs text-slate-500">Поступления</span>
          <span class="text-xl font-semibold text-emerald-700">
            {{ formatBddsOperationAmount(page.totals.income) }}
          </span>
        </div>
        <div class="ms-surface flex flex-col gap-1 p-4">
          <span class="text-xs text-slate-500">Списания</span>
          <span class="text-xl font-semibold text-rose-700">
            {{ formatBddsOperationAmount(page.totals.expense) }}
          </span>
        </div>
        <div class="ms-surface flex flex-col gap-1 p-4">
          <span class="text-xs text-slate-500">Поступления минус списания</span>
          <span
            class="text-xl font-semibold"
            :class="page.totals.net < 0 ? 'text-rose-700' : 'text-slate-900'"
          >
            {{ formatBddsOperationAmount(page.totals.net) }}
          </span>
          <span class="text-xs text-slate-400">
            Это не финрезультат проекта: стоимости списанных часов здесь нет.
          </span>
        </div>
      </section>

      <section class="ms-surface flex flex-col gap-3 p-5">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm text-slate-500">{{ totalLabel }}</p>
          <p class="text-xs text-slate-400">{{ totalsHint }}</p>
        </div>

        <BddsOperationsTable
          :rows="rows"
          :author-names="authorNames"
          :project-names="projectNames"
          show-project
          :entity-type-id="page?.entityTypeId || null"
          :loading="isLoading"
          :has-more="page?.hasMore || false"
          :truncated="page?.truncated || false"
          :not-configured="notConfigured"
          :empty-text="emptyText"
          @load-more="loadOperations({ append: true })"
          @open-settings="openFieldSettings"
        />

        <p v-if="!notConfigured && !canCreateOperation" class="text-xs text-slate-500">
          {{ noRightsText }}
        </p>
      </section>
    </template>
  </BddsGate>
</template>
