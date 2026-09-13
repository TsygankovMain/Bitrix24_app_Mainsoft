/**
 * Отмена выставленного документа: тексты подтверждения и проверка причины.
 *
 * Вынесено из разметки по той же причине, что companySearch.ts и
 * appNavigation.ts: node:test через tsx не резолвит .vue, и всё, что осталось
 * внутри компонента, ревью проверить не может. Здесь лежат правила, из-за
 * которых кнопка подтверждения гаснет, и все тексты панели; сама панель
 * (components/finance/BillingCancelDrawer.vue) только рисует то, что эти
 * функции вернули.
 *
 * Главное про содержание текстов. Отмена — не «закрыть окно»: она освобождает
 * потреблённые списания (частичный уникальный индекс работает только для
 * действующих документов), то есть те же часы после неё снова можно выставить.
 * Человек обязан прочитать это ДО нажатия, а не узнать по факту, поэтому
 * последствие названо прямо и стоит в панели первым абзацем.
 *
 * Про минимальную длину. Бэкенд (billing_service.cancel) требует лишь
 * непустую причину, клиент — три символа: «-» или пробел в поле формально
 * проходят серверную проверку, но в документе остаются мусором, по которому
 * через месяц никто не поймёт, почему часы вернулись в работу. Планку выше не
 * ставим: это не поле-обоснование, а пометка для своих, и требовать сочинения
 * там, где хватает «ошиблись клиентом», значит получать «ааааааааа».
 */

/** Меньше — уже не причина, а отметка «лишь бы пропустило». */
export const BILLING_CANCEL_REASON_MIN_LENGTH = 3

/**
 * Мягкий предел: в модели у поля нет ограничения (TextField), но вставленный
 * в него целиком чужой протокол совещания читать в карточке потом невозможно.
 */
export const BILLING_CANCEL_REASON_MAX_LENGTH = 500

/** Заголовок панели без номера — когда номер ещё не загрузился. */
export const BILLING_CANCEL_TITLE = 'Отменить документ'

/** Последствие отмены. Первый абзац панели. */
export const BILLING_CANCEL_CONSEQUENCE
  = 'Списания снова станут свободными для выставления: те же часы можно будет включить в другой счёт.'

/** Чего отмена НЕ делает — иначе её ждут от неё и не находят. */
export const BILLING_CANCEL_CRM_NOTE
  = 'Счёт в CRM портала при этом остаётся: его судьбу решают там же, где выставляли.'

/** Зачем спрашиваем причину. */
export const BILLING_CANCEL_REASON_HINT
  = 'Причина сохраняется в документе — по ней потом понимают, почему часы вернулись в работу.'

export const BILLING_CANCEL_REASON_LABEL = 'Причина отмены'

export const BILLING_CANCEL_REASON_PLACEHOLDER = 'Например: ошиблись клиентом, счёт переоформляем'

export const BILLING_CANCEL_CONFIRM_LABEL
  = 'Понимаю, что отмена освободит списания и документ станет отменённым.'

export const BILLING_CANCEL_SUBMIT_LABEL = 'Отменить документ'

export const BILLING_CANCEL_CLOSE_LABEL = 'Закрыть'

/** Подпись кнопки, пока ответа сервера ещё нет. */
export const BILLING_CANCEL_PENDING_LABEL = 'Отменяем…'

/** Пояснение к ожиданию: отмена ходит на портал, это не мгновенно. */
export const BILLING_CANCEL_PENDING_HINT
  = 'Отменяем документ и освобождаем списания. Не закрывайте панель — операция уже пошла на сервер.'

/** Заголовок панели: с номером документа, если он известен. */
export function billingCancelHeading(documentNumber?: string | null): string {
  const number = String(documentNumber ?? '').trim()

  return number ? `${BILLING_CANCEL_TITLE} ${number}` : BILLING_CANCEL_TITLE
}

/** Причина в том виде, в котором она уйдёт на сервер. */
export function normalizeBillingCancelReason(raw: string | null | undefined): string {
  return String(raw ?? '').trim().slice(0, BILLING_CANCEL_REASON_MAX_LENGTH)
}

/**
 * Что не так с причиной. null — всё в порядке.
 *
 * Текст ошибки возвращается готовым: у поля одна точка показа, и собирать его
 * из кодов в разметке незачем.
 */
export function validateBillingCancelReason(raw: string | null | undefined): string | null {
  const reason = String(raw ?? '').trim()

  if (!reason) {
    return 'Укажите причину отмены — без неё документ отменить нельзя.'
  }

  if (reason.length < BILLING_CANCEL_REASON_MIN_LENGTH) {
    return `Причина слишком короткая: нужно хотя бы ${BILLING_CANCEL_REASON_MIN_LENGTH} символа.`
  }

  if (reason.length > BILLING_CANCEL_REASON_MAX_LENGTH) {
    return `Причина длиннее ${BILLING_CANCEL_REASON_MAX_LENGTH} символов — сократите её.`
  }

  return null
}

export type BillingCancelState = {
  reason: string
  /** Отмечена ли галочка «понимаю последствия». */
  confirmed: boolean
  /** Ждём ответа сервера. */
  submitting: boolean
}

/** Можно ли отправлять отмену. */
export function canSubmitBillingCancel(state: BillingCancelState): boolean {
  return !state.submitting
    && state.confirmed
    && validateBillingCancelReason(state.reason) === null
}

/**
 * Почему кнопка недоступна. null — доступна.
 *
 * Молча погасшая кнопка без объяснения в этом приложении уже приводила к
 * жалобам (см. докстринг CreateProjectDrawer.vue про canSubmit), поэтому
 * причина показывается рядом с кнопкой текстом, а не остаётся в коде.
 */
export function billingCancelBlockReason(state: BillingCancelState): string | null {
  if (state.submitting) {
    return null
  }

  const reasonError = validateBillingCancelReason(state.reason)

  if (reasonError) {
    return reasonError
  }

  if (!state.confirmed) {
    return 'Подтвердите, что последствия отмены понятны.'
  }

  return null
}

/**
 * Можно ли закрыть панель «мимо» — щелчком по затемнению или Escape.
 *
 * Пока ответа сервера нет — нельзя: операция уже пошла, и закрытая панель
 * скрыла бы её исход. Как только в поле появился текст, тоже нельзя:
 * случайный щелчок по затемнению не должен стирать набранное (то же решение
 * заказчика, что и в CreateProjectDrawer.vue). Явные «Закрыть» и крестик
 * работают всегда, кроме отправки.
 */
export function canDismissBillingCancel(state: Pick<BillingCancelState, 'reason' | 'submitting'>): boolean {
  return !state.submitting && String(state.reason ?? '').trim().length === 0
}

/** Сколько символов причины ещё можно набрать. */
export function billingCancelReasonLeft(raw: string | null | undefined): number {
  return Math.max(0, BILLING_CANCEL_REASON_MAX_LENGTH - String(raw ?? '').trim().length)
}

/** Плашка на карточке после успешной отмены. */
export function billingCancelledNotice(documentNumber?: string | null): string {
  const number = String(documentNumber ?? '').trim()
  const subject = number ? `Документ ${number} отменён` : 'Документ отменён'

  return `${subject}, списания освобождены — эти часы снова можно выставить.`
}
