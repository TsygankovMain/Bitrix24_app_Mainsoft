import test from 'node:test'
import assert from 'node:assert/strict'

import {
  classifyCompanySearchError,
  companyCreationActionLabel,
  companyFieldsForQuery,
  companyNameMatchesQuery,
  companySearchNoticeText,
  createCompanySearchGate,
  isRateLimitError,
  limitVisibleSuggestions,
  MAX_VISIBLE_SUGGESTIONS,
  normalizeCompanyQuery,
  pendingCompanyDisplayLabel,
  shouldOfferCompanyCreation,
  shouldSearchCompanies,
} from '../app/utils/companySearch'

// --- normalizeCompanyQuery ---

test('normalizeCompanyQuery: обрезает пробелы по краям, середину не трогает', () => {
  assert.equal(normalizeCompanyQuery('  Ромашка  '), 'Ромашка')
  assert.equal(normalizeCompanyQuery('Рога и копыта'), 'Рога и копыта')
})

test('normalizeCompanyQuery: не падает на null/undefined', () => {
  assert.equal(normalizeCompanyQuery(null as unknown as string), '')
  assert.equal(normalizeCompanyQuery(undefined as unknown as string), '')
})

// --- shouldSearchCompanies ---

test('shouldSearchCompanies: запрос короче двух символов не идёт на сервер', () => {
  assert.equal(shouldSearchCompanies(''), false)
  assert.equal(shouldSearchCompanies('р'), false)
})

test('shouldSearchCompanies: запрос из одних пробелов не идёт на сервер', () => {
  assert.equal(shouldSearchCompanies('   '), false)
  assert.equal(shouldSearchCompanies('\t\n'), false)
})

test('shouldSearchCompanies: запрос из 10 цифр (похож на ИНН) идёт на сервер', () => {
  assert.equal(shouldSearchCompanies('1234567890'), true)
})

test('shouldSearchCompanies: ровно два непробельных символа — граница, тоже идёт', () => {
  assert.equal(shouldSearchCompanies('оо'), true)
  assert.equal(shouldSearchCompanies('  оо  '), true)
})

// --- createCompanySearchGate ---

test('createCompanySearchGate: повторный тот же запрос в пределах задержки не порождает второй вызов', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  assert.equal(gate.shouldTrigger('Ромашка'), false)
  // тот же запрос после нормализации (пробелы по краям) — тоже повтор
  assert.equal(gate.shouldTrigger('  Ромашка  '), false)
})

test('createCompanySearchGate: другой запрос снова порождает вызов', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  assert.equal(gate.shouldTrigger('Одуванчик'), true)
})

test('createCompanySearchGate: короткий запрос никогда не триггерит и сбрасывает память', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  assert.equal(gate.shouldTrigger('р'), false)
  // после короткого запроса память "последнего запроса" сброшена — тот же
  // валидный запрос, что уже был, снова триггерит, а не считается повтором
  assert.equal(gate.shouldTrigger('Ромашка'), true)
})

test('createCompanySearchGate: reset() возвращает гейт в чистое состояние', () => {
  const gate = createCompanySearchGate()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
  gate.reset()
  assert.equal(gate.shouldTrigger('Ромашка'), true)
})

// --- isRateLimitError / classifyCompanySearchError / companySearchNoticeText ---
//
// Бэкенд (backends/python/api/main/utils/decorators/rate_limit.py) отвечает
// на превышение лимита HTTP 429 с телом {"error": "..."} — формой, которая
// НЕ совпадает с обычным ответом {companies, truncated, failed}. ofetch на
// не-2xx бросает исключение с `.response.status`/`.status`/`.statusCode` —
// проверяем все три формы, потому что код, который ловит ошибку, не всегда
// заранее знает, какая версия ofetch её создала.

test('isRateLimitError: узнаёт 429 в разных формах ошибки ofetch', () => {
  assert.equal(isRateLimitError({ response: { status: 429 } }), true)
  assert.equal(isRateLimitError({ status: 429 }), true)
  assert.equal(isRateLimitError({ statusCode: 429 }), true)
})

