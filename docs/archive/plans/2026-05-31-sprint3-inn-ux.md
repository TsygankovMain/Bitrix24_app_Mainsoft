# Спринт 3 — ИНН-UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Реализация — Haiku-агентами под ревью.

**Goal:** Добавить настройку «Незаполненные проекты», окно заполнения/замены ИНН на проект целиком, переиспользуемый прогресс-оверлей с маскотом 🦫, сворачивание групп и убрать дублирующие кнопки.

**Architecture:** Бэк — расширяем `inn_backfill_service` (резолв элементов проекта + health-проверка проектов) и добавляем 2 endpoint'а. Фронт — новые `ProgressOverlay.vue`, `InnAssignModal.vue`, страница настроек, доработка `InnBackfillPanel.vue` и `raw-data.client.vue`. Замена ИНН: бэк резолвит список карточек проекта (с учётом overwrite), фронт пишет существующим чанковым `applyInnBackfill` под прогресс-оверлеем.

**Tech Stack:** Django (Python), Nuxt3/Vue3 + Bitrix24 UI Kit. Тесты бэка: `DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_inn_backfill`. Фронт: `npx nuxt prepare` + `npm run lint`.

---

## File Structure

**Бэк (`backends/python/api/main/`):**
- `inn_backfill_service.py` — +`project_items(...)` (резолв элементов проекта для простановки/замены), +`projects_health(...)` (незаполненные проекты).
- `views.py` — +`inn_backfill_project_items` (POST), +`projects_health` (GET); регистрация в `__all__`.
- `urls.py` — 2 роута.
- `tests_inn_backfill.py` — тесты на `project_items` и `projects_health`.

**Фронт (`frontend/app/`):**
- `components/common/ProgressOverlay.vue` — НОВЫЙ, переиспользуемый оверлей с бобром.
- `components/reports/InnAssignModal.vue` — НОВЫЙ, окно заполнения/замены ИНН на проект.
- `pages/settings/projects-health.client.vue` — НОВАЯ страница.
- `components/reports/InnBackfillPanel.vue` — сворачивание групп, открытие модалки, прогресс-оверлей.
- `pages/reports/raw-data.client.vue` — убрать дубли кнопок, прогресс-оверлей на синк/экспорт.
- `pages/settings/index.client.vue` — ссылка на «Незаполненные проекты».
- `stores/api.ts` — +`resolveInnProjectItems`, +`getProjectsHealth`.
- `types/inn.ts` — +типы.

---

## Task 1: Бэк — `project_items` (резолв карточек проекта для простановки/замены)

**Files:**
- Modify: `backends/python/api/main/inn_backfill_service.py`
- Test: `backends/python/api/main/tests_inn_backfill.py`

- [ ] **Step 1: Написать падающий тест** (добавить в класс `ScanTests`, использует существующие `self.card`, `self._service()`, `FakeClient`):

```python
@mock.patch("main.inn_backfill_service.get_project_card_queryset")
def test_project_items_blank_only_vs_overwrite(self, m_qs):
    m_qs.return_value = [self.card]  # project_id="G1", project_item_id="100"
    svc = self._service()
    svc.items = [
        {"id": 1, "UF_PITEM": "100", "UF_OUR": "", "UF_CLIENT": ""},          # оба пусты
        {"id": 2, "UF_PITEM": "100", "UF_OUR": "OLD", "UF_CLIENT": "OLD"},     # оба заполнены
        {"id": 3, "UF_PITEM": "999", "UF_OUR": "", "UF_CLIENT": ""},           # другой проект
    ]
    # только пустые
    r1 = svc.project_items("G1", "2026-05-01", "2026-05-31", "NEWOUR", "NEWCLI", overwrite=False)
    ids1 = {i["bitrix_id"] for i in r1["items"]}
    self.assertEqual(ids1, {1})  # только карточка с пустыми полями
    # перезаписать всё
    r2 = svc.project_items("G1", "2026-05-01", "2026-05-31", "NEWOUR", "NEWCLI", overwrite=True)
    ids2 = {i["bitrix_id"] for i in r2["items"]}
    self.assertEqual(ids2, {1, 2})  # и пустую, и заполненную; карточка 3 — чужой проект
    by_id = {i["bitrix_id"]: i for i in r2["items"]}
    self.assertEqual(by_id[2]["our_inn"], "NEWOUR")
    self.assertEqual(by_id[2]["client_inn"], "NEWCLI")
```

