<script setup lang="ts">
/**
 * Закрытие месяца. Спека и мокапы:
 *   docs/architecture/period-closing-spec.md
 *   docs/architecture/period-closing-mockups.html
 *
 * Экран проводит через весь процесс: список периодов -> проверка -> закрытие,
 * плюс переоткрытие и список опоздавших часов.
 *
 * Про доверие к проверке. Кнопка закрытия гаснет, когда есть блокеры, но это
 * УДОБСТВО, а не защита: сервер проверяет блокеры повторно и отвечает 409,
 * потому что запрос можно отправить и мимо интерфейса, а закрытие необратимо.
 *
 * Блокеры и предупреждения показываются РАЗДЕЛЬНО и по-разному. Если свалить
 * их в один список, люди привыкнут нажимать «закрыть» не читая — и проверка
 * перестанет работать ровно тогда, когда понадобится.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import type { PeriodBulkPlan, PeriodCheckResult, PeriodEntryRow, PeriodRow } from '~/types/period'

const router = useRouter()
const apiStore = useApiStore()
const toast = useToast()

useHead({ title: 'Закрытие месяца' })

const { initApp, processErrorGlobal } = useAppInit('PeriodsPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const { locales: localesI18n, setLocale } = useI18n()

const isInit = ref(false)
const isLoading = ref(false)
const periods = ref<PeriodRow[]>([])

// Проверка
const checking = ref(false)
const check = ref<PeriodCheckResult | null>(null)
const checkTarget = ref<PeriodRow | null>(null)

// Детализация находки
const detailsCode = ref('')
const detailsTitle = ref('')
const detailsRows = ref<PeriodEntryRow[]>([])

// Подтверждение и переоткрытие
const confirmClose = ref(false)
const reopenTarget = ref<PeriodRow | null>(null)
const reopenReason = ref('')
const busy = ref(false)

// Опоздавшие
const lateTarget = ref<PeriodRow | null>(null)
const lateRows = ref<PeriodEntryRow[]>([])

async function loadPeriods() {
  isLoading.value = true
  try {
    periods.value = (await apiStore.getPeriods()).periods
  } catch (e) {
    processErrorGlobal(e)
  } finally {
    isLoading.value = false
  }
}

/**
 * Закрывать периоды можно только по порядку, от САМОГО СТАРОГО к новым.
 *
 * Так устроен учёт: нельзя закрыть август, оставив июль открытым — иначе
 * слово «закрыт» перестаёт что-либо значить, а в череде закрытых периодов
 * появляются дыры.
 *
 * Первая версия брала open[0], а список приходит отсортированным от НОВЫХ к
 * старым — то есть кнопка оказывалась у самого свежего месяца, ровно наоборот
 * (найдено при первом же боевом использовании 31.08.2026: у пользователя
 * кнопка была только у сентября, а у остальных девяти периодов стояла
 * подсказка «сначала закройте предыдущий», указывавшая в никуда).
 *
 * Считаем минимум явно, а не по позиции в массиве: порядок сортировки — не то
 * свойство, на которое стоит опираться, оно может измениться на сервере.
 */
const oldestOpen = computed<PeriodRow | null>(() => {
  const open = periods.value.filter(p => !p.closed)
  if (!open.length) return null
  return open.reduce((a, b) => (a.year * 12 + a.month <= b.year * 12 + b.month ? a : b))
})

function isClosable(row: PeriodRow) {
  const target = oldestOpen.value
  return !!target && row.year === target.year && row.month === target.month
}

async function runCheck(row: PeriodRow) {
  checkTarget.value = row
  check.value = null
  detailsCode.value = ''
  checking.value = true
  try {
    check.value = await apiStore.checkPeriod(row.year, row.month)
  } catch (e) {
    processErrorGlobal(e)
    checkTarget.value = null
  } finally {
    checking.value = false
  }
}

async function showDetails(code: string, title: string) {
  if (!checkTarget.value) return
  detailsCode.value = code
  detailsTitle.value = title
  try {
    const res = await apiStore.getPeriodCheckDetails(
      checkTarget.value.year, checkTarget.value.month, code,
    )
    detailsRows.value = res.items
  } catch (e) {
    processErrorGlobal(e)
  }
}

