<script setup lang="ts">
/**
 * Сопоставление полей приложения с полями смарт-процессов портала.
 *
 * Это самый важный экран приложения: пока сопоставление не заполнено, не
 * работает ничего — ни запись часов во вкладке задачи, ни отчёты, ни счета,
 * ни БДДС. До разбора экран был устроен так, что провести человека с нуля до
 * рабочего состояния не мог:
 *
 * - не было видно, что уже сделано и что осталось. Две плоские таблицы на 15
 *   и 12 строк, у каждой строки только тип поля;
 * - не было сказано, ЗАЧЕМ поле и что сломается без него. Поэтому оставить
 *   строку пустой ничего не стоило, а узнавал человек об этом по пустому
 *   отчёту через неделю;
 * - «Создать поле» было пунктом ВНУТРИ выпадающего списка, то есть выбор из
 *   списка молча выполнял запись на портал;
 * - поля неподходящего типа из списка просто исчезали, и он выглядел пустым;
 * - ошибки печатались кодами: «missing_mapping_keys: title, stage_id»,
 *   «ожидалось: crm_binding, фактически: string»;
 * - сохранение после успеха уводило на /settings, то есть результат своей
 *   работы человек не видел;
 * - и главное: сервер отклоняет сохранение с неполным сопоставлением
 *   проектного смарт-процесса (400 «Конфигурация Project SPA невалидна»),
 *   НЕ сохраняя при этом ничего. Экран об этом не предупреждал, и попытка
 *   «выберу процесс, поля заполню потом» стоила всей несохранённой работы.
 *
 * Как устроено теперь: экран идёт шагами сверху вниз (полоса прогресса ведёт
 * к нужному блоку), у каждого поля написано последствие, автоподбор сначала
 * показывает найденное и только потом применяется, а перед сохранением видно,
 * ЧТО именно сохранится — planMappingSave решает это заранее и не даёт
 * упереться в 400.
 *
 * Шаг 6 «Доходы-расходы» — необязательный: смарт-процесс нужен только
 * операциям «БДДС по проектам». Он не бывает «сейчас здесь», не входит в
 * счёт шагов и не поднимает баннер в шапке приложения. Сохраняется и общей
 * кнопкой, и своей: своя шлёт конфигурацию целиком с признаком
 * scope=finance, и сервер не запускает для неё проверку и синхронизацию
 * проектов (FINANCE_CONFIG_SAVE_SCOPE). Экраны БДДС ведут сюда ссылкой
 * `?step=finance` — после загрузки экран сам прокручивается к шагу.
 *
 * Вся логика — app/utils/fieldMapping.ts, под тестами (node:test не резолвит
 * `.vue`, поэтому оставленное в компоненте ревью проверить не может).
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import MappingFieldsCard from '~/components/settings/MappingFieldsCard.vue'
import {
  FINANCE_APP_SMART_PROCESS_TITLE,
  FINANCE_CONFIG_SAVE_SCOPE,
  FINANCE_MAPPING_ROWS,
  MAPPING_STEP_QUERY_KEY,
  PROJECT_MAPPING_ROWS,
  TIMESHEET_MAPPING_ROWS,
  applyFinanceMappingToConfig,
  applySuggestions,
  buildMappingSteps,
  findFinanceAppSmartProcess,
  hasUnsavedMappingChanges,
  isFinanceMappingChanged,
  isStaleSpFieldsResponse,
  planFinanceMappingSave,
  resolveFinanceMappingNotice,
  resolveMappingStepTarget,
  describeMappingSaveError,
  describeProjectSpaValidation,
  describeSmartProcessCreated,
  describeSuggestions,
  mergeCreatedFieldMapping,
  normalizeMappingState,
  normalizeProjectMappingState,
  planMappingSave,
  resolveMappingBlockStatus,
  resolveMappingOverall,
  serializeProjectMappingState,
  suggestMappingMatches,
  type MappingBlockId,
  type MappingSuggestion,
} from '~/utils/fieldMapping'
import type {
  AppConfigurationPayload,
  ProjectSpaValidationPayload,
  SmartProcessFieldOption,
  SmartProcessOption,
} from '~/types/config'

const { locales: localesI18n, setLocale } = useI18n()
const router = useRouter()
const route = useRoute()
const apiStore = useApiStore()
const { applyConfig: applyMappingHealthConfig } = useMappingHealth()
const { access: bddsAccess } = useBddsFeature()

useHead({
  title: 'Сопоставление полей'
})

const { initApp, processErrorGlobal } = useAppInit('MappingPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

// region Состояние

const isLoading = ref(false)
const isInit = ref(false)
const isSaving = ref(false)
const isCreatingSP = ref(false)
const isLoadingSpFields = ref(false)
const isLoadingProjectFields = ref(false)
const isValidating = ref(false)
const isSuggestingTimesheet = ref(false)
const isSuggestingProject = ref(false)
const isLoadingFinanceFields = ref(false)
const isSuggestingFinance = ref(false)
const isSavingFinance = ref(false)
const creatingKey = ref<string | null>(null)

const smartProcesses = ref<SmartProcessOption[]>([])
const config = ref<AppConfigurationPayload>({})

/**
 * Конфигурация в том виде, в каком она лежит на СЕРВЕРЕ.
 *
 * `config` выше — черновик: в него пишет поле ставки и из него собирается
 * общее сохранение. Отдельное сохранение «Доходов-расходов» обязано
 * отправить серверную конфигурацию, а не черновик: иначе своя кнопка шага
 * молча сохранила бы и чужие несохранённые правки, а сервер, увидев
 * изменённую проектную часть, пошёл бы проверять проекты (и мог ответить 400).
 */
const savedConfig = ref<AppConfigurationPayload>({})

/**
 * Что лежит на СЕРВЕРЕ, а не в полях экрана.
 *
 * Нужно плану сохранения: «процесс выбран в черновике» и «процесс уже
 * подключён на портале» — два разных случая с разными последствиями (см.
 * planMappingSave).
 */
const savedProjectSpId = ref(0)

const selectedSpId = ref<number | null>(null)
const selectedProjectSpId = ref<number | null>(null)
const spFields = ref<SmartProcessFieldOption[]>([])
const projectSpFields = ref<SmartProcessFieldOption[]>([])
const mapping = ref<Record<string, string>>({})
const projectMapping = ref<Record<string, string>>({})
const selectedFinanceSpId = ref<number | null>(null)
const financeSpFields = ref<SmartProcessFieldOption[]>([])
const financeMapping = ref<Record<string, string>>({})

const validation = ref<ProjectSpaValidationPayload | null>(null)

const timesheetSuggestions = ref<MappingSuggestion[] | null>(null)
const projectSuggestions = ref<MappingSuggestion[] | null>(null)
const timesheetSuggestionsNote = ref('')
const projectSuggestionsNote = ref('')
const financeSuggestions = ref<MappingSuggestion[] | null>(null)
const financeSuggestionsNote = ref('')

/** Шаг, на который привела ссылка с другого экрана (`?step=`): подсвечиваем. */
const targetStep = ref<MappingBlockId | ''>('')

/** Успех или отказ последнего действия. Живёт до следующего действия. */
const statusMessage = ref<{ type: 'success' | 'error' | 'info', text: string } | null>(null)

/**
 * Сводка отказа сохранения.
 *
 * Отдельно от statusMessage: у неё есть список полей со ссылками и она
 * получает фокус — по гайдлайну про error summary, которую надо находить и
 * клавиатурой.
 */
