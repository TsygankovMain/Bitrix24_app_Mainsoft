/**
 * Сопоставление полей приложения с полями смарт-процессов портала.
 *
 * Здесь — ВСЯ логика экрана `/settings/mapping`, кроме разметки: состав полей,
 * состояния готовности, автоподбор, план сохранения и перевод серверных
 * ответов на человеческий язык. Причина та же, что у appNavigation.ts и
 * companySearch.ts: node:test через tsx не резолвит `.vue`, и всё, что
 * осталось внутри компонента, ревью и тестами проверить нельзя. До разбора
 * экран держал 900 строк в одном `.client.vue` без единого теста.
 *
 * Три вещи, которые тут кодируются намеренно и которых не было раньше.
 *
 * 1. У каждого поля написано, ЧТО СЛОМАЕТСЯ без него (`breaks`). Раньше была
 *    только строка «desc» про содержимое поля, и человек не мог понять, чем
 *    рискует, оставив «Не сопоставлено»: приложение при этом молчит и просто
 *    показывает пустые отчёты.
 *
 * 2. Требования СЕРВЕРА продублированы явным списком
 *    PROJECT_SPA_SERVER_REQUIRED_KEYS — это копия PROJECT_SPA_REQUIRED_MAPPING
 *    из backends/python/api/main/views.py. Сервер при сохранении конфигурации
 *    с заданным project_sp_entity_type_id прогоняет валидацию и на неполном
 *    сопоставлении отвечает 400 «Конфигурация Project SPA невалидна» — то
 *    есть «выбрать смарт-процесс сейчас, а поля дозаполнить потом»
 *    технически невозможно. Копия списка нужна, чтобы предупредить об этом
 *    ДО запроса (planMappingSave), а не показать человеку код ошибки после.
 *    Список полей смарт-процесса проектов в приложении менять нельзя, не
 *    поправив тот же список на бэкенде.
 *
 * 3. Автоподбор здесь НИЧЕГО не сохраняет: suggestMappingMatches только
 *    возвращает найденное, а применяет его человек кнопкой. Автоподбор в
 *    stores/fieldConfig.ts устроен иначе (пишет сразу в app.option и только
 *    для администратора) и покрывает пять ключей из пятнадцати — он остаётся
 *    как есть, для тех, кто на экран настроек не заходит.
 */

import type {
  AppConfigurationPayload,
  ProjectSpaValidationPayload,
  SmartProcessFieldOption,
} from '~/types/config'

/**
 * Какой из блоков экрана.
 *
 * `finance` — смарт-процесс «Доходы-расходы». Он третий и единственный
 * НЕОБЯЗАТЕЛЬНЫЙ: нужен только операциям «БДДС по проектам», а часы, отчёты
 * и счета работают без него. Отсюда особые правила ниже — шаг никогда не
 * становится «сейчас здесь», не входит в счёт шагов и не поднимает
 * общеприкладной баннер (см. buildMappingSteps, resolveMappingHealth).
 */
export type MappingBlockId = 'timesheet' | 'project' | 'finance'

/**
 * Насколько поле обязательно.
 *
 * `critical` — без него не работает сам учёт времени (в блоке проектов —
 * без него сервер отказывается сохранять конфигурацию).
 * `reports` — учёт работает, но отчёты, счета или БДДС считают неправду.
 * `optional` — теряется удобство, цифры не врут.
 */
export type MappingImportance = 'critical' | 'reports' | 'optional'

export type MappingRow = {
  key: string
  label: string
  /** Человекочитаемый тип, как он показан в строке. */
  type: string
  /** Что лежит в поле. */
  desc: string
  /** Что сломается, если поле не сопоставить. */
  breaks: string
  importance: MappingImportance
  /** Типы полей Битрикса, которые принимаются. Пусто — принимается любой. */
  acceptedTypes?: string[]
  /** Можно ли создать такое поле кнопкой (POST /api/smart-processes/create-field). */
  creatable: boolean
  /** Названия полей, по которым автоподбор узнаёт это поле. */
  synonyms: string[]
  /** Куски кода поля (UF_CRM_...), по которым автоподбор узнаёт это поле. */
  codeHints: string[]
  /**
   * Суффикс кода, с которым это поле заводит установка приложения
   * (`suffix` в *_FIELD_DEFINITIONS, backends/python/api/main/installation_service.py).
   *
   * Установка создаёт поле `UF_CRM_<N>_<суффикс>`, а портал отдаёт его как
   * `ufCrm<N><Суффикс>`, где N — внутренний номер смарт-процесса. Когда
   * суффикс известен, автоподбор узнаёт поле ТОЧНО, по коду целиком, а не
   * угадывает по названию (см. matchesInstallCode).
   */
  installCode?: string
  /**
   * Автоподбор по названию и по куску кода берёт только поля подходящего типа.
   *
   * Нужен там, где названия полей совпадают с системными полями элемента:
   * у смарт-процесса есть свои «Сумма», «Валюта», «Источник»,
   * «Ответственный», и без этой проверки «Источник» операции получил бы
   * системную стадию-справочник sourceId.
   */
  matchCompatibleTypesOnly?: boolean
}

export const PROJECT_STAGE_FIELD_KEY = 'stage'

/** Ключи стадии, оставшиеся от прежних версий конфигурации. */
export const LEGACY_PROJECT_STAGE_KEYS = [
  'stage_id',
  'project_stage',
  'manual_stage',
  'effective_stage',
] as const

/**
 * Поля метки времени (смарт-процесс списаний).
 *
 * Порядок — порядок заполнения: сначала то, без чего нет записи, потом то,
 * без чего врут отчёты, в конце удобства.
 */
export const TIMESHEET_MAPPING_ROWS: MappingRow[] = [
  {
    key: 'id_zadachi',
    label: 'ID задачи',
    type: 'число',
    desc: 'ID задачи, к которой относится списание.',
    breaks: 'Списание не привязать к задаче: вкладка в карточке задачи покажет пусто, а отчёты не соберутся вообще.',
    importance: 'critical',
    acceptedTypes: ['integer', 'string', 'double'],
    creatable: true,
    synonyms: ['ID задачи', 'Задача', 'ID Задачи'],
    codeHints: ['TASK_ID'],
  },
  {
    key: 'kolichestvo_chasov',
    label: 'Количество часов',
    type: 'число с дробной частью',
    desc: 'Сколько часов списано.',
    breaks: 'Записывать и считать часы нечем: и вкладка задачи, и все отчёты останутся пустыми.',
    importance: 'critical',
    acceptedTypes: ['double', 'integer'],
    creatable: true,
    synonyms: ['Количество часов', 'Часы', 'Часов'],
    codeHints: ['HOURS'],
  },
  {
    key: 'sotrudnik',
    label: 'Сотрудник',
    type: 'пользователь',
    desc: 'Кто списал время.',
    breaks: 'Отчёты по сотрудникам, ежедневная нагрузка и дисциплина времени останутся пустыми.',
    importance: 'reports',
    acceptedTypes: ['employee', 'user'],
    creatable: true,
    synonyms: ['Сотрудник', 'Исполнитель', 'Пользователь'],
    codeHints: ['EMPLOYEE'],
  },
  {
    key: 'data',
    label: 'Дата',
    type: 'дата',
    desc: 'Дата, за которую списаны часы.',
    breaks: 'Ни один отчёт не отберётся по периоду, а закрытие месяца не поймёт, какие часы морозить.',
    importance: 'reports',
    acceptedTypes: ['date', 'datetime'],
    creatable: true,
    synonyms: ['Дата', 'Дата списания'],
    codeHints: ['DATE'],
  },
  {
    key: 'uchitivaem',
    label: 'Учитываем?',
    type: 'да/нет',
    desc: 'Оплачиваемое ли это время.',
    breaks: 'Все часы станут оплачиваемыми: суммы в счетах и «Потери выручки» будут завышены.',
    importance: 'reports',
    acceptedTypes: ['boolean'],
    creatable: true,
    synonyms: ['Учитываем?', 'Учитываем', 'Оплачиваемое', 'Биллинг'],
    codeHints: ['IS_CONSIDERED'],
  },
  {
    key: 'ne_uchitivaemie_chasi',
    label: 'Неучитываемые часы',
    type: 'число с дробной частью',
    desc: 'Часы, которые не идут в оплату.',
    breaks: 'Отчёт «Потери выручки» не увидит неоплачиваемую часть работы.',
    importance: 'reports',
    acceptedTypes: ['double', 'integer'],
    creatable: true,
    synonyms: ['Неучитываемые часы', 'Не учитываемые часы'],
    codeHints: ['NON_BILLABLE_HOURS'],
  },
  {
    key: 'project_id',
    label: 'ID проекта (группы)',
    type: 'число или строка',
    desc: 'ID рабочей группы (проекта) портала.',
    breaks: 'Часы не свяжутся с проектом: отчёты по проектам, БДДС и счета проект не найдут.',
    importance: 'reports',
    acceptedTypes: ['integer', 'string'],
    creatable: true,
    synonyms: ['ID проекта', 'ID группы', 'Проект (ID)'],
    codeHints: ['PROJECT_ID'],
  },
  {
    key: 'project_item_id',
    label: 'ID карточки проекта',
    type: 'число',
    desc: 'ID элемента в смарт-процессе проектов.',
    breaks: 'Часы не свяжутся с карточкой проекта: бюджет часов, ставка и БДДС считаться не будут.',
    importance: 'reports',
    acceptedTypes: ['integer', 'string'],
    creatable: true,
    synonyms: ['ID элемента проекта SPA', 'ID элемента проекта', 'ID карточки проекта'],
    codeHints: ['PROJECT_ITEM_ID'],
  },
  {
    key: 'project_title',
    label: 'Название проекта',
    type: 'строка',
    desc: 'Название проекта на момент списания.',
    breaks: 'В отчётах и выгрузках вместо названия проекта будет пусто.',
    importance: 'reports',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Название проекта', 'Проект'],
    codeHints: ['PROJECT_TITLE'],
  },
  {
    key: 'task_name',
    label: 'Название задачи',
    type: 'строка',
    desc: 'Название задачи на момент списания.',
    breaks: 'В строках счёта и в отчёте по задачам вместо названия будет пусто.',
    importance: 'reports',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Название задачи', 'Задача (название)'],
    codeHints: ['TASK_NAME'],
  },
  {
    key: 'opisanie',
    label: 'Описание',
    type: 'строка',
    desc: 'Комментарий к списанию.',
    breaks: 'В отчётах и выгрузках не будет видно, за что именно списаны часы.',
    importance: 'reports',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Описание', 'Комментарий'],
    codeHints: ['DESCRIPTION'],
  },
  {
    key: 'our_inn',
    label: 'Наш ИНН',
    type: 'строка',
    desc: 'ИНН нашего юрлица, от которого велась работа.',
    breaks: 'Проверка данных и ИНН не разложит часы по юрлицам, а счёт уйдёт не от того лица.',
    importance: 'reports',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Наш ИНН', 'ИНН нашей компании', 'ИНН исполнителя'],
    codeHints: ['OUR_INN'],
  },
  {
    key: 'client_inn',
    label: 'ИНН клиента',
    type: 'строка',
    desc: 'ИНН клиента, для которого велась работа.',
    breaks: 'Часы не разложатся по клиентам: счёт не на кого выставить.',
    importance: 'reports',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['ИНН клиента', 'Клиентский ИНН'],
    codeHints: ['CLIENT_INN'],
  },
  {
    key: 'id_zadach_ierarhiya',
    label: 'Иерархия: ID задач',
    type: 'строка (JSON)',
    desc: 'Массив ID родительских задач.',
    breaks: 'В отчёте «Учёт по проектам и задачам» подзадачи не соберутся в дерево.',
    importance: 'optional',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Иерархия ID', 'Иерархия задач'],
    codeHints: ['TASK_HIERARCHY'],
  },
  {
    key: 'title_zadach_ierarhiya',
    label: 'Иерархия: названия задач',
    type: 'строка (JSON)',
    desc: 'Массив названий родительских задач.',
    breaks: 'В дереве отчёта у родительских задач вместо названий будут ID.',
    importance: 'optional',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Иерархия Названий', 'Иерархия названий'],
    codeHints: ['TITLE_HIERARCHY'],
  },
]

