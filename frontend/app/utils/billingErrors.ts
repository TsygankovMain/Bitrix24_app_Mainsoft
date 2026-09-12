/**
 * Отказы сервера по «Счёту и акту» — понятным текстом.
 *
 * Экраны этой функции НЕ зовут processErrorGlobal на каждую ошибку. Фатальный
 * экран (app/error.vue, :clear="false") здесь почти всегда неверная реакция:
 * «эти часы уже выставлены» — это штатный ответ 409 со ссылкой на готовый
 * документ, а не поломка приложения, и человеку надо дать ссылку, а не
 * предложить перезагрузить страницу.
 *
 * Отдельная причина разбирать ошибки здесь: общий клиент $api
 * (app/stores/api.ts) на 403 подменяет ошибку голым Error с серверным
 * текстом — статус и код при этом теряются. Поэтому функция смотрит и на
 * статус, и на тело, и на само сообщение, и обязана давать осмысленный текст
 * во всех трёх случаях.
 *
 * Пока бэкенда нет, отказы приходят в четвёртой форме — 404 на неизвестный
 * маршрут и обрыв сети. Это тоже штатная ветка: интерфейс должен объяснить,
 * что функция ещё не поднята, а не показать белый экран.
 */

import { isRateLimitError, RATE_LIMIT_NOTICE_TEXT } from './apiErrors'

/** Статус HTTP из ошибки ofetch в любой из трёх её форм. null — статуса нет. */
export function readErrorStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object') {
    return null
  }

  const candidate = error as {
    response?: { status?: number }
    status?: number
    statusCode?: number
  }
  const status = candidate.response?.status ?? candidate.status ?? candidate.statusCode

  return typeof status === 'number' && Number.isFinite(status) ? status : null
}

/** Тело ответа с ошибкой. ofetch кладёт его в .data, а сырой ответ — в ._data. */
export function readErrorPayload(error: unknown): Record<string, unknown> {
  if (!error || typeof error !== 'object') {
    return {}
  }

  const candidate = error as {
    data?: unknown
    response?: { _data?: unknown }
  }
  const body = candidate.data ?? candidate.response?._data

  return body && typeof body === 'object' ? body as Record<string, unknown> : {}
}

/** Код отказа из тела ответа (feature_disabled, act_template_missing, ...). */
export function readErrorCode(error: unknown): string {
  const payload = readErrorPayload(error)

  return String(payload.code || '').trim()
}

/**
 * Текст, который прислал СЕРВЕР в теле ответа.
 *
 * Отделён от readErrorMessage намеренно: показывать человеку можно только
 * это. Сообщение самой ошибки ofetch выглядит как «[POST] "/api/billing/
 * documents": 404 Not Found» — машинная строка, которая ничего не объясняет
 * и в интерфейсе смотрится как утечка внутренностей.
 */
function readServerMessage(error: unknown): string {
  const payload = readErrorPayload(error)

  return String(payload.error || payload.detail || payload.message || '').trim()
}

/**
 * Текст для РАСПОЗНАВАНИЯ, а не для показа.
 *
 * Сюда попадает и message самой ошибки: общий клиент $api на 403 подменяет
 * ошибку голым Error с серверным текстом и теряет статус (см. onResponseError
 * в app/stores/api.ts), и единственный способ узнать такой отказ — прочитать
 * его сообщение.
 */
function readErrorMessage(error: unknown): string {
  const fromBody = readServerMessage(error)

  if (fromBody) {
    return fromBody
  }

  if (error instanceof Error) {
    return String(error.message || '').trim()
  }

  if (typeof error === 'string') {
    return error.trim()
  }

  return ''
}

/**
 * Машинное сообщение ofetch: «[POST] "/api/billing/documents": 404 Not Found».
 *
 * Такое человеку не показываем ни при каких условиях — это адрес и код, а не
 * объяснение. Отличаем по префиксу с методом в квадратных скобках.
 */
function looksLikeMachineMessage(message: string): boolean {
  return /^\[[A-Z]+\]/.test(message)
}

/** Похоже ли сообщение на обрыв связи, а не на ответ сервера. */
function looksLikeNetworkFailure(message: string): boolean {
  return /fetch failed|failed to fetch|load failed|network|socket|econn|enotfound|timeout|aborted/i.test(message)
}

