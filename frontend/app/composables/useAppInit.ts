import {computed, type ComputedRef, ref} from "vue";
import { LoggerBrowser, AjaxError, LoadDataType, useB24Helper } from '@bitrix24/b24jssdk'
import type { B24Frame } from '@bitrix24/b24jssdk'
import type { Locale } from 'vue-i18n'
import type { LocaleObject } from '@nuxtjs/i18n'
import { markRateLimitFatal, RATE_LIMIT_NOTICE_TEXT, shouldTreatAsFatalError } from '~/utils/apiErrors'

export interface ProcessErrorData {
  description?: string
  isShowClearError?: boolean
  clearErrorHref?: string
  clearErrorTitle?: string
  homePageIsHide?: boolean
  homePageHref?: string
  homePageTitle?: string
}

const { initB24Helper, getB24Helper, destroyB24Helper: destroyB24HelperOry, usePullClient, useSubscribePullClient, startPullClient } = useB24Helper()
const isInitB24Helper = ref(false)

const moduleId = 'main'

/**
 * Composable handling application initialization
 * Coordinates data loading via batch request
 */
export const useAppInit = (loggerTitle?: string) => {
  const $logger = LoggerBrowser.build(
    loggerTitle ?? 'App',
    import.meta.dev
  )

  // Stores
  const appSettings = useAppSettingsStore()
  const userSettings = useUserSettingsStore()
  const user = useUserStore()
  const api = useApiStore()

  /**
   * Initialize application data
   * Performs batch request and updates all stores
   */
  async function initApp(
    $b24: B24Frame,
    localesI18n: ComputedRef<LocaleObject[]>,
    setLocale: (locale: Locale) => Promise<void>
  ) {
    $logger.info('InitApp start')
    await initLang($b24, localesI18n, setLocale)

    if (!isInitB24Helper.value) {
      const loadTypes = [
        LoadDataType.App,
        LoadDataType.AppOptions,
        LoadDataType.UserOptions,
        LoadDataType.Currency,
        LoadDataType.Profile
      ]
      try {
        await initB24Helper($b24, loadTypes)
      } catch {
        // Network can be unstable in embedded mode; retry once before failing hard.
        $logger.warn('InitApp initB24Helper first attempt failed, retrying once')
        await new Promise((resolve) => setTimeout(resolve, 250))
        await initB24Helper($b24, loadTypes)
      }
      isInitB24Helper.value = true
    } else {
      // Reuse helper data on client-side route changes to avoid duplicate SDK bootstrap calls.
      $logger.log('InitApp reuse existing B24 helper')
    }

    const helper = getB24Helper()
    if (!helper) {
      throw new Error('B24 helper is not initialized')
    }

    const data = {
      appInfo: helper.appInfo,
      appSettings: helper.appOptions,
      userSettings: helper.userOptions,
      profileData: helper.profileInfo,
    }
    $logger.log('Init data >>', data)

    /**
     * @memo This can be used instead of `initB24Helper`
     */
    // const commands = {
    //   appInfo: { method: 'app.info' },
    //   appSettings: { method: 'app.option.get' },
    //   userSettings: { method: 'user.option.get' },
    //   profileData: { method: 'profile' }
    // }
    //
    // const response = await $b24.callBatch(commands)
    //
    // const data = response.getData()
    // $logger.log('Init data >>', data)

    // Update stores with received data
    user.initFromBatch({
      id: data.profileData?.data.id ?? undefined,
      name: data.profileData?.data.name ?? undefined,
      lastName: data.profileData?.data.lastName ?? undefined,
      isAdmin: data.profileData?.data.isAdmin
    })

    appSettings.setB24($b24)
    appSettings.initFromBatch({
      version: (data.appInfo?.data.version ?? 1),
      status: data.appInfo?.data.status,
      configSettings: (data.appSettings?.data ?? new Map()).get('configSettings')
    })

    userSettings.setB24($b24)
    userSettings.initFromBatch({
      configSettings: (data.userSettings?.data ?? new Map()).get('configSettings')
    })

    try {
      await api.init($b24)
    } catch (error) {
      // api.init() -> reinitToken() -> getToken() — единственный $api-вызов
      // здесь, за ним get_token (@rate_limit("get_token", 10, 60,
      // key="ip_domain") — backends/python/api/main/views.py). initApp()
      // вызывается из onMounted буквально каждой страницы (не только из
      // /install — там свой бутстрап через apiStore.postInstall, get_token
      // не использует), так что это тоже подпадает под общий инвариант
      // «429 не фатален по умолчанию» (processErrorGlobal ниже). Но здесь
      // особый случай: без валидного JWT ни один другой $api-запрос в
      // приложении не пройдёт, так что лёгкое уведомление оставило бы
      // человека на пустом/сломанном экране без объяснения — фатальный
      // экран тут осознанно лучше. Явный, видимый в коде опт-ин обратно в
      // старое поведение (см. markRateLimitFatal/shouldTreatAsFatalError в
      // apiErrors.ts), а не забытая точка.
      throw markRateLimitFatal(error)
    }

    $logger.info('InitApp stop')
  }

  async function initLang(
    $b24: B24Frame,
    localesI18n: ComputedRef<LocaleObject[]>,
    setLocale: (locale: Locale) => Promise<void>
  ) {
    const b24CurrentLang = $b24.getLang()
    if (localesI18n.value.filter(i => i.code === b24CurrentLang).length > 0) {
      await setLocale(b24CurrentLang)
      $logger.log('setLocale >>>', b24CurrentLang)
    } else {
      $logger.warn('not support locale >>>', b24CurrentLang)
    }
  }

  /**
   * Reloads data
   */
  async function reloadData() {
    await b24Helper.value?.loadData([
      LoadDataType.AppOptions,
      LoadDataType.UserOptions,
      LoadDataType.Currency
    ])

    const data = {
      appSettings: getB24Helper().appOptions,
      userSettings: getB24Helper().userOptions
    }

    $logger.log('Reload data >>', data)

    // Update stores with received data
    appSettings.initFromBatch({
      configSettings: (data.appSettings?.data ?? new Map()).get('configSettings')
    })

    userSettings.initFromBatch({
      configSettings: (data.userSettings?.data ?? new Map()).get('configSettings')
    })

    $logger.info('reloadData stop')
  }

  const b24Helper = computed(() => {
    if (isInitB24Helper.value) {
      return getB24Helper()
    }

    return null
  })

  const destroyB24Helper = () => {
    isInitB24Helper.value = false
    destroyB24HelperOry()
  }

  function processErrorGlobal(
    error: unknown | string | Error,
    processErrorData?: ProcessErrorData
  ) {
    $logger.error(error)

    if (!shouldTreatAsFatalError(error)) {
      // Централизованная безопасная реакция на HTTP 429 (см.
      // shouldTreatAsFatalError в apiErrors.ts — единственный источник этого
      // решения, и .superpowers/sdd/2026-07-28-project-references-from-db/critical-429-central-report.md).
      // Лёгкое самоочищающееся уведомление вместо showError({fatal:true})
      // (frontend/app/error.vue, :clear="false", без пути лёгкого возврата)
      // покрывает ЛЮБОЙ вызывающий код, который просто зовёт
      // processErrorGlobal(e) в catch, ничего специально не делая, — то
      // есть все текущие и будущие экраны с лимитером «по построению», а не
      // только те, что чинили точечно (frontend/app/pages/projects/index.client.vue).
      const toast = useToast()
      toast.add({ title: RATE_LIMIT_NOTICE_TEXT, color: 'air-primary-warning' })
      return
    }

    let statusMessage = 'Error'
    let message = ''
    let statusCode = 404

    if (error instanceof AjaxError) {
      statusCode = error.status
      statusMessage = error.name
      message = `${error.message}`
    } else if (error instanceof Error) {
      message = error.message
    } else {
      message = error as string
    }

    showError({
      statusCode,
      statusMessage,
      message,
      data: Object.assign({}, (processErrorData ?? {})),
      cause: error,
      fatal: true
    })
  }

  return {
    $logger,
    moduleId,
    initApp,
    initLang,
    reloadData,
    b24Helper,
    usePullClient,
    useSubscribePullClient,
    startPullClient,
    destroyB24Helper,
    processErrorGlobal
  }
}
