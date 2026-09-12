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

        Стоят ЗДЕСЬ, а не на отдельном экране: все они — про то, от кого,
        кому, когда и какими строками можно выставлять, и искать их человек
        будет в настройках приложения. Сохраняются существующим механизмом — POST
        /api/configuration/save, тот же, что у сопоставления полей: все они
        нужны СЕРВЕРУ (контракт, правила 1 и 3, плюс выбор нашего юрлица), а
        app.option портала сервер сам не читает.
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

          <!--
            Наше юрлицо. Стоит ПЕРВЫМ в блоке: это единственная настройка
            «Счёта и акта», без которой счёт уходит не от того, от кого надо,
            — остальные две решают «кому можно» и «когда можно».
          -->
          <div>
            <label class="block text-sm font-medium text-slate-700" for="billing-our-company">
              Наше юрлицо для счетов
            </label>
            <p class="mb-2 mt-1 text-sm text-slate-500">
              Юрлицо, от которого выставляются все счета и печатаются акты. Оно перекрывает то, что
              записано в карточке проекта: карточки приходят с портала синхронизацией, и поправить
              их в приложении нельзя — следующий обмен вернёт прежние значения.
            </p>
            <select
              id="billing-our-company"
              v-model="billingSettings.ourCompanyId"
              class="w-full"
              :disabled="!userStore.isAdmin"
              @change="onOurCompanyChange"
            >
              <option value="">Как в карточке проекта</option>
              <option v-for="company in myCompanies" :key="company.id" :value="company.id">
                {{ company.name }}
              </option>
              <!--
                Сохранённое юрлицо, которого нет в списке портала: показать его
                надо обязательно, иначе select молча покажет «Как в карточке
                проекта» — то есть соврёт про действующую настройку.
              -->
              <option
                v-if="ourCompanySetting.configured && ourCompanySetting.missing"
                :value="billingSettings.ourCompanyId"
              >
                {{ ourCompanySetting.label }} — не найдено на портале
              </option>
            </select>
            <p
              class="mt-1 text-xs"
              :class="ourCompanySetting.missing ? 'font-medium text-red-700' : 'text-slate-500'"
            >
              {{ ourCompanySetting.text }}
            </p>
            <p v-if="myCompaniesFailed" class="mt-1 text-xs text-amber-700">
              Список своих юрлиц портал не отдал — в нём может не быть всех компаний. Сохранённое
              значение при этом не меняется.
            </p>
          </div>

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

          <!--
            Варианты наполнения счёта. Стоят сразу после юрлица: это второе,
            что клиент читает в документе. До настройки строка называлась
            ровно так, как названа карточка проекта, и у клиента НУОЛАБ
            карточка названа по клиенту — наименованием работ в счёте
            оказалось «НУОЛАБ».

            Формулировка у КАЖДОГО варианта своя. Одного общего шаблона не
            хватало: «{задача}, {месяц}» в счёте на одну строку читается как
            «Услуги по договору, август 2026».
          -->
          <div>
            <label class="block text-sm font-medium text-slate-700" for="billing-line-variant">
              Вариант наполнения счёта по умолчанию
            </label>
            <p class="mb-2 mt-1 text-sm text-slate-500">
              Этот вариант мастер «Выставить» подставляет при открытии. Переключить его на один
              счёт можно прямо в предпросмотре — настройка от этого не меняется.
            </p>
            <select
              id="billing-line-variant"
              v-model="billingSettings.lineVariant"
              class="w-full"
              :disabled="!userStore.isAdmin"
            >
              <option v-for="variant in BILLING_LINE_VARIANTS" :key="variant.id" :value="variant.id">
                {{ variant.label }}
              </option>
            </select>
          </div>

          <div>
            <p class="text-sm font-medium text-slate-700">Наименование работ в строке</p>
            <p class="mb-2 mt-1 text-sm text-slate-500">
              По этим шаблонам собирается текст строк счёта и акта — по одному на каждый вариант
              наполнения. Под полем видно, как строка прочитается на вымышленных данных; текст
              можно поправить и вручную в предпросмотре перед выставлением.
            </p>

            <div class="space-y-3">
              <div
                v-for="row in lineVariantRows"
                :key="row.id"
                class="rounded-lg border px-3 py-2"
                :class="row.isDefaultVariant ? 'border-[#0075ff] bg-blue-50/40' : 'border-slate-200'"
              >
                <div class="flex flex-wrap items-baseline justify-between gap-2">
                  <label class="text-sm font-medium text-slate-700" :for="`billing-line-template-${row.id}`">
                    {{ row.label }}
                  </label>
                  <span v-if="row.isDefaultVariant" class="text-[11px] font-semibold uppercase tracking-wide text-[#0075ff]">
                    по умолчанию
                  </span>
                </div>
                <p class="mb-1 text-xs text-slate-500">{{ row.summary }}</p>
                <input
                  :id="`billing-line-template-${row.id}`"
                  :value="row.template"
                  type="text"
                  class="w-full"
                  :disabled="!userStore.isAdmin"
                  :placeholder="row.defaultTemplate"
                  @input="setLineTemplate(row.id, ($event.target as HTMLInputElement).value)"
                >
                <p class="mt-1 text-xs text-slate-500">
                  Так будет выглядеть строка:
                  <span class="font-medium text-slate-900">{{ row.example }}</span>
                </p>
                <p v-if="row.unknown.length" class="mt-1 text-xs font-medium text-amber-700">
                  Подстановки {{ row.unknown.join(', ') }} приложение не знает — они уйдут в счёт
                  как есть, фигурными скобками. Проверьте написание.
                </p>
              </div>
            </div>

            <ul class="mt-2 space-y-0.5 text-xs text-slate-500">
              <li v-for="item in BILLING_LINE_PLACEHOLDERS" :key="item.token">
                <span class="font-mono text-slate-700">{{ item.token }}</span> — {{ item.hint }}
              </li>
            </ul>
          </div>

          <!--
            Текст услуги отдельной настройкой, а не словом внутри шаблонов:
            услуга повторяется в формулировках («Разработка по проекту…»,
            «Услуги по разработке…»), и менять её правкой четырёх полей
            человек забудет.
          -->
          <div>
            <label class="block text-sm font-medium text-slate-700" for="billing-service-name">
              Услуга для подстановки {{ '{услуга}' }}
            </label>
            <p class="mb-2 mt-1 text-sm text-slate-500">
              Предмет договора одним словом: он подставляется в формулировки вместо
              {{ '{услуга}' }} — «Разработка по проекту „Личный кабинет“».
            </p>
            <input
              id="billing-service-name"
              v-model="billingSettings.serviceName"
              type="text"
              class="w-full"
              :disabled="!userStore.isAdmin"
              :placeholder="DEFAULT_BILLING_SERVICE_NAME"
            >
          </div>

          <div>
            <label class="block text-sm font-medium text-slate-700" for="billing-task-level">
              Уровень задачи в строке
            </label>
            <p class="mb-2 mt-1 text-sm text-slate-500">
              Работает при варианте «Строка на задачу». Часы, не привязанные ни к одной задаче,
              в любом случае уходят отдельной строкой «Работы без привязки к задаче» — они не
              теряются.
            </p>
            <select
              id="billing-task-level"
              v-model="billingSettings.taskLevel"
              class="w-full"
              :disabled="!userStore.isAdmin"
            >
              <option v-for="option in BILLING_TASK_LEVEL_OPTIONS" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
            <p class="mt-1 text-xs text-slate-500">{{ taskLevelHint }}</p>
          </div>

          <!--
            Шаблоны генератора документов. Стоят ПОСЛЕ формулировки строки и
            ПЕРЕД списком «Бухгалтерия»: это последняя настройка про то, как
            выглядит документ, а дальше идут настройки про людей.

            Список приходит с портала (GET /api/billing/templates) и в
            приложении не редактируется — поэтому подпись про это стоит над
            обоими полями, а не под каждым: главное недоразумение здесь не
            «какой шаблон выбрать», а «где поменять текст акта».
          -->
          <div class="space-y-4 rounded-lg border border-slate-200 p-4">
            <div>
              <p class="text-sm font-medium text-slate-700">Шаблоны печатных форм</p>
              <p class="mt-1 text-sm text-slate-500">{{ BILLING_TEMPLATE_SOURCE_HINT }}</p>
            </div>

            <p v-if="!templatesReady" class="text-sm text-slate-500">Загружаем шаблоны с портала…</p>

            <!--
              Пустой список НЕ показываем пустым селектом: человеку нужно
              знать, что шаблоны создаются на портале, а не искать их в
              приложении. Отказ портала и честный ноль различаются текстом.
            -->
            <p
              v-else-if="!templates.length && !templatesSkipped"
              :class="templatesFailed ? 'ms-panel-warning' : 'ms-note ms-note-info'"
            >
              {{ templatesEmptyText }}
            </p>

            <div>
              <label class="block text-sm font-medium text-slate-700" for="billing-act-template">
                Шаблон акта
              </label>
              <select
                id="billing-act-template"
                v-model="billingSettings.actTemplateId"
                class="mt-2 w-full"
                :disabled="!userStore.isAdmin"
              >
                <!--
                  Пустое значение у акта — это не «не печатать», а прежнее
                  поведение: подбор по названию. Писать «не выбран» было бы
                  неправдой — акт всё равно напечатается.
                -->
                <option value="">Подбирать по названию (как было)</option>
                <option v-for="template in templates" :key="template.id" :value="template.id">
                  {{ billingTemplateOptionLabel(template) }}
                </option>
                <!--
                  Сохранённый шаблон, которого нет в списке портала: не
                  показать его значило бы, что select молча покажет первый
                  вариант и соврёт про действующую настройку.
                -->
                <option
                  v-if="actTemplateSetting.missing"
                  :value="billingSettings.actTemplateId"
                >
                  Шаблон {{ billingSettings.actTemplateId }} — удалён на портале
                </option>
              </select>
              <p
                class="mt-1 text-xs"
                :class="actTemplateSetting.missing ? 'font-medium text-red-700' : 'text-slate-500'"
              >
                {{ actTemplateSetting.text }}
              </p>
            </div>

            <div>
              <label class="block text-sm font-medium text-slate-700" for="billing-invoice-template">
                Шаблон счёта
              </label>
              <select
                id="billing-invoice-template"
                v-model="billingSettings.invoiceTemplateId"
                class="mt-2 w-full"
                :disabled="!userStore.isAdmin"
              >
                <option value="">Не печатать счёт из приложения</option>
                <option v-for="template in templates" :key="template.id" :value="template.id">
                  {{ billingTemplateOptionLabel(template) }}
                </option>
                <option
                  v-if="invoiceTemplateSetting.missing"
                  :value="billingSettings.invoiceTemplateId"
                >
                  Шаблон {{ billingSettings.invoiceTemplateId }} — удалён на портале
                </option>
              </select>
              <p
                class="mt-1 text-xs"
                :class="invoiceTemplateSetting.missing ? 'font-medium text-red-700' : 'text-slate-500'"
              >
                {{ invoiceTemplateSetting.text }}
              </p>
            </div>
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

      <!--
        Настройки «БДДС по проектам».

        Отдельной картой рядом с «Счётом и актом», а не внутри него: это
        другая платная функция с другой подпиской, и смешивать их настройки
        в одном блоке значит обещать, что они включаются вместе.

        Сохраняются тем же POST /api/configuration/save: пороги и адресатов
        читает СЕРВЕР (main/bdds_settings.py), а настройка, которой сервер не
        видит, ничего не меняет. Выключателя подписки здесь нет и быть не
        может — он на нашем сервере (PortalFeature), иначе платную функцию
        включали бы через app.option из консоли браузера.
      -->
      <B24Card>
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">БДДС по проектам</span>
            <span
              v-if="bddsAccess.badge"
              class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
            >
              {{ bddsAccess.badge }}
            </span>
          </div>
        </template>

        <div v-if="billingSettingsError" class="ms-note ms-note-danger">
          {{ billingSettingsError }}
        </div>

        <div v-else-if="!billingSettingsReady" class="text-sm text-slate-500">
          Загружаем настройки…
        </div>

        <div v-else class="space-y-6">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-sm font-medium text-slate-700">Уведомления о бюджете</p>
              <p class="mt-1 text-sm text-slate-500">
                Куратор проекта получает уведомление, когда проект входит в «Риск» или
                «Перерасход», а поддержка уходит в минус. Повтор одного и того же события
                по одному проекту не чаще раза в 12 часов.
              </p>
            </div>
            <label class="relative ml-4 inline-flex cursor-pointer items-center">
              <input v-model="bddsSettings.notificationsEnabled" type="checkbox" class="sr-only peer">
              <div class="h-6 w-11 rounded-full bg-slate-300 transition peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-200 peer-checked:bg-[#0075ff] peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-slate-300 after:bg-white after:transition-all after:content-['']" />
            </label>
          </div>

          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label class="block text-sm font-medium text-slate-700" for="bdds-risk">
                Порог «Риск», %
              </label>
              <input
                id="bdds-risk"
                v-model.number="bddsSettings.riskPercent"
                type="number"
                min="1"
                max="1000"
                class="mt-2 w-full"
              >
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-700" for="bdds-overrun">
                Порог «Перерасход», %
              </label>
              <input
                id="bdds-overrun"
                v-model.number="bddsSettings.overrunPercent"
                type="number"
                min="1"
                max="1000"
                class="mt-2 w-full"
              >
            </div>
          </div>
          <p class="text-sm text-slate-500">{{ bddsThresholdsHint }}</p>

          <div>
            <p class="text-sm font-medium text-slate-700">Кому ещё уходит уведомление</p>
            <p class="mt-1 mb-2 text-sm text-slate-500">
              Кроме куратора проекта. Пусто — только куратор; у проекта без куратора
              уведомление тогда никому не уходит.
            </p>
            <MultiSelectFilter
              label="Сотрудники"
              :options="employeeOptions"
              :model-value="bddsSettings.notifyUserIds"
              @update:model-value="bddsSettings.notifyUserIds = ($event as string[]).map(String)"
            />
          </div>

          <div v-if="bddsSaveNotice" class="ms-note ms-note-success">{{ bddsSaveNotice }}</div>
          <div v-if="bddsSaveError" class="ms-note ms-note-danger">{{ bddsSaveError }}</div>
          <div v-if="bddsNotifierNotice" class="ms-note ms-note-info">{{ bddsNotifierNotice }}</div>
        </div>

        <template #footer>
          <div class="flex flex-wrap items-center gap-3">
            <B24Button
              label="Сохранить"
              color="success"
              :disabled="!canSaveBddsSettings"
              :loading="isSavingBdds"
              @click="saveBddsSettings"
            />
            <B24Button
              label="Проверить сейчас"
              color="default"
              :disabled="!canRunBddsNotifier"
              :loading="isRunningBddsNotifier"
              @click="runBddsNotifier"
            />
            <span v-if="bddsSettingsDirty" class="text-sm text-slate-500">Есть несохранённые изменения</span>
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
import { describeBillingError } from '~/utils/billingErrors'
import {
  BILLING_LINE_PLACEHOLDERS,
  BILLING_LINE_VARIANTS,
  BILLING_TASK_LEVEL_OPTIONS,
  DEFAULT_BILLING_LINE_TEMPLATES,
  DEFAULT_BILLING_SERVICE_NAME,
  previewBillingLineTemplate,
  unknownBillingPlaceholders,
} from '~/utils/billingLineTemplate'
import { describeOurCompanySetting } from '~/utils/billingOurCompany'
import { describeBddsError } from '~/utils/bddsErrors'
import { describeBddsNotifierRun } from '~/utils/bddsRegistry'
import {
  applyBddsSettings,
  bddsSettingsChanged,
  defaultBddsSettings,
  describeBddsThresholds,
  readBddsSettings,
  type BddsSettings,
} from '~/utils/bddsSettings'
import {
  BILLING_TEMPLATE_SOURCE_HINT,
  billingTemplateOptionLabel,
  billingTemplatesEmptyText,
  describeBillingTemplateSetting,
  parseBillingTemplates,
  type BillingTemplate,
} from '~/utils/billingTemplates'
import {
  applyBillingSettings,
  billingSettingsChanged,
  readBillingSettings,
  type BillingSettings,
} from '~/utils/billingSettings'
import type { AppConfigurationPayload } from '~/types/config'
import type { FilterOption } from '~/types/report'

