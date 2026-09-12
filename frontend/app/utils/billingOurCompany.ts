/**
 * От какого нашего юрлица уйдёт счёт и откуда это взято.
 *
 * Юрлицо счёта берётся из одного из двух мест: настройка приложения
 * «наше юрлицо по умолчанию» (billing_our_company_id) либо карточка проекта
 * (ProjectCard.our_legal_entity_id). Сервер сам решает, какое из них
 * применить (billing_service.resolve_our_company), и кладёт в ответ preview
 * поле our_company_source.
 *
 * Почему источник обязан быть НА ЭКРАНЕ. Настройка перекрывает карточку
 * молча — иначе она не спасала бы от того, ради чего появилась (карточки
 * приходят с портала, и в них лежат компании, своими юрлицами не
 * являющиеся). Но подмена стороны, от которой уходит счёт, — это реквизиты в
 * печатной форме и в CRM клиента: человек, который видит в карточке проекта
 * одно юрлицо, а в счёте получает другое, имеет право узнать об этом до
 * нажатия «Выставить», а не после.
 *
 * Всё чистыми функциями и без Vue — node:test через tsx не резолвит .vue, и
 * логика, оставшаяся внутри компонента, ревью не проходит (тот же довод, что
 * в billingFeature.ts).
 */

import type { BillingCompanyRef } from '~/types/billing'

/** Значения our_company_source из ответа сервера (billing_service.py). */
export const OUR_COMPANY_FROM_SETTINGS = 'settings'
export const OUR_COMPANY_FROM_PROJECT_CARD = 'project_card'

/** Пустая строка — источника нет: юрлицо не определено ни там, ни там. */
export type BillingOurCompanySource =
  | typeof OUR_COMPANY_FROM_SETTINGS
  | typeof OUR_COMPANY_FROM_PROJECT_CARD
  | ''

export type BillingOurCompanyView = {
  /** Юрлицо известно — есть что показать в строке «Счёт от». */
  present: boolean
  /** Подпись юрлица: название, а если его нет — идентификатор. */
  label: string
  /** Название известно (а не подставлен id). */
  named: boolean
  /** Разобранный источник. */
  source: BillingOurCompanySource
  /** «из настроек приложения» / «из карточки проекта»; пусто — источника нет. */
  sourceText: string
  /** Юрлицо карточек подменено настройкой приложения. */
  overridden: boolean
  /** Юрлица карточек отбора, отличающиеся от того, от кого пойдёт счёт. */
  cardLabels: string[]
  /** Пояснение под строкой. Пусто — пояснять нечего. */
  hint: string
}

function cleanText(value: unknown): string {
  return String(value ?? '').trim()
}

/** Разбор our_company_source. Чужое значение — это «источник неизвестен». */
export function normalizeOurCompanySource(raw: unknown): BillingOurCompanySource {
  const value = cleanText(raw).toLowerCase()

  if (value === OUR_COMPANY_FROM_SETTINGS || value === OUR_COMPANY_FROM_PROJECT_CARD) {
    return value
  }

  return ''
}

/**
 * Подписи юрлиц карточек, отличающихся от юрлица документа.
 *
 * Совпавшее отбрасываем: показывать «в карточках стоит X, а счёт уйдёт от X»
 * значит сообщать о расхождении, которого нет.
 */
function otherCardLabels(
  companies: BillingCompanyRef[] | null | undefined,
  ownId: string
): string[] {
  if (!Array.isArray(companies)) {
    return []
  }

  const seen = new Set<string>()
  const result: string[] = []

  for (const item of companies) {
    const id = cleanText(item?.id)
    if (!id || id === ownId || seen.has(id)) {
      continue
    }

    seen.add(id)
    result.push(cleanText(item?.name) || id)
  }

  return result
}

function listRu(values: string[]): string {
  return values.map(value => `«${value}»`).join(', ')
}

/**
 * Строка «счёт уйдёт от такого-то юрлица» и пояснение к ней.
 *
 * Источник читается ИЗ ОТВЕТА, а не выводится по наличию настройки на
 * экране: решает сервер, и повторять его логику на клиенте — это второй
 * ответ на тот же вопрос, который однажды разойдётся с первым.
 */
