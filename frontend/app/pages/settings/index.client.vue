<template>
  <B24Container>
    <B24PageHeader
      title="Настройки"
      description="Персональные и системные параметры приложения."
    >
      <template #links>
        <B24Button label="Назад" color="link" @click="router.push('/')" />
      </template>
    </B24PageHeader>

    <div class="mt-6 space-y-6">
      <!-- Тумблер «Кликабельные метки» -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Отчёты</span>
        </template>
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-slate-700">Кликабельные метки</p>
            <p class="mt-1 text-sm text-slate-500">
              Названия меток времени в отчётах становятся ссылками, открывающими карточку элемента.
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer ml-4">
            <input v-model="clickableLabelsEnabled" type="checkbox" class="sr-only peer" @change="saveUserSettings">
            <div class="h-6 w-11 rounded-full bg-slate-300 transition peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-200 peer-checked:bg-[#0075ff] peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-slate-300 after:bg-white after:transition-all after:content-['']" />
          </label>
        </div>
      </B24Card>

      <!--
        Настройки «Счёта и акта».

        Стоят ЗДЕСЬ, а не на отдельном экране: обе настройки — про то, кому и
        когда можно выставлять, и искать их человек будет в настройках
        приложения. Сохраняются существующим механизмом — POST
        /api/configuration/save, тот же, что у сопоставления полей: обе
        настройки нужны СЕРВЕРУ (контракт, правила 1 и 3), а app.option
        портала сервер не читает.
      -->
      <B24Card>
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Счёт и акт</span>
            <span
              v-if="billingAccess.badge"
              class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
            >
              {{ billingAccess.badge }}
            </span>
          </div>
        </template>

        <div v-if="billingSettingsError" class="ms-note ms-note-danger">
          {{ billingSettingsError }}
        </div>

        <div v-else-if="!billingSettingsReady" class="text-sm text-slate-500">
          Загружаем настройки…
        </div>

        <div v-else class="space-y-5">
          <p v-if="!userStore.isAdmin" class="text-sm text-slate-500">
            Менять эти настройки может админ портала. Ниже — текущие значения.
          </p>

          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-sm font-medium text-slate-700">
                Разрешить выставление за незакрытый месяц
              </p>
              <p class="mt-1 text-sm text-slate-500">
                По умолчанию счёт можно выставить только за закрытый период: в открытом месяце часы
                ещё правят, и сумма счёта разойдётся с учётом. Включайте, когда клиент требует счёт
                до закрытия месяца.
              </p>
            </div>
            <label class="relative ml-4 inline-flex cursor-pointer items-center">
              <input
                v-model="billingSettings.allowOpenPeriod"
                type="checkbox"
                class="peer sr-only"
                :disabled="!userStore.isAdmin"
              >
              <div class="h-6 w-11 rounded-full bg-slate-300 transition peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-200 peer-checked:bg-[#0075ff] peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-slate-300 after:bg-white after:transition-all after:content-['']" />
            </label>
          </div>

          <div>
            <p class="text-sm font-medium text-slate-700">Бухгалтерия</p>
            <p class="mb-2 mt-1 text-sm text-slate-500">
              Кто может выставлять счета, печатать акты и отменять документы, кроме админов портала.
              Реестр документов при этом видят все — список ограничивает только запись.
            </p>
            <MultiSelectFilter
              label="Сотрудники"
              :options="employeeOptions"
              :model-value="billingSettings.accountantIds"
              @update:model-value="billingSettings.accountantIds = ($event as string[]).map(String)"
            />
          </div>

          <div v-if="billingSaveNotice" class="ms-note ms-note-success">{{ billingSaveNotice }}</div>
        </div>

        <template #footer>
          <div class="flex flex-wrap items-center gap-3">
            <B24Button
              label="Сохранить"
              color="success"
              :disabled="!canSaveBillingSettings"
              :loading="isSavingBilling"
              @click="saveBillingSettings"
            />
            <span v-if="billingSettingsDirty" class="text-sm text-slate-500">Есть несохранённые изменения</span>
          </div>
        </template>
      </B24Card>

      <!-- Грид основных разделов -->
      <B24PageGrid>
        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Конфигурация</span>
          </template>
          <p class="text-sm text-slate-500">
            Сопоставление полей процесса с данными приложения.
          </p>
          <template #footer>
            <B24Button label="Настройка полей" color="success" @click="router.push('/settings/mapping')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Данные</span>
          </template>
          <p class="text-sm text-slate-500">
            Просмотр исходных записей, синхронизированных с системой.
          </p>
          <template #footer>
            <B24Button label="Открыть проверку данных" color="primary" @click="router.push('/reports/raw-data')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Диагностика</span>
          </template>
          <p class="text-sm text-slate-500">
            Логи запросов и ошибок системы.
          </p>
          <template #footer>
            <B24Button label="Диагностика системы" color="default" @click="router.push('/settings/debug')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Проекты</span>
          </template>
          <p class="text-sm text-slate-500">
            Проверка заполненности данных проектов для ИНН.
          </p>
          <template #footer>
            <B24Button label="Незаполненные проекты" color="default" @click="router.push('/settings/projects-health')" />
          </template>
        </B24Card>

        <B24Card>
          <template #header>
            <span class="text-base font-semibold text-slate-900">Закрытие месяца</span>
          </template>
          <p class="text-sm text-slate-500">
            Заморозка часов за период. После закрытия списать или изменить часы
            за этот месяц нельзя.
          </p>
          <template #footer>
            <B24Button label="Периоды" color="default" @click="router.push('/settings/periods')" />
          </template>
        </B24Card>
      </B24PageGrid>

      <!-- Служебные разделы -->
      <B24Card>
        <template #header>
          <span class="text-base font-semibold text-slate-900">Служебные разделы</span>
        </template>
        <p class="text-sm text-slate-500">
          Технические экраны вынесены из главной страницы и доступны отсюда.
        </p>
        <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <B24Button label="Проверка данных" color="default" @click="router.push('/reports/raw-data')" />
          <B24Button label="Диагностика отчетов" color="default" @click="router.push('/reports/debug')" />
          <B24Button label="Диагностика настроек" color="default" @click="router.push('/settings/debug')" />
          <B24Button label="Опции слайдера" color="default" @click="router.push('/slider/app-options')" />
        </div>
      </B24Card>
    </div>
  </B24Container>
