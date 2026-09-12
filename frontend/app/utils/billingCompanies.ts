/**
 * Разбор предупреждения mixed_companies в список клиентов для выбора.
 *
 * Предупреждение «в отборе несколько клиентов» блокирует выставление
 * (контракт, правило 4: один клиент на документ). Само по себе оно ставит
 * человека в тупик: строки показаны, кнопка мертва, а что нажать — неясно.
 * Поэтому список клиентов из предупреждения превращается в кнопки: нажал —
 * клиент подставился в фильтр, предпросмотр перезапустился.
 *
 * Откуда берутся названия. Сервер (billing_service.py::collect) кладёт в
 * предупреждение поле `companies` — пары id/name, где name это
 * `card.company_name or company_id`. Когда в карточке проекта названия нет,
 * сервер честно подставляет id, и на экране это выглядит как «в отборе
 * несколько клиентов: 1758, 1766, 2568». Такой «name» мы за название не
 * считаем и пробуем найти настоящее в том справочнике, который уже есть на
 * экране (выбранный ранее клиент в SearchableSelect). Не нашли — показываем
 * id как есть. Придумывать название по id нельзя: подпись на кнопке, которая
 * подставляет клиента в счёт, обязана быть правдой.
 */

import type { BillingCompanyRef, BillingWarningPayload } from '~/types/billing'

export type BillingCompanyChoice = {
  id: string
  /** Подпись кнопки: название, если оно известно, иначе сам идентификатор. */
  label: string
  /** Название известно (а не подставлен id) — экран может это пометить. */
  named: boolean
}

function cleanId(value: unknown): string {
  return String(value ?? '').trim()
}

/** Справочник «id -> название» из того, что уже загружено на экране. */
function buildNameIndex(
  sources: Array<Array<{ id?: unknown, name?: unknown }> | null | undefined>
): Map<string, string> {
  const index = new Map<string, string>()

  for (const source of sources) {
    if (!Array.isArray(source)) {
      continue
    }

    for (const item of source) {
      const id = cleanId(item?.id)
      const name = cleanId(item?.name)

      if (!id || !name || name === id || index.has(id)) {
        continue
      }

      index.set(id, name)
    }
  }

  return index
}

/**
 * Кандидаты из предупреждения.
 *
 * `companies` — основная форма ответа. `details` сервер дублирует строками, и
 * когда там оказались числовые идентификаторы, они тоже годятся: это ровно тот
 * случай, когда названий у карточек проектов нет. Нечисловой `details` — это
 * названия без идентификаторов, подставить такое в фильтр невозможно, поэтому
 * оно игнорируется, а не превращается в кнопку, которая ничего не найдёт.
 */
function readWarningCompanies(
  warning: BillingWarningPayload | null | undefined
): BillingCompanyRef[] {
  const result: BillingCompanyRef[] = []
  const companies = warning?.companies

  if (Array.isArray(companies)) {
    for (const item of companies) {
      const id = cleanId(item?.id)
      if (id) {
        result.push({ id, name: cleanId(item?.name) })
      }
    }
  }

  if (result.length) {
    return result
  }

  const details = Array.isArray(warning?.details) ? warning.details : []

  for (const item of details) {
    const id = cleanId(item)
    if (id && /^\d+$/.test(id)) {
      result.push({ id, name: '' })
    }
  }

  return result
}

/**
 * Клиенты из блокирующего предупреждения — кнопками.
 *
 * `companies` из ответа preview принимается вторым источником: там тот же
 * список, и если бэкенд перестанет дублировать его внутрь предупреждения,
 * кнопки не исчезнут.
 */
export function extractMixedCompanies(input: {
  warning?: BillingWarningPayload | null
  /** preview.companies — тот же список на верхнем уровне ответа. */
  companies?: BillingCompanyRef[] | null
  /** Справочник экрана: выбранный клиент и всё, что уже подгружено. */
  directory?: Array<{ id?: unknown, name?: unknown }> | null
}): BillingCompanyChoice[] {
  const names = buildNameIndex([
    input.directory,
    Array.isArray(input.companies) ? input.companies : null,
    Array.isArray(input.warning?.companies) ? input.warning?.companies : null,
  ])

  const candidates = readWarningCompanies(input.warning)
  const fallback = Array.isArray(input.companies) ? input.companies : []
  const source = candidates.length ? candidates : fallback

  const seen = new Set<string>()
  const result: BillingCompanyChoice[] = []

  for (const item of source) {
    const id = cleanId(item?.id)
    if (!id || seen.has(id)) {
      continue
    }

    seen.add(id)

    const own = cleanId(item?.name)
    const name = (own && own !== id ? own : '') || names.get(id) || ''

    result.push({ id, label: name || id, named: Boolean(name) })
  }

  return result
}