/**
 * Поля карточки проекта (смарт-процесс проектов).
 *
 * Все они `critical`, и это не завышение важности: сервер требует ровно этот
 * список и отказывается сохранять конфигурацию, пока в нём есть дырка (см.
 * PROJECT_SPA_SERVER_REQUIRED_KEYS ниже).
 */
export const PROJECT_MAPPING_ROWS: MappingRow[] = [
  {
    key: 'title',
    label: 'Название проекта',
    type: 'строка',
    desc: 'Название карточки проекта.',
    breaks: 'Проект будет без названия во всех списках приложения.',
    importance: 'critical',
    acceptedTypes: ['string', 'text'],
    creatable: false,
    synonyms: ['Название', 'Название проекта', 'Наименование'],
    codeHints: ['TITLE'],
  },
  {
    key: 'bitrix_group_id',
    label: 'ID группы Битрикс24',
    type: 'число или строка',
    desc: 'Связь карточки проекта с рабочей группой портала.',
    breaks: 'Карточка проекта не найдёт свои часы: бюджет, ставка и БДДС останутся нулевыми.',
    importance: 'critical',
    acceptedTypes: ['integer', 'string'],
    creatable: true,
    synonyms: ['ID группы Bitrix', 'ID группы', 'Рабочая группа', 'Группа'],
    codeHints: ['GROUP_ID', 'BITRIX_GROUP'],
  },
  {
    key: PROJECT_STAGE_FIELD_KEY,
    label: 'Стадия проекта',
    type: 'стадия',
    desc: 'Типовое поле стадии смарт-процесса.',
    breaks: 'Доска проектов не разложит карточки по колонкам, а фильтр «активные проекты» перестанет работать.',
    importance: 'critical',
    acceptedTypes: ['crm_status', 'status', 'stage'],
    creatable: false,
    synonyms: ['Стадия', 'Стадия проекта', 'Статус'],
    codeHints: ['STAGE_ID', 'STAGE'],
  },
  {
    key: 'is_support',
    label: 'Флаг поддержки',
    type: 'да/нет',
    desc: 'Проект работает в режиме поддержки.',
    breaks: 'Поддержка будет считаться обычным проектом: БДДС не увидит уход в минус по подписке.',
    importance: 'critical',
    acceptedTypes: ['boolean'],
    creatable: true,
    synonyms: ['Флаг поддержки', 'Поддержка'],
    codeHints: ['IS_SUPPORT', 'SUPPORT'],
  },
  {
    key: 'project_hours_budget',
    label: 'Бюджет часов',
    type: 'число с дробной частью',
    desc: 'Плановый объём часов проекта.',
    breaks: 'Не с чем сравнивать факт: «Риск» и «Перерасход» в БДДС не сработают.',
    importance: 'critical',
    acceptedTypes: ['double', 'integer'],
    creatable: true,
    synonyms: ['Бюджет часов', 'План часов', 'Часы плана'],
    codeHints: ['HOURS_BUDGET', 'BUDGET'],
  },
  {
    key: 'hourly_rate',
    label: 'Ставка часа',
    type: 'число с дробной частью',
    desc: 'Коммерческая ставка проекта.',
    breaks: 'Суммы в счетах и в БДДС посчитаются по ставке по умолчанию, то есть неверно.',
    importance: 'critical',
    acceptedTypes: ['double', 'integer'],
    creatable: true,
    synonyms: ['Ставка часа', 'Ставка', 'Стоимость часа'],
    codeHints: ['HOURLY_RATE', 'RATE'],
  },
  {
    key: 'curator_id',
    label: 'Куратор',
    type: 'пользователь',
    desc: 'Ответственный за проект сотрудник портала.',
    breaks: 'Уведомления о бюджете никому не уйдут: адресат берётся из этого поля.',
    importance: 'critical',
    acceptedTypes: ['employee', 'user'],
    creatable: true,
    synonyms: ['Куратор', 'Ответственный', 'Руководитель проекта'],
    codeHints: ['CURATOR'],
  },
  {
    key: 'company_id',
    label: 'Компания клиента',
    type: 'привязка к CRM',
    desc: 'Клиентская компания проекта.',
    breaks: 'Счёт не на кого выставить, а ИНН клиента в часах останется пустым.',
    importance: 'critical',
    acceptedTypes: ['crm', 'crm_company', 'string', 'integer'],
    creatable: true,
    synonyms: ['Компания', 'Клиент', 'Компания клиента', 'Контрагент'],
    codeHints: ['COMPANY'],
  },
  {
    key: 'our_legal_entity_id',
    label: 'Наше юрлицо',
    type: 'привязка к CRM',
    desc: 'Наша компания, от которой ведётся проект. В карточки подставляется из CRM-компаний с признаком «Моя компания»; искать её можно по названию и по ИНН.',
    breaks: 'Счёт уйдёт не от того юрлица, а «Наш ИНН» в часах не заполнится.',
    importance: 'critical',
    acceptedTypes: ['crm', 'crm_company', 'string', 'integer'],
    creatable: true,
    synonyms: ['Наше юрлицо', 'Наша компания', 'Юрлицо исполнителя'],
    codeHints: ['OUR_LEGAL', 'LEGAL_ENTITY', 'OUR_COMPANY'],
  },
  {
    key: 'start_date',
    label: 'Дата старта',
    type: 'дата',
    desc: 'План или факт начала проекта.',
    breaks: 'Проект не встанет на таймлайн, а БДДС не разложит бюджет по месяцам.',
    importance: 'critical',
    acceptedTypes: ['date', 'datetime'],
    creatable: true,
    synonyms: ['Дата старта', 'Начало', 'Дата начала'],
    codeHints: ['START_DATE', 'DATE_START'],
  },
  {
    key: 'finish_date',
    label: 'Дата окончания',
    type: 'дата',
    desc: 'План или факт завершения проекта.',
    breaks: 'Проект не встанет на таймлайн, а просрочка не подсветится.',
    importance: 'critical',
    acceptedTypes: ['date', 'datetime'],
    creatable: true,
    synonyms: ['Дата окончания', 'Окончание', 'Дата завершения', 'Дедлайн'],
    codeHints: ['FINISH_DATE', 'DATE_END', 'END_DATE'],
  },
  {
    key: 'is_archived',
    label: 'Архив',
    type: 'да/нет',
    desc: 'Проект убран в архив.',
    breaks: 'Закрытые проекты останутся в рабочих списках и в отчётах навсегда.',
    importance: 'critical',
    acceptedTypes: ['boolean'],
    creatable: true,
    synonyms: ['Архив', 'В архиве', 'Архивный'],
    codeHints: ['IS_ARCHIVED', 'ARCHIVE'],
  },
]

/**
 * Копия PROJECT_SPA_REQUIRED_MAPPING из backends/python/api/main/views.py.
 *
 * Сервер спрашивает стадию под ключом `stage_id`, а экран показывает её как
 * `stage` — соответствие держит PROJECT_ROW_KEY_BY_SERVER_KEY ниже.
 */
export const PROJECT_SPA_SERVER_REQUIRED_KEYS = [
  'title',
  'bitrix_group_id',
  'stage_id',
  'is_support',
  'project_hours_budget',
  'hourly_rate',
  'curator_id',
  'company_id',
  'our_legal_entity_id',
  'start_date',
  'finish_date',
  'is_archived',
] as const

/** Серверный ключ -> ключ строки экрана. Различие ровно одно, у стадии. */
export const PROJECT_ROW_KEY_BY_SERVER_KEY: Record<string, string> = {
  stage_id: PROJECT_STAGE_FIELD_KEY,
  project_stage: PROJECT_STAGE_FIELD_KEY,
  manual_stage: PROJECT_STAGE_FIELD_KEY,
  effective_stage: PROJECT_STAGE_FIELD_KEY,
}

