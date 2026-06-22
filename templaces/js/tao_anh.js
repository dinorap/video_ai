let imageFormCounter = 0;

function _imageStorageKey() {
    return 'tao_anh_state_v1';
}

function _safeJsonParse(s, fallback) {
    try {
        return JSON.parse(String(s || ''));
    } catch (e) {
        return fallback;
    }
}

function _isVeo3Provider(provider) {
    return String(provider || '').trim().toLowerCase().includes('veo3');
}

function _throttle(fn, waitMs) {
    let t = null;
    let lastArgs = null;
    return function () {
        lastArgs = arguments;
        if (t) return;
        t = setTimeout(() => {
            t = null;
            try { fn.apply(null, lastArgs); } catch (e) { }
        }, Math.max(0, parseInt(String(waitMs || 0), 10) || 0));
    };
}

const _persistTaoAnhStateThrottled = _throttle(() => {
    try {
        const displayArea = document.getElementById('image-display-area');
        if (!displayArea) return;
        const forms = Array.from(displayArea.querySelectorAll('.workspace-container'));
        const items = forms.map((root) => {
            const formId = String(root.dataset.formId || '').trim();
            const charImg = root.querySelector(`[id$="-display-character"] img`);
            const prodImg = root.querySelector(`[id$="-display-product"] img`);
            const promptEl = root.querySelector(`[id$="-display-description"] textarea`);
            const resultImg = root.querySelector(`[id$="-display-result"] img`);
            const genBtn = root.querySelector(`[id$="-btn-generate"]`);
            return {
                formId,
                image1: charImg ? String(charImg.getAttribute('src') || '') : '',
                image2: prodImg ? String(prodImg.getAttribute('src') || '') : '',
                prompt: promptEl ? String(promptEl.value || '') : '',
                taskId: String(root.dataset.taskId || ''),
                running: genBtn ? (String(genBtn.dataset.running || '') === '1') : false,
                resultUrl: resultImg ? String(resultImg.getAttribute('src') || '') : '',
                completed: !!resultImg,
            };
        });

        localStorage.setItem(_imageStorageKey(), JSON.stringify({ forms: items }));
    } catch (e) { }
}, 350);

function _persistTaoAnhStateNow() {
    try { _persistTaoAnhStateThrottled(); } catch (e) { }
}

function _setCreateBtnState(root, isRunning) {
    try {
        const genBtn = root ? root.querySelector(`[id$="-btn-generate"]`) : null;
        if (!genBtn) return;
        genBtn.dataset.running = isRunning ? '1' : '0';
        genBtn.textContent = isRunning ? 'Hủy' : 'Tạo';
    } catch (e) { }
}

