/**
 * Чистые функции решения для серверного поиска компаний в SearchableSelect
 * (см. frontend/app/components/common/SearchableSelect.vue).
 *
 * Вынесены из компонента намеренно: node:test через tsx не резолвит .vue,
 * а именно эта логика — «идти ли на сервер», нормализация запроса, разбор
 * ошибки поиска — единственная часть фичи, которую стоит и можно проверить
 * юнит-тестами без Vue и без сети. Остальное (debounce, состояние "идёт
 * поиск", разметка) — в самом компоненте, проверяется сборкой и вручную.
 */

import { isRateLimitError } from './apiErrors'

/** Реэкспорт: SearchableSelect.vue и tests/companySearch.test.ts продолжают
 * импортировать isRateLimitError отсюда. Канонический источник —
 * frontend/app/utils/apiErrors.ts (см. докстринг там же про сведение
 * дубля): раньше здесь была независимая копия с той же логикой — не
 * переиспользовалась осознанно, а совпала случайно, потому что писалась в
 * спешке отдельным патчем, не глядя на apiErrors.ts. Собственная копия НЕ
 * имела дополнительного смысла (проверка тривиальна и одинакова для любого
 * потребителя $api), так что это был тот самый дубль, а не оправданное
 * расхождение — в отличие от classifyCompanySearchError/
 * companySearchNoticeText ниже, у которых причина отличаться от
 * RATE_LIMIT_NOTICE_TEXT реальная (см. их комментарии). */
export { isRateLimitError }

/** Бэкенд (CompanySearchService.search, MIN_QUERY_LENGTH) не обрабатывает
 * запрос короче двух символов вообще — та же граница здесь, чтобы не тратить
 * сетевой запрос впустую и не приближать лимитер (60 запросов/60 секунд на
 * сотрудника, @rate_limit("company_search", 60, 60) в views.py) без пользы. */
export const MIN_COMPANY_QUERY_LENGTH = 2

/** Убирает пробелы по краям — то же значение, что уходит в запрос на сервер
 * и что бэкенд сверяет со своей минимальной длиной. */
export function normalizeCompanyQuery(raw: string): string {
  return String(raw ?? '').trim()
}

/** Решает, стоит ли обращаться к серверу с этим запросом. */
export function shouldSearchCompanies(query: string): boolean {
  return normalizeCompanyQuery(query).length >= MIN_COMPANY_QUERY_LENGTH
}

export interface CompanySearchGate {
  /**
   * true — обращаться к серверу нужно: запрос валиден (см.
   * shouldSearchCompanies) и отличается от последнего запроса, на который
   * гейт уже дал добро. false — запрос слишком короткий/пустой, либо это
   * повтор уже запущенного запроса (типичная ситуация при debounce, когда
   * таймер или наблюдатель за полем ввода могут сработать больше одного
   * раза подряд с одним и тем же значением).
   *
   * Слишком короткий запрос дополнительно сбрасывает память последнего
   * запроса — иначе после того, как пользователь стёр текст и ввёл его
   * заново, повторный ввод того же значения ошибочно считался бы дублем.
   */
  shouldTrigger(query: string): boolean
  /** Возвращает гейт в чистое состояние — например, при закрытии выпадающего списка. */
  reset(): void
}

/** Один экземпляр — на одно поле поиска (замыкание хранит последний запрос,
 * на который уже был дан зелёный свет). */
export function createCompanySearchGate(): CompanySearchGate {
  let lastTriggeredQuery: string | null = null

  return {
    shouldTrigger(query: string): boolean {
      const normalized = normalizeCompanyQuery(query)
      if (!shouldSearchCompanies(normalized)) {
        lastTriggeredQuery = null
        return false
      }
      if (normalized === lastTriggeredQuery) {
        return false
      }
      lastTriggeredQuery = normalized
      return true
    },
    reset(): void {
      lastTriggeredQuery = null
    },
  }
}

/**
 * isRateLimitError (реэкспортирована выше из apiErrors.ts) отличает HTTP 429
 * от серверного ограничителя частоты (backends/python/api/main/utils/decorators/rate_limit.py,
 * @rate_limit("company_search", 60, 60, key="account") на
 * search_project_board_companies — тело ответа {"error": "..."}) от обычного
 * успешного ответа {companies, truncated, failed}.
 *
 * Это отдельный случай от `failed: true` в успешном ответе. `failed` значит
 * «Битрикс не ответил, но запрос до него дошёл»; 429 значит «до Битрикса
 * вообще не дошло, лимитер отказал раньше» — экрану нужно показать разные
 * подсказки для этих случаев (см. classifyCompanySearchError ниже).
 */

/** Причина, по которой найденный список компаний не стоит считать надёжным
 * (но и прятать его не стоит — см. companySearchNoticeText). */
export type CompanySearchNotice = 'rate-limited' | 'unavailable'

/** Единая точка классификации брошенного исключения поиска компаний. */
export function classifyCompanySearchError(error: unknown): CompanySearchNotice {
  return isRateLimitError(error) ? 'rate-limited' : 'unavailable'
}

const COMPANY_SEARCH_NOTICE_TEXT: Record<CompanySearchNotice, string> = {
  'rate-limited': 'Слишком много запросов, подождите немного.',
  'unavailable': 'Битрикс не отвечает. Показанный список может быть неполным.',
}

/** Текст подсказки для ненадёжного (но не обязательно пустого) результата
 * поиска. Специально не пересекается по смыслу с "Ничего не найдено" —
 * человек не должен решить, что компаний нет, и создать дубль. */
export function companySearchNoticeText(notice: CompanySearchNotice | null | undefined): string {
  return notice ? COMPANY_SEARCH_NOTICE_TEXT[notice] : ''
}
