<script setup lang="ts">
/**
 * Роли и права.
 *
 * Зачем отдельный экран. До 12.09.2026 права задавались списком «Бухгалтерия»
 * внутри блока «Счёт и акт» на длинной странице настроек, и пользователь
 * «настройки так и не нашёл». Теперь это пункт под шестерёнкой, карточка на
 * странице настроек и адрес, на который ведут тексты отказов.
 *
 * Что на экране — сверху вниз, в порядке вопросов человека:
 *  1. какой режим действует (подключена ли ролевая модель) и какая роль у меня;
 *  2. таблица «что может роль» — прямо здесь, без документации; у роли
 *     «Администратор» при живом Pro она редактируется (права × роли с
 *     переключателями, предпросмотр до сохранения, «вернуть по умолчанию»,
 *     журнал изменений). Логика редактора — app/utils/permissionMatrix.ts,
 *     проверка и хранение — на сервере (main/roles.py);
 *  3. кто сейчас в какой роли;
 *  4. поиск сотрудника и назначение роли.
 *
 * Права решает СЕРВЕР (main/roles.py): роли в нашей БД, назначение — только
 * через /api/roles/assign с правом roles_manage. Выпадающие списки здесь
 * гаснут у тех, кто назначать не может, но это забота, а не охрана.
 *
 * Логика — чистыми функциями в app/utils/appRoles.ts (node:test не резолвит
 * .vue). Ширины — явными значениями: именованные max-w-* в этом проекте
 * попадают на шкалу --spacing темы UI Kit и дают десятки пикселей.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import ProPlanNotice from '~/components/finance/ProPlanNotice.vue'
import {
  buildRoleMatrixRows,
  buildRoleOptions,
  describeAssignment,
  describeRoleAssignError,
  describeRolesMode,
  rolesModeBadge,
  mergeUsersWithRoles,
  parseRoleAssignments,
  parseRolesCatalog,
  parseRolesMe,
  type PermissionCode,
  type RoleAssignment,
  type RoleCode,
  type RolesCatalog,
  type RolesMe,
  type RoleUserRow,
} from '~/utils/appRoles'
import {
  buildMatrixSections,
  cloneMatrix,
  describeLocks,
  describeLogEntry,
  describeMatrixSaveError,
  describeRequirement,
  describeRoleChange,
  diffMatrices,
  formatLogDate,
  isRoleAtDefault,
  matrixCellView,
  matrixEditMode,
  parseMatrixEditor,
  parseMatrixLog,
  pluralChanges,
  resetAllToDefault,
  resetRoleToDefault,
  summarizeChanges,
  togglePermission,
  type AutoChange,
  type MatrixEditorData,
  type MatrixLogEntry,
  type PermissionMatrix,
} from '~/utils/permissionMatrix'

const router = useRouter()
const apiStore = useApiStore()
const { me: sharedMe, rolesAccess } = useAppPermissions()

useHead({ title: 'Роли и права' })

const { initApp, processErrorGlobal } = useAppInit('RolesSettingsPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const isLoading = ref(true)
const loadError = ref('')
const me = ref<RolesMe | null>(null)
const catalog = ref<RolesCatalog>(parseRolesCatalog(null))
const assignments = ref<RoleAssignment[]>([])
const canManage = ref(false)
const assignable = ref<RoleCode[]>([])

const search = ref('')
const searching = ref(false)
const searchError = ref('')
const foundUsers = ref<RoleUserRow[]>([])
const searched = ref(false)

/** user_id -> сохраняется прямо сейчас. */
const saving = ref<Record<string, boolean>>({})
const notice = ref('')
const assignError = ref('')

/**
 * Режим — из общего состояния подписки (usePaidFeature('roles')):
 * restrictionsActive — роли действуют (Pro или «только чтение» после него),
 * canWrite — роли можно менять. До ответа /api/features режим неизвестен.
 */
const modeInput = computed(() => rolesAccess.value.unknown ? null : rolesAccess.value)
const rolesEnabled = computed(() => rolesAccess.value.restrictionsActive)
const canChangeRoles = computed(() => canManage.value && rolesAccess.value.canWrite)
const mode = computed(() => describeRolesMode(modeInput.value))
const matrixRows = computed(() => buildRoleMatrixRows(catalog.value, rolesEnabled.value))
/** Какие роли назначать — решает сервер (assignable_roles), экран только гасит остальные. */
const roleOptions = computed(() => buildRoleOptions(catalog.value, canChangeRoles.value ? assignable.value : []))
const modeBadge = computed(() => rolesModeBadge(modeInput.value))
const rolesActiveNow = computed(() => rolesAccess.value.restrictionsActive && rolesAccess.value.canWrite)