function _createImageForm({ characterSrc, characterName }) {
    const formId = `img-form-${imageFormCounter++}`;

    const root = document.createElement('div');
    root.className = 'workspace-container';
    root.dataset.formId = formId;
    root.style.flex = '0 0 100%';

    const charBtnId = `${formId}-btn-select-character`;
    const prodBtnId = `${formId}-btn-select-product`;
    const resetBtnId = `${formId}-btn-reset-form`;
    const genBtnId = `${formId}-btn-generate`;

    const charBoxId = `${formId}-display-character`;
    const prodBoxId = `${formId}-display-product`;
    const descBoxId = `${formId}-display-description`;
    const resultBoxId = `${formId}-display-result`;

    root.innerHTML = `
        <div class="column">
            <button class="col-header-btn" type="button" id="${charBtnId}">Chọn Nhân Vật</button>
            <div class="content-area media-box" id="${charBoxId}"></div>
        </div>

        <div class="column">
            <button class="col-header-btn" type="button" id="${prodBtnId}">Chọn Sản Phẩm</button>
            <div class="content-area media-box placeholder" id="${prodBoxId}">Chưa có sản phẩm</div>
        </div>

        <div class="column">
            <div class="col-header-text">Nhập Mô Tả</div>
            <div class="content-area" id="${descBoxId}" style="padding: 8px;">
                <textarea></textarea>
            </div>
        </div>

        <div class="column">
            <div class="col-header-text">Kết Quả</div>
            <div class="content-area" id="${resultBoxId}"></div>
        </div>

        <div class="action-column">
            <button class="btn-small" type="button" id="${resetBtnId}">Xóa Form</button>
            <button class="btn-small" type="button" id="${genBtnId}" style="padding: 15px 5px;">Tạo</button>
        </div>
    `;

    const charBox = root.querySelector(`#${CSS.escape(charBoxId)}`);
    if (charBox && characterSrc) {
        const img = document.createElement('img');
        img.src = characterSrc;
        img.alt = characterName || 'character';
        img.style.cursor = 'pointer';
        img.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openImageLightbox(String(img.src));
        });
        charBox.appendChild(img);
    }

    const chooseCharBtn = root.querySelector(`#${CSS.escape(charBtnId)}`);
    if (chooseCharBtn) {
        chooseCharBtn.addEventListener('click', () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.onchange = (e) => {
                const file = e.target.files && e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (ev) => {
                    const box = root.querySelector(`#${CSS.escape(charBoxId)}`);
                    if (!box) return;
                    box.innerHTML = '';
                    const img = document.createElement('img');
                    img.src = String(ev.target && ev.target.result ? ev.target.result : '');
                    img.alt = file.name;
                    img.style.cursor = 'pointer';
                    img.addEventListener('click', (ev) => {
                        ev.stopPropagation();
                        openImageLightbox(String(img.src));
                    });
                    box.appendChild(img);
                };
                reader.readAsDataURL(file);
            };
            input.click();
        });
    }

    const chooseProdBtn = root.querySelector(`#${CSS.escape(prodBtnId)}`);
    if (chooseProdBtn) {
        chooseProdBtn.addEventListener('click', () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.onchange = (e) => {
                const file = e.target.files && e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (ev) => {
                    const box = root.querySelector(`#${CSS.escape(prodBoxId)}`);
                    if (!box) return;
                    box.innerHTML = '';
                    box.classList.remove('placeholder');
                    const img = document.createElement('img');
                    img.src = String(ev.target && ev.target.result ? ev.target.result : '');
                    img.alt = file.name;
                    img.style.cursor = 'pointer';
                    img.addEventListener('click', (ev) => {
                        ev.stopPropagation();
                        openImageLightbox(String(img.src));
                    });
                    box.appendChild(img);
                };
                reader.readAsDataURL(file);
            };
            input.click();
        });
    }

    const resetBtn = root.querySelector(`#${CSS.escape(resetBtnId)}`);
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            root.remove();
            _persistTaoAnhStateNow();
        });
    }

    const genBtn = root.querySelector(`#${CSS.escape(genBtnId)}`);
    if (genBtn) {
        genBtn.addEventListener('click', async () => {
            const isRunning = String(genBtn.dataset.running || '') === '1';
            const existingTaskId = String(root.dataset.taskId || '').trim();

            // Cancel
            if (isRunning && existingTaskId) {
                try {
                    await fetch('/cancel_image_task', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: existingTaskId }),
                    });
                } catch (e) { }

                try {
                    if (window._singleImagePollers && window._singleImagePollers[existingTaskId]) {
                        clearInterval(window._singleImagePollers[existingTaskId]);
                        delete window._singleImagePollers[existingTaskId];
                    }
                } catch (e) { }

                root.dataset.taskId = '';
                _setCreateBtnState(root, false);
                _persistTaoAnhStateNow();

                const box = root.querySelector(`#${CSS.escape(resultBoxId)}`);
                if (box) {
                    box.innerHTML = '';
                    const note = document.createElement('div');
                    note.style.cssText = 'padding: 10px; color: #ff4d4d; font-size: 12px;';
                    note.textContent = 'Đã hủy';
                    box.appendChild(note);
                }
                return;
            }

            const charImg = root.querySelector(`[id$="-display-character"] img`);
            const prodImg = root.querySelector(`[id$="-display-product"] img`);
            const promptEl = root.querySelector(`[id$="-display-description"] textarea`);

            try {
                if (promptEl && !promptEl.dataset.persistBound) {
                    promptEl.dataset.persistBound = '1';
                    promptEl.addEventListener('input', () => _persistTaoAnhStateNow());
                    promptEl.addEventListener('change', () => _persistTaoAnhStateNow());
                }
            } catch (e) { }

            const task = {
                form_id: String(root.dataset.formId || '').trim(),
                image1: charImg ? String(charImg.getAttribute('src') || '') : '',
                image2: prodImg ? String(prodImg.getAttribute('src') || '') : '',
                prompt: promptEl ? String(promptEl.value || '') : '',
            };

            const modelSelect = document.getElementById('model-select');
            const provider = modelSelect ? String(modelSelect.options[modelSelect.selectedIndex].textContent || '') : '';

            const aspectSelect = document.getElementById('aspect_ratio');
            const ratio = aspectSelect ? String(aspectSelect.value || '9:16').trim() : '9:16';

            // Read Veo3 image model if provider is Veo3
            let veo3_image_model = null;
            if (_isVeo3Provider(provider)) {
                const veo3ModelSelect = document.getElementById('veo3-image-model');
                if (veo3ModelSelect) {
                    veo3_image_model = String(veo3ModelSelect.value || '🍌 Nano Banana Pro').trim();
                }
            }

            const resultFolderLabel = document.getElementById('resultFolderLabel');
            const out_dir_label = resultFolderLabel ? String(resultFolderLabel.textContent || '').trim() : '';

            const _looksLikeAbsPath = (p) => {
                const s = String(p || '').trim();
                if (!s) return false;
                if (/^[a-zA-Z]:\\/.test(s)) return true;
                if (s.startsWith('/')) return true;
                return false;
            };
            if (!_looksLikeAbsPath(out_dir_label)) {
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay('Vui lòng chọn thư mục lưu kết quả trước khi tạo ảnh');
                } else {
                    _showErrorOverlay('Vui lòng chọn thư mục lưu kết quả trước khi tạo ảnh');
                }
                return;
            }

            const maxTabsInput = document.getElementById('max-tabs-input');
            let max_tabs = 5;
            if (maxTabsInput) {
                const n = parseInt(String(maxTabsInput.value || '').trim(), 10);
                if (Number.isFinite(n) && n > 0) max_tabs = n;
            }

            const box = root.querySelector(`#${CSS.escape(resultBoxId)}`);
            if (box) {
                box.innerHTML = '';
                box.onclick = null;
                box.title = '';
            }

            _setCreateBtnState(root, true);
            _persistTaoAnhStateNow();

            try {
                const payload = { provider, out_dir_label, max_tabs, ratio, tasks: [task] };
                if (veo3_image_model) {
                    payload.veo3_image_model = veo3_image_model;
                }

                // Route to correct endpoint based on provider
                const endpoint = _isVeo3Provider(provider)
                    ? '/create_images_veo3'
                    : '/create_images_batch_start';

                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || !data || data.ok !== true) {
                    const msg = (data && (data.error || data.message)) ? (data.error || data.message) : 'Tạo ảnh thất bại';
                    if (typeof window.showSuccessOverlay === 'function') {
                        window.showSuccessOverlay(msg);
                    } else {
                        _showErrorOverlay(msg);
                    }
                    genBtn.dataset.running = '0';
                    genBtn.textContent = 'Tạo';
                    return;
                }

                let newTaskId = '';
                try {
                    const mappings = Array.isArray(data.tasks) ? data.tasks : [];
                    const expectedFormId = String(task.form_id || '').trim();
                    const found = mappings.find(m => m && String(m.form_id || '').trim() === expectedFormId);
                    if (found && found.task_id) newTaskId = String(found.task_id || '').trim();
                } catch (e) {
                    newTaskId = '';
                }

                if (!newTaskId) {
                    _setCreateBtnState(root, false);
                    _persistTaoAnhStateNow();
                    return;
                }

                root.dataset.taskId = newTaskId;
                _persistTaoAnhStateNow();
                window._singleImagePollers = window._singleImagePollers || {};

                const pollOnce = async () => {
                    const tid = String(root.dataset.taskId || '').trim();
                    if (!tid || tid !== newTaskId) return;

                    try {
                        const r = await fetch(`/task_image?task_id=${encodeURIComponent(tid)}`);
                        const d = await r.json().catch(() => ({}));
                        if (!d || d.ok !== true) return;

                        if (d.status === 'completed' && d.url) {
                            if (box) {
                                box.innerHTML = '';
                                const img = document.createElement('img');
                                img.src = d.url;
                                img.alt = 'result';
                                img.style.maxWidth = '100%';
                                img.style.maxHeight = '100%';
                                box.appendChild(img);
                            }
                            _setCreateBtnState(root, false);
                            _persistTaoAnhStateNow();
                            if (window._singleImagePollers && window._singleImagePollers[tid]) {
                                clearInterval(window._singleImagePollers[tid]);
                                delete window._singleImagePollers[tid];
                            }
                        } else if (d.status === 'failed' || d.status === 'cancelled') {
                            if (box) {
                                box.innerHTML = '';
                                const note = document.createElement('div');
                                note.style.cssText = 'padding: 10px; color: #ff4d4d; font-size: 12px;';
                                note.textContent = d.error || (d.status === 'failed' ? 'Tạo ảnh thất bại' : 'Đã hủy');
                                box.appendChild(note);
                            }
                            _setCreateBtnState(root, false);
                            _persistTaoAnhStateNow();
                            if (window._singleImagePollers && window._singleImagePollers[tid]) {
                                clearInterval(window._singleImagePollers[tid]);
                                delete window._singleImagePollers[tid];
                            }
                        }
                    } catch (e) { }
                };

                await pollOnce();
                window._singleImagePollers[newTaskId] = setInterval(pollOnce, 1200);
            } catch (e) {
                _setCreateBtnState(root, false);
                _persistTaoAnhStateNow();
            }
        });
    }

    return root;
}

