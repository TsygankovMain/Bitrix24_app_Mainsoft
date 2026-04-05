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
        @click="setTheme('light')"
        :class="['ms-tab-btn',
          theme === 'light' ? 'ms-tab-btn-active' : ''
        ]"
      >
        Светлая
      </button>
      <button
        @click="setTheme('dark')"
        :class="['ms-tab-btn',
          theme === 'dark' ? 'ms-tab-btn-active' : ''
        ]"
      >
        Темная
      </button>
      <button
        @click="setTheme('system')"
        :class="['ms-tab-btn',
          theme === 'system' ? 'ms-tab-btn-active' : ''
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