// --- Права ролей: редактор матрицы --------------------------------------

const editor = ref<MatrixEditorData>(parseMatrixEditor(null))
/** Черновик на экране; сохранённое — editor.matrix. */
const draft = ref<PermissionMatrix>(cloneMatrix(editor.value.matrix))
const matrixLog = ref<MatrixLogEntry[]>([])
const canEditMatrixOnServer = ref(false)
const autoNotes = ref<AutoChange[]>([])
const blockedNote = ref('')
const matrixSaving = ref(false)
const matrixNotice = ref('')
const matrixError = ref('')

const editMode = computed(() => matrixEditMode({
  canManage: canManage.value,
  restrictionsActive: rolesAccess.value.restrictionsActive,
  canWrite: rolesAccess.value.canWrite,
  unknown: rolesAccess.value.unknown,
}))
/** Экран и сервер согласны: править можно (сервер всё равно проверит сам). */
const matrixEditable = computed(() => editMode.value.editable && canEditMatrixOnServer.value)
const matrixSections = computed(() => buildMatrixSections(editor.value))
const pendingChanges = computed(() => diffMatrices(editor.value.matrix, draft.value))
const pendingSummary = computed(() => summarizeChanges(editor.value, pendingChanges.value))
const lockLegend = computed(() => describeLocks(editor.value))
const draftAtDefault = computed(() => editor.value.roles.every(role => isRoleAtDefault(editor.value, draft.value, role.code)))
const customizedOnPortal = computed(() => editor.value.roles.some(role => role.customized))
const roleColumnsWidth = computed(() => `${Math.max(760, 360 + editor.value.roles.length * 150)}px`)

function applyRolesPayload(data: Record<string, unknown>) {
  editor.value = parseMatrixEditor(data.catalog)
  draft.value = cloneMatrix(editor.value.matrix)
  matrixLog.value = parseMatrixLog(data.matrix_log)
  autoNotes.value = []
  blockedNote.value = ''
}

function cell(role: RoleCode, permission: PermissionCode) {
  return matrixCellView(editor.value, editor.value.matrix, draft.value, role, permission)
}

function onToggle(role: RoleCode, permission: PermissionCode, value: boolean) {
  matrixNotice.value = ''
  matrixError.value = ''
  const result = togglePermission(editor.value, draft.value, role, permission, value)
  if (result.blocked) {
    blockedNote.value = result.blocked
    return
  }
  blockedNote.value = ''
  draft.value = result.matrix
  // Пояснение показываем про последние авто-изменения; прежние, уже
  // отменённые ручным переключением, не копим.
  autoNotes.value = [
    ...autoNotes.value.filter(note => !result.auto.some(next => next.role === note.role && next.permission === note.permission)),
    ...result.auto,
  ].filter(note => (draft.value[note.role] || []).includes(note.permission) === note.granted)
}

function resetRole(role: RoleCode) {
  draft.value = resetRoleToDefault(editor.value, draft.value, role)
  autoNotes.value = autoNotes.value.filter(note => note.role !== role)
  blockedNote.value = ''
  matrixNotice.value = ''
}

function resetAll() {
  draft.value = resetAllToDefault(editor.value)
  autoNotes.value = []
  blockedNote.value = ''
  matrixNotice.value = ''
}

function discardDraft() {
  draft.value = cloneMatrix(editor.value.matrix)
  autoNotes.value = []
  blockedNote.value = ''
  matrixError.value = ''
}

async function saveMatrix() {
  if (!pendingChanges.value.length) {
    return
  }
  matrixSaving.value = true
  matrixNotice.value = ''
  matrixError.value = ''
  const count = pendingChanges.value.length
  try {
    const result = await apiStore.saveRolesMatrix(draft.value, editor.value.revision)
    applyRolesPayload(result)
    if (result.me) {
      me.value = parseRolesMe(result.me)
      sharedMe.value = me.value
    }
    matrixNotice.value = `Права сохранены (${pluralChanges(count)}). Сотрудники получат их при следующем действии — `
      + 'перезаходить в приложение не нужно.'
  } catch (e) {
    const failure = describeMatrixSaveError(e)
    matrixError.value = failure.text
    if (failure.conflict) {
      await loadRoles()
      matrixError.value = failure.text
    }
  } finally {
    matrixSaving.value = false
  }
}

