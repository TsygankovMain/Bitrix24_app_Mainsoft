/**
 * Состояние подписки на «Счёт и акт» и права человека — одно на приложение.
 *
 * Почему useState, а не ref в компоненте: состояние нужно и постоянному меню
 * (components/nav/SectionNavigation.vue, живёт в лейауте), и экранам функции.
 * Меню рисуется РАНЬШЕ, чем приложение получило JWT, — свой запрос оттуда
 * ушёл бы без авторизации. Поэтому спрашивает тот, кто и так прошёл бутстрап
 * (useAppInit.initApp), а меню только читает готовое значение. Тот же приём,
 * что у счётчика проблем «Контроля» (NAV_CONTROL_ISSUES_STATE_KEY).
 *
 * Отказ /api/features НЕ роняет приложение. Пока бэкенда нет, эта ручка
 * отвечает 404 — и это не повод показать фатальный экран на главной или во
 * вкладке задачи. Мы запоминаем «не ответила» и оставляем функцию закрытой:
 * замок вместо ложного обещания.
 */

import { computed } from 'vue'
import {
  isBillingManager,
  parsePortalFeatures,
  resolveBillingAccess,
  resolveBillingUiPermissions,
  type PortalFeatureInfo,
} from '~/utils/billingFeature'
import { readBillingSettings } from '~/utils/billingSettings'
import { FINANCE_BILLING_ENABLED } from '~/utils/featureFlags'

/** Ключи общего состояния. Строки, а не Symbol: useState требует строку. */
export const PORTAL_FEATURES_STATE_KEY = 'app-portal-features'
export const PORTAL_FEATURES_FAILED_STATE_KEY = 'app-portal-features-failed'
export const BILLING_ACCOUNTANTS_STATE_KEY = 'app-billing-accountants'
/**
 * Настройка «Разрешить выставление за открытый период».
 *
 * Читается тем же запросом конфигурации, что и список «Бухгалтерия», и живёт
 * рядом с ним: мастеру она нужна, чтобы не предлагать снять галочку «только
 * закрытые месяцы», когда сервер всё равно откажет (контракт, правило 3).
 */
export const BILLING_ALLOW_OPEN_PERIOD_STATE_KEY = 'app-billing-allow-open-period'
/**
 * Настройка «наше юрлицо по умолчанию».
 *
 * Мастеру она нужна ДО первого предпросмотра: поле «Наше юрлицо» в отборе
 * при заданной настройке перестаёт быть выбором стороны счёта и остаётся
 * только фильтром часов, и подписать его надо честно. Само юрлицо счёта
 * приходит с ответом preview (our_company_source) — решает сервер, а не эта
 * копия настройки.
 */
export const BILLING_OUR_COMPANY_STATE_KEY = 'app-billing-our-company'

/**
 * Запросы «в полёте».
 *
 * Модульные переменные, а не useState: их задача — не дать двум экранам,
 * смонтированным подряд, послать один и тот же запрос дважды (ровно та же
 * причина, по которой в api.ts дедуплицируется getToken).
 */
let featuresRequest: Promise<void> | null = null
let settingsRequest: Promise<void> | null = null

export const useBillingFeature = () => {
  const apiStore = useApiStore()
  const userStore = useUserStore()

  const features = useState<Record<string, PortalFeatureInfo> | null>(
    PORTAL_FEATURES_STATE_KEY,
    () => null
  )
  const featuresFailed = useState<boolean>(PORTAL_FEATURES_FAILED_STATE_KEY, () => false)
  /** null — список «Бухгалтерия» ещё не читали (конфигурация не загружена). */
  const accountantIds = useState<string[] | null>(BILLING_ACCOUNTANTS_STATE_KEY, () => null)
  /** Разрешает ли портал выставлять за незакрытый месяц. До ответа — нет. */
  const allowOpenPeriod = useState<boolean>(BILLING_ALLOW_OPEN_PERIOD_STATE_KEY, () => false)
  /** Наше юрлицо из настроек приложения; пустой id — берётся из карточки. */
  const ourCompany = useState<{ id: string, name: string }>(
    BILLING_OUR_COMPANY_STATE_KEY,
    () => ({ id: '', name: '' })
  )

  /**
   * Состояния платных функций портала.
   *
   * Ошибку намеренно НЕ пробрасываем: функция зовётся из бутстрапа каждой
   * страницы, и отказ этой ручки не должен мешать работать с часами и
   * отчётами.
   */
  const loadPortalFeatures = async (force = false): Promise<void> => {
    if (features.value && !force) {
      return
    }

    if (featuresRequest) {
      await featuresRequest
      return
    }

    featuresRequest = (async () => {
      try {
        const payload = await apiStore.getFeatures(force)
        features.value = parsePortalFeatures(payload)
        featuresFailed.value = false
      } catch {
        featuresFailed.value = true
      }
    })().finally(() => {
      featuresRequest = null
    })

    await featuresRequest
  }

  /**
   * Список «Бухгалтерия» из настроек приложения.
   *
   * Нужен только экранам функции, поэтому в бутстрап не входит: лишний
   * запрос конфигурации на каждой странице приложения ради кнопки, которой
   * там нет, не нужен. Отказ трактуем как «список пуст» — тогда выставлять
   * сможет только админ портала, то есть ошибаемся в строгую сторону.
   */
  const loadBillingSettings = async (force = false): Promise<void> => {
    if (accountantIds.value && !force) {
      return
    }

    if (settingsRequest) {
      await settingsRequest
      return
    }

    settingsRequest = (async () => {
      try {
        const config = await apiStore.getConfiguration(force)
        const settings = readBillingSettings(config)
        accountantIds.value = settings.accountantIds
        allowOpenPeriod.value = settings.allowOpenPeriod
        ourCompany.value = { id: settings.ourCompanyId, name: settings.ourCompanyName }
      } catch {
        accountantIds.value = []
        allowOpenPeriod.value = false
        // Отказ конфигурации — это «настройка неизвестна», и трактуем её как
        // незаданную: юрлицо счёта всё равно решает сервер, а интерфейс не
        // должен обещать подмену, которой может не быть.
        ourCompany.value = { id: '', name: '' }
      }
    })().finally(() => {
      settingsRequest = null
    })

    await settingsRequest
  }

  /** Открыт ли экран. Флаг из featureFlags остаётся аварийным выключателем. */
  const access = computed(() => resolveBillingAccess({
    features: features.value,
    flagEnabled: FINANCE_BILLING_ENABLED,
  }))

  const isManager = computed(() => isBillingManager({
    isAdmin: Boolean(userStore.isAdmin),
    userId: userStore.id,
    accountantIds: accountantIds.value || [],
  }))

  const permissions = computed(() => resolveBillingUiPermissions(access.value, isManager.value))

  return {
    features,
    featuresFailed,
    accountantIds,
    allowOpenPeriod,
    ourCompany,
    access,
    isManager,
    permissions,
    loadPortalFeatures,
    loadBillingSettings,
  }
}
