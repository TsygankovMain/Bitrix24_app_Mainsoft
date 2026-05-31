<script setup lang="ts">
import type { ProgressProps } from '@bitrix24/b24ui-nuxt'
import type { IStep } from '#shared/types/base'
import type { B24Frame } from '@bitrix24/b24jssdk'
import { ref, onMounted } from 'vue'
import { sleepAction } from '~/utils/sleep'
import { withoutTrailingSlash } from 'ufo'
import Logo from '~/components/Logo.vue'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: t('page.install.seo.title')
})

// region Init ////
const config = useRuntimeConfig()
const appUrl = withoutTrailingSlash(config.public.appUrl)

const { $logger, initLang, processErrorGlobal } = useAppInit('Install')
const { $initializeB24Frame } = useNuxtApp()
const $b24: B24Frame = await $initializeB24Frame()
await initLang($b24, localesI18n, setLocale)

const confetti = useConfetti()

const isShowDebug = ref(false)

const progressColor = ref<ProgressProps['color']>('air-primary')
const progressValue = ref<null | number>(null)

const apiStore = useApiStore()
// endregion ////

// region Steps ////
const steps = ref<Record<string, IStep>>({
  init: {
    caption: t('page.install.step.init.caption'),
    action: makeInit
  },
  demo: {
    caption: t('page.install.step.demo.caption'),
    action: async () => {
      return sleepAction(1000)
    }
  },
  // events: {
  //   caption: t('page.install.step.events.caption'),
  //   action: async () => {
  //     /**
  //      * Registering onAppInstall | onAppUninstall
  //      */
  //     await $b24.callBatch([
  //       {
  //         method: 'event.unbind',
  //         params: {
  //           event: 'ONAPPINSTALL',
  //           handler: `${appUrl}/api/event/onAppInstall`
  //         }
  //       },
  //       {
  //         method: 'event.unbind',
  //         params: {
  //           event: 'ONAPPUNINSTALL',
  //           handler: `${appUrl}/api/event/onAppUninstall`
  //         }
  //       },
  //       {
  //         method: 'event.bind',
  //         params: {
  //           event: 'ONAPPINSTALL',
  //           handler: `${appUrl}/api/event/onAppInstall`
  //         }
  //       },
  //       {
  //         method: 'event.bind',
  //         params: {
  //           event: 'ONAPPUNINSTALL',
  //           handler: `${appUrl}/api/event/onAppUninstall`
  //         }
  //       }
  //     ])
  //   }
  // },

  // --- Финансовый функционал (в планах) изолирован ---
  // Регистрация встройки `project_finance_embed` (финансовый таб в карточке сделки) отключена,
  // т.к. бэкенд-эндпоинты finance отключены (см. backends/python/api/main/urls.py).
  // Страница-обработчик /handler/placement-crm-deal-detail-tab показывает заглушку «в разработке».
  // Для восстановления: раскомментировать шаг ниже.
  // userFields: {
  //   caption: t('page.install.step.userFields.caption'),
  //   action: async () => {
  //     const typeId = `project_finance_embed_${import.meta.dev ? 'dev' : 'prod'}`
  //     const commonParams = {
  //       USER_TYPE_ID: typeId,
  //       HANDLER: `${appUrl}/handler/placement-crm-deal-detail-tab`,
  //       TITLE: 'Финансы проекта (сделка)',
  //       DESCRIPTION: 'Встройка для создания доходов и расходов проекта прямо из сделки',
  //       OPTIONS: {
  //         height: 640
  //       }
  //     }
  //
  //     const exists = (steps.value.init?.data?.userFieldTypeList as { USER_TYPE_ID: string }[]).some(item => item.USER_TYPE_ID === typeId)
  //     if (exists) {
  //       await $b24.callBatch([
  //         {
  //           method: 'userfieldtype.update',
  //           params: commonParams
  //         }
  //       ], false)
  //
  //       return
  //     }
  //
  //     await $b24.callBatch([
  //       {
  //         method: 'userfieldtype.add',
  //         params: commonParams
  //       }
  //     ], false)
  //   }
  // },
  // crm: {
  //   caption: t('page.install.step.crm.caption'),
  //   action: async () => {
  //     /**
  //      * Some actions for crm
  //      */
  //     if (steps.value.crm) {
  //       steps.value.crm.data = {
  //         par31: 'val31',
  //         par32: 'val32'
  //       }
  //     }
  //     return sleepAction()
  //   }
  // },
  serverSide: {
    caption: t('page.install.step.serverSide.caption'),
    action: async () => {
      const authData = $b24.auth.getAuthData() as Record<string, any> | false

      if(authData === false) {
        throw new Error('Some problem with auth. See App logic')
      }

      const rawPlacementInfo = (() => {
        try {
          return (window as any)?.BX24?.placement?.info?.() || {}
        } catch {
          return {}
        }
      })() as Record<string, any>

      const legacyAuth = (() => {
        try {
          return (window as any)?.BX24?.getAuth?.() || {}
        } catch {
          return {}
        }
      })() as Record<string, any>

      const accessToken = String(
        authData.access_token
        || authData.AUTH_ID
        || rawPlacementInfo.AUTH_ID
        || legacyAuth.AUTH_ID
        || legacyAuth.access_token
        || ''
      ).trim()

      const refreshToken = String(
        authData.refresh_token
        || authData.REFRESH_ID
        || rawPlacementInfo.REFRESH_ID
        || legacyAuth.REFRESH_ID
        || legacyAuth.refresh_token
        || ''
      ).trim()

      const memberId = String(
        authData.member_id
        || rawPlacementInfo.MEMBER_ID
        || legacyAuth.member_id
        || ''
      ).trim()

      if (!accessToken) {
        throw new Error('Install auth payload is missing AUTH_ID/access_token')
      }

      await apiStore.postInstall({
        DOMAIN: withoutTrailingSlash(String(authData.domain || rawPlacementInfo.DOMAIN || '')).replace('https://', '').replace('http://', ''),
        PROTOCOL: Number(rawPlacementInfo.PROTOCOL || (String(authData.domain || '').includes('https://') ? 1 : 0)),
        LICENSE: steps.value.init?.data?.appInfo.LICENSE,
        LICENSE_FAMILY: steps.value.init?.data?.appInfo.LICENSE_FAMILY,
        LANG: $b24.getLang(),
        APP_SID: $b24.getAppSid(),
        AUTH_ID: accessToken,
        AUTH_EXPIRES: Number(authData.expires_in || rawPlacementInfo.AUTH_EXPIRES || 0),
        REFRESH_ID: refreshToken,
        REFRESH_TOKEN: refreshToken,
        member_id: memberId,
        user_id: Number(steps.value.init?.data?.profile.ID),
        status: steps.value.init?.data?.appInfo.STATUS,
        appVersion: Number(steps.value.init?.data?.appInfo.VERSION),
        appCode: steps.value.init?.data?.appInfo.CODE,
        appId: Number(steps.value.init?.data?.appInfo.ID),
        PLACEMENT: $b24.placement.title,
        PLACEMENT_OPTIONS: $b24.placement.options
      })
    }
  },
  finish: {
    caption: t('page.install.step.finish.caption'),
    action: makeFinish
  }
})
const stepCode = ref<string>('init' as const)
// endregion ////