function _createPromptOverlay() {
    const overlay = document.createElement('div');
    overlay.id = 'prompt-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    `;

    const modal = document.createElement('div');
    modal.style.cssText = `
        background: #1a1a1a;
        border: 2px solid #555;
        border-radius: 12px;
        padding: 25px;
        width: 550px;
        max-width: 90%;
        box-shadow: 0 10px 30px rgba(0,0,0,0.8);
    `;

    const title = document.createElement('h3');
    title.textContent = 'Nhập mô tả cho tất cả ảnh';
    title.style.cssText = `
        margin: 0 0 20px 0;
        color: white;
        text-align: center;
        font-size: 20px;
        font-weight: bold;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
    `;

    const textarea = document.createElement('textarea');
    textarea.id = 'prompt-textarea-all';
    textarea.placeholder = 'Nhập mô tả chung cho tất cả ảnh...';
    textarea.style.cssText = `
        width: 100%;
        height: 150px;
        background: #111;
        color: white;
        border: 1px solid #444;
        border-radius: 6px;
        padding: 15px;
        font-size: 16px;
        font-weight: 500;
        resize: none;
        box-sizing: border-box;
        line-height: 1.5;
    `;

    const buttonsContainer = document.createElement('div');
    buttonsContainer.style.cssText = `
        display: flex;
        gap: 10px;
        justify-content: flex-end;
        margin-top: 15px;
    `;

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Hủy';
    cancelBtn.style.cssText = `
        background: #666;
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 16px;
        font-weight: 600;
        transition: background 0.3s;
    `;

    const confirmBtn = document.createElement('button');
    confirmBtn.textContent = 'Xác nhận';
    confirmBtn.style.cssText = `
        background: #e74c3c;
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 16px;
        font-weight: 600;
        transition: background 0.3s;
    `;

    buttonsContainer.appendChild(cancelBtn);
    buttonsContainer.appendChild(confirmBtn);
    modal.appendChild(title);
    modal.appendChild(textarea);
    modal.appendChild(buttonsContainer);
    overlay.appendChild(modal);

    cancelBtn.onclick = () => {
        document.body.removeChild(overlay);
    };

    confirmBtn.onclick = () => {
        const promptText = textarea.value.trim();
        if (promptText) {
            const descriptionTextareas = document.querySelectorAll('[id$="-display-description"] textarea');
            descriptionTextareas.forEach(textarea => {
                textarea.value = promptText;
            });
        }
        document.body.removeChild(overlay);
    };

    overlay.onclick = (e) => {
        if (e.target === overlay) {
            document.body.removeChild(overlay);
        }
    };

    return overlay;
}

