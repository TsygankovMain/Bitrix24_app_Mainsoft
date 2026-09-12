/**
 * Шаблоны генератора документов портала: разбор списка и тексты для экрана.
 *
 * Зачем это здесь, а не в компоненте: node:test через tsx не резолвит .vue,
 * и логика, оставшаяся внутри компонента, тестами не покрывается (тот же
 * довод, что в billingOurCompany.ts). А проверять здесь есть что: список
 * приезжает с портала в его собственной форме, и половина текстов на экране
 * — это объяснение, ПОЧЕМУ шаблон нельзя поправить в приложении.
 *
 * Главный факт про портал, который определяет весь экран: шаблоны живут в
 * Битрикс24, а не у нас. Приложение их только выбирает. Состав печатной
 * формы, её вёрстку, нумератор и привязку к сущностям правят в CRM, поэтому
 * рядом с выбором обязана стоять подпись об этом — иначе первым же вопросом
 * будет «а где поменять текст акта».
 *
 * Второй факт: пустой список — это НЕ поломка и не «нет прав». На портале
 * без штатных шаблонов (или с удалёнными) генератор отвечает честным нулём,
 * и единственно полезная реакция — сказать, где шаблоны создаются, а не
 * показать пустой выпадающий список.
 */

import type { BillingTemplatePayload } from '~/types/billing'

/** Разобранный шаблон: только то, что нужно выбору и подписям. */
export type BillingTemplate = {
  /** Идентификатор строкой: в <select> значение всё равно строка. */
  id: string
  name: string
  /** Код штатного шаблона портала (ACT_RU, BILL_RU) или пусто. */
  code: string
  /** Шаблон активен. Неактивный показываем, но с пометкой. */
  active: boolean
  /** Штатный шаблон своего вида — только подпись, выбор по нему не делается. */
  isDefault: boolean
}

/** Какой из двух шаблонов настраиваем. */
export type BillingTemplateKind = 'act' | 'invoice'

function cleanText(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }

  const text = String(value).trim()

  return ['none', 'null', 'undefined'].includes(text.toLowerCase()) ? '' : text
}

/**
 * Флаг из ответа сервера.
 *
 * Сервер приводит "Y"/"N" портала к булевым, но клиент обязан выдержать и
 * сырую форму: строка 'N' в JavaScript истинна, и признак «неактивен»
 * превратился бы в «активен» у всех шаблонов сразу.
 */
function readFlag(value: unknown, fallback: boolean): boolean {
  if (value === null || value === undefined || value === '') {
    return fallback
  }

  if (typeof value === 'boolean') {
    return value
  }

  const text = String(value).trim().toLowerCase()

  if (['n', 'no', 'false', '0', 'off'].includes(text)) {
    return false
  }

  if (['y', 'yes', 'true', '1', 'on'].includes(text)) {
    return true
  }

  return fallback
}

/**
 * Список шаблонов из ответа сервера.
 *
 * Принимаем и массив, и объект с полем templates: ответ ручки — второе, но
 * тот же разбор используется на уже распакованном списке. Строка без
 * идентификатора выбрасывается: выбрать её нельзя, а в списке она выглядит
 * как рабочий вариант.
 *
 * Порядок портала сохраняется (он отдаёт шаблоны по своему sort), НО
 * неактивные уезжают в конец: их выбирают в последнюю очередь, а место в
 * начале списка выглядит как рекомендация.
 */
export function parseBillingTemplates(raw: unknown): BillingTemplate[] {
  const source: unknown = Array.isArray(raw)
    ? raw
    : (raw && typeof raw === 'object'
        ? (raw as { templates?: unknown }).templates
        : null)

  if (!Array.isArray(source)) {
    return []
  }

  const templates: BillingTemplate[] = []
  const seen = new Set<string>()

  for (const item of source as BillingTemplatePayload[]) {
    if (!item || typeof item !== 'object') {
      continue
    }

    const id = cleanText(item.id)

    if (!id || id === '0' || seen.has(id)) {
      continue
    }

    seen.add(id)
    templates.push({
      id,
      // Шаблон без названия всё равно надо показать: он существует и,
      // возможно, именно он и выбран. Подписываем идентификатором.
      name: cleanText(item.name) || `Шаблон ${id}`,
      code: cleanText(item.code),
      active: readFlag(item.active, true),
      isDefault: readFlag(item.is_default, false),
    })
  }

  const activeFirst = templates.filter(item => item.active)

  return [...activeFirst, ...templates.filter(item => !item.active)]
}

/** Подпись строки выпадающего списка: название, код и пометка «неактивен». */
export function billingTemplateOptionLabel(template: BillingTemplate): string {
  const parts = [template.name]

  if (template.code) {
    parts.push(`(${template.code})`)
  }

  if (!template.active) {
    parts.push('— отключён на портале')
  }

  return parts.join(' ')
}