- [ ] **Step 2: Запустить — упадёт** (`AttributeError: 'InnBackfillService' object has no attribute 'project_items'`).

Run: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_inn_backfill.ScanTests.test_project_items_blank_only_vs_overwrite -v`
Expected: FAIL.

- [ ] **Step 3: Реализация** — добавить метод в класс `InnBackfillService` (после `autofill`):

```python
def project_items(self, project_id: str, date_from: str, date_to: str,
                  our_inn: str, client_inn: str, overwrite: bool) -> Dict[str, Any]:
    """Резолвит карточки проекта за период и формирует items для простановки.
    overwrite=False → только пустые поля; True → перезаписать непустые переданными значениями.
    Запись делает фронт чанками через apply()."""
    our_inn = _clean(our_inn)
    client_inn = _clean(client_inn)
    target = _clean(project_id)
    raw = self._fetch_cards(date_from, date_to)
    by_item, by_id = build_project_lookup(get_project_card_queryset(self.account))
    f_our, f_client = self.field("our_inn"), self.field("client_inn")
    f_pid, f_pitem = self.field("project_id"), self.field("project_item_id")
    items: List[Dict[str, Any]] = []
    for it in raw:
        proj_item = _clean(it.get(f_pitem)) if f_pitem else ""
        proj_id_v = _clean(it.get(f_pid)) if f_pid else ""
        card = by_item.get(proj_item) or by_id.get(proj_id_v)
        card_pid = _clean(getattr(card, "project_id", "")) if card else proj_id_v
        if card_pid != target:
            continue
        our_blank = is_blank(it.get(f_our)) if f_our else True
        client_blank = is_blank(it.get(f_client)) if f_client else True
        entry: Dict[str, Any] = {"bitrix_id": it.get("id") or it.get("ID")}
        if our_inn and (overwrite or our_blank):
            entry["our_inn"] = our_inn
        if client_inn and (overwrite or client_blank):
            entry["client_inn"] = client_inn
        if entry.get("our_inn") or entry.get("client_inn"):
            items.append(entry)
    return {"items": items, "total": len(items)}
```

- [ ] **Step 4: Запустить — пройдёт.**

Run: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_inn_backfill.ScanTests.test_project_items_blank_only_vs_overwrite -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backends/python/api/main/inn_backfill_service.py backends/python/api/main/tests_inn_backfill.py
git commit -m "feat(inn): project_items resolver for fill/replace by project"
```

---

## Task 2: Бэк — `projects_health` (незаполненные проекты)

**Files:**
- Modify: `backends/python/api/main/inn_backfill_service.py`
- Test: `backends/python/api/main/tests_inn_backfill.py`

- [ ] **Step 1: Падающий тест** (новый класс):

```python
class HealthTests(unittest.TestCase):
    @mock.patch("main.inn_backfill_service.get_project_card_queryset")
    def test_projects_health_flags(self, m_qs):
        from types import SimpleNamespace
        m_qs.return_value = [
            SimpleNamespace(project_id="G1", project_name="OK",   company_id="C1", our_legal_entity_id="L1"),
            SimpleNamespace(project_id="G2", project_name="NoCo", company_id="",   our_legal_entity_id="L1"),
            SimpleNamespace(project_id="G3", project_name="NoInn",company_id="C2", our_legal_entity_id="L1"),
        ]
        cfg = {"sp_entity_type_id": 1, "fields_mapping": {"our_inn": "UF_OUR", "client_inn": "UF_CLIENT"}}
        svc = InnBackfillService(FakeClient(), object(), cfg)
        svc._inn_maps = lambda: ({"C1": "7701"}, {"L1": "7709"})  # C2 без ИНН
        res = svc.projects_health()
        names = {r["project_name"]: r for r in res["projects"]}
        self.assertNotIn("OK", names)          # полностью заполнен → не в списке
        self.assertIn("NoCo", names)           # нет компании
        self.assertFalse(names["NoCo"]["has_company"])
        self.assertIn("NoInn", names)          # компания есть, ИНН нет
        self.assertEqual(names["NoInn"]["client_inn"], "")
```

