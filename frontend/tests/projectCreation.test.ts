import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addOneYear, plannedAmount } from '../app/types/project-creation'
import { companyNameMismatchNotice, stepBadgeClass, stepErrorTextClass, stepLabel } from '../app/utils/projectCreationLabels'
import {
  missingFieldLabel,
  shouldEmitProjectCreated,
  shouldRefetchLegalEntities,
  shouldResetFormOnOpen,
  shouldShowLegalEntityBlock,
  unslottedMissingFields
} from '../app/utils/projectCreationModalState'

test('addOneYear: обычная дата', () => {
  assert.equal(addOneYear('2026-07-28'), '2027-07-28')
})

test('addOneYear: 29 февраля переносится на 28-е', () => {
  assert.equal(addOneYear('2028-02-29'), '2029-02-28')
})

test('addOneYear: пустая строка не ломается', () => {
  assert.equal(addOneYear(''), '')
})

test('plannedAmount: часы × ставка', () => {
  assert.equal(plannedAmount('10', '1500'), 15000)
})

test('plannedAmount: без часов — null, а не ноль', () => {
  assert.equal(plannedAmount('', '1500'), null)
})

test('plannedAmount: запятая как десятичный разделитель', () => {
  assert.equal(plannedAmount('1,5', '1000'), 1500)
})

test('stepLabel: каждый статус имеет человеческий текст', () => {
  const make = (status: string) => ({ status, id: null, name: '', candidates: [], error: null }) as never
  assert.equal(stepLabel(make('created')), '✓ создано')
  assert.equal(stepLabel(make('found')), '✓ найдено')
  assert.equal(stepLabel(make('skipped')), '— пропущено')
  assert.equal(stepLabel(make('ambiguous')), '⚠ уточните')
  assert.equal(stepLabel(make('error')), '✗ ошибка')
})

test('stepLabel: неизвестный статус не роняет интерфейс', () => {
  assert.equal(stepLabel({ status: 'xxx' } as never), '— пропущено')
})

// 'skipped' и 'ambiguous' обязаны отличаться цветом от 'error' так же, как
// текстом: иначе быстрый взгляд на бейдж читает "пропущено" или "уточните"
// как сбой (см. бриф задачи 8, раздел про семантику ответа).
test('stepBadgeClass: успех — зелёный, пропущено — нейтральный, уточните — жёлтый, ошибка — красный', () => {
  const make = (status: string) => ({ status, id: null, name: '', candidates: [], error: null }) as never
  assert.equal(stepBadgeClass(make('created')), 'bg-emerald-100 text-emerald-700')
  assert.equal(stepBadgeClass(make('found')), 'bg-emerald-100 text-emerald-700')
  assert.equal(stepBadgeClass(make('skipped')), 'bg-slate-100 text-slate-500')
  assert.equal(stepBadgeClass(make('ambiguous')), 'bg-amber-100 text-amber-700')
  assert.equal(stepBadgeClass(make('error')), 'bg-rose-100 text-rose-700')
  assert.notEqual(stepBadgeClass(make('skipped')), stepBadgeClass(make('error')))
  assert.notEqual(stepBadgeClass(make('ambiguous')), stepBadgeClass(make('error')))
})

test('stepBadgeClass: неизвестный статус не роняет интерфейс', () => {
  assert.equal(stepBadgeClass({ status: 'xxx' } as never), 'bg-slate-100 text-slate-500')
})

// Важное 1 финального ревью: шаг карточки возвращает status='skipped' ВМЕСТЕ
// с текстом причины, когда смарт-процесс проектов не настроен (ensure_card
// в project_creation_service.py: error="Смарт-процесс проектов не
// настроен — карточка не создана."). Разметка красила текст ЛЮБОГО .error
// одинаково тревожным rose-600 — под нейтральным серым бейджом
// "— пропущено" оказывалась красная строка, бейдж и подпись противоречили
// друг другу. Тревожным (rose-600) остаётся только текст при статусе
// 'error' — остальное, включая неизвестные статусы, нейтрально, тем же
// приёмом "не пугать несуществующей проблемой", что и у stepLabel/stepBadgeClass.
test('stepErrorTextClass: skipped с текстом причины — нейтральный, не тревожный', () => {
  const step = { status: 'skipped', id: null, name: '', candidates: [], error: 'Смарт-процесс проектов не настроен — карточка не создана.' } as never
  assert.equal(stepErrorTextClass(step), 'text-xs text-slate-500')
})

