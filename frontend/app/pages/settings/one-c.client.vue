<script setup lang="ts">
/**
 * Настройки обмена с 1С: куда приложение отправляет часы за период
 * и кому эти часы принадлежат на стороне 1С.
 *
 * Адрес и токен живут в настройках портала, а не в переменных окружения:
 * у каждого портала своя 1С, и менять адрес должен администратор, а не
 * правка файла на сервере. Пустые поля токена и пароля означают
 * «оставить прежнее значение» — секреты обратно на экран не возвращаются.
 *
 * Сопоставления выбираются из справочников самой 1С: ФИО и ИНН, набранные
 * руками, ошибаются молча — отказ всплывает только при отправке часов.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import type {
  OneCCompanyRow, OneCDirectoryItem, OneCEmployeeRow, OneCExportRun, OneCProjectRow
} from '~/types/oneC'

const router = useRouter()
const apiStore = useApiStore()
const toast = useToast()

useHead({ title: 'Обмен с 1С' })

const { initApp, processErrorGlobal } = useAppInit('OneCSettingsPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const { locales: localesI18n, setLocale } = useI18n()

const isInit = ref(false)
const saving = ref(false)
const lastRun = ref<OneCExportRun | null>(null)
const form = ref({ inbox_url: '', token: '', user: '', password: '' })

// Сопоставления: кто списывал часы и какие компании участвуют. Списки
// строятся по факту списаний, а не по всему справочнику портала.
const employees = ref<OneCEmployeeRow[]>([])
const companies = ref<OneCCompanyRow[]>([])
const legalEntities = ref<OneCCompanyRow[]>([])
const projects = ref<OneCProjectRow[]>([])
const savingMapping = ref(false)

// Справочники 1С — то, из чего выбирают. Пока они не загружены, поля
// остаются обычным вводом: экран не должен становиться неработоспособным
// из-за недоступной 1С.
const people = ref<OneCDirectoryItem[]>([])
const organizations = ref<OneCDirectoryItem[]>([])
const counterparties = ref<OneCDirectoryItem[]>([])
const directoriesMessage = ref('')
const loadingDirectories = ref(false)

const unmappedProjects = computed(
  () => projects.value.filter(row => !row.client_inn || !row.legal_inn).length)
const unmappedProjectRows = computed(
  () => projects.value.filter(row => !row.client_inn || !row.legal_inn)
    .reduce((sum, row) => sum + row.rows, 0))
const unmappedEmployees = computed(() => employees.value.filter(row => !row.mapped_to).length)
const companiesWithoutInn = computed(
  () => [...companies.value, ...legalEntities.value]
    .filter(row => !row.inn_manual && !row.inn_auto).length)

const hasPeople = computed(() => people.value.length > 0)
const hasCounterparties = computed(() => counterparties.value.length > 0)
const hasOrganizations = computed(() => organizations.value.length > 0)

/** Варианты для списка ИНН: без ИНН выбирать нечего — такие строки не показываем. */
function innOptions(items: OneCDirectoryItem[], current: string) {
  const options = items
    .filter(item => item.inn)
    .map(item => ({ value: item.inn, label: `${item.name} — ${item.inn}` }))

  // Сохранённое значение, которого нет в 1С, не должно молча пропасть из поля.
  if (current && !options.some(option => option.value === current)) {
    options.unshift({ value: current, label: `${current} (нет в 1С)` })
  }
  return options
}

function nameOptions(items: OneCDirectoryItem[], current: string) {
  const options = items.map(item => ({ value: item.name, label: item.name }))
  if (current && !options.some(option => option.value === current)) {
    options.unshift({ value: current, label: `${current} (нет в 1С)` })
  }
  return options
}

