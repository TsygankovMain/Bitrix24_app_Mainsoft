import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readJwtExpiryMs, isJwtFresh, TOKEN_REFRESH_MARGIN_MS } from '../app/utils/jwt'

function makeToken(payload: object): string {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value))
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(payload)}.signature`
}

test('readJwtExpiryMs берёт exp и переводит секунды в миллисекунды', () => {
  const exp = 1_800_000_000
  assert.equal(readJwtExpiryMs(makeToken({ exp })), exp * 1000)
})

test('readJwtExpiryMs разбирает base64url с символами - и _', () => {
  // Подбираем payload так, чтобы в base64 попали символы, требующие url-алфавита.
  const token = makeToken({ exp: 1_800_000_000, sub: 'a?b>c~dÿ' })
  assert.equal(readJwtExpiryMs(token), 1_800_000_000_000)
})

test('readJwtExpiryMs возвращает 0 на непригодном входе', () => {
  assert.equal(readJwtExpiryMs(''), 0)
  assert.equal(readJwtExpiryMs('не-jwt'), 0)
  assert.equal(readJwtExpiryMs('only.two'), 0)
  assert.equal(readJwtExpiryMs('a.!!!непарсится!!!.c'), 0)
  assert.equal(readJwtExpiryMs(makeToken({ nbf: 1 })), 0, 'нет поля exp')
  assert.equal(readJwtExpiryMs(makeToken({ exp: 'скоро' })), 0, 'exp не число')
})

test('isJwtFresh: свежий токен переиспользуется', () => {
  const now = 1_000_000_000_000
  const expiresAt = now + 60 * 60 * 1000
  assert.equal(isJwtFresh(expiresAt, now), true)
})

test('isJwtFresh: внутри запаса токен считается протухшим и будет обновлён', () => {
  const now = 1_000_000_000_000
  const expiresAt = now + TOKEN_REFRESH_MARGIN_MS - 1
  assert.equal(isJwtFresh(expiresAt, now), false)
})

test('isJwtFresh: ровно на границе запаса — обновляем', () => {
  const now = 1_000_000_000_000
  assert.equal(isJwtFresh(now + TOKEN_REFRESH_MARGIN_MS, now), false)
})

test('isJwtFresh: истёкший и нечитаемый срок дают false', () => {
  const now = 1_000_000_000_000
  assert.equal(isJwtFresh(now - 1, now), false)
  assert.equal(isJwtFresh(0, now), false, 'срок прочитать не удалось')
})