// region Actions ////
async function makeInit(): Promise<void> {
  if (steps.value.init) {
    const response = await $b24.callBatch({
      appInfo: { method: 'app.info' },
      profile: { method: 'profile' },
      userFieldTypeList: { method: 'userfieldtype.list' },
      placementList: { method: 'placement.get' }
    })

    steps.value.init.data = response.getData() as {
      appInfo: {
        ID: number
        CODE: string
        VERSION: string
        STATUS: string
        LICENSE: string
        LICENSE_FAMILY: string
        INSTALLED: boolean
      },
      profile: {
        ID: number
        ADMIN: boolean
        LAST_NAME?: string
        NAME?: string
      }
      userFieldTypeList: {
        USER_TYPE_ID: string
        HANDLER: string
        TITLE: string
        DESCRIPTION: string
      }[]
      placementList: {
        placement: string
        userId: number
        handler: string
        options: any
        title: string
        description: string
      }[]
    }
  }
}

async function makeFinish(): Promise<void> {
  progressColor.value = 'air-primary-success'
  progressValue.value = 100

  confetti.fire()
  await sleepAction(3000)

  await $b24.installFinish()
}

const stepsData = computed(() => {
  return Object.entries(steps.value).map(([index, row]) => {
    return {
      step: index,
      data: row?.data
    }
  })
})
// endregion ////

// region Lifecycle Hooks ////
onMounted(async () => {
  $logger.info('Hi from install page')

  try {
    await $b24.parent.setTitle(t('page.install.seo.title'))

    for (const [key, step] of Object.entries(steps.value)) {
      stepCode.value = key
      await step.action()
    }
  } catch (error: any) {
    processErrorGlobal(error)
  }
})
// endregion ////
</script>

<template>
  <div class="mx-auto px-6 w-full flex flex-col items-center justify-center gap-1 h-dvh">
    <Logo
      class="size-[208px]"
      :class="[
        stepCode === 'finish' ? 'text-(--ui-color-accent-main-success)' : 'text-(--ui-color-accent-soft-green-1)'
      ]"
    />
    <B24Progress
      v-model="progressValue"
      size="xs"
      animation="elastic"
      :color="progressColor"
      class="w-full"
    />
    <div class="mt-6 flex flex-col items-center justify-center gap-2">
      <ProseH1 class="text-nowrap mb-0">
        {{ $t('page.install.ui.title') }}
      </ProseH1>
      <ProseP small>
        {{ steps[stepCode]?.caption || '...' }}
      </ProseP>
    </div>

    <ProsePre v-if="isShowDebug">
      {{ stepsData }}
    </ProsePre>
  </div>
</template>