/**
 * Поля операции «доход/расход» (смарт-процесс «Доходы-расходы»).
 *
 * Состав и суффиксы кодов — FINANCE_FIELD_DEFINITIONS из
 * backends/python/api/main/installation_service.py: те девять полей, которые
 * заводит установка приложения. Ключи — ровно те, что читает
 * FinanceOperationService (backends/python/api/main/finance_operation_service.py);
 * переименовать ключ здесь, не поправив сервис, значит тихо выключить
 * операции.
 *
 * `critical` — ровно FINANCE_SERVER_REQUIRED_KEYS: без любого из них сервис
 * операций отвечает 409 finance_spa_not_configured, и экран «Операции по
 * проектам» показывает «не настроен».
 */
export const FINANCE_MAPPING_ROWS: MappingRow[] = [
  {
    key: 'project_item_id',
    label: 'ID карточки проекта',
    type: 'число',
    desc: 'ID элемента в смарт-процессе проектов, к которому относится операция.',
    breaks: 'Операцию не к чему привязать: поступления и списания не попадут в бюджет проекта, а экран операций останется «не настроен».',
    importance: 'critical',
    acceptedTypes: ['integer', 'string'],
    creatable: true,
    synonyms: ['ID карточки проекта', 'ID элемента проекта', 'Карточка проекта'],
    codeHints: ['PROJECT_ITEM_ID'],
    installCode: 'PROJECT_ITEM_ID',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'operation_type',
    label: 'Тип операции',
    type: 'строка',
    desc: 'Поступление или списание.',
    breaks: 'Поступление не отличить от списания: все суммы посчитаются поступлениями, а экран операций останется «не настроен».',
    importance: 'critical',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Тип операции', 'Вид операции'],
    codeHints: ['OPERATION_TYPE'],
    installCode: 'OPERATION_TYPE',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'amount',
    label: 'Сумма',
    type: 'число с дробной частью',
    desc: 'Сумма операции.',
    breaks: 'Сумм не будет: финрезультат проекта и итоги реестра операций останутся нулевыми.',
    importance: 'critical',
    acceptedTypes: ['double', 'integer'],
    creatable: true,
    synonyms: ['Сумма', 'Сумма операции'],
    codeHints: ['AMOUNT'],
    installCode: 'AMOUNT',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'operation_date',
    label: 'Дата операции',
    type: 'дата',
    desc: 'Дата поступления или списания.',
    breaks: 'Операции не отберутся по периоду, а новая операция не сохранит дату.',
    importance: 'critical',
    acceptedTypes: ['date', 'datetime'],
    creatable: true,
    synonyms: ['Дата операции', 'Дата платежа'],
    codeHints: ['OPERATION_DATE'],
    installCode: 'OPERATION_DATE',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'source',
    label: 'Источник',
    type: 'строка',
    desc: 'Откуда операция: заведена вручную или пришла из сделки.',
    breaks: 'Сервер операций без этого поля их не читает: экран останется «не настроен».',
    importance: 'critical',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Источник операции', 'Источник'],
    codeHints: [],
    installCode: 'SOURCE',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'comment',
    label: 'Комментарий',
    type: 'строка',
    desc: 'Комментарий к операции.',
    breaks: 'Комментарий не сохранится, и защита от повторного сохранения перестанет узнавать операции с комментарием — деньги могут задвоиться.',
    importance: 'reports',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Комментарий', 'Комментарий к операции'],
    codeHints: [],
    installCode: 'COMMENT',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'deal_id',
    label: 'ID сделки',
    type: 'число',
    desc: 'Сделка, из которой пришла операция.',
    breaks: 'Операцию не связать со сделкой: отбор операций по сделке ничего не найдёт.',
    importance: 'optional',
    acceptedTypes: ['integer', 'string'],
    creatable: true,
    synonyms: ['ID сделки', 'Сделка (ID)'],
    codeHints: ['DEAL_ID'],
    installCode: 'DEAL_ID',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'currency',
    label: 'Валюта',
    type: 'строка',
    desc: 'Код валюты операции.',
    breaks: 'Валюта не запишется в операцию: все суммы будут показаны в рублях.',
    importance: 'optional',
    acceptedTypes: ['string', 'text'],
    creatable: true,
    synonyms: ['Валюта операции', 'Валюта'],
    codeHints: [],
    installCode: 'CURRENCY',
    matchCompatibleTypesOnly: true,
  },
  {
    key: 'responsible_user_id',
    label: 'Ответственный',
    type: 'пользователь',
    desc: 'Сотрудник, к которому относится операция.',
    breaks: 'В колонке «Автор» реестра операций будет ответственный за элемент CRM, а не сотрудник из операции.',
    importance: 'optional',
    acceptedTypes: ['employee', 'user'],
    creatable: true,
    synonyms: ['Ответственный за операцию', 'Ответственный'],
    codeHints: ['RESPONSIBLE_USER_ID'],
    installCode: 'RESPONSIBLE_USER_ID',
    matchCompatibleTypesOnly: true,
  },
]

/**
 * Копия required_keys из FinanceOperationService._ensure_configured
 * (backends/python/api/main/finance_operation_service.py).
 *
 * Сервер операций проверяет эти ключи при каждом чтении и записи и без
 * любого из них отвечает 409 finance_spa_not_configured. Сохранение
 * конфигурации их НЕ проверяет — поэтому неполное сопоставление сохранить
 * можно (черновик), а предупредить о последствиях обязан экран.
 */
export const FINANCE_SERVER_REQUIRED_KEYS = [
  'project_item_id',
  'operation_type',
  'amount',
  'operation_date',
  'source',
] as const

/** Название готового смарт-процесса, который заводит установка приложения. */
export const FINANCE_APP_SMART_PROCESS_TITLE = 'Доходы-расходы (App)'

/** Код готового смарт-процесса (SMART_PROCESS_DEFINITIONS['finance']['code']). */
export const FINANCE_APP_SMART_PROCESS_CODE = 'finance_app'

export function getMappingRows(block: MappingBlockId): MappingRow[] {
  switch (block) {
    case 'timesheet':
      return TIMESHEET_MAPPING_ROWS
    case 'finance':
      return FINANCE_MAPPING_ROWS
    default:
      return PROJECT_MAPPING_ROWS
  }
}

// region Ссылки на шаги экрана

/** Адрес экрана сопоставления. Одна строка на приложение, чтобы не разъехалась. */
export const MAPPING_SETTINGS_PATH = '/settings/mapping'

/** Параметр адреса, которым другие экраны открывают нужный шаг. */
export const MAPPING_STEP_QUERY_KEY = 'step'

/** id карточки шага и id выпадающего списка процесса в ней. */
const MAPPING_STEP_TARGETS: Record<MappingBlockId, { anchor: string, focusId: string }> = {
  timesheet: { anchor: 'block-timesheet-process', focusId: 'timesheet-process' },
  project: { anchor: 'block-project-process', focusId: 'project-process' },
  finance: { anchor: 'block-finance-process', focusId: 'finance-process' },
}

/**
 * Ссылка сразу на шаг экрана сопоставления.
 *
 * Параметр, а не `#якорь`: экран дочитывает конфигурацию и поля портала уже
 * после перехода, и к моменту, когда роутер ищет якорь, карточки шага на
 * странице ещё нет — прокрутка по хэшу молча не срабатывала бы. Параметр
 * экран читает сам, после загрузки (resolveMappingStepTarget).
 */
export function buildMappingStepLink(block: MappingBlockId): string {
  return `${MAPPING_SETTINGS_PATH}?${MAPPING_STEP_QUERY_KEY}=${block}`
}

/** Куда прокрутить экран по параметру адреса. Чужое значение — никуда. */
export function resolveMappingStepTarget(
  value: unknown
): { block: MappingBlockId, anchor: string, focusId: string } | null {
  const raw = Array.isArray(value) ? value[0] : value
  const block = String(raw || '').trim().toLowerCase() as MappingBlockId

  if (!Object.prototype.hasOwnProperty.call(MAPPING_STEP_TARGETS, block)) {
    return null
  }

  return { block, ...MAPPING_STEP_TARGETS[block] }
}

// endregion

/** Подпись серверного ключа по-человечески. Неизвестный ключ отдаём как есть. */
export function describeMappingKey(block: MappingBlockId, key: string): string {
  const normalizedKey = PROJECT_ROW_KEY_BY_SERVER_KEY[key] || key
  const row = getMappingRows(block).find(item => item.key === normalizedKey)

  return row ? row.label : key
}

// region Нормализация состояния

/** Выкидывает пустые значения и приводит всё к строкам. */
export function normalizeMappingState(source?: Record<string, string> | null): Record<string, string> {
  return Object.entries(source || {}).reduce<Record<string, string>>((acc, [key, value]) => {
    if (!value) {
      return acc
    }

    acc[key] = String(value)
    return acc
  }, {})
}

/**
 * Стадия проекта из конфигурации любой давности.
 *
 * Ключей у неё исторически пять, и лежать они могут как внутри
 * project_fields_mapping, так и в корне конфигурации. Сервер при
 * нормализации размножает значение по всем пяти, поэтому читаем первый
 * непустой.
 */
export function getLegacyStageValue(configSource: AppConfigurationPayload): string {
  const projectFields = (configSource.project_fields_mapping || {}) as Record<string, unknown>
  const candidates = [
    projectFields.stage_id,
    projectFields[PROJECT_STAGE_FIELD_KEY],
    projectFields.project_stage,
    projectFields.effective_stage,
    projectFields.manual_stage,
    configSource.stage_id,
    configSource[PROJECT_STAGE_FIELD_KEY],
    configSource.project_stage,
    configSource.effective_stage,
    configSource.manual_stage,
  ]

  return candidates.map(value => String(value || '').trim()).find(value => value.length > 0) || ''
}

/** Сопоставление проекта в виде, удобном экрану: одна стадия под ключом `stage`. */
export function normalizeProjectMappingState(configSource: AppConfigurationPayload): Record<string, string> {
  const next = normalizeMappingState(configSource.project_fields_mapping || {})
  const stageValue = getLegacyStageValue(configSource)

  for (const legacyKey of [...LEGACY_PROJECT_STAGE_KEYS, PROJECT_STAGE_FIELD_KEY]) {
    Reflect.deleteProperty(next, legacyKey)
  }

  if (stageValue) {
    next[PROJECT_STAGE_FIELD_KEY] = stageValue
  }

  return next
}