export function describeBillingOurCompany(input: {
  ourCompanyId?: unknown
  ourCompanyName?: unknown
  /** Поле our_company_source из ответа preview. */
  source?: unknown
  /** preview.our_companies — юрлица КАРТОЧЕК отбора. */
  cardCompanies?: BillingCompanyRef[] | null
}): BillingOurCompanyView {
  const id = cleanText(input.ourCompanyId)
  const name = cleanText(input.ourCompanyName)
  const source = normalizeOurCompanySource(input.source)
  const named = Boolean(name) && name !== id
  const label = named ? name : id
  const cardLabels = otherCardLabels(input.cardCompanies, id)
  const overridden = source === OUR_COMPANY_FROM_SETTINGS

  const sourceText = source === OUR_COMPANY_FROM_SETTINGS
    ? 'из настроек приложения'
    : source === OUR_COMPANY_FROM_PROJECT_CARD
      ? 'из карточки проекта'
      : ''

  const view: BillingOurCompanyView = {
    present: Boolean(id),
    label,
    named,
    source,
    sourceText: id ? sourceText : '',
    overridden: Boolean(id) && overridden,
    cardLabels,
    hint: '',
  }

  if (!view.present) {
    view.hint = 'Наше юрлицо не определено: в настройках приложения оно не задано, а в карточках '
      + 'проектов отбора не заполнено. Счёт уйдёт без наших реквизитов — задайте юрлицо в '
      + 'настройках приложения.'
    return view
  }

  if (view.overridden) {
    view.hint = cardLabels.length
      ? `В карточках проектов отбора стоит другое юрлицо (${listRu(cardLabels)}) — настройка `
        + 'приложения его перекрывает, и счёт уйдёт от выбранного в настройках.'
      : 'Юрлицо задано настройкой приложения и не зависит от того, что записано в карточках '
        + 'проектов.'
    return view
  }

  if (source === OUR_COMPANY_FROM_PROJECT_CARD) {
    view.hint = cardLabels.length
      ? `В отборе есть часы и по другим юрлицам карточек (${listRu(cardLabels)}). Чтобы все счета `
        + 'уходили от одного юрлица, задайте его в настройках приложения.'
      : 'Юрлицо взято из карточки проекта, а карточки приходят с портала синхронизацией. Чтобы '
        + 'все счета уходили от одного юрлица, задайте его в настройках приложения.'
  }

  return view
}

/**
 * Подпись настройки на экране настроек.
 *
 * Пустая настройка — это не поломка, а прежнее поведение, и говорить о ней
 * надо тем же тоном: «берётся из карточки проекта», а не «не настроено».
 */
export function describeOurCompanySetting(input: {
  ourCompanyId?: unknown
  ourCompanyName?: unknown
  /** Список своих компаний портала — чтобы сверить название с текущим. */
  myCompanies?: Array<{ id?: unknown, name?: unknown }> | null
}): { configured: boolean, label: string, text: string, missing: boolean } {
  const id = cleanText(input.ourCompanyId)

  if (!id) {
    return {
      configured: false,
      label: '',
      missing: false,
      text: 'Юрлицо не задано: счёт уйдёт от того, что записано в карточке проекта. Карточки '
        + 'приходят с портала синхронизацией, поэтому у разных проектов оно разное.',
    }
  }

  const list = Array.isArray(input.myCompanies) ? input.myCompanies : []
  const found = list.find(item => cleanText(item?.id) === id) || null
  const label = cleanText(found?.name) || cleanText(input.ourCompanyName) || id

  // Пустой справочник — это «не загрузился», а не «юрлица нет». Пугать
  // человека отсутствием юрлица, когда портал просто не ответил, нельзя:
  // ту же осторожность соблюдает сервер (verify_our_company).
  const missing = list.length > 0 && !found

  return {
    configured: true,
    label,
    missing,
    text: missing
      ? `Юрлицо «${label}» не найдено среди своих компаний портала — выставить счёт от него не `
        + 'получится. Выберите юрлицо заново или поставьте компании признак «Моя компания» в CRM.'
      : `Все счета будут выставляться от «${label}», независимо от того, что записано в карточках `
        + 'проектов.',
  }
}
