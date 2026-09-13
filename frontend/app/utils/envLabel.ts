/**
 * Метка стенда: «DEV_ver2» на дев-сборке, пустая строка на проде.
 *
 * Значение печётся во фронт при сборке (аргумент Docker APP_ENV_LABEL ->
 * NUXT_PUBLIC_ENV_LABEL). Прод на Timeweb собирается без аргумента, поэтому
 * метку не покажет, даже если ветку с этим кодом вольют в боевую.
 */
export function normalizeEnvLabel(raw: unknown): string {
  return String(raw ?? '').trim()
}

export function withEnvLabel(title: string, label: string): string {
  return label ? `[${label}] ${title}` : title
}
