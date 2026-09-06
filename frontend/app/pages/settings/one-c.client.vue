<script setup lang="ts">
/**
 * Настройки обмена с 1С: куда приложение отправляет часы за период.
 *
 * Адрес и токен живут в настройках портала, а не в переменных окружения:
 * у каждого портала своя 1С, и менять адрес должен администратор, а не
 * правка файла на сервере. Пустые поля токена и пароля означают
 * «оставить прежнее значение» — секреты обратно на экран не возвращаются.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import type { OneCCompanyRow, OneCEmployeeRow, OneCExportRun } from '~/types/oneC'

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
const savingMapping = ref(false)

const unmappedEmployees = computed(() => employees.value.filter(row => !row.mapped_to).length)
const companiesWithoutInn = computed(
  () => [...companies.value, ...legalEntities.value]
    .filter(row => !row.inn_manual && !row.inn_auto).length)

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
      employees: asMap(employees.value.map(r => ({ id: r.id, value: r.mapped_to.trim() }))),
      companies: asMap(companies.value.map(r => ({ id: r.id, value: r.inn_manual.trim() }))),
      legal_entities: asMap(legalEntities.value.map(r => ({ id: r.id, value: r.inn_manual.trim() })))
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
      inbox_url: form.value.inbox_url,
      user: form.value.user,
      token: form.value.token || current.token || '',
      password: form.value.password || current.password || ''
    }
    await apiStore.saveConfiguration({ ...(config as object), one_c: next } as never)
    toast.add({ title: 'Настройки обмена сохранены', color: 'success' })
    form.value.token = ''
    form.value.password = ''
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
          <B24Button label="Сохранить" color="primary" :loading="saving" @click="save" />
        </template>
      </B24Card>

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
          Пустое поле — 1С попробует найти сама по своему регистру.
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
                  <input
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
          подставляется само — заполняйте, только если там пусто или неверно.
        </p>

        <div class="max-h-80 overflow-y-auto rounded border border-slate-200">
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr>
                <th class="px-2 py-1 text-left">Компания</th>
                <th class="px-2 py-1 text-left">ИНН из Битрикса</th>
                <th class="px-2 py-1 text-left">ИНН вручную</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in legalEntities" :key="'l' + row.id" class="border-t border-slate-100 bg-slate-50/50">
                <td class="px-2 py-1">
                  {{ row.name || '—' }}
                  <span class="text-xs text-slate-400">наше юрлицо</span>
                </td>
                <td class="px-2 py-1 tabular-nums text-slate-500">{{ row.inn_auto || '—' }}</td>
                <td class="px-2 py-1">
                  <input
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
                  <input
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