- [ ] **Step 2: Запустить — упадёт.**

Run: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_inn_backfill.HealthTests -v`
Expected: FAIL.

- [ ] **Step 3: Реализация** — метод в `InnBackfillService`:

```python
def projects_health(self) -> Dict[str, Any]:
    """Список проектов, которым не хватает данных для ИНН (нет компании/юрлица или ИНН не резолвится)."""
    companies_inn, legal_inn = self._inn_maps()
    out: List[Dict[str, Any]] = []
    for card in get_project_card_queryset(self.account):
        company_id = _clean(getattr(card, "company_id", ""))
        legal_id = _clean(getattr(card, "our_legal_entity_id", ""))
        client_inn = companies_inn.get(company_id, "")
        our_inn = legal_inn.get(legal_id, "")
        has_company = bool(company_id)
        has_legal = bool(legal_id)
        complete = has_company and has_legal and client_inn and our_inn
        if complete:
            continue
        out.append({
            "project_id": _clean(getattr(card, "project_id", "")),
            "project_name": _clean(getattr(card, "project_name", "")) or "Без названия",
            "has_company": has_company,
            "has_legal_entity": has_legal,
            "client_inn": _clean(client_inn),
            "our_inn": _clean(our_inn),
        })
    return {"projects": out}
```

- [ ] **Step 4: Запустить — пройдёт.**

Run: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_inn_backfill -v`
Expected: PASS (все тесты).

- [ ] **Step 5: Commit**

```bash
git add backends/python/api/main/inn_backfill_service.py backends/python/api/main/tests_inn_backfill.py
git commit -m "feat(inn): projects_health for unfilled projects"
```

---

## Task 3: Бэк — endpoints + роуты

**Files:**
- Modify: `backends/python/api/main/views.py`, `backends/python/api/main/urls.py`

- [ ] **Step 1: Добавить views** (рядом с `inn_backfill_apply`, тот же набор декораторов):

```python
@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("inn_backfill_project_items")
@auth_required
def inn_backfill_project_items(request: AuthorizedRequest):
    """Резолв карточек проекта для простановки/замены ИНН (запись делает фронт чанками)."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    config = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account).get_configuration_sync()
    service = InnBackfillService(request.bitrix24_account.client, request.bitrix24_account, config)
    err = service.ensure_inn_fields()
    if err:
        return JsonResponse({"error": err}, status=400)
    result = service.project_items(
        body.get("project_id", ""), body.get("date_from", ""), body.get("date_to", ""),
        body.get("our_inn", ""), body.get("client_inn", ""), bool(body.get("overwrite")),
    )
    return JsonResponse(result, safe=False)


@xframe_options_exempt
@require_GET
@log_errors("projects_health")
@auth_required
def projects_health(request: AuthorizedRequest):
    """Список незаполненных проектов (нет данных для ИНН)."""
    config = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account).get_configuration_sync()
    service = InnBackfillService(request.bitrix24_account.client, request.bitrix24_account, config)
    return JsonResponse(service.projects_health(), safe=False)
```

- [ ] **Step 2: Зарегистрировать в `__all__`** (после `"inn_backfill_apply",`):

```python
    "inn_backfill_project_items",
    "projects_health",
```

- [ ] **Step 3: Роуты** (`urls.py`, после `inn-backfill/apply`):

```python
    path('api/inn-backfill/project-items', views.inn_backfill_project_items, name='inn_backfill_project_items'),
    path('api/projects-health', views.projects_health, name='projects_health'),
```

- [ ] **Step 4: Проверка** — `py_compile` + `django check`:

Run: `cd backends/python/api && .venv/bin/python -m py_compile main/views.py main/urls.py && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 5: Commit**

```bash
git add backends/python/api/main/views.py backends/python/api/main/urls.py
git commit -m "feat(inn): endpoints project-items + projects-health"
```

---

## Task 4: Фронт — типы и api-методы

**Files:**
- Modify: `frontend/app/types/inn.ts`, `frontend/app/stores/api.ts`

- [ ] **Step 1: Типы** (`types/inn.ts`, добавить):

```ts
export interface InnProjectItemsResult {
  items: InnApplyItem[]
  total: number
}