/** Сопоставление проекта в виде, который ждёт сервер: стадия во всех пяти ключах. */
export function serializeProjectMappingState(source: Record<string, string>): Record<string, string> {
  const next = normalizeMappingState(source)
  const stageValue = String(
    next.stage_id
    || next[PROJECT_STAGE_FIELD_KEY]
    || next.project_stage
    || next.effective_stage
    || next.manual_stage
    || ''
  ).trim()

  for (const legacyKey of [...LEGACY_PROJECT_STAGE_KEYS, PROJECT_STAGE_FIELD_KEY]) {
    Reflect.deleteProperty(next, legacyKey)
  }

  if (stageValue) {
    next.stage_id = stageValue
    next[PROJECT_STAGE_FIELD_KEY] = stageValue
    next.manual_stage = stageValue
    next.effective_stage = stageValue
    next.project_stage = stageValue
  }

  return next
}

/**
 * Значение только что созданного поля.
 *
 * Сервер возвращает и обновлённую конфигурацию, и id созданного поля.
 * Доверяем сначала конфигурации, а `field_id` держим запасным вариантом:
 * бывает, что конфигурация в ответе ещё без нового ключа.
 */
export function mergeCreatedFieldMapping(
  currentMapping: Record<string, string>,
  serverMapping: Record<string, string> | undefined,
  fieldKey: string,
  fallbackValue?: string | number | null
): Record<string, string> {
  const next = { ...normalizeMappingState(currentMapping) }
  const serverValue = serverMapping?.[fieldKey]
  const normalizedFallback = fallbackValue === undefined || fallbackValue === null
    ? ''
    : String(fallbackValue).trim()

  if (serverValue !== undefined && serverValue !== null && String(serverValue).trim()) {
    next[fieldKey] = String(serverValue)
  } else if (normalizedFallback) {
    next[fieldKey] = normalizedFallback
  }

  return next
}

// endregion

// region Типы полей и варианты выбора

export function normalizeFieldType(value?: string | null): string {
  return String(value || '').trim().toLowerCase()
}

/**
 * Подходит ли поле портала под строку сопоставления.
 *
 * Псевдонимы — те же, что у сервера (PROJECT_SPA_TYPE_ALIASES в views.py):
 * разойтись они не имеют права, иначе экран разрешит то, что сервер потом
 * отклонит.
 */
export function isFieldTypeCompatible(row: MappingRow, optionType?: string | null): boolean {
  if (!row.acceptedTypes?.length) {
    return true
  }

  const accepted = new Set(row.acceptedTypes.map(type => normalizeFieldType(type)))
  const actualType = normalizeFieldType(optionType)
  if (!actualType) {
    return false
  }

  if (accepted.has(actualType)) {
    return true
  }
  if (accepted.has('string') && ['text', 'char', 'url'].includes(actualType)) {
    return true
  }
  if (accepted.has('integer') && ['int'].includes(actualType)) {
    return true
  }
  if (accepted.has('double') && ['float', 'money', 'integer', 'int'].includes(actualType)) {
    return true
  }
  if (accepted.has('employee') && ['user'].includes(actualType)) {
    return true
  }
  if (accepted.has('crm_status') && ['status', 'stage'].includes(actualType)) {
    return true
  }
  if (accepted.has('crm') && ['crm_company', 'crm_entity'].includes(actualType)) {
    return true
  }
  if (accepted.has('date') && ['datetime'].includes(actualType)) {
    return true
  }

  return false
}

export type MappingFieldOption = {
  value: string
  label: string
  type: string
}

export type MappingFieldOptionGroups = {
  /** Поля подходящего типа. */
  suitable: MappingFieldOption[]
  /**
   * Остальные поля смарт-процесса.
   *
   * Раньше их просто не показывали, и если на портале под дату завели
   * строковое поле, сопоставить его было НЕЧЕМ — выпадающий список выглядел
   * пустым без объяснения. Теперь они доступны отдельной группой с честной
   * подписью «тип не совпадает».
   */
  other: MappingFieldOption[]
}

export function buildFieldOptionGroups(
  row: MappingRow,
  spFields: SmartProcessFieldOption[],
  currentValue?: string | null
): MappingFieldOptionGroups {
  const current = String(currentValue || '').trim()
  const suitable: MappingFieldOption[] = []
  const other: MappingFieldOption[] = []

  for (const field of spFields || []) {
    const value = String(field.id || '').trim()
    if (!value) {
      continue
    }

    const option: MappingFieldOption = {
      value,
      label: String(field.title || value),
      type: normalizeFieldType(field.type),
    }

    if (isFieldTypeCompatible(row, field.type) || value === current) {
      suitable.push(option)
    } else {
      other.push(option)
    }
  }

  return { suitable, other }
}

/** Есть ли выбранное значение среди полей смарт-процесса. */
export function isMappedFieldMissing(
  mappedValue: string | undefined | null,
  spFields: SmartProcessFieldOption[]
): boolean {
  const value = String(mappedValue || '').trim()
  if (!value) {
    return false
  }

  if (!spFields?.length) {
    return false
  }

  return !spFields.some(field => String(field.id || '').trim().toLowerCase() === value.toLowerCase())
}

// endregion

// region Состояния готовности

export type MappingBlockState =
  /** Смарт-процесс не выбран. */
  | 'no-process'
  /** Смарт-процесс выбран, но его поля ещё не загружены. */
  | 'no-fields'
  /** Поля загружены, сопоставлений нет ни одного. */
  | 'empty'
  /** Часть обязательных полей не сопоставлена. */
  | 'partial'
  /** Обязательное сопоставлено; необязательное могло остаться пустым. */
  | 'ready'

export type MappingBlockStatus = {
  block: MappingBlockId
  state: MappingBlockState
  entityTypeId: number
  mappedCount: number
  totalCount: number
  requiredTotal: number
  requiredMapped: number
  missingCritical: MappingRow[]
  missingReports: MappingRow[]
  missingOptional: MappingRow[]
  /** Строки, чьё сопоставление указывает на поле, которого в СП нет. */
  brokenRows: MappingRow[]
  /** Одна фраза про текущее положение. */
  headline: string
  /** Одна фраза про то, что делать дальше. */
  nextStep: string
}

function isRequiredRow(row: MappingRow): boolean {
  return row.importance !== 'optional'
}

export function resolveMappingBlockStatus(input: {
  block: MappingBlockId
  entityTypeId: number | null | undefined
  spFields: SmartProcessFieldOption[]
  mapping: Record<string, string>
}): MappingBlockStatus {
  const rows = getMappingRows(input.block)
  const entityTypeId = Number(input.entityTypeId || 0)
  const mapping = normalizeMappingState(input.mapping)
  const spFields = input.spFields || []

  const missingCritical: MappingRow[] = []
  const missingReports: MappingRow[] = []
  const missingOptional: MappingRow[] = []
  const brokenRows: MappingRow[] = []
  let mappedCount = 0

  for (const row of rows) {
    const value = String(mapping[row.key] || '').trim()
    if (!value) {
      if (row.importance === 'critical') {
        missingCritical.push(row)
      } else if (row.importance === 'reports') {
        missingReports.push(row)
      } else {
        missingOptional.push(row)
      }
      continue
    }

    mappedCount += 1
    if (isMappedFieldMissing(value, spFields)) {
      brokenRows.push(row)
    }
  }

  const requiredRows = rows.filter(isRequiredRow)
  const requiredMissing = [...missingCritical, ...missingReports]
  const requiredMapped = requiredRows.length - requiredMissing.length

  const blockName = input.block === 'timesheet'
    ? 'списаний'
    : input.block === 'finance' ? '«Доходы-расходы»' : 'проектов'
  let state: MappingBlockState = 'ready'

  if (!entityTypeId) {
    state = 'no-process'
  } else if (!spFields.length) {
    state = 'no-fields'
  } else if (mappedCount === 0) {
    state = 'empty'
  } else if (requiredMissing.length > 0) {
    state = 'partial'
  }

  const headline = ((): string => {
    switch (state) {
      case 'no-process':
        return `Смарт-процесс ${blockName} не выбран`
      case 'no-fields':
        return `Поля смарт-процесса ${blockName} не загружены`
      case 'empty':
        return 'Ни одно поле не сопоставлено'
      case 'partial':
        return `Сопоставлено ${requiredMapped} из ${requiredRows.length} обязательных полей`
      default:
        return missingOptional.length
          ? `Обязательное сопоставлено, необязательных не хватает: ${missingOptional.length}`
          : 'Сопоставлены все поля'
    }
  })()

  const nextStep = ((): string => {
    switch (state) {
      case 'no-process':
        if (input.block === 'timesheet') {
          return 'Выберите смарт-процесс, в который приложение пишет списания, или создайте новый кнопкой ниже.'
        }
        if (input.block === 'finance') {
          return `Выберите смарт-процесс «${FINANCE_APP_SMART_PROCESS_TITLE}» — в нём ведутся поступления и списания по проектам. Шаг нужен только для операций БДДС.`
        }
        return 'Выберите смарт-процесс с карточками проектов. Без него не работают доска проектов, БДДС и счета.'
      case 'no-fields':
        return 'Нажмите «Обновить список полей»: без полей портала сопоставлять нечего.'
      case 'empty':
        return input.block === 'finance'
          ? 'Нажмите «Подобрать автоматически» — поля, заведённые установкой приложения, найдутся точно по коду, остальные по названиям. Результат вы проверите до сохранения.'
          : 'Нажмите «Подобрать автоматически» — приложение найдёт поля по названиям, а вы проверите результат до сохранения.'
      case 'partial':
        return requiredMissing.length === 1 && requiredMissing[0]
          ? `Осталось сопоставить «${requiredMissing[0].label}».`
          : `Осталось сопоставить ${requiredMissing.length} обязательных полей — они помечены ниже.`
      default:
        return brokenRows.length
          ? 'Часть сопоставлений указывает на поля, которых в смарт-процессе больше нет: их надо переназначить.'
          : 'Дальше действий не требуется — нажмите «Сохранить».'
    }
  })()

  return {
    block: input.block,
    state,
    entityTypeId,
    mappedCount,
    totalCount: rows.length,
    requiredTotal: requiredRows.length,
    requiredMapped: Math.max(0, requiredMapped),
    missingCritical,
    missingReports,
    missingOptional,
    brokenRows,
    headline,
    nextStep,
  }
}