async function loadDirectories(quiet = true) {
  loadingDirectories.value = true
  try {
    const data = await apiStore.getOneCDirectories()
    people.value = data.people || []
    organizations.value = data.organizations || []
    counterparties.value = data.counterparties || []
    directoriesMessage.value = data.ok ? '' : (data.message || '')

    if (!quiet) {
      if (data.ok) {
        toast.add({
          title: `Загружено из 1С: физлиц ${people.value.length}, `
            + `юрлиц ${organizations.value.length}, клиентов ${counterparties.value.length}`,
          color: 'success'
        })
      } else {
        toast.add({ title: data.message || 'Справочники 1С не получены', color: 'warning' })
      }
    }
  } catch (error) {
    directoriesMessage.value = 'Справочники 1С не получены'
    if (!quiet) processErrorGlobal(error)
  } finally {
    loadingDirectories.value = false
  }
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    isInit.value = true

    const config = await apiStore.getConfiguration()
    const oneC = ((config as Record<string, unknown>).one_c || {}) as Record<string, string>
    form.value.inbox_url = oneC.inbox_url || ''
    form.value.user = oneC.user || ''

    const history = await apiStore.getOneCExportHistory()
    lastRun.value = history.runs?.[0] || null

    const mapping = await apiStore.getOneCMapping()
    employees.value = mapping.employees || []
    companies.value = mapping.companies || []
    legalEntities.value = mapping.legal_entities || []
    projects.value = mapping.projects || []

    // Списки тянем сразу, если подключение уже настроено: чаще всего человек
    // приходит на экран именно доделывать сопоставление.
    if (form.value.inbox_url) await loadDirectories(true)
  } catch (error) {
    processErrorGlobal(error)
  }
})