test('stepErrorTextClass: error — тревожный красный текст', () => {
  const step = { status: 'error', id: null, name: '', candidates: [], error: 'Не удалось создать компанию.' } as never
  assert.equal(stepErrorTextClass(step), 'text-xs text-rose-600')
})

test('stepErrorTextClass: неизвестный статус — нейтральный по умолчанию, как у stepLabel/stepBadgeClass', () => {
  assert.equal(stepErrorTextClass({ status: 'xxx' } as never), 'text-xs text-slate-500')
})

// Фикс-раунд ревью задачи 8, находка 1: безусловный сброс формы при каждом
// открытии терял данные при частичном сбое (компания создалась, группа —
// нет, сотрудник случайно закрыл окно — оно закрываемо сразу после ответа,
// см. :close="!submitting"). Сброс допустим только когда предыдущая попытка
// завершена: результата не было (свежее открытие) либо он успешен.
test('shouldResetFormOnOpen: результата ещё не было — сбрасываем (свежее открытие)', () => {
  assert.equal(shouldResetFormOnOpen(null), true)
})

test('shouldResetFormOnOpen: предыдущая попытка успешна (done=true) — сбрасываем', () => {
  assert.equal(shouldResetFormOnOpen({ done: true } as never), true)
})

test('shouldResetFormOnOpen: предыдущая попытка оборвалась частичным результатом (done=false) — сохраняем форму и прогресс', () => {
  assert.equal(shouldResetFormOnOpen({ done: false } as never), false)
})

// Находка 2: поле выбора юрлица и подсказка о его нехватке лежали за одним
// клиентским условием (legalEntities.length > 1), а бэкенд решает
// необходимость поля независимо на каждой отправке. Блок обязан появляться
// по любой из двух оценок, иначе сотрудник видит три "пропущено" без
// единого объяснения (см. фикс-раунд ревью задачи 8, находка 2).
test('shouldShowLegalEntityBlock: клиент сам видит несколько юрлиц', () => {
  assert.equal(shouldShowLegalEntityBlock(true, []), true)
})

test('shouldShowLegalEntityBlock: бэкенд явно сообщил о нехватке юрлица, хотя клиент так не считает', () => {
  assert.equal(shouldShowLegalEntityBlock(false, ['our_legal_entity_id']), true)
})

test('shouldShowLegalEntityBlock: ни клиент, ни бэкенд не считают юрлицо нужным', () => {
  assert.equal(shouldShowLegalEntityBlock(false, ['hourly_rate']), false)
})

test('shouldShowLegalEntityBlock: пустой missing_fields не роняет интерфейс', () => {
  assert.equal(shouldShowLegalEntityBlock(false, []), false)
})

// Показать блок мало — если список юрлиц на клиенте не догрузился, поле
// выбора будет пустым и сотрудник всё равно застрянет. Пробуем перезагрузить
// список молча, когда расхождение обнаружено.
test('shouldRefetchLegalEntities: бэкенд требует юрлицо, у клиента список пуст', () => {
  assert.equal(shouldRefetchLegalEntities(['our_legal_entity_id'], 0), true)
})

test('shouldRefetchLegalEntities: бэкенд требует юрлицо, у клиента ровно одна запись (тоже расхождение)', () => {
  assert.equal(shouldRefetchLegalEntities(['our_legal_entity_id'], 1), true)
})

