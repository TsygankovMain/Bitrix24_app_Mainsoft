/**
 * Состояние платных функций портала — одно на приложение.
 *
 * Один запрос GET /api/features на все функции (bdds, billing, roles) и одно
 * общее состояние (useState). Спрашивает бутстрап (useAppInit.initApp) —
 * единственная точка, после которой гарантированно есть JWT; меню и экраны
 * только читают готовое значение. Второй запрос /api/features из экрана
 * означал бы два ответа на вопрос «функция включена?».
 *
 * Отказ /api/features НЕ роняет приложение: запоминаем «не ответила» и
 * оставляем функции закрытыми — замок вместо ложного обещания.
 *
 * Трактовка ответа по функции — usePaidFeature(code) и обёртки
 * useBillingFeature / useBddsFeature.
 */

import { parsePortalFeatures, type PortalFeatureInfo } from '~/utils/featureAccess'

/** Ключи общего состояния. Строки, а не Symbol: useState требует строку. */
export const PORTAL_FEATURES_STATE_KEY = 'app-portal-features'
export const PORTAL_FEATURES_FAILED_STATE_KEY = 'app-portal-features-failed'

/**
 * Запрос «в полёте». Модульная переменная, а не useState: её задача — не дать
 * двум экранам, смонтированным подряд, послать один и тот же запрос дважды.
 */
let featuresRequest: Promise<void> | null = null

export const usePortalFeatures = () => {
  const apiStore = useApiStore()

  const features = useState<Record<string, PortalFeatureInfo> | null>(
    PORTAL_FEATURES_STATE_KEY,
    () => null
  )
  const featuresFailed = useState<boolean>(PORTAL_FEATURES_FAILED_STATE_KEY, () => false)

  /** Ошибку намеренно НЕ пробрасываем: отказ не должен мешать работать с часами. */
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

  return {
    features,
    featuresFailed,
    loadPortalFeatures,
  }
}
