/**
 * Человеко-читаемые представления статуса одного из трёх шагов оркестратора
 * кнопки «Создать проект» (компания / проект в Задачах / карточка
 * смарт-процесса, см. frontend/app/types/project-creation.ts).
 *
 * Вынесено в utils, а не в CreateProjectModal.vue: node:test через tsx не
 * резолвит .vue, а разграничение статусов ниже — та самая логика, которую
 * бриф задачи 8 явно требует покрыть тестом до вёрстки.
 *
 * Ключевое требование заказчика (см. бриф, раздел «Семантика ответа»):
 * 'skipped' и 'ambiguous' — НЕ ошибки. 'skipped' значит, что шаг осознанно
 * не выполнялся — чаще всего потому, что предыдущий шаг не дал
 * идентификатора, но не только: карточка (см. ensure_card в
 * project_creation_service.py) возвращает 'skipped' и тогда, когда сам
 * смарт-процесс проектов не настроен на портале, — и в этом случае ЕЩЁ И
 * заполняет error объяснением причины, оставаясь 'skipped', а не становясь
 * 'error' (текст при этом обязан выглядеть нейтрально — см.
 * stepErrorTextClass ниже, финальное ревью «Важное 1»). 'ambiguous' значит,
 * что нашлось несколько совпадений и приложение отказалось выбирать за
 * пользователя. Показывать любой из них как 'error' — пугать человека
 * несуществующей проблемой, поэтому текст и цвет всех пяти статусов
 * специально различны.
 */
import type { ProjectCreationStep } from '~/types/project-creation'

const LABELS: Record<ProjectCreationStep['status'], string> = {
  created: '✓ создано',
  found: '✓ найдено',
  skipped: '— пропущено',
  ambiguous: '⚠ уточните',
  error: '✗ ошибка'
}

/** Неизвестный/повреждённый статус трактуем как 'skipped' (нейтрально), а не
 * как ошибку — по тому же принципу «не пугать человека несуществующей
 * проблемой»: если бэкенд однажды пришлёт статус, которого сегодня нет,
 * интерфейс не должен красить это красным без причины. */
export function stepLabel(step: ProjectCreationStep): string {
  return LABELS[step?.status] ?? '— пропущено'
}

/** Цвет бейджа под тот же статус, тем же приёмом (Record + фоллбэк), что
 * getStageBadgeClass/getBudgetStatusBadgeClass в frontend/app/utils/projectBoard.ts.
 * 'skipped' и 'ambiguous' обязаны визуально отличаться от 'error' не только
 * текстом, но и цветом — иначе беглый взгляд на бейдж читает жёлтый/серый
 * статус как красный. */
const BADGE_CLASSES: Record<ProjectCreationStep['status'], string> = {
  created: 'bg-emerald-100 text-emerald-700',
  found: 'bg-emerald-100 text-emerald-700',
  skipped: 'bg-slate-100 text-slate-500',
  ambiguous: 'bg-amber-100 text-amber-700',
  error: 'bg-rose-100 text-rose-700'
}

export function stepBadgeClass(step: ProjectCreationStep): string {
  return BADGE_CLASSES[step?.status] ?? 'bg-slate-100 text-slate-500'
}

/**
 * Класс текста строки с error шага (см. разметку CreateProjectModal.vue:
 * `<p v-if="result.X.error">Х: {{ result.X.error }}</p>`).
 *
 * Финальное ревью, «Важное 1»: этот текст был жёстко покрашен в тревожный
 * rose-600 одинаково для любого статуса. Верно для 'error', но не для
 * 'skipped' — карточка возвращает 'skipped' ВМЕСТЕ с текстом причины, когда
 * смарт-процесс проектов не настроен (см. докстринг выше и ensure_card в
 * project_creation_service.py: error="Смарт-процесс проектов не настроен —
 * карточка не создана."). Итог был: нейтральный серый бейдж «— пропущено»
 * (см. BADGE_CLASSES.skipped) и сразу под ним тревожная красная строка —
 * бейдж и подпись противоречили друг другу.
 *
 * Тревожным остаётся только текст при статусе 'error' — всё остальное,
 * включая неизвестные/будущие статусы, нейтрально, тем же приёмом «не
 * пугать человека несуществующей проблемой», что и у stepLabel/stepBadgeClass
 * выше (тот же самый Record+fallback подход здесь избыточен: значений
 * всего два, а не пять).
 */
export function stepErrorTextClass(step: ProjectCreationStep): string {
  return step?.status === 'error' ? 'text-xs text-rose-600' : 'text-xs text-slate-500'
}

/**
 * §3 брифа ИНН (.superpowers/sdd/2026-07-28-create-project-button/
 * inn-frontend-brief.md) — ГЛАВНАЯ часть той задачи. Когда шаг company
 * находит компанию по ИНН под ДРУГИМ названием, чем ввёл человек, сервер
 * ЦЕЛЕНАПРАВЛЕННО не собирает готовую фразу: он отдаёт два сырых названия
 * раздельно — `name` (найденное, настоящее название в портале) и
 * `entered_name` (то, что напечатал человек) — см. StepResult.entered_name
 * и докстринг ensure_company в project_creation_service.py. Формулировка
 * текста осознанно оставлена фронту.
 *
 * Молча подменять введённое название на чужое нельзя — тот же класс
 * расхождения, что и Важное 3 финального ревью пары company_id/company_name
 * (см. докстринг companyFieldsForQuery в frontend/app/utils/companySearch.ts):
 * человек ввёл одно название, а проект привяжется к другому, уже
 * существующему в CRM — он обязан увидеть это явно, а не только по факту
 * (например, задним числом на доске проектов).
 *
 * Это ПРЕДУПРЕЖДЕНИЕ, а не ошибка: действие корректное (создание дубля с
 * тем же ИНН на бэкенде и так невозможно, см. ensure_company), но
 * неожиданное для человека. CreateProjectModal.vue показывает текст через
 * ms-panel-warning (тот же нейтрально-предупреждающий класс, что и
 * loadError/unslottedMissing), а не через тревожный rose-* — по аналогии с
 * тем, как stepErrorTextClass выше не красит 'skipped' тревожным цветом.
 *
 * entered_name пуст (null/undefined/пробелы) в подавляющем большинстве
 * случаев — это и есть "расхождения нет", функция возвращает null.
 * Дополнительные защитные проверки (пустое name, entered_name после обрезки
 * пробелов совпало с name) на практике не должны срабатывать — бэкенд сам
 * гарантирует и то, и другое (entered_name пишется, только если строки
 * различаются буквально, а name на статусе 'found' всегда непусто), — но
 * ничего не стоят и не дают двум местам разойтись, если контракт когда-нибудь
 * изменится, вместо того чтобы показать пустое "уже есть под названием «»".
 */
export function companyNameMismatchNotice(step: ProjectCreationStep): string | null {
  const entered = String(step?.entered_name ?? '').trim()
  if (!entered) {
    return null
  }
  const found = String(step?.name ?? '').trim()
  if (!found || found === entered) {
    return null
  }
  return `Компания с таким ИНН уже есть в портале под названием «${found}» — проект будет привязан к ней, а не к «${entered}», как вы ввели.`
}