const KIND_TITLES: Record<BillingTemplateKind, string> = {
  act: 'акта',
  invoice: 'счёта',
}

/**
 * Постоянная подпись под выбором: шаблон живёт на портале.
 *
 * Текст один для обоих шаблонов и намеренно говорит про правку СОСТАВА: это
 * единственное недоразумение, которое здесь стоит денег времени — человек
 * ищет в приложении поля и вёрстку печатной формы, которых тут нет и не
 * будет (своя генерация DOCX/PDF в первую версию не входит).
 */
export const BILLING_TEMPLATE_SOURCE_HINT = 'Список приходит с портала. Сам шаблон — его поля, '
  + 'вёрстка, нумерация и штампы — правится в Битрикс24 (CRM → Настройки CRM → Печатные формы), '
  + 'а не в приложении: приложение только выбирает, каким шаблоном печатать.'

/**
 * Что показать вместо пустого выпадающего списка.
 *
 * Два состояния, и путать их нельзя: портал ответил «шаблонов нет» —
 * человеку надо объяснить, где они создаются; портал не ответил — надо
 * сказать, что дело в портале, и не пугать отсутствием шаблонов, которые,
 * возможно, на месте.
 */
export function billingTemplatesEmptyText(input: { failed?: boolean, errorText?: string }): string {
  if (input.failed) {
    return input.errorText
      ? `Список шаблонов портал не отдал: ${input.errorText}`
      : 'Список шаблонов портал не отдал — генератор документов недоступен или у приложения нет '
        + 'прав на него. Сохранённый шаблон при этом продолжает работать.'
  }

  return 'На портале нет ни одного шаблона генератора документов. Создайте его в Битрикс24: '
    + 'CRM → Настройки CRM → Печатные формы → добавить шаблон (или в карточке счёта кнопка '
    + '«Документ» → «Настроить шаблоны»). После этого вернитесь и обновите страницу — шаблон '
    + 'появится в списке.'
}

export type BillingTemplateSettingView = {
  /** Шаблон выбран. */
  configured: boolean
  /** Подпись выбранного шаблона. */
  label: string
  /** Выбранного шаблона нет в списке портала — настройка мертва. */
  missing: boolean
  /** Текст под полем. */
  text: string
}

/**
 * Подпись выбранного шаблона на экране настроек.
 *
 * Сверяем с загруженным списком, но ТОЛЬКО когда он загружен: пометка «нет
 * на портале» из-за недоступного генератора документов врёт про настройку,
 * которая на самом деле рабочая. Ту же осторожность соблюдает сервер — он
 * не запирает сохранение, если проверить шаблон не удалось.
 */
export function describeBillingTemplateSetting(input: {
  kind: BillingTemplateKind
  templateId?: unknown
  templates?: BillingTemplate[] | null
  /** Список получен (пусть и пустой). false — сверять не с чем. */
  listLoaded?: boolean
}): BillingTemplateSettingView {
  const title = KIND_TITLES[input.kind]
  const id = cleanText(input.templateId)
  const selected = id && id !== '0' ? id : ''

  if (!selected) {
    return {
      configured: false,
      label: '',
      missing: false,
      text: input.kind === 'act'
        ? 'Шаблон акта не выбран: приложение будет искать его на портале по названию — берётся '
          + 'первый шаблон, в имени которого есть «акт». Выберите шаблон явно, чтобы в акт не '
          + 'ушла счёт-фактура или УПД.'
        : 'Шаблон счёта не выбран: печатная форма счёта из приложения недоступна. Сам счёт при '
          + 'этом выставляется и лежит в CRM — печатать его можно из карточки счёта на портале.',
    }
  }

  const list = Array.isArray(input.templates) ? input.templates : []
  const found = list.find(item => item.id === selected) || null
  const label = found ? billingTemplateOptionLabel(found) : `Шаблон ${selected}`
  const missing = Boolean(input.listLoaded) && list.length > 0 && !found

  if (missing) {
    return {
      configured: true,
      label,
      missing: true,
      text: `Шаблона ${title} с идентификатором ${selected} на портале больше нет — его удалили. `
        + 'Выберите другой шаблон: сохранить несуществующий сервер не даст, а печать по нему '
        + 'откажет в момент, когда документ нужен клиенту.',
    }
  }

  if (found && !found.active) {
    return {
      configured: true,
      label,
      missing: false,
      text: `Выбранный шаблон ${title} отключён на портале. Включите его в Битрикс24 или выберите `
        + 'другой — печать по отключённому шаблону портал не выполнит.',
    }
  }

  return {
    configured: true,
    label,
    missing: false,
    text: input.kind === 'act'
      ? `Акты печатаются шаблоном «${label}». Номер и дата акта берутся от счёта.`
      : `Печатная форма счёта собирается шаблоном «${label}».`,
  }
}