/** Назначенные роли; администраторы портала сервер отдаёт первыми строками. */
const assignedRows = computed(() => assignments.value)

async function loadRoles() {
  isLoading.value = true
  loadError.value = ''
  try {
    const data = await apiStore.getRoles()
    me.value = parseRolesMe(data.me)
    // Экран ролей — самый свежий источник прав: кладём их в общее состояние,
    // чтобы меню и кнопки на других экранах не жили вчерашним ответом.
    sharedMe.value = me.value
    catalog.value = parseRolesCatalog(data.catalog)
    assignments.value = parseRoleAssignments(data.assignments)
    canManage.value = data.can_manage === true
    canEditMatrixOnServer.value = data.can_edit_matrix === true
    assignable.value = me.value?.assignableRoles || []
    applyRolesPayload(data)
  } catch (e) {
    loadError.value = e instanceof Error && e.message && !/^\[[A-Z]+\]/.test(e.message)
      ? e.message
      : 'Не удалось загрузить роли. Обновите страницу позже.'
  } finally {
    isLoading.value = false
  }
}

async function searchUsers() {
  const query = search.value.trim()
  searchError.value = ''
  if (!query) {
    foundUsers.value = []
    searched.value = false
    return
  }

  searching.value = true
  try {
    const response = await apiStore.getUsers(1, 30, true, query)
    foundUsers.value = mergeUsersWithRoles(response.items || [], assignments.value)
    searched.value = true
  } catch {
    searchError.value = 'Поиск не ответил. Попробуйте ещё раз.'
  } finally {
    searching.value = false
  }
}

async function assign(userId: string, role: RoleCode, name: string) {
  saving.value = { ...saving.value, [userId]: true }
  notice.value = ''
  assignError.value = ''

  try {
    const result = await apiStore.assignRole(userId, role)
    assignments.value = parseRoleAssignments(result.assignments)
    foundUsers.value = foundUsers.value.map(row => row.userId === userId
      ? { ...row, role, roleTitle: String(result.role_title || row.roleTitle) }
      : row)
    notice.value = `${name || `Сотрудник #${userId}`}: роль «${String(result.role_title || role)}». `
      + 'Права поменяются при следующем действии сотрудника — перезаходить в приложение не нужно.'
  } catch (e) {
    assignError.value = describeRoleAssignError(e)
    // Список назад: показанная роль должна совпадать с сохранённой.
    await loadRoles()
    if (searched.value) {
      foundUsers.value = mergeUsersWithRoles(
        foundUsers.value.map(row => ({ id: row.userId, name: row.name })),
        assignments.value
      )
    }
  } finally {
    saving.value = { ...saving.value, [userId]: false }
  }
}

function onRoleChange(row: { userId: string, name: string }, event: Event) {
  const value = (event.target as HTMLSelectElement).value as RoleCode
  void assign(row.userId, value, row.name)
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
  } catch (e) {
    processErrorGlobal(e)
    return
  }
  await loadRoles()
})
</script>

