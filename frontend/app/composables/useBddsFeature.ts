/**
 * Состояние подписки на «БДДС по проектам» — одно на приложение.
 *
 * Общее состояние и запрос НЕ дублируются: и то и другое живёт в
 * useBillingFeature (ключ PORTAL_FEATURES_STATE_KEY, запрос
 * /api/features), потому что ручка ОДНА на все платные функции портала и
 * зовёт её бутстрап приложения (useAppInit.initApp). Здесь только своя
 * трактовка того же ответа: свой код функции и свой аварийный выключатель.
 *
 * Почему не «второй механизм подписки»: его и нет. Второй запрос
 * /api/features из меню и с экрана БДДС означал бы два ответа на вопрос
 * «функция включена?» — ровно то, чего в приложении быть не должно.
 */

import { computed } from 'vue'
import { resolveBddsAccess } from '~/utils/bddsFeature'
import { FINANCE_BDDS_ENABLED } from '~/utils/featureFlags'

export const useBddsFeature = () => {
  const { features, featuresFailed, loadPortalFeatures } = useBillingFeature()

  const access = computed(() => resolveBddsAccess({
    features: features.value,
    flagEnabled: FINANCE_BDDS_ENABLED,
  }))

  return {
    features,
    featuresFailed,
    access,
    loadPortalFeatures,
  }
}