export type MappingStepState = 'done' | 'current' | 'todo' | 'attention' | 'optional'

export type MappingStep = {
  id: string
  title: string
  hint: string
  state: MappingStepState
  /** id блока на странице, к которому ведёт шаг. */
  anchor: string
  /**
   * Шаг по желанию («Доходы-расходы»).
   *
   * Такой шаг не бывает «сейчас здесь» и не входит в «N из M шагов»: иначе
   * тот, кто пользуется только часами и отчётами, никогда не увидел бы
   * «настройка завершена».
   */
  optional: boolean
}

/**
 * Шаги настройки для полосы прогресса.
 *
 * `current` ровно один — первый незакрытый шаг. Так человек видит не просто
 * «где дырки», а с чего начать; остальные незакрытые остаются `todo`.
 * `attention` — шаг формально пройден, но в нём есть проблема (битые
 * сопоставления, отказ проверки).
 */
export function buildMappingSteps(input: {
  timesheet: MappingBlockStatus
  project: MappingBlockStatus
  validation?: ProjectSpaValidationPayload | null
  /** Статус «Доходов-расходов». Не передан — шага в полосе нет. */
  finance?: MappingBlockStatus | null
  /**
   * У портала подключён «БДДС по проектам».
   *
   * Тогда начатая, но не законченная настройка «Доходов-расходов» — это
   * проблема (операции не работают у тех, кто за них платит), и шаг
   * помечается «есть проблема». Без подписки шаг просто «по желанию».
   */
  financeNeeded?: boolean
}): MappingStep[] {
  const { timesheet, project, validation, finance, financeNeeded } = input

  const steps: Array<Omit<MappingStep, 'state' | 'optional'> & { done: boolean, attention: boolean, optional?: boolean }> = [
    {
      id: 'timesheet-process',
      title: 'Смарт-процесс списаний',
      hint: 'Куда приложение пишет часы',
      anchor: 'block-timesheet-process',
      done: timesheet.state !== 'no-process',
      attention: false,
    },
    {
      id: 'timesheet-fields',
      title: 'Поля списаний',
      hint: `${timesheet.requiredMapped} из ${timesheet.requiredTotal} обязательных`,
      anchor: 'block-timesheet-fields',
      done: timesheet.state === 'ready',
      attention: timesheet.brokenRows.length > 0,
    },
    {
      id: 'project-process',
      title: 'Смарт-процесс проектов',
      hint: 'Карточки проектов: бюджет, ставка, куратор',
      anchor: 'block-project-process',
      done: project.state !== 'no-process',
      attention: false,
    },
    {
      id: 'project-fields',
      title: 'Поля проектов',
      hint: `${project.requiredMapped} из ${project.requiredTotal} обязательных`,
      anchor: 'block-project-fields',
      done: project.state === 'ready',
      attention: project.brokenRows.length > 0,
    },
    {
      id: 'project-check',
      title: 'Проверка связности',
      hint: 'Права приложения и связь карточек с группами',
      anchor: 'block-project-check',
      done: Boolean(validation?.is_valid),
      attention: Boolean(validation && !validation.is_valid && validation.is_configured),
    },
  ]

  if (finance) {
    const started = finance.state !== 'no-process'
    steps.push({
      id: 'finance',
      title: 'Доходы-расходы',
      hint: started
        ? `${finance.requiredMapped} из ${finance.requiredTotal} обязательных · по желанию`
        : 'Только для операций БДДС · по желанию',
      anchor: MAPPING_STEP_TARGETS.finance.anchor,
      done: finance.state === 'ready',
      attention: finance.brokenRows.length > 0
        || Boolean(financeNeeded && started && finance.state !== 'ready'),
      optional: true,
    })
  }

  const firstUnfinished = steps.findIndex(step => !step.done && !step.optional)

  return steps.map((step, index) => {
    let state: MappingStepState = step.done ? 'done' : 'todo'
    if (step.attention) {
      state = 'attention'
    } else if (!step.done && step.optional) {
      state = 'optional'
    } else if (!step.done && index === firstUnfinished) {
      state = 'current'
    }

    return {
      id: step.id,
      title: step.title,
      hint: step.hint,
      anchor: step.anchor,
      state,
      optional: Boolean(step.optional),
    }
  })
}

export type MappingOverallState = 'not-started' | 'in-progress' | 'ready-with-gaps' | 'ready'

export type MappingOverall = {
  state: MappingOverallState
  title: string
  text: string
  /** Сколько шагов из полосы прогресса закрыто. */
  doneSteps: number
  totalSteps: number
}

export function resolveMappingOverall(steps: MappingStep[], input: {
  timesheet: MappingBlockStatus
  project: MappingBlockStatus
}): MappingOverall {
  // Шаг по желанию в счёт не входит ни в числителе, ни в знаменателе.
  const requiredSteps = steps.filter(step => !step.optional)
  const doneSteps = requiredSteps.filter(step => step.state === 'done').length
  const totalSteps = requiredSteps.length
  const { timesheet, project } = input

  if (timesheet.state === 'no-process' && project.state === 'no-process') {
    return {
      state: 'not-started',
      title: 'Приложение ещё не настроено',
      text: 'Пока поля не сопоставлены, приложению некуда писать часы: вкладка задачи, отчёты, счета и БДДС будут пустыми. Настройка идёт по шагам сверху вниз и занимает несколько минут.',
      doneSteps,
      totalSteps,
    }
  }

  if (timesheet.state === 'ready' && project.state === 'ready') {
    const hasGaps = timesheet.missingOptional.length > 0
      || project.missingOptional.length > 0
      || timesheet.brokenRows.length > 0
      || project.brokenRows.length > 0

    return hasGaps
      ? {
          state: 'ready-with-gaps',
          title: 'Всё обязательное сопоставлено',
          text: 'Приложение работает. Осталось необязательное — без него цифры верные, но часть удобств недоступна; список ниже.',
          doneSteps,
          totalSteps,
        }
      : {
          state: 'ready',
          title: 'Настройка завершена',
          text: 'Сопоставлены все поля обоих смарт-процессов, проверка связности пройдена. Возвращаться сюда нужно только при изменении полей на портале.',
          doneSteps,
          totalSteps,
        }
  }

  return {
    state: 'in-progress',
    title: `Настройка не закончена: ${doneSteps} из ${totalSteps} шагов`,
    text: 'Ниже помечено, чего не хватает. Пока шаги не закрыты, часть приложения работать не будет — рядом с каждым полем написано, что именно.',
    doneSteps,
    totalSteps,
  }
}

// endregion

// region План сохранения

export type MappingSaveBlocker = {
  key: string
  label: string
  reason: string
}

export type MappingSavePlan =
  /** Сохраняем всё как есть. */
  | { kind: 'full', title: string, note: string, projectSpIdToSend: number }
  /** Сохраняем только списания, выбор смарт-процесса проектов оставляем в черновике. */
  | { kind: 'timesheet-only', title: string, note: string, projectSpIdToSend: number }
  /** Сохранять нельзя: сервер откажет, объясняем заранее. */
  | { kind: 'blocked', title: string, note: string, blockers: MappingSaveBlocker[] }

/**
 * Что произойдёт при нажатии «Сохранить».
 *
 * Ловушка, которую эта функция обходит: save_configuration на бэкенде
 * валидирует смарт-процесс проектов ЦЕЛИКОМ, как только в конфигурации есть
 * project_sp_entity_type_id > 0, и на неполном сопоставлении отвечает 400,
 * НЕ сохраняя ничего — включая уже сделанную работу по списаниям. То есть
 * «выберу процесс, поля дозаполню завтра» невозможно, и человек об этом
 * узнавал текстом «Конфигурация Project SPA не прошла валидацию» после
 * того, как потерял несохранённые правки.
 *
 * Решение — сохранять по частям и говорить об этом заранее:
 *
 * - смарт-процесс проектов не выбран или сопоставлен полностью -> обычное
 *   сохранение;
 * - выбран в черновике (на сервере его ещё нет), но сопоставление неполное ->
 *   сохраняем ТОЛЬКО списания: в запрос уходит project_sp_entity_type_id = 0
 *   (то есть ровно то, что и так лежит на сервере), а черновик сопоставления
 *   проектов сохраняется вместе с ним и никуда не пропадает. Валидация на
 *   сервере при нуле не запускается, 400 взяться негде;
 * - процесс УЖЕ сохранён на сервере, а сопоставление стало неполным (на
 *   портале удалили поле) -> сохранять нельзя: обнулить процесс значило бы
 *   тихо выключить синхронизацию проектов, а отправить как есть — получить
 *   400. Показываем, что именно починить.
 */
export function planMappingSave(input: {
  selectedProjectSpId: number | null | undefined
  savedProjectSpId: number | null | undefined
  projectStatus: MappingBlockStatus
}): MappingSavePlan {
  const selected = Number(input.selectedProjectSpId || 0)
  const saved = Number(input.savedProjectSpId || 0)
  const { projectStatus } = input

  if (!selected) {
    return saved
      ? {
          kind: 'full',
          title: 'Смарт-процесс проектов будет отвязан',
          note: 'Сохранение уберёт связь с карточками проектов: доска проектов, БДДС и счета перестанут получать бюджет, ставку и куратора. Если это не то, что нужно, верните процесс в поле выше.',
          projectSpIdToSend: 0,
        }
      : {
          kind: 'full',
          title: 'Сохраняем сопоставление списаний',
          note: 'Смарт-процесс проектов не выбран — доска проектов, БДДС и счета останутся без данных о проектах.',
          projectSpIdToSend: 0,
        }
  }

  if (projectStatus.state === 'ready') {
    return {
      kind: 'full',
      title: 'Сохраняем оба смарт-процесса',
      note: 'После сохранения приложение сразу синхронизирует карточки проектов и подтянет связи у уже внесённых часов — это занимает до минуты.',
      projectSpIdToSend: selected,
    }
  }

  const blockers = [...projectStatus.missingCritical, ...projectStatus.missingReports].map<MappingSaveBlocker>(row => ({
    key: row.key,
    label: row.label,
    reason: row.breaks,
  }))

  if (!saved) {
    return {
      kind: 'timesheet-only',
      title: 'Сохраним пока только списания',
      note: `Смарт-процесс проектов сервер принимает только с полным сопоставлением, а в нём не хватает ${blockers.length} ${pluralizeFields(blockers.length)}. Сопоставление списаний и черновик по проектам сохранятся сейчас, сам выбор процесса — когда заполните остальное.`,
      projectSpIdToSend: 0,
    }
  }

  return {
    kind: 'blocked',
    title: 'Сохранить нельзя: сопоставление проектов неполное',
    note: 'Смарт-процесс проектов уже подключён, и сервер принимает его только целиком. Отвязать его вместо этого — значит выключить доску проектов, БДДС и счета, поэтому сначала заполните недостающее: кнопка «Подобрать автоматически» находит поля по названиям, «Создать поле» заводит нужное поле на портале.',
    blockers,
  }
}

