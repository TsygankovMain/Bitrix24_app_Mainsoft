<template>
  <div class="ms-panel">
    <div class="ms-toolbar">
      <div>
        <h3 class="text-base font-semibold text-slate-900">Тема оформления</h3>
        <p class="mt-1 text-sm text-slate-500">Персональная настройка отображения интерфейса.</p>
      </div>
    </div>
    <div class="ms-tabbar mt-4">
      <button
        :class="['ms-tab-btn',
          theme === 'light' ? 'ms-tab-btn-active' : ''
        ]"
        @click="setTheme('light')"
      >
        Светлая
      </button>
      <button
        :class="['ms-tab-btn',
          theme === 'dark' ? 'ms-tab-btn-active' : ''
        ]"
        @click="setTheme('dark')"
      >
        Темная
      </button>
      <button
        :class="['ms-tab-btn',
          theme === 'system' ? 'ms-tab-btn-active' : ''
        ]"
        @click="setTheme('system')"
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
