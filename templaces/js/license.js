/**
 * License key — sidebar (thay User ID cũ). Lần đầu EXE vẫn dùng Tkinter (ensure_license).
 */
(function () {
    const keyInput = () => document.getElementById('license-key-input');
    const statusEl = () => document.getElementById('license-status-text');
    const expireEl = () => document.getElementById('license-expire-text');
    const btnActivate = () => document.getElementById('btn-license-activate');

    async function fetchLicenseStatus() {
        try {
            const res = await fetch('/api/license/status', { cache: 'no-store' });
            if (!res.ok) return;
            const data = await res.json();
            const st = statusEl();
            const ex = expireEl();
            if (!st) return;

            if (data.ok) {
                st.textContent = 'Đã kích hoạt';
                st.className = 'license-status-ok';
                if (ex) {
                    const exp = data.expire_at;
                    ex.textContent = exp ? `Hết hạn: ${exp}` : 'Không giới hạn thời gian';
                }
            } else {
                st.textContent = 'Chưa kích hoạt — nhập key và bấm Kích hoạt';
                st.className = 'license-status-warn';
                if (ex) ex.textContent = '';
            }

            const inp = keyInput();
            if (inp && data.license_key) {
                inp.value = data.license_key;
            }

        } catch (e) {
            console.warn('[license] status', e);
        }
    }

    async function activateLicense() {
        const inp = keyInput();
        const btn = btnActivate();
        const key = (inp && inp.value || '').trim();
        if (!key) {
            alert('Vui lòng nhập license key');
            return;
        }
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Đang kích hoạt...';
        }
        try {
            const res = await fetch('/api/license/activate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ license_key: key }),
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok && data.ok) {
                alert(data.message || 'Kích hoạt thành công');
                await fetchLicenseStatus();
            } else {
                alert(data.message || data.error || 'Kích hoạt thất bại');
            }
        } catch (e) {
            alert('Lỗi kết nối: ' + e.message);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-key"></i> KÍCH HOẠT';
            }
        }
    }

    function copyLicenseKey(event) {
        if (event) event.stopPropagation();
        const inp = keyInput();
        const text = (inp && inp.value || '').trim();
        if (!text) {
            alert('Chưa có license key để sao chép');
            return;
        }
        navigator.clipboard.writeText(text).then(() => {
            alert('Đã sao chép license key');
        });
    }

    window.activateLicense = activateLicense;
    window.fetchLicenseStatus = fetchLicenseStatus;
    window.copyLicenseKey = copyLicenseKey;

    document.addEventListener('DOMContentLoaded', () => {
        fetchLicenseStatus();
        const btn = btnActivate();
        if (btn) btn.addEventListener('click', activateLicense);
    });
})();