const saveReport = ref<{
  title: string
  text: string
  blockers: Array<{ key: string, label: string, reason: string, block: MappingBlockId }>
  /** Баг 6: конфликт ревизии — рядом с текстом показывается кнопка «Обновить». */
  conflict?: boolean
} | null>(null)
const saveReportRef = ref<HTMLElement | null>(null)
const statusRef = ref<HTMLElement | null>(null)

/** Поле, к которому только что перешли из сводки: подсвечиваем, чтобы не терялось. */
const highlightKey = ref('')

// endregion

// region Производные состояния

const timesheetStatus = computed(() => resolveMappingBlockStatus({
  block: 'timesheet',
  entityTypeId: selectedSpId.value,
  spFields: spFields.value,
  mapping: mapping.value,
}))

const projectStatus = computed(() => resolveMappingBlockStatus({
  block: 'project',
  entityTypeId: selectedProjectSpId.value,
  spFields: projectSpFields.value,
  mapping: projectMapping.value,
}))

const financeStatus = computed(() => resolveMappingBlockStatus({
  block: 'finance',
  entityTypeId: selectedFinanceSpId.value,
  spFields: financeSpFields.value,
  mapping: financeMapping.value,
}))

const steps = computed(() => buildMappingSteps({
  timesheet: timesheetStatus.value,
  project: projectStatus.value,
  validation: validation.value,
  finance: financeStatus.value,
  financeNeeded: bddsAccess.value.enabled,
}))

const overall = computed(() => resolveMappingOverall(steps.value, {
  timesheet: timesheetStatus.value,
  project: projectStatus.value,
}))

const savePlan = computed(() => planMappingSave({
  selectedProjectSpId: selectedProjectSpId.value,
  savedProjectSpId: savedProjectSpId.value,
  projectStatus: projectStatus.value,
}))

const financePlan = computed(() => planFinanceMappingSave({
  selectedFinanceSpId: selectedFinanceSpId.value,
  savedFinanceSpId: savedConfig.value.finance_sp_entity_type_id,
  financeStatus: financeStatus.value,
  mapping: financeMapping.value,
}))

const financeChanged = computed(() => isFinanceMappingChanged(savedConfig.value, {
  entityTypeId: selectedFinanceSpId.value,
  mapping: financeMapping.value,
}))

/**
 * Несохранённая правка хоть в одном из трёх блоков (Баг 7).
 *
 * До этой правки черновик отслеживался только у «Доходов-расходов»
 * (financeChanged выше) — уход с экрана кнопкой «К настройкам» терял
 * правки списаний и проектов молча, без единого предупреждения.
 */
const hasUnsavedChanges = computed(() => hasUnsavedMappingChanges({
  saved: savedConfig.value,
  timesheet: { entityTypeId: selectedSpId.value, mapping: mapping.value },
  project: { entityTypeId: selectedProjectSpId.value, mapping: projectMapping.value },
  finance: { entityTypeId: selectedFinanceSpId.value, mapping: financeMapping.value },
}))

/** Готовый процесс, который заводит установка приложения. */
const financeAppProcess = computed(() => findFinanceAppSmartProcess(smartProcesses.value))

/**
 * Напоминание про БДДС — только при подключённой подписке и только по
 * СОХРАНЁННОЙ конфигурации: пока человек заполняет шаг, текст «не
 * подключены» над его же заполненным черновиком только путал бы.
 */
const financeNotice = computed(() => resolveFinanceMappingNotice(savedConfig.value, bddsAccess.value.enabled))

const validationReport = computed(() => describeProjectSpaValidation(validation.value))

const saveButtonLabel = computed(() => (
  savePlan.value.kind === 'timesheet-only' ? 'Сохранить сопоставление списаний' : 'Сохранить'
))

const overallToneClass = computed(() => {
  switch (overall.value.state) {
    case 'ready':
      return 'ms-note ms-note-success'
    case 'ready-with-gaps':
      return 'ms-note ms-note-info'
    case 'not-started':
      return 'ms-note ms-note-danger'
    default:
      return 'ms-panel-warning'
  }
})

const smartProcessOptions = computed(() => smartProcesses.value.map(item => ({
  value: item.entityTypeId,
  label: `${item.title} (ID ${item.entityTypeId})`,
})))

// endregion

// region Загрузка

function showStatus(type: 'success' | 'error' | 'info', text: string) {
  statusMessage.value = { type, text }
}

/**
 * Гонка ответов (Баг 8): человек может сменить смарт-процесс списаний ещё
 * раз до того, как пришёл ответ на предыдущий выбор. Более старый запрос,
 * придя ПОСЛЕ нового, не должен подменить список полей — isStaleSpFieldsResponse
 * сравнивает entityTypeId, с которым запрос стартовал, с тем, что выбрано
 * СЕЙЧАС (selectedSpId.value в момент ответа).
 */
async function loadSpFields(entityTypeId: number) {
  isLoadingSpFields.value = true
  try {
    const res = await apiStore.getSpFields(entityTypeId)
    if (isStaleSpFieldsResponse(entityTypeId, selectedSpId.value)) {
      return
    }
    spFields.value = res.fields || []
  } catch (e) {
    if (isStaleSpFieldsResponse(entityTypeId, selectedSpId.value)) {
      return
    }
    spFields.value = []
    showStatus('error', `Не удалось получить поля смарт-процесса списаний. ${describeMappingSaveError(e).text}`)
  } finally {
    isLoadingSpFields.value = false
  }
}

async function loadProjectSpFields(entityTypeId: number) {
  isLoadingProjectFields.value = true
  try {
    const res = await apiStore.getSpFields(entityTypeId)
    if (isStaleSpFieldsResponse(entityTypeId, selectedProjectSpId.value)) {
      return
    }
    projectSpFields.value = res.fields || []
  } catch (e) {
    if (isStaleSpFieldsResponse(entityTypeId, selectedProjectSpId.value)) {
      return
    }
    projectSpFields.value = []
    showStatus('error', `Не удалось получить поля смарт-процесса проектов. ${describeMappingSaveError(e).text}`)
  } finally {
    isLoadingProjectFields.value = false
  }
}

async function loadFinanceSpFields(entityTypeId: number) {
  isLoadingFinanceFields.value = true
  try {
    const res = await apiStore.getSpFields(entityTypeId)
    if (isStaleSpFieldsResponse(entityTypeId, selectedFinanceSpId.value)) {
      return
    }
    financeSpFields.value = res.fields || []
  } catch (e) {
    if (isStaleSpFieldsResponse(entityTypeId, selectedFinanceSpId.value)) {
      return
    }
    financeSpFields.value = []
    showStatus('error', `Не удалось получить поля смарт-процесса «Доходы-расходы». ${describeMappingSaveError(e).text}`)
  } finally {
    isLoadingFinanceFields.value = false
  }
}

async function runValidation(silent = false) {
  if (!selectedProjectSpId.value) {
    validation.value = null
    return
  }

  isValidating.value = true
  try {
    validation.value = await apiStore.getProjectSpaValidation()
    if (!silent) {
      showStatus(
        validationReport.value.ok ? 'success' : 'info',
        validationReport.value.headline
      )
    }
  } catch (e) {
    validation.value = null
    if (!silent) {
      showStatus('error', `Проверка не выполнена. ${describeMappingSaveError(e).text}`)
    }
  } finally {
    isValidating.value = false
  }
}

