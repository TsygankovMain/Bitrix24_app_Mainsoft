/**
 * Доступ к любой платной функции по коду: usePaidFeature('roles').
 *
 * Общий вход для функций, у которых нет своей обёртки (ролевая модель и
 * будущие). Состояние и запрос — usePortalFeatures, правило и тексты —
 * resolveFeatureAccess (app/utils/featureAccess.ts). Что получает экран:
 *
 *   access.enabled   — экран открыт (в том числе «только чтение»);
 *   access.canWrite  — можно создавать и изменять;
 *   access.readOnly  — Pro закончился: показывать access.notice, прятать запись;
 *   access.locked    — замок и <PaidFeatureCard feature-id="roles" />;
 *   access.restrictionsActive — применять ли назначенные ограничения ролей.
 *
 * Ролевая модель: при окончании Pro закрыто только назначение и правка ролей
 * (canWrite = false), а ограничения продолжают действовать
 * (restrictionsActive = true). Прятать ставки и деньги — по
 * restrictionsActive, а не по canWrite.
 */

import { computed } from 'vue'
import { resolveFeatureAccess } from '~/utils/featureAccess'
import { isPaidFeatureId, PAID_FEATURES } from '~/utils/paidFeatures'

export const usePaidFeature = (code: string, options: { flagEnabled?: boolean } = {}) => {
  const { features, featuresFailed, loadPortalFeatures } = usePortalFeatures()

  const access = computed(() => resolveFeatureAccess({
    features: features.value,
    code,
    title: isPaidFeatureId(code) ? PAID_FEATURES[code].label : code,
    flagEnabled: options.flagEnabled ?? true,
  }))

  return {
    features,
    featuresFailed,
    access,
    loadPortalFeatures,
  }
}
