/**
 * Сборка полей списания часов для смарт-процесса.
 *
 * Логика вынесена из экрана в чистые функции намеренно. Прецедент проекта
 * зафиксирован в featureFlags.ts: «вся логика формы жила внутри .vue, а
 * node:test через tsx не резолвит .vue — ревью проверяло чистые функции и не
 * могло пройти сам экран», из-за чего три дефекта формы создания проекта
 * доехали до прода. Здесь цена ошибки выше: поля ИНН, снимок ставки часа и
 * привязка к элементу проекта не видны на экране, и при их потере интерфейс
 * остаётся исправным, а расхождение всплывает только на выгрузке в 1С.
 *
 * Поведение перенесено ДОСЛОВНО из pages/embedded.vue (рабочий экран) —
 * включая приоритеты источников и решения о том, что блокирует сохранение,
 * а что только пишет предупреждение. Асинхронные части (обход иерархии задач,
 * загрузка карточки проекта, дозагрузка названия задачи) остаются в экране:
 * им нужен $b24 и apiStore.
 */

/** Минимальная форма конфигурации, от которой зависит сборка полей. */
export interface EntryFieldConfig {
  FIELDS?: Record<string, string | undefined>
  SPA_FIELDS?: Record<string, string | undefined>
}

/** Черновик записи в форме редактирования. */
export interface EntryDraft {
  id: string | number | null
  taskId: string
  description: string
  employeeId: string | number
  date: string
  hours: number
  isConsidered: boolean
  splitHours: number
  keepOriginalConsidered: boolean
}

/** Иерархия задачи: цепочка предков плюс проектный контекст. */
export interface TaskHierarchy {
  idPath?: string[]
  titlePath?: string[]
  projectId?: string | null
  projectTitle?: string
  ourInn?: string
  clientInn?: string
}

/** Карточка проекта из /api/project-board/card. */
export interface ProjectCardLike {
  project_item_id?: string | number | null
  our_legal_entity_id?: string | number | null
  our_legal_entity_inn?: string | null
  company_inn?: string | null
  hourly_rate?: string | number | null
}

/**
 * Записывает значение только если поле замаплено и значение задано.
 *
 * Пустая строка — валидное значение (ей затирают поле), а `undefined` означает
 * «нечего писать». Не-замапленное поле молча пропускается: маппинг у каждого
 * портала свой, и отсутствие необязательного поля не повод ронять сохранение.
 */
export function assignMappedField(
  target: Record<string, unknown>,
  fieldCode: string | undefined,
  value: unknown
): void {
  if (!fieldCode || value === undefined) {
    return
  }
  target[fieldCode] = value
}

/**
 * Код поля ИНН. Маппинг из SPA_FIELDS приоритетнее общего FIELDS —
 * так у портала есть возможность переопределить поле только для смарт-процесса.
 */
export function resolveInnFieldCode(
  config: EntryFieldConfig | null | undefined,
  kind: 'OUR_INN' | 'CLIENT_INN'
): string {
  if (!config) {
    return ''
  }
  return String(config.SPA_FIELDS?.[kind] || config.FIELDS?.[kind] || '').trim()
}

/** Значение считается заполненным. Пробельная строка — нет. */
export function hasMeaningfulValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false
  }
  if (typeof value === 'string') {
    return value.trim().length > 0
  }
  return true
}

/** Число или null. Пустая строка, null и мусор дают null. */
export function toNumberOrNull(value: unknown): number | null {
  const normalized = Number(value)
  return Number.isFinite(normalized) ? normalized : null
}

/**
 * Черновик новой записи. `today` передаётся снаружи, чтобы функция оставалась
 * чистой и тестируемой (в проде — new Date()).
 */
export function makeNewEntryDraft(options: {
  taskId: string
  employeeId?: string | number | null
  today: Date
}): EntryDraft {
  return {
    id: null,
    taskId: options.taskId,
    description: '',
    employeeId: options.employeeId || '',
    date: options.today.toISOString().split('T')[0] as string,
    hours: 1,
    isConsidered: true,
    splitHours: 0.5,
    keepOriginalConsidered: false
  }
}

/**
 * Базовые поля записи — без проектного контекста.
 *
 * TITLE обрезается до 255 символов: это ограничение поля заголовка элемента
 * смарт-процесса, а описание пользователь пишет свободно.
 */
export function buildBaseEntryFields(
  config: EntryFieldConfig,
  entry: Pick<EntryDraft, 'hours' | 'isConsidered' | 'description' | 'employeeId' | 'date'>,
  taskId: string
): Record<string, unknown> {
  const fields = config.FIELDS || {}
  const description = entry.description || ''

  return {
    [String(fields.HOURS)]: entry.hours,
    [String(fields.IS_CONSIDERED)]: entry.isConsidered ? 'Y' : 'N',
    [String(fields.DESCRIPTION)]: description,
    [String(fields.EMPLOYEE)]: entry.employeeId,
    [String(fields.DATE)]: entry.date,
    [String(fields.TASK_ID)]: taskId,
    TITLE: description.substring(0, 255)
  }
}

/**
 * ИНН для записи. Карточка проекта приоритетнее полей задачи: в карточке
 * реквизиты ведут осознанно, а на задаче они могли остаться от копирования.
 */
export function resolveEntryInn(source: {
  projectCard?: ProjectCardLike | null
  hierarchy?: TaskHierarchy | null
}): { ourInn: string, clientInn: string } {
  const projectOurInn = String(source.projectCard?.our_legal_entity_inn || '').trim()
  const projectClientInn = String(source.projectCard?.company_inn || '').trim()

  return {
    ourInn: projectOurInn || String(source.hierarchy?.ourInn || '').trim(),
    clientInn: projectClientInn || String(source.hierarchy?.clientInn || '').trim()
  }
}