async function doClose() {
  if (!checkTarget.value) return
  busy.value = true
  try {
    await apiStore.closePeriod(checkTarget.value.year, checkTarget.value.month)
    toast.add({ title: `${checkTarget.value.title} закрыт`, color: 'air-primary-success' })
    confirmClose.value = false
    checkTarget.value = null
    check.value = null
    await loadPeriods()
  } catch (e: unknown) {
    // Сюда попадает и отказ сервера по блокерам (409): экран мог считать, что
    // всё чисто, а данные изменились между проверкой и нажатием.
    toast.add({
      title: (e as { message?: string })?.message || 'Не удалось закрыть период',
      color: 'air-primary-alert',
    })
  } finally {
    busy.value = false
  }
}

async function doReopen() {
  if (!reopenTarget.value || !reopenReason.value.trim()) return
  busy.value = true
  try {
    await apiStore.reopenPeriod(
      reopenTarget.value.year, reopenTarget.value.month, reopenReason.value.trim(),
    )
    toast.add({ title: `${reopenTarget.value.title} переоткрыт`, color: 'air-primary-success' })
    reopenTarget.value = null
    reopenReason.value = ''
    await loadPeriods()
  } catch (e: unknown) {
    toast.add({
      title: (e as { message?: string })?.message || 'Не удалось переоткрыть период',
      color: 'air-primary-alert',
    })
  } finally {
    busy.value = false
  }
}

// Массовое закрытие истории
const bulkPlan = ref<PeriodBulkPlan | null>(null)

/**
 * Предлагаем закрыть всё, что старше самого свежего периода: обычно человеку
 * нужен именно текущий месяц, а девять предыдущих он ревизовать не собирался.
 */
const bulkTarget = computed<PeriodRow | null>(() => {
  const open = periods.value.filter(p => !p.closed)
  if (open.length < 2) return null
  const newest = open.reduce((a, b) => (a.year * 12 + a.month >= b.year * 12 + b.month ? a : b))
  // Всё, что СТРОГО старше самого нового открытого.
  const older = open.filter(p => p.year * 12 + p.month < newest.year * 12 + newest.month)
  if (!older.length) return null
  return older.reduce((a, b) => (a.year * 12 + a.month >= b.year * 12 + b.month ? a : b))
})

async function planBulk() {
  const target = bulkTarget.value
  if (!target) return
  busy.value = true
  try {
    bulkPlan.value = await apiStore.closePeriodsBulk(target.year, target.month, false)
  } catch (e: unknown) {
    toast.add({
      title: (e as { message?: string })?.message || 'Не удалось построить план',
      color: 'air-primary-alert',
    })
  } finally {
    busy.value = false
  }
}

async function confirmBulk() {
  const target = bulkTarget.value
  if (!target) return
  busy.value = true
  try {
    const res = await apiStore.closePeriodsBulk(target.year, target.month, true)
    toast.add({
      title: `Закрыто периодов: ${res.closed?.length ?? 0}`,
      color: 'air-primary-success',
    })
    bulkPlan.value = null
    await loadPeriods()
  } catch (e: unknown) {
    toast.add({
      title: (e as { message?: string })?.message || 'Не удалось закрыть периоды',
      color: 'air-primary-alert',
    })
  } finally {
    busy.value = false
  }
}

async function showLate(row: PeriodRow) {
  lateTarget.value = row
  try {
    lateRows.value = (await apiStore.getLateArrivals(row.year, row.month)).items
  } catch (e) {
    processErrorGlobal(e)
  }
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('ru-RU')
}

