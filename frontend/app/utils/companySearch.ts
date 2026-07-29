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

/**
 * Важное 3 финального ревью: company_id и company_name формы создания
 * проекта обязаны описывать одну и ту же компанию. До этой правки
 * CreateProjectModal.vue::searchCompanyOptions писал введённый текст в
 * company_name на КАЖДЫЙ поисковый запрос, а company_id трогал только выбор
 * варианта из списка (SearchableSelect selectOption/clearValue) — если
 * человек выбрал компанию, передумал, набрал другое название и закрыл
 * список НЕ выбирая, на отправку уходила пара из id старой компании и имени
 * нового текста. На сервере company_id имеет приоритет — он верит id и
 * подписывает карточку/доску чужим именем, а это имя ещё и расползается в
 * справочник (CompanySearchService дописывает company_name туда, где
 * находит company_id).
 *
 * Фикс: company_id и company_name пишутся ОДНОЙ операцией в момент, когда
 * стартует новый поисковый запрос (см. createCompanySearchGate — вызывается
 * только на реально новый, достаточно длинный запрос, не на каждый keydown).
 * До первого клика по варианту это пара (null, <введённый текст>) — то же
 * значение, которое сегодня и означает "создать новую компанию с этим
 * именем" (§5 спеки), а не рассинхрон. Если человек всё же кликнет вариант,
 * SearchableSelect эмитит modelValue и selected синхронно в одном тике
 * (selectOption), а handleCompanySelected восстановит каноничное имя поверх
 * этой пары — расхождению взяться неоткуда ни в одном из двух путей.
 */
export function companyFieldsForQuery(query: string): { company_id: null, company_name: string } {
  return { company_id: null, company_name: normalizeCompanyQuery(query) }
}

export interface PendingCompanyDisplayLabelInput {
  /** Каноничное имя УЖЕ ВЫБРАННОЙ из списка компании (готовая строка —
   * SearchableSelect сам решает, добавлять ли к ней "· ИНН ...", это не
   * забота этой функции). null/пусто/пробелы — компания не выбрана. */
  selectedName?: string | null
  /** Название, введённое для компании, которой в CRM ещё нет — то же
   * значение, что уходит в company_name через companyFieldsForQuery, пока
   * company_id остаётся null. null/пусто/пробелы — ждать нечего. */
  pendingName?: string | null
  emptyLabel: string
}

/**
 * Д1 хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
 * hotfix-new-company-brief.md): что показывает кнопка поля компании
 * (SearchableSelect.vue::displayLabel) на ТРИ возможных состояния поля, а не
 * на два, как было. Раньше displayLabel знал только "выбрано" (есть
 * selectedOption) и "не выбрано" (emptyLabel) — а состояние "человек ввёл
 * название новой компании, из списка ничего не выбрал" молча схлопывалось
 * во второе. Текст казался потерянным, хотя form.company_name его хранил.
 *
 * Приоритет:
 *  1. selectedName — компания выбрана ИЗ СПИСКА (id указывает на реальную
 *     запись CRM). Показываем как раньше, без изменений.
 *  2. pendingName — записи в CRM ещё нет, но человек ввёл текст и не выбрал
 *     вариант (companyFieldsForQuery в этот момент уже держит пару
 *     (company_id: null, company_name: pendingName) — то же самое состояние,
 *     которое форма трактует как "создать новую компанию с этим именем").
 *     Возвращается С ПОМЕТКОЙ "новая": человек обязан на глаз отличать
 *     "выбрана существующая" от "создастся новая" — одинаковый на вид текст
 *     в обоих случаях воспроизвёл бы ту же путаницу на шаг дальше (решил бы,
 *     что уже выбрал существующую компанию, хотя её ещё нет в CRM).
 *  3. emptyLabel — ни то, ни другое: поле действительно пустое. Ровно
 *     прежнее поведение для всех потребителей, которые pendingName не знают
 *     (SearchableSelect без пропа pendingCompanyName — "Наше юрлицо",
 *     "Куратор", фильтры на доске проектов).
 */
export function pendingCompanyDisplayLabel({ selectedName, pendingName, emptyLabel }: PendingCompanyDisplayLabelInput): string {
  const selected = String(selectedName ?? '').trim()
  if (selected) {
    return selected
  }

  const pending = normalizeCompanyQuery(pendingName ?? '')
  if (pending) {
    return `Новая компания: «${pending}»`
  }

  return emptyLabel
}