/**
 * Дописывает в поля проектный контекст: иерархию задач, проект, ИНН, снимок
 * ставки часа и привязку к элементу Project SPA.
 *
 * `resolvedTaskName` приходит снаружи, потому что его получение асинхронное
 * (дерево -> иерархия -> запрос tasks.task.get как последний резерв).
 *
 * Мутирует переданный объект — как и оригинал в embedded.vue, чтобы порядок
 * ключей и уже записанные базовые поля не пересобирались.
 */
export function applyProjectContextFields(
  fields: Record<string, unknown>,
  config: EntryFieldConfig,
  context: {
    hierarchy?: TaskHierarchy | null
    projectCard?: ProjectCardLike | null
    resolvedTaskName?: string
  }
): void {
  const mapped = config.FIELDS || {}
  const taskNameFieldCode = String(mapped.TASK_NAME || '').trim()
  const { hierarchy, projectCard } = context

  // Без иерархии пишем только название задачи — так же, как оригинал.
  if (!hierarchy) {
    assignMappedField(fields, taskNameFieldCode || undefined, context.resolvedTaskName)
    return
  }

  const { ourInn, clientInn } = resolveEntryInn({ projectCard, hierarchy })
  const ourInnFieldCode = resolveInnFieldCode(config, 'OUR_INN')
  const clientInnFieldCode = resolveInnFieldCode(config, 'CLIENT_INN')
  const hourlyRateSnapshotFieldCode = String(mapped.HOURLY_RATE_SNAPSHOT || '').trim()
  const projectHourlyRate = toNumberOrNull(projectCard?.hourly_rate)

  assignMappedField(fields, mapped.TASK_HIERARCHY, hierarchy.idPath)
  assignMappedField(fields, mapped.TITLE_HIERARCHY, hierarchy.titlePath)

  if (hierarchy.projectId) {
    assignMappedField(fields, mapped.PROJECT_ID, hierarchy.projectId)
    assignMappedField(fields, mapped.PROJECT_TITLE, hierarchy.projectTitle)
  }

  assignMappedField(fields, taskNameFieldCode || undefined, context.resolvedTaskName)
  assignMappedField(fields, ourInnFieldCode || undefined, ourInn)
  assignMappedField(fields, clientInnFieldCode || undefined, clientInn)

  if (hierarchy.projectId) {
    const projectItemId = String(projectCard?.project_item_id || '').trim()
    if (projectItemId) {
      assignMappedField(fields, mapped.PROJECT_ITEM_ID, projectItemId)
    }
    if (hourlyRateSnapshotFieldCode && projectHourlyRate !== null && projectHourlyRate > 0) {
      assignMappedField(fields, hourlyRateSnapshotFieldCode, projectHourlyRate)
    }
    const myCompanyId = String(projectCard?.our_legal_entity_id || '').trim()
    if (myCompanyId) {
      fields.mycompanyId = /^\d+$/.test(myCompanyId) ? Number(myCompanyId) : myCompanyId
    }
  }
}

export interface EntryValidationResult {
  /** Текст ошибки для пользователя. null — сохранять можно. */
  error: string | null
  /** Предупреждение в консоль: сохранять можно, но связка неполная. */
  warning: string | null
}

/**
 * Проверка перед сохранением.
 *
 * Важное отличие двух исходов: отсутствие проектной группы БЛОКИРУЕТ запись,
 * а отсутствие project_item_id — нет. Второе сознательно: штатное списание
 * часов должно работать, даже если связка group_id → project_item_id ещё не
 * прописана в карточке проекта. Такая запись не попадёт в бюджет-аналитику,
 * но нативный поток учёта времени из-за этого страдать не должен.
 */
export function validateEntryBeforeSave(
  config: EntryFieldConfig | null | undefined,
  fields: Record<string, unknown>,
  hierarchy?: TaskHierarchy | null,
  options?: { requireRateSnapshot?: boolean }
): EntryValidationResult {
  if (!config) {
    return { error: 'Не удалось загрузить конфигурацию приложения.', warning: null }
  }

  if (!hierarchy?.projectId) {
    return {
      error: 'Задача не привязана к проектной группе. Списание без проекта запрещено.',
      warning: null
    }
  }

  const mapped = config.FIELDS || {}
  const projectItemField = mapped.PROJECT_ITEM_ID
  if (!projectItemField) {
    return {
      error: 'В настройках не задано поле «ID элемента проекта SPA». Обратитесь к администратору.',
      warning: null
    }
  }

  let warning: string | null = null
  if (!hasMeaningfulValue(fields[projectItemField])) {
    const projectLabel = hierarchy.projectTitle
      ? `«${hierarchy.projectTitle}»`
      : `group_id ${hierarchy.projectId}`
    warning = `project_item_id не найден для ${projectLabel}. Запись будет сохранена без привязки к Project SPA.`
  }

  if (options?.requireRateSnapshot === true) {
    const hourlyRateSnapshotField = String(mapped.HOURLY_RATE_SNAPSHOT || '').trim()
    if (!hourlyRateSnapshotField) {
      return {
        error: 'В настройках не задано поле «Ставка часа (снимок)». Обратитесь к администратору.',
        warning
      }
    }

    const hourlyRateSnapshot = toNumberOrNull(fields[hourlyRateSnapshotField])
    if (hourlyRateSnapshot === null || hourlyRateSnapshot <= 0) {
      return {
        error: 'Не удалось определить ставку часа проекта для сохранения снимка. Проверьте ставку в карточке проекта.',
        warning
      }
    }
  }

  return { error: null, warning }
}
