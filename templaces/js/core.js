async function loadWorkspace(page) {
    const root = document.getElementById('workspace-root');
    if (!root) return;

    const slug = page.replace('.html', '');

    // Ẩn tất cả các tab content hiện có
    const existingContents = root.querySelectorAll('.tab-content-container');
    existingContents.forEach(el => {
        el.style.display = 'none';
    });

    // Kiểm tra xem tab này đã được load chưa
    let targetContent = document.getElementById(`tab-content-${slug}`);
    if (targetContent) {
        // Nếu đã có thì chỉ cần hiện lại
        targetContent.style.display = 'block';
        return;
    }

    // Nếu chưa có thì load mới và append vào root
    try {
        const res = await fetch(`/templaces/html/${page}`);
        if (!res.ok) return;
        const html = await res.text();

        const wrapper = document.createElement('div');
        wrapper.id = `tab-content-${slug}`;
        wrapper.className = 'tab-content-container';
        wrapper.innerHTML = html;
        root.appendChild(wrapper);
    } catch (err) {
        console.error('Không thể tải workspace:', err);
    }
}

async function isAppExeMode() {
    if (typeof window.__appIsExe === 'boolean') {
        return window.__appIsExe;
    }
    try {
        const res = await fetch('/api/version', { cache: 'no-store' });
        const data = await res.json().catch(() => ({}));
        window.__appIsExe = !!(data && data.exe);
    } catch (_) {
        window.__appIsExe = false;
    }
    return window.__appIsExe;
}

function initClientHeartbeat() {
    if (window.__clientHeartbeatStarted) return;
    window.__clientHeartbeatStarted = true;

    const pingOnce = async () => {
        try {
            await fetch('/client_ping', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-store',
                body: JSON.stringify({ ts: Date.now() }),
                keepalive: true,
            });
        } catch (_) {
        }
    };

    pingOnce();
    window.__clientHeartbeatTimer = setInterval(pingOnce, 4000);
}

function initExitAppBindings() {
    const exitBtn = document.getElementById('exitAppBtn');
    if (exitBtn) {
        exitBtn.onclick = async function () {
            try {
                if (window.__shutdownRequested) {
                    return;
                }

                const exeMode = await isAppExeMode();
                const taskIdsNow = (typeof window.getVideoTaskIdsFromUI === 'function') ? window.getVideoTaskIdsFromUI() : [];
                const hasForms = Array.isArray(taskIdsNow) && taskIdsNow.length > 0;

                // Dev (py app.py): chỉ đóng tab UI, server Flask vẫn chạy
                if (!exeMode) {
                    try {
                        if (typeof window.showSuccessOverlay === 'function') {
                            window.showSuccessOverlay('Đã đóng tab UI. Server vẫn chạy — dừng bằng Ctrl+C trong terminal.');
                        }
                    } catch (_) { }
                    try { window.close(); } catch (_) { }
                    return;
                }

                // EXE: không có form/video nào => thoát app
                if (!hasForms) {
                    window.__shutdownRequested = true;
                    try {
                        if (navigator && navigator.sendBeacon) {
                            navigator.sendBeacon('/exit_app', new Blob([JSON.stringify({ action: 'shutdown', task_ids: [] })], { type: 'application/json' }));
                        } else {
                            await fetch('/shutdown', { method: 'POST' });
                        }
                    } catch (_) { }
                    try {
                        window.close();
                    } catch (_) { }
                    return;
                }

                if (typeof window.askExitAppConfirm !== 'function') {
                    return;
                }

                const choice = await window.askExitAppConfirm();
                if (choice === 'cancel') {
                    return;
                }

                // Close tab immediately; let server handle save/discard + shutdown.
                window.__shutdownRequested = true;
                try {
                    const taskIds = (typeof window.getVideoTaskIdsFromUI === 'function') ? window.getVideoTaskIdsFromUI() : [];
                    const action = (choice === 'save') ? 'save' : 'discard';
                    if (navigator && navigator.sendBeacon) {
                        navigator.sendBeacon('/exit_app', new Blob([JSON.stringify({ action, task_ids: taskIds })], { type: 'application/json' }));
                    } else {
                        await fetch('/exit_app', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ action, task_ids: taskIds }),
                            keepalive: true,
                        });
                    }
                } catch (_) { }

                try { window.close(); } catch (_) { }
            } catch (_) {
            }
        };
    }

    if (!window.__exitBeforeUnloadBound) {
        window.__exitBeforeUnloadBound = true;

        // Chỉ cảnh báo khi đang có task; không gọi /exit_app khi F5/đóng tab (tránh tắt py app).
        window.addEventListener('beforeunload', function (e) {
            try {
                if (window.__shutdownRequested) {
                    return undefined;
                }
                const taskIds = (typeof window.getVideoTaskIdsFromUI === 'function') ? window.getVideoTaskIdsFromUI() : [];
                if (Array.isArray(taskIds) && taskIds.length > 0) {
                    e.preventDefault();
                    e.returnValue = '';
                    return '';
                }
            } catch (_) { }
            return undefined;
        });
    }
}

async function loadOverlays() {
    const root = document.getElementById('overlays-root');
    if (!root) return;

    try {
        const res = await fetch('/templaces/html/overlays.html');
        if (!res.ok) return;
        const html = await res.text();
        root.innerHTML = html;
    } catch (err) {
        console.error('Không thể tải overlays:', err);
    }
}

