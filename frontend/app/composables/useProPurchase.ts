/**
 * Текущая заявка на Pro — одна на приложение.
 *
 * Нужна трём местам сразу: кнопке в меню («Счёт ждёт оплаты»), карточке
 * «Подписка» в настройках и самой форме /pro. Один запрос
 * GET /api/pro/requests/current и общее состояние (useState): форма после
 * отправки кладёт сюда свежую заявку, и меню меняется без второго запроса.
 *
 * Отказ ручки ничего не роняет: заявки «нет», кнопка ведёт на форму, а форма
 * сама спросит сервер ещё раз.
 */

import { computed } from 'vue'
import { isOpenProRequest, parseProRequest, type ProRequestView } from '~/utils/proPurchase'

export const PRO_REQUEST_STATE_KEY = 'app-pro-request'
export const PRO_REQUEST_LOADED_STATE_KEY = 'app-pro-request-loaded'

let requestInFlight: Promise<void> | null = null

export const useProPurchase = () => {
  const apiStore = useApiStore()

  const request = useState<ProRequestView | null>(PRO_REQUEST_STATE_KEY, () => null)
  const loaded = useState<boolean>(PRO_REQUEST_LOADED_STATE_KEY, () => false)

  const loadCurrentRequest = async (force = false): Promise<void> => {
    if ((loaded.value && !force) || !apiStore.hasToken) {
      return
    }
    if (requestInFlight) {
      await requestInFlight
      return
    }

    requestInFlight = (async () => {
      try {
        const payload = await apiStore.getProCurrentRequest() as { request?: unknown }
        request.value = parseProRequest(payload?.request)
        loaded.value = true
      } catch {
        // Не помечаем loaded: следующий экран спросит ещё раз.
      }
    })().finally(() => {
      requestInFlight = null
    })

    await requestInFlight
  }

  const setRequest = (value: ProRequestView | null) => {
    request.value = value
    loaded.value = true
  }

  const hasOpenRequest = computed(() => isOpenProRequest(request.value))

  return {
    request,
    loaded,
    hasOpenRequest,
    loadCurrentRequest,
    setRequest,
  }
}