<template>
  <B24Container>
    <B24PageHeader
      title="Роли и права"
      description="Кто видит суммы, выставляет счета, добавляет начисления и списания, закрывает месяц и меняет настройки."
    >
      <template #links>
        <B24Button label="Обновить" :loading="isLoading" @click="loadRoles" />
        <B24Button label="Все настройки" color="link" @click="router.push('/settings')" />
      </template>
    </B24PageHeader>

    <div class="mt-6 flex flex-col gap-6">
      <div v-if="loadError" class="ms-note ms-note-danger">{{ loadError }}</div>

      <!-- Сроки тарифа (грейс, «Pro закончился — роли не меняются») — общая плашка подписки. -->
      <ProPlanNotice :notice="rolesAccess.notice" feature-id="roles" />

      <!-- 1. Режим и моя роль -->
      <B24Card>
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Режим прав</span>
            <span
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
              :class="rolesActiveNow ? 'bg-emerald-100 text-emerald-700' : (rolesEnabled ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-500')"
            >
              {{ modeBadge }}
            </span>
          </div>
        </template>

        <p :class="mode.tone === 'warning' ? 'ms-panel-warning text-sm' : 'text-sm text-slate-600'">
          {{ mode.text }}
        </p>
        <p v-if="me" class="mt-3 text-sm text-slate-600">
          Ваша роль: <span class="font-semibold text-slate-900">{{ me.roleTitle }}</span>
          <span v-if="me.isPortalAdmin" class="text-slate-500"> (вы администратор портала)</span>.
          <span v-if="!canManage" class="text-slate-500">
            Назначать роли может роль «Администратор».
          </span>
        </p>
      </B24Card>

      <!-- 2. Права ролей -->
      <B24Card>
        <template #header>
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-base font-semibold text-slate-900">Права ролей</span>
              <span
                v-if="rolesEnabled && customizedOnPortal"
                class="rounded-full bg-sky-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-sky-700"
              >
                изменены на портале
              </span>
            </div>
            <B24Button
              v-if="matrixEditable"
              label="Вернуть всё по умолчанию"
              color="link"
              size="sm"
              :disabled="draftAtDefault || matrixSaving"
              @click="resetAll"
            />
          </div>
        </template>

        <div class="ms-panel-muted mb-4">
          <p class="text-sm font-medium text-slate-800">Всем ролям всегда открыто</p>
          <p class="mt-1 text-sm text-slate-600">
            {{ editor.alwaysOpen.join(' · ') }}.
            Работа с часами правами не настраивается: права ограничивают только деньги, закрытие месяца и настройки.
          </p>
        </div>

        <template v-if="rolesEnabled">
          <p v-if="editMode.reason" class="ms-note ms-note-info mb-4">{{ editMode.reason }}</p>
          <p v-else-if="matrixEditable" class="mb-3 text-sm text-slate-500">
            Отметьте, что может каждая роль. Изменения видны в предпросмотре и начинают действовать только после
            сохранения. Серые ячейки с замком закреплены — почему, написано под таблицей.
          </p>

          <div class="ms-table-shell">
            <table class="ms-table" :style="{ minWidth: roleColumnsWidth }">
              <thead>
                <tr>
                  <th class="w-[360px] align-bottom">Право и что оно даёт</th>
                  <th v-for="role in editor.roles" :key="role.code" class="w-[150px] text-center align-bottom">
                    <div class="flex flex-col items-center gap-1">
                      <span>{{ role.title }}</span>
                      <span v-if="role.customized" class="text-[10px] font-medium normal-case tracking-normal text-sky-700">
                        изменена
                      </span>
                      <button
                        v-if="matrixEditable"
                        type="button"
                        class="text-[11px] font-medium normal-case tracking-normal text-sky-700 underline-offset-2 hover:underline disabled:cursor-default disabled:text-slate-300 disabled:no-underline"
                        :disabled="isRoleAtDefault(editor, draft, role.code) || matrixSaving"
                        :aria-label="`Вернуть права роли «${role.title}» по умолчанию`"
                        @click="resetRole(role.code)"
                      >
                        по умолчанию
                      </button>
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                <template v-for="section in matrixSections" :key="section.code">
                  <tr class="bg-slate-50 hover:bg-slate-50">
                    <td :colspan="editor.roles.length + 1" class="py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                      {{ section.title }}
                    </td>
                  </tr>
                  <tr v-for="permission in section.rows" :key="permission.code">
                    <td class="align-top">
                      <p class="font-medium text-slate-800">{{ permission.title }}</p>
                      <p v-if="permission.description" class="mt-1 text-xs text-slate-500">{{ permission.description }}</p>
                      <p v-if="describeRequirement(editor, permission.code)" class="mt-1 text-xs text-amber-700">
                        {{ describeRequirement(editor, permission.code) }}
                      </p>
                    </td>
                    <td
                      v-for="role in editor.roles"
                      :key="role.code"
                      class="text-center align-middle"
                      :class="cell(role.code, permission.code).changed ? 'bg-amber-50' : ''"
                    >
                      <template v-if="matrixEditable">
                        <label
                          class="inline-flex flex-col items-center gap-1"
                          :title="cell(role.code, permission.code).lockReason || undefined"
                        >
                          <input
                            type="checkbox"
                            class="size-[18px] accent-sky-600 disabled:cursor-not-allowed"
                            :checked="cell(role.code, permission.code).checked"
                            :disabled="cell(role.code, permission.code).locked || matrixSaving"
                            :aria-label="`${role.title}: ${permission.title}`"
                            @change="onToggle(role.code, permission.code, ($event.target as HTMLInputElement).checked)"
                          >
                          <span v-if="cell(role.code, permission.code).locked" class="text-[10px] text-slate-400">
                            закреплено
                          </span>
                        </label>
                      </template>
                      <template v-else>
                        <span
                          v-if="cell(role.code, permission.code).checked"
                          class="font-semibold text-emerald-700"
                          aria-label="можно"
                          :title="cell(role.code, permission.code).lockReason || undefined"
                        >✓</span>
                        <span v-else class="text-slate-300" aria-label="нельзя">—</span>
                      </template>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <p v-if="blockedNote" class="ms-note ms-note-danger mt-3">{{ blockedNote }}</p>

          <div v-if="matrixEditable && lockLegend.length" class="mt-3 flex flex-col gap-1 text-xs text-slate-500">
            <p class="font-medium text-slate-600">Закреплённые ячейки:</p>
            <p v-for="reason in lockLegend" :key="reason">{{ reason }}</p>
          </div>

          <!-- Предпросмотр до сохранения -->
          <div v-if="matrixEditable && pendingChanges.length" class="ms-panel-warning mt-4">
            <p class="font-semibold">Не сохранено: {{ pluralChanges(pendingChanges.length) }}</p>
            <ul class="mt-2 flex list-disc flex-col gap-1 pl-5">
              <li v-for="summary in pendingSummary" :key="summary.role">{{ describeRoleChange(summary) }}</li>
            </ul>
            <div v-if="autoNotes.length" class="mt-3 flex flex-col gap-1 text-xs">
              <p class="font-medium">Изменено автоматически из-за зависимостей:</p>
              <p v-for="note in autoNotes" :key="`${note.role}:${note.permission}`">
                {{ editor.roles.find(role => role.code === note.role)?.title }}: {{ note.reason }}
              </p>
            </div>
            <div class="mt-3 flex flex-wrap gap-2">
              <B24Button label="Сохранить права" color="primary" :loading="matrixSaving" @click="saveMatrix" />
              <B24Button label="Отменить изменения" color="link" :disabled="matrixSaving" @click="discardDraft" />
            </div>
          </div>

          <p v-if="matrixNotice" class="ms-note ms-note-success mt-4">{{ matrixNotice }}</p>
          <p v-if="matrixError" class="ms-note ms-note-danger mt-4">{{ matrixError }}</p>
        </template>

        <template v-else>
          <p class="mb-3 text-sm text-slate-500">
            Пока тариф Pro не подключён, таблица показывает права, которые действуют сейчас: столбец
            «Администратор» — это администраторы портала, «Руководитель проекта» работает как «Сотрудник».
            Настраивать права ролей можно после подключения Pro.
          </p>
          <div class="ms-table-shell">
            <table class="ms-table min-w-[760px]">
              <thead>
                <tr>
                  <th class="w-[320px]">Право</th>
                  <th v-for="role in catalog.roles" :key="role.code" class="text-center">{{ role.title }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in matrixRows" :key="row.permission">
                  <td class="text-slate-800">{{ row.title }}</td>
                  <td v-for="legacyCell in row.cells" :key="legacyCell.role" class="text-center">
                    <span v-if="legacyCell.allowed" class="font-semibold text-emerald-700" aria-label="можно">✓</span>
                    <span v-else class="text-slate-300" aria-label="нельзя">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div v-for="role in catalog.roles" :key="role.code" class="ms-panel-muted">
            <p class="text-sm font-semibold text-slate-800">{{ role.title }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ role.description }}</p>
          </div>
        </div>
      </B24Card>

      <!-- Журнал изменений прав -->
      <B24Card v-if="rolesEnabled">
        <template #header>
          <span class="text-base font-semibold text-slate-900">Журнал изменений прав</span>
        </template>

        <p v-if="!matrixLog.length" class="text-sm text-slate-500">
          Права ролей на портале не менялись — действуют значения по умолчанию.
        </p>
        <ol v-else class="flex flex-col divide-y divide-slate-200">
          <li v-for="entry in matrixLog" :key="entry.revision" class="py-3 first:pt-0 last:pb-0">
            <p class="text-sm font-medium text-slate-800">{{ describeLogEntry(entry).title }}</p>
            <p v-for="line in describeLogEntry(entry).lines" :key="line" class="mt-1 text-sm text-slate-600">{{ line }}</p>
          </li>
        </ol>
        <p v-if="editor.updatedAt" class="mt-3 text-xs text-slate-400">
          Последнее изменение: {{ formatLogDate(editor.updatedAt) }}<template v-if="editor.updatedByName">, {{ editor.updatedByName }}</template>.
        </p>
      </B24Card>

      <!-- 3. Назначение -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Назначить роль сотруднику</span>
        </template>

        <form class="flex flex-wrap items-end gap-3" @submit.prevent="searchUsers">
          <div class="flex min-w-[260px] grow flex-col gap-1">
            <label class="text-sm font-medium text-slate-700" for="roles-search">Сотрудник</label>
            <input
              id="roles-search"
              v-model="search"
              type="search"
              class="w-full"
              placeholder="Фамилия или имя"
              autocomplete="off"
            >
          </div>
          <B24Button label="Найти" type="submit" color="default" :loading="searching" />
        </form>

        <p class="mt-2 text-xs text-slate-500">
          Ищем по справочнику сотрудников приложения. Роль «Сотрудник» снимает назначенную роль.
        </p>
        <p v-if="canManage && !rolesAccess.unknown && !rolesAccess.canWrite" class="ms-note ms-note-info mt-3">
          {{ rolesEnabled
            ? 'Тариф Pro закончился: назначенные роли действуют, но менять их можно будет после продления.'
            : 'Назначать роли можно после подключения тарифа Pro.' }}
        </p>
        <p v-if="searchError" class="ms-note ms-note-danger mt-3">{{ searchError }}</p>

        <div v-if="searched" class="ms-table-shell mt-4">
          <table class="ms-table min-w-[560px]">
            <thead>
              <tr>
                <th>Сотрудник</th>
                <th class="w-[260px]">Роль</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!foundUsers.length">
                <td colspan="2" class="text-slate-500">Никого не нашли. Проверьте написание фамилии.</td>
              </tr>
              <tr v-for="row in foundUsers" :key="row.userId">
                <td class="text-slate-800">{{ row.name }}</td>
                <td>
                  <span v-if="row.isPortalAdmin" class="text-sm text-slate-500">
                    Администратор — администратор портала
                  </span>
                  <select
                    v-else
                    class="w-full"
                    :value="row.role"
                    :disabled="!canChangeRoles || saving[row.userId]"
                    :aria-label="`Роль: ${row.name}`"
                    @change="onRoleChange(row, $event)"
                  >
                    <option
                      v-for="option in roleOptions"
                      :key="option.value"
                      :value="option.value"
                      :disabled="option.disabled"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="notice" class="ms-note ms-note-success mt-4">{{ notice }}</p>
        <p v-if="assignError" class="ms-note ms-note-danger mt-4">{{ assignError }}</p>
      </B24Card>

      <!-- 4. Кто в какой роли -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Назначенные роли</span>
        </template>

        <B24Empty v-if="isLoading" title="Загрузка…" size="sm" />
        <p v-else-if="!assignedRows.length" class="text-sm text-slate-500">
          Ролей пока никому не назначено — у всех, кроме администраторов портала, роль «Сотрудник».
        </p>
        <div v-else class="ms-table-shell">
          <table class="ms-table min-w-[640px]">
            <thead>
              <tr>
                <th>Сотрудник</th>
                <th class="w-[260px]">Роль</th>
                <th>Откуда</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in assignedRows" :key="row.userId">
                <td class="text-slate-800">{{ row.name || `Сотрудник #${row.userId}` }}</td>
                <td>
                  <span v-if="row.isPortalAdmin" class="text-sm font-medium text-slate-700">{{ row.roleTitle }}</span>
                  <select
                    v-else
                    class="w-full"
                    :value="row.role"
                    :disabled="!canChangeRoles || saving[row.userId]"
                    :aria-label="`Роль: ${row.name || row.userId}`"
                    @change="onRoleChange({ userId: row.userId, name: row.name }, $event)"
                  >
                    <option
                      v-for="option in roleOptions"
                      :key="option.value"
                      :value="option.value"
                      :disabled="option.disabled"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                </td>
                <td class="text-xs text-slate-500">{{ describeAssignment(row) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </B24Card>
    </div>
  </B24Container>
</template>
