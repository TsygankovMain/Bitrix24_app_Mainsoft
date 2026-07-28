/**
 * Классификация HTTP-ошибок общего API-клиента ($api в frontend/app/stores/api.ts)
 * для мест, которым нужно отличить «подождите минуту» (HTTP 429 от наших
 * лимитеров, см. backends/python/api/main/utils/decorators/rate_limit.py) от
 * настоящего сбоя.
 *
 * Вынесено в отдельный файл, а не в компонент страницы, по той же причине,
 * что и frontend/app/utils/companySearch.ts: node:test через tsx не резолвит
 * .vue, а это единственная часть логики страницы проектов
 * (frontend/app/pages/projects/index.client.vue), которую стоит и можно
 * проверить юнит-тестами без Vue и без сети.
 *
 * Намеренно НЕ переиспользует companySearch.ts::isRateLimitError (хотя форма
 * проверки идентична) и не выносит её в общий модуль вместо дублирования:
 * та функция уже протестирована и живёт в горячем пути поиска компаний
 * (SearchableSelect.vue), который явно указано не трогать при этой правке.
 * Логика классификации тривиальна и стабильна (HTTP 429 — часть контракта
 * ofetch), так что цена дублирования на несколько строк меньше риска
 * зацепить чужой протестированный путь ради общего модуля.
 */

/**
 * Возвращает true, если ошибка вызвана серверным ограничителем частоты
 * (HTTP 429), а не другим сбоем (сеть, 4xx/5xx, парсинг и т.п.).
 *
 * ofetch на не-2xx ответе бросает исключение — в зависимости от версии/пути
 * статус лежит в `.response.status`, `.status` или `.statusCode`. Проверяем
 * все три формы, потому что вызывающий код не всегда знает заранее, какая
 * версия его создала (тот же приём, что и в companySearch.ts).
 */
export function isRateLimitError(error: unknown): boolean {
  if (!error || typeof error !== 'object') {
    return false
  }

  const candidate = error as { response?: { status?: number }, status?: number, statusCode?: number }
  const status = candidate.response?.status ?? candidate.status ?? candidate.statusCode
  return status === 429
}

/**
 * Текст лёгкого уведомления для HTTP 429 — используется вместо фатального
 * экрана (frontend/app/error.vue рендерится без пути лёгкого возврата,
 * :clear="false", единственный выход — перезагрузка страницы, что
 * непропорционально реакции лимитера «подождите минуту»).
 */
export const RATE_LIMIT_NOTICE_TEXT = 'Слишком много запросов, попробуйте через минуту.'
