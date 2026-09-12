/**
 * Подписка на «Счёт и акт» и права человека — одно на приложение.
 *
 * Состояние платных функций и запрос /api/features живут в
 * usePortalFeatures (один ответ на все функции); loadPortalFeatures и
 * features отдаются отсюда как раньше — их зовёт бутстрап
 * (useAppInit.initApp). Здесь своё: трактовка ответа для счёта и настройки
 * «Бухгалтерии» из конфигурации портала.
 */

import { computed } from 'vue'
import {
  isBillingManager,
  resolveBillingAccess,
  resolveBillingUiPermissions,
} from '~/utils/billingFeature'
import { readBillingSettings } from '~/utils/billingSettings'
import { FINANCE_BILLING_ENABLED } from '~/utils/featureFlags'

/** Ключи общего состояния. Строки, а не Symbol: useState требует строку. */
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
let settingsRequest: Promise<void> | null = null

export const useBillingFeature = () => {
  const apiStore = useApiStore()
  const userStore = useUserStore()
  // Права «выставлять» решает ролевая модель на сервере (/api/roles/me).
  // Список «Бухгалтерия» из конфигурации остаётся запасной догадкой, пока
  // ответа нет: сервер после переноса списка в роли его уже не читает.
  const { permissions: appPermissions, loadPermissions } = useAppPermissions()

  const { features, featuresFailed, loadPortalFeatures } = usePortalFeatures()
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
   * Список «Бухгалтерия» из настроек приложения.
   *
   * Нужен только экранам функции, поэтому в бутстрап не входит: лишний
   * запрос конфигурации на каждой странице приложения ради кнопки, которой
   * там нет, не нужен. Отказ трактуем как «список пуст» — тогда выставлять
   * сможет только админ портала, то есть ошибаемся в строгую сторону.
   */
  const loadBillingSettings = async (force = false): Promise<void> => {
    // Права грузятся рядом с настройками: оба ответа нужны одним и тем же
    // экранам, а отказ ручки прав не мешает настройкам (и наоборот).
    const permissionsRequest = loadPermissions(force)

    if (accountantIds.value && !force) {
      await permissionsRequest
      return
    }

    if (settingsRequest) {
      await Promise.all([settingsRequest, permissionsRequest])
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

    await Promise.all([settingsRequest, permissionsRequest])
  }

  /** Открыт ли экран. Флаг из featureFlags остаётся аварийным выключателем. */
  const access = computed(() => resolveBillingAccess({
    features: features.value,
    flagEnabled: FINANCE_BILLING_ENABLED,
  }))

  const isManager = computed(() => appPermissions.value.known
    ? appPermissions.value.billing_issue
    : isBillingManager({
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