function pluralizeFields(count: number): string {
  const mod100 = Math.abs(count) % 100
  const mod10 = mod100 % 10

  if (mod100 >= 11 && mod100 <= 14) {
    return 'полей'
  }
  if (mod10 === 1) {
    return 'поля'
  }
  if (mod10 >= 2 && mod10 <= 4) {
    return 'полей'
  }
  return 'полей'
}

/**
 * Значение `scope` в теле POST /api/configuration/save для отдельного
 * сохранения «Доходов-расходов».
 *
 * Зачем он вообще нужен. Сервер при project_sp_entity_type_id > 0 на
 * КАЖДОМ сохранении валидирует смарт-процесс проектов и запускает
 * синхронизацию (save_configuration в views.py). Для шага, который к
 * проектам отношения не имеет, это означало бы: сохранение операций ждёт
 * синхронизацию проектов, съедает её лимит 6 в минуту и упирается в 400,
 * если на портале поломалось сопоставление проектов. С этим признаком
 * сервер пропускает проектную ветку — но ТОЛЬКО если проектная часть
 * присланной конфигурации совпадает с сохранённой; иначе идёт обычным
 * путём, и обойти проверку проектов через него нельзя.
 */
export const FINANCE_CONFIG_SAVE_SCOPE = 'finance'

export type FinanceSavePlanKind =
  /** Не выбран и не был выбран — сохранять нечего. */
  | 'skip'
  /** Был выбран, теперь снят: операции перестанут читаться. */
  | 'unlink'
  /** Выбран, но обязательных для сервера операций полей не хватает. */
  | 'draft'
  /** Выбран и готов. */
  | 'ready'

export type FinanceSavePlan = {
  kind: FinanceSavePlanKind
  title: string
  note: string
  financeSpIdToSend: number
  /** Поля, без которых сервер операций отвечает «не настроен». */
  missing: MappingSaveBlocker[]
}

/**
 * Что будет с «Доходами-расходами» при сохранении.
 *
 * В отличие от проектов, сервер конфигурацию операций при сохранении не
 * проверяет, поэтому сохранить можно и неполное сопоставление — это
 * черновик. Честно говорим, чем он кончится: экран операций останется
 * «не настроен», пока не заполнены FINANCE_SERVER_REQUIRED_KEYS.
 */
export function planFinanceMappingSave(input: {
  selectedFinanceSpId: number | null | undefined
  savedFinanceSpId: number | string | null | undefined
  financeStatus: MappingBlockStatus
  mapping: Record<string, string>
}): FinanceSavePlan {
  const selected = Number(input.selectedFinanceSpId || 0)
  const saved = Number(input.savedFinanceSpId || 0)
  const mapping = normalizeMappingState(input.mapping)

  if (!selected) {
    return saved
      ? {
          kind: 'unlink',
          title: 'Смарт-процесс «Доходы-расходы» будет отвязан',
          note: 'Экран «Операции по проектам» и блок операций в карточке проекта перестанут показывать поступления и списания, а заводить их станет некуда. Часы, отчёты и счета это не затронет.',
          financeSpIdToSend: 0,
          missing: [],
        }
      : {
          kind: 'skip',
          title: '«Доходы-расходы» не настроены',
          note: 'Шаг необязательный: часы, отчёты и счета работают без него. Операции БДДС до его настройки недоступны.',
          financeSpIdToSend: 0,
          missing: [],
        }
  }

  const missing = FINANCE_MAPPING_ROWS
    .filter(row => (FINANCE_SERVER_REQUIRED_KEYS as readonly string[]).includes(row.key))
    .filter(row => !String(mapping[row.key] || '').trim())
    .map<MappingSaveBlocker>(row => ({ key: row.key, label: row.label, reason: row.breaks }))

  const switched = saved > 0 && saved !== selected
    ? ` Операции из прежнего смарт-процесса (ID ${saved}) приложение показывать перестанет — они останутся на портале.`
    : ''

  if (missing.length) {
    return {
      kind: 'draft',
      title: 'Сохранится черновик: операции пока работать не будут',
      note: `Не сопоставлено ${missing.length} из ${FINANCE_SERVER_REQUIRED_KEYS.length} полей, без которых сервер операций отвечает «не настроен». Сохранить можно — дозаполните их позже.${switched}`,
      financeSpIdToSend: selected,
      missing,
    }
  }

  const gaps = input.financeStatus.missingReports.length + input.financeStatus.missingOptional.length

  return {
    kind: 'ready',
    title: 'Сохраняем «Доходы-расходы»',
    note: gaps
      ? `Операции заработают сразу после сохранения. Не сопоставлено необязательных полей: ${gaps} — рядом с каждым написано, чего без него не будет.${switched}`
      : `Операции заработают сразу после сохранения.${switched}`,
    financeSpIdToSend: selected,
    missing: [],
  }
}

/**
 * Конфигурация целиком с подставленными ключами «Доходов-расходов».
 *
 * Сервер хранит настройки ОДНОЙ строкой JSON в app.option, поэтому
 * сохраняется всегда вся конфигурация: прислать только два финансовых ключа
 * значит затереть всё остальное — сопоставление списаний, проекты, счета.
 * Остальные ключи берутся из `base` без изменений.
 */
export function applyFinanceMappingToConfig(
  base: AppConfigurationPayload,
  input: { entityTypeId: number | null | undefined, mapping: Record<string, string> }
): AppConfigurationPayload {
  const entityTypeId = Number(input.entityTypeId || 0)

  return {
    ...base,
    finance_sp_entity_type_id: entityTypeId > 0 ? entityTypeId : 0,
    finance_fields_mapping: normalizeMappingState(input.mapping),
  }
}

/** Отличается ли черновик «Доходов-расходов» от сохранённого на сервере. */
export function isFinanceMappingChanged(
  saved: AppConfigurationPayload,
  input: { entityTypeId: number | null | undefined, mapping: Record<string, string> }
): boolean {
  if (Number(saved.finance_sp_entity_type_id || 0) !== Number(input.entityTypeId || 0)) {
    return true
  }

  const before = normalizeMappingState(saved.finance_fields_mapping || {})
  const after = normalizeMappingState(input.mapping)
  const keys = new Set([...Object.keys(before), ...Object.keys(after)])

  for (const key of keys) {
    if ((before[key] || '') !== (after[key] || '')) {
      return true
    }
  }

  return false
}

/**
 * Готовый «Доходы-расходы (App)» среди смарт-процессов портала.
 *
 * Сначала по коду `finance_app` (его ставит установка, и он не меняется при
 * переименовании процесса на портале), затем по названию — для ответов
 * сервера, где кода ещё нет.
 */
export function findFinanceAppSmartProcess<T extends { entityTypeId: number, title?: unknown, code?: unknown }>(
  processes: T[]
): T | null {
  const byCode = processes.find(item => String(item.code || '').trim().toLowerCase() === FINANCE_APP_SMART_PROCESS_CODE)
  if (byCode) {
    return byCode
  }

  const title = normalizeSearchText(FINANCE_APP_SMART_PROCESS_TITLE)
  return processes.find(item => normalizeSearchText(item.title) === title) || null
}

// endregion

// region Автоподбор

export type MappingSuggestionSource = 'install' | 'label' | 'code' | 'type'

export type MappingSuggestion = {
  key: string
  label: string
  fieldId: string
  fieldTitle: string
  fieldType: string
  source: MappingSuggestionSource
  /** Пояснение, откуда взялось совпадение. */
  reason: string
}

function normalizeSearchText(value: unknown): string {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ')
}

function normalizeCode(value: unknown): string {
  return normalizeSearchText(value).replace(/[_\s-]/g, '')
}

/**
 * Совпадает ли код поля портала с кодом, который заводит установка.
 *
 * Установка создаёт `UF_CRM_<N>_<суффикс>`; портал отдаёт то же поле как
 * `ufCrm<N><Суффикс>`. После снятия регистра и подчёркиваний оба пишутся
 * одинаково: `ufcrm<N><суффикс>`. Сравнивается код ЦЕЛИКОМ, а не вхождение:
 * иначе суффикс AMOUNT узнал бы себя и в `ufCrm12AmountVat`. Номер N
 * необязателен — так узнаются и старые коды без номера (`UF_CRM_AMOUNT`),
 * которые FinanceOperationService держит запасными.
 */
export function matchesInstallCode(fieldId: unknown, installCode: string | undefined): boolean {
  const suffix = normalizeCode(installCode)
  if (!suffix) {
    return false
  }

  const code = normalizeCode(fieldId)
  if (!code.startsWith('ufcrm') || !code.endsWith(suffix)) {
    return false
  }

  const middle = code.slice('ufcrm'.length, code.length - suffix.length)
  return /^\d*$/.test(middle)
}

/**
 * Типы, по которым можно угадывать поле, когда название и код не совпали.
 *
 * Только характерные: дата, флаг, пользователь, стадия, привязка к CRM. Общие
 * типы (строка, число) сюда не входят — строковых полей в смарт-процессе
 * обычно десяток, и «единственное подходящее» встречается разве что в почти
 * пустом процессе. На таком процессе правило и сработало неверно: поле «ИНН
 * клиента» досталось строке «Наш ИНН» просто потому, что было единственным
 * строковым.
 */
