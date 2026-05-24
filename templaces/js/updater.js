// ============================================================================
// OTA UPDATE CLIENT (GitHub release: VideoCreator.zip + update.json)
// Ghi đè file có trong ZIP; file chỉ có trên máy khách được giữ nguyên.
// ============================================================================

class UpdaterClient {
    constructor(apiBase = '') {
        this.apiBase = apiBase || window.location.origin;
        this.checkInterval = null;
        this.updateInfo = null;
    }

    async checkForUpdate() {
        try {
            const response = await fetch(`${this.apiBase}/api/update/check`);
            if (!response.ok) {
                console.warn('[Updater] Check HTTP', response.status);
                return false;
            }
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                console.warn('[Updater] Check returned non-JSON');
                return false;
            }
            const data = await response.json();

            if (data.has_update) {
                this.updateInfo = data;
                this.showUpdateNotification(data);
                return true;
            }
            if (data.error) {
                console.warn('[Updater] No update:', data.error, data.found_assets || '', data.hint || '');
            }
            return false;
        } catch (error) {
            console.error('[Updater] Check failed:', error);
            return false;
        }
    }

    showUpdateNotification(info) {
        const updateBtn = document.getElementById('updateBtn');
        const updateVersion = document.getElementById('updateVersion');

        if (updateBtn) {
            updateBtn.style.display = 'inline-flex';
            updateBtn.onclick = () => this.showUpdateDialog(info);

            if (updateVersion && info.version) {
                updateVersion.textContent = info.version;
            }
        }
    }

    showUpdateDialog(info) {
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.style.cssText = `
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
        `;

        const dialog = document.createElement('div');
        dialog.style.cssText = `
            background: #1e1e2e;
            border-radius: 12px;
            padding: 24px;
            max-width: 500px;
            width: 90%;
            color: #fff;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        `;

        const title = document.createElement('h2');
        title.textContent = `Phiên bản mới ${info.version} đã có sẵn!`;
        title.style.cssText = 'margin: 0 0 16px 0; color: #4CAF50;';

        const body = document.createElement('div');
        body.style.cssText = 'margin: 16px 0; max-height: 300px; overflow-y: auto;';
        body.innerHTML = info.body ? info.body.replace(/\n/g, '<br>') : 'Cập nhật mới có sẵn.';

        const progressContainer = document.createElement('div');
        progressContainer.style.cssText = 'margin: 16px 0; display: none;';

        const progressBar = document.createElement('div');
        progressBar.style.cssText = `
            width: 100%;
            height: 24px;
            background: #2a2a3a;
            border-radius: 12px;
            overflow: hidden;
            position: relative;
        `;

        const progressFill = document.createElement('div');
        progressFill.style.cssText = `
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #4CAF50, #45a049);
            transition: width 0.3s ease;
        `;

        const progressText = document.createElement('div');
        progressText.style.cssText = `
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 12px;
            font-weight: bold;
            color: #fff;
        `;
        progressText.textContent = '0%';

        progressBar.appendChild(progressFill);
        progressBar.appendChild(progressText);
        progressContainer.appendChild(progressBar);

        const statusText = document.createElement('div');
        statusText.style.cssText = 'margin: 8px 0; font-size: 14px; color: #aaa; text-align: center;';

        const buttons = document.createElement('div');
        buttons.style.cssText = 'display: flex; gap: 12px; margin-top: 20px;';

        const updateButton = document.createElement('button');
        updateButton.textContent = 'Cập nhật ngay';
        updateButton.className = 'btn btn-update';
        updateButton.style.cssText = `
            flex: 1;
            padding: 12px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
        `;
        updateButton.onclick = async () => {
            updateButton.disabled = true;
            cancelButton.disabled = true;
            progressContainer.style.display = 'block';

            try {
                await this.performUpdate((progress, status) => {
                    progressFill.style.width = `${progress}%`;
                    progressText.textContent = `${progress}%`;
                    statusText.textContent = status;
                });
            } catch (error) {
                alert(`Lỗi cập nhật: ${error.message}`);
                updateButton.disabled = false;
                cancelButton.disabled = false;
                progressContainer.style.display = 'none';
            }
        };

        const cancelButton = document.createElement('button');
        cancelButton.textContent = 'Để sau';
        cancelButton.className = 'btn';
        cancelButton.style.cssText = `
            flex: 1;
            padding: 12px;
            background: #555;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        `;
        cancelButton.onclick = () => {
            document.body.removeChild(modal);
        };

        buttons.appendChild(updateButton);
        buttons.appendChild(cancelButton);

        dialog.appendChild(title);
        dialog.appendChild(body);
        dialog.appendChild(progressContainer);
        dialog.appendChild(statusText);
        dialog.appendChild(buttons);
        modal.appendChild(dialog);
        document.body.appendChild(modal);
    }

    async performUpdate(onProgress) {
        onProgress(15, 'Đang gửi yêu cầu cập nhật...');

        const response = await fetch(`${this.apiBase}/api/update/perform`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Không thể bắt đầu cập nhật');
        }

        onProgress(40, 'Đang tải và xác minh (SHA256)...');
        await new Promise((r) => setTimeout(r, 1500));
        onProgress(70, 'Đang ghi đè file mới (giữ file cũ không có trong bản release)...');
        await new Promise((r) => setTimeout(r, 2000));
        onProgress(100, 'Hoàn tất! Ứng dụng sẽ tự khởi động lại...');
    }

    startAutoCheck(intervalMinutes = 60) {
        this.checkForUpdate();
        this.checkInterval = setInterval(() => {
            this.checkForUpdate();
        }, intervalMinutes * 60 * 1000);
    }

    stopAutoCheck() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
        }
    }
}

window.updaterClient = new UpdaterClient();

document.addEventListener('DOMContentLoaded', async () => {
    if (typeof loadAppVersion === 'function') {
        await loadAppVersion();
    }
    window.updaterClient.startAutoCheck(60);
});

