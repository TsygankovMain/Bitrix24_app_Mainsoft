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
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import ThemeSwitcher from '~/components/ThemeSwitcher.vue'

const router = useRouter()

useHead({
  title: 'Настройки'
})

// The useTheme composable is called within ThemeSwitcher,
// but we could also call it here if the page needed direct access to the theme state.
</script>
