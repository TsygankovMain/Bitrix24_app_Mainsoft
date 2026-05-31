import type { ComputedRef, InjectionKey, Ref } from 'vue'

/**
 * Контекст кликабельных меток времени в отчёте «Учет по проектам/задачам».
 * Прокидывается со страницы через provide и потребляется вложенными
 * строками таблицы (ProjectTaskReportEmployeeRow) через inject —
 * без prop-drilling сквозь рекурсивные компоненты.
 */
export interface ProjectTaskLabelContext {
  /** Включён ли клик по метке (настройка + наличие entityTypeId). */
  enabled: ComputedRef<boolean> | Ref<boolean>
  /** Открыть карточку CRM по id элемента смарт-процесса. */
  onClick: (idElem: string | number) => void
}

export const PROJECT_TASK_LABEL_KEY: InjectionKey<ProjectTaskLabelContext> = Symbol('projectTaskLabel')
