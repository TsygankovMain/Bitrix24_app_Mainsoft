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
 * 'skipped' и 'ambiguous' — НЕ ошибки. 'skipped' значит, что предыдущий шаг
 * не дал идентификатора и этот шаг осознанно не выполнялся; 'ambiguous'
 * значит, что нашлось несколько совпадений и приложение отказалось выбирать
 * за пользователя. Показывать любой из них как 'error' — пугать человека
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
