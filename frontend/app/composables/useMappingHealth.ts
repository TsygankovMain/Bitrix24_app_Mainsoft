/**
 * Настроено ли сопоставление полей — одно состояние на всё приложение.
 *
 * Зачем: без сопоставления не работает НИЧЕГО — ни запись часов, ни отчёты,
 * ни счета, ни БДДС, — а приложение об этом молчало. Человек открывал отчёт,
 * видел пустую таблицу и считал, что данных нет. Экран настройки при этом
 * лежал за кнопкой в карточке «Конфигурация» внизу страницы настроек, и в
 * меню его не было вовсе.
 *
 * useState, а не ref в компоненте: состояние читает баннер в лейауте и может
 * читать любой экран. Модульная переменная `request` не даёт двум
 * смонтированным подряд компонентам послать один запрос дважды — тот же
 * приём, что в useBillingFeature.
 *
 * Конфигурацию спрашиваем НЕ из бутстрапа (useAppInit), а по готовности
 * токена и только там, где баннер рисуется: вкладка задачи (/embedded) живёт
 * в карточке Битрикса на критическом пути, и лишний запрос в ней уже однажды
 * стоил всем нескольких минут загрузки (см. докстринг
 * autoDetectMissingMappings в stores/fieldConfig.ts). Ответ /api/configuration
 * кэшируется в браузере, поэтому экранам, которые и так его читают, запрос
 * ничего не добавляет.
 */

import { computed } from 'vue'
import { MAPPING_SETTINGS_PATH, resolveMappingHealth, type MappingHealth } from '~/utils/fieldMapping'
import type { AppConfigurationPayload } from '~/types/config'

export const MAPPING_HEALTH_CONFIG_STATE_KEY = 'app-mapping-health-config'
export const MAPPING_HEALTH_FAILED_STATE_KEY = 'app-mapping-health-failed'

/**
 * Адрес экрана сопоставления. Сама строка живёт в utils/fieldMapping.ts
 * рядом со ссылками на отдельные шаги (buildMappingStepLink), чтобы адрес
 * экрана и адреса шагов не разъехались.
 */
export const MAPPING_SETTINGS_ROUTE = MAPPING_SETTINGS_PATH

let configRequest: Promise<void> | null = null

export const useMappingHealth = () => {
  const apiStore = useApiStore()

  /** null — конфигурацию ещё не читали. */
  const config = useState<AppConfigurationPayload | null>(
    MAPPING_HEALTH_CONFIG_STATE_KEY,
    () => null
  )
  const failed = useState<boolean>(MAPPING_HEALTH_FAILED_STATE_KEY, () => false)

  /**
   * Читает конфигурацию приложения.
   *
   * Отказ НЕ пробрасываем: предупреждение о настройке не должно ронять экран,
   * на котором оно висит. «Не ответила» трактуем как «неизвестно» и молчим —
   * ложная тревога про ненастроенное приложение хуже отсутствия баннера.
   */
  const load = async (force = false): Promise<void> => {
    if (config.value && !force) {
      return
    }

    if (configRequest) {
      await configRequest
      return
    }

    configRequest = (async () => {
      try {
        config.value = await apiStore.getConfiguration(force)
        failed.value = false
      } catch {
        failed.value = true
      }
    })().finally(() => {
      configRequest = null
    })

    await configRequest
  }

  /** Обновляет состояние после сохранения на экране настройки. */
  const applyConfig = (next: AppConfigurationPayload | null) => {
    config.value = next
    failed.value = false
  }

  const health = computed<MappingHealth>(() => resolveMappingHealth(config.value))

  const isLoaded = computed(() => config.value !== null)

  return {
    config,
    failed,
    health,
    isLoaded,
    load,
    applyConfig,
  }
}
