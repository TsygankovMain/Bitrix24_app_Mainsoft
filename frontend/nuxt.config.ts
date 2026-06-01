import tailwindcss from '@tailwindcss/vite'
import { contentLocales } from './i18n/i18n.map'

type FsEntryMiddleware = (req: { url?: string }, res: unknown, next: () => void) => void

interface FsEntryDevServer {
  middlewares: {
    stack: Array<{ route: string, handle: FsEntryMiddleware }>
  }
}

const normalizePublicUrl = (rawValue: unknown): string => {
  const raw = String(rawValue || '').trim()
  if (!raw) {
    return ''
  }

  if (raw.startsWith('/')) {
    return raw
  }

  if (/^https?:\/\//i.test(raw)) {
    return raw
  }

  if (raw.startsWith('//')) {
    return `https:${raw}`
  }

  return `https://${raw}`
}

const isDev = process.env.NODE_ENV !== 'production'
const publicAppUrl = normalizePublicUrl(process.env.NUXT_PUBLIC_APP_URL || process.env.VIRTUAL_HOST || '')
const publicApiUrl = normalizePublicUrl(process.env.NUXT_PUBLIC_API_URL || publicAppUrl || '')
const devAllowedHosts = [
  'localhost',
  '127.0.0.1',
  ...String(process.env.NUXT_ALLOWED_HOSTS || '')
    .split(',')
    .map(host => host.trim())
    .filter(Boolean)
]

const mainsoftFsEntryRewrite = {
  name: 'mainsoft-fs-entry-rewrite',
  transformIndexHtml(html: string) {
    return html.replaceAll('/_nuxt/Users/', '/_nuxt/@fs/Users/')
  },
  configureServer(server: FsEntryDevServer) {
    const rewriteFsEntry: FsEntryMiddleware = (req, _res, next) => {
      const url = req.url || ''
      if (url.startsWith('/_nuxt/Users/')) {
        req.url = url.replace('/_nuxt/Users/', '/_nuxt/@fs/Users/')
      }
      next()
    }

    server.middlewares.stack.unshift({
      route: '',
      handle: rewriteFsEntry
    })
  },
}

export default defineNuxtConfig({
  modules: [
    '@bitrix24/b24ui-nuxt',
    '@bitrix24/b24jssdk-nuxt',
    '@nuxt/eslint',
    '@nuxtjs/i18n',
    '@pinia/nuxt'
  ],

  ssr: false,

  devtools: { enabled: false },

  runtimeConfig: {
    /**
     * @memo this will be overwritten from .env or Docker_*
     * @see https://nuxt.com/docs/guide/going-further/runtime-config#example
     */
    public: {
      appUrl: publicAppUrl,
      apiUrl: publicApiUrl
    }
  },

  compatibilityDate: '2025-07-16',

  experimental: {
    asyncEntry: false
  },

  app: {
    head: {
      title: 'Starter',
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200' }
      ],
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' }
      ],
      htmlAttrs: { class: 'light' }
    }
  },

  css: ['~/assets/css/main.css'],

  vite: {
    plugins: [
      ...(isDev ? [mainsoftFsEntryRewrite] : []),
      tailwindcss()
    ],
    build: {
      target: 'es2020', // Change target to support modern destructuring syntax
      minify: true
    },
    server: {
      allowedHosts: devAllowedHosts,
      proxy: {
        '/api': { target: process.env.SERVER_HOST || 'http://api-need_set:8000', changeOrigin: true }
      }
    }
  },

  nitro: {
    devProxy: {
      '/api': { target: process.env.SERVER_HOST || 'http://api-need_set:8000', changeOrigin: true }
    },
  },

  i18n: {
    detectBrowserLanguage: false,
    strategy: 'no_prefix',
    langDir: 'locales',
    locales: contentLocales,
    defaultLocale: 'en'
  }
})
