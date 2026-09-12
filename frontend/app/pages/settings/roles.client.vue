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
 *  2. таблица «что может роль» — прямо здесь, без документации;
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
  type RoleAssignment,
  type RoleCode,
  type RolesCatalog,
  type RolesMe,
  type RoleUserRow,
} from '~/utils/appRoles'

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
    assignable.value = me.value?.assignableRoles || []
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

      <!-- 2. Что может роль -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Что может каждая роль</span>
        </template>

        <p class="mb-3 text-sm text-slate-500">
          Работа с часами — списание времени, отчёты по часам, доска проектов, проверка данных — открыта всем
          ролям. Роли ограничивают только деньги, закрытие месяца и настройки.
          <template v-if="!rolesEnabled">
            Пока тариф Pro не подключён, таблица показывает права, которые действуют сейчас: столбец
            «Администратор» — это администраторы портала, «Руководитель проекта» работает как «Сотрудник».
          </template>
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
                <td v-for="cell in row.cells" :key="cell.role" class="text-center">
                  <span v-if="cell.allowed" class="font-semibold text-emerald-700" aria-label="можно">✓</span>
                  <span v-else class="text-slate-300" aria-label="нельзя">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div v-for="role in catalog.roles" :key="role.code" class="ms-panel-muted">
            <p class="text-sm font-semibold text-slate-800">{{ role.title }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ role.description }}</p>
          </div>
        </div>
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
