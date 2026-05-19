let THEMES = [];

function formatTaskTime(iso) {
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const hh = String(d.getHours()).padStart(2, '0');
        const mi = String(d.getMinutes()).padStart(2, '0');
        return `${dd}/${mm} ${hh}:${mi}`;
    } catch (_) {
        return '';
    }
}

function renderTaskTable(tasks) {
    const tbody = document.getElementById('taskTableBody');
    if (!tbody) return;

    const list = Array.isArray(tasks) ? tasks : [];
    tbody.innerHTML = '';

    list.forEach((t, idx) => {
        const tr = document.createElement('tr');

        const status = String(t.status || '').toLowerCase();
        let statusText = 'Đang xử lý';
        if (status === 'completed') statusText = 'Hoàn thành';
        if (status === 'failed') statusText = 'Thất bại';
        if (status === 'cancelled') statusText = 'Đã hủy';

        let statusClass = 'status-processing';
        if (status === 'completed') statusClass = 'status-completed';
        if (status === 'failed') statusClass = 'status-failed';
        if (status === 'cancelled') statusClass = 'status-failed';

        tr.innerHTML = `
            <td>${String(idx + 1).padStart(2, '0')}</td>
            <td>${t.name || ''}</td>
            <td>${t.model || ''}</td>
            <td>${formatTaskTime(t.created_at)}</td>
            <td style="text-align: center;">
                <span class="status-badge ${statusClass}">${statusText}</span>
            </td>
        `;

        tbody.appendChild(tr);
    });
}

async function refreshTasksOnce() {
    try {
        const res = await fetch('/list_tasks');
        const body = await res.json().catch(() => ({}));
        if (!res.ok || !body.ok) {
            return;
        }
        renderTaskTable(body.tasks || []);
    } catch (_) {
    }
}

function changeTheme(themeName) {
    document.body.classList.remove(
        'theme-default',
        'theme-hacker',
        'theme-tech',
        'theme-princess'
    );

    document.body.classList.add(themeName);
    localStorage.setItem('selectedTheme', themeName);

    const inputs = document.querySelectorAll('input[name="theme"]');
    inputs.forEach(input => {
        input.checked = (input.value === themeName);
    });
}

function renderThemes() {
    const grid = document.getElementById('themeGrid');
    if (!grid) return;

    grid.innerHTML = '';

    THEMES.forEach(theme => {
        const label = document.createElement('label');
        label.style.cursor = 'pointer';
        label.style.textAlign = 'center';

        const img = document.createElement('img');
        img.src = theme.url || `/templaces/img/${theme.file}`;
        img.style.width = '100px';
        img.style.display = 'block';
        img.style.borderRadius = '6px';
        img.style.border = '2px solid transparent';

        img.style.cursor = 'zoom-in';
        img.addEventListener('click', function (e) {
            e.stopPropagation();
            openImageOverlay(this.src);
        });

        const input = document.createElement('input');
        input.type = 'radio';
        input.name = 'theme';
        input.value = theme.className || theme.name || theme.file;
        input.style.marginTop = '8px';

        const labelText = theme.label || theme.name || theme.file;
        const text = document.createTextNode(' ' + labelText);

        input.addEventListener('change', function () {
            if (this.checked) {
                changeTheme(input.value);
            }
        });

        label.appendChild(img);
        label.appendChild(input);
        label.appendChild(text);

        grid.appendChild(label);
    });
}

function initHomePage() {
    renderThemes();

    const cdpPortInput = document.getElementById('cdpPortInput');
    if (cdpPortInput) {
        // Load initial value from config.json
        fetch('/config/config.json')
            .then(res => res.json())
            .then(cfg => {
                const raw = (cfg && (cfg.CDP_PORT ?? cfg.cdp_port)) ? (cfg.CDP_PORT ?? cfg.cdp_port) : 9222;
                let n = parseInt(String(raw), 10);
                if (!Number.isFinite(n) || n < 1 || n > 65535) n = 9222;
                cdpPortInput.value = String(n);
            })
            .catch(() => {
                cdpPortInput.value = '9222';
            });

        const _savePort = async () => {
            let n = parseInt(String(cdpPortInput.value || '').trim(), 10);
            if (!Number.isFinite(n) || n < 1 || n > 65535) {
                n = 9222;
                cdpPortInput.value = String(n);
            }
            try {
                await fetch('/save_config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ CDP_PORT: n }),
                });
            } catch (_) {}
        };

        cdpPortInput.addEventListener('change', _savePort);
        cdpPortInput.addEventListener('blur', _savePort);
    }

    const clearTasksBtn = document.getElementById('clearTasksBtn');
    if (clearTasksBtn) {
        clearTasksBtn.onclick = async function () {
            try {
                const res = await fetch('/clear_tasks', { method: 'POST' });
                const body = await res.json().catch(() => ({}));
                if (!res.ok || !body.ok) {
                    return;
                }
                await refreshTasksOnce();
            } catch (_) {
            }
        };
    }

    if (window.__homeTaskPoll) {
        try { clearInterval(window.__homeTaskPoll); } catch (_) {}
        window.__homeTaskPoll = null;
    }
    refreshTasksOnce();
    window.__homeTaskPoll = setInterval(refreshTasksOnce, 3000);

    fetch('/listthemes')
        .then(res => res.json())
        .then(list => {
            THEMES = list.map(item => ({
                className: item.theme || 'theme-default',
                name: item.name,
                file: item.file,
                url: item.url,
                label: item.name,
            }));
            renderThemes();
        })
        .catch(err => {
            console.error('Không load được danh sách theme:', err);
        });

    const uninstallBtn = document.getElementById('uninstallBtn');
    if (uninstallBtn) {
        uninstallBtn.onclick = async function () {
            const ok = await askUninstallConfirm();
            if (!ok) return;

            try {
                const res = await fetch('/uninstall', { method: 'POST' });
                const body = await res.json();
                
                if (res.ok && body.ok) {
                    // Bước 2: Gọi api /exit_app và chạy file bat (thông qua trình duyệt mở file hoặc tự thoát)
                    // Ở đây /exit_app sẽ làm app dừng lại. 
                    // File bat đã được tạo ở bước 1 và sẽ tự chạy uninstall.exe sau 2s
                    
                    fetch('/exit_app', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'exit' })
                    });

                    // Thông báo cho người dùng và đóng cửa sổ
                    alert('Ứng dụng sẽ đóng để thực hiện gỡ cài đặt.');
                    window.close();
                } else {
                    console.error('Gỡ cài đặt thất bại:', body.error);
                    alert('Lỗi: ' + (body.error || 'Không thể khởi tạo gỡ cài đặt'));
                }
            } catch (err) {
                console.error('Lỗi gọi /uninstall:', err);
            }
        };
    }
}

window.PageInits = window.PageInits || {};
window.PageInits.home = initHomePage;
