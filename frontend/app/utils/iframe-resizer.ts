
/**
 * Utilities for interacting with the parent Bitrix24 iframe/window.
 * Used to overcome iframe limitations (clipping modals).
 */

export function requestIframeResize(height: number | string) {
    if (window.parent && window.parent !== window) {
        console.log(`[IframeResizer] Requesting resize to ${height}`)
        window.parent.postMessage({
            action: 'resizeIframe',
            height: typeof height === 'number' ? `${height}px` : height,
            app: 'b24-app' // Identifier for the parent to filter
        }, '*')
    }
}

export function requestIframeFullHeight() {
    requestIframeResize('100vh')
}

export function requestIframeAutoHeight() {
    // Attempt to reset to content height
    const height = document.body.scrollHeight
    requestIframeResize(height)
}