test('shouldRefetchLegalEntities: бэкенд требует юрлицо, у клиента уже несколько — перезагружать незачем', () => {
  assert.equal(shouldRefetchLegalEntities(['our_legal_entity_id'], 3), false)
})

test('shouldRefetchLegalEntities: юрлицо не упомянуто среди недостающих полей', () => {
  assert.equal(shouldRefetchLegalEntities(['hourly_rate'], 0), false)
})

// Более широкий вопрос из находки 2: то же расхождение может случиться с
// любым другим полем из missing_fields, для которого на форме нет
// отдельного слота. Запасной путь — общее сообщение обо всём необъяснённом.
test('unslottedMissingFields: все пять известных сегодня полей уже имеют слот на форме', () => {
  assert.deepEqual(
    unslottedMissingFields(['project_name', 'company', 'inn', 'our_legal_entity_id', 'hourly_rate']),
    []
  )
})

// inn-frontend-brief.md: ИНН — пятое поле с собственной подсказкой на форме
// (см. CreateProjectModal.vue, блок v-if="creatingNewCompany"). Без записи
// здесь missing_fields=['inn'] дублировался бы и точечной подсказкой под
// полем, и общим баннером "Не хватает данных для отправки: inn." — тот же
// класс бага, что и находка 2 (см. докстринг выше), просто для нового поля.
test('unslottedMissingFields: inn — у него есть слот на форме (поле ИНН), не должен дублироваться в общем баннере', () => {
  assert.deepEqual(unslottedMissingFields(['inn']), [])
})

test('unslottedMissingFields: неизвестное поле остаётся для общего сообщения', () => {
  assert.deepEqual(unslottedMissingFields(['hourly_rate', 'stage']), ['stage'])
})

test('unslottedMissingFields: пустой список ничего не роняет', () => {
  assert.deepEqual(unslottedMissingFields([]), [])
})

test('missingFieldLabel: известное поле — человеческий текст', () => {
  assert.equal(missingFieldLabel('our_legal_entity_id'), 'юрлицо')
  assert.equal(missingFieldLabel('hourly_rate'), 'ставка')
  assert.equal(missingFieldLabel('inn'), 'ИНН')
})

test('missingFieldLabel: неизвестное поле — сырой код как есть, а не пусто', () => {
  assert.equal(missingFieldLabel('stage'), 'stage')
})

// Важное 2 финального ревью: событие 'created' (по нему доска/главный экран
// перечитывают себя — см. onProjectCreated в pages/index.client.vue и
// pages/projects/index.client.vue) раньше отправлялось только при
// result.done===true. Но группа в Задачах пишется в локальную таблицу
// (write_through на бэкенде) сразу, как только у неё есть id, — ДО попытки
// шага карточки. Если карточка заканчивается status='error' (например,
// Битрикс моргнул на crm.item.list), done=false прятал уже записанную
// строку от доски: сотрудник закрывал окно и не видел свежий проект.
// group.id заполнен ровно тогда, когда group.status — 'created' или 'found'
// (ensure_group никогда не выставляет id при 'ambiguous'/'error') — то есть
// ровно тогда, когда оркестратор дошёл до write_through независимо от
// исхода карточки. Условие шире прежнего done: там, где done было true,
// group.id тоже обязательно заполнен (card.status!=='error' недостижим без
// успешной группы), так что уже покрытые случаи не меняются.
function makeCreationResult(overrides: {
  groupId?: string | null
  cardStatus?: string
  done?: boolean
  missingFields?: string[]
}) {
  return {
    company: { status: 'found', id: '1', name: 'АО Ромашка', candidates: [], error: null },
    group: {
      status: overrides.groupId ? 'found' : 'skipped',
      id: overrides.groupId ?? null,
      name: '',
      candidates: [],
      error: null
    },
    card: {
      status: overrides.cardStatus ?? 'created',
      id: overrides.cardStatus === 'error' ? null : '3',
      name: '',
      candidates: [],
      error: overrides.cardStatus === 'error' ? 'Не удалось найти карточку.' : null
    },
    done: overrides.done ?? false,
    missing_fields: overrides.missingFields ?? []
  } as never
}