function slugifyTabLabel(label) {
    const map = {
        'à': 'a', 'á': 'a', 'ạ': 'a', 'ả': 'a', 'ã': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ậ': 'a', 'ẩ': 'a', 'ẫ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ặ': 'a', 'ẳ': 'a', 'ẵ': 'a',
        'è': 'e', 'é': 'e', 'ẹ': 'e', 'ẻ': 'e', 'ẽ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ệ': 'e', 'ể': 'e', 'ễ': 'e',
        'ì': 'i', 'í': 'i', 'ị': 'i', 'ỉ': 'i', 'ĩ': 'i',
        'ò': 'o', 'ó': 'o', 'ọ': 'o', 'ỏ': 'o', 'õ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ộ': 'o', 'ổ': 'o', 'ỗ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ợ': 'o', 'ở': 'o', 'ỡ': 'o',
        'ù': 'u', 'ú': 'u', 'ụ': 'u', 'ủ': 'u', 'ũ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ự': 'u', 'ử': 'u', 'ữ': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỵ': 'y', 'ỷ': 'y', 'ỹ': 'y',
        'đ': 'd',
    };

    const normalized = String(label)
        .trim()
        .toLowerCase()
        .split('')
        .map(ch => map[ch] || ch)
        .join('');

    return normalized
        .replace(/[^a-z0-9\s-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');
}


function getActiveWorkspaceSlug() {
    const activeTab = document.querySelector('.horizontal-tabs .tab-item.active');
    return activeTab ? slugifyTabLabel(activeTab.textContent) : '';
}

const MODEL_OPTIONS_IMAGE = ['Grok (X-AI)', 'Veo3 (Google)'];
const MODEL_OPTIONS_VIDEO = ['Grok (X-AI)', 'Grok Chain (X-AI)', 'Veo3 (Google)'];

function updateModelSelectForWorkspace(slug) {
    const modelSelect = document.getElementById('model-select');
    if (!modelSelect) return;

    const workspace = String(slug || getActiveWorkspaceSlug() || '').trim();
    const isVideo = workspace === 'tao-video';
    const options = isVideo ? MODEL_OPTIONS_VIDEO : MODEL_OPTIONS_IMAGE;

    const current = modelSelect.options[modelSelect.selectedIndex]
        ? String(modelSelect.options[modelSelect.selectedIndex].textContent || '').trim()
        : '';
    const preferred = String(
        (window.configData && window.configData.MODEL_AI) || current || 'Grok (X-AI)'
    ).trim();

    modelSelect.innerHTML = '';
    options.forEach((label) => {
        const opt = document.createElement('option');
        opt.textContent = label;
        modelSelect.appendChild(opt);
    });

    let next = preferred;
    if (!options.includes(next)) {
        next = next.toLowerCase().includes('grok') ? 'Grok (X-AI)' : (options[0] || 'Grok (X-AI)');
    }
    setSelectByValueOrText(modelSelect, next);
    toggleGrokDurationVisibility();
}


function initTabBindings() {
    const tabs = document.querySelectorAll('.horizontal-tabs .tab-item');
    if (!tabs || tabs.length === 0) return;

    tabs.forEach(tab => {
        tab.onclick = async function () {
            if (tab.classList.contains('active')) return;

            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            const label = (tab.textContent || '').trim();
            const slug = slugifyTabLabel(label);
            const page = `${slug}.html`;

            const isAlreadyLoaded = document.getElementById(`tab-content-${slug}`) !== null;

            await loadWorkspace(page);

            updateModelSelectForWorkspace(slug);

            // Chỉ chạy init và loadConfig nếu tab chưa từng được load
            if (!isAlreadyLoaded) {
                await loadConfig();
                updateModelSelectForWorkspace(slug);
                initWorkspaceBindings(slug);
            }
        };
    });
}

function initWorkspaceBindings(slug) {
    const inits = window.PageInits || {};
    const initFn = inits[slug];
    if (typeof initFn === 'function') {
        initFn();
    }
}

async function saveToConfig(data) {
    try {
        await fetch('/save_config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
    } catch (err) {
        console.error('Lỗi lưu config:', err);
    }
}


function setSelectByValueOrText(selectEl, desired) {
    try {
        if (!selectEl) return;
        if (desired === undefined || desired === null) return;

        const desiredStr = String(desired);
        const desiredNum = Number(desiredStr);
        const hasNumeric = Number.isFinite(desiredNum) && desiredStr.trim() !== '';

        // 1) Match by option.value
        for (let i = 0; i < selectEl.options.length; i++) {
            if (String(selectEl.options[i].value) === desiredStr) {
                selectEl.selectedIndex = i;
                return;
            }
        }

        // 2) Match by option.textContent contains desired
        for (let i = 0; i < selectEl.options.length; i++) {
            const text = String(selectEl.options[i].textContent || '');
            if (text.toLowerCase().includes(desiredStr.toLowerCase())) {
                selectEl.selectedIndex = i;
                return;
            }
        }

        // 3) Backward-compat: if stored as index
        if (hasNumeric) {
            const idx = Math.max(0, Math.min(selectEl.options.length - 1, Math.floor(desiredNum)));
            selectEl.selectedIndex = idx;
        }
    } catch (e) { }
}


async function loadConfig() {
    try {
        const response = await fetch('/config/config.json');
        if (!response.ok) {
            console.error('Không thể load config.json');
            return;
        }
        const data = await response.json();

        if (typeof loadAppVersion === 'function') {
            await loadAppVersion();
        }

        window.configData = data;

        if (typeof fetchLicenseStatus === 'function') {
            await fetchLicenseStatus();
        }

        // Sidebar model select (UI text may not match MODEL_AI string, so only best-effort)
        const sidebarModelSelect = document.querySelector('#sidebar .group-box select');
        if (sidebarModelSelect) {
            setSelectByValueOrText(sidebarModelSelect, data.MODEL_AI);
        }

        // Model select with ID — options phụ thuộc tab (Grok Chain chỉ ở Tạo video)
        updateModelSelectForWorkspace(getActiveWorkspaceSlug());
        const modelSelect = document.getElementById('model-select');
        if (modelSelect) {
            setSelectByValueOrText(modelSelect, data.MODEL_AI);
            updateModelSelectForWorkspace(getActiveWorkspaceSlug());
        }

        const cloneVideoModelSelect = document.getElementById('cloneVideoModelSelect');
        setSelectByValueOrText(cloneVideoModelSelect, data.cloneVideoModel);

        const cloneVideoApiKey = document.getElementById('cloneVideoApiKey');
        if (cloneVideoApiKey) {
            cloneVideoApiKey.value = data.cloneVideoApiKey || '';
        }
    } catch (error) {
        console.error('Lỗi loading config:', error);
        const versionElements = document.querySelectorAll('.app-version');
        versionElements.forEach(el => el.innerText = 'Error');
    }
}


function setCreditDisplay(html) {
    const creditEls = document.querySelectorAll('.credit-value');
    if (!creditEls || !creditEls.length) return;
    creditEls.forEach((el) => {
        try {
            el.innerHTML = html;
        } catch (_) { }
    });
}

function setCreditDisplayEmpty() {
    setCreditDisplay('—');
}

async function refreshCreditAsync() {
    try {
        const uid = (window.configData && window.configData.ACCOUNT_ID)
            ? String(window.configData.ACCOUNT_ID || '').trim()
            : '';
        if (!uid || uid === 'Nhập User ID') {
            setCreditDisplayEmpty();
            return null;
        }

        const res = await fetch('/api/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            cache: 'no-store',
            body: JSON.stringify({ user_id: uid }),
        });
        const body = await res.json().catch(() => ({}));

        if (!res.ok || body.ok === false) {
            // Nếu lỗi từ server, hiển thị thông báo tài khoản không hợp lệ
            if (body.error && (body.error.toLowerCase().includes('invalid') || body.error.toLowerCase().includes('không tìm thấy'))) {
                showInvalidAccountModal();
            } else if (body.error && body.error.toLowerCase().includes('quota')) {
                showOutOfQuotaModal();
            }            
            setCreditDisplayEmpty();
            return body;
        }

        const count = (body && typeof body.count !== 'undefined') ? body.count : 0;
        const limit = (body && typeof body.limit !== 'undefined') ? body.limit : 0;
        setCreditDisplay(`<i class="fas fa-coins"></i> ${count}/${limit}`);

        // Nếu count = 0, hiển thị thông báo hết lượt
        if (count === 0) {
            showOutOfQuotaModal();
        }

        return body;
    } catch (e) {
        // Lỗi kết nối - có thể hiển thị thông báo mạng
        showNetworkErrorModal();
        setCreditDisplayEmpty();
        return null;
    }
}

try {
    window.openLogToggleModal = openLogToggleModal;
} catch (e) { }

function initLogSettingsBindings() {
    const logBtn = document.getElementById('btn-log-settings');
    if (!logBtn) return;

    logBtn.onclick = function () {
        const modal = document.getElementById('logPasswordModal');
        if (modal) {
            modal.style.display = 'flex';
            const input = document.getElementById('logPasswordInput');
            const error = document.getElementById('logPasswordError');
            if (input) {
                input.value = '';
                setTimeout(() => input.focus(), 100);
            }
            if (error) error.style.display = 'none';
        }
    };

    // Add Enter key handler for password input
    const passwordInput = document.getElementById('logPasswordInput');
    if (passwordInput) {
        passwordInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const verifyBtn = document.getElementById('logPasswordConfirmBtn');
                if (verifyBtn) verifyBtn.click();
            }
        });
    }

    const verifyBtn = document.getElementById('logPasswordConfirmBtn');
    if (verifyBtn) {
        verifyBtn.onclick = async function () {
            const input = document.getElementById('logPasswordInput');
            const error = document.getElementById('logPasswordError');
            if (!input || !error) return;

            const password = input.value.trim();
            if (!password) {
                error.textContent = 'Vui lòng nhập mật khẩu';
                error.style.display = 'block';
                return;
            }

            try {
                const res = await fetch('/api/log/verify_password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });
                const data = await res.json();

                if (data.ok && data.verified) {
                    const pwModal = document.getElementById('logPasswordModal');
                    if (pwModal) pwModal.style.display = 'none';
                    openLogToggleModal();
                } else {
                    error.textContent = 'Mật khẩu không đúng';
                    error.style.display = 'block';
                }
            } catch (err) {
                error.textContent = 'Lỗi kết nối';
                error.style.display = 'block';
            }
        };
    }

    const cancelPwBtn = document.getElementById('logPasswordCancelBtn');
    if (cancelPwBtn) {
        cancelPwBtn.onclick = function () {
            const modal = document.getElementById('logPasswordModal');
            if (modal) modal.style.display = 'none';
        };
    }

    const closeToggleBtn = document.getElementById('logToggleCloseBtn');
    if (closeToggleBtn) {
        closeToggleBtn.onclick = function () {
            const modal = document.getElementById('logToggleModal');
            if (modal) modal.style.display = 'none';
        };
    }

    const toggleCheckbox = document.getElementById('logToggleCheckbox');
    if (toggleCheckbox) {
        toggleCheckbox.onchange = async function () {
            const enabled = this.checked;
            try {
                const res = await fetch('/api/log/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                const data = await res.json();
                if (data.ok) {
                    updateLogStatusDisplay(data.suppress_enabled);
                }
            } catch (err) {
                console.error('Lỗi toggle log:', err);
            }
        };
    }
}

async function openLogToggleModal() {
    const modal = document.getElementById('logToggleModal');
    if (!modal) return;

    try {
        const res = await fetch('/api/log/status');
        const data = await res.json();

        const checkbox = document.getElementById('logToggleCheckbox');
        if (checkbox) {
            checkbox.checked = data.suppress_enabled || false;
        }

        updateLogStatusDisplay(data.suppress_enabled || false);
        modal.style.display = 'flex';
    } catch (err) {
        console.error('Lỗi load log status:', err);
    }
}

function updateLogStatusDisplay(enabled) {
    const statusText = document.getElementById('logStatusText');
    if (statusText) {
        statusText.textContent = enabled ? 'Đang tắt log' : 'Đang bật log';
        statusText.style.color = enabled ? '#f44336' : '#4CAF50';
    }
}

function showSuccessOverlay(message) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.3s ease;
    `;

    const messageBox = document.createElement('div');
    messageBox.style.cssText = `
        background: var(--card-bg, rgba(255,255,255,0.1));
        border: 2px solid var(--accent-color, #4CAF50);
        border-radius: 12px;
        padding: 20px 40px;
        color: var(--text-primary, #fff);
        font-size: 18px;
        font-weight: 600;
        box-shadow: 0 4px 20px rgba(76, 175, 80, 0.3);
        animation: slideUp 0.3s ease;
    `;
    messageBox.textContent = message;

    overlay.appendChild(messageBox);
    document.body.appendChild(overlay);

    setTimeout(() => {
        overlay.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => {
            if (document.body.contains(overlay)) {
                document.body.removeChild(overlay);
            }
        }, 300);
    }, 2000);

    overlay.addEventListener('click', () => {
        overlay.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => {
            if (document.body.contains(overlay)) {
                document.body.removeChild(overlay);
            }
        }, 300);
    });
}

if (!document.getElementById('success-overlay-styles')) {
    const style = document.createElement('style');
    style.id = 'success-overlay-styles';
    style.textContent = `
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
        @keyframes slideUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    `;
    document.head.appendChild(style);
}

function showProcessingOverlay(message) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.3s ease;
    `;

    const messageBox = document.createElement('div');
    messageBox.style.cssText = `
        background: var(--card-bg, rgba(255,255,255,0.1));
        border: 2px solid var(--accent-color, #3498db);
        border-radius: 12px;
        padding: 20px 40px;
        color: var(--text-primary, #fff);
        font-size: 18px;
        font-weight: 600;
        box-shadow: 0 4px 20px rgba(52, 152, 219, 0.3);
        animation: slideUp 0.3s ease;
    `;
    messageBox.textContent = message;

    overlay.appendChild(messageBox);
    document.body.appendChild(overlay);
}


function closePaymentOverlay() {
    const el = document.getElementById('paymentOverlay');
    if (!el) return;
    el.style.display = 'none';
}


function showPaymentOverlay(message) {
    const el = document.getElementById('paymentOverlay');
    if (!el) return;

    const msgEl = document.getElementById('paymentOverlayMessage');
    if (msgEl) {
        msgEl.textContent = message || 'Đã hết lượt. Vui lòng thanh toán để tiếp tục.';
    }

    el.style.display = 'flex';
}

try {
    window.showPaymentOverlay = showPaymentOverlay;
    window.closePaymentOverlay = closePaymentOverlay;
} catch (e) { }

function closeProcessingOverlay() {
    const overlays = document.querySelectorAll('div[style*="position: fixed"]');
    overlays.forEach(overlay => {
        if (overlay.textContent.includes('Đang tạo kịch bản') || overlay.textContent.includes('Đang xử lý')) {
            overlay.style.animation = 'fadeOut 0.3s ease';
            setTimeout(() => {
                if (document.body.contains(overlay)) {
                    document.body.removeChild(overlay);
                }
            }, 300);
        }
    });
}

let pendingDeleteMusic = null;

function deleteSelectedMusic() {
    const musicInput = document.getElementById('musicSelect');
    if (!musicInput) return;

    const fileName = String(musicInput.value || '').trim();
    if (!fileName || fileName.toLowerCase().startsWith('none')) {
        return;
    }

    pendingDeleteMusic = { name: fileName };

    const msgEl = document.getElementById('deleteMusicMessage');
    const btnsEl = document.getElementById('deleteMusicButtons');
    if (msgEl) {
        msgEl.textContent = `Xóa file nhạc "${fileName}"?`;
    }
    if (btnsEl) {
        btnsEl.style.display = 'flex';
    }

    const modal = document.getElementById('deleteMusicModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeDeleteMusicModal() {
    const modal = document.getElementById('deleteMusicModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function confirmDeleteMusic() {
    const musicInput = document.getElementById('musicSelect');
    const musicList = document.getElementById('musicSelectList');
    if (!musicInput || !musicList || !pendingDeleteMusic) return;

    const { name } = pendingDeleteMusic;

    fetch('/deletemusic', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name }),
    })
        .then(res => res.json().then(body => ({ ok: res.ok, body })))
        .then(({ ok, body }) => {
            const msgEl = document.getElementById('deleteMusicMessage');
            const btnsEl = document.getElementById('deleteMusicButtons');

            if (!ok || !body.ok) {
                console.error('Xóa nhạc thất bại:', body.error);
                if (msgEl) {
                    msgEl.textContent = 'Xóa thất bại. Vui lòng thử lại.';
                }
                return;
            }

            try {
                const opts = Array.from(musicList.querySelectorAll('option'));
                opts.forEach((opt) => {
                    const v = String(opt.getAttribute('value') || '').trim();
                    if (v === name) {
                        try { musicList.removeChild(opt); } catch (e) { }
                    }
                });
            } catch (e) { }

            try {
                if (window.__musicUrlByName && window.__musicUrlByName[name]) {
                    delete window.__musicUrlByName[name];
                }
                if (Array.isArray(window.__musicList)) {
                    window.__musicList = window.__musicList.filter((x) => x && String(x.name || '').trim() !== name);
                }
            } catch (e) { }

            try {
                if (String(musicInput.value || '').trim() === name) {
                    musicInput.value = '';
                }
            } catch (e) { }

            if (msgEl) {
                msgEl.textContent = 'Đã xóa file nhạc ✔';
            }
            if (btnsEl) {
                btnsEl.style.display = 'none';
            }

            pendingDeleteMusic = null;

            setTimeout(() => {
                closeDeleteMusicModal();
                if (msgEl) {
                    msgEl.textContent = 'Xóa file nhạc này?';
                }
                if (btnsEl) {
                    btnsEl.style.display = 'flex';
                }
            }, 1500);
        })
        .catch(err => {
            console.error('Lỗi gọi /deletemusic:', err);
        });
}

async function loadMusicList() {
    try {
        const res = await fetch('/listmusic');
        const list = await res.json().catch(() => []);
        const musicList = document.getElementById('musicSelectList');
        if (!musicList) return;

        window.__musicList = Array.isArray(list) ? list : [];
        window.__musicUrlByName = {};
        (window.__musicList || []).forEach((it) => {
            try {
                const n = String(it && it.name ? it.name : '').trim();
                const u = String(it && it.url ? it.url : '').trim();
                if (n) window.__musicUrlByName[n] = u;
            } catch (e) { }
        });

        try {
            musicList.innerHTML = '';
        } catch (e) { }

        const optNone = document.createElement('option');
        optNone.setAttribute('value', 'None (Mặc định)');
        musicList.appendChild(optNone);

        (window.__musicList || []).forEach((item) => {
            const n = String(item && item.name ? item.name : '').trim();
            if (!n) return;
            const opt = document.createElement('option');
            opt.setAttribute('value', n);
            musicList.appendChild(opt);
        });
    } catch (err) {
        console.error('Không load được danh sách nhạc:', err);
    }
}

function initAudioVolumeBindings() {
    const musicSlider = document.getElementById('music-volume-input');
    const videoSlider = document.getElementById('video-audio-volume-input');
    const musicLabel = document.getElementById('music-volume-label');
    const videoLabel = document.getElementById('video-audio-volume-label');

    const sync = () => {
        if (musicSlider && musicLabel) {
            musicLabel.textContent = `${musicSlider.value}%`;
        }
        if (videoSlider && videoLabel) {
            videoLabel.textContent = `${videoSlider.value}%`;
        }
    };

    if (musicSlider) musicSlider.addEventListener('input', sync);
    if (videoSlider) videoSlider.addEventListener('input', sync);
    sync();
}

function initMusicBindings() {
    // Preview music
    const previewBtn = document.querySelector('.btn-preview');
    if (previewBtn) {
        previewBtn.onclick = function () {
            const musicInput = document.getElementById('musicSelect');
            if (!musicInput) return;
            const name = String(musicInput.value || '').trim();
            if (!name || name.toLowerCase().startsWith('none')) return;
            const url = (window.__musicUrlByName && window.__musicUrlByName[name]) ? window.__musicUrlByName[name] : '';
            if (!url) return;
            openAudioOverlay(url, name);
        };
    }

    // Add music
    const addMusicBtn = document.getElementById('addMusicBtn');
    const addMusicInput = document.getElementById('addMusicInput');
    if (addMusicBtn && addMusicInput) {
        addMusicBtn.onclick = function () {
            addMusicInput.click();
        };

        addMusicInput.onchange = async function () {
            if (!this.files || !this.files[0]) return;

            const file = this.files[0];
            const desiredName = await askDesiredMusicName(file.name);
            if (!desiredName) {
                addMusicInput.value = '';
                return;
            }

            const formData = new FormData();
            formData.append('file', file);
            formData.append('desired_name', desiredName);

            fetch('/uploadmusic', {
                method: 'POST',
                body: formData,
            })
                .then(res => res.json().then(body => ({ ok: res.ok, body })))
                .then(({ ok, body }) => {
                    if (!ok || !body.ok) {
                        console.error('Thêm nhạc thất bại:', body.error);
                        return;
                    }

                    const musicSelect = document.getElementById('musicSelect');
                    const musicList = document.getElementById('musicSelectList');
                    if (!musicSelect || !musicList) return;

                    const name = String(body.name || '').trim();
                    const url = String(body.url || '').trim();
                    if (!name) return;

                    try {
                        window.__musicUrlByName = window.__musicUrlByName || {};
                        window.__musicUrlByName[name] = url;
                        window.__musicList = Array.isArray(window.__musicList) ? window.__musicList : [];
                        window.__musicList.push({ name, url });
                    } catch (e) { }

                    const opt = document.createElement('option');
                    opt.setAttribute('value', name);
                    musicList.appendChild(opt);
                    musicSelect.value = name;

                    addMusicInput.value = '';
                })
                .catch(err => {
                    console.error('Lỗi gọi /uploadmusic:', err);
                });
        };
    }
}

function initResultFolderBindings() {
    const resultBtn = document.getElementById('resultFolderBtn');
    const resultLabel = document.getElementById('resultFolderLabel');

    if (!resultBtn || !resultLabel) return;

    try {
        const saved = String(localStorage.getItem('resultFolderPath') || '').trim();
        if (saved) {
            resultLabel.textContent = saved;
        }
    } catch (e) { }

    resultBtn.onclick = async function () {
        try {
            const res = await fetch('/pick_result_folder', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({})
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data || data.ok !== true) {
                const msg = (data && data.error) ? data.error : 'Không thể chọn thư mục';
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay(msg);
                } else {
                    alert(msg);
                }
                return;
            }

            resultLabel.textContent = data.path;
            try {
                localStorage.setItem('resultFolderPath', String(data.path || '').trim());
            } catch (e) { }
        } catch (err) {
            console.error('Lỗi gọi /pick_result_folder:', err);
            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Lỗi kết nối đến server');
            } else {
                alert('Lỗi kết nối đến server');
            }
        }
    };
}