async function loadData() {
  isLoading.value = true
  try {
    const [cfgRes, spRes] = await Promise.allSettled([
      apiStore.getConfiguration(),
      apiStore.getSmartProcesses(),
    ])

    if (cfgRes.status !== 'fulfilled') {
      throw cfgRes.reason
    }

    const cfg = cfgRes.value
    config.value = cfg
    savedConfig.value = { ...cfg }
    applyMappingHealthConfig(cfg)
    smartProcesses.value = spRes.status === 'fulfilled' ? (spRes.value.types || []) : []

    if (spRes.status !== 'fulfilled') {
      showStatus(
        'error',
        'Список смарт-процессов портала не загрузился, поэтому выбрать процесс сейчас нельзя. Сохранённые настройки показаны и не пострадали — обновите страницу.'
      )
    }

    savedProjectSpId.value = Number(cfg.project_sp_entity_type_id || 0)

    if (cfg.sp_entity_type_id) {
      selectedSpId.value = Number(cfg.sp_entity_type_id)
      mapping.value = normalizeMappingState(cfg.fields_mapping || {})
      await loadSpFields(Number(cfg.sp_entity_type_id))
    }

    /**
     * Черновик сопоставления проектов читается ВСЕГДА, даже когда сам
     * смарт-процесс на сервере ещё не выбран.
     *
     * Так работает частичное сохранение (planMappingSave, ветка
     * 'timesheet-only'): выбор процесса уходит нулём, а сопоставление
     * сохраняется как черновик. Если читать его только при заданном
     * project_sp_entity_type_id, обещание «работа не потеряется» ломалось бы
     * на первой же перезагрузке экрана.
     */
    projectMapping.value = normalizeProjectMappingState(cfg)

    if (cfg.project_sp_entity_type_id) {
      selectedProjectSpId.value = Number(cfg.project_sp_entity_type_id)
      await loadProjectSpFields(Number(cfg.project_sp_entity_type_id))
      await runValidation(true)
    }

    financeMapping.value = normalizeMappingState(cfg.finance_fields_mapping || {})
    if (Number(cfg.finance_sp_entity_type_id || 0) > 0) {
      selectedFinanceSpId.value = Number(cfg.finance_sp_entity_type_id)
      await loadFinanceSpFields(Number(cfg.finance_sp_entity_type_id))
    }
  } catch (e) {
    processErrorGlobal(e)
  } finally {
    isLoading.value = false
    isInit.value = true
  }
}

/**
 * Прокрутка к шагу, на который вела ссылка (`?step=finance`).
 *
 * Только после загрузки: до неё на странице стоит заглушка «Читаем
 * настройки», и карточки шага, к которой надо прокрутить, ещё нет. Фокус —
 * на выпадающий список процесса, с которого шаг начинается.
 */
