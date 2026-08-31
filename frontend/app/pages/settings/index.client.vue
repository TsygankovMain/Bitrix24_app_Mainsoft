<template>
  <B24Container>
    <B24PageHeader
      title="Настройки"
      description="Персональные и системные параметры приложения."
    >
      <template #links>
        <B24Button label="Назад" color="link" @click="router.push('/')" />
      </template>
    </B24PageHeader>

    <div class="mt-6 space-y-6">
      <!-- Тумблер «Кликабельные метки» -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Отчёты</span>
        </template>
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-slate-700">Кликабельные метки</p>
            <p class="mt-1 text-sm text-slate-500">
              Названия меток времени в отчётах становятся ссылками, открывающими карточку элемента.
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer ml-4">
            <input v-model="clickableLabelsEnabled" type="checkbox" class="sr-only peer" @change="saveUserSettings">
            <div class="h-6 w-11 rounded-full bg-slate-300 transition peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-200 peer-checked:bg-[#0075ff] peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-slate-300 after:bg-white after:transition-all after:content-['']" />
          </label>
        </div>
      </B24Card>

      <!-- Грид основных разделов -->
      <B24PageGrid>
        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Конфигурация</span>
          </template>
          <p class="text-sm text-slate-500">
            Сопоставление полей процесса с данными приложения.
          </p>
          <template #footer>
            <B24Button label="Настройка полей" color="success" @click="router.push('/settings/mapping')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Данные</span>
          </template>
          <p class="text-sm text-slate-500">
            Просмотр исходных записей, синхронизированных с системой.
          </p>
          <template #footer>
            <B24Button label="Открыть проверку данных" color="primary" @click="router.push('/reports/raw-data')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Диагностика</span>
          </template>
          <p class="text-sm text-slate-500">
            Логи запросов и ошибок системы.
          </p>
          <template #footer>
            <B24Button label="Диагностика системы" color="default" @click="router.push('/settings/debug')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Проекты</span>
          </template>
          <p class="text-sm text-slate-500">
            Проверка заполненности данных проектов для ИНН.
          </p>
          <template #footer>
            <B24Button label="Незаполненные проекты" color="default" @click="router.push('/settings/projects-health')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Закрытие месяца</span>
          </template>
          <p class="text-sm text-slate-500">
            Заморозка часов за период. После закрытия списать или изменить часы
            за этот месяц нельзя.
          </p>
          <template #footer>
            <B24Button label="Периоды" color="default" @click="router.push('/settings/periods')" />
          </template>
        </B24Card>
      </B24PageGrid>

      <!-- Служебные разделы -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Служебные разделы</span>
        </template>
        <p class="text-sm text-slate-500">
          Технические экраны вынесены из главной страницы и доступны отсюда.
        </p>
        <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <B24Button label="Проверка данных" color="default" @click="router.push('/reports/raw-data')" />
          <B24Button label="Диагностика отчетов" color="default" @click="router.push('/reports/debug')" />
          <B24Button label="Диагностика настроек" color="default" @click="router.push('/settings/debug')" />
          <B24Button label="Опции слайдера" color="default" @click="router.push('/slider/app-options')" />
        </div>
      </B24Card>
    </div>
  </B24Container>
</template>

<script setup lang="ts">
const router = useRouter()
const userSettings = useUserSettingsStore()

useHead({
  title: 'Настройки'
})

const clickableLabelsEnabled = ref(userSettings.configSettings.clickableLabelsEnabled ?? false)

// Sync local ref with store changes
watch(() => userSettings.configSettings.clickableLabelsEnabled, (val) => {
  clickableLabelsEnabled.value = val ?? false
})

async function saveUserSettings() {
  userSettings.configSettings.clickableLabelsEnabled = clickableLabelsEnabled.value
  try {
    await userSettings.saveSettings()
  } catch (e) {
    console.error('Failed to save user settings:', e)
  }
}
</script>