/**
 * Идентификатор уже существующего документа из ответа 409.
 *
 * Контракт (правило 8, идемпотентность) требует вернуть ссылку на
 * существующий документ, но не фиксирует имя поля. Принимаем все разумные
 * написания: цена ошибки — потерянная ссылка и текст «ошибка сервера» вместо
 * перехода в готовый документ.
 */
export function readConflictDocumentId(error: unknown): string {
  const payload = readErrorPayload(error)
  const nested = payload.document && typeof payload.document === 'object'
    ? payload.document as Record<string, unknown>
    : {}

  // document_ids — форма, в которой конфликт отдаёт сервер (billing_service.py:
  // BillingError extra={"document_ids": ...}). Список, потому что конфликтующих
  // документов теоретически несколько; ссылку даём на первый — этого хватает,
  // чтобы человек увидел, что часы уже в счёте, а остальные найдёт в реестре.
  const ids = Array.isArray(payload.document_ids) ? payload.document_ids : []

  const candidates = [
    ids[0],
    payload.document_id,
    payload.documentId,
    payload.existing_document_id,
    payload.existingDocumentId,
    nested.id,
  ]

  for (const candidate of candidates) {
    const id = String(candidate ?? '').trim()
    if (id) {
      return id
    }
  }

  return ''
}

export type BillingErrorView = {
  title: string
  text: string
  /** Код отказа, если сервер его прислал. */
  code: string
  /** Документ, на который надо дать ссылку (только для 409). */
  documentId: string
  /** Отказ по правам или по подписке: повторять запрос бессмысленно. */
  permanent: boolean
}

/**
 * Отказы печати и выбора шаблона — по коду сервера.
 *
 * Разбираются ДО общих ветвей по статусу: «шаблон не выбран» приходит с 400,
 * и без этой таблицы превратилось бы в «сервер не принял отбор», а дело не в
 * отборе, а в настройках приложения.
 */
const DOCUMENT_TEXTS: Record<string, { title: string, text: string }> = {
  act_template_missing: {
    title: 'На портале нет шаблона акта',
    text: 'Генератор документов не нашёл шаблон, по которому печатать акт. Выберите шаблон акта в '
      + 'настройках приложения («Счёт и акт») или добавьте его в Битрикс24 — или выгрузите '
      + 'детализацию в XLSX и оформите акт по ней.',
  },
  invoice_template_missing: {
    title: 'Шаблон счёта не выбран',
    text: 'Печатную форму счёта приложение не угадывает: под «счёт» на портале подходят и '
      + 'счёт-фактура, и УПД, а отправить клиенту вместо счёта УПД нельзя. Выберите шаблон счёта '
      + 'в настройках приложения («Счёт и акт»). Сам счёт выставлен и лежит в CRM.',
  },
  billing_template_not_found: {
    title: 'Шаблон на портале не найден',
    text: 'Выбранный шаблон генератора документов удалён на портале. Откройте настройки приложения '
      + '(«Счёт и акт») и выберите другой шаблон — список подтянется с портала заново.',
  },
  invoice_generation_failed: {
    title: 'Счёт не напечатался',
    text: 'Шаблон есть, но генератор документов не собрал печатную форму счёта. Проверьте шаблон в '
      + 'Битрикс24 — сам счёт при этом выставлен и доступен в CRM.',
  },
  documentgenerator_unavailable: {
    title: 'Генератор документов недоступен',
    text: 'Портал не отдал генератор документов: модуль может быть отключён или недоступен на вашем тарифе. '
      + 'Счёт при этом выставлен — детализацию можно скачать в XLSX и напечатать акт позже.',
  },
}

/**
 * Отказ сервера -> заголовок и текст для плашки на экране.
 *
 * Порядок проверок важен: 409 (штатная идемпотентность) и коды печати акта
 * разбираются ДО общих ветвей по статусу, иначе «уже выставлено» превратится
 * в «конфликт версий», а отсутствие шаблона — в «ошибка сервера».
 */
