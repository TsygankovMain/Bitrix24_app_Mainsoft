
/**
 * Utilities for interacting with the parent Bitrix24 iframe/window.
 * Uses official BX24 SDK methods when available.
 */

export function requestIframeResize(height: number) {
    // @ts-ignore
    if (typeof window.BX24 !== 'undefined') {
        try {
            // Official way: BX24.resizeWindow(width, height, callback)
            // We only care about height, keeping width auto/current?
            // Actually BX24.resizeWindow expects both. 
            // But often BX24.fitWindow() is better for auto-sizing.

            // If explicit height is given:
            // @ts-ignore
            window.BX24.resizeWindow(window.innerWidth, height)
            return
        } catch (e) {
            console.error('[IframeResizer] BX24.resizeWindow failed', e)
        }
    }

    // Fallback for custom environments or local dev
    if (window.parent && window.parent !== window) {
        console.log(`[IframeResizer] Requesting resize to ${height} via postMessage`)
        window.parent.postMessage({
            action: 'resizeIframe',
            height: `${height}px`,
            app: 'b24-app' // Identifier for the parent to filter
        }, '*')
    }
}

export function requestIframeFullHeight() {
    // For full height, we might try a large number or 100vh logic
    // BX24 resizeWindow takes pixels. 
    // Let's try to set it to a large enough value or use 100vh equivalent in pixels if possible.
    // Since we can't know parent viewport size reliably, we assume a reasonable max or rely on fitWindow if content is large.

    // However, the intent of "Full Height" in our context was to expand iframe to show modal.
    // A modal is usually as tall as the viewport.
    // Let's request a safe large height, e.g. 1500px, or try fitWindow if content expanded.

    const docHeight = document.documentElement.scrollHeight
    const modalHeight = 800 // Approximate modal height
    const target = Math.max(docHeight, modalHeight)

    requestIframeResize(target)
}

export function requestIframeAutoHeight() {
    // @ts-ignore
    if (typeof window.BX24 !== 'undefined') {
        // @ts-ignore
        window.BX24.fitWindow();
        return;
    }

    const height = document.body.scrollHeight
    requestIframeResize(height)
}