const TYPE_FALLBACK_TYPES = new Set([
  'date',
  'datetime',
  'boolean',
  'employee',
  'user',
  'crm_status',
  'status',
  'stage',
])

const TYPE_FALLBACK_GENERIC_TYPES = new Set(['string', 'text', 'char', 'integer', 'int', 'double', 'float', 'money'])

function allowsTypeFallback(row: MappingRow): boolean {
  const accepted = (row.acceptedTypes || []).map(normalizeFieldType)
  if (!accepted.length) {
    return false
  }

  if (accepted.some(type => TYPE_FALLBACK_GENERIC_TYPES.has(type))) {
    return false
  }

  return accepted.some(type => TYPE_FALLBACK_TYPES.has(type))
}

/**
 * Что автоподбор нашёл для незаполненных строк.
 *
 * Ничего не сохраняет и ничего не применяет: возвращает предложения, а
 * решение остаётся за человеком. Одно поле портала не предлагается дважды —
 * уже занятые id исключаются, иначе два ключа получили бы одно поле и
 * приложение начало бы писать часы поверх себя.
 *
 * Порядок правил от надёжного к рискованному: код поля целиком совпал с
 * кодом, который заводит установка (только у строк с `installCode`) ->
 * точное совпадение названия ->
 * название содержит синоним -> код поля содержит подсказку -> в
 * смарт-процессе ровно одно поле подходящего типа. Последнее правило самое
 * слабое, поэтому у него отдельный `source: 'type'` (в интерфейсе такие
 * предложения помечены «проверьте») и работает оно только для характерных
 * типов — см. allowsTypeFallback: по строке и числу не угадываем.
 */
export function suggestMappingMatches(
  rows: MappingRow[],
  spFields: SmartProcessFieldOption[],
  mapping: Record<string, string>
): MappingSuggestion[] {
  const current = normalizeMappingState(mapping)
  const used = new Set(Object.values(current).map(value => normalizeSearchText(value)))
  const suggestions: MappingSuggestion[] = []

  const fields = (spFields || [])
    .map(field => ({
      id: String(field.id || '').trim(),
      title: String(field.title || '').trim(),
      type: normalizeFieldType(field.type),
    }))
    .filter(field => field.id.length > 0)

  for (const row of rows) {
    if (String(current[row.key] || '').trim()) {
      continue
    }

    const free = fields.filter(field => !used.has(normalizeSearchText(field.id)))
    if (!free.length) {
      continue
    }

    const synonyms = row.synonyms.map(normalizeSearchText).filter(Boolean)
    const hints = row.codeHints.map(normalizeCode).filter(Boolean)
    // Для угадывания по названию и куску кода — только поля подходящего
    // типа, если строка этого требует (см. MappingRow.matchCompatibleTypesOnly).
    const guessable = row.matchCompatibleTypesOnly
      ? free.filter(field => isFieldTypeCompatible(row, field.type))
      : free

    let matched: { id: string, title: string, type: string } | undefined
    let source: MappingSuggestionSource = 'label'
    let reason = ''

    // Самое надёжное правило: код целиком совпал с тем, что заводит установка.
    // Тип здесь не проверяется намеренно — это то самое поле, и если его тип
    // на портале поменяли, человек увидит это в строке, а не потеряет поле.
    if (row.installCode) {
      matched = free.find(field => matchesInstallCode(field.id, row.installCode))
      if (matched) {
        source = 'install'
        reason = `Поле заведено установкой приложения — код совпадает точно: ${matched.id}.`
      }
    }

    if (!matched) {
      matched = guessable.find(field => synonyms.includes(normalizeSearchText(field.title)))
      if (matched) {
        reason = `Название поля совпадает: «${matched.title}».`
      }
    }

    if (!matched) {
      matched = guessable.find((field) => {
        const title = normalizeSearchText(field.title)
        return Boolean(title) && synonyms.some(synonym => title.includes(synonym))
      })
      if (matched) {
        reason = `В названии поля есть «${row.label.toLowerCase()}»: «${matched.title}».`
      }
    }

    if (!matched) {
      matched = guessable.find((field) => {
        const code = normalizeCode(field.id)
        return hints.some(hint => code.includes(hint))
      })
      if (matched) {
        source = 'code'
        reason = `Код поля похож на служебный: ${matched.id}.`
      }
    }

    if (!matched && isRequiredRow(row) && allowsTypeFallback(row)) {
      const byType = free.filter(field => isFieldTypeCompatible(row, field.type))
      if (byType.length === 1 && byType[0]) {
        matched = byType[0]
        source = 'type'
        reason = `В смарт-процессе только одно поле подходящего типа (${matched.type}) — проверьте, то ли это поле.`
      }
    }

    if (!matched) {
      continue
    }

    used.add(normalizeSearchText(matched.id))
    suggestions.push({
      key: row.key,
      label: row.label,
      fieldId: matched.id,
      fieldTitle: matched.title || matched.id,
      fieldType: matched.type,
      source,
      reason,
    })
  }

  return suggestions
}

/** Итог автоподбора одной фразой. */
export function describeSuggestions(suggestions: MappingSuggestion[], missingCount: number): string {
  if (!suggestions.length) {
    return missingCount
      ? 'Автоподбор не нашёл подходящих полей по названиям и кодам. Заполните строки вручную или создайте поля кнопкой «Создать поле».'
      : 'Подбирать нечего: все поля уже сопоставлены.'
  }

  const risky = suggestions.filter(item => item.source === 'type').length
  const base = `Найдено совпадений: ${suggestions.length}. Ничего ещё не сохранено — проверьте список и примените.`

  return risky
    ? `${base} Из них ${risky} подобрано только по типу поля — их проверьте особенно внимательно.`
    : base
}

/** Применяет выбранные предложения к сопоставлению, не трогая заполненное. */
export function applySuggestions(
  mapping: Record<string, string>,
  suggestions: MappingSuggestion[],
  acceptedKeys?: string[]
): Record<string, string> {
  const next = { ...normalizeMappingState(mapping) }
  const accepted = acceptedKeys ? new Set(acceptedKeys) : null

  for (const suggestion of suggestions) {
    if (accepted && !accepted.has(suggestion.key)) {
      continue
    }
    if (String(next[suggestion.key] || '').trim()) {
      continue
    }

    next[suggestion.key] = suggestion.fieldId
  }

  return next
}

// endregion

// region Разбор ответов сервера

export type MappingProblem = {
  id: string
  title: string
  detail: string
  fix: string
}

export type ProjectSpaReport = {
  ok: boolean
  headline: string
  problems: MappingProblem[]
  warnings: string[]
}

/**
 * Ответ /api/project-spa/validation по-человечески.
 *
 * Раньше экран печатал сырые ключи (`missing_mapping_keys.join(', ')`,
 * «ожидалось: crm_binding, фактически: string»). Человеку, который не читал
 * views.py, эти строки не говорят ни что сломано, ни что делать.
 */
export function describeProjectSpaValidation(
  payload: ProjectSpaValidationPayload | null | undefined
): ProjectSpaReport {
  if (!payload) {
    return {
      ok: false,
      headline: 'Проверка ещё не запускалась.',
      problems: [],
      warnings: [],
    }
  }

  if (!payload.is_configured) {
    return {
      ok: false,
      headline: 'Смарт-процесс проектов не выбран, проверять нечего.',
      problems: [],
      warnings: [],
    }
  }

  const problems: MappingProblem[] = []

  for (const key of payload.missing_mapping_keys || []) {
    problems.push({
      id: `missing-${key}`,
      title: `Поле «${describeMappingKey('project', key)}» не сопоставлено`,
      detail: 'Сервер считает это поле обязательным и не примет конфигурацию без него.',
      fix: 'Выберите поле в блоке «Поля карточки проекта» или создайте его кнопкой «Создать поле».',
    })
  }

  for (const row of payload.missing_fields_in_sp || []) {
    problems.push({
      id: `broken-${row.key}`,
      title: `Поле «${describeMappingKey('project', row.key)}» указывает на несуществующее поле`,
      detail: `В смарт-процессе больше нет поля ${row.mapped_field} — скорее всего, его удалили или переименовали на портале.`,
      fix: 'Выберите поле заново: список полей обновляется кнопкой «Обновить список полей».',
    })
  }

  for (const row of payload.type_mismatches || []) {
    problems.push({
      id: `type-${row.key}`,
      title: `У поля «${describeMappingKey('project', row.key)}» не тот тип`,
      detail: `Приложению нужен тип «${describeExpectedType(row.expected_type)}», а у выбранного поля ${row.mapped_field} тип «${row.actual_type || 'неизвестен'}».`,
      fix: 'Выберите другое поле подходящего типа либо создайте новое — приложение заведёт его с правильным типом.',
    })
  }

  if (payload.access_error) {
    problems.push({
      id: 'access',
      title: 'Приложение не может читать карточки проектов',
      detail: `Портал ответил: ${payload.access_error}`,
      fix: 'Проверьте, что у смарт-процесса включён доступ для приложения и что выбран существующий смарт-процесс.',
    })
  }

  if (payload.write_access_error) {
    problems.push({
      id: 'write-access',
      title: 'Приложение не может изменять карточки проектов',
      detail: `Портал ответил: ${payload.write_access_error}`,
      fix: 'Дайте приложению право на изменение элементов этого смарт-процесса, иначе синхронизация проектов ничего не запишет.',
    })
  }

  const linkage = payload.linkage_issues
  if (linkage?.missing_group_link_count) {
    problems.push({
      id: 'linkage-missing-group',
      title: `Карточек проектов без рабочей группы: ${linkage.missing_group_link_count}`,
      detail: 'У таких карточек не заполнен ID группы Битрикс24, поэтому часы к ним не привяжутся.',
      fix: 'Заполните группу в карточках проектов на портале — экран «Незаполненные проекты» показывает их списком.',
    })
  }
  if (linkage?.duplicate_group_link_count) {
    problems.push({
      id: 'linkage-duplicate-group',
      title: `Одна группа указана в нескольких карточках: ${linkage.duplicate_group_link_count}`,
      detail: 'Часы одной группы разойдутся по разным карточкам проекта, и суммы в отчётах и БДДС раздвоятся.',
      fix: 'Оставьте у группы одну карточку проекта, лишние уберите в архив.',
    })
  }
  if (linkage?.duplicate_project_item_link_count) {
    problems.push({
      id: 'linkage-duplicate-item',
      title: `Одна карточка проекта привязана к нескольким группам: ${linkage.duplicate_project_item_link_count}`,
      detail: 'Приложение не сможет однозначно определить, чьи часы относятся к этой карточке.',
      fix: 'Разведите группы по отдельным карточкам проектов на портале.',
    })
  }

  const headline = payload.is_valid
    ? problems.length
      ? 'Конфигурация принимается сервером, но в данных есть нестыковки — список ниже.'
      : 'Проверка пройдена: сопоставление полное, права у приложения есть, карточки связаны с группами.'
    : `Сервер не примет такую конфигурацию. Проблем: ${problems.length}.`

  return {
    ok: Boolean(payload.is_valid) && problems.length === 0,
    headline,
    problems,
    warnings: (payload.warnings || []).filter(Boolean),
  }
}