/** Пустые настройки «Счёта и акта» — самое строгое из состояний. */
function emptyBillingSettings(): BillingSettings {
  return {
    allowOpenPeriod: false,
    accountantIds: [],
    ourCompanyId: '',
    ourCompanyName: '',
    // Вариант, формулировки и уровень — не «строгая» часть настроек: пустая
    // строка оставила бы строки счёта без наименования работ, поэтому
    // исходное состояние равно значениям по умолчанию.
    lineVariant: 'task',
    lineTemplates: { ...DEFAULT_BILLING_LINE_TEMPLATES },
    serviceName: DEFAULT_BILLING_SERVICE_NAME,
    taskLevel: 'task',
    // Шаблоны: «не выбран». Для акта это прежнее поведение (подбор по
    // названию), для счёта — печать недоступна.
    actTemplateId: '',
    invoiceTemplateId: '',
  }
}

const router = useRouter()
const userSettings = useUserSettingsStore()
const userStore = useUserStore()
const apiStore = useApiStore()
const { access: billingAccess } = useBillingFeature()
const { access: bddsAccess } = useBddsFeature()

const { initApp } = useAppInit('SettingsPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()

const billingSettingsReady = ref(false)
const billingSettingsError = ref('')
const billingSaveNotice = ref('')
const isSavingBilling = ref(false)

const configuration = ref<AppConfigurationPayload>({})
const bddsSettings = ref<BddsSettings>(defaultBddsSettings())
const savedBddsSettings = ref<BddsSettings>(defaultBddsSettings())
const bddsSaveNotice = ref('')
const bddsSaveError = ref('')
const isSavingBdds = ref(false)
const bddsNotifierNotice = ref('')
const isRunningBddsNotifier = ref(false)
const billingSettings = ref<BillingSettings>(emptyBillingSettings())
const savedBillingSettings = ref<BillingSettings>(emptyBillingSettings())
const employeeOptions = ref<FilterOption[]>([])
/** Свои юрлица портала (GET /api/project-board/my-companies). */
const myCompanies = ref<Array<{ id: string, name: string }>>([])
/** Портал не подтвердил полноту списка — это НЕ «юрлиц нет». */
const myCompaniesFailed = ref(false)
/** Шаблоны генератора документов портала (GET /api/billing/templates). */
const templates = ref<BillingTemplate[]>([])
/** Список получен (пусть и пустой) — только тогда с ним можно сверять настройку. */
const templatesReady = ref(false)
/** Портал список не отдал. Это НЕ «шаблонов нет»: текст на экране разный. */
const templatesFailed = ref(false)
/** Что именно ответил портал — чтобы не гадать, дело в модуле или в правах. */
const templatesError = ref('')
/**
 * Список не запрашивали вовсе — читатель не админ и менять настройку всё
 * равно не может.
 *
 * Отдельное состояние, а не «пустой список»: сказать не-админу «на портале
 * нет шаблонов» значило бы соврать, а показать ему отказ по правам —
 * пожаловаться на то, чего он не просил.
 */
const templatesSkipped = ref(false)

/**
 * Четыре варианта наполнения с полем формулировки и живым примером у каждого.
 *
 * Пример считается ЗДЕСЬ, а не на сервере: он нужен на каждое нажатие
 * клавиши, а запрос на каждое нажатие — нет. Правила подстановки в
 * utils/billingLineTemplate.ts повторяют серверные.
 *
 * Опечатки в подстановках показываются вслух у ТОГО поля, где сделаны: одно
 * общее предупреждение под четырьмя полями не сказало бы, в каком из них
 * искать.
 */
const lineVariantRows = computed(() => BILLING_LINE_VARIANTS.map((variant) => {
  const template = billingSettings.value.lineTemplates?.[variant.id] ?? ''

  return {
    ...variant,
    template,
    example: previewBillingLineTemplate(
      template, variant.id, billingSettings.value.serviceName,
    ),
    unknown: unknownBillingPlaceholders(template),
    isDefaultVariant: billingSettings.value.lineVariant === variant.id,
  }
}))

/** Правка формулировки одного варианта. */
function setLineTemplate(variant: string, value: string) {
  billingSettings.value.lineTemplates = {
    ...billingSettings.value.lineTemplates,
    [variant]: value,
  }
}

const taskLevelHint = computed(
  () => BILLING_TASK_LEVEL_OPTIONS.find(
    option => option.id === billingSettings.value.taskLevel
  )?.hint || ''
)

const templatesEmptyText = computed(() => billingTemplatesEmptyText({
  failed: templatesFailed.value,
  errorText: templatesError.value,
}))

const actTemplateSetting = computed(() => describeBillingTemplateSetting({
  kind: 'act',
  templateId: billingSettings.value.actTemplateId,
  templates: templates.value,
  // Недогруженный список сверять нельзя: пометка «удалён на портале» из-за
  // недоступного генератора документов врёт про рабочую настройку.
  listLoaded: templatesReady.value && !templatesFailed.value && !templatesSkipped.value,
}))

const invoiceTemplateSetting = computed(() => describeBillingTemplateSetting({
  kind: 'invoice',
  templateId: billingSettings.value.invoiceTemplateId,
  templates: templates.value,
  listLoaded: templatesReady.value && !templatesFailed.value && !templatesSkipped.value,
}))

const ourCompanySetting = computed(() => describeOurCompanySetting({
  ourCompanyId: billingSettings.value.ourCompanyId,
  ourCompanyName: billingSettings.value.ourCompanyName,
  // Неполный список сверять нельзя: пометка «не найдено на портале» из-за
  // сетевого сбоя врёт про настройку, которая на самом деле рабочая.
  myCompanies: myCompaniesFailed.value ? null : myCompanies.value,
}))

/**
 * Название юрлица запоминается ВМЕСТЕ с идентификатором.
 *
 * Сервер в счёт всё равно подставит текущее название с портала
 * (billing_service.verify_our_company), но экранам приложения нужна подпись
 * и до этого: одного идентификатора человеку недостаточно, чтобы понять, от
 * кого он собирается выставлять.
 */
function onOurCompanyChange() {
  const id = String(billingSettings.value.ourCompanyId || '').trim()
  const found = myCompanies.value.find(item => item.id === id)

  billingSettings.value.ourCompanyName = id ? (found?.name || '') : ''
}

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

const bddsThresholdsHint = computed(() => describeBddsThresholds(bddsSettings.value))

const bddsSettingsDirty = computed(() => bddsSettingsChanged(
  bddsSettings.value,
  savedBddsSettings.value
))

const canSaveBddsSettings = computed(() => userStore.isAdmin
  && billingSettingsReady.value
  && bddsSettingsDirty.value
  && !isSavingBdds.value)

const canRunBddsNotifier = computed(() => userStore.isAdmin
  && bddsAccess.value.enabled
  && !isRunningBddsNotifier.value)

/**
 * Сохранение шлёт конфигурацию целиком с подменёнными ключами БДДС — тем же
 * приёмом, что у «Счёта и акта» (см. saveBillingSettings выше).
 *
 * Оговорка, общая для обоих блоков: конфигурация одна, и сохранение одного
 * блока отправляет её в том виде, в каком она пришла с сервера, плюс СВОИ
 * ключи. То есть несохранённые правки соседнего блока при этом не уезжают —
 * но и не сохраняются. Каждый блок сохраняется своей кнопкой.
 */
async function saveBddsSettings() {
  if (!canSaveBddsSettings.value) {
    return
  }

  isSavingBdds.value = true
  bddsSaveNotice.value = ''
  bddsSaveError.value = ''

  try {
    const next = applyBddsSettings(configuration.value, bddsSettings.value)
    const result = await apiStore.saveConfiguration(next)

    configuration.value = result?.config || next
    savedBddsSettings.value = readBddsSettings(configuration.value)
    bddsSettings.value = readBddsSettings(configuration.value)
    bddsSaveNotice.value = 'Настройки «БДДС по проектам» сохранены.'
  } catch (e) {
    bddsSaveError.value = e instanceof Error && e.message
      ? e.message
      : 'Не удалось сохранить настройки. Попробуйте ещё раз.'
  } finally {
    isSavingBdds.value = false
  }
}

/**
 * Прогон уведомлений руками.
 *
 * Нотификатор рассчитан на внешнее расписание, и без этой кнопки убедиться,
 * что уведомления доходят, было бы можно только дождавшись ночного прогона.
 * Кнопка доступна только при включённой подписке: ручка закрыта
 * @feature_required('bdds') и на выключенном портале ответила бы 403.
 *
 * Прогон ничего не меняет в данных — он рассылает уведомления и ставит
 * паузу на отправленные события. Поэтому «Проверить сейчас» не требует
 * сохранённых изменений и не мешает несохранённым: сервер считает по тому,
 * что у него уже сохранено, и текст итога об этом честен.
 */
async function runBddsNotifier() {
  if (!canRunBddsNotifier.value) {
    return
  }

  isRunningBddsNotifier.value = true
  bddsNotifierNotice.value = ''

  try {
    const result = await apiStore.runProjectBudgetNotifier()
    bddsNotifierNotice.value = describeBddsNotifierRun(result)
      || 'Прогон завершён.'
  } catch (e) {
    bddsNotifierNotice.value = describeBddsError(e).title
  } finally {
    isRunningBddsNotifier.value = false
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

  const [configResult, employeesResult, companiesResult, templatesResult] = await Promise.allSettled([
    apiStore.getConfiguration(),
    apiStore.getFilterEmployees(),
    apiStore.getMyCompanies(),
    // Шаблоны тянем вместе с остальным, но их отказ закрывает только свой
    // блок: настройку шаблона при недоступном генераторе документов менять
    // нельзя, а всё остальное — можно.
    //
    // Не-админу список не нужен: сохранить настройку он всё равно не может,
    // а ручка закрыта тем же гейтом, что выставление, и ответила бы ему 403
    // — жалобой на права, которых он не запрашивал.
    userStore.isAdmin ? apiStore.getBillingTemplates() : Promise.resolve(null),
  ])

  if (configResult.status !== 'fulfilled') {
    billingSettingsError.value = 'Не удалось загрузить настройки приложения с сервера. Остальные разделы работают.'
    return
  }

  configuration.value = configResult.value || {}
  billingSettings.value = readBillingSettings(configuration.value)
  savedBillingSettings.value = readBillingSettings(configuration.value)
  bddsSettings.value = readBddsSettings(configuration.value)
  savedBddsSettings.value = readBddsSettings(configuration.value)
  employeeOptions.value = employeesResult.status === 'fulfilled' ? employeesResult.value : []

  // Отказ справочника юрлиц НЕ закрывает блок: остальные настройки менять
  // можно, а сохранённое юрлицо мы всё равно покажем — по названию из
  // конфигурации.
  if (companiesResult.status === 'fulfilled') {
    myCompanies.value = (companiesResult.value.companies || [])
      .map(item => ({ id: String(item.id), name: String(item.name) }))
    myCompaniesFailed.value = Boolean(companiesResult.value.failed)
  } else {
    myCompanies.value = []
    myCompaniesFailed.value = true
  }

  if (!userStore.isAdmin) {
    templatesSkipped.value = true
  } else if (templatesResult.status === 'fulfilled') {
    templates.value = parseBillingTemplates(templatesResult.value)
    templatesFailed.value = false
    templatesError.value = ''
  } else {
    templates.value = []
    templatesFailed.value = true
    // Текст берём разобранным: сырое сообщение ofetch выглядит как
    // «[GET] "/api/billing/templates": 502» и ничего не объясняет.
    templatesError.value = describeBillingError(templatesResult.reason).text
  }

  templatesReady.value = true
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
