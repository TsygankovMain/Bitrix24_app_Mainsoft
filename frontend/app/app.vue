<script setup lang="ts">
import * as locales from '@bitrix24/b24ui-nuxt/locale'
import AppOutdatedBanner from '~/components/common/AppOutdatedBanner.vue'
import EnvLabelBadge from '~/components/common/EnvLabelBadge.vue'
import ProgressOverlay from '~/components/common/ProgressOverlay.vue'
import { useProgress } from '~/composables/useProgress'
import { normalizeEnvLabel, withEnvLabel } from '~/utils/envLabel'

// region Init ////
const { locale, defaultLocale } = useI18n()
const lang = computed(() => locales[locale.value]?.code || defaultLocale)
const dir = computed(() => locales[locale.value]?.dir || 'ltr')
const envLabel = normalizeEnvLabel(useRuntimeConfig().public.envLabel)

useHead({
  htmlAttrs: { lang, dir },
  titleTemplate: title => withEnvLabel(title || '', envLabel)
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
    <ProgressOverlay :visible="progress.active.value" :title="progress.state.title" :hint="progress.state.hint" :done="progress.state.done" :total="progress.state.total" />
    <AppOutdatedBanner />
    <EnvLabelBadge />
  </B24App>
</template>
