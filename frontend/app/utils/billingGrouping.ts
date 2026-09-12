/**
 * Признак, по которому собраны строки счёта, — словами.
 *
 * Мастер обязан подписать таблицу предпросмотра: «одна строка на задачу», а
 * не оставлять человека угадывать признак по самим строкам. Цена ошибки тут
 * не косметическая — именно из-за неё в счёт клиенту НУОЛАБ ушло
 * наименование работ «НУОЛАБ»: строки собирались по проектам, карточка
 * проекта названа по клиенту, и в предпросмотре это выглядело как нормальный
 * текст.
 *
 * Функции чистые и живут отдельно от формы фильтра: их проверяет node:test, а
 * `.vue` он не резолвит.
 */

import { BILLING_GROUPING_OPTIONS } from './billingFilter'
import { normalizeBillingTaskLevel } from './billingLineTemplate'
import type { BillingTaskLevel } from './billingLineTemplate'
import type { BillingGrouping } from '~/types/billing'

/**
 * Откуда взялся вариант наполнения показанного документа.
 *
 * Значения серверные (billing_service.GROUPING_FROM_*). Мастер обязан
 * показать источник: «строки собраны по задачам» без объяснения, кто так
 * решил, оставляет человека в догадках — править настройку портала или
 * достаточно переключить вариант здесь.
 */
export type BillingGroupingSource = 'settings' | 'request'

export type BillingGroupingSourceDescription = {
  /** Короткая подпись рядом с вариантом. */
  text: string
  /** Что с этим делать. Пусто, когда объяснять нечего. */
  hint: string
}

export function describeBillingGroupingSource(
  source: unknown
): BillingGroupingSourceDescription {
  const value = String(source ?? '').trim().toLowerCase()

  if (value === 'request') {
    return {
      text: 'вариант выбран в этом мастере',
      hint: 'Выбор действует только для этого счёта. Чтобы он подставлялся сразу, '
        + 'поменяйте вариант по умолчанию в настройках приложения.',
    }
  }

  if (value === 'settings') {
    return {
      text: 'вариант по умолчанию из настроек приложения',
      hint: '',
    }
  }

  // Сервер источника не передал (старый ответ). Врать про настройку
  // приложения нельзя — молчим.
  return { text: '', hint: '' }
}

/** Наименование строки для часов, не привязанных к задаче (константа сервера). */
export const BILLING_NO_TASK_LINE_TITLE = 'Работы без привязки к задаче'

export type BillingGroupingDescription = {
  /** Подпись варианта: «По задачам». */
  label: string
  /** Одна строка про состав: «одна строка на задачу». */
  summary: string
  /** Что попадёт в наименование работ счёта. */
  hint: string
  /**
   * Как назвать предмет строки в таблице: «Задача», «Проект», «Сотрудник».
   * Пусто у группировки одной строкой — предмета у неё нет.
   */
  subjectLabel: string
}

/**
 * Описание группировки для предпросмотра и для селекта.
 *
 * `taskLevel` учитывается только у группировки по задачам: при остальных
 * уровень задачи ни на что не влияет, и упоминать его значило бы объяснять
 * то, чего не происходит.
 */
export function describeBillingGrouping(
  grouping: BillingGrouping,
  taskLevel: BillingTaskLevel | string = 'task'
): BillingGroupingDescription {
  const label = BILLING_GROUPING_OPTIONS.find(option => option.id === grouping)?.label || 'По задачам'

  if (grouping === 'task') {
    const level = normalizeBillingTaskLevel(taskLevel)

    if (level === 'root') {
      return {
        label,
        subjectLabel: 'Родительская задача',
        summary: 'одна строка на родительскую задачу',
        hint: 'В наименование работ попадёт название родительской задачи верхнего '
          + 'уровня: подзадачи собраны в одну строку. Уровень задаётся в настройках '
          + 'приложения.',
      }
    }

    return {
      label,
      subjectLabel: 'Задача',
      summary: 'одна строка на задачу',
      hint: `В наименование работ попадёт название задачи. Часы без задачи идут `
        + `отдельной строкой «${BILLING_NO_TASK_LINE_TITLE}» — они не теряются и не `
        + `приписываются чужой задаче.`,
    }
  }

  if (grouping === 'project') {
    return {
      label,
      subjectLabel: 'Проект',
      summary: 'одна строка на проект',
      hint: 'В наименование работ попадёт название карточки проекта. Если карточка '
        + 'названа по клиенту, в счёте окажется имя клиента, а не описание работ — '
        + 'для описания работ выберите группировку по задачам.',
    }
  }

  if (grouping === 'employee') {
    return {
      label,
      subjectLabel: 'Сотрудник',
      summary: 'одна строка на сотрудника',
      hint: 'В наименование работ попадут фамилия и имя сотрудника. Описания работ '
        + 'в счёте при этом не будет.',
    }
  }

  return {
    label,
    subjectLabel: '',
    summary: 'весь период одной строкой',
    hint: 'Наименование работ будет одно на весь счёт («Услуги по договору»). '
      + 'Что именно сделано, видно только в детализации.',
  }
}