function _showErrorOverlay(message) {
    const overlay = document.createElement('div');
    overlay.id = 'error-modal-overlay';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.85); display: flex; align-items: center;
        justify-content: center; z-index: 10000; color: white; font-family: sans-serif;
    `;

    const content = document.createElement('div');
    content.style.cssText = `
        background: #222; padding: 30px; border-radius: 12px;
        max-width: 500px; width: 90%; text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid #444;
    `;

    const title = document.createElement('h2');
    title.innerText = '⚠️ CẦN THIẾT LẬP TRÌNH DUYỆT';
    title.style.color = '#ff4d4d';
    title.style.marginBottom = '20px';

    const msg = document.createElement('p');
    msg.innerText = message;
    msg.style.lineHeight = '1.6';
    msg.style.fontSize = '16px';
    msg.style.marginBottom = '25px';

    const btn = document.createElement('button');
    btn.innerText = 'ĐÃ HIỂU';
    btn.style.cssText = `
        background: #007bff; color: white; border: none;
        padding: 12px 30px; border-radius: 6px; cursor: pointer;
        font-weight: bold; transition: background 0.2s;
    `;
    btn.onclick = () => document.body.removeChild(overlay);

    content.appendChild(title);
    content.appendChild(msg);
    content.appendChild(btn);
    overlay.appendChild(content);
    document.body.appendChild(overlay);
}

function initTaoAnhPage() {
    const addImagesBtn = document.getElementById('btn-add-images');
    if (addImagesBtn) {
        addImagesBtn.onclick = () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.multiple = true;
            input.onchange = (e) => {
                const files = Array.from(e.target.files);
                const displayArea = document.getElementById('image-display-area');
                if (!displayArea) return;

                if (!displayArea.classList.contains('is-visible')) {
                    displayArea.classList.add('is-visible');
                }
                files.forEach(file => {
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        const src = String(event.target && event.target.result ? event.target.result : '');
                        const formEl = _createImageForm({ characterSrc: src, characterName: file.name });
                        displayArea.appendChild(formEl);
                        _persistTaoAnhStateNow();
                    };
                    reader.readAsDataURL(file);
                });
            };
            input.click();
        };
    }

    const clearCompletedBtn = document.getElementById('btn-clear-completed-images');
    if (clearCompletedBtn) {
        clearCompletedBtn.onclick = () => {
            const displayArea = document.getElementById('image-display-area');
            if (!displayArea) return;
            const forms = Array.from(displayArea.querySelectorAll('.workspace-container'));
            forms.forEach((root) => {
                try {
                    const hasResultImg = !!root.querySelector(`[id$="-display-result"] img`);
                    if (!hasResultImg) return;

                    const genBtn = root.querySelector(`[id$="-btn-generate"]`);
                    const isRunning = genBtn ? (String(genBtn.dataset.running || '') === '1') : false;
                    const taskId = String(root.dataset.taskId || '').trim();
                    if (isRunning || taskId) {
                        return;
                    }
                    root.remove();
                } catch (e) { }
            });
            _persistTaoAnhStateNow();
        };
    }

    try {
        const displayArea = document.getElementById('image-display-area');
        if (displayArea) {
            const saved = _safeJsonParse(localStorage.getItem(_imageStorageKey()), null);
            const items = saved && Array.isArray(saved.forms) ? saved.forms : [];
            if (items.length > 0) {
                if (!displayArea.classList.contains('is-visible')) {
                    displayArea.classList.add('is-visible');
                }

                items.forEach((it) => {
                    const formEl = _createImageForm({ characterSrc: String(it.image1 || ''), characterName: '' });
                    try {
                        if (it.formId) formEl.dataset.formId = String(it.formId);
                        if (it.taskId) formEl.dataset.taskId = String(it.taskId);
                    } catch (e) { }

                    // product image
                    try {
                        if (it.image2) {
                            const prodBox = formEl.querySelector(`[id$="-display-product"]`);
                            if (prodBox) {
                                prodBox.innerHTML = '';
                                prodBox.classList.remove('placeholder');
                                const img = document.createElement('img');
                                img.src = String(it.image2);
                                img.alt = 'product';
                                img.style.cursor = 'pointer';
                                img.addEventListener('click', (ev) => {
                                    ev.stopPropagation();
                                    openImageLightbox(String(img.src));
                                });
                                prodBox.appendChild(img);
                            }
                        }
                    } catch (e) { }

                    // prompt
                    try {
                        const promptEl = formEl.querySelector(`[id$="-display-description"] textarea`);
                        if (promptEl) {
                            promptEl.value = String(it.prompt || '');
                            if (!promptEl.dataset.persistBound) {
                                promptEl.dataset.persistBound = '1';
                                promptEl.addEventListener('input', () => _persistTaoAnhStateNow());
                                promptEl.addEventListener('change', () => _persistTaoAnhStateNow());
                            }
                        }
                    } catch (e) { }

                    // restore result
                    try {
                        if (it.resultUrl) {
                            const box = formEl.querySelector(`[id$="-display-result"]`);
                            if (box) {
                                box.innerHTML = '';
                                const img = document.createElement('img');
                                img.src = String(it.resultUrl);
                                img.alt = 'result';
                                img.style.maxWidth = '100%';
                                img.style.maxHeight = '100%';
                                img.style.cursor = 'pointer';
                                img.addEventListener('click', (ev) => {
                                    ev.stopPropagation();
                                    openImageLightbox(String(img.src));
                                });
                                box.appendChild(img);
                            }
                        }
                    } catch (e) { }

                    // restore running state (best-effort)
                    try {
                        if (it.running && it.taskId) {
                            _setCreateBtnState(formEl, true);
                        }
                    } catch (e) { }

                    displayArea.appendChild(formEl);

                    // if running and has taskId, resume polling
                    try {
                        const tid = String(it.taskId || '').trim();
                        if (it.running && tid) {
                            const genBtn = formEl.querySelector(`[id$="-btn-generate"]`);
                            const box = formEl.querySelector(`[id$="-display-result"]`);

                            window._singleImagePollers = window._singleImagePollers || {};
                            const pollOnce = async () => {
                                const t0 = String(formEl.dataset.taskId || '').trim();
                                if (!t0 || t0 !== tid) return;
                                try {
                                    const r = await fetch(`/task_image?task_id=${encodeURIComponent(t0)}`);
                                    const d = await r.json().catch(() => ({}));
                                    if (!d || d.ok !== true) return;
                                    if (d.status === 'completed' && d.url) {
                                        if (box) {
                                            box.innerHTML = '';
                                            const img = document.createElement('img');
                                            img.src = d.url;
                                            img.alt = 'result';
                                            img.style.maxWidth = '100%';
                                            img.style.maxHeight = '100%';
                                            img.style.cursor = 'pointer';
                                            img.addEventListener('click', (ev) => {
                                                ev.stopPropagation();
                                                openImageLightbox(String(img.src));
                                            });
                                            box.appendChild(img);
                                        }
                                        formEl.dataset.taskId = '';
                                        if (genBtn) genBtn.dataset.running = '0';
                                        _setCreateBtnState(formEl, false);
                                        if (window._singleImagePollers && window._singleImagePollers[t0]) {
                                            clearInterval(window._singleImagePollers[t0]);
                                            delete window._singleImagePollers[t0];
                                        }
                                        _persistTaoAnhStateNow();
                                    } else if (d.status === 'failed' || d.status === 'cancelled') {
                                        if (box) {
                                            box.innerHTML = '';
                                            const note = document.createElement('div');
                                            note.style.cssText = 'padding: 10px; color: #ff4d4d; font-size: 12px;';
                                            note.textContent = d.error || (d.status === 'failed' ? 'Tạo ảnh thất bại' : 'Đã hủy');
                                            box.appendChild(note);
                                        }
                                        formEl.dataset.taskId = '';
                                        _setCreateBtnState(formEl, false);
                                        if (window._singleImagePollers && window._singleImagePollers[t0]) {
                                            clearInterval(window._singleImagePollers[t0]);
                                            delete window._singleImagePollers[t0];
                                        }
                                        _persistTaoAnhStateNow();
                                    }
                                } catch (e) { }
                            };
                            pollOnce();
                            window._singleImagePollers[tid] = setInterval(pollOnce, 1200);
                        }
                    } catch (e) { }
                });
            }
        }
    } catch (e) { }

    try {
        if (!window.__taoAnhPersistBound) {
            window.__taoAnhPersistBound = true;
            window.addEventListener('beforeunload', () => {
                try { _persistTaoAnhStateNow(); } catch (e) { }
            });
        }
    } catch (e) { }

    const promptAllBtn = document.getElementById('btn-input-prompt-image-all');
    if (promptAllBtn) {
        promptAllBtn.onclick = () => {
            const overlay = _createPromptOverlay();
            document.body.appendChild(overlay);
        };
    }

    const generateAllBtn = document.getElementById('btn-generate-all-images');
    if (generateAllBtn) {
        generateAllBtn.onclick = async () => {
            if (_createImagesRunning) {
                _createImagesRunning = false;
                if (_createImagesPollingTimer) {
                    try { clearInterval(_createImagesPollingTimer); } catch (e) { }
                    _createImagesPollingTimer = null;
                }
                _createImagesPending = null;

                if (_createImagesAbortController) {
                    try { _createImagesAbortController.abort(); } catch (e) { }
                    _createImagesAbortController = null;
                }

                try {
                    await fetch('/cancel_create_images_batch', { method: 'POST' });
                } catch (e) { }

                generateAllBtn.textContent = 'Tạo Tất Cả';
                return;
            }

            const displayArea = document.getElementById('image-display-area');
            if (!displayArea) return;

            const forms = Array.from(displayArea.querySelectorAll('.workspace-container'));
            if (forms.length === 0) {
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay('Chưa có thông tin để tạo');
                } else {
                    _showErrorOverlay('Chưa có thông tin để tạo');
                }
                return;
            }

            const tasks = forms.map(formEl => {
                const formId = formEl.dataset.formId || '';
                const charImg = formEl.querySelector(`[id$="-display-character"] img`);
                const prodImg = formEl.querySelector(`[id$="-display-product"] img`);
                const promptEl = formEl.querySelector(`[id$="-display-description"] textarea`);

                return {
                    form_id: formId,
                    image1: charImg ? String(charImg.getAttribute('src') || '') : '',
                    image2: prodImg ? String(prodImg.getAttribute('src') || '') : '',
                    prompt: promptEl ? String(promptEl.value || '') : ''
                };
            });

            const modelSelect = document.getElementById('model-select');
            const provider = modelSelect ? String(modelSelect.options[modelSelect.selectedIndex].textContent || '') : '';

            const aspectSelect = document.getElementById('aspect_ratio');
            const ratio = aspectSelect ? String(aspectSelect.value || '9:16').trim() : '9:16';

            // Read Veo3 image model if provider is Veo3
            let veo3_image_model = null;
            if (_isVeo3Provider(provider)) {
                const veo3ModelSelect = document.getElementById('veo3-image-model');
                if (veo3ModelSelect) {
                    veo3_image_model = String(veo3ModelSelect.value || '🍌 Nano Banana Pro').trim();
                }
            }

            const resultFolderLabel = document.getElementById('resultFolderLabel');
            const out_dir_label = resultFolderLabel ? String(resultFolderLabel.textContent || '').trim() : '';

            // Require output folder selection before starting (same as video)
            const _looksLikeAbsPath = (p) => {
                const s = String(p || '').trim();
                if (!s) return false;
                // Windows: C:\ or D:\ ...
                if (/^[a-zA-Z]:\\/.test(s)) return true;
                // Unix-like absolute
                if (s.startsWith('/')) return true;
                return false;
            };
            if (!_looksLikeAbsPath(out_dir_label)) {
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay('Vui lòng chọn thư mục lưu kết quả trước khi tạo ảnh');
                } else {
                    _showErrorOverlay('Vui lòng chọn thư mục lưu kết quả trước khi tạo ảnh');
                }
                return;
            }

            const maxTabsInput = document.getElementById('max-tabs-input');
            let max_tabs = 5;
            if (maxTabsInput) {
                const n = parseInt(String(maxTabsInput.value || '').trim(), 10);
                if (Number.isFinite(n) && n > 0) {
                    max_tabs = n;
                }
            }

            forms.forEach(formEl => {
                const resultBox = formEl && formEl.querySelector ? formEl.querySelector('[id$="-display-result"]') : null;
                if (!resultBox) return;
                resultBox.innerHTML = '';
                resultBox.onclick = null;
                resultBox.title = '';
            });

            _createImagesAbortController = new AbortController();
            _createImagesRunning = true;
            generateAllBtn.textContent = 'Dừng';

            try {
                const payload = { provider, out_dir_label, max_tabs, ratio, tasks };
                if (veo3_image_model) {
                    payload.veo3_image_model = veo3_image_model;
                }

                // Route to correct endpoint based on provider
                const endpoint = _isVeo3Provider(provider)
                    ? '/create_images_veo3'
                    : '/create_images_batch_start';

                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(payload),
                    signal: _createImagesAbortController.signal,
                });

                const data = await res.json().catch(() => ({}));
                if (!res.ok || !data || data.ok !== true) {
                    const msg = (data && (data.error || data.message)) ? (data.error || data.message) : 'Tạo ảnh thất bại';
                    if (typeof window.showSuccessOverlay === 'function') {
                        window.showSuccessOverlay(msg);
                    } else {
                        _showErrorOverlay(msg);
                    }
                    return;
                }

                const taskMappings = Array.isArray(data.tasks) ? data.tasks : [];
                _createImagesPending = {};
                taskMappings.forEach(m => {
                    if (!m || !m.form_id || !m.task_id) return;
                    _createImagesPending[m.task_id] = m.form_id;
                });

                const _pollOnce = async () => {
                    if (!_createImagesRunning || !_createImagesPending) return;
                    const pendingTaskIds = Object.keys(_createImagesPending);
                    if (pendingTaskIds.length === 0) {
                        if (_createImagesPollingTimer) {
                            try { clearInterval(_createImagesPollingTimer); } catch (e) { }
                            _createImagesPollingTimer = null;
                        }
                        _createImagesPending = null;
                        _createImagesRunning = false;
                        generateAllBtn.textContent = 'Tạo Tất Cả';
                        return;
                    }

                    await Promise.all(pendingTaskIds.map(async (taskId) => {
                        const formId = _createImagesPending ? _createImagesPending[taskId] : null;
                        if (!formId) return;
                        try {
                            const r = await fetch(`/task_image?task_id=${encodeURIComponent(taskId)}`);
                            const d = await r.json().catch(() => ({}));
                            if (!d || d.ok !== true) return;

                            if (d.status === 'completed' && d.url) {
                                const formEl = forms.find(f => (f.dataset.formId || '') === formId);
                                if (!formEl) return;
                                const resultBox = formEl.querySelector(`[id$="-display-result"]`);
                                if (!resultBox) return;
                                resultBox.innerHTML = '';
                                const img = document.createElement('img');
                                img.src = d.url;
                                img.alt = 'result';
                                img.style.maxWidth = '100%';
                                img.style.maxHeight = '100%';
                                img.style.cursor = 'pointer';
                                img.addEventListener('click', (ev) => {
                                    ev.stopPropagation();
                                    openImageLightbox(String(img.src));
                                });
                                resultBox.appendChild(img);
                                delete _createImagesPending[taskId];
                                _persistTaoAnhStateNow();
                            } else if (d.status === 'failed') {
                                const formEl = forms.find(f => (f.dataset.formId || '') === formId);
                                if (!formEl) return;
                                const resultBox = formEl.querySelector(`[id$="-display-result"]`);
                                if (!resultBox) return;
                                resultBox.innerHTML = '';
                                const note = document.createElement('div');
                                note.style.cssText = 'padding: 10px; color: #ff4d4d; font-size: 12px;';
                                note.textContent = d.error || 'Tạo ảnh thất bại';
                                resultBox.appendChild(note);
                                delete _createImagesPending[taskId];
                                _persistTaoAnhStateNow();
                            } else if (d.status === 'cancelled') {
                                const formEl = forms.find(f => (f.dataset.formId || '') === formId);
                                if (!formEl) return;
                                const resultBox = formEl.querySelector(`[id$="-display-result"]`);
                                if (!resultBox) return;
                                resultBox.innerHTML = '';
                                const note = document.createElement('div');
                                note.style.cssText = 'padding: 10px; color: #ff4d4d; font-size: 12px;';
                                note.textContent = d.error || 'Đã hủy';
                                resultBox.appendChild(note);
                                delete _createImagesPending[taskId];
                                _persistTaoAnhStateNow();
                            }
                        } catch (e) {
                            // ignore transient polling errors
                        }
                    }));
                };

                await _pollOnce();
                if (_createImagesRunning) {
                    _createImagesPollingTimer = setInterval(_pollOnce, 1200);
                }
            } catch (err) {
                if (err && (err.name === 'AbortError' || String(err).toLowerCase().includes('abort'))) {
                    return;
                }
                console.error('Lỗi gọi /create_images_batch_start:', err);
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay('Lỗi kết nối đến server');
                } else {
                    alert('Lỗi kết nối đến server');
                }
            } finally {
                _createImagesAbortController = null;
                if (!_createImagesRunning) {
                    generateAllBtn.textContent = 'Tạo Tất Cả';
                }
            }
        };
    }
}

function openImageLightbox(src) {
    const box = document.getElementById('imageLightbox');
    const img = document.getElementById('imageLightboxImg');
    if (!box || !img) return;
    img.src = src;
    box.style.display = 'flex';
}

function closeImageLightbox() {
    const box = document.getElementById('imageLightbox');
    if (!box) return;
    box.style.display = 'none';
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeImageLightbox();
    }
});

window.PageInits = window.PageInits || {};
window.PageInits['tao-anh'] = initTaoAnhPage;

let _createImagesAbortController = null;
let _createImagesPollingTimer = null;
let _createImagesPending = null;
let _createImagesRunning = false;
