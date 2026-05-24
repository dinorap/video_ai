function _getNextVideoIndex(displayArea) {
    let startIndex = 0;
    const existingRows = Array.from(displayArea.querySelectorAll('.video-row'));
    existingRows.forEach((el) => {
        const v = parseInt(String(el.dataset.videoIndex || ''), 10);
        if (Number.isFinite(v) && v > startIndex) startIndex = v;
    });
    return startIndex + 1;
}

function _videoStorageKey() {
    return 'tao_video_state_v1';
}

function _safeJsonParse(s, fallback) {
    try {
        return JSON.parse(String(s || ''));
    } catch (e) {
        return fallback;
    }
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

const _persistTaoVideoStateThrottled = _throttle(() => {
    try {
        const displayArea = document.getElementById('video-display-area');
        if (!displayArea) return;
        const rows = Array.from(displayArea.querySelectorAll('.video-row'));
        const items = rows.map((rowEl) => {
            const idx = parseInt(String(rowEl.dataset.videoIndex || ''), 10) || 0;
            const effectSelect = idx > 0 ? document.getElementById(`video-effect-${idx}`) : null;
            const effect_key = effectSelect ? String(effectSelect.value || '') : String(rowEl.dataset.effectKey || '');
            return {
                videoIndex: idx,
                defaultImage: String(rowEl.dataset.defaultImage || ''),
                effectKey: String(effect_key || ''),
                scriptName: String(rowEl.dataset.scriptName || ''),
                scenes: String(rowEl.dataset.scenes || ''),
                taskId: String(rowEl.dataset.taskId || ''),
                resultUrl: String(rowEl.dataset.resultUrl || ''),
                progressPercent: String(rowEl.dataset.progressPercent || ''),
                sceneIndex: String(rowEl.dataset.sceneIndex || ''),
                totalScenes: String(rowEl.dataset.totalScenes || ''),
                phase: String(rowEl.dataset.phase || ''),
                status: String(rowEl.dataset.status || ''),
            };
        });
        localStorage.setItem(_videoStorageKey(), JSON.stringify({ rows: items }));
    } catch (e) { }
}, 350);

function _persistTaoVideoStateNow() {
    try { _persistTaoVideoStateThrottled(); } catch (e) { }
}

async function _waitUrlReady(url, timeoutMs) {
    const start = Date.now();
    const maxMs = Math.max(0, parseInt(String(timeoutMs || 0), 10) || 0);
    const u0 = String(url || '').trim();
    if (!u0) return false;

    while (true) {
        try {
            const bust = u0 + (u0.includes('?') ? '&' : '?') + `t=${Date.now()}`;
            const res = await fetch(bust, { method: 'GET', cache: 'no-store' });
            if (res && res.ok) {
                try { await res.arrayBuffer(); } catch (e) { }
                return true;
            }
        } catch (e) { }

        if (maxMs > 0 && (Date.now() - start) > maxMs) {
            return false;
        }
        await new Promise((r) => setTimeout(r, 700));
    }
}

function _setRowCreateBtnState(videoIndex, isRunning) {
    const btn = document.getElementById(`video-btn-create-${videoIndex}`);
    if (!btn) return;
    btn.textContent = isRunning ? 'Hủy' : 'Tạo';
    btn.dataset.running = isRunning ? '1' : '0';
}

function _setAllRowCreateBtnState(isRunning) {
    const rows = Array.from(document.querySelectorAll('#video-display-area .video-row'));
    rows.forEach((rowEl) => {
        const idx = parseInt(String(rowEl.dataset.videoIndex || ''), 10) || 0;
        if (idx > 0) _setRowCreateBtnState(idx, isRunning);
    });
}

function _collectOneVideoTaskFromRow(rowEl) {
    const videoIndex = parseInt(String(rowEl.dataset.videoIndex || ''), 10) || 0;
    const form_id = `video_${videoIndex}`;
    const defaultImage = String(rowEl.dataset.defaultImage || '');

    let effect_key = String(rowEl.dataset.effectKey || '');
    const effectSelect = document.getElementById(`video-effect-${videoIndex}`);
    if (effectSelect) {
        effect_key = String(effectSelect.value || '').trim();
        rowEl.dataset.effectKey = effect_key;
    }

    let scenes = [];
    const raw = String(rowEl.dataset.scenes || '');
    if (raw) {
        try { scenes = JSON.parse(raw) || []; } catch (e) { scenes = []; }
    }
    if (!Array.isArray(scenes) || scenes.length === 0) {
        scenes = [{ scene: 1, prompt: '', image: '' }];
    }

    const normalizedScenes = scenes.map((s, i) => {
        const prompt = String((s && s.prompt) ? s.prompt : '').trim();
        const overrideImage = String((s && s.image) ? s.image : '');
        const image = overrideImage ? overrideImage : defaultImage;
        return { scene: i + 1, prompt, image };
    });

    return { form_id, scenes: normalizedScenes, effect_key };
}

function _ensureVideoSettingsModal() {
    let modal = document.getElementById('videoSettingsModal');
    if (modal) return modal;

    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
<div id="videoSettingsModal" class="modal-overlay" style="display:none;">
    <div class="modal-box" style="max-width: 900px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap: 10px;">
            <div style="font-weight: 800;">Thiết lập video</div>
            <button id="videoSettingsCloseBtn" type="button" class="modal-cancel">Đóng</button>
        </div>

        <div id="videoSettingsHeader" style="margin-top: 10px; position: sticky; top: 0; z-index: 2; background: inherit; padding-bottom: 10px;">
            <div style="margin-bottom: 6px;">Chọn kịch bản</div>
            <select id="videoScriptSelect" class="input-control"></select>
        </div>

        <div id="videoSceneContainer" style="flex: 1; overflow: auto; margin-top: 0; padding-right: 6px;"></div>

        <div id="videoSettingsFooter" style="margin-top: 12px; display: flex; justify-content: flex-end; gap: 10px;">
            <button id="videoSettingsAddPromptBtn" type="button" class="btn-header" style="padding: 10px 12px; font-size: 13px; font-weight: 900;">Thêm prompt</button>
            <button id="videoSettingsConfirmBtn" type="button" class="modal-confirm">Xác nhận</button>
        </div>
    </div>
</div>
    `.trim();
    modal = wrapper.firstElementChild;
    document.body.appendChild(modal);
    return modal;
}

function _renumberVideoSceneItems() {
    const container = document.getElementById('videoSceneContainer');
    if (!container) return;
    const items = Array.from(container.querySelectorAll('.scene-item'));
    items.forEach((el, idx) => {
        const sceneIndex = idx + 1;
        el.dataset.sceneIndex = String(sceneIndex);
        const title = el.querySelector('[data-role="scene-title"]');
        if (title) title.textContent = `Cảnh ${sceneIndex}`;
    });
}

function _createVideoSceneBlock(scene, idx, videoIndex, defaultImage) {
    const sceneIndex = idx + 1;
    const block = document.createElement('div');
    block.className = 'scene-item';
    block.dataset.videoIndex = String(videoIndex);
    block.dataset.sceneIndex = String(sceneIndex);

    // Restore custom image if present in scene data
    const sceneImg = String(scene && scene.image ? scene.image : '');
    if (sceneImg) {
        block.dataset.sceneImage = sceneImg;
    }

    block.style.cssText = 'background: color-mix(in srgb, var(--card-bg) 92%, transparent); border: 1px solid color-mix(in srgb, var(--border-color) 70%, transparent); border-radius: 10px; padding: 12px; margin-bottom: 10px;';

    const titleRow = document.createElement('div');
    titleRow.style.cssText = 'display:flex; align-items:center; justify-content:space-between; gap: 10px; margin-bottom: 8px;';

    const title = document.createElement('div');
    title.dataset.role = 'scene-title';
    title.style.cssText = 'font-weight: 800;';
    title.textContent = `Cảnh ${scene.scene || sceneIndex}`;

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn-header';
    delBtn.textContent = 'Xóa';
    delBtn.style.cssText = 'flex: 0 0 auto; padding: 8px 10px; font-size: 12px; font-weight: 900; background: color-mix(in srgb, var(--border-color) 70%, transparent);';
    delBtn.onclick = () => {
        try { block.remove(); } catch (e) {
            if (block && block.parentNode) block.parentNode.removeChild(block);
        }
        _renumberVideoSceneItems();
    };

    titleRow.appendChild(title);
    titleRow.appendChild(delBtn);

    const promptLabel = document.createElement('div');
    promptLabel.style.cssText = 'margin-bottom: 6px; color: #ddd; font-weight: 700;';
    promptLabel.textContent = 'Prompt';

    const prompt = document.createElement('textarea');
    prompt.className = 'input-control';
    prompt.value = String(scene && scene.prompt ? scene.prompt : '');
    prompt.dataset.role = 'scene-prompt';
    prompt.style.cssText = 'width: 100%; min-height: 110px; resize: vertical;';

    const imageLabel = document.createElement('div');
    imageLabel.style.cssText = 'margin-top: 10px; margin-bottom: 6px; color: #ddd; font-weight: 700;';
    imageLabel.textContent = 'Chọn ảnh cho cảnh';

    const imageRow = document.createElement('div');
    imageRow.style.cssText = 'display: flex; align-items: center; gap: 10px;';

    const pickBtn = document.createElement('button');
    pickBtn.type = 'button';
    pickBtn.className = 'btn-header';
    pickBtn.style.cssText = 'flex: 0 0 auto; padding: 10px 12px; font-size: 13px;';
    pickBtn.textContent = 'Chọn ảnh';

    const preview = document.createElement('img');
    preview.alt = 'scene-image';
    preview.style.cssText = 'width: 84px; height: 84px; object-fit: cover; border-radius: 10px; border: 1px solid rgba(255,255,255,0.18); display: none;';

    // Priority: Custom scene image > Default video image
    if (sceneImg) {
        preview.src = sceneImg;
        preview.style.display = '';
    } else if (defaultImage) {
        preview.src = defaultImage;
        preview.style.display = '';
    }

    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    fileInput.style.display = 'none';

    pickBtn.onclick = () => {
        fileInput.value = '';
        fileInput.click();
    };

    fileInput.onchange = (e) => {
        const f = e && e.target && e.target.files ? e.target.files[0] : null;
        if (!f) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            const src = String(ev && ev.target ? ev.target.result : '');
            if (!src) return;
            preview.src = src;
            preview.style.display = '';
            block.dataset.sceneImage = src;
        };
        reader.readAsDataURL(f);
    };

    imageRow.appendChild(pickBtn);
    imageRow.appendChild(preview);
    imageRow.appendChild(fileInput);

    block.appendChild(titleRow);
    block.appendChild(promptLabel);
    block.appendChild(prompt);
    block.appendChild(imageLabel);
    block.appendChild(imageRow);
    return block;
}

async function _loadVideoScriptList() {
    const select = document.getElementById('videoScriptSelect');
    if (!select) return;

    try {
        const res = await fetch('/listscripts');
        const names = await res.json().catch(() => []);
        select.innerHTML = '<option value="" selected>None</option>';
        (Array.isArray(names) ? names : []).forEach((name) => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = String(name || '').endsWith('.txt') ? String(name).slice(0, -4) : String(name || '');
            select.appendChild(opt);
        });
    } catch (e) {
        select.innerHTML = '<option value="" selected>None</option>';
    }
}

let _ffmpegEffectsCache = null;
let _ffmpegEffectsPromise = null;

async function _loadFfmpegEffects() {
    if (_ffmpegEffectsCache) return _ffmpegEffectsCache;
    if (_ffmpegEffectsPromise) return _ffmpegEffectsPromise;

    _ffmpegEffectsPromise = (async () => {
        try {
            const res = await fetch('/config/ffmpeg_effects.json');
            const data = await res.json().catch(() => null);
            _ffmpegEffectsCache = Array.isArray(data) ? data : [];
            return _ffmpegEffectsCache;
        } catch (e) {
            _ffmpegEffectsCache = [];
            return _ffmpegEffectsCache;
        } finally {
            _ffmpegEffectsPromise = null;
        }
    })();

    return _ffmpegEffectsPromise;
}

async function _populateEffectSelect(selectEl, rowEl) {
    if (!selectEl) return;
    const effects = await _loadFfmpegEffects();

    selectEl.innerHTML = '';
    const optNone = document.createElement('option');
    optNone.value = '';
    optNone.textContent = 'Không hiệu ứng';
    optNone.title = '';
    selectEl.appendChild(optNone);

    (Array.isArray(effects) ? effects : []).forEach((eff) => {
        const key = String(eff && eff.key ? eff.key : '');
        const nameVi = String(eff && eff.name_vi ? eff.name_vi : key);
        const desc = String(eff && eff.description ? eff.description : '');
        if (!key) return;
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = nameVi;
        opt.title = desc;
        opt.dataset.description = desc;
        selectEl.appendChild(opt);
    });

    const saved = rowEl ? String(rowEl.dataset.effectKey || '') : '';
    if (saved) {
        selectEl.value = saved;
    }

    const _syncTitle = () => {
        const opt = selectEl.options && selectEl.selectedIndex >= 0 ? selectEl.options[selectEl.selectedIndex] : null;
        const desc = opt ? String(opt.dataset.description || opt.title || '') : '';
        selectEl.title = desc;
    };
    _syncTitle();

    selectEl.onchange = () => {
        if (rowEl) rowEl.dataset.effectKey = String(selectEl.value || '');
        _syncTitle();
    };
    selectEl.onmouseenter = _syncTitle;
}

function _setVideoSceneStatus(videoIndex, text) {
    const el = document.getElementById(`video-scene-status-${videoIndex}`);
    if (!el) return;
    el.textContent = String(text || '');
}

function _updatePromptsList(videoIndex) {
    const container = document.getElementById(`video-prompts-list-${videoIndex}`);
    const rowEl = document.getElementById(`video-row-${videoIndex}`);
    if (!container || !rowEl) return;

    container.innerHTML = '';

    const raw = String(rowEl.dataset.scenes || '');
    let scenes = [];
    if (raw) {
        try { scenes = JSON.parse(raw) || []; } catch (e) { scenes = []; }
    }

    if (!Array.isArray(scenes) || scenes.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'scene-item';
        empty.innerHTML = `<span class="scene-num">1</span><span class="scene-prompt empty">Chưa có prompt — bấm Thiết lập để thêm</span>`;
        container.appendChild(empty);
        return;
    }

    scenes.forEach((scene, idx) => {
        const item = document.createElement('div');
        item.className = 'scene-item';

        const num = document.createElement('span');
        num.className = 'scene-num';
        num.textContent = idx + 1;

        const text = document.createElement('span');
        text.className = 'scene-prompt' + (!scene.prompt ? ' empty' : '');
        text.textContent = scene.prompt || 'Chưa có prompt';

        item.appendChild(num);
        item.appendChild(text);
        container.appendChild(item);
    });
}

function _setVideoProgress(videoIndex, percent, sceneIndex, totalScenes) {
    // Progress bar removed — only show scene status
    _setVideoSceneStatus(videoIndex, sceneIndex && totalScenes ? `Tạo cảnh ${sceneIndex}/${totalScenes}` : '');
}

function _setVideoResultLink(videoIndex, url) {
    const el = document.getElementById(`video-result-link-${videoIndex}`);
    const previewCol = document.getElementById(`video-preview-col-${videoIndex}`);
    if (!el) return;
    const u = String(url || '').trim();
    if (!u) {
        el.innerHTML = '';
        return;
    }

    // Update preview thumbnail
    if (previewCol) {
        previewCol.innerHTML = '';
        const video = document.createElement('video');
        video.src = u;
        video.style.cssText = 'width: 100%; height: 100%; object-fit: contain; border-radius: 10px;';
        video.muted = true;
        video.preload = 'metadata';

        const overlay = document.createElement('div');
        overlay.className = 'preview-play';
        const playBtn = document.createElement('div');
        playBtn.className = 'play-btn';
        overlay.appendChild(playBtn);

        previewCol.appendChild(video);
        previewCol.appendChild(overlay);

        previewCol.onclick = async () => {
            const freshUrl = u + (u.includes('?') ? '&' : '?') + `v=${Date.now()}`;
            if (typeof window.openVideoOverlay === 'function') {
                window.openVideoOverlay(freshUrl, `Video ${videoIndex}`);
            } else if (typeof openVideoOverlay === 'function') {
                openVideoOverlay(freshUrl, `Video ${videoIndex}`);
            } else {
                window.open(freshUrl, '_blank');
            }
        };
    }

    el.innerHTML = `<button class="remerge-btn" type="button">⟳ GHÉP LẠI</button>`;
    const btn = el.querySelector('button');
    if (btn) {
        btn.onclick = async () => {
            const rowEl = document.getElementById(`video-row-${videoIndex}`);
            const taskId = rowEl ? String(rowEl.dataset.taskId || '') : '';
            if (!taskId) {
                if (typeof window.showAutoError === 'function') {
                    window.showSuccessOverlay('Không tìm thấy task để ghép lại');
                } else {
                    alert('Không tìm thấy task để ghép lại');
                }
                return;
            }

            // Re-collect current effect from UI (source of truth)
            let effect_key = rowEl ? String(rowEl.dataset.effectKey || '') : '';
            const effectSelect = document.getElementById(`video-effect-${videoIndex}`);
            if (effectSelect) {
                effect_key = String(effectSelect.value || '').trim();
                if (rowEl) rowEl.dataset.effectKey = effect_key;
            }

            const musicInput = document.getElementById('musicSelect');
            const randomMusicCb = document.getElementById('random-music-checkbox');
            const useRandomMusic = !!(randomMusicCb && randomMusicCb.checked);

            let music_url = '';
            let music_name = '';
            if (useRandomMusic && Array.isArray(window.__musicList) && window.__musicList.length > 0) {
                const selectable = window.__musicList.filter((x) => x && String(x.name || '').trim());
                if (selectable.length > 0) {
                    const pick = selectable[Math.floor(Math.random() * selectable.length)];
                    music_name = String(pick.name || '').trim();
                    music_url = String(pick.url || '').trim();
                }
            } else if (musicInput) {
                const v = String(musicInput.value || '').trim();
                if (v && !v.toLowerCase().startsWith('none')) {
                    music_name = v;
                    music_url = (window.__musicUrlByName && window.__musicUrlByName[v]) ? String(window.__musicUrlByName[v] || '').trim() : '';
                }
            }

            _setVideoSceneStatus(videoIndex, 'Đang ghép lại');
            try {
                if (rowEl) rowEl.dataset.remerging = '1';
            } catch (e) { }
            try {
                const res = await fetch('/remerge_video', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId, effect_key, music_url, music_name })
                });
                const body = await res.json().catch(() => ({}));
                if (!res.ok || !body.ok) {
                    _setVideoSceneStatus(videoIndex, `Lỗi: ${body && body.error ? body.error : 'Không thể ghép lại'}`);
                    return;
                }
                const newUrl = String(body.result_url || '');
                if (newUrl) {
                    const freshUrl = newUrl + (newUrl.includes('?') ? '&' : '?') + `v=${Date.now()}`;
                    const row = document.getElementById(`video-row-${videoIndex}`);
                    if (row) row.dataset.resultUrl = freshUrl;
                    _setVideoResultLink(videoIndex, freshUrl);
                    const playBtn = document.getElementById(`video-play-btn-${videoIndex}`);
                    if (playBtn) playBtn.style.display = 'flex';
                }
                _setVideoSceneStatus(videoIndex, 'Hoàn tất');
            } catch (e) {
                _setVideoSceneStatus(videoIndex, 'Lỗi ghép lại');
            } finally {
                try {
                    if (rowEl) rowEl.dataset.remerging = '0';
                } catch (e) { }
            }
        };
    }
}

function _renderVideoScenes(scenes, videoIndex) {
    const container = document.getElementById('videoSceneContainer');
    if (!container) return;
    container.innerHTML = '';

    const rowEl = document.getElementById(`video-row-${videoIndex}`);
    const defaultImage = rowEl ? String(rowEl.dataset.defaultImage || '') : '';

    const list = Array.isArray(scenes) ? scenes : [];
    if (list.length === 0) {
        const empty = document.createElement('div');
        empty.style.cssText = 'padding: 10px; color: #aaa;';
        empty.textContent = 'Chưa có cảnh nào trong kịch bản.';
        container.appendChild(empty);
        return;
    }

    list.forEach((scene, idx) => {
        const block = _createVideoSceneBlock(scene, idx, videoIndex, defaultImage);
        container.appendChild(block);
    });
    _renumberVideoSceneItems();
}

async function _loadVideoScript(fileName, videoIndex) {
    if (!fileName) {
        _renderVideoScenes([], videoIndex);
        return;
    }
    try {
        const res = await fetch(`/load_script?name=${encodeURIComponent(fileName)}`);
        const body = await res.json().catch(() => ({}));
        if (!res.ok || !body.ok || !Array.isArray(body.scenes)) {
            _renderVideoScenes([], videoIndex);
            return;
        }
        _renderVideoScenes(body.scenes, videoIndex);
    } catch (e) {
        _renderVideoScenes([], videoIndex);
    }
}


function _updateScriptBadge(index) {
    const rowEl = document.getElementById(`video-row-${index}`);
    const badge = document.getElementById(`video-script-badge-${index}`);
    if (!rowEl || !badge) return;

    const scriptName = String(rowEl.dataset.scriptName || '').trim();
    const scenesRaw = String(rowEl.dataset.scenes || '').trim();

    let text = 'None';
    let color = '#aaa';

    if (scriptName && scriptName !== 'None') {
        text = scriptName;
        color = '#00ff88';
    }

    if (scenesRaw) {
        try {
            const scenes = JSON.parse(scenesRaw);
            if (Array.isArray(scenes) && scenes.length > 0) {
                // If there's a script name but it's a custom list of scenes (user added/removed/edited)
                text = `Tùy chỉnh * (${scenes.length} cảnh)`;
                color = '#ffaa00';
            }
        } catch (e) { }
    }

    badge.textContent = text;
    badge.style.color = color;
}

function _createVideoRow(index, defaultImage, titleText) {
    const row = document.createElement('div');
    row.className = 'video-row';
    row.id = `video-row-${index}`;
    row.dataset.videoIndex = String(index);
    row.dataset.defaultImage = String(defaultImage || '');

    // ============ COL 1: INPUT IMAGE ============
    const inputCol = document.createElement('div');
    inputCol.className = 'video-col input';

    const inputLabel = document.createElement('div');
    inputLabel.style.cssText = 'font-size: 11px; font-weight: 900; color: var(--text-soft); text-align: center;';
    inputLabel.textContent = `VIDEO ${index}`;

    const inputImg = document.createElement('img');
    inputImg.alt = 'input';
    inputImg.style.cssText = 'width: 100%; max-height: 160px; object-fit: contain; background: rgba(0,0,0,0.3); border-radius: 10px; border: 1px solid var(--border-color);';
    if (defaultImage) {
        inputImg.src = defaultImage;
    } else {
        inputImg.style.display = 'none';
    }

    inputCol.appendChild(inputLabel);
    inputCol.appendChild(inputImg);

    // ============ COL 2: PROMPTS ============
    const promptsCol = document.createElement('div');
    promptsCol.className = 'video-col prompts';

    const promptsLabel = document.createElement('div');
    promptsLabel.className = 'prompts-label';
    promptsLabel.textContent = 'PROMPTS';

    const sceneList = document.createElement('div');
    sceneList.className = 'scene-list';
    sceneList.id = `video-prompts-list-${index}`;

    // Load existing prompts
    const rawScenes = String(row.dataset.scenes || '');
    if (rawScenes) {
        try {
            const scenes = JSON.parse(rawScenes) || [];
            if (Array.isArray(scenes) && scenes.length > 0) {
                scenes.forEach((scene, idx) => {
                    const item = document.createElement('div');
                    item.className = 'scene-item';
                    const num = document.createElement('span');
                    num.className = 'scene-num';
                    num.textContent = idx + 1;
                    const text = document.createElement('span');
                    text.className = 'scene-prompt' + (!scene.prompt ? ' empty' : '');
                    text.textContent = scene.prompt || 'Chưa có prompt';
                    item.appendChild(num);
                    item.appendChild(text);
                    sceneList.appendChild(item);
                });
            } else {
                sceneList.innerHTML = `<div class="scene-item"><span class="scene-num">1</span><span class="scene-prompt empty">Chưa có prompt — bấm Thiết lập</span></div>`;
            }
        } catch (e) {
            sceneList.innerHTML = `<div class="scene-item"><span class="scene-num">1</span><span class="scene-prompt empty">Chưa có prompt — bấm Thiết lập</span></div>`;
        }
    } else {
        sceneList.innerHTML = `<div class="scene-item"><span class="scene-num">1</span><span class="scene-prompt empty">Chưa có prompt — bấm Thiết lập</span></div>`;
    }

    const statusText = document.createElement('div');
    statusText.className = 'scene-status';
    statusText.id = `video-scene-status-${index}`;

    promptsCol.appendChild(promptsLabel);
    promptsCol.appendChild(sceneList);
    promptsCol.appendChild(statusText);

    // ============ COL 3: VIDEO PREVIEW ============
    const previewCol = document.createElement('div');
    previewCol.className = 'video-col preview';
    previewCol.id = `video-preview-col-${index}`;

    const placeholder = document.createElement('div');
    placeholder.className = 'preview-placeholder';
    placeholder.innerHTML = '<i class="fas fa-film"></i><span>Chưa có video</span>';

    const previewPlay = document.createElement('div');
    previewPlay.className = 'preview-play';
    const playBtn = document.createElement('div');
    playBtn.className = 'play-btn';
    previewPlay.appendChild(playBtn);

    previewCol.appendChild(placeholder);
    previewCol.appendChild(previewPlay);

    previewCol.onclick = async () => {
        const rowEl = document.getElementById(`video-row-${index}`);
        const url = rowEl ? String(rowEl.dataset.resultUrl || '') : '';
        if (!url) return;

        const ok = await _waitUrlReady(url, 12000);
        if (!ok) {
            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Video đang được chuẩn bị, vui lòng thử lại sau vài giây');
            } else {
                alert('Video đang được chuẩn bị, vui lòng thử lại sau vài giây');
            }
            return;
        }

        const freshUrl = url + (url.includes('?') ? '&' : '?') + `v=${Date.now()}`;
        if (typeof window.openVideoOverlay === 'function') {
            window.openVideoOverlay(freshUrl, `Video ${index}`);
        } else if (typeof openVideoOverlay === 'function') {
            openVideoOverlay(freshUrl, `Video ${index}`);
        } else {
            window.open(freshUrl, '_blank');
        }
    };

    // ============ COL 4: ACTIONS ============
    const actionsCol = document.createElement('div');
    actionsCol.className = 'video-col actions';

    const btnSetting = document.createElement('button');
    btnSetting.className = 'btn-row btn-setting';
    btnSetting.id = `video-btn-setting-${index}`;
    btnSetting.textContent = '⚙ THIẾT LẬP';

    const btnCreate = document.createElement('button');
    btnCreate.className = 'btn-row btn-create';
    btnCreate.id = `video-btn-create-${index}`;
    btnCreate.textContent = '▶ TẠO VIDEO';

    const btnDelete = document.createElement('button');
    btnDelete.className = 'btn-row btn-delete';
    btnDelete.id = `video-btn-delete-${index}`;
    btnDelete.textContent = '✕ XÓA';

    const resultLink = document.createElement('div');
    resultLink.className = 'result-link';
    resultLink.id = `video-result-link-${index}`;

    actionsCol.appendChild(btnSetting);
    actionsCol.appendChild(btnCreate);
    actionsCol.appendChild(btnDelete);
    actionsCol.appendChild(resultLink);

    btnSetting.onclick = async () => {
        const modal = _ensureVideoSettingsModal();
        modal.dataset.videoIndex = String(index);
        modal.style.display = 'flex';

        const closeBtn = document.getElementById('videoSettingsCloseBtn');
        if (closeBtn) {
            closeBtn.onclick = () => {
                modal.style.display = 'none';
            };
        }

        const confirmBtn = document.getElementById('videoSettingsConfirmBtn');
        if (confirmBtn) {
            confirmBtn.onclick = () => {
                const scriptSelect = document.getElementById('videoScriptSelect');
                const scriptName = scriptSelect ? String(scriptSelect.value || '') : '';

                const rowEl = document.getElementById(`video-row-${index}`);
                const defaultImage = rowEl ? String(rowEl.dataset.defaultImage || '') : '';
                if (rowEl) {
                    rowEl.dataset.scriptName = scriptName;

                    const sceneItems = document.querySelectorAll('#videoSceneContainer .scene-item');
                    const scenes = Array.from(sceneItems).map((el, i) => {
                        const promptEl = el.querySelector('textarea[data-role="scene-prompt"]');
                        const prompt = promptEl ? String(promptEl.value || '') : '';
                        const overrideImage = String(el.dataset.sceneImage || '');
                        const image = (overrideImage && overrideImage !== defaultImage) ? overrideImage : '';
                        return {
                            scene: i + 1,
                            prompt,
                            image,
                        };
                    });
                    rowEl.dataset.scenes = JSON.stringify(scenes);
                    _updatePromptsList(index);
                }

                modal.style.display = 'none';
            };
        }

        modal.onclick = (e) => {
            if (e && e.target === modal) {
                modal.style.display = 'none';
            }
        };

        const addPromptBtn = document.getElementById('videoSettingsAddPromptBtn');
        if (addPromptBtn) {
            addPromptBtn.onclick = () => {
                const container = document.getElementById('videoSceneContainer');
                if (!container) return;

                if (container.querySelectorAll('.scene-item').length === 0) {
                    container.innerHTML = '';
                }

                const rowEl = document.getElementById(`video-row-${index}`);
                const defaultImage = rowEl ? String(rowEl.dataset.defaultImage || '') : '';
                const nextIdx = container.querySelectorAll('.scene-item').length;
                const scene = { scene: nextIdx + 1, prompt: '', image: '' };
                const block = _createVideoSceneBlock(scene, nextIdx, index, defaultImage);
                container.appendChild(block);
                _renumberVideoSceneItems();
            };
        }

        await _loadVideoScriptList();
        const scriptSelect = document.getElementById('videoScriptSelect');
        if (scriptSelect) {
            const rowEl = document.getElementById(`video-row-${index}`);
            const savedScript = rowEl ? String(rowEl.dataset.scriptName || '') : '';
            scriptSelect.value = savedScript;
            scriptSelect.onchange = async () => {
                const rowEl = document.getElementById(`video-row-${index}`);
                if (rowEl) {
                    rowEl.dataset.scriptName = scriptSelect.value;
                    rowEl.dataset.scenes = '';
                }
                await _loadVideoScript(scriptSelect.value, index);
                _updatePromptsList(index);
            };
        }
        _updatePromptsList(index);

        const rowElForLoad = document.getElementById(`video-row-${index}`);
        const savedScenesRaw = rowElForLoad ? String(rowElForLoad.dataset.scenes || '') : '';
        if (savedScenesRaw) {
            try {
                const savedScenes = JSON.parse(savedScenesRaw);
                if (Array.isArray(savedScenes) && savedScenes.length > 0) {
                    _renderVideoScenes(savedScenes, index);
                } else {
                    await _loadVideoScript((scriptSelect ? scriptSelect.value : ''), index);
                }
            } catch (e) {
                await _loadVideoScript((scriptSelect ? scriptSelect.value : ''), index);
            }
        } else {
            await _loadVideoScript((scriptSelect ? scriptSelect.value : ''), index);
        }
    };

    btnCreate.onclick = async () => {
        if (typeof window._toggleOneVideo === 'function') {
            await window._toggleOneVideo(index);
        }
    };

    btnDelete.onclick = () => {
        try { row.remove(); } catch (e) {
            if (row && row.parentNode) row.parentNode.removeChild(row);
        }
        _persistTaoVideoStateNow();
    };

    // ============ APPEND ALL COLUMNS ============
    row.appendChild(inputCol);
    row.appendChild(promptsCol);
    row.appendChild(previewCol);
    row.appendChild(actionsCol);
    return row;
}

function initTaoVideoPage() {
    const addBtn = document.getElementById('btn-add-video');
    const startBtn = document.getElementById('btn-start-video');
    const saveBtn = document.getElementById('btn-save-video');
    const displayArea = document.getElementById('video-display-area');
    if (!addBtn || !displayArea) return;

    try {
        const musicInput = document.getElementById('musicSelect');
        const randomMusicCb = document.getElementById('random-music-checkbox');
        if (musicInput && randomMusicCb) {
            const syncRandomState = () => {
                const v = String(musicInput.value || '').trim();
                const picked = !!(v && !v.toLowerCase().startsWith('none'));
                if (picked) {
                    randomMusicCb.checked = false;
                }
            };
            musicInput.addEventListener('input', syncRandomState);
            musicInput.addEventListener('change', syncRandomState);
            try { syncRandomState(); } catch (e) { }
        }
    } catch (e) { }

    window.getVideoTaskIdsFromUI = () => {
        try {
            const rows = Array.from(displayArea.querySelectorAll('.video-row'));
            return rows
                .map((r) => String((r && r.dataset && r.dataset.taskId) ? r.dataset.taskId : '').trim())
                .filter((x) => !!x);
        } catch (e) {
            return [];
        }
    };

    window.saveVideoResultsFromUI = async () => {
        const rows = Array.from(displayArea.querySelectorAll('.video-row'));
        const taskIds = rows
            .map((r) => String((r && r.dataset && r.dataset.taskId) ? r.dataset.taskId : '').trim())
            .filter((x) => !!x);

        if (taskIds.length === 0) {
            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Không có video nào để lưu');
            } else {
                alert('Không có video nào để lưu');
            }
            return { ok: false, empty: true };
        }

        try {
            const res = await fetch('/save_video_results', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_ids: taskIds }),
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok || !body.ok) {
                const msg = body && body.error ? body.error : 'Không thể lưu video';
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay(msg);
                } else {
                    alert(msg);
                }
                return { ok: false, error: msg };
            }

            const urls = body && body.result_urls ? body.result_urls : {};
            rows.forEach((rowEl) => {
                const tid = String(rowEl.dataset.taskId || '').trim();
                const newUrl = urls && tid ? String(urls[tid] || '').trim() : '';
                if (!newUrl) return;
                rowEl.dataset.resultUrl = newUrl;
                const idx = parseInt(String(rowEl.dataset.videoIndex || ''), 10) || 0;
                if (idx > 0) {
                    _setVideoResultLink(idx, newUrl);
                    const playBtn = document.getElementById(`video-play-btn-${idx}`);
                    if (playBtn) playBtn.style.display = 'flex';
                    _setVideoSceneStatus(idx, 'Đã lưu');
                }
            });

            try {
                displayArea.innerHTML = '';
                displayArea.classList.remove('is-visible');
            } catch (e) { }

            try {
                localStorage.removeItem(_videoStorageKey());
            } catch (e) { }

            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Đã lưu thành công');
            } else {
                alert('Đã lưu thành công');
            }
            return { ok: true };
        } catch (e) {
            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Lỗi lưu video');
            } else {
                alert('Lỗi lưu video');
            }
            return { ok: false, error: 'Lỗi lưu video' };
        }
    };

    if (saveBtn) {
        saveBtn.onclick = async () => {
            if (typeof window.saveVideoResultsFromUI === 'function') {
                await window.saveVideoResultsFromUI();
            }
        };
    }

    addBtn.onclick = () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.multiple = true;
        input.onchange = (e) => {
            const files = Array.from(e && e.target && e.target.files ? e.target.files : []);
            if (files.length === 0) return;

            displayArea.classList.add('is-visible');

            let nextIndex = _getNextVideoIndex(displayArea);
            files.forEach((file) => {
                const reader = new FileReader();
                reader.onload = (ev) => {
                    const src = String(ev && ev.target ? ev.target.result : '');
                    if (!src) return;
                    const row = _createVideoRow(nextIndex, src);
                    displayArea.appendChild(row);
                    _persistTaoVideoStateNow();
                    nextIndex += 1;
                };
                reader.readAsDataURL(file);
            });
        };
        input.click();
    };

    try {
        const saved = _safeJsonParse(localStorage.getItem(_videoStorageKey()), null);
        const rows = saved && Array.isArray(saved.rows) ? saved.rows : [];
        if (rows.length > 0) {
            displayArea.classList.add('is-visible');
            try {
                rows.sort((a, b) => (parseInt(String(a.videoIndex || 0), 10) || 0) - (parseInt(String(b.videoIndex || 0), 10) || 0));
            } catch (e) { }

            rows.forEach((it) => {
                const idx = parseInt(String(it.videoIndex || ''), 10) || 0;
                if (idx <= 0) return;
                const row = _createVideoRow(idx, String(it.defaultImage || ''));
                try {
                    row.dataset.effectKey = String(it.effectKey || '');
                    row.dataset.scriptName = String(it.scriptName || '');
                    row.dataset.scenes = String(it.scenes || '');
                    row.dataset.taskId = String(it.taskId || '');
                    row.dataset.resultUrl = String(it.resultUrl || '');
                    row.dataset.progressPercent = String(it.progressPercent || '');
                    row.dataset.sceneIndex = String(it.sceneIndex || '');
                    row.dataset.totalScenes = String(it.totalScenes || '');
                    row.dataset.phase = String(it.phase || '');
                    row.dataset.status = String(it.status || '');
                } catch (e) { }

                displayArea.appendChild(row);

                try {
                    if (row.dataset.resultUrl) {
                        const playBtn = document.getElementById(`video-play-btn-${idx}`);
                        if (playBtn) playBtn.style.display = 'flex';
                        _setVideoResultLink(idx, row.dataset.resultUrl);
                    }
                } catch (e) { }

                try {
                    const p = parseInt(String(row.dataset.progressPercent || ''), 10);
                    const sIdx = parseInt(String(row.dataset.sceneIndex || ''), 10);
                    const sTot = parseInt(String(row.dataset.totalScenes || ''), 10);
                    if (Number.isFinite(p) || Number.isFinite(sIdx) || Number.isFinite(sTot)) {
                        _setVideoProgress(idx, Number.isFinite(p) ? p : 0, Number.isFinite(sIdx) ? sIdx : null, Number.isFinite(sTot) ? sTot : null);
                    }
                } catch (e) { }

                try {
                    const st = String(row.dataset.status || '');
                    const ph = String(row.dataset.phase || '');
                    if (st || ph) {
                        _setVideoSceneStatus(idx, ph || st);
                    }
                } catch (e) { }
            });
        }
    } catch (e) { }

    try {
        if (!window.__taoVideoPersistBound) {
            window.__taoVideoPersistBound = true;
            window.addEventListener('beforeunload', () => {
                try { _persistTaoVideoStateNow(); } catch (e) { }
            });
        }
    } catch (e) { }

    let _createVideosPollingTimer = null;
    let _createVideosRunning = false;
    let _createVideosPending = null; // task_id -> videoIndex

    window._toggleOneVideo = async (videoIndex) => {
        const idx = parseInt(String(videoIndex || ''), 10) || 0;
        if (idx <= 0) return;
        const rowEl = document.getElementById(`video-row-${idx}`);
        if (!rowEl) return;

        const btn = document.getElementById(`video-btn-create-${idx}`);
        const isRunning = !!(btn && String(btn.dataset.running || '') === '1');
        const taskId = String(rowEl.dataset.taskId || '').trim();

        if (isRunning && taskId) {
            try {
                await fetch('/cancel_video_task', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId }),
                });
            } catch (e) { }

            if (_createVideosPending && _createVideosPending[taskId]) {
                delete _createVideosPending[taskId];
            }
            _setRowCreateBtnState(idx, false);
            _setVideoSceneStatus(idx, 'Đã hủy');
            return;
        }

        const rows = Array.from(displayArea.querySelectorAll('.video-row'));
        if (rows.length === 0) return;

        const modelSelect = document.getElementById('model-select');
        const provider = modelSelect ? String(modelSelect.options[modelSelect.selectedIndex].textContent || '') : '';

        const aspectSelect = document.getElementById('aspect_ratio');
        const ratio = aspectSelect ? String(aspectSelect.value || '9:16').trim() : '9:16';

        const qualitySelect = document.getElementById('video-quality-select');
        const quality = qualitySelect ? String(qualitySelect.value || '1080p').trim() : '1080p';

        const resultFolderLabel = document.getElementById('resultFolderLabel');
        const out_dir_label = resultFolderLabel ? String(resultFolderLabel.textContent || '').trim() : '';
        if (!out_dir_label || out_dir_label.toLowerCase().includes('thư mục')) {
            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Vui lòng chọn thư mục lưu kết quả');
            } else {
                alert('Vui lòng chọn thư mục lưu kết quả');
            }
            return;
        }

        const maxTabsInput = document.getElementById('max-tabs-input');
        let max_tabs = 5;
        if (maxTabsInput) {
            const n = parseInt(String(maxTabsInput.value || '').trim(), 10);
            if (Number.isFinite(n) && n > 0) max_tabs = n;
        }

        const musicInput = document.getElementById('musicSelect');
        const randomMusicCb = document.getElementById('random-music-checkbox');
        const useRandomMusic = !!(randomMusicCb && randomMusicCb.checked);

        let music_url = '';
        let music_name = '';
        if (useRandomMusic && Array.isArray(window.__musicList) && window.__musicList.length > 0) {
            const selectable = window.__musicList.filter((x) => x && String(x.name || '').trim());
            if (selectable.length > 0) {
                const pick = selectable[Math.floor(Math.random() * selectable.length)];
                music_name = String(pick.name || '').trim();
                music_url = String(pick.url || '').trim();
            }
        } else if (musicInput) {
            const v = String(musicInput.value || '').trim();
            if (v && !v.toLowerCase().startsWith('none')) {
                music_name = v;
                music_url = (window.__musicUrlByName && window.__musicUrlByName[v]) ? String(window.__musicUrlByName[v] || '').trim() : '';
            }
        }

        const task = _collectOneVideoTaskFromRow(rowEl);

        // reset UI
        _setVideoProgress(idx, 0, null, null);
        _setVideoSceneStatus(idx, '');
        _setVideoResultLink(idx, '');
        _setRowCreateBtnState(idx, true);
        _setVideoSceneStatus(idx, 'Đang tạo cảnh 1');

        _persistTaoVideoStateNow();

        // Get Grok duration if Grok is selected
        let grok_duration = '6s';
        if (provider && provider.toLowerCase().includes('grok')) {
            const durationSelect = document.getElementById('grok-video-duration');
            if (durationSelect) {
                grok_duration = String(durationSelect.value || '6s').trim();
            }
        }

        // Get Veo3 video quality if Veo3 is selected
        let veo3_video_quality = null;
        if (provider && (provider.includes('Veo3') || provider.includes('veo3'))) {
            const veo3QualitySelect = document.getElementById('veo3-video-quality');
            if (veo3QualitySelect) {
                veo3_video_quality = String(veo3QualitySelect.value || 'Veo 3.1 - Lite [Lower Priority]').trim();
                console.log('[Veo3 Video] 🔍 DEBUG: veo3_video_quality from frontend:', veo3_video_quality);
            }
        }

        try {
            const payload = {
                provider,
                out_dir_label,
                max_tabs,
                ratio,
                quality,
                music_url,
                music_name,
                grok_duration,
                tasks: [task],
            };
            if (veo3_video_quality) {
                payload.veo3_video_quality = veo3_video_quality;
            }
            const res = await fetch('/create_videos_batch_start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data || data.ok !== true) {
                const msg = data && data.error ? data.error : 'Không thể bắt đầu tạo video';
                try {
                    if (data && data.redirect_to_payment && typeof window.showPaymentOverlay === 'function') {
                        window.showPaymentOverlay(msg);
                    }
                } catch (e) { }
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay(msg);
                } else {
                    alert(msg);
                }
                _setRowCreateBtnState(idx, false);
                return;
            }

            let newTaskId = '';
            try {
                const mappings = Array.isArray(data.tasks) ? data.tasks : [];
                const expectedFormId = String(task && task.form_id ? task.form_id : '').trim();
                const found = mappings.find(m => m && String(m.form_id || '').trim() === expectedFormId);
                if (found && found.task_id) {
                    newTaskId = String(found.task_id || '').trim();
                }
                // Fallback: if server did not echo form_id as expected, but we only requested 1 task,
                // use the first returned mapping so polling still works.
                if (!newTaskId && mappings.length === 1 && mappings[0] && mappings[0].task_id) {
                    newTaskId = String(mappings[0].task_id || '').trim();
                }
            } catch (e) {
                newTaskId = '';
            }

            if (newTaskId) {
                rowEl.dataset.taskId = newTaskId;
                _createVideosPending = _createVideosPending || {};
                _createVideosPending[newTaskId] = idx;
            }

            await _pollOnce();
            if (!_createVideosPollingTimer) {
                _createVideosPollingTimer = setInterval(_pollOnce, 1500);
            }
        } catch (e) {
            _setRowCreateBtnState(idx, false);
        }
    };

    const _stopPolling = () => {
        if (_createVideosPollingTimer) {
            clearInterval(_createVideosPollingTimer);
            _createVideosPollingTimer = null;
        }
        _createVideosPending = null;
        _createVideosRunning = false;
    };

    const _pollOnce = async () => {
        if (!_createVideosPending) return;
        const ids = Object.keys(_createVideosPending);
        if (ids.length === 0) {
            _stopPolling();
            if (startBtn) startBtn.textContent = 'Bắt đầu';
            return;
        }

        const checks = ids.map(async (taskId) => {
            const videoIndex = _createVideosPending[taskId];
            try {
                const res = await fetch(`/task_video?task_id=${encodeURIComponent(taskId)}`);
                const body = await res.json().catch(() => ({}));
                if (!res.ok || !body || body.ok !== true) {
                    return;
                }

                const rowEl = document.getElementById(`video-row-${videoIndex}`);
                if (rowEl && String(rowEl.dataset.remerging || '') === '1') {
                    return;
                }
                const status = String(body.status || '');
                const progress = body.progress_percent;
                const sceneIndex = body.scene_index;
                const totalScenes = body.total_scenes;
                const phase = String(body.phase || '');
                const resultUrl = String(body.result_url || '');
                if (progress !== undefined && progress !== null) {
                    _setVideoProgress(videoIndex, progress, sceneIndex, totalScenes);
                }

                if (phase === 'downloading') {
                    _setVideoSceneStatus(videoIndex, 'Đang tải video');
                }

                if (status === 'completed') {
                    _setVideoSceneStatus(videoIndex, 'Hoàn tất');
                    if (resultUrl) {
                        _setVideoResultLink(videoIndex, resultUrl);
                        if (rowEl) rowEl.dataset.resultUrl = resultUrl;
                        const playBtn = document.getElementById(`video-play-btn-${videoIndex}`);
                        if (playBtn) playBtn.style.display = 'flex';
                    }

                    _setRowCreateBtnState(videoIndex, false);
                    delete _createVideosPending[taskId];
                    return;
                }

                if (status === 'failed') {
                    const err = String(body.error || 'Lỗi');
                    _setVideoSceneStatus(videoIndex, `Lỗi: ${err}`);
                    _setRowCreateBtnState(videoIndex, false);
                    delete _createVideosPending[taskId];
                    return;
                }

                if (status === 'cancelled') {
                    const err = String(body.error || 'Đã hủy');
                    _setVideoSceneStatus(videoIndex, `Đã hủy: ${err}`);
                    _setRowCreateBtnState(videoIndex, false);
                    delete _createVideosPending[taskId];
                    return;
                }

                if (phase === 'merging') {
                    _setVideoSceneStatus(videoIndex, 'Đang ghép video');
                    return;
                }

                if (sceneIndex && totalScenes) {
                    _setVideoSceneStatus(videoIndex, `Đang tạo cảnh ${sceneIndex}/${totalScenes}`);
                } else if (sceneIndex) {
                    _setVideoSceneStatus(videoIndex, `Đang tạo cảnh ${sceneIndex}`);
                }
            } catch (e) {
                // ignore transient
            }
        });

        await Promise.all(checks);
    };

    if (startBtn) {
        startBtn.onclick = async () => {
            if (_createVideosRunning) {
                _stopPolling();
                try {
                    await fetch('/cancel_create_videos_batch', { method: 'POST' });
                } catch (e) { }
                startBtn.textContent = 'Bắt đầu';
                _setAllRowCreateBtnState(false);
                return;
            }

            const rows = Array.from(displayArea.querySelectorAll('.video-row'));
            if (rows.length === 0) {
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay('Vui lòng thêm ảnh để tạo video');
                } else {
                    alert('Vui lòng thêm ảnh để tạo video');
                }
                return;
            }

            const modelSelect = document.getElementById('model-select');
            const provider = modelSelect ? String(modelSelect.options[modelSelect.selectedIndex].textContent || '') : '';

            const aspectSelect = document.getElementById('aspect_ratio');
            const ratio = aspectSelect ? String(aspectSelect.value || '9:16').trim() : '9:16';

            const qualitySelect = document.getElementById('video-quality-select');
            const quality = qualitySelect ? String(qualitySelect.value || '1080p').trim() : '1080p';

            const resultFolderLabel = document.getElementById('resultFolderLabel');
            const out_dir_label = resultFolderLabel ? String(resultFolderLabel.textContent || '').trim() : '';
            if (!out_dir_label || out_dir_label.toLowerCase().includes('thư mục')) {
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay('Vui lòng chọn thư mục lưu kết quả');
                } else {
                    alert('Vui lòng chọn thư mục lưu kết quả');
                }
                return;
            }

            const maxTabsInput = document.getElementById('max-tabs-input');
            let max_tabs = 5;
            if (maxTabsInput) {
                const n = parseInt(String(maxTabsInput.value || '').trim(), 10);
                if (Number.isFinite(n) && n > 0) max_tabs = n;
            }

            const musicInput = document.getElementById('musicSelect');
            const randomMusicCb = document.getElementById('random-music-checkbox');
            const useRandomMusic = !!(randomMusicCb && randomMusicCb.checked);

            let music_url = '';
            let music_name = '';
            if (useRandomMusic && Array.isArray(window.__musicList) && window.__musicList.length > 0) {
                const selectable = window.__musicList.filter((x) => x && String(x.name || '').trim());
                if (selectable.length > 0) {
                    const pick = selectable[Math.floor(Math.random() * selectable.length)];
                    music_name = String(pick.name || '').trim();
                    music_url = String(pick.url || '').trim();
                }
            } else if (musicInput) {
                const v = String(musicInput.value || '').trim();
                if (v && !v.toLowerCase().startsWith('none')) {
                    music_name = v;
                    music_url = (window.__musicUrlByName && window.__musicUrlByName[v]) ? String(window.__musicUrlByName[v] || '').trim() : '';
                }
            }

            const tasks = rows.map((rowEl) => {
                const videoIndex = parseInt(String(rowEl.dataset.videoIndex || ''), 10) || 0;
                const form_id = `video_${videoIndex}`;
                const defaultImage = String(rowEl.dataset.defaultImage || '');
                const effect_key = String(rowEl.dataset.effectKey || '');

                let scenes = [];
                const raw = String(rowEl.dataset.scenes || '');
                if (raw) {
                    try { scenes = JSON.parse(raw) || []; } catch (e) { scenes = []; }
                }
                if (!Array.isArray(scenes) || scenes.length === 0) {
                    scenes = [{ scene: 1, prompt: '', image: '' }];
                }

                const normalizedScenes = scenes.map((s, i) => {
                    const prompt = String((s && s.prompt) ? s.prompt : '').trim();
                    const overrideImage = String((s && s.image) ? s.image : '');
                    const image = overrideImage ? overrideImage : defaultImage;
                    return { scene: i + 1, prompt, image };
                });

                return { form_id, scenes: normalizedScenes, effect_key };
            }).filter(t => t && t.form_id);

            // reset UI
            rows.forEach((rowEl) => {
                const idx = parseInt(String(rowEl.dataset.videoIndex || ''), 10) || 0;
                _setVideoProgress(idx, 0, null, null);
                _setVideoSceneStatus(idx, '');
                _setVideoResultLink(idx, '');
            });

            _setAllRowCreateBtnState(true);

            startBtn.textContent = 'Dừng';
            _createVideosRunning = true;

            try {
                const res = await fetch('/create_videos_batch_start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider,
                        out_dir_label,
                        max_tabs,
                        ratio,
                        quality,
                        music_url,
                        music_name,
                        tasks,
                    }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || !data || data.ok !== true) {
                    const msg = data && data.error ? data.error : 'Không thể bắt đầu tạo video';
                    try {
                        if (data && data.redirect_to_payment && typeof window.showPaymentOverlay === 'function') {
                            window.showPaymentOverlay(msg);
                        }
                    } catch (e) { }
                    if (typeof window.showSuccessOverlay === 'function') {
                        window.showSuccessOverlay(msg);
                    } else {
                        alert(msg);
                    }
                    _stopPolling();
                    startBtn.textContent = 'Bắt đầu';
                    return;
                }

                const mappings = Array.isArray(data.tasks) ? data.tasks : [];
                _createVideosPending = {};
                mappings.forEach((m) => {
                    if (!m || !m.task_id || !m.form_id) return;
                    const mForm = String(m.form_id || '');
                    const idx = parseInt(mForm.replace(/^video_/, ''), 10);
                    if (!Number.isFinite(idx) || idx <= 0) return;
                    _createVideosPending[String(m.task_id)] = idx;

                    const rowEl = document.getElementById(`video-row-${idx}`);
                    if (rowEl) rowEl.dataset.taskId = String(m.task_id);
                });

                await _pollOnce();
                if (_createVideosRunning) {
                    _createVideosPollingTimer = setInterval(_pollOnce, 1500);
                }
            } catch (e) {
                console.error('start videos error', e);
                _stopPolling();
                startBtn.textContent = 'Bắt đầu';
            }
        };
    }
}

window.PageInits = window.PageInits || {};
window.PageInits['tao-video'] = initTaoVideoPage;