test('isRateLimitError: не путает 429 с другими статусами и обычным сбоем сети', () => {
  assert.equal(isRateLimitError({ response: { status: 500 } }), false)
  assert.equal(isRateLimitError({ response: { status: 403 } }), false)
  assert.equal(isRateLimitError(new Error('network down')), false)
})

test('isRateLimitError: не падает на мусорных значениях', () => {
  assert.equal(isRateLimitError(null), false)
  assert.equal(isRateLimitError(undefined), false)
  assert.equal(isRateLimitError('429'), false)
  assert.equal(isRateLimitError(429), false)
})

test('classifyCompanySearchError: 429 — rate-limited, любая другая ошибка — unavailable', () => {
  assert.equal(classifyCompanySearchError({ response: { status: 429 } }), 'rate-limited')
  assert.equal(classifyCompanySearchError({ response: { status: 500 } }), 'unavailable')
  assert.equal(classifyCompanySearchError(new TypeError('boom')), 'unavailable')
})

test('companySearchNoticeText: у лимитера и недоступности разный текст, не похожий на "ничего не найдено"', () => {
  const rateLimited = companySearchNoticeText('rate-limited')
  const unavailable = companySearchNoticeText('unavailable')

  assert.match(rateLimited, /слишком много запросов/i)
  assert.match(unavailable, /битрикс/i)
  assert.notEqual(rateLimited, unavailable)
})

test('companySearchNoticeText: без причины — пустая строка (нет повода что-то показывать)', () => {
  assert.equal(companySearchNoticeText(null), '')
  assert.equal(companySearchNoticeText(undefined), '')
})

// --- companyFieldsForQuery ---
//
// Важное 3 финального ревью: company_id и company_name обязаны описывать
// одну и ту же компанию. Сценарий бага — выбрал «АО Ромашка» (company_id
// заполнен), передумал, набрал «Лютик», закрыл список не выбирая, нажал
// «Создать»: раньше company_name перезаписывался сырым текстом на каждый
// поисковый запрос (CreateProjectModal.vue::searchCompanyOptions), а
// company_id оставался от прошлого выбора — на сервер уезжала пара из id
// Ромашки и имени «Лютик». companyFieldsForQuery — та единственная операция,
// которая теперь пишет оба поля формы: как только запрос меняется, id
// обнуляется В ТОТ ЖЕ момент, что и имя — разойтись им негде. Если человек
// всё же выберет вариант из списка, SearchableSelect/handleCompanySelected
// восстановят согласованную пару поверх этого.

test('companyFieldsForQuery: обнуляет company_id и подставляет обрезанный текст в company_name', () => {
  assert.deepEqual(companyFieldsForQuery('Лютик'), { company_id: null, company_name: 'Лютик' })
  assert.deepEqual(companyFieldsForQuery('  Лютик  '), { company_id: null, company_name: 'Лютик' })
})

test('companyFieldsForQuery: пустой запрос — тоже обнуляет id, имя пустое', () => {
  assert.deepEqual(companyFieldsForQuery(''), { company_id: null, company_name: '' })
})

// --- pendingCompanyDisplayLabel ---
//
// Д1 хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
// hotfix-new-company-brief.md): SearchableSelect.vue::displayLabel возвращал
// props.emptyLabel всегда, когда selectedOption===null — в том числе когда
// человек уже ввёл название НОВОЙ компании (нечего выбирать из списка) и
// закрыл его. Поле показывало "Компания не выбрана", хотя form.company_name
// уже хранил введённый текст — человек считал ввод потерянным.

test('pendingCompanyDisplayLabel: выбранная компания в приоритете над ожидающим названием', () => {
  assert.equal(
    pendingCompanyDisplayLabel({ selectedName: 'АО Ромашка', pendingName: 'Лютик', emptyLabel: 'Не выбрано' }),
    'АО Ромашка',
  )
})

