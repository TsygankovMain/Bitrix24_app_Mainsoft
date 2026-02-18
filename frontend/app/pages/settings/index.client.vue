<template>
  <div class="p-4 sm:p-6 bg-white dark:bg-gray-900 min-h-screen">
    <div class="mx-auto">
      <!-- Header -->
      <div class="flex items-center justify-between mb-8">
        <h1 class="text-3xl font-bold text-gray-900 dark:text-gray-100">Настройки</h1>
        <button @click="router.push('/')" class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 rounded-md hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
          Назад
        </button>
      </div>

      <div class="space-y-8">
        <!-- Theme Switcher -->
        <ThemeSwitcher />

        <!-- Reports Settings -->
        <div class="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg">
          <h3 class="text-lg font-semibold mb-3 text-gray-900 dark:text-gray-100">Отчёты</h3>
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Кликабельные метки</p>
              <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Названия меток времени в отчётах становятся ссылками, открывающими карточку элемента.
              </p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer ml-4">
              <input type="checkbox" v-model="clickableLabelsEnabled" @change="saveUserSettings" class="sr-only peer">
              <div class="w-11 h-6 bg-gray-300 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
          </div>
        </div>

        <!-- Configuration Link -->
        <div class="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg">
          <h3 class="text-lg font-semibold mb-3 text-gray-900 dark:text-gray-100">Конфигурация</h3>
          <button @click="router.push('/settings/mapping')" class="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700 transition-colors">
            Настройка полей (Маппинг)
          </button>
          <p class="text-sm text-gray-500 dark:text-gray-400 mt-2">
            Сопоставление полей Smart Process с полями приложения.
          </p>
        </div>

        <!-- Raw Data Link -->
        <div class="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg">
          <h3 class="text-lg font-semibold mb-3 text-gray-900 dark:text-gray-100">Данные</h3>
          <button @click="router.push('/reports/raw-data')" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors">
            Перейти к сырым данным
          </button>
          <p class="text-sm text-gray-500 dark:text-gray-400 mt-2">
            Просмотр необработанных данных, синхронизированных с базой данных.
          </p>
        </div>

        <!-- Debug -->
        <div class="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg">
          <h3 class="text-lg font-semibold mb-3 text-gray-900 dark:text-gray-100">Отладка</h3>
          <button @click="router.push('/settings/debug')" class="px-4 py-2 text-sm font-medium text-white bg-slate-600 rounded-md hover:bg-slate-700 transition-colors">
            Панель отладки
          </button>
          <p class="text-sm text-gray-500 dark:text-gray-400 mt-2">
            Логи запросов и ошибок системы.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import ThemeSwitcher from '~/components/ThemeSwitcher.vue'

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