function describeExpectedType(expected: string): string {
  const map: Record<string, string> = {
    string: 'строка',
    integer: 'целое число',
    double: 'число с дробной частью',
    boolean: 'да/нет',
    employee: 'пользователь портала',
    crm_binding: 'привязка к элементам CRM',
    date: 'дата',
    stage: 'стадия',
    project_identifier: 'число или строка (ID группы)',
  }

  return map[normalizeFieldType(expected)] || expected
}

export type MappingErrorReport = {
  title: string
  text: string
  validation: ProjectSpaValidationPayload | null
}

type ErrorLike = {
  status?: number
  statusCode?: number
  message?: string
  data?: {
    error?: string
    validation?: unknown
    status?: string
  } | null
}

/**
 * Отказ сохранения по-человечески.
 *
 * Кодов и статусов в ответе экран больше не показывает: они ничего не
 * подсказывают. 400 с валидацией разбирается отдельно — в нём лежит готовый
 * список проблем, который умеет читать describeProjectSpaValidation.
 */
export function describeMappingSaveError(error: unknown): MappingErrorReport {
  const err = (error || {}) as ErrorLike
  const status = Number(err.status || err.statusCode || 0)
  const payload = err.data || null
  const serverText = String(payload?.error || '').trim()

  const validation = payload && typeof payload.validation === 'object' && payload.validation
    ? payload.validation as ProjectSpaValidationPayload
    : null

  if (validation) {
    return {
      title: 'Сервер отклонил сопоставление полей проектов',
      text: 'Настройки НЕ сохранены. Ниже — что именно не так; после исправления нажмите «Сохранить» снова.',
      validation,
    }
  }

  if (status === 429) {
    return {
      title: 'Слишком часто',
      text: 'Сохранение сопоставления с подключённым смарт-процессом проектов запускает синхронизацию, поэтому чаще шести раз в минуту его делать нельзя. Подождите минуту и повторите.',
      validation: null,
    }
  }

  if (status === 403) {
    return {
      title: 'Недостаточно прав',
      text: 'Настройки приложения хранятся на портале, и записать их может только администратор портала. Попросите администратора открыть этот экран.',
      validation: null,
    }
  }

  if (status === 409) {
    return {
      title: 'Вкладка работает на старой версии',
      text: 'Приложение обновилось, а эта вкладка осталась на прежней сборке. Перезагрузите её и повторите сохранение.',
      validation: null,
    }
  }

  if (status >= 500) {
    return {
      title: 'Портал или сервер приложения не ответили',
      text: 'Настройки не сохранены. Повторите через минуту; если повторяется — посмотрите «Диагностика системы» в настройках.',
      validation: null,
    }
  }

  return {
    title: 'Не удалось сохранить настройки',
    text: serverText || String(err.message || '').trim() || 'Причина неизвестна. Повторите попытку; если не помогает — обновите страницу.',
    validation: null,
  }
}

/** Итог создания смарт-процесса одной фразой. */
export function describeSmartProcessCreated(input: {
  entityTypeId?: number | string | null
  createdFieldsCount?: number | null
  warnings?: string[] | null
}): { text: string, warnings: string[] } {
  const id = String(input.entityTypeId || '').trim()
  const count = Number(input.createdFieldsCount || 0)

  return {
    text: `Смарт-процесс создан${id ? ` (ID ${id})` : ''}, в нём заведено полей: ${count}. Сопоставление заполнено автоматически — проверьте его ниже и нажмите «Сохранить».`,
    warnings: (input.warnings || []).filter(Boolean),
  }
}

// endregion

// region Предупреждение для всего приложения

export type MappingHealthLevel = 'ok' | 'warning' | 'critical'

export type MappingHealth = {
  level: MappingHealthLevel
  title: string
  text: string
  actionLabel: string
  /** Названия полей, которых не хватает; для подсказки в баннере. */
  missingLabels: string[]
}

const HEALTHY: MappingHealth = {
  level: 'ok',
  title: '',
  text: '',
  actionLabel: '',
  missingLabels: [],
}

/**
 * Настроено ли приложение — по одной уже загруженной конфигурации.
 *
 * Нужно предупреждению в шапке приложения: до него человек узнавал о
 * незаполненном сопоставлении по пустым отчётам, потому что приложение об
 * этом молчало.
 *
 * Проверяются только вещи, видимые из конфигурации: выбран ли смарт-процесс
 * и заполнены ли обязательные ключи.
 *
 * «Доходы-расходы» здесь НЕ проверяются намеренно: они нужны только
 * операциям БДДС, и баннер на каждом экране у тех, кто пользуется лишь
 * часами и отчётами, был бы ложной тревогой. Там, где операции важны, их
 * состояние показывает resolveFinanceMappingNotice. Права приложения и связность карточек
 * тут не проверяются — это отдельный живой запрос, ради баннера его делать
 * незачем.
 */
export function resolveMappingHealth(config: AppConfigurationPayload | null | undefined): MappingHealth {
  if (!config) {
    return HEALTHY
  }

  const timesheetSpId = Number(config.sp_entity_type_id || 0)
  const timesheetMapping = normalizeMappingState(config.fields_mapping || {})

  if (!timesheetSpId || Object.keys(timesheetMapping).length === 0) {
    return {
      level: 'critical',
      title: 'Приложение не настроено',
      text: 'Поля не сопоставлены со смарт-процессом, поэтому часы не записываются, а отчёты, счета и БДДС остаются пустыми.',
      actionLabel: 'Настроить сопоставление',
      missingLabels: [],
    }
  }

  const missingCritical = TIMESHEET_MAPPING_ROWS
    .filter(row => row.importance === 'critical' && !String(timesheetMapping[row.key] || '').trim())

  if (missingCritical.length) {
    return {
      level: 'critical',
      title: 'Сопоставление полей неполное',
      text: 'Без этих полей приложение не может ни записать, ни прочитать часы.',
      actionLabel: 'Досопоставить поля',
      missingLabels: missingCritical.map(row => row.label),
    }
  }

  const missingReports = TIMESHEET_MAPPING_ROWS
    .filter(row => row.importance === 'reports' && !String(timesheetMapping[row.key] || '').trim())

  const projectSpId = Number(config.project_sp_entity_type_id || 0)
  const projectMapping = normalizeProjectMappingState(config)
  const missingProject = projectSpId
    ? PROJECT_MAPPING_ROWS.filter(row => !String(projectMapping[row.key] || '').trim())
    : []

  if (!projectSpId) {
    return {
      level: 'warning',
      title: 'Проекты не подключены',
      text: 'Смарт-процесс проектов не выбран: доска проектов, БДДС и счета не получат бюджет часов, ставку и куратора.',
      actionLabel: 'Подключить проекты',
      missingLabels: missingReports.map(row => row.label),
    }
  }

  if (missingReports.length || missingProject.length) {
    return {
      level: 'warning',
      title: 'Часть полей не сопоставлена',
      text: 'Учёт часов работает, но отчёты и документы по этим полям будут неполными.',
      actionLabel: 'Проверить сопоставление',
      missingLabels: [...missingReports, ...missingProject].map(row => row.label),
    }
  }

  return HEALTHY
}

export type FinanceMappingNotice = {
  title: string
  text: string
  actionLabel: string
  /** Ссылка сразу на шаг «Доходы-расходы» экрана сопоставления. */
  to: string
  missingLabels: string[]
}

/**
 * Мягкое напоминание про «Доходы-расходы» — только там, где это важно.
 *
 * Показывается, лишь когда у портала подключён «БДДС по проектам»: без
 * подписки операций всё равно нет, и напоминать не о чем. Не баннер на
 * всё приложение, а строка на карточке настроек БДДС и на шаге экрана
 * сопоставления.
 */
export function resolveFinanceMappingNotice(
  config: AppConfigurationPayload | null | undefined,
  bddsEnabled: boolean
): FinanceMappingNotice | null {
  if (!config || !bddsEnabled) {
    return null
  }

  const to = buildMappingStepLink('finance')
  const entityTypeId = Number(config.finance_sp_entity_type_id || 0)

  if (!entityTypeId) {
    return {
      title: 'Операции БДДС не подключены',
      text: 'Смарт-процесс «Доходы-расходы» не выбран: план и факт по часам считаются, а поступления и внешние платежи не видны и заводить их некуда.',
      actionLabel: 'Настроить «Доходы-расходы»',
      to,
      missingLabels: [],
    }
  }

  const mapping = normalizeMappingState(config.finance_fields_mapping || {})
  const missing = FINANCE_MAPPING_ROWS
    .filter(row => (FINANCE_SERVER_REQUIRED_KEYS as readonly string[]).includes(row.key))
    .filter(row => !String(mapping[row.key] || '').trim())

  if (missing.length) {
    return {
      title: 'Сопоставление «Доходов-расходов» неполное',
      text: 'Пока эти поля не сопоставлены, экран операций пишет «не настроен», а добавить операцию нельзя.',
      actionLabel: 'Досопоставить поля',
      to,
      missingLabels: missing.map(row => row.label),
    }
  }

  return null
}

// endregion
