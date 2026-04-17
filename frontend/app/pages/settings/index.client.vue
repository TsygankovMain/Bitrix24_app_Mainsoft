<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="ms-page-header">
        <div>
          <h1 class="ms-title">Настройки</h1>
          <p class="ms-subtitle mt-2">Персональные и системные параметры приложения.</p>
        </div>
        <B24Button label="Назад" color="link" @click="router.push('/')" />
      </div>

      <div class="space-y-8">
        <div class="ms-panel">
          <h3 class="text-base font-semibold text-slate-900">Отчёты</h3>
          <div class="flex items-center justify-between">
            <div>
              <p class="mt-3 text-sm font-medium text-slate-700">Кликабельные метки</p>
              <p class="mt-1 text-sm text-slate-500">
                Названия меток времени в отчётах становятся ссылками, открывающими карточку элемента.
              </p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer ml-4">
              <input type="checkbox" v-model="clickableLabelsEnabled" @change="saveUserSettings" class="sr-only peer">
              <div class="h-6 w-11 rounded-full bg-slate-300 transition peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-lime-200 peer-checked:bg-lime-400 peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-slate-300 after:bg-white after:transition-all after:content-['']" />
            </label>
          </div>
        </div>

        <div class="ms-card-grid">
          <div class="ms-panel">
            <h3 class="text-base font-semibold text-slate-900">Конфигурация</h3>
            <p class="mt-2 text-sm text-slate-500">
            Сопоставление полей Smart Process с полями приложения.
            </p>
            <B24Button class="mt-4" label="Настройка полей (Маппинг)" color="success" @click="router.push('/settings/mapping')" />
          </div>

          <div class="ms-panel">
            <h3 class="text-base font-semibold text-slate-900">Данные</h3>
            <p class="mt-2 text-sm text-slate-500">
            Просмотр необработанных данных, синхронизированных с базой данных.
            </p>
            <B24Button class="mt-4" label="Перейти к сырым данным" color="primary" @click="router.push('/reports/raw-data')" />
          </div>

          <div class="ms-panel">
            <h3 class="text-base font-semibold text-slate-900">Отладка</h3>
            <p class="mt-2 text-sm text-slate-500">
            Логи запросов и ошибок системы.
            </p>
            <B24Button class="mt-4" label="Панель отладки" color="default" @click="router.push('/settings/debug')" />
          </div>
        </div>

        <div class="ms-panel">
          <h3 class="text-base font-semibold text-slate-900">Служебные разделы</h3>
          <p class="mt-2 text-sm text-slate-500">
            Технические экраны вынесены из главной страницы и доступны отсюда.
          </p>
          <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <B24Button label="Сырые данные" color="default" @click="router.push('/reports/raw-data')" />
            <B24Button label="Отладка отчетов" color="default" @click="router.push('/reports/debug')" />
            <B24Button label="Отладка настроек" color="default" @click="router.push('/settings/debug')" />
            <B24Button label="Опции слайдера" color="default" @click="router.push('/slider/app-options')" />
          </div>
        </div>
      </div>
    </div>
  </div>
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