function toggleGrokDurationVisibility() {
    const modelSelect = document.getElementById('model-select');
    const durationContainer = document.getElementById('grok-duration-container');
    const grokChainHint = document.getElementById('grok-chain-hint-container');
    const veo3ImageModelContainer = document.getElementById('veo3-image-model-container');
    const veo3VideoQualityContainer = document.getElementById('veo3-video-quality-container');
    const maxTabsContainer = document.getElementById('max-tabs-container');
    const qualitySelect = document.getElementById('video-quality-select');

    if (!modelSelect || !durationContainer) return;

    const selectedModel = modelSelect.options[modelSelect.selectedIndex].textContent;
    const isGrok = selectedModel && selectedModel.toLowerCase().includes('grok');
    const isGrokChain = selectedModel && selectedModel.toLowerCase().includes('grok chain');
    const isVeo3 = selectedModel && selectedModel.toLowerCase().includes('veo3');

    // Show/hide duration selector (Grok thường + Grok Chain)
    durationContainer.style.display = isGrok ? 'block' : 'none';

    if (grokChainHint) {
        grokChainHint.style.display = isGrokChain ? 'block' : 'none';
    }

    // Show/hide Veo3 model selectors (only for Veo3)
    if (veo3ImageModelContainer) {
        veo3ImageModelContainer.style.display = isVeo3 ? 'block' : 'none';
    }
    if (veo3VideoQualityContainer) {
        veo3VideoQualityContainer.style.display = isVeo3 ? 'block' : 'none';
    }

    // Veo3 và Grok Chain không dùng số tab song song (chạy tuần tự)
    if (maxTabsContainer) {
        maxTabsContainer.style.display = (isVeo3 || isGrokChain) ? 'none' : 'block';
    }

    // Update quality options based on model
    if (qualitySelect) {
        const currentValue = qualitySelect.value;
        qualitySelect.innerHTML = '';

        if (isGrok) {
            // Grok only supports 480p and 720p
            const option720 = document.createElement('option');
            option720.value = '720p';
            option720.textContent = '720p';
            qualitySelect.appendChild(option720);

            const option480 = document.createElement('option');
            option480.value = '480p';
            option480.textContent = '480p';
            qualitySelect.appendChild(option480);

            // Set default to 720p for Grok
            qualitySelect.value = '720p';
        } else if (isVeo3) {
            // Veo3 supports 1080p and 720p
            const option1080 = document.createElement('option');
            option1080.value = '1080p';
            option1080.textContent = '1080p';
            qualitySelect.appendChild(option1080);

            const option720 = document.createElement('option');
            option720.value = '720p';
            option720.textContent = '720p';
            qualitySelect.appendChild(option720);

            // Default to 720p for Veo3
            qualitySelect.value = '720p';
        } else {
            // Other models support 1080p and 720p
            const option1080 = document.createElement('option');
            option1080.value = '1080p';
            option1080.textContent = '1080p';
            qualitySelect.appendChild(option1080);

            const option720 = document.createElement('option');
            option720.value = '720p';
            option720.textContent = '720p';
            qualitySelect.appendChild(option720);

            // Restore previous value if valid, otherwise default to 1080p
            if (currentValue === '1080p' || currentValue === '720p') {
                qualitySelect.value = currentValue;
            } else {
                qualitySelect.value = '1080p';
            }
        }
    }
}

