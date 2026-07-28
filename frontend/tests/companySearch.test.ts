import test from 'node:test'
import assert from 'node:assert/strict'

import {
  classifyCompanySearchError,
  companyCreationActionLabel,
  companyFieldsForQuery,
  companySearchNoticeText,
  createCompanySearchGate,
  isRateLimitError,
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

// --- shouldOfferCompanyCreation ---
//
// Д2 хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
// hotfix-new-company-brief.md): при пустом результате поиска показывалась
// неактивная надпись "Ничего не найдено", хотя подсказка под полем обещала
// действие "создать компанию с этим названием". Обещание было, механизма —
// не было.

test('shouldOfferCompanyCreation: запрос валиден, поиск завершён, вариантов ноль — true', () => {
  assert.equal(shouldOfferCompanyCreation({ query: 'Лютик', isSearching: false, optionCount: 0 }), true)
})

test('shouldOfferCompanyCreation: поиск ещё идёт — false, даже при нуле вариантов на экране', () => {
  // serverResults на старте нового запроса не очищаются (см. SearchableSelect.vue::
  // runServerSearch) — 0 в этот момент может значить "ещё не пришёл ответ", а не
  // "точно ничего нет". Предлагать создание в этот момент — обгонять сервер.
  assert.equal(shouldOfferCompanyCreation({ query: 'Лютик', isSearching: true, optionCount: 0 }), false)
})

test('shouldOfferCompanyCreation: запрос короче двух символов — false', () => {
  assert.equal(shouldOfferCompanyCreation({ query: 'р', isSearching: false, optionCount: 0 }), false)
})

test('shouldOfferCompanyCreation: пустой и пробельный запрос — false', () => {
  assert.equal(shouldOfferCompanyCreation({ query: '', isSearching: false, optionCount: 0 }), false)
  assert.equal(shouldOfferCompanyCreation({ query: '   ', isSearching: false, optionCount: 0 }), false)
})

test('shouldOfferCompanyCreation: сервер вернул варианты — действие не предлагаем, даже без точного совпадения', () => {
  // Осознанное решение (см. докстринг функции): сигнатура получает только
  // optionCount, не сами варианты, поэтому "есть похожие, но ни один не
  // совпадает дословно" неотличимо здесь от "есть точное совпадение" — и то,
  // и другое трактуется как "варианты есть", действие не показываем.
  assert.equal(shouldOfferCompanyCreation({ query: 'Ромашка Казань', isSearching: false, optionCount: 3 }), false)
  assert.equal(shouldOfferCompanyCreation({ query: 'Ромашка Казань', isSearching: false, optionCount: 1 }), false)
})

// --- companyCreationActionLabel ---

test('companyCreationActionLabel: показывает обрезанное введённое название в кавычках', () => {
  assert.equal(companyCreationActionLabel('Лютик'), 'Создать компанию «Лютик»')
  assert.equal(companyCreationActionLabel('  Лютик  '), 'Создать компанию «Лютик»')
})
