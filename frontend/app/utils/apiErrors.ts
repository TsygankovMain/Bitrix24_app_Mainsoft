/**
 * Классификация HTTP-ошибок общего API-клиента ($api в frontend/app/stores/api.ts)
 * и центральное решение о том, что показать пользователю, когда лимитер
 * (см. backends/python/api/main/utils/decorators/rate_limit.py) отвечает
 * HTTP 429: «подождите минуту», а не фатальный экран.
 *
 * Вынесено в отдельный файл, а не в компонент/composable, по одной причине
 * везде в этом проекте: node:test через tsx не резолвит .vue, поэтому вся
 * логика, которую стоит и можно проверить юнит-тестами без Vue/Nuxt и без
 * сети, живёт здесь в виде чистых функций. Их вызывают:
 *  - frontend/app/composables/useAppInit.ts::processErrorGlobal —
 *    центральная точка (см. shouldTreatAsFatalError ниже);
 *  - frontend/app/pages/projects/index.client.vue (refreshReferenceOptions,
 *    syncBoard) — более конкретные локальные ветки поверх той же
 *    isRateLimitError, см. комментарии там же.
 *
 * Канонический источник isRateLimitError: frontend/app/utils/companySearch.ts
 * импортирует её отсюда (и реэкспортирует под тем же именем для
 * SearchableSelect.vue и своих тестов), а не хранит свою копию — до этой
 * правки копии были независимыми (написаны в разное время, форма проверки
 * совпала случайно, не по расчёту), что и есть тот самый дубль, который
 * теперь сведён. companySearch.ts сохраняет СВОИ classifyCompanySearchError/
 * companySearchNoticeText: это осознанно другой текст уведомления
 * («…подождите немного.» — для живого поиска по мере ввода, где 429 от
 * лимитера company_search — фоновая деталь, а не результат явного клика),
 * не совпадение с RATE_LIMIT_NOTICE_TEXT ниже.
 */

/**
 * Возвращает true, если ошибка вызвана серверным ограничителем частоты
 * (HTTP 429), а не другим сбоем (сеть, 4xx/5xx, парсинг и т.п.).
 *
 * ofetch на не-2xx ответе бросает исключение — в зависимости от версии/пути
 * статус лежит в `.response.status`, `.status` или `.statusCode`. Проверяем
 * все три формы, потому что вызывающий код не всегда знает заранее, какая
 * версия его создала (тот же приём нужен и SearchableSelect.vue, который
 * получает эту функцию через реэкспорт из companySearch.ts).
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

/**
 * Явный флаг на самой ошибке: «для 429 здесь нужен старый фатальный экран,
 * это осознанный выбор конкретного вызывающего кода, а не забытая точка».
 * Мутирует и возвращает тот же объект (безопасно — это всегда обычный
 * Error/FetchError), поэтому годится прямо в throw без потери ссылки:
 * `throw markRateLimitFatal(error)`.
 *
 * Единственный сегодняшний вызывающий — initApp() в
 * frontend/app/composables/useAppInit.ts, оборачивающий api.init() (то есть
 * getToken/reinitToken — единственный $api-вызов внутри bootstrap'а
 * приложения, @rate_limit("get_token", 10, 60, key="ip_domain") в
 * backends/python/api/main/views.py). Без валидного JWT ни один другой
 * $api-запрос не пройдёт: лёгкое уведомление оставило бы человека на
 * пустом/сломанном экране без объяснения, а initApp() вызывается из onMounted
 * буквально каждой страницы (не только из потока установки /install — там
 * бутстрап отдельный, через apiStore.postInstall, get_token не использует).
 * Поэтому это тот редкий случай, где фатальный экран — осознанно правильное
 * поведение, а не дефект, который чинит эта задача.
 *
 * На не-объектных значениях (например, строка) — no-op: пометить нечего, но
 * и падать не должна.
 */
export function markRateLimitFatal<T>(error: T): T {
  if (error && typeof error === 'object') {
    (error as Record<string, unknown>).fatalOnRateLimit = true
  }

  return error
}

/**
 * Центральный инвариант починки 429 (см. RATE_LIMIT_NOTICE_TEXT выше и
 * .superpowers/sdd/2026-07-28-project-references-from-db/critical-429-central-report.md):
 * HTTP 429 сам по себе не повод показывать фатальный экран
 * (frontend/app/error.vue через showError({fatal:true}) в processErrorGlobal,
 * frontend/app/composables/useAppInit.ts — единственном месте всего
 * приложения, которое зовёт showError). processErrorGlobal вызывает именно
 * эту функцию первым делом, поэтому решение действует для ЛЮБОГО catch,
 * который просто зовёт processErrorGlobal(e) ничего специально не делая, —
 * то есть «по построению» для всех экранов с этим паттерном (а их около
 * двадцати), включая ещё не написанные, а не только для точечно
 * пофикшенных.
 *
 * Безопасно по умолчанию: false (не фатальна) только когда ошибка — 429 БЕЗ
 * явной пометки markRateLimitFatal. Во всех остальных случаях — true, то
 * есть ровно прежнее поведение:
 *  - ошибка не 429 (сеть, 403, 500, ошибка валидации и т.п.) — не наша
 *    забота, всегда true, эта функция их поведение не меняет;
 *  - 429, но явно помечена markRateLimitFatal (сегодня — только get_token,
 *    см. его докстринг выше) — true, вызывающий код осознанно попросил
 *    старое поведение.
 */
export function shouldTreatAsFatalError(error: unknown): boolean {
  if (!isRateLimitError(error)) {
    return true
  }

  return Boolean(
    error
    && typeof error === 'object'
    && (error as Record<string, unknown>).fatalOnRateLimit === true
  )
}