function initSettingsAccountBindings() {
    const settingsBtn = document.getElementById('btn-settings-account');
    const modelSelect = document.getElementById('model-select');

    if (!settingsBtn || !modelSelect) return;

    // Toggle duration visibility when model changes
    modelSelect.onchange = function () {
        toggleGrokDurationVisibility();
        if (typeof window._refreshVideoSceneBlocksIfOpen === 'function') {
            window._refreshVideoSceneBlocksIfOpen();
        }
    };

    settingsBtn.onclick = async function () {
        const selectedModel = modelSelect.options[modelSelect.selectedIndex].textContent;

        try {
            const response = await fetch('/setup_profile', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    model: selectedModel
                })
            });

            const result = await response.json();

            if (response.ok && result.success) {
                showSuccessOverlay('Thiết lập tài khoản thành công!');
            } else {
                showSuccessOverlay('Thiết lập tài khoản thất bại: ' + (result.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Lỗi thiết lập tài khoản:', error);
            showSuccessOverlay('Lỗi kết nối đến server');
        }
    };
}

window.onload = async function () {
    await loadOverlays();
    try { await isAppExeMode(); } catch (_) { }
    initLogSettingsBindings();
    initExitAppBindings();
    initTabBindings();

    // Khởi tạo tab mặc định (Home) mà không xóa nội dung
    const activeTab = document.querySelector('.horizontal-tabs .tab-item.active');
    const defaultSlug = activeTab ? slugifyTabLabel(activeTab.textContent) : 'home';
    await loadWorkspace(`${defaultSlug}.html`);
    updateModelSelectForWorkspace(defaultSlug);

    const savedTheme = localStorage.getItem('selectedTheme');
    if (savedTheme) {
        document.body.classList.add(savedTheme);
    }

    await loadConfig();
    updateModelSelectForWorkspace(getActiveWorkspaceSlug());

    await loadMusicList();
    initMusicBindings();
    initAudioVolumeBindings();

    initResultFolderBindings();
    initSettingsAccountBindings();

    initWorkspaceBindings(defaultSlug);

    initClientHeartbeat();

    try {
        const splash = document.getElementById('startup-splash');
        if (splash) {
            splash.style.display = 'none';
        }
    } catch (_) { }

    // Show intro splash if not already shown this session
    showIntroSplash();

    // Show intro splash if not already shown this session
    showIntroSplash();

    document.addEventListener('keydown', function (e) {
        const userIdSpan = document.getElementById('userId');
        if (!userIdSpan) return;

        if (userIdSpan.contentEditable === 'true' && e.key === 'Enter') {
            e.preventDefault();
            saveUserId(e);
        }

        if (userIdSpan.contentEditable === 'true' && e.key === 'Escape') {
            cancelEdit();
        }
    });
};