test('pendingCompanyDisplayLabel: компания не выбрана, но есть ожидающее название — оно видно и помечено как новое', () => {
  const label = pendingCompanyDisplayLabel({ selectedName: null, pendingName: 'Лютик', emptyLabel: 'Не выбрано' })
  assert.match(label, /Лютик/, 'введённое название обязано остаться видимым')
  assert.notEqual(label, 'Лютик', 'голое имя неотличимо от выбранной существующей компании — нужна пометка "новая"')
})

test('pendingCompanyDisplayLabel: ожидающее название обрезается по краям так же, как в companyFieldsForQuery', () => {
  assert.equal(
    pendingCompanyDisplayLabel({ selectedName: null, pendingName: '  Лютик  ', emptyLabel: 'Не выбрано' }),
    pendingCompanyDisplayLabel({ selectedName: null, pendingName: 'Лютик', emptyLabel: 'Не выбрано' }),
  )
})

test('pendingCompanyDisplayLabel: ни выбора, ни ожидающего названия — emptyLabel, как и раньше', () => {
  assert.equal(pendingCompanyDisplayLabel({ selectedName: null, pendingName: null, emptyLabel: 'Не выбрано' }), 'Не выбрано')
  assert.equal(pendingCompanyDisplayLabel({ selectedName: '', pendingName: '', emptyLabel: 'Не выбрано' }), 'Не выбрано')
  assert.equal(pendingCompanyDisplayLabel({ selectedName: '   ', pendingName: undefined, emptyLabel: 'Не выбрано' }), 'Не выбрано')
})

test('pendingCompanyDisplayLabel: пустая строка выбранного имени не маскирует ожидающее название', () => {
  // selectedOption у SearchableSelect — либо реальный объект (name непустой
  // по построению), либо null. Пустая строка сюда прийти не должна, но
  // функция обязана трактовать её как "не выбрано", а не как выбор с именем "".
  const label = pendingCompanyDisplayLabel({ selectedName: '', pendingName: 'Лютик', emptyLabel: 'Не выбрано' })
  assert.match(label, /Лютик/)
})

// --- companyNameMatchesQuery ---
//
// Ре-ревью хотфикса 2026-07-29: граница "точное совпадение" для
// shouldOfferCompanyCreation ниже. Без учёта регистра, с обрезкой пробелов
// по краям; внутренние пробелы НЕ схлопываются — см. докстринг функции
// (зеркалирует _clean_str/ensure_company на бэкенде).

test('companyNameMatchesQuery: совпадение символ в символ — true', () => {
  assert.equal(companyNameMatchesQuery('Ромашка', 'Ромашка'), true)
})

test('companyNameMatchesQuery: регистр не учитывается', () => {
  assert.equal(companyNameMatchesQuery('РОМАШКА', 'ромашка'), true)
  assert.equal(companyNameMatchesQuery('ооо ромашка', 'ООО РОМАШКА'), true)
})

test('companyNameMatchesQuery: пробелы по краям обрезаются с обеих сторон', () => {
  assert.equal(companyNameMatchesQuery('  Ромашка  ', 'Ромашка'), true)
  assert.equal(companyNameMatchesQuery('Ромашка', '  Ромашка  '), true)
  assert.equal(companyNameMatchesQuery('  РОМАШКА  ', '  ромашка  '), true)
})

test('companyNameMatchesQuery: внутренние пробелы НЕ схлопываются', () => {
  // Осознанное решение — см. докстринг функции: бэкенд (_clean_str в
  // project_creation_service.py) тоже только .strip(), без схлопывания
  // внутренних пробелов, а ensure_company ищет ТОЧНО этой строкой через
  // {"=TITLE": company_name}. Если бы фронт был снисходительнее бэкенда,
  // кнопка "создать" могла бы пропасть именно тогда, когда ensure_company
  // всё равно завёл бы дубль (сам не найдя "нестрогого" совпадения).
  assert.equal(companyNameMatchesQuery('Ромашка  Плюс', 'Ромашка Плюс'), false)
})