export interface ProjectHealthRow {
  project_id: string
  project_name: string
  has_company: boolean
  has_legal_entity: boolean
  client_inn: string
  our_inn: string
}

export interface ProjectsHealthResult {
  projects: ProjectHealthRow[]
}
```

- [ ] **Step 2: api-методы** (`stores/api.ts`, рядом с `scanInnBackfill`; импортировать новые типы из `~/types/inn`):

```ts
    const resolveInnProjectItems = async (
      projectId: string, dateFrom: string, dateTo: string,
      ourInn: string, clientInn: string, overwrite: boolean
    ): Promise<InnProjectItemsResult> => {
      return await $api<InnProjectItemsResult>('/api/inn-backfill/project-items', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: JSON.stringify({ project_id: projectId, date_from: dateFrom, date_to: dateTo, our_inn: ourInn, client_inn: clientInn, overwrite })
      })
    }

    const getProjectsHealth = async (): Promise<ProjectsHealthResult> => {
      return await $api<ProjectsHealthResult>('/api/projects-health', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }
```

- [ ] **Step 3: Зарегистрировать в `return {...}` стора** (рядом с `applyInnBackfill,`):

```ts
      resolveInnProjectItems,
      getProjectsHealth,
```

- [ ] **Step 4: Проверка** — `npx nuxt prepare` без ошибок.

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot" | head`
Expected: пусто.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/types/inn.ts frontend/app/stores/api.ts
git commit -m "feat(inn): api methods resolveInnProjectItems + getProjectsHealth"
```

---

## Task 5: Фронт — `ProgressOverlay.vue` (переиспользуемый, бобёр)

**Files:**
- Create: `frontend/app/components/common/ProgressOverlay.vue`

- [ ] **Step 1: Создать компонент** (полностью):

```vue
<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{
  visible: boolean
  title?: string
  done?: number
  total?: number
  label?: string
}>()
const pct = computed(() => {
  if (!props.total || props.total <= 0) return null // неопределённый прогресс
  return Math.min(100, Math.round(((props.done ?? 0) / props.total) * 100))
})
const finished = computed(() => pct.value === 100)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[1000] flex items-center justify-center" style="background:rgba(15,23,42,.45)">
      <div class="bg-white rounded-2xl shadow-xl border border-slate-200 w-[440px] p-6 text-center">
        <div class="text-sm font-semibold text-slate-700">{{ title || 'Идёт операция…' }}</div>
        <div class="text-xs text-slate-400 mt-1 mb-5">Бобёр-Учётчик тащит карточки в 1С</div>
        <div class="relative h-6 rounded-full bg-slate-200 overflow-visible">
          <div
            class="h-full rounded-full transition-all duration-300"
            :style="{ width: (pct ?? 30) + '%', background: 'linear-gradient(90deg,#84cc16,#10b981)' }"
          />
          <div
            class="absolute -top-5 text-2xl"
            :style="{ left: (pct ?? 30) + '%', transform: 'translateX(-50%)', animation: 'bobx 1s ease-in-out infinite' }"
          >{{ finished ? '🦫✅' : '🦫' }}<span v-if="!finished" class="text-xs absolute top-2 left-5">🗂️</span></div>
        </div>
        <div class="flex justify-between text-xs text-slate-500 mt-2">
          <span>{{ label || (total ? `обработано ${done ?? 0} / ${total}` : 'обработка…') }}</span>
          <span v-if="pct !== null" class="font-semibold text-slate-700">{{ pct }}%</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
@keyframes bobx { 0%,100% { transform: translateX(-50%) translateY(0) } 50% { transform: translateX(-50%) translateY(-3px) } }
</style>
```

- [ ] **Step 2: Проверка** — `npx nuxt prepare` без ошибок.

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot" | head`
Expected: пусто.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/components/common/ProgressOverlay.vue
git commit -m "feat(ui): reusable ProgressOverlay with beaver mascot"
```

---

## Task 6: Фронт — `InnAssignModal.vue` (окно заполнения/замены)

**Files:**
- Create: `frontend/app/components/reports/InnAssignModal.vue`

- [ ] **Step 1: Создать компонент.** Props: `visible`, `projectId`, `projectName`, `ourInn`, `clientInn`, `dateFrom`, `dateTo`. Emits: `close`, `applied`. Внутри: редактируемые поля наш/клиент ИНН, radio «Только пустые» / «Перезаписать всё», кнопки. По «Применить»: `resolveInnProjectItems(...)` → затем чанками `applyInnBackfill` (по 25) с `ProgressOverlay`; по завершении `emit('applied', summary)` и `emit('close')`.

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import ProgressOverlay from '../common/ProgressOverlay.vue'
import type { InnApplyItem } from '~/types/inn'

const props = defineProps<{
  visible: boolean
  projectId: string
  projectName: string
  ourInn: string
  clientInn: string
  dateFrom: string
  dateTo: string
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'applied', updated: number): void }>()

const apiStore = useApiStore()
const localOur = ref('')
const localClient = ref('')
const overwrite = ref(false)
const applying = ref(false)
const progress = ref({ done: 0, total: 0 })
const error = ref('')

watch(() => props.visible, (v) => {
  if (v) { localOur.value = props.ourInn || ''; localClient.value = props.clientInn || ''; overwrite.value = false; error.value = '' }
})

async function apply() {
  error.value = ''
  applying.value = true
  try {
    const resolved = await apiStore.resolveInnProjectItems(
      props.projectId, props.dateFrom, props.dateTo, localOur.value.trim(), localClient.value.trim(), overwrite.value
    )
    const items: InnApplyItem[] = resolved.items
    if (!items.length) { error.value = 'Нет карточек для применения'; applying.value = false; return }
    const CHUNK = 25
    let updated = 0
    progress.value = { done: 0, total: items.length }
    for (let i = 0; i < items.length; i += CHUNK) {
      const res = await apiStore.applyInnBackfill(items.slice(i, i + CHUNK))
      updated += res.updated
      progress.value = { done: Math.min(i + CHUNK, items.length), total: items.length }
    }
    emit('applied', updated)
    emit('close')
  } catch (e: any) {
    error.value = e?.data?.error || e?.message || 'Ошибка применения'
  } finally {
    applying.value = false
    progress.value = { done: 0, total: 0 }
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[900] flex items-center justify-center" style="background:rgba(15,23,42,.45)" @click.self="emit('close')">
      <div class="bg-white rounded-2xl shadow-xl w-[460px] p-5">
        <h3 class="text-lg font-bold text-slate-900">Заполнение ИНН · «{{ projectName }}»</h3>
        <p class="text-xs text-slate-500 mt-1 mb-4">Применится ко всем карточкам проекта за период</p>
        <label class="block text-xs font-semibold text-slate-500 mb-1">Наш ИНН</label>
        <input v-model="localOur" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mb-3" placeholder="наш ИНН">
        <label class="block text-xs font-semibold text-slate-500 mb-1">ИНН клиента</label>
        <input v-model="localClient" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mb-4" placeholder="ИНН клиента">
        <div class="rounded-lg bg-slate-50 border border-slate-200 p-3 mb-4 text-sm">
          <label class="flex items-center gap-2 mb-1 text-slate-700"><input type="radio" :value="false" v-model="overwrite"> Только пустые поля</label>
          <label class="flex items-center gap-2 text-rose-700"><input type="radio" :value="true" v-model="overwrite"> <b>Перезаписать всё</b> (смена юр.лица)</label>
        </div>
        <div v-if="error" class="rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700 mb-3">{{ error }}</div>
        <div class="flex justify-end gap-2">
          <B24Button label="Отмена" color="link" @click="emit('close')" />
          <B24Button label="Применить к проекту" color="success" :loading="applying" @click="apply" />
        </div>
      </div>
    </div>
    <ProgressOverlay :visible="applying" title="Простановка ИНН…" :done="progress.done" :total="progress.total" />
  </Teleport>
</template>
```

- [ ] **Step 2: Проверка** — `npx nuxt prepare` без ошибок.

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot" | head`
Expected: пусто.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/components/reports/InnAssignModal.vue
git commit -m "feat(inn): InnAssignModal (fill/replace INN per project)"
```

---

## Task 7: Фронт — `InnBackfillPanel.vue`: сворачивание + кнопка модалки + оверлей

**Files:**
- Modify: `frontend/app/components/reports/InnBackfillPanel.vue`

- [ ] **Step 1: Состояние сворачивания и модалки** (в `<script setup>`):

```ts
import InnAssignModal from './InnAssignModal.vue'
import ProgressOverlay from '../common/ProgressOverlay.vue'

const collapsed = ref<Set<string>>(new Set())
function toggleCollapse(key: string) {
  collapsed.value.has(key) ? collapsed.value.delete(key) : collapsed.value.add(key)
  collapsed.value = new Set(collapsed.value)
}
function isCollapsed(key: string): boolean { return collapsed.value.has(key) }

const modal = ref<{ open: boolean; projectId: string; projectName: string; ourInn: string; clientInn: string }>(
  { open: false, projectId: '', projectName: '', ourInn: '', clientInn: '' }
)
function openAssign(group: InnBackfillGroup) {
  modal.value = { open: true, projectId: group.project_id || '', projectName: group.project_name, ourInn: group.our_inn, clientInn: group.client_inn }
}
function onAssigned() { runScan() }
```
(добавить импорт типа `InnBackfillGroup` к существующим из `~/types/inn`).

- [ ] **Step 2: Шаблон группы** — в строке-заголовке группы добавить chevron (сворачивание) и кнопку «Заполнить / Изменить ИНН →», а строки карточек обернуть в `v-if="!isCollapsed(group.key)"`:

```html
<!-- в строке-заголовке группы, перед названием -->
<span class="cursor-pointer select-none text-lime-700 mr-1" @click="toggleCollapse(group.key)">{{ isCollapsed(group.key) ? '▶' : '▼' }}</span>
<!-- ...название/бейджи... в конце ячейки действий: -->
<button v-if="group.project_id" class="ml-2 text-xs font-semibold text-sky-700 hover:underline" @click="openAssign(group)">Заполнить / Изменить ИНН →</button>
```
И обернуть `<tr v-for="row in group.rows" ...>` в `<template v-if="!isCollapsed(group.key)">...</template>`.

- [ ] **Step 3: Прогресс-оверлей для массовой простановки** — заменить текстовый прогресс в нижней панели на `ProgressOverlay`, и в конце шаблона добавить модалку:

```html
<ProgressOverlay :visible="applying" title="Простановка ИНН…" :done="progress.done" :total="progress.total" />
<InnAssignModal
  :visible="modal.open" :project-id="modal.projectId" :project-name="modal.projectName"
  :our-inn="modal.ourInn" :client-inn="modal.clientInn" :date-from="dateFrom" :date-to="dateTo"
  @close="modal.open = false" @applied="onAssigned"
/>
```

- [ ] **Step 4: Проверка** — `npx nuxt prepare` без ошибок; eslint composables/utils чист.

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot" | head`
Expected: пусто.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/components/reports/InnBackfillPanel.vue
git commit -m "feat(inn): collapsible groups, per-project assign modal, progress overlay"
```

---

## Task 8: Фронт — убрать дубли кнопок + оверлей на синк/экспорт (`raw-data`)

**Files:**
- Modify: `frontend/app/pages/reports/raw-data.client.vue`

- [ ] **Step 1: Кнопки шапки — только на вкладке «Выгрузка».** Обернуть в шапке `B24Card` блок с «Синхронизировать с Б24»/«Обновить»:

```html
<div v-if="activeTab === 'export'" class="flex gap-2 items-center">
  <B24Button label="Синхронизировать с Б24" @click="handleSync" :loading="isSyncing" color="success" class="mr-2" />
  <B24Button label="Обновить" @click="() => fetchTimesheetList(itemsPage)" loading-auto />
</div>
```

- [ ] **Step 2: Прогресс-оверлей на синхронизацию/экспорт.** Импортировать `ProgressOverlay`, добавить в конец шаблона (неопределённый прогресс — без total):

```html
<ProgressOverlay :visible="isSyncing" title="Синхронизация с Bitrix24…" />
<ProgressOverlay :visible="isExporting" title="Формирование Excel…" />
```
(`import ProgressOverlay from '../../components/common/ProgressOverlay.vue'` в `<script setup>`.)

- [ ] **Step 3: Проверка** — `npx nuxt prepare`.

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot" | head`
Expected: пусто.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/pages/reports/raw-data.client.vue
git commit -m "fix(ui): dedup tab buttons + progress overlay on sync/export"
```

---

## Task 9: Фронт — страница настроек «Незаполненные проекты»

**Files:**
- Create: `frontend/app/pages/settings/projects-health.client.vue`
- Modify: `frontend/app/pages/settings/index.client.vue` (ссылка/кнопка перехода)

- [ ] **Step 1: Страница** — таблица в стиле отчётов (классы `ms-*`), загрузка `apiStore.getProjectsHealth()` в `onMounted`. Колонки: Проект · Клиент · Наше юр.лицо · ИНН клиента · Наш ИНН · «Открыть проект». Подсветка: `has_company===false` / `has_legal_entity===false` → красный бейдж «не указано»; есть юрлицо но `client_inn===''`/`our_inn===''` → жёлтый «нет в реквизитах»; иначе зелёный ИНН. «Открыть проект» → `$router.push('/projects?project=' + row.project_id)` (см. как открывается доска в `pages/projects/index.client.vue`; если параметр иной — подставить актуальный).

Структуру брать с `pages/reports/raw-data.client.vue` (обёртка `ms-page-shell`/`B24Card`) и `InnBackfillPanel` (таблица/бейджи). Загрузка с JWT уже в `apiStore`.

- [ ] **Step 2: Ссылка в настройках** — в `pages/settings/index.client.vue` добавить пункт/кнопку «Незаполненные проекты» → `$router.push('/settings/projects-health')`. (Найти блок навигации настроек и добавить по образцу существующих пунктов.)

- [ ] **Step 3: Проверка** — `npx nuxt prepare`.

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot" | head`
Expected: пусто.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/pages/settings/projects-health.client.vue frontend/app/pages/settings/index.client.vue
git commit -m "feat(settings): unfilled projects (INN readiness) page"
```

---

## Task 10: Верификация и документация

**Files:**
- Modify: `docs/CHANGELOG.md`, `docs/RELEASES.md`, `docs/BACKLOG.md` (вычеркнуть прогресс-бар), `docs/architecture/feature-map.md`

- [ ] **Step 1: Прогон всех тестов бэка.**

Run: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_inn_backfill -v && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python manage.py check`
Expected: все тесты PASS, `System check identified no issues`.

- [ ] **Step 2: Прогон фронта.**

Run: `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot|fail"; npm run lint 2>&1 | grep -E "reportFormat|useProjectTaskLabel|ProgressOverlay|InnAssign" || echo "мои файлы чисты"`
Expected: без ошибок в новых файлах.

- [ ] **Step 3: Записи в доках.** Добавить в `CHANGELOG.md` (Спринт 3), `RELEASES.md` (пользовательский релиз), вычеркнуть «прогресс-бар» из `BACKLOG.md`, дополнить `architecture/feature-map.md` (ИНН: модалка/health/overlay).

- [ ] **Step 4: e2e на проде (вручную пользователем)** — по разделу «Верификация» спека: настройки/незаполненные, сворачивание, модалка (пустые/перезапись, проверить в Bitrix), оверлей с бобром, отсутствие дублей кнопок.

- [ ] **Step 5: Commit**

```bash
git add docs/
git commit -m "docs: sprint 3 changelog/releases/feature-map"
```

---

## Self-Review (выполнено)
- **Покрытие спека:** Ф1 (health) → Task 2,3,9; Ф2 (сворачивание/окно/замена) → Task 1,3,6,7; Ф3 (оверлей+бобёр) → Task 5,7,8; Ф4 (дубли кнопок) → Task 8. ✔
- **Плейсхолдеры:** код приведён для бэка и ключевых компонентов; для страницы настроек (Task 9) дан контракт + образцы-источники (Vue-страница по образцу существующих — допустимо для агента-исполнителя).
- **Согласованность типов:** `InnApplyItem` (из Спринта 2) переиспользуется; новые `InnProjectItemsResult`/`ProjectHealthRow`/`ProjectsHealthResult` определены в Task 4 и используются в Task 6/9. Методы `resolveInnProjectItems`/`getProjectsHealth`/`project_items`/`projects_health` — единые имена во всех задачах. ✔