export function describeBillingError(error: unknown): BillingErrorView {
  const status = readErrorStatus(error)
  const code = readErrorCode(error)
  const message = readErrorMessage(error)
  const serverMessage = readServerMessage(error)

  if (isRateLimitError(error)) {
    return { title: 'Слишком много запросов', text: RATE_LIMIT_NOTICE_TEXT, code, documentId: '', permanent: false }
  }

  if (DOCUMENT_TEXTS[code]) {
    return { ...DOCUMENT_TEXTS[code], code, documentId: '', permanent: false }
  }

  // 409 у этой функции значит три разные вещи, и путать их нельзя: «часы уже
  // выставлены» (идемпотентность, правило 8 контракта), «прямо сейчас
  // выставляет кто-то другой» (замок портала) и «документ уже отменён».
  // Первое — со ссылкой на готовый документ, второе — предложение повторить,
  // третье — просто факт.
  if (status === 409) {
    if (code === 'billing_busy') {
      return {
        title: 'Счёт выставляет кто-то ещё',
        text: serverMessage
          || 'На этом портале уже идёт выставление. Подождите несколько секунд и повторите — документ не создан.',
        code,
        documentId: '',
        permanent: false,
      }
    }

    if (code === 'already_cancelled') {
      return {
        title: 'Документ уже отменён',
        text: serverMessage || 'Этот документ отменён раньше — списания по нему уже свободны.',
        code,
        documentId: '',
        permanent: true,
      }
    }

    const documentId = readConflictDocumentId(error)

    return {
      title: 'Эти часы уже выставлены',
      text: documentId
        ? 'Документ с этими списаниями уже существует — откройте его, чтобы не выставить второй счёт за то же время.'
        : 'Документ с этими списаниями уже существует. Найдите его в реестре: второй счёт за те же часы приложение не создаёт.',
      code: code || 'already_invoiced',
      documentId,
      permanent: true,
    }
  }

  if (code === 'feature_disabled' || /подписк/i.test(message)) {
    return {
      title: 'Функция не подключена',
      text: '«Счёт и акт» входит в платную подписку, и на этом портале она выключена. Выставление и печать '
        + 'закрыты; реестр и отмена уже выставленных документов работают. Подключение — через администратора приложения.',
      code: code || 'feature_disabled',
      documentId: '',
      permanent: true,
    }
  }

  if (status === 403 || /недостаточно прав/i.test(message)) {
    return {
      title: 'Недостаточно прав',
      text: 'Выставлять, печатать акт и отменять документы могут админ портала и сотрудники из списка '
        + '«Бухгалтерия» в настройках приложения.',
      code,
      documentId: '',
      permanent: true,
    }
  }

  if (status === 404) {
    return {
      title: 'Не найдено',
      text: serverMessage
        || 'Сервер не знает такого адреса или документа. Если функция только выкатывается, бэкенд «Счёта и акта» '
          + 'может быть ещё не поднят — обновите страницу позже.',
      code,
      documentId: '',
      permanent: false,
    }
  }

  if (status === 400 || status === 422) {
    return {
      title: 'Сервер не принял отбор',
      text: serverMessage || 'Проверьте период и фильтры: сервер счёл запрос некорректным.',
      code,
      documentId: '',
      permanent: false,
    }
  }

  if (status !== null && status >= 500) {
    return {
      title: 'Сервер не справился',
      text: serverMessage
        || 'Попробуйте повторить запрос. Если отказ повторяется, посмотрите диагностику в настройках.',
      code,
      documentId: '',
      permanent: false,
    }
  }

  if (status === null && (!message || looksLikeNetworkFailure(message))) {
    return {
      title: 'Нет связи с сервером',
      text: 'Запрос не дошёл до приложения. Проверьте соединение и повторите — данные при этом не изменились.',
      code,
      documentId: '',
      permanent: false,
    }
  }

  // Последняя ветка ловит в том числе подменённые клиентом ошибки: $api на 403
  // отдаёт голый Error с серверным текстом и без статуса (app/stores/api.ts).
  // Такое сообщение показать можно — оно от сервера, а не от ofetch.
  const humanMessage = serverMessage
    || (message && !looksLikeNetworkFailure(message) && !looksLikeMachineMessage(message) ? message : '')

  return {
    title: 'Не получилось',
    text: humanMessage
      || 'Сервер ответил отказом без объяснения. Повторите запрос или посмотрите диагностику в настройках.',
    code,
    documentId: '',
    permanent: false,
  }
}
