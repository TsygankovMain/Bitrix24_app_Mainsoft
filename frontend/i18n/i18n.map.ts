import type { LocaleObject } from '@nuxtjs/i18n'

/**
 * @memo file put at frontend/i18n/locales
 *
 * Поддерживаются только русский и английский. Остальные локали стартер-кита
 * удалены: они были заморожены на его исходной версии и не содержали ключей
 * приложения — интерфейс на них всё равно падал в fallback.
 */
export const contentLocales: LocaleObject[] = [
  { code: 'ru', name: 'Русский', file: 'ru.json' },
  { code: 'en', name: 'English', file: 'en.json' }
]