test('companyNameMatchesQuery: разные названия — false', () => {
  assert.equal(companyNameMatchesQuery('Ромашка-Плюс', 'Ромашка'), false)
  assert.equal(companyNameMatchesQuery('Ромашка', 'Ромашка-Плюс'), false)
})

test('companyNameMatchesQuery: пустое имя или запрос — не совпадение, а не "оба пустых равны"', () => {
  assert.equal(companyNameMatchesQuery('', ''), false)
  assert.equal(companyNameMatchesQuery('   ', 'Ромашка'), false)
  assert.equal(companyNameMatchesQuery('Ромашка', '   '), false)
})

// --- shouldOfferCompanyCreation ---
//
// Д2 хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
// hotfix-new-company-brief.md): при пустом результате поиска показывалась
// неактивная надпись "Ничего не найдено", хотя подсказка под полем обещала
// действие "создать компанию с этим названием". Обещание было, механизма —
// не было.
//
// Граница «точное совпадение» (а не «есть хоть какой-то результат») —
// поправка ре-ревью того же дня: первая версия прятала действие при ЛЮБЫХ
// непустых результатах поиска. Сценарий тупика: в CRM есть "Ромашка-Плюс",
// нужна новая "Ромашка" — человек вводит "Ромашка", видит один
// нерелевантный вариант, кнопки "создать" нет, и никак не понять, что делать,
// чтобы она появилась. Та же жалоба, из-за которой форму сняли с прода.

test('shouldOfferCompanyCreation: пустой список, запрос валиден, поиск завершён — true', () => {
  assert.equal(shouldOfferCompanyCreation({ query: 'Лютик', isSearching: false, optionNames: [] }), true)
})

test('shouldOfferCompanyCreation: непустой список БЕЗ точного совпадения — true (это и есть фикс ре-ревью)', () => {
  assert.equal(
    shouldOfferCompanyCreation({ query: 'Ромашка', isSearching: false, optionNames: ['Ромашка-Плюс', 'Ромашка Сервис'] }),
    true,
  )
})

test('shouldOfferCompanyCreation: точное совпадение среди вариантов — false, компанию надо выбрать из списка', () => {
  assert.equal(
    shouldOfferCompanyCreation({ query: 'Ромашка', isSearching: false, optionNames: ['Ромашка-Плюс', 'Ромашка'] }),
    false,
  )
})

test('shouldOfferCompanyCreation: точное совпадение в другом регистре и с лишними пробелами по краям — тоже false', () => {
  assert.equal(
    shouldOfferCompanyCreation({ query: '  ромашка  ', isSearching: false, optionNames: ['РОМАШКА'] }),
    false,
  )
})

test('shouldOfferCompanyCreation: поиск ещё идёт — false, даже если среди уже показанных вариантов нет совпадения', () => {
  // serverResults на старте нового запроса не очищаются (см. SearchableSelect.vue::
  // runServerSearch) — то, что видно на экране в момент isSearching===true,
  // относится к ПРЕДЫДУЩЕМУ запросу, сравнивать его с текущим query нельзя.
  assert.equal(shouldOfferCompanyCreation({ query: 'Лютик', isSearching: true, optionNames: [] }), false)
})

test('shouldOfferCompanyCreation: запрос короче двух символов — false', () => {
  assert.equal(shouldOfferCompanyCreation({ query: 'р', isSearching: false, optionNames: [] }), false)
})

test('shouldOfferCompanyCreation: пустой и пробельный запрос — false', () => {
  assert.equal(shouldOfferCompanyCreation({ query: '', isSearching: false, optionNames: [] }), false)
  assert.equal(shouldOfferCompanyCreation({ query: '   ', isSearching: false, optionNames: [] }), false)
})

// --- companyCreationActionLabel ---

