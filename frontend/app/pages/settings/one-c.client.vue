<template>
  <B24Container>
    <B24PageHeader
      title="Обмен с 1С"
      description="Куда приложение отправляет часы за период и под какими реквизитами."
    >
      <template #links>
        <B24Button label="Назад" color="link" @click="router.push('/settings')" />
      </template>
    </B24PageHeader>

    <div class="mt-6 space-y-6">
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
              Публикация базы 1С плюс путь <code>/hs/msbx24/v1/inbox/timesheet</code>.
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
              Сохранённое значение не показывается — поле пустое означает «не менять».
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
          <B24Button label="Отправить часы" color="link" @click="router.push('/settings/periods')" />
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
        <p v-if="lastRun.message" class="mt-2 text-sm text-red-600">{{ lastRun.message }}</p>
      </B24Card>
    </div>
  </B24Container>
</template>

<script setup lang="ts">
import type { OneCExportRun } from '~/types/oneC'

const router = useRouter()
const apiStore = useApiStore()
const toast = useToast()
const { initApp, processErrorGlobal } = useAppInit('OneCSettingsPage')

const saving = ref(false)
const lastRun = ref<OneCExportRun | null>(null)
const form = ref({ inbox_url: '', token: '', user: '', password: '' })

onMounted(async () => {
  try {
    await initApp()
    const config = await apiStore.getConfiguration()
    const oneC = (config as Record<string, any>).one_c || {}
    // Токен и пароль намеренно не подставляем: секреты не возвращаются
    // на экран, пустое поле означает «оставить прежнее значение».
    form.value.inbox_url = oneC.inbox_url || ''
    form.value.user = oneC.user || ''

    const history = await apiStore.getOneCExportHistory()
    lastRun.value = history.runs?.[0] || null
  } catch (error) {
    processErrorGlobal(error)
  }
})

async function save() {
  saving.value = true
  try {
    const config = await apiStore.getConfiguration(true)
    const current = (config as Record<string, any>).one_c || {}
    const next: Record<string, string> = {
      inbox_url: form.value.inbox_url,
      user: form.value.user,
      token: form.value.token || current.token || '',
      password: form.value.password || current.password || '',
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