async function saveMapping() {
  savingMapping.value = true
  try {
    const config = await apiStore.getConfiguration(true)
    const current = ((config as Record<string, unknown>).one_c || {}) as Record<string, unknown>

    // В настройки уходит только заполненное: пустые строки не засоряют
    // хранилище и не мешают автоматическому поиску.
    const asMap = (rows: { id: string, value: string }[]) => rows
      .filter(row => row.value)
      .reduce<Record<string, string>>((acc, row) => ({ ...acc, [row.id]: row.value }), {})

    const next = {
      ...current,
      employees: asMap(employees.value.map(r => ({ id: r.id, value: (r.mapped_to || '').trim() }))),
      companies: asMap(companies.value.map(r => ({ id: r.id, value: (r.inn_manual || '').trim() }))),
      legal_entities: asMap(
        legalEntities.value.map(r => ({ id: r.id, value: (r.inn_manual || '').trim() }))),
      // Проекты хранятся парой ИНН: у таких строк нет ни компании, ни юрлица,
      // подставлять нужно оба.
      projects: projects.value
        .filter(row => row.client_inn || row.legal_inn)
        .reduce<Record<string, { client_inn: string, legal_inn: string }>>(
          (acc, row) => ({ ...acc, [row.title]: {
            client_inn: (row.client_inn || '').trim(),
            legal_inn: (row.legal_inn || '').trim()
          } }), {})
    }

    await apiStore.saveConfiguration({ ...(config as object), one_c: next } as never)
    toast.add({ title: 'Сопоставления сохранены', color: 'success' })
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    savingMapping.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const config = await apiStore.getConfiguration(true)
    const current = ((config as Record<string, unknown>).one_c || {}) as Record<string, string>
    const next = {
      ...current,
      inbox_url: form.value.inbox_url,
      user: form.value.user,
      token: form.value.token || current.token || '',
      password: form.value.password || current.password || ''
    }
    await apiStore.saveConfiguration({ ...(config as object), one_c: next } as never)
    toast.add({ title: 'Настройки обмена сохранены', color: 'success' })
    form.value.token = ''
    form.value.password = ''

    // Реквизиты изменились — самое время проверить их делом и получить списки.
    await loadDirectories(false)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <B24Container>
    <B24PageHeader
      title="Обмен с 1С"
      description="Куда приложение отправляет часы за период и под какими реквизитами"
    >
      <template #links>
        <B24Button label="Отправка часов" color="link" @click="router.push('/settings/periods')" />
        <B24Button label="Назад" color="link" @click="router.push('/settings')" />
      </template>
    </B24PageHeader>

    <div v-if="isInit" class="mt-6 space-y-6">
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Приёмник часов</span>
        </template>

        <div class="space-y-4">
          <label class="block">
            <span class="text-sm font-medium text-slate-700">Адрес точки приёма</span>
            <input
              v-model.trim="form.inbox_url"
              type="text"
              placeholder="http://1c.example.ru/База/hs/msbx24/v1/inbox/timesheet"
              class="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
            <span class="mt-1 block text-xs text-slate-500">
              Адрес публикации базы 1С плюс путь <code>/hs/msbx24/v1/inbox/timesheet</code>.
              Точку публикует «Расширенный коннектор 1С».
            </span>
          </label>

          <label class="block">
            <span class="text-sm font-medium text-slate-700">Токен подключения</span>
            <input
              v-model.trim="form.token"
              type="password"
              autocomplete="new-password"
              class="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
            <span class="mt-1 block text-xs text-slate-500">
              Тот же токен, что записан в подключении на стороне 1С.
              Пустое поле — оставить прежнее значение.
            </span>
          </label>

          <div class="grid gap-4 sm:grid-cols-2">
            <label class="block">
              <span class="text-sm font-medium text-slate-700">Пользователь 1С</span>
              <input
                v-model.trim="form.user"
                type="text"
                class="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              >
            </label>
            <label class="block">
              <span class="text-sm font-medium text-slate-700">Пароль пользователя 1С</span>
              <input
                v-model="form.password"
                type="password"
                autocomplete="new-password"
                class="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
              >
            </label>
          </div>

          <p class="text-xs text-slate-500">
            Публикация 1С закрыта обычной авторизацией: без пользователя веб-сервер
            отвечает 401 ещё до того, как запрос дойдёт до приёмника.
          </p>
        </div>

        <template #footer>
          <div class="flex items-center gap-3">
            <B24Button label="Сохранить" color="primary" :loading="saving" @click="save" />
            <B24Button
              label="Проверить связь и обновить списки"
              color="link"
              :loading="loadingDirectories"
              @click="loadDirectories(false)"
            />
          </div>
        </template>
      </B24Card>

      <div
        v-if="directoriesMessage"
        class="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
      >
        Списки из 1С не получены: {{ directoriesMessage }}.
        Сопоставление ниже можно заполнить вручную.
      </div>

      <B24Card>
        <template #header>
          <div class="flex items-center justify-between">
            <span class="text-base font-semibold text-slate-900">Сопоставление сотрудников</span>
            <span v-if="unmappedEmployees" class="text-xs text-amber-700">
              не сопоставлено: {{ unmappedEmployees }}
            </span>
          </div>
        </template>

        <p class="mb-3 text-sm text-slate-500">
          Кому в 1С принадлежат часы. Пока сотрудник не сопоставлен, его строки
          возвращаются с причиной «сотрудник не связан с физлицом».
          <template v-if="hasPeople">
            Список физлиц загружен из 1С — выберите нужного.
          </template>
          <template v-else>
            Пустое поле — 1С попробует найти сама по своему регистру.
          </template>
        </p>

        <div class="max-h-80 overflow-y-auto rounded border border-slate-200">
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr>
                <th class="px-2 py-1 text-left">Сотрудник в Битрикс24</th>
                <th class="px-2 py-1 text-left">Физлицо в 1С</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in employees" :key="row.id" class="border-t border-slate-100">
                <td class="px-2 py-1">
                  {{ row.name || '—' }}
                  <span class="text-xs text-slate-400">id {{ row.id }}</span>
                </td>
                <td class="px-2 py-1">
                  <select
                    v-if="hasPeople"
                    v-model="row.mapped_to"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                    <option value="">— не сопоставлен —</option>
                    <option
                      v-for="option in nameOptions(people, row.mapped_to)"
                      :key="option.value"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <input
                    v-else
                    v-model.trim="row.mapped_to"
                    type="text"
                    placeholder="Фамилия Имя Отчество"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </B24Card>

      <B24Card v-if="projects.length">
        <template #header>
          <div class="flex items-center justify-between">
            <span class="text-base font-semibold text-slate-900">Проекты без карточки</span>
            <span v-if="unmappedProjects" class="text-xs text-amber-700">
              не сопоставлено: {{ unmappedProjects }} ({{ unmappedProjectRows }} списаний)
            </span>
          </div>
        </template>

        <p class="mb-3 text-sm text-slate-500">
          Часы списаны на проект, которого нет в смарт-процессе: ни клиента, ни
          нашего юрлица у такой строки нет, и в 1С она уходит без ИНН — то есть
          возвращается отклонённой. Укажите, кому эти часы принадлежат.
        </p>

        <div class="max-h-80 overflow-y-auto rounded border border-slate-200">
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr>
                <th class="px-2 py-1 text-left">Проект в списаниях</th>
                <th class="px-2 py-1 text-left">Клиент в 1С</th>
                <th class="px-2 py-1 text-left">Наше юрлицо</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in projects" :key="row.title" class="border-t border-slate-100">
                <td class="px-2 py-1">
                  {{ row.title }}
                  <span class="text-xs text-slate-400">{{ row.rows }} списаний</span>
                </td>
                <td class="px-2 py-1">
                  <select
                    v-if="hasCounterparties"
                    v-model="row.client_inn"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                    <option value="">— не выбран —</option>
                    <option
                      v-for="option in innOptions(counterparties, row.client_inn)"
                      :key="option.value"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <input
                    v-else
                    v-model.trim="row.client_inn"
                    type="text"
                    placeholder="ИНН клиента"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm tabular-nums"
                  >
                </td>
                <td class="px-2 py-1">
                  <select
                    v-if="hasOrganizations"
                    v-model="row.legal_inn"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                    <option value="">— не выбрано —</option>
                    <option
                      v-for="option in innOptions(organizations, row.legal_inn)"
                      :key="option.value"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <input
                    v-else
                    v-model.trim="row.legal_inn"
                    type="text"
                    placeholder="ИНН нашего юрлица"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm tabular-nums"
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </B24Card>

      <B24Card>
        <template #header>
          <div class="flex items-center justify-between">
            <span class="text-base font-semibold text-slate-900">ИНН клиентов и наших юрлиц</span>
            <span v-if="companiesWithoutInn" class="text-xs text-amber-700">
              без ИНН: {{ companiesWithoutInn }}
            </span>
          </div>
        </template>

        <p class="mb-3 text-sm text-slate-500">
          По ИНН 1С находит контрагента и организацию. Найденное в Битриксе
          подставляется само — выбирайте вручную, только если там пусто или неверно.
        </p>

        <div class="max-h-80 overflow-y-auto rounded border border-slate-200">
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr>
                <th class="px-2 py-1 text-left">Компания</th>
                <th class="px-2 py-1 text-left">ИНН из Битрикса</th>
                <th class="px-2 py-1 text-left">Соответствие в 1С</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in legalEntities"
                :key="'l' + row.id"
                class="border-t border-slate-100 bg-slate-50/50"
              >
                <td class="px-2 py-1">
                  {{ row.name || '—' }}
                  <span class="text-xs text-slate-400">наше юрлицо</span>
                </td>
                <td class="px-2 py-1 tabular-nums text-slate-500">{{ row.inn_auto || '—' }}</td>
                <td class="px-2 py-1">
                  <select
                    v-if="hasOrganizations"
                    v-model="row.inn_manual"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                    <option value="">— как в Битриксе —</option>
                    <option
                      v-for="option in innOptions(organizations, row.inn_manual)"
                      :key="option.value"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <input
                    v-else
                    v-model.trim="row.inn_manual"
                    type="text"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm tabular-nums"
                  >
                </td>
              </tr>
              <tr v-for="row in companies" :key="'c' + row.id" class="border-t border-slate-100">
                <td class="px-2 py-1">{{ row.name || '—' }}</td>
                <td class="px-2 py-1 tabular-nums text-slate-500">{{ row.inn_auto || '—' }}</td>
                <td class="px-2 py-1">
                  <select
                    v-if="hasCounterparties"
                    v-model="row.inn_manual"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                    <option value="">— как в Битриксе —</option>
                    <option
                      v-for="option in innOptions(counterparties, row.inn_manual)"
                      :key="option.value"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <input
                    v-else
                    v-model.trim="row.inn_manual"
                    type="text"
                    class="w-full rounded border border-slate-300 px-2 py-1 text-sm tabular-nums"
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <template #footer>
          <B24Button
            label="Сохранить сопоставления"
            color="primary"
            :loading="savingMapping"
            @click="saveMapping"
          />
        </template>
      </B24Card>

      <B24Card v-if="lastRun">
        <template #header>
          <span class="text-base font-semibold text-slate-900">Последняя отправка</span>
        </template>
        <p class="text-sm">
          {{ lastRun.period_from }} — {{ lastRun.period_to }}:
          принято <b class="tabular-nums">{{ lastRun.accepted }}</b>,
          отклонено <b class="tabular-nums">{{ lastRun.rejected }}</b>,
          документов <b class="tabular-nums">{{ lastRun.documents.length }}</b>.
        </p>
        <p v-if="lastRun.message" class="mt-2 text-sm text-red-600">
          {{ lastRun.message }}
        </p>
      </B24Card>
    </div>
  </B24Container>
</template>