// ========== INTRO SPLASH ==========
function showIntroSplash() {
    if (sessionStorage.getItem('introShown')) return;

    const intro = document.getElementById('intro-splash');
    if (!intro) return;

    intro.style.display = 'flex';

    const video = document.getElementById('intro-video');
    if (video) {
        video.currentTime = 0;
        video.play().catch(() => {});

        // Loop video until user clicks
        video.loop = true;
    }

    const skip = () => {
        sessionStorage.setItem('introShown', '1');
        if (intro) intro.style.display = 'none';
        if (video) video.pause();
        document.removeEventListener('click', skip);
        document.removeEventListener('keydown', skip);
    };

    document.addEventListener('click', skip, { once: true });
    document.addEventListener('keydown', skip, { once: true });
}

try { window.showIntroSplash = showIntroSplash; } catch(e) {}

// ========== NOTIFICATION MODALS ==========

// Hiển thị thông báo lỗi
function showErrorModal(message) {
    const modal = document.getElementById('errorModal');
    const msgEl = document.getElementById('errorModalMessage');
    if (modal) {
        if (msgEl) msgEl.textContent = message || 'Đã xảy ra lỗi không xác định.';
        modal.style.display = 'flex';
    }
}

function closeErrorModal() {
    const modal = document.getElementById('errorModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị cảnh báo
function showWarningModal(message) {
    const modal = document.getElementById('warningModal');
    const msgEl = document.getElementById('warningModalMessage');
    if (modal) {
        if (msgEl) msgEl.textContent = message || 'Vui lòng kiểm tra lại thông tin.';
        modal.style.display = 'flex';
    }
}

function closeWarningModal() {
    const modal = document.getElementById('warningModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo thành công
function showSuccessModal(message) {
    const modal = document.getElementById('successModal');
    const msgEl = document.getElementById('successModalMessage');
    if (modal) {
        if (msgEl) msgEl.textContent = message || 'Thao tác đã được thực hiện thành công.';
        modal.style.display = 'flex';
    }
}

function closeSuccessModal() {
    const modal = document.getElementById('successModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo hết lượt tạo
function showOutOfQuotaModal() {
    const modal = document.getElementById('outOfQuotaModal');
    if (modal) modal.style.display = 'flex';
}

function closeOutOfQuotaModal() {
    const modal = document.getElementById('outOfQuotaModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo tài khoản không hợp lệ
function showInvalidAccountModal() {
    const modal = document.getElementById('invalidAccountModal');
    if (modal) modal.style.display = 'flex';
}

function closeInvalidAccountModal() {
    const modal = document.getElementById('invalidAccountModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo lỗi kết nối mạng
function showNetworkErrorModal(message) {
    const modal = document.getElementById('networkErrorModal');
    if (modal) modal.style.display = 'flex';
}

function closeNetworkErrorModal() {
    const modal = document.getElementById('networkErrorModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo lỗi khi tạo nội dung
function showCreationErrorModal(message) {
    const modal = document.getElementById('creationErrorModal');
    const msgEl = document.getElementById('creationErrorMessage');
    if (modal) {
        if (msgEl) {
            if (message) {
                msgEl.innerHTML = `<p>${message}</p><p style="margin-top: 10px;"><strong>Giải pháp:</strong> Kiểm tra lại tài khoản và thử tạo lại.</p>`;
            }
        }
        modal.style.display = 'flex';
    }
}

function closeCreationErrorModal() {
    const modal = document.getElementById('creationErrorModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo tài khoản Grok đạt giới hạn
function showGrokLimitModal() {
    const modal = document.getElementById('grokLimitModal');
    if (modal) modal.style.display = 'flex';
}

function closeGrokLimitModal() {
    const modal = document.getElementById('grokLimitModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo lỗi server Veo3 (500, 403, 429)
function showVeo3ServerErrorModal(title, message) {
    const modal = document.getElementById('veo3ServerErrorModal');
    if (!modal) return;
    
    const titleEl = document.getElementById('veo3ServerErrorTitle');
    const messageEl = document.getElementById('veo3ServerErrorMessage');
    
    if (titleEl) titleEl.textContent = title || 'Lỗi server Veo3';
    if (messageEl) {
        if (typeof message === 'object' && message.innerHTML !== undefined) {
            messageEl.innerHTML = message.innerHTML;
        } else {
            messageEl.innerHTML = message || 'Đã xảy ra lỗi khi kết nối đến server Veo3.';
        }
    }
    
    modal.style.display = 'flex';
}

function closeVeo3ServerErrorModal() {
    const modal = document.getElementById('veo3ServerErrorModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị hướng dẫn nhanh
function showQuickGuideModal() {
    const modal = document.getElementById('quickGuideModal');
    if (modal) modal.style.display = 'flex';
}

function closeQuickGuideModal() {
    const modal = document.getElementById('quickGuideModal');
    if (modal) modal.style.display = 'none';
}

// Mở hướng dẫn đầy đủ
function openFullHelpGuide() {
    closeQuickGuideModal();
    const helpModal = document.getElementById('helpGuideModal');
    if (helpModal) helpModal.style.display = 'flex';
}

// Hiển thị hướng dẫn về tài khoản
function showAccountGuideModal() {
    const modal = document.getElementById('accountGuideModal');
    if (modal) modal.style.display = 'flex';
}

function closeAccountGuideModal() {
    const modal = document.getElementById('accountGuideModal');
    if (modal) modal.style.display = 'none';
}

// Hiển thị thông báo lỗi đăng nhập AI
function showAiLoginErrorModal() {
    const modal = document.getElementById('aiLoginErrorModal');
    if (modal) modal.style.display = 'flex';
}

function closeAiLoginErrorModal() {
    const modal = document.getElementById('aiLoginErrorModal');
    if (modal) modal.style.display = 'none';
}

// Close modals with ESC key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeErrorModal();
        closeWarningModal();
        closeSuccessModal();
        closeOutOfQuotaModal();
        closeInvalidAccountModal();
        closeNetworkErrorModal();
        closeCreationErrorModal();
        closeGrokLimitModal();
        closeVeo3ServerErrorModal();
        closeQuickGuideModal();
        closeAccountGuideModal();
        closeAiLoginErrorModal();
    }
});

// Export functions to window for global access
try {
    window.showErrorModal = showErrorModal;
    window.closeErrorModal = closeErrorModal;
    window.showWarningModal = showWarningModal;
    window.closeWarningModal = closeWarningModal;
    window.showSuccessModal = showSuccessModal;
    window.closeSuccessModal = closeSuccessModal;
    window.showOutOfQuotaModal = showOutOfQuotaModal;
    window.closeOutOfQuotaModal = closeOutOfQuotaModal;
    window.showInvalidAccountModal = showInvalidAccountModal;
    window.closeInvalidAccountModal = closeInvalidAccountModal;
    window.showNetworkErrorModal = showNetworkErrorModal;
    window.closeNetworkErrorModal = closeNetworkErrorModal;
    window.showCreationErrorModal = showCreationErrorModal;
    window.closeCreationErrorModal = closeCreationErrorModal;
    window.showGrokLimitModal = showGrokLimitModal;
    window.closeGrokLimitModal = closeGrokLimitModal;
    window.showVeo3ServerErrorModal = showVeo3ServerErrorModal;
    window.closeVeo3ServerErrorModal = closeVeo3ServerErrorModal;
    window.showQuickGuideModal = showQuickGuideModal;
    window.closeQuickGuideModal = closeQuickGuideModal;
    window.openFullHelpGuide = openFullHelpGuide;
    window.showAccountGuideModal = showAccountGuideModal;
    window.closeAccountGuideModal = closeAccountGuideModal;
    window.showAiLoginErrorModal = showAiLoginErrorModal;
    window.closeAiLoginErrorModal = closeAiLoginErrorModal;
} catch(e) {}
