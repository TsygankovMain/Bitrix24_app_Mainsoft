<script setup lang="ts">
import * as locales from '@bitrix24/b24ui-nuxt/locale'

// region Init ////
const { locale, defaultLocale } = useI18n()
const lang = computed(() => locales[locale.value]?.code || defaultLocale)
const dir = computed(() => locales[locale.value]?.dir || 'ltr')

useHead({
  htmlAttrs: { lang, dir }
})
// endregion ////
</script>

<template>
  <B24App :locale="locales[locale]">
    <NuxtLoadingIndicator color="var(--ui-color-design-filled-warning-bg)" :height="3" />
    <B24DashboardGroup>
      <NuxtLayout>
        <NuxtPage />
      </NuxtLayout>
    </B24DashboardGroup>
  </B24App>
</template>

<style>
/* Force fluid layout — override B24 UI library width constraints */
.b24-dashboard-group,
[class*="b24-dashboard"],
[class*="b24-sidebar-layout"] {
  max-width: 100% !important;
  width: 100% !important;
}

.b24-sidebar-layout__content,
[class*="sidebar-layout__content"] {
  max-width: 100% !important;
  width: 100% !important;
}
</style>
