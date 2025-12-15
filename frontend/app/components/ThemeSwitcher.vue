<template>
  <div class="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg">
    <h3 class="text-lg font-semibold mb-3 text-gray-900 dark:text-gray-100">Тема оформления</h3>
    <div class="flex items-center space-x-2">
      <button
        @click="setTheme('light')"
        :class="['px-4 py-2 rounded-md text-sm font-medium transition-colors',
          theme === 'light' ? 'bg-blue-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600'
        ]"
      >
        Светлая
      </button>
      <button
        @click="setTheme('dark')"
        :class="['px-4 py-2 rounded-md text-sm font-medium transition-colors',
          theme === 'dark' ? 'bg-blue-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600'
        ]"
      >
        Темная
      </button>
      <button
        @click="setTheme('system')"
        :class="['px-4 py-2 rounded-md text-sm font-medium transition-colors',
          theme === 'system' ? 'bg-blue-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600'
        ]"
      >
        Системная
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useTheme } from '~/composables/useTheme'

const { theme, setTheme } = useTheme()
</script>