</template>

<script setup lang="ts">
/**
 * Настройки приложения.
 *
 * Экран исторически работал без обращений к бэкенду — только тумблер личной
 * настройки через app.option портала. Блок «Счёт и акт» добавил сюда первый
 * серверный запрос (/api/configuration), и это единственная причина, по
 * которой здесь появился бутстрап B24.
 *
 * Отказ бутстрапа или конфигурации НЕ зовёт processErrorGlobal: тот показал
 * бы фатальный экран (app/error.vue, :clear="false") на странице, которая до
 * этой правки открывалась всегда. Ломать остальные настройки из-за одной
 * недоступной ручки нельзя — блок просто скажет, что настройки недоступны.
 */
import { computed, onMounted, ref, watch } from 'vue'
import MultiSelectFilter from '~/components/common/MultiSelectFilter.vue'
import {
  applyBillingSettings,
  billingSettingsChanged,
  readBillingSettings,
  type BillingSettings,
} from '~/utils/billingSettings'
import type { AppConfigurationPayload } from '~/types/config'
import type { FilterOption } from '~/types/report'

const router = useRouter()
const userSettings = useUserSettingsStore()
const userStore = useUserStore()
const apiStore = useApiStore()
const { access: billingAccess } = useBillingFeature()

const { initApp } = useAppInit('SettingsPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()

const billingSettingsReady = ref(false)
const billingSettingsError = ref('')
const billingSaveNotice = ref('')
const isSavingBilling = ref(false)

const configuration = ref<AppConfigurationPayload>({})
const billingSettings = ref<BillingSettings>({ allowOpenPeriod: false, accountantIds: [] })
const savedBillingSettings = ref<BillingSettings>({ allowOpenPeriod: false, accountantIds: [] })
const employeeOptions = ref<FilterOption[]>([])

const billingSettingsDirty = computed(() => billingSettingsChanged(
  billingSettings.value,
  savedBillingSettings.value
))

const canSaveBillingSettings = computed(() => userStore.isAdmin
  && billingSettingsReady.value
  && billingSettingsDirty.value
  && !isSavingBilling.value)

/**
 * Сохранение шлёт конфигурацию ЦЕЛИКОМ с подменёнными ключами «Счёта и акта».
 *
 * /api/configuration/save принимает объект целиком, и отправка одних только
 * своих ключей затёрла бы сопоставление полей смарт-процессов — то есть всю
 * настройку приложения. Мерж делает applyBillingSettings, он же покрыт
 * тестами.
 */
async function saveBillingSettings() {
  if (!canSaveBillingSettings.value) {
    return
  }

  isSavingBilling.value = true
  billingSaveNotice.value = ''
  billingSettingsError.value = ''

  try {
    const next = applyBillingSettings(configuration.value, billingSettings.value)
    const result = await apiStore.saveConfiguration(next)

    configuration.value = result?.config || next
    savedBillingSettings.value = readBillingSettings(configuration.value)
    billingSettings.value = readBillingSettings(configuration.value)
    billingSaveNotice.value = 'Настройки «Счёта и акта» сохранены.'
  } catch (e) {
    billingSettingsError.value = e instanceof Error && e.message
      ? e.message
      : 'Не удалось сохранить настройки. Попробуйте ещё раз.'
  } finally {
    isSavingBilling.value = false
  }
}

onMounted(async () => {
  try {
    const $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
  } catch {
    billingSettingsError.value = 'Приложение не смогло связаться с порталом — настройки «Счёта и акта» недоступны.'
    return
  }

  const [configResult, employeesResult] = await Promise.allSettled([
    apiStore.getConfiguration(),
    apiStore.getFilterEmployees(),
  ])

  if (configResult.status !== 'fulfilled') {
    billingSettingsError.value = 'Не удалось загрузить настройки приложения с сервера. Остальные разделы работают.'
    return
  }

  configuration.value = configResult.value || {}
  billingSettings.value = readBillingSettings(configuration.value)
  savedBillingSettings.value = readBillingSettings(configuration.value)
  employeeOptions.value = employeesResult.status === 'fulfilled' ? employeesResult.value : []
  billingSettingsReady.value = true
})

useHead({
  title: 'Настройки'
})

const clickableLabelsEnabled = ref(userSettings.configSettings.clickableLabelsEnabled ?? false)

// Sync local ref with store changes
watch(() => userSettings.configSettings.clickableLabelsEnabled, (val) => {
  clickableLabelsEnabled.value = val ?? false
})

async function saveUserSettings() {
  userSettings.configSettings.clickableLabelsEnabled = clickableLabelsEnabled.value
  try {
    await userSettings.saveSettings()
  } catch (e) {
    console.error('Failed to save user settings:', e)
  }
}
</script>