async function revealStepFromRoute() {
  const target = resolveMappingStepTarget(route.query[MAPPING_STEP_QUERY_KEY])
  if (!target) {
    return
  }

  targetStep.value = target.block
  await nextTick()

  if (typeof document === 'undefined') {
    return
  }

  document.getElementById(target.anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const select = document.getElementById(target.focusId)
  if (select instanceof HTMLSelectElement) {
    select.focus({ preventScroll: true })
  }
}

// endregion

// region Действия

/**
 * Смена смарт-процесса.
 *
 * Поля подгружаются сразу: раньше это требовало отдельной кнопки
 * «Подгрузить поля», и до нажатия выпадающие списки сопоставления стояли
 * пустыми без объяснения. Кнопка «Обновить список полей» осталась — она
 * нужна, когда поля правили на портале, не закрывая экран.
 *
 * Прежнее сопоставление при смене процесса НЕ стирается: коды полей от
 * другого процесса подсветятся как ненайденные («Поля X больше нет»), и это
 * честнее, чем молча обнулить работу из-за случайного выбора в списке.
 */
async function onProcessChange(block: MappingBlockId, event: Event) {
  const select = event.target as HTMLSelectElement | null
  const raw = select?.value || ''
  const nextId = raw ? Number(raw) : null

  statusMessage.value = null
  saveReport.value = null

  if (block === 'timesheet') {
    selectedSpId.value = nextId
    timesheetSuggestions.value = null
    spFields.value = []
    if (nextId) {
      await loadSpFields(nextId)
    }
    return
  }

  if (block === 'finance') {
    await selectFinanceProcess(nextId)
    return
  }

  selectedProjectSpId.value = nextId
  projectSuggestions.value = null
  projectSpFields.value = []
  validation.value = null

  if (nextId) {
    await loadProjectSpFields(nextId)
  }
}

async function selectFinanceProcess(nextId: number | null) {
  selectedFinanceSpId.value = nextId
  financeSuggestions.value = null
  financeSpFields.value = []
  if (nextId) {
    await loadFinanceSpFields(nextId)
  }
}

/**
 * «Выбрать «Доходы-расходы (App)»» — готовый процесс установки.
 *
 * Сразу после выбора запускаем автоподбор: поля этого процесса заведены
 * установкой и находятся точно по коду. Найденное только ПОКАЗЫВАЕТСЯ —
 * применяет его человек, как и в остальных шагах.
 */
async function useFinanceAppProcess() {
  const app = financeAppProcess.value
  if (!app) {
    return
  }

  statusMessage.value = null
  saveReport.value = null
  await selectFinanceProcess(Number(app.entityTypeId))

  if (financeSpFields.value.length) {
    handleSuggest('finance')
  }
}

function mappingRef(block: MappingBlockId) {
  switch (block) {
    case 'timesheet':
      return mapping
    case 'finance':
      return financeMapping
    default:
      return projectMapping
  }
}

function onMappingChange(block: MappingBlockId, key: string, value: string) {
  const target = mappingRef(block)
  const next = { ...target.value }

  if (value) {
    next[key] = value
  } else {
    Reflect.deleteProperty(next, key)
  }

  target.value = next
  highlightKey.value = ''
  saveReport.value = null
}

async function handleCreateSmartProcess() {
  isCreatingSP.value = true
  statusMessage.value = null
  saveReport.value = null

  try {
    const result = await apiStore.createSmartProcess()
    const newConfig = result.config
    config.value = { ...config.value, ...newConfig }
    savedConfig.value = { ...newConfig }
    selectedSpId.value = Number(newConfig.sp_entity_type_id)
    mapping.value = normalizeMappingState(newConfig.fields_mapping || {})

    if (newConfig.sp_entity_type_id) {
      await loadSpFields(Number(newConfig.sp_entity_type_id))
    }

    try {
      const spRes = await apiStore.getSmartProcesses()
      smartProcesses.value = spRes.types || []
    } catch {
      // Список процессов — только для выпадающего списка. Созданный процесс
      // уже выбран, и падать из-за неудачного обновления списка незачем.
    }

    const described = describeSmartProcessCreated({
      entityTypeId: newConfig.sp_entity_type_id,
      createdFieldsCount: result.created_fields_count,
      warnings: result.field_warnings,
    })

    showStatus(
      'success',
      described.warnings.length
        ? `${described.text} Портал предупредил: ${described.warnings.join('; ')}`
        : described.text
    )
  } catch (e) {
    const report = describeMappingSaveError(e)
    showStatus('error', `${report.title}. ${report.text}`)
  } finally {
    isCreatingSP.value = false
  }
}

async function handleCreateField(block: MappingBlockId, fieldKey: string, fieldLabel: string) {
  const entityTypeId = Number(
    (block === 'timesheet'
      ? selectedSpId.value
      : block === 'finance' ? selectedFinanceSpId.value : selectedProjectSpId.value) || 0
  )

  if (!entityTypeId) {
    showStatus('error', 'Сначала выберите смарт-процесс — создавать поле пока негде.')
    return
  }

  creatingKey.value = `${block}:${fieldKey}`
  statusMessage.value = null
  saveReport.value = null

  try {
    const result = await apiStore.createMappedField(entityTypeId, fieldKey, block)
    config.value = { ...config.value, ...result.config }
    // Сервер записал конфигурацию сам (create_single_field): это и есть
    // новое серверное состояние, от него считается отдельное сохранение.
    savedConfig.value = { ...result.config }

    if (block === 'finance') {
      financeMapping.value = mergeCreatedFieldMapping(
        financeMapping.value,
        result.config.finance_fields_mapping,
        fieldKey,
        result.field_id
      )
      config.value.finance_fields_mapping = { ...financeMapping.value }
      config.value.finance_sp_entity_type_id = entityTypeId
      await loadFinanceSpFields(entityTypeId)
    } else if (block === 'timesheet') {
      mapping.value = mergeCreatedFieldMapping(
        mapping.value,
        result.config.fields_mapping,
        fieldKey,
        result.field_id
      )
      config.value.fields_mapping = { ...mapping.value }
      await loadSpFields(entityTypeId)
    } else {
      projectMapping.value = mergeCreatedFieldMapping(
        projectMapping.value,
        result.config.project_fields_mapping,
        fieldKey,
        result.field_id
      )
      config.value.project_fields_mapping = serializeProjectMappingState(projectMapping.value)
      await loadProjectSpFields(entityTypeId)
      await runValidation(true)
    }

    const warnings = result.field_warnings?.length
      ? ` Портал предупредил: ${result.field_warnings.join('; ')}`
      : ''
    showStatus('success', `Поле «${fieldLabel}» создано на портале и привязано к этой строке.${warnings}`)
  } catch (e) {
    const report = describeMappingSaveError(e)
    showStatus('error', `Поле «${fieldLabel}» создать не удалось. ${report.text}`)
  } finally {
    creatingKey.value = null
  }
}

/** Всё, что нужно автоподбору одного блока. */
function suggestionContext(block: MappingBlockId) {
  switch (block) {
    case 'timesheet':
      return {
        rows: TIMESHEET_MAPPING_ROWS,
        fields: spFields,
        mapping,
        status: timesheetStatus,
        suggestions: timesheetSuggestions,
        note: timesheetSuggestionsNote,
        busy: isSuggestingTimesheet,
      }
    case 'finance':
      return {
        rows: FINANCE_MAPPING_ROWS,
        fields: financeSpFields,
        mapping: financeMapping,
        status: financeStatus,
        suggestions: financeSuggestions,
        note: financeSuggestionsNote,
        busy: isSuggestingFinance,
      }
    default:
      return {
        rows: PROJECT_MAPPING_ROWS,
        fields: projectSpFields,
        mapping: projectMapping,
        status: projectStatus,
        suggestions: projectSuggestions,
        note: projectSuggestionsNote,
        busy: isSuggestingProject,
      }
  }
}

function handleSuggest(block: MappingBlockId) {
  const ctx = suggestionContext(block)
  ctx.busy.value = true
  statusMessage.value = null

  try {
    const found = suggestMappingMatches(ctx.rows, ctx.fields.value, ctx.mapping.value)
    const missingCount = ctx.status.value.totalCount - ctx.status.value.mappedCount

    ctx.suggestions.value = found
    ctx.note.value = describeSuggestions(found, missingCount)
  } finally {
    ctx.busy.value = false
  }
}

function handleApplySuggestions(block: MappingBlockId) {
  const ctx = suggestionContext(block)
  const found = ctx.suggestions.value || []

  ctx.mapping.value = applySuggestions(ctx.mapping.value, found)
  ctx.suggestions.value = null

  const saveHint = block === 'finance'
    ? 'нажмите «Сохранить «Доходы-расходы»» в этом шаге или общее «Сохранить»'
    : 'нажмите «Сохранить»'
  showStatus('info', `Применено сопоставлений: ${found.length}. Изменения пока не сохранены — ${saveHint}.`)
}

function dismissSuggestions(block: MappingBlockId) {
  suggestionContext(block).suggestions.value = null
}

/** Переход из сводки ошибок к полю: подсветка плюс фокус на выпадающем списке. */
async function goToField(block: MappingBlockId, key: string) {
  highlightKey.value = `${block}:${key}`
  await nextTick()

  if (typeof document === 'undefined') {
    return
  }

  const row = document.getElementById(`field-${block}-${key}`)
  row?.scrollIntoView({ behavior: 'smooth', block: 'center' })

  const select = document.getElementById(`mapping-${block}-${key}`)
  if (select instanceof HTMLSelectElement) {
    select.focus()
  }
}

async function focusSaveReport() {
  await nextTick()
  saveReportRef.value?.focus()
}

/**
 * Показать результат сохранения.
 *
 * Кнопка «Сохранить» есть и внизу страницы, а сообщение о результате стоит
 * наверху — без прокрутки человек нажимал бы сохранение и не видел, чем оно
 * закончилось. Прежний экран решал это иначе: после успеха уводил на
 * /settings, то есть результат своей работы человек не видел вообще.
 */
async function revealStatus() {
  await nextTick()
  statusRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

/**
 * Сохранение.
 *
 * План считает planMappingSave — он же и объясняет заранее, что уйдёт на
 * сервер. Ветка 'blocked' до сервера не доходит: там гарантированный 400, и
 * показать список полей полезнее, чем отправить запрос за отказом.
 */
async function handleSave() {
  const plan = savePlan.value
  statusMessage.value = null

  if (plan.kind === 'blocked') {
    saveReport.value = {
      title: plan.title,
      text: plan.note,
      blockers: plan.blockers.map(item => ({ ...item, block: 'project' as MappingBlockId })),
    }
    await focusSaveReport()
    return
  }

  saveReport.value = null
  isSaving.value = true

  try {
    const serializedProjectMapping = serializeProjectMappingState(projectMapping.value)
    const baseConfig: AppConfigurationPayload = {
      ...config.value,
      sp_entity_type_id: selectedSpId.value,
      fields_mapping: mapping.value,
      project_sp_entity_type_id: plan.projectSpIdToSend,
      project_fields_mapping: serializedProjectMapping,
      stage_id: serializedProjectMapping.stage_id || null,
      stage: serializedProjectMapping.stage || null,
      project_stage: serializedProjectMapping.stage || null,
      manual_stage: serializedProjectMapping.manual_stage || null,
      effective_stage: serializedProjectMapping.effective_stage || null,
      is_configured: true,
    }
    // «Доходы-расходы» уходят той же кнопкой: общее «Сохранить» сохраняет
    // всё, что видно на экране. Проверки на сервере у них нет, поэтому
    // неполный черновик общее сохранение не блокирует.
    const newConfig = applyFinanceMappingToConfig(baseConfig, {
      entityTypeId: selectedFinanceSpId.value,
      mapping: financeMapping.value,
    })

    const saveResult = await apiStore.saveConfiguration(newConfig, {
      baseRevision: savedConfig.value.config_revision,
    })

    // Ревизия из ОТВЕТА, а не из newConfig: сервер продвинул её вперёд при
    // записи (см. save_configuration_sync), и следующее сохранение обязано
    // отправить именно её — иначе своё же успешное сохранение тут же
    // выглядело бы устаревшим.
    const savedWithRevision = { ...newConfig, config_revision: saveResult?.config_revision ?? newConfig.config_revision }
    config.value = savedWithRevision
    savedConfig.value = { ...savedWithRevision }
    savedProjectSpId.value = Number(plan.projectSpIdToSend || 0)
    applyMappingHealthConfig(newConfig)

    const parts: string[] = []
    parts.push(plan.kind === 'timesheet-only'
      ? 'Сопоставление списаний сохранено. Смарт-процесс проектов останется неподключённым, пока его сопоставление не заполнено целиком.'
      : 'Настройки сохранены.')

    const syncInfo = saveResult?.project_sync as Record<string, unknown> | undefined
    if (syncInfo && typeof syncInfo === 'object') {
      const created = Number(syncInfo.created || 0)
      const updated = Number(syncInfo.updated || 0)
      const warning = String(syncInfo.warning || '').trim()

      parts.push(warning
        ? `Синхронизация проектов: ${warning}`
        : `Карточек проектов создано ${created}, обновлено ${updated}.`)
    }

    const backfillInfo = saveResult?.timesheet_backfill as Record<string, unknown> | undefined
    if (backfillInfo && typeof backfillInfo === 'object') {
      const backfillUpdated = Number(backfillInfo.updated || 0)
      const unresolved = Number(backfillInfo.unresolved || 0)

      if (backfillUpdated || unresolved) {
        parts.push(unresolved
          ? `У уже внесённых часов дописаны связи с проектами: ${backfillUpdated}; без связки осталось ${unresolved} — их проекты не нашлись на портале.`
          : `У уже внесённых часов дописаны связи с проектами: ${backfillUpdated}.`)
      }
    }

    showStatus('success', parts.join(' '))
    await revealStatus()

    if (savedProjectSpId.value) {
      await runValidation(true)
    }
  } catch (e) {
    await reportSaveError(e)
  } finally {
    isSaving.value = false
  }
}

async function reportSaveError(e: unknown) {
  const report = describeMappingSaveError(e)

  if (report.validation) {
    validation.value = report.validation
    const described = describeProjectSpaValidation(report.validation)
    saveReport.value = {
      title: report.title,
      text: report.text,
      blockers: described.problems.map(problem => ({
        key: problem.id,
        label: problem.title,
        reason: `${problem.detail} ${problem.fix}`,
        block: 'project' as MappingBlockId,
      })),
    }
  } else {
    saveReport.value = { title: report.title, text: report.text, blockers: [], conflict: report.conflict }
  }

  await focusSaveReport()
}

/**
 * «Обновить» на конфликте ревизии (Баг 6).
 *
 * Перечитывает конфигурацию с сервера. Несохранённый черновик при этом
 * действительно пропадает — но не молча: до этой кнопки человек видит
 * сообщение и решает сам, а не теряет правки на пустом месте, как было бы
 * при автоматическом обновлении сразу на 409.
 */
async function reloadAfterConflict() {
  saveReport.value = null
  await loadData()
}

/**
 * Сохранение одного шага «Доходы-расходы».
 *
 * Тело — СЕРВЕРНАЯ конфигурация целиком (savedConfig) с подменёнными двумя
 * финансовыми ключами: сервер хранит настройки одной строкой, и прислать
 * только финансовые ключи значило бы затереть всё остальное. Черновики
 * других шагов сюда не попадают — их сохраняет общая кнопка.
 *
 * scope=finance просит сервер не запускать проверку и синхронизацию
 * проектов. Сервер соглашается, только если проектная часть совпадает с
 * сохранённой, — а она совпадает, потому что взята из savedConfig.
 */
async function handleSaveFinance() {
  const plan = financePlan.value
  statusMessage.value = null
  saveReport.value = null

  if (!financeChanged.value) {
    showStatus('info', 'В шаге «Доходы-расходы» нет несохранённых изменений.')
    await revealStatus()
    return
  }

  isSavingFinance.value = true

  try {
    const next = applyFinanceMappingToConfig(savedConfig.value, {
      entityTypeId: selectedFinanceSpId.value,
      mapping: financeMapping.value,
    })

    const saveResult = await apiStore.saveConfiguration(next, {
      scope: FINANCE_CONFIG_SAVE_SCOPE,
      baseRevision: savedConfig.value.config_revision,
    })

    const nextWithRevision = { ...next, config_revision: saveResult?.config_revision ?? next.config_revision }
    savedConfig.value = nextWithRevision
    config.value = {
      ...config.value,
      finance_sp_entity_type_id: nextWithRevision.finance_sp_entity_type_id,
      finance_fields_mapping: nextWithRevision.finance_fields_mapping,
      config_revision: nextWithRevision.config_revision,
    }
    applyMappingHealthConfig(nextWithRevision)

    switch (plan.kind) {
      case 'ready':
        showStatus('success', `«Доходы-расходы» сохранены: операции БДДС читаются из смарт-процесса ID ${plan.financeSpIdToSend}. Остальные шаги не менялись.`)
        break
      case 'draft':
        showStatus('info', `Черновик «Доходов-расходов» сохранён. Операции заработают, когда будут сопоставлены: ${plan.missing.map(item => `«${item.label}»`).join(', ')}.`)
        break
      default:
        showStatus('success', 'Смарт-процесс «Доходы-расходы» отвязан. Остальные шаги не менялись.')
    }
    await revealStatus()
  } catch (e) {
    await reportSaveError(e)
  } finally {
    isSavingFinance.value = false
  }
}

// endregion

// region Уход с экрана с несохранённым черновиком (Баг 7)

const UNSAVED_CHANGES_CONFIRM_TEXT = 'На экране есть несохранённые изменения сопоставления. Уйти без сохранения?'

/**
 * «К настройкам» — единственная навигационная кнопка на экране, поэтому обе
 * (наверху и внизу шаблона) используют один обработчик вместо голого
 * `router.push('/settings')`: раньше он уводил без всякой проверки черновика.
 */
function goToSettings() {
  if (hasUnsavedChanges.value && typeof window !== 'undefined' && !window.confirm(UNSAVED_CHANGES_CONFIRM_TEXT)) {
    return
  }

  router.push('/settings')
}

/** Переход роутером на другой экран приложения (левое меню, ссылки и т.п.). */
onBeforeRouteLeave(() => {
  if (!hasUnsavedChanges.value) {
    return true
  }

  if (typeof window === 'undefined') {
    return true
  }

  return window.confirm(UNSAVED_CHANGES_CONFIRM_TEXT)
})

/** Закрытие вкладки/перезагрузка страницы — роутер здесь не задействован. */
function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedChanges.value) {
    return
  }

  event.preventDefault()
  // Значение для Chrome — большинство браузеров игнорируют текст и
  // показывают свой системный, но само присвоение обязательно.
  event.returnValue = ''
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', handleBeforeUnload)
  onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
}