test('companyCreationActionLabel: показывает обрезанное введённое название в кавычках', () => {
  assert.equal(companyCreationActionLabel('Лютик'), 'Создать компанию «Лютик»')
  assert.equal(companyCreationActionLabel('  Лютик  '), 'Создать компанию «Лютик»')
})

// --- limitVisibleSuggestions ---
//
// Требование 4 брифа инлайн-версии (.superpowers/sdd/2026-07-28-create-project-button/
// inline-list-brief.md): список подсказок SearchableSelect больше не всплывает
// в отдельной прокручиваемой панели, а рисуется в потоке документа под полем —
// см. SearchableSelect.vue. Сервер сегодня отдаёт до 50 компаний на короткий
// запрос (serverTruncated) — все 50 строк в потоке растянули бы форму на
// несколько экранов, и листать их всё равно никто не станет: дальше двух
// символов люди дописывают буквы запроса, а не скроллят. Поэтому в потоке
// показывается не больше MAX_VISIBLE_SUGGESTIONS вариантов, а под ними —
// строка с числом остатка и подсказкой уточнить запрос.

test('limitVisibleSuggestions: список короче потолка — возвращается целиком, остатка нет', () => {
  const result = limitVisibleSuggestions(['a', 'b', 'c'])
  assert.deepEqual(result.visible, ['a', 'b', 'c'])
  assert.equal(result.remainderCount, 0)
  assert.equal(result.remainderText, '')
})

test('limitVisibleSuggestions: список ровно равен потолку — виден целиком, остатка нет', () => {
  const options = Array.from({ length: MAX_VISIBLE_SUGGESTIONS }, (_, i) => i)
  const result = limitVisibleSuggestions(options)
  assert.deepEqual(result.visible, options)
  assert.equal(result.remainderCount, 0)
  assert.equal(result.remainderText, '')
})

test('limitVisibleSuggestions: типичный ответ поиска компаний (50) — обрезается, остаток посчитан и назван в тексте', () => {
  const options = Array.from({ length: 50 }, (_, i) => i)
  const result = limitVisibleSuggestions(options)
  assert.equal(result.visible.length, MAX_VISIBLE_SUGGESTIONS)
  assert.deepEqual(result.visible, options.slice(0, MAX_VISIBLE_SUGGESTIONS))
  assert.equal(result.remainderCount, 50 - MAX_VISIBLE_SUGGESTIONS)
  assert.match(result.remainderText, new RegExp(String(50 - MAX_VISIBLE_SUGGESTIONS)))
  assert.match(result.remainderText, /уточните запрос/i)
})

test('limitVisibleSuggestions: пустой список — пусто, остатка нет', () => {
  const result = limitVisibleSuggestions([])
  assert.deepEqual(result.visible, [])
  assert.equal(result.remainderCount, 0)
  assert.equal(result.remainderText, '')
})

test('limitVisibleSuggestions: на единицу больше потолка — остаток ровно 1, а не 0', () => {
  const options = Array.from({ length: MAX_VISIBLE_SUGGESTIONS + 1 }, (_, i) => i)
  const result = limitVisibleSuggestions(options)
  assert.equal(result.visible.length, MAX_VISIBLE_SUGGESTIONS)
  assert.equal(result.remainderCount, 1)
  assert.match(result.remainderText, /ещё 1\b/)
})

test('limitVisibleSuggestions: явно переданный потолок переопределяет значение по умолчанию', () => {
  const result = limitVisibleSuggestions([1, 2, 3, 4, 5], 2)
  assert.deepEqual(result.visible, [1, 2])
  assert.equal(result.remainderCount, 3)
  assert.match(result.remainderText, /ещё 3\b/)
})

test('MAX_VISIBLE_SUGGESTIONS: в границах, которые просит бриф (не больше 5-7)', () => {
  assert.ok(MAX_VISIBLE_SUGGESTIONS >= 5 && MAX_VISIBLE_SUGGESTIONS <= 7)
})
