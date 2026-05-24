/**
 * Phiên bản app — luôn lấy từ /api/version (version.py trong exe, không đọc config).
 */
window.APP_VERSION = '';

async function loadAppVersion() {
    if (window.APP_VERSION) {
        applyAppVersionToDom(window.APP_VERSION);
        return window.APP_VERSION;
    }
    try {
        const res = await fetch('/api/version');
        if (!res.ok) {
            throw new Error('HTTP ' + res.status);
        }
        const data = await res.json();
        const raw = String(data.version || '').trim();
        window.APP_VERSION = raw;
        applyAppVersionToDom(raw);
        return raw;
    } catch (err) {
        console.error('[Version] Failed to load /api/version:', err);
        applyAppVersionToDom('');
        return '';
    }
}

function applyAppVersionToDom(versionStr) {
    const raw = String(versionStr || '').trim();
    const display = raw
        ? (raw.toLowerCase().startsWith('v') ? raw : `v${raw}`)
        : '—';

    document.querySelectorAll('.app-version').forEach((el) => {
        el.textContent = display;
    });

    const appVersionEl = document.getElementById('app-version');
    if (appVersionEl) {
        appVersionEl.textContent = display;
    }
}
