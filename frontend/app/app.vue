<script setup lang="ts">
import * as locales from '@bitrix24/b24ui-nuxt/locale'
import ProgressOverlay from '~/components/common/ProgressOverlay.vue'
import { useProgress } from '~/composables/useProgress'

// region Init ////
const { locale, defaultLocale } = useI18n()
const lang = computed(() => locales[locale.value]?.code || defaultLocale)
const dir = computed(() => locales[locale.value]?.dir || 'ltr')

useHead({
  htmlAttrs: { lang, dir }
})
// endregion ////

const progress = useProgress()
</script>

<template>
  <B24App :locale="locales[locale]">
    <NuxtLoadingIndicator color="var(--ui-color-design-filled-warning-bg)" :height="3" />
    <B24DashboardGroup>
      <NuxtLayout>
        <NuxtPage />
      </NuxtLayout>
    </B24DashboardGroup>
    <ProgressOverlay :visible="progress.active.value" :title="progress.state.title" :done="progress.state.done" :total="progress.state.total" />
  </B24App>
</template>