// endregion

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await loadData()
    await revealStepFromRoute()
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <B24Container>
    <B24PageHeader
      title="Сопоставление полей"
      description="Связывает поля приложения с полями смарт-процессов портала. Пока связь не настроена, приложению некуда писать часы, а отчёты, счета и БДДС остаются пустыми."
    >
      <template #links>
        <B24Button label="К настройкам" color="link" @click="goToSettings" />
        <B24Button
          :label="saveButtonLabel"
          color="success"
          :loading="isSaving"
          :disabled="isSaving || !isInit"
          @click="handleSave"
        />
      </template>
    </B24PageHeader>

    <div v-if="isLoading && !isInit" class="mt-6">
      <B24Empty title="Читаем настройки портала…" size="sm" />
    </div>

    <div v-else class="mt-6 flex flex-col gap-6 pb-10">
      <!-- Итог: где человек находится и что делать дальше -->
      <section aria-labelledby="mapping-overall-title" class="space-y-4">
        <div :class="overallToneClass">
          <p id="mapping-overall-title" class="text-sm font-semibold">
            {{ overall.title }}
          </p>
          <p class="mt-1 text-sm">
            {{ overall.text }}
          </p>
        </div>

        <!--
          Полоса прогресса.

          Кнопки, а не декорация: незакрытый шаг — это ещё и переход к своему
          блоку, иначе на длинной странице человек ищет нужный блок глазами.
        -->
        <ol class="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
          <li v-for="(step, index) in steps" :key="step.id">
            <a
              :href="`#${step.anchor}`"
              class="mapping-step"
              :class="`mapping-step--${step.state}`"
            >
              <span class="mapping-step__index">{{ index + 1 }}</span>
              <span class="mapping-step__title">{{ step.title }}</span>
              <span class="mapping-step__hint">{{ step.hint }}</span>
              <span class="mapping-step__state">
                <template v-if="step.state === 'done'">готово</template>
                <template v-else-if="step.state === 'attention'">есть проблема</template>
                <template v-else-if="step.state === 'current'">сейчас здесь</template>
                <template v-else-if="step.state === 'optional'">по желанию</template>
                <template v-else>позже</template>
              </span>
            </a>
          </li>
        </ol>
      </section>

      <!-- Результат последнего действия -->
      <div
        v-if="statusMessage"
        ref="statusRef"
        class="ms-note"
        :class="{
          'ms-note-success': statusMessage.type === 'success',
          'ms-note-danger': statusMessage.type === 'error',
          'ms-note-info': statusMessage.type === 'info',
        }"
        role="status"
      >
        {{ statusMessage.text }}
      </div>

      <!-- Сводка отказа сохранения: получает фокус, ведёт к полям -->
      <div
        v-if="saveReport"
        ref="saveReportRef"
        class="ms-note ms-note-danger"
        role="alert"
        tabindex="-1"
      >
        <p class="text-sm font-semibold">{{ saveReport.title }}</p>
        <p class="mt-1 text-sm">{{ saveReport.text }}</p>
        <div v-if="saveReport.conflict" class="mt-3">
          <B24Button label="Обновить" color="default" size="sm" @click="reloadAfterConflict" />
        </div>
        <ul v-if="saveReport.blockers.length" class="mt-3 space-y-2">
          <li v-for="blocker in saveReport.blockers" :key="`blocker-${blocker.key}`">
            <button
              type="button"
              class="text-sm font-semibold underline decoration-dotted"
              @click="goToField(blocker.block, blocker.key)"
            >
              {{ blocker.label }}
            </button>
            <p class="text-xs">{{ blocker.reason }}</p>
          </li>
        </ul>
      </div>

      <!-- Шаг 1 -->
      <B24Card id="block-timesheet-process">
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Шаг 1. Куда приложение пишет часы</span>
            <span class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {{ timesheetStatus.state === 'no-process' ? 'не выбрано' : `ID ${timesheetStatus.entityTypeId}` }}
            </span>
          </div>
        </template>

        <div class="space-y-4">
          <p class="text-sm text-slate-600">
            Каждое списание часов — отдельный элемент смарт-процесса на портале. Выберите
            существующий процесс или создайте новый: приложение само заведёт в нём нужные поля и
            заполнит сопоставление.
          </p>

          <div class="max-w-[520px]">
            <label for="timesheet-process" class="mb-1 block text-sm font-semibold text-slate-800">
              Смарт-процесс списаний
            </label>
            <select
              id="timesheet-process"
              class="block w-full"
              :value="selectedSpId ?? ''"
              :disabled="isLoadingSpFields"
              @change="event => onProcessChange('timesheet', event)"
            >
              <option value="">— не выбрано —</option>
              <option v-for="option in smartProcessOptions" :key="`ts-${option.value}`" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <p class="mt-1 text-xs text-slate-500">
              Поля выбранного процесса подгружаются сразу — отдельно нажимать ничего не нужно.
            </p>
          </div>

          <div class="flex flex-wrap gap-2">
            <B24Button
              label="Создать смарт-процесс с полями"
              color="primary"
              size="sm"
              :loading="isCreatingSP"
              :disabled="Boolean(selectedSpId) || isCreatingSP"
              @click="handleCreateSmartProcess"
            />
          </div>
          <p v-if="selectedSpId" class="text-xs text-slate-500">
            Создание нового процесса доступно, пока не выбран существующий: иначе приложение
            потеряло бы связь с уже внесёнными часами.
          </p>
        </div>
      </B24Card>

      <!-- Шаг 2 -->
      <B24Card v-if="selectedSpId" id="block-timesheet-fields">
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Шаг 2. Поля списания</span>
            <span
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
              :class="timesheetStatus.state === 'ready' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'"
            >
              {{ timesheetStatus.headline }}
            </span>
          </div>
        </template>

        <MappingFieldsCard
          block="timesheet"
          :rows="TIMESHEET_MAPPING_ROWS"
          :status="timesheetStatus"
          :mapping="mapping"
          :sp-fields="spFields"
          :suggestions="timesheetSuggestions"
          :suggestions-note="timesheetSuggestionsNote"
          :is-suggesting="isSuggestingTimesheet"
          :is-loading-fields="isLoadingSpFields"
          :creating-key="creatingKey"
          :highlight-key="highlightKey"
          :can-edit="true"
          @change="(key, value) => onMappingChange('timesheet', key, value)"
          @create="(key, label) => handleCreateField('timesheet', key, label)"
          @suggest="handleSuggest('timesheet')"
          @apply-suggestions="handleApplySuggestions('timesheet')"
          @dismiss-suggestions="dismissSuggestions('timesheet')"
          @reload-fields="selectedSpId && loadSpFields(selectedSpId)"
        />
      </B24Card>

      <!-- Шаг 3 -->
      <B24Card id="block-project-process">
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Шаг 3. Карточки проектов</span>
            <span class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {{ projectStatus.state === 'no-process' ? 'не выбрано' : `ID ${projectStatus.entityTypeId}` }}
            </span>
          </div>
        </template>

        <div class="space-y-4">
          <p class="text-sm text-slate-600">
            Смарт-процесс проектов — источник правды по бюджету часов, ставке, куратору и юрлицам.
            Из него работают доска проектов, БДДС и счета. Без него учёт часов останется, а всё
            перечисленное — нет.
          </p>

          <div class="max-w-[520px]">
            <label for="project-process" class="mb-1 block text-sm font-semibold text-slate-800">
              Смарт-процесс проектов
            </label>
            <select
              id="project-process"
              class="block w-full"
              :value="selectedProjectSpId ?? ''"
              :disabled="isLoadingProjectFields"
              @change="event => onProcessChange('project', event)"
            >
              <option value="">— не выбрано —</option>
              <option v-for="option in smartProcessOptions" :key="`pr-${option.value}`" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>

          <!--
            Предупреждение про поведение сервера.

            Сказать об этом надо ДО того, как человек начнёт заполнять: иначе
            он выбирает процесс, жмёт «Сохранить» и получает 400 без
            сохранения хоть чего-нибудь.
          -->
          <p v-if="selectedProjectSpId" class="ms-note ms-note-info">
            Этот процесс сервер принимает только с ПОЛНЫМ сопоставлением: все 12 полей ниже
            обязательны. Пока хотя бы одно пустое, кнопка «Сохранить» сохранит только сопоставление
            списаний, а выбор процесса останется черновиком — работа при этом не теряется.
          </p>
        </div>
      </B24Card>

      <!-- Шаг 4 -->
      <B24Card v-if="selectedProjectSpId" id="block-project-fields">
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Шаг 4. Поля карточки проекта</span>
            <span
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
              :class="projectStatus.state === 'ready' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'"
            >
              {{ projectStatus.headline }}
            </span>
          </div>
        </template>

        <MappingFieldsCard
          block="project"
          :rows="PROJECT_MAPPING_ROWS"
          :status="projectStatus"
          :mapping="projectMapping"
          :sp-fields="projectSpFields"
          :suggestions="projectSuggestions"
          :suggestions-note="projectSuggestionsNote"
          :is-suggesting="isSuggestingProject"
          :is-loading-fields="isLoadingProjectFields"
          :creating-key="creatingKey"
          :highlight-key="highlightKey"
          :can-edit="true"
          all-required-note="Все поля этого блока обязательны — так требует сервер при сохранении. Необязательных здесь нет."
          @change="(key, value) => onMappingChange('project', key, value)"
          @create="(key, label) => handleCreateField('project', key, label)"
          @suggest="handleSuggest('project')"
          @apply-suggestions="handleApplySuggestions('project')"
          @dismiss-suggestions="dismissSuggestions('project')"
          @reload-fields="selectedProjectSpId && loadProjectSpFields(selectedProjectSpId)"
        />
      </B24Card>

      <!-- Шаг 5 -->
      <B24Card v-if="selectedProjectSpId" id="block-project-check">
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Шаг 5. Проверка связности</span>
          </div>
        </template>

        <div class="space-y-4">
          <p class="text-sm text-slate-600">
            Проверка спрашивает портал: видит ли приложение карточки проектов, может ли их
            изменять, и у всех ли карточек есть своя рабочая группа. Это то, что нельзя узнать по
            одному сопоставлению полей.
          </p>

          <div class="flex flex-wrap gap-2">
            <B24Button
              label="Проверить сейчас"
              color="primary"
              size="sm"
              :loading="isValidating"
              :disabled="isValidating"
              @click="runValidation(false)"
            />
          </div>

          <div
            class="ms-note"
            :class="validationReport.ok ? 'ms-note-success' : validation ? 'ms-note-danger' : 'ms-note-info'"
          >
            {{ validationReport.headline }}
          </div>

          <ul v-if="validationReport.problems.length" class="space-y-3">
            <li
              v-for="problem in validationReport.problems"
              :key="problem.id"
              class="rounded-xl border border-slate-200 bg-white px-4 py-3"
            >
              <p class="text-sm font-semibold text-slate-900">{{ problem.title }}</p>
              <p class="mt-1 text-sm text-slate-600">{{ problem.detail }}</p>
              <p class="mt-1 text-sm text-slate-500">Что делать: {{ problem.fix }}</p>
            </li>
          </ul>

          <div v-if="validation" class="grid gap-2 md:grid-cols-4">
            <div class="ms-panel-muted">
              <div class="text-xs text-slate-500">Карточек проектов</div>
              <div class="text-lg font-semibold text-slate-900">
                {{ validation.linkage_issues.total_items }}
              </div>
            </div>
            <div class="ms-panel-muted">
              <div class="text-xs text-slate-500">Без рабочей группы</div>
              <div class="text-lg font-semibold text-amber-600">
                {{ validation.linkage_issues.missing_group_link_count }}
              </div>
            </div>
            <div class="ms-panel-muted">
              <div class="text-xs text-slate-500">Группа в двух карточках</div>
              <div class="text-lg font-semibold text-rose-600">
                {{ validation.linkage_issues.duplicate_group_link_count }}
              </div>
            </div>
            <div class="ms-panel-muted">
              <div class="text-xs text-slate-500">Карточка на двух группах</div>
              <div class="text-lg font-semibold text-rose-600">
                {{ validation.linkage_issues.duplicate_project_item_link_count }}
              </div>
            </div>
          </div>

          <details v-if="validationReport.warnings.length" class="rounded-2xl border border-slate-200 bg-white">
            <summary class="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-900">
              Замечания проверки ({{ validationReport.warnings.length }})
            </summary>
            <ul class="space-y-1 border-t border-slate-100 px-4 py-3 text-sm text-slate-600">
              <li v-for="(warning, index) in validationReport.warnings" :key="`warning-${index}`">
                {{ warning }}
              </li>
            </ul>
          </details>
        </div>
      </B24Card>

      <!--
        Шаг 6: «Доходы-расходы». Необязательный.

        Одной карточкой, а не двумя, как у списаний и проектов: шаг один и
        по желанию, и растягивать его на два блока значит делать его
        похожим на обязательный. Сюда ведут экраны БДДС (`?step=finance`).
      -->
      <B24Card
        id="block-finance-process"
        :class="targetStep === 'finance' ? 'mapping-card--target' : ''"
      >
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Шаг 6. Доходы-расходы</span>
            <span class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              по желанию
            </span>
            <span
              v-if="financeStatus.state !== 'no-process'"
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
              :class="financeStatus.state === 'ready' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'"
            >
              {{ `ID ${financeStatus.entityTypeId} · ${financeStatus.headline}` }}
            </span>
          </div>
        </template>

        <div class="space-y-4">
          <p class="text-sm text-slate-600">
            Смарт-процесс «Доходы-расходы» хранит поступления и списания по проектам: из него
            работают экран «Операции по проектам» и блок операций в карточке проекта БДДС. Шаг
            необязательный — часы, отчёты и счета работают без него, и предупреждение в шапке
            приложения из-за него не появится.
          </p>

          <!--
            Мягкое напоминание — только при подключённом «БДДС по проектам».
            Без подписки операций нет вовсе, и напоминать не о чем.
          -->
          <div v-if="financeNotice" class="ms-note ms-note-info">
            <p class="text-sm font-semibold">{{ financeNotice.title }}</p>
            <p class="mt-1 text-sm">
              У портала подключён «БДДС по проектам». {{ financeNotice.text }}
            </p>
            <p v-if="financeNotice.missingLabels.length" class="mt-1 text-sm">
              Не сопоставлено: {{ financeNotice.missingLabels.join(', ') }}.
            </p>
          </div>
          <p v-else-if="!bddsAccess.enabled && !bddsAccess.unknown" class="text-xs text-slate-500">
            «БДДС по проектам» на этом портале не подключён — шаг можно пропустить.
          </p>

          <div class="max-w-[520px]">
            <label for="finance-process" class="mb-1 block text-sm font-semibold text-slate-800">
              Смарт-процесс «Доходы-расходы»
            </label>
            <select
              id="finance-process"
              class="block w-full"
              :value="selectedFinanceSpId ?? ''"
              :disabled="isLoadingFinanceFields"
              @change="event => onProcessChange('finance', event)"
            >
              <option value="">— не выбрано —</option>
              <option v-for="option in smartProcessOptions" :key="`fin-${option.value}`" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <p v-if="!financeAppProcess" class="mt-1 text-xs text-slate-500">
              Готового процесса «{{ FINANCE_APP_SMART_PROCESS_TITLE }}» на портале не нашлось.
              Выберите свой процесс и заведите недостающие поля кнопками «Создать поле на портале».
            </p>
          </div>

          <!-- Подсказка готового процесса: его заводит установка, поля в нём уже есть -->
          <div
            v-if="financeAppProcess && selectedFinanceSpId !== Number(financeAppProcess.entityTypeId)"
            class="ms-panel-muted flex flex-wrap items-center justify-between gap-3"
          >
            <p class="min-w-0 text-sm text-slate-700">
              На портале есть «{{ financeAppProcess.title }}» (ID {{ financeAppProcess.entityTypeId }}) —
              его завела установка приложения, все поля в нём уже созданы и подберутся точно по коду.
            </p>
            <B24Button
              :label="`Выбрать «${FINANCE_APP_SMART_PROCESS_TITLE}»`"
              color="primary"
              size="sm"
              :loading="isLoadingFinanceFields"
              :disabled="isLoadingFinanceFields"
              @click="useFinanceAppProcess"
            />
          </div>

          <MappingFieldsCard
            v-if="selectedFinanceSpId"
            block="finance"
            :rows="FINANCE_MAPPING_ROWS"
            :status="financeStatus"
            :mapping="financeMapping"
            :sp-fields="financeSpFields"
            :suggestions="financeSuggestions"
            :suggestions-note="financeSuggestionsNote"
            :is-suggesting="isSuggestingFinance"
            :is-loading-fields="isLoadingFinanceFields"
            :creating-key="creatingKey"
            :highlight-key="highlightKey"
            :can-edit="true"
            @change="(key, value) => onMappingChange('finance', key, value)"
            @create="(key, label) => handleCreateField('finance', key, label)"
            @suggest="handleSuggest('finance')"
            @apply-suggestions="handleApplySuggestions('finance')"
            @dismiss-suggestions="dismissSuggestions('finance')"
            @reload-fields="selectedFinanceSpId && loadFinanceSpFields(selectedFinanceSpId)"
          />

          <!-- Что будет при сохранении шага -->
          <section aria-labelledby="finance-save-plan-title" class="ms-panel-muted">
            <p id="finance-save-plan-title" class="text-sm font-semibold text-slate-900">
              {{ financePlan.title }}
            </p>
            <p class="mt-1 text-sm text-slate-600">
              {{ financePlan.note }}
            </p>
            <ul v-if="financePlan.missing.length" class="mt-3 space-y-1 text-sm text-slate-600">
              <li v-for="item in financePlan.missing" :key="`finance-plan-${item.key}`">
                <button
                  type="button"
                  class="font-semibold underline decoration-dotted"
                  @click="goToField('finance', item.key)"
                >
                  {{ item.label }}
                </button>
              </li>
            </ul>
            <div class="mt-3 flex flex-wrap items-center gap-3">
              <B24Button
                label="Сохранить «Доходы-расходы»"
                color="success"
                size="sm"
                :loading="isSavingFinance"
                :disabled="isSavingFinance || isSaving || !isInit || !financeChanged"
                @click="handleSaveFinance"
              />
              <span v-if="!financeChanged" class="text-xs text-slate-500">Несохранённых изменений в шаге нет.</span>
            </div>
            <p class="mt-2 text-xs text-slate-500">
              Сохраняет только этот шаг: несохранённые правки других шагов останутся черновиком, а
              проверка и синхронизация проектов не запускаются.
            </p>
          </section>
        </div>
      </B24Card>

      <!-- Ставка по умолчанию: не сопоставление, но сохраняется той же кнопкой -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Ставка часа по умолчанию</span>
        </template>

        <div class="max-w-[320px]">
          <label for="hour-rate" class="mb-1 block text-sm font-semibold text-slate-800">
            Стоимость часа, ₽
          </label>
          <input
            id="hour-rate"
            v-model.number="config.hourly_rate"
            type="number"
            min="0"
            class="block w-full"
            placeholder="Например: 1500"
          >
          <p class="mt-1 text-xs text-slate-500">
            Применяется к проектам, у которых своя ставка в карточке не заполнена. Без ставки суммы
            в счетах и БДДС посчитаются нулевыми. Сохраняется вместе с сопоставлением, кнопкой
            наверху.
          </p>
        </div>
      </B24Card>

      <!-- Что произойдёт при сохранении -->
      <section aria-labelledby="mapping-save-plan-title" class="ms-panel-muted">
        <p id="mapping-save-plan-title" class="text-sm font-semibold text-slate-900">
          {{ savePlan.title }}
        </p>
        <p class="mt-1 text-sm text-slate-600">
          {{ savePlan.note }}
        </p>
        <p v-if="financeChanged" class="mt-1 text-sm text-slate-600">
          <template v-if="savePlan.kind === 'blocked'">
            «Доходы-расходы» от этого не зависят — их можно сохранить отдельно, кнопкой в шаге 6.
          </template>
          <template v-else>
            «Доходы-расходы» тоже уйдут этой кнопкой. {{ financePlan.title }}.
          </template>
        </p>
        <ul v-if="savePlan.kind === 'blocked'" class="mt-3 space-y-1 text-sm text-slate-600">
          <li v-for="blocker in savePlan.blockers" :key="`plan-${blocker.key}`">
            <button
              type="button"
              class="font-semibold underline decoration-dotted"
              @click="goToField('project', blocker.key)"
            >
              {{ blocker.label }}
            </button>
          </li>
        </ul>
        <div class="mt-3 flex flex-wrap gap-2">
          <B24Button
            :label="saveButtonLabel"
            color="success"
            :loading="isSaving"
            :disabled="isSaving"
            @click="handleSave"
          />
          <B24Button label="К настройкам" color="link" @click="goToSettings" />
        </div>
        <p class="mt-2 text-xs text-slate-500">
          Настройка общая на весь портал: её видят все сотрудники сразу после сохранения.
        </p>
      </section>
    </div>
  </B24Container>