test('shouldEmitProjectCreated: группа создана, карточка упала ошибкой (done=false) — событие всё равно нужно', () => {
  const result = makeCreationResult({ groupId: '44', cardStatus: 'error', done: false })
  assert.equal(shouldEmitProjectCreated(result), true)
})

test('shouldEmitProjectCreated: группы нет (ранний отказ по missing_fields) — событие не отправляем', () => {
  const result = makeCreationResult({ groupId: null, missingFields: ['hourly_rate'] })
  assert.equal(shouldEmitProjectCreated(result), false)
})

test('shouldEmitProjectCreated: обычный полный успех (done=true) — событие отправляем как и раньше', () => {
  const result = makeCreationResult({ groupId: '44', cardStatus: 'created', done: true })
  assert.equal(shouldEmitProjectCreated(result), true)
})

test('shouldEmitProjectCreated: карточка осознанно skipped (смарт-процесс не настроен), группа есть — событие нужно', () => {
  const result = makeCreationResult({ groupId: '44', cardStatus: 'skipped', done: true })
  assert.equal(shouldEmitProjectCreated(result), true)
})

test('shouldEmitProjectCreated: результата ещё нет (null) — не роняет интерфейс', () => {
  assert.equal(shouldEmitProjectCreated(null), false)
})

// --- companyNameMismatchNotice ---
// inn-frontend-brief.md, §3 — ГЛАВНОЕ в задаче ИНН. Когда шаг company
// находит компанию по ИНН под ДРУГИМ названием, чем ввёл человек, сервер
// намеренно отдаёт два сырых названия раздельно (name — найденное,
// entered_name — введённое, см. StepResult.entered_name в
// project_creation_service.py) и не собирает готовую фразу — формулировка
// на фронте. Молча подменять введённое название на чужое нельзя (тот же
// класс расхождения, что и Важное 3 финального ревью — см. докстринг
// companyFieldsForQuery в companySearch.ts).
function makeCompanyStep(name: string, enteredName: string | null) {
  return { status: 'found', id: '1', name, candidates: [], error: null, entered_name: enteredName } as never
}

test('companyNameMismatchNotice: entered_name пуст (обычный случай) — предупреждения нет', () => {
  assert.equal(companyNameMismatchNotice(makeCompanyStep('АО Ромашка', null)), null)
})

test('companyNameMismatchNotice: entered_name отличается от name — предупреждение называет ОБА названия', () => {
  const notice = companyNameMismatchNotice(makeCompanyStep('Ромашка Плюс', 'Ромашка'))
  assert.notEqual(notice, null)
  assert.match(notice as string, /Ромашка Плюс/)
  assert.match(notice as string, /Ромашка(?! Плюс)/)
})

test('companyNameMismatchNotice: явно упоминает, что проект привяжется к найденной компании (не молчаливая подмена)', () => {
  const notice = companyNameMismatchNotice(makeCompanyStep('Ромашка Плюс', 'Ромашка')) as string
  assert.match(notice, /привя/i)
})

test('companyNameMismatchNotice: entered_name совпадает с name после обрезки пробелов — расхождения на самом деле нет', () => {
  assert.equal(companyNameMismatchNotice(makeCompanyStep('Ромашка', '  Ромашка  ')), null)
})

test('companyNameMismatchNotice: entered_name из одних пробелов — то же самое, что null', () => {
  assert.equal(companyNameMismatchNotice(makeCompanyStep('АО Ромашка', '   ')), null)
})

test('companyNameMismatchNotice: пустое name при непустом entered_name — защитный случай, не показываем "под названием «»"', () => {
  assert.equal(companyNameMismatchNotice(makeCompanyStep('', 'Ромашка')), null)
})

test('companyNameMismatchNotice: undefined/неизвестный статус шага не роняет функцию', () => {
  assert.equal(companyNameMismatchNotice({ status: 'skipped' } as never), null)
})
