/**
 * Чтение срока годности JWT на клиенте.
 *
 * Подпись здесь намеренно НЕ проверяется: она проверяется бэкендом на каждом
 * запросе, а фронту нужен единственный факт — когда токен протухнет, чтобы не
 * дёргать /api/getToken на каждой навигации. Любая проблема разбора трактуется
 * как «токен просрочен»: поведение деградирует в прежнее (получить заново),
 * а не в «ходить с мёртвым токеном».
 */

/** Запас перед истечением: обновляем токен заранее, а не в последнюю секунду. */
export const TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1000

function decodeBase64Url(value: string): string | null {
  try {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
    if (typeof atob === 'function') {
      return atob(padded)
    }
    // Node (юнит-тесты): atob есть с 16.x, но Buffer надёжнее как запасной путь.
    return Buffer.from(padded, 'base64').toString('binary')
  } catch {
    return null
  }
}

/**
 * Возвращает момент истечения токена в мс epoch, либо 0, если срок прочитать
 * не удалось (пустая строка, не-JWT, битый base64, нет поля `exp`).
 */
export function readJwtExpiryMs(token: string): number {
  if (!token) {
    return 0
  }

  const parts = token.split('.')
  if (parts.length !== 3 || !parts[1]) {
    return 0
  }

  const decoded = decodeBase64Url(parts[1])
  if (decoded === null) {
    return 0
  }

  try {
    const payload = JSON.parse(decoded) as { exp?: unknown }
    return typeof payload.exp === 'number' && Number.isFinite(payload.exp)
      ? payload.exp * 1000
      : 0
  } catch {
    return 0
  }
}

/**
 * Токен ещё можно использовать, не запрашивая новый.
 *
 * @param expiresAtMs момент истечения (из {@link readJwtExpiryMs})
 * @param nowMs текущее время
 * @param marginMs запас перед истечением
 */
export function isJwtFresh(
  expiresAtMs: number,
  nowMs: number,
  marginMs: number = TOKEN_REFRESH_MARGIN_MS
): boolean {
  if (!expiresAtMs) {
    return false
  }
  return nowMs < expiresAtMs - marginMs
}