function formatDateTime(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    isInit.value = true
    await loadPeriods()
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <B24Container>
    <B24PageHeader
      title="Закрытие месяца"
      description="После закрытия часы за период замораживаются и правке не подлежат"
    >
      <template #links>
        <B24Button label="Обновить" :loading="isLoading" @click="loadPeriods" />
        <B24Button label="Назад" color="link" @click="router.push('/settings')" />
      </template>
    </B24PageHeader>

    <!-- ===== Список периодов ===== -->
    <B24Card v-if="isInit && !checkTarget && !lateTarget" class="mt-6">
      <B24Empty v-if="isLoading" title="Загрузка…" size="sm" />
      <B24Empty v-else-if="!periods.length" title="Списаний пока нет" size="sm" />
      <div v-else class="ms-table-shell mt-4">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50">
            <tr class="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <th class="px-3 py-3">Период</th>
              <th class="px-3 py-3 text-right">Часов</th>
              <th class="px-3 py-3 text-right">Записей</th>
              <th class="px-3 py-3">Статус</th>
              <th class="px-3 py-3"/>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="row in periods" :key="`${row.year}-${row.month}`" class="hover:bg-slate-50">
              <td class="px-3 py-2 font-medium text-slate-800">{{ row.title }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ row.hours.toLocaleString('ru-RU') }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ row.entries.toLocaleString('ru-RU') }}</td>
              <td class="px-3 py-2">
                <template v-if="row.closed">
                  <span class="inline-flex rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">Закрыт</span>
                  <span class="mt-1 block text-xs text-slate-500">
                    {{ row.closed_by_name || '—' }} · {{ formatDate(row.closed_at) }}
                  </span>
                </template>
                <template v-else>
                  <span class="inline-flex rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">Открыт</span>
                  <span v-if="row.reopen_reason" class="mt-1 block text-xs text-slate-500">
                    Переоткрыт: {{ row.reopen_reason }}
                  </span>
                </template>
              </td>
              <td class="px-3 py-2 text-right">
                <B24Button
                  v-if="isClosable(row)"
                  label="Закрыть"
                  color="primary"
                  @click="runCheck(row)"
                />
                <B24Button
                  v-else-if="row.closed"
                  label="Переоткрыть"
                  color="default"
                  @click="reopenTarget = row"
                />
                <span v-else class="text-xs text-slate-400">
                  Сначала закройте {{ oldestOpen?.title }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!--
        Массовое закрытие истории. Появляется, только когда открытых периодов
        больше одного: иначе закрывать «всё до» нечего.
      -->
      <div
        v-if="bulkTarget"
        class="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700"
      >
        <span>
          Периоды закрываются по порядку. Если прошлое ревизовать не нужно —
          закройте историю разом до «{{ bulkTarget.title }}» включительно.
        </span>
        <B24Button
          label="Закрыть историю разом"
          color="default"
          :loading="busy"
          @click="planBulk"
        />
      </div>

      <!-- Опоздавшие часы: заметны, но не мешают -->
      <template v-for="row in periods" :key="`late-${row.year}-${row.month}`">
        <div
          v-if="row.closed && row.late_arrivals"
          class="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <span>
            В периоде «{{ row.title }}» после закрытия поступило
            {{ row.late_arrivals }} записей. В отчёт они не включены.
          </span>
          <B24Button label="Посмотреть" color="link" @click="showLate(row)" />
        </div>
      </template>
    </B24Card>

    <!-- ===== Проверка перед закрытием ===== -->
    <B24Card v-if="isInit && checkTarget && !detailsCode" class="mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-lg font-semibold text-slate-800">
          Проверка перед закрытием: {{ checkTarget.title }}
        </h2>
        <B24Button label="К списку" color="link" @click="checkTarget = null; check = null" />
      </div>

      <B24Empty v-if="checking" title="Проверяем…" size="sm" class="mt-4" />

      <template v-else-if="check">
        <!-- Блокеры -->
        <template v-if="check.blockers.length">
          <p class="mt-5 text-xs font-bold uppercase tracking-wider text-red-700">
            Блокеры — закрыть нельзя
          </p>
          <div
            v-for="item in check.blockers"
            :key="item.code"
            class="mt-2 flex items-start gap-3 rounded-lg bg-red-50 px-4 py-3"
          >
            <span class="font-bold text-red-700">✕</span>
            <span class="flex-1">
              <span class="block font-semibold text-slate-800">{{ item.title }}</span>
              <span class="block text-xs text-slate-600">{{ item.why }}</span>
            </span>
            <B24Button label="Показать" color="link" @click="showDetails(item.code, item.title)" />
          </div>
        </template>
        <p v-else class="mt-5 text-xs font-bold uppercase tracking-wider text-emerald-700">
          Блокеров нет
        </p>

        <!-- Предупреждения -->
        <template v-if="check.warnings.length">
          <p class="mt-5 text-xs font-bold uppercase tracking-wider text-amber-700">
            Предупреждения — закрыть можно
          </p>
          <div
            v-for="item in check.warnings"
            :key="item.code"
            class="mt-2 flex items-start gap-3 rounded-lg bg-amber-50 px-4 py-3"
          >
            <span class="font-bold text-amber-700">!</span>
            <span class="flex-1">
              <span class="block font-semibold text-slate-800">{{ item.title }}</span>
              <span class="block text-xs text-slate-600">{{ item.why }}</span>
            </span>
            <B24Button label="Показать" color="link" @click="showDetails(item.code, item.title)" />
          </div>
        </template>

        <p v-if="check.can_close" class="mt-5 border-t border-slate-200 pt-4 text-sm text-slate-700">
          К закрытию:
          <b class="tabular-nums">{{ check.stats.hours.toLocaleString('ru-RU') }} ч</b>
          в <b class="tabular-nums">{{ check.stats.entries.toLocaleString('ru-RU') }}</b> записях ·
          <b class="tabular-nums">{{ check.stats.projects }}</b> проектов ·
          <b class="tabular-nums">{{ check.stats.employees }}</b> сотрудников
        </p>

        <div class="mt-5 flex flex-wrap justify-end gap-2">
          <B24Button label="Обновить проверку" @click="runCheck(checkTarget)" />
          <B24Button
            label="Закрыть месяц"
            color="primary"
            :disabled="!check.can_close"
            @click="confirmClose = true"
          />
        </div>
      </template>
    </B24Card>

    <!-- ===== Детализация находки ===== -->
    <B24Card v-if="isInit && detailsCode" class="mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-lg font-semibold text-slate-800">{{ detailsTitle }}</h2>
        <B24Button label="К проверке" color="link" @click="detailsCode = ''" />
      </div>
      <B24Empty v-if="!detailsRows.length" title="Записей нет" size="sm" class="mt-4" />
      <div v-else class="ms-table-shell mt-4">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50">
            <tr class="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <th class="px-3 py-3">Дата</th>
              <th class="px-3 py-3">Задача</th>
              <th class="px-3 py-3">Сотрудник</th>
              <th class="px-3 py-3">Проект</th>
              <th class="px-3 py-3 text-right">Часы</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="row in detailsRows" :key="row.bitrix_id" class="hover:bg-slate-50">
              <td class="px-3 py-2 tabular-nums">{{ formatDate(row.date) }}</td>
              <td class="px-3 py-2">{{ row.task_id || '—' }}</td>
              <td class="px-3 py-2">{{ row.employee_id || '—' }}</td>
              <td class="px-3 py-2">{{ row.project_title || '—' }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ row.hours }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </B24Card>

    <!-- ===== Поступило после закрытия ===== -->
    <B24Card v-if="isInit && lateTarget" class="mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-lg font-semibold text-slate-800">
          {{ lateTarget.title }} — поступило после закрытия
        </h2>
        <B24Button label="К списку" color="link" @click="lateTarget = null" />
      </div>
      <p class="mt-2 text-sm text-slate-600">
        Эти записи созданы в Битриксе уже после закрытия периода. В отчёт они не включены.
        Чтобы учесть их — переоткройте период, затем закройте снова.
      </p>
      <B24Empty v-if="!lateRows.length" title="Опоздавших нет" size="sm" class="mt-4" />
      <div v-else class="ms-table-shell mt-4">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50">
            <tr class="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <th class="px-3 py-3">Дата</th>
              <th class="px-3 py-3">Задача</th>
              <th class="px-3 py-3">Сотрудник</th>
              <th class="px-3 py-3 text-right">Часы</th>
              <th class="px-3 py-3">Создана</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="row in lateRows" :key="row.bitrix_id" class="hover:bg-slate-50">
              <td class="px-3 py-2 tabular-nums">{{ formatDate(row.date) }}</td>
              <td class="px-3 py-2">{{ row.task_id || '—' }}</td>
              <td class="px-3 py-2">{{ row.employee_id || '—' }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ row.hours }}</td>
              <td class="px-3 py-2 tabular-nums">{{ formatDateTime(row.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-5 flex justify-end">
        <B24Button label="Переоткрыть период" color="primary" @click="reopenTarget = lateTarget; lateTarget = null" />
      </div>
    </B24Card>

    <!-- ===== Подтверждение закрытия ===== -->
    <B24Modal v-model:open="confirmClose" title="Закрыть период?">
      <template #body>
        <p v-if="check" class="text-sm text-slate-700">
          После закрытия <b>{{ check.stats.entries.toLocaleString('ru-RU') }} записей</b>
          будут заморожены. Изменить их через приложение станет нельзя — только через
          переоткрытие периода.
        </p>
        <p v-if="check && check.warnings.length" class="mt-3 text-sm text-slate-600">
          Предупреждения останутся как есть.
        </p>
      </template>
      <template #footer>
        <B24Button label="Отмена" color="link" @click="confirmClose = false" />
        <B24Button label="Закрыть месяц" color="primary" :loading="busy" @click="doClose" />
      </template>
    </B24Modal>

    <!--
      ===== Подтверждение массового закрытия =====
      Сервер сначала присылает план и НИЧЕГО не закрывает. Здесь человек видит,
      что именно принимает: сколько периодов, часов и сколько из них с
      блокерами. Одно осознанное решение вместо девяти — но осознанное.
    -->
    <B24Modal
      :open="!!bulkPlan"
      title="Закрыть историю разом?"
      @update:open="v => { if (!v) bulkPlan = null }"
    >
      <template #body>
        <template v-if="bulkPlan?.total">
          <p class="text-sm text-slate-700">
            Будет закрыто <b>{{ bulkPlan.total.periods }}</b> периодов:
            <b class="tabular-nums">{{ bulkPlan.total.hours.toLocaleString('ru-RU') }} ч</b>
            в <b class="tabular-nums">{{ bulkPlan.total.entries.toLocaleString('ru-RU') }}</b> записях.
          </p>

          <p
            v-if="bulkPlan.total.with_blockers"
            class="mt-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900"
          >
            В <b>{{ bulkPlan.total.with_blockers }}</b> из них проверка нашла ошибки
            в данных. Эти периоды будут заморожены <b>как есть</b> — исправить их
            потом можно будет только через переоткрытие.
            Что именно сломано, записывается в историю каждого периода.
          </p>

          <div class="ms-table-shell mt-4 max-h-64 overflow-y-auto">
            <table class="min-w-full text-sm">
              <thead class="bg-slate-50">
                <tr class="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <th class="px-3 py-2">Период</th>
                  <th class="px-3 py-2 text-right">Часов</th>
                  <th class="px-3 py-2">Ошибки</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                <tr v-for="p in bulkPlan.periods" :key="`${p.year}-${p.month}`">
                  <td class="px-3 py-2">{{ p.title }}</td>
                  <td class="px-3 py-2 text-right tabular-nums">
                    {{ p.stats.hours.toLocaleString('ru-RU') }}
                  </td>
                  <td class="px-3 py-2">
                    <span v-if="!p.blockers.length" class="text-xs text-emerald-700">чисто</span>
                    <span v-else class="text-xs text-red-700">
                      {{ p.blockers.map(b => b.title).join('; ') }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
      <template #footer>
        <B24Button label="Отмена" color="link" @click="bulkPlan = null" />
        <B24Button
          label="Закрыть всё перечисленное"
          color="primary"
          :loading="busy"
          @click="confirmBulk"
        />
      </template>
    </B24Modal>

    <!-- ===== Переоткрытие ===== -->
    <B24Modal :open="!!reopenTarget" title="Переоткрыть период?" @update:open="v => { if (!v) reopenTarget = null }">
      <template #body>
        <p class="text-sm text-slate-700">
          Записи периода снова станут доступны для изменения. Отчёт может измениться —
          если он уже лёг в основу счёта, расхождение придётся объяснять.
        </p>
        <label class="mt-4 block text-xs font-semibold text-slate-600">
          Причина (обязательно)
        </label>
        <B24Input
          v-model="reopenReason"
          class="mt-1 w-full"
          placeholder="Например: учесть записи, поступившие после закрытия"
        />
      </template>
      <template #footer>
        <B24Button label="Отмена" color="link" @click="reopenTarget = null" />
        <B24Button
          label="Переоткрыть"
          color="primary"
          :disabled="!reopenReason.trim()"
          :loading="busy"
          @click="doReopen"
        />
      </template>
    </B24Modal>
  </B24Container>
</template>
