<script setup lang="ts">
import { onMounted } from 'vue'

definePageMeta({ layout: false })

onMounted(() => {
    (window as any).doInstall = function() {
        const btn = document.getElementById('install-btn') as HTMLButtonElement | null
        const content = document.getElementById('install-content')
        const success = document.getElementById('install-success')
        const errorDiv = document.getElementById('install-error')
        const errorText = document.getElementById('error-text')

        if (btn) {
            btn.disabled = true
            btn.textContent = 'Установка...'
        }
        if (errorDiv) errorDiv.style.display = 'none'

        if (typeof (window as any).BX24 === 'undefined') {
            if (errorDiv) errorDiv.style.display = 'block'
            if (errorText) errorText.textContent = 'BX24 SDK не загружен. Откройте приложение из Битрикс24.'
            if (btn) { btn.disabled = false; btn.textContent = 'Установить встройку' }
            return
        }

        ;(window as any).BX24.init(function() {
            const currentUrl = window.location.href
            const baseUrl = currentUrl.substring(0, currentUrl.lastIndexOf('/'))
            const handlerUrl = baseUrl + '/embedded'

            ;(window as any).BX24.callMethod('placement.bind', {
                PLACEMENT: 'TASK_VIEW_TAB',
                HANDLER: handlerUrl,
                TITLE: 'Учет трудозатрат',
                DESCRIPTION: 'Встройка для учета времени по задачам'
            }, function(result: any) {
                if (result.error()) {
                    if (errorDiv) errorDiv.style.display = 'block'
                    if (errorText) errorText.textContent = 'Ошибка: ' + result.error().ex.error_description
                    if (btn) { btn.disabled = false; btn.textContent = 'Установить встройку' }
                } else {
                    if (content) content.style.display = 'none'
                    if (success) success.style.display = 'block'
                    setTimeout(function() {
                        ;(window as any).BX24.installFinish()
                    }, 2000)
                }
            })
        })
    }
})
</script>

<template>
<div class="install-page">
    <div class="install-card">
        <div class="install-header">
            <div class="install-icon">
                <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>
            </div>
            <h1 class="install-title">Учет трудозатрат</h1>
            <p class="install-subtitle">Установка встройки в карточку задачи</p>
        </div>

        <div id="install-content">
            <div class="info-box">
                <h2 class="info-title">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                    Что будет установлено?
                </h2>
                <ul class="info-list">
                    <li>
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        <span>Вкладка «Учет трудозатрат» в карточке каждой задачи</span>
                    </li>
                    <li>
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        <span>Иерархическое отображение задач и подзадач</span>
                    </li>
                    <li>
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        <span>Возможность редактировать записи времени без попапов</span>
                    </li>
                    <li>
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        <span>Функционал разделения записей и расчета стоимости</span>
                    </li>
                </ul>
            </div>

            <button id="install-btn" class="install-btn" onclick="doInstall()">
                <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Установить встройку
            </button>
        </div>

        <div id="install-success" style="display:none;">
            <div class="success-icon">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            </div>
            <h2 class="success-title">Установка завершена!</h2>
            <p class="success-text">Теперь вы можете открыть любую задачу и увидеть новую вкладку</p>
        </div>

        <div id="install-error" style="display:none;">
            <div class="error-box">
                <h3 class="error-title">Ошибка</h3>
                <p id="error-text" class="error-text"></p>
                <button class="retry-btn" onclick="doInstall()">Попробовать снова</button>
            </div>
        </div>
    </div>
</div>
</template>

<style scoped>
* { box-sizing: border-box; margin: 0; padding: 0; }

.install-page {
    width: 100%;
    min-height: 100vh;
    background: linear-gradient(135deg, #eff6ff 0%, #e0e7ff 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.install-card {
    background: #fff;
    border-radius: 16px;
    box-shadow: 0 20px 60px rgba(0,0,0,.1), 0 1px 3px rgba(0,0,0,.06);
    max-width: 560px;
    width: 100%;
    padding: 40px;
}

.install-header {
    text-align: center;
    margin-bottom: 32px;
}

.install-icon {
    width: 72px;
    height: 72px;
    background: #2563eb;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 16px;
}

.install-title {
    font-size: 28px;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 6px;
}

.install-subtitle {
    font-size: 15px;
    color: #64748b;
}

.info-box {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
}

.info-title {
    font-size: 16px;
    font-weight: 700;
    color: #1e3a5f;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
}

.info-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.info-list li {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    font-size: 14px;
    color: #1e40af;
    line-height: 1.5;
}

.info-list li svg {
    flex-shrink: 0;
    margin-top: 1px;
}

.install-btn {
    width: 100%;
    padding: 16px;
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 12px;
    font-size: 17px;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    transition: background .2s;
    box-shadow: 0 4px 14px rgba(37,99,235,.3);
}

.install-btn:hover { background: #1d4ed8; }
.install-btn:disabled {
    background: #94a3b8;
    cursor: not-allowed;
    box-shadow: none;
}

.success-icon { text-align: center; margin-bottom: 16px; }
.success-title {
    text-align: center;
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 8px;
}
.success-text {
    text-align: center;
    font-size: 14px;
    color: #64748b;
}

.error-box {
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 12px;
    padding: 24px;
}
.error-title {
    font-size: 16px;
    font-weight: 700;
    color: #991b1b;
    margin-bottom: 8px;
}
.error-text {
    font-size: 14px;
    color: #b91c1c;
    margin-bottom: 16px;
}
.retry-btn {
    width: 100%;
    padding: 10px;
    background: #fff;
    border: 1px solid #fca5a5;
    color: #b91c1c;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
}
.retry-btn:hover { background: #fef2f2; }
</style>


