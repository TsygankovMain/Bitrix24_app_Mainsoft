<script setup lang="ts">
import type { NuxtError } from '#app'
import { createError as createH3Error } from "h3"
import EnvLabelBadge from '~/components/common/EnvLabelBadge.vue'
import { normalizeEnvLabel, withEnvLabel } from '~/utils/envLabel'

const props = defineProps<{
  error: NuxtError
}>()

// Экран ошибки рендерится вместо app.vue, поэтому метку стенда ставим и здесь
const envLabel = normalizeEnvLabel(useRuntimeConfig().public.envLabel)

useHead({
  meta: [
    { name: 'viewport', content: 'width=device-width, initial-scale=1' }
  ],
  link: [],
  htmlAttrs: { lang: 'en' },
  titleTemplate: title => withEnvLabel(title || '', envLabel)
})

const getError = computed(() => {
  if (props?.error?.message === 'Unable to initialize Bitrix24Frame library!') {
    return createH3Error({
      statusCode: 500,
      statusMessage: 'Well done!',
      message: 'Now paste this URL into the B24 app settings',
      cause: props?.error
    })
  }

  return props?.error
})

console.log(props?.error.message)
</script>

<template>
  <B24App>
    <NuxtLoadingIndicator color="var(--ui-color-accent-main-primary)" :height="2" />

    <B24SidebarLayout :use-light-content="false">
      <B24Card class="mt-[2px]">
        <B24Error
          :error="getError"
          :clear="false"
        />
      </B24Card>
    </B24SidebarLayout>
    <EnvLabelBadge />
  </B24App>
</template>
