function openImageOverlay(src) {
    const overlay = document.getElementById('imageOverlay');
    const img = document.getElementById('overlayImage');
    if (!overlay || !img) return;
    img.src = src;
    overlay.style.display = 'flex';
}

function closeImageOverlay() {
    const overlay = document.getElementById('imageOverlay');
    if (!overlay) return;
    overlay.style.display = 'none';
}

function openAudioOverlay(src, title) {
    const overlay = document.getElementById('audioOverlay');
    const audio = document.getElementById('audioPlayer');
    const titleEl = document.getElementById('audioTitle');
    if (!overlay || !audio) return;

    audio.src = src;
    audio.currentTime = 0;
    audio.play().catch(() => {});

    if (titleEl && title) {
        titleEl.textContent = title;
    }

    overlay.style.display = 'flex';
}

function closeAudioOverlay() {
    const overlay = document.getElementById('audioOverlay');
    const audio = document.getElementById('audioPlayer');
    if (audio) {
        audio.pause();
        audio.currentTime = 0;
    }
    if (overlay) {
        overlay.style.display = 'none';
    }
}

function openVideoOverlay(src, title) {
    const overlay = document.getElementById('videoOverlay');
    const video = document.getElementById('videoPlayer');
    const titleEl = document.getElementById('videoTitle');

    if (!overlay || !video || !titleEl) {
        return;
    }

    video.src = src;
    video.currentTime = 0;
    if (titleEl && title) {
        titleEl.textContent = title;
    }

    overlay.style.display = 'flex';
    video.play().catch(() => {});
}

function closeVideoOverlay() {
    const overlay = document.getElementById('videoOverlay');
    const video = document.getElementById('videoPlayer');
    if (video) {
        video.pause();
        video.currentTime = 0;
        video.removeAttribute('src');
        video.load();
    }
    if (overlay) {
        overlay.style.display = 'none';
    }
}

function askUninstallConfirm() {
    return new Promise((resolve) => {
        const modal = document.getElementById('uninstallConfirmModal');
        const btnOk = document.getElementById('uninstallConfirmBtn');
        const btnCancel = document.getElementById('uninstallCancelBtn');

        if (!modal || !btnOk || !btnCancel) {
            resolve(false);
            return;
        }

        let settled = false;

        const cleanup = () => {
            btnOk.onclick = null;
            btnCancel.onclick = null;
            document.onkeydown = null;
        };

        const close = () => {
            modal.style.display = 'none';
            cleanup();
        };

        const confirm = () => {
            if (settled) return;
            settled = true;
            close();
            resolve(true);
        };

        const cancel = () => {
            if (settled) return;
            settled = true;
            close();
            resolve(false);
        };

        modal.style.display = 'flex';

        btnOk.onclick = confirm;
        btnCancel.onclick = cancel;

        document.onkeydown = function (e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                cancel();
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                confirm();
            }
        };
    });
}

function askExitAppConfirm() {
    return new Promise((resolve) => {
        const modal = document.getElementById('exitAppModal');
        const btnSave = document.getElementById('exitAppSaveBtn');
        const btnDiscard = document.getElementById('exitAppDiscardBtn');
        const btnCancel = document.getElementById('exitAppCancelBtn');

        if (!modal || !btnSave || !btnDiscard || !btnCancel) {
            resolve('cancel');
            return;
        }

        let settled = false;

        const cleanup = () => {
            btnSave.onclick = null;
            btnDiscard.onclick = null;
            btnCancel.onclick = null;
            document.onkeydown = null;
        };

        const close = () => {
            modal.style.display = 'none';
            cleanup();
        };

        const done = (choice) => {
            if (settled) return;
            settled = true;
            close();
            resolve(choice);
        };

        modal.style.display = 'flex';

        btnSave.onclick = () => done('save');
        btnDiscard.onclick = () => done('discard');
        btnCancel.onclick = () => done('cancel');

        document.onkeydown = function (e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                done('cancel');
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                done('save');
            }
        };
    });
}

function askDesiredMusicName(defaultName) {
    return new Promise((resolve) => {
        const modal = document.getElementById('saveMusicNameModal');
        const input = document.getElementById('saveMusicNameInput');
        const btnOk = document.getElementById('saveMusicNameConfirmBtn');
        const btnCancel = document.getElementById('saveMusicNameCancelBtn');

        if (!modal || !input || !btnOk || !btnCancel) {
            resolve(null);
            return;
        }

        let settled = false;

        const cleanup = () => {
            btnOk.onclick = null;
            btnCancel.onclick = null;
            input.onkeydown = null;
        };

        const close = () => {
            modal.style.display = 'none';
            cleanup();
        };

        const confirm = () => {
            if (settled) return;
            settled = true;
            const name = String(input.value || '').trim();
            close();
            resolve(name || null);
        };

        const cancel = () => {
            if (settled) return;
            settled = true;
            close();
            resolve(null);
        };

        input.value = defaultName || '';
        modal.style.display = 'flex';
        input.focus();
        input.select();

        btnOk.onclick = confirm;
        btnCancel.onclick = cancel;
        input.onkeydown = function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                confirm();
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                cancel();
            }
        };
    });
}