/**
 * "Это то же название компании?" — граница для shouldOfferCompanyCreation
 * ниже. Без учёта регистра, с обрезкой пробелов по краям. Внутренние
 * пробелы НЕ схлопываются — сознательное решение, а не недосмотр: бэкенд
 * (`_clean_str` в backends/python/api/main/project_creation_service.py,
 * используется и в `ensure_company`) тоже делает только `.strip()`, без
 * схлопывания внутренних пробелов, и именно эту, только по краям обрезанную
 * строку передаёт в фильтр `{"=TITLE": company_name}` — точное совпадение на
 * стороне Битрикса. Если бы фронт был снисходительнее бэкенда (считал
 * "Ромашка  Плюс" (двойной пробел) и "Ромашка Плюс" одним и тем же), кнопка
 * "создать" могла бы пропасть именно тогда, когда `ensure_company`,
 * сравнивая ту же пару строк буквально, всё равно завёл бы дубль — то есть
 * человек не увидел бы предупреждения ровно в момент, когда дубль
 * действительно создаётся. Обрезка только краёв (без нормализации середины)
 * исключает этот разрыв.
 *
 * Регистронезависимость — по инструкции ре-ревью 2026-07-29; на бэкенде её
 * обеспечивает сравнение внутри самого Битрикса/БД (Python-код нигде не
 * приводит company_name к одному регистру перед фильтром `=TITLE`) — это не
 * проверено напрямую (нет доступа к коллации БД портала), но ошибиться в
 * сторону "менее прощающего фронта, чем бэкенд" безопаснее, чем наоборот.
 */
export function companyNameMatchesQuery(name: string, query: string): boolean {
  const normalizedName = String(name ?? '').trim().toLowerCase()
  const normalizedQuery = normalizeCompanyQuery(query).toLowerCase()
  if (!normalizedName || !normalizedQuery) {
    return false
  }
  return normalizedName === normalizedQuery
}

export interface ShouldOfferCompanyCreationInput {
  /** Сырой текст из поля поиска — та же строка, что уходит в shouldSearchCompanies/companyFieldsForQuery. */
  query: string
  /** true, пока ответ текущего серверного поиска ещё не пришёл. */
  isSearching: boolean
  /** Названия вариантов, сейчас показанных в открытом списке
   * (visibleOptions.map(o => o.name) в SearchableSelect.vue). Не количество —
   * функции нужны сами названия, чтобы сравнить каждое с query. */
  optionNames: string[]
}

/**
 * Д2 хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
 * hotfix-new-company-brief.md), граница пересмотрена в тот же день по
 * ре-ревью: решает, показывать ли в открытом списке SearchableSelect
 * действие "Создать компанию «...»" вместо надписи "Ничего не найдено" (или
 * вместо самого списка найденных вариантов).
 *
 * ПЕРВАЯ версия (см. историю git) прятала действие при ЛЮБОМ непустом
 * результате поиска — оказалось, что это тот же тупик, из-за которого форму
 * сняли с прода. Сценарий: в CRM есть "Ромашка-Плюс", человеку нужна новая
 * "Ромашка". Он вводит "Ромашка", видит один нерелевантный вариант — и
 * действия "создать" нет. Связь "количество результатов -> есть кнопка или
 * нет" человеку не видна — а подсказка под полем обещает кнопку без всяких
 * оговорок про пустой результат.
 *
 * Верная граница — ТОЧНОЕ совпадение названия, а не факт наличия
 * результатов:
 *  - query проходит shouldSearchCompanies (>= 2 непробельных символа) —
 *    короче действие предлагать бессмысленно, сервер и не искал;
 *  - isSearching===false — serverResults в SearchableSelect.vue::
 *    runServerSearch НЕ очищаются в момент старта нового поиска (отдельное
 *    намеренное решение — старый список не должен мигать в пустоту на время
 *    запроса), поэтому то, что видно на экране в момент isSearching===true,
 *    относится к ПРЕДЫДУЩЕМУ запросу и сравнивать его с текущим query нельзя;
 *  - среди optionNames НЕТ ни одного, совпадающего с query по правилам
 *    companyNameMatchesQuery (без учёта регистра, обрезка пробелов по краям,
 *    без нормализации середины — см. её докстринг). Есть совпадение —
 *    компания уже в CRM, "создать" показывать неверно, человеку нужно
 *    выбрать её из списка. Нет совпадения — не важно, пуст список или нет,
 *    действие показываем.
 *
 * Дубля это не создаёт: как только среди вариантов появляется точное
 * совпадение, кнопка реактивно пропадает сама (query/optionNames меняются на
 * каждый ввод и каждый ответ сервера). Разные по названию компании (в т.ч.
 * "Ромашка" и "Ромашка-Плюс") — разные записи CRM по построению; какую из
 * двух похожих выбрать или всё же завести новую — решает человек, который
 * видит список рядом с кнопкой, а не эта функция.
 *
 * Согласовано с бэкендом: `ensure_company` (project_creation_service.py)
 * ищет компанию фильтром `{"=TITLE": company_name}` — точным совпадением, и
 * создаёт новую, только если такого совпадения нет (см. докстринг
 * companyNameMatchesQuery про то, как именно она зеркалирует это правило).
 * До этой правки фронт и бэкенд расходились в понимании "такая компания уже
 * есть" — фронт прятал кнопку при ЛЮБЫХ результатах, бэкенд создавал только
 * при их ПОЛНОМ отсутствии буквально; теперь оба используют одно и то же
 * условие.
 */