</template>

<style scoped>
/*
 * Шаги настройки.
 *
 * Ширины и отступы в явных единицах: именованные `max-w-*`/`w-<размер>`
 * в Tailwind 4 вместе с темой UI Kit падают на шкалу `--spacing` и дают
 * 16–24 px (см. предупреждение в app/assets/css/main.css).
 */
.mapping-step {
  display: flex;
  flex-direction: column;
  gap: 2px;
  height: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  text-decoration: none;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.mapping-step:hover {
  border-color: #94a3b8;
}

.mapping-step:focus-visible {
  outline: 2px solid #0075ff;
  outline-offset: 2px;
}

.mapping-step__index {
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  color: #94a3b8;
}

.mapping-step__title {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.25;
  color: #0f172a;
}

.mapping-step__hint {
  font-size: 11px;
  line-height: 1.3;
  color: #64748b;
}

.mapping-step__state {
  margin-top: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #94a3b8;
}

.mapping-step--done {
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.mapping-step--done .mapping-step__state {
  color: #047857;
}

.mapping-step--current {
  border-color: #0075ff;
  background: #eff6ff;
}

.mapping-step--current .mapping-step__state {
  color: #0075ff;
}

.mapping-step--attention {
  border-color: #fecdd3;
  background: #fff1f2;
}

.mapping-step--attention .mapping-step__state {
  color: #be123c;
}

/* Шаг по желанию: пунктир, чтобы не читался как недоделанный обязательный. */
.mapping-step--optional {
  border-style: dashed;
}

/* Карточка шага, к которому привела ссылка с другого экрана. */
.mapping-card--target {
  box-shadow: 0 0 0 2px #0075ff;
}

@media (max-width: 768px) {
  .mapping-step {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 6px;
  }

  .mapping-step__hint {
    width: 100%;
  }
}
</style>
