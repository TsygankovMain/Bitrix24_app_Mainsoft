/**
 * Права текущего человека — одни на приложение.
 *
 * Два источника, и у каждого своя роль:
 *  - РЕЖИМ ролевой модели — общее состояние подписки (usePaidFeature('roles'),
 *    GET /api/features): access.restrictionsActive говорит, действуют ли
 *    ограничения ролей (при Pro и после его окончания), access.canWrite —
 *    можно ли менять роли;
 *  - ПРАВА человека — GET /api/roles/me: сервер считает их по ролям из нашей
 *    БД (main/roles.py) и ровно по ним же отказывает. Второй расчёт матрицы
 *    на клиенте разошёлся бы с сервером при первой её правке.
 *
 * Почему права не в бутстрапе (useAppInit.initApp). Они нужны экранам денег и
 * настроек, а initApp зовёт и вкладка задачи, открываемая десятки раз в день.
 * Экран, которому права нужны, спрашивает сам после initApp; ответ живёт в
 * useState и второй раз не запрашивается.
 *
 * Пока ответа нет — или ручка не ответила — права угадываются по режиму и
 * признаку администратора портала (resolveUiPermissions). Отказ ручки не
 * роняет экран.
 */

import { computed } from 'vue'
import { canEditAppSettings, parseRolesMe, resolveUiPermissions, type RolesMe } from '~/utils/appRoles'

export const ROLES_ME_STATE_KEY = 'app-roles-me'
export const ROLES_ME_FAILED_STATE_KEY = 'app-roles-me-failed'

let meRequest: Promise<void> | null = null

export const useAppPermissions = () => {
  const apiStore = useApiStore()
  const userStore = useUserStore()
  const { access: rolesAccess } = usePaidFeature('roles')

  const me = useState<RolesMe | null>(ROLES_ME_STATE_KEY, () => null)
  const failed = useState<boolean>(ROLES_ME_FAILED_STATE_KEY, () => false)

  const loadPermissions = async (force = false): Promise<void> => {
    if (me.value && !force) {
      return
    }
    if (meRequest) {
      await meRequest
      return
    }

    meRequest = (async () => {
      try {
        me.value = parseRolesMe(await apiStore.getRolesMe())
        failed.value = me.value === null
      } catch {
        failed.value = true
      }
    })().finally(() => {
      meRequest = null
    })

    await meRequest
  }

  /** Действуют ли ограничения ролей — по подписке, не по canWrite. */
  const restrictionsActive = computed(() => rolesAccess.value.restrictionsActive)

  const permissions = computed(() => resolveUiPermissions({
    me: me.value,
    isAdmin: Boolean(userStore.isAdmin),
    restrictionsActive: restrictionsActive.value,
  }))

  const canEditSettings = computed(() => canEditAppSettings(
    me.value,
    Boolean(userStore.isAdmin),
    restrictionsActive.value
  ))

  /**
   * Суммы закрыты для этого человека: ограничения ролей действуют и сервер
   * сказал, что права money_view нет. Догадка экран не закрывает.
   */
  const moneyDenied = computed(() => restrictionsActive.value
    && permissions.value.known
    && !permissions.value.money_view)

  return {
    me,
    failed,
    rolesAccess,
    restrictionsActive,
    permissions,
    canEditSettings,
    moneyDenied,
    loadPermissions,
  }
}