export function shouldOfferCompanyCreation({ query, isSearching, optionNames }: ShouldOfferCompanyCreationInput): boolean {
  if (isSearching) {
    return false
  }
  if (!shouldSearchCompanies(query)) {
    return false
  }
  return !optionNames.some(name => companyNameMatchesQuery(name, query))
}

/** Текст действия "создать компанию" в открытом списке — введённое (обрезанное)
 * название обязано быть видно в самой кнопке, чтобы человек видел, что именно
 * создастся, до клика (см. §5 брифа хотфикса). */
export function companyCreationActionLabel(query: string): string {
  return `Создать компанию «${normalizeCompanyQuery(query)}»`
}

/**
 * Требование 4 брифа инлайн-версии (.superpowers/sdd/2026-07-28-create-project-button/
 * inline-list-brief.md): список подсказок SearchableSelect.vue больше не
 * всплывает в отдельной панели со своим скроллом — он рисуется в потоке
 * документа прямо под полем (см. брифа "Зачем"). Сервер уже сегодня отдаёт до
 * 50 компаний на двухсимвольный запрос (serverTruncated/"Показаны первые 50" —
 * отдельный, СЕРВЕРНЫЙ лимит, эта константа его не меняет и с ним не связана).
 * Пятьдесят строк в потоке страницы растянули бы форму на несколько экранов, а
 * листать их всё равно никто не станет — люди дописывают буквы запроса, а не
 * скроллят длинный список в поисках нужной компании.
 *
 * 5 — выбранный потолок (бриф разрешает 5-7, точное число и обоснование
 * оставлены на усмотрение реализации): свободно умещается на экране ноутбука
 * даже под остальными полями формы создания проекта (дата, ставка, куратор
 * ниже поля компании), не требует собственной прокрутки внутри страницы и
 * оставляет заметный, однозначно читаемый остаток — типичный ответ поиска
 * компании (30-50 штук) даёт "ещё 45", а не "ещё 43", разница на потолке
 * 5 vs 7 не влияет на итоговое решение человека (всё равно уточнять запрос),
 * зато меньший потолок держит список визуально компактным при каждом вводе.
 */
export const MAX_VISIBLE_SUGGESTIONS = 5

export interface LimitedSuggestions<T> {
  /** Не больше MAX_VISIBLE_SUGGESTIONS первых элементов исходного списка —
   * порядок не меняется, обрезаются только "хвостовые" варианты. */
  visible: T[]
  /** Сколько элементов исходного списка не попало в visible. 0 — список
   * поместился целиком, остатка нет. */
  remainderCount: number
  /** Строка под перечнем ("ещё N — уточните запрос"). Пустая строка, если
   * remainderCount равен нулю — рисовать в разметке нечего. */
  remainderText: string
}

/**
 * Решает, сколько вариантов показать в потоке под полем, и что написать про
 * остаток (требование 4 брифа инлайн-версии, см. докстринг MAX_VISIBLE_SUGGESTIONS
 * выше). Источник списка (серверный поиск компаний или локальная фильтрация
 * options — см. SearchableSelect.vue::visibleOptions) для этой функции не
 * важен: она работает с уже готовым, отфильтрованным перечнем, не заглядывая
 * внутрь элементов.
 */
export function limitVisibleSuggestions<T>(options: readonly T[], max: number = MAX_VISIBLE_SUGGESTIONS): LimitedSuggestions<T> {
  const visible = options.slice(0, max)
  const remainderCount = Math.max(0, options.length - visible.length)
  return {
    visible,
    remainderCount,
    remainderText: remainderCount > 0 ? `ещё ${remainderCount} — уточните запрос` : '',
  }
}
