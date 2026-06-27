let currentScriptData = [];

async function loadScriptList() {
    try {
        const res = await fetch('/listscripts');
        const names = await res.json().catch(() => []);
        const scriptSelect = document.getElementById('scriptSelect');
        if (!scriptSelect) return;
        scriptSelect.innerHTML = '';
        let hasTemp = false;
        names.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name.endsWith('.txt') ? name.slice(0, -4) : name;
            scriptSelect.appendChild(opt);
            if (name === '_temp_prompt.txt') hasTemp = true;
        });
        // Add None option at end
        const noneOpt = document.createElement('option');
        noneOpt.value = '';
        noneOpt.textContent = 'None';
        scriptSelect.appendChild(noneOpt);
        // Auto-select _temp_prompt.txt if exists, otherwise None
        if (hasTemp) {
            scriptSelect.value = '_temp_prompt.txt';
            await loadScript('_temp_prompt.txt');
        } else {
            scriptSelect.value = '';
            await loadScript('');
        }
    } catch (err) {
        console.error('Lỗi load danh sách kịch bản:', err);
    }
}

async function loadScript(fileName) {
    if (!fileName) {
        const sceneContainer = document.getElementById('sceneContainer');
        if (sceneContainer) sceneContainer.innerHTML = '';
        currentScriptData = [];
        updateButtonStates();
        return;
    }
    try {
        const res = await fetch(`/load_script?name=${encodeURIComponent(fileName)}`);
        const body = await res.json().catch(() => ({}));
        if (!res.ok || !body.ok || !Array.isArray(body.scenes)) {
            console.error('Không load được kịch bản:', body.error);
            const sceneContainer = document.getElementById('sceneContainer');
            if (sceneContainer) sceneContainer.innerHTML = '<div style="color:#f55;">Không tải được kịch bản</div>';
            currentScriptData = [];
            updateButtonStates();
            return;
        }
        currentScriptData = body.scenes;
        renderScenes(body.scenes);
    } catch (err) {
        console.error('Lỗi gọi /load_script:', err);
        currentScriptData = [];
        updateButtonStates();
    }
}

function renderScenes(scenes) {
    const sceneContainer = document.getElementById('sceneContainer');
    if (!sceneContainer) return;

    // Cập nhật currentScriptData trước khi render để đảm bảo đồng bộ
    currentScriptData = Array.isArray(scenes) ? scenes : [];

    // Lưu scroll position trước khi re-render (tính theo phần tử đang thấy)
    let savedScrollTop = sceneContainer.scrollTop;
    let savedRelativeScroll = 0;
    const scrollHeight = sceneContainer.scrollHeight;
    const clientHeight = sceneContainer.clientHeight;
    if (scrollHeight > clientHeight) {
        savedRelativeScroll = savedScrollTop / (scrollHeight - clientHeight);
    }

    // Tạo document fragment để render không trigger scroll
    const fragment = document.createDocumentFragment();

    const viewportHeight = window.innerHeight;
    const containerTop = sceneContainer.getBoundingClientRect().top;
    // Tăng chiều cao tối đa để hiển thị nhiều cảnh hơn
    const availableHeight = viewportHeight - containerTop - 60;
    // Tăng min-height và giảm buffer để container dài hơn
    sceneContainer.style.maxHeight = Math.max(500, availableHeight) + 'px';
    sceneContainer.style.overflowY = 'auto';
    sceneContainer.style.paddingRight = '8px';

    const style = document.createElement('style');
    style.textContent = `
        #sceneContainer::-webkit-scrollbar { width: 8px; }
        #sceneContainer::-webkit-scrollbar-track { background: var(--input-bg, rgba(0,0,0,0.3)); border-radius: 4px; }
        #sceneContainer::-webkit-scrollbar-thumb { background: var(--border-color, rgba(255,255,255,0.3)); border-radius: 4px; }
        #sceneContainer::-webkit-scrollbar-thumb:hover { background: var(--accent-color, #3498db); }
    `;
    if (!document.getElementById('scene-container-scrollbar-style')) {
        style.id = 'scene-container-scrollbar-style';
        document.head.appendChild(style);
    }

    scenes.forEach((scene, index) => {
        const sceneDiv = document.createElement('div');
        sceneDiv.className = 'scene-item';
        sceneDiv.dataset.sceneIndex = index;
        sceneDiv.style.cssText = 'background: var(--card-bg, rgba(255,255,255,0.08)); border: 2px solid var(--border-color, rgba(255,255,255,0.2)); border-radius: 12px; padding: 16px; margin-bottom: 16px; cursor: move; transition: all 0.3s ease; position: relative;';

        // Ẩn nút xóa nếu chỉ còn 1 cảnh
        const showDeleteBtn = scenes.length > 1;
        const deleteBtnStyle = showDeleteBtn
            ? 'background: var(--accent-red, #e74c3c); color: white; border: none; border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.2s;'
            : 'display: none;';

        sceneDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div style="color: var(--text-primary, #fff); font-weight: bold; font-size: 18px;">Cảnh ${scene.scene}</div>
                <button class="delete-scene-btn" data-scene-index="${index}" style="${deleteBtnStyle}">Xóa</button>
            </div>
            <div style="margin-bottom: 12px;">
                <label style="color: var(--text-secondary, #e0e0e0); font-size: 15px; font-weight: 600; display: block; margin-bottom: 6px;">Prompt:</label>
                <textarea class="scene-prompt" style="width: 100%; min-height: 120px; background: var(--input-bg, rgba(0,0,0,0.5)); border: 2px solid var(--input-border, rgba(255,255,255,0.3)); border-radius: 8px; padding: 12px; color: var(--text-primary, #fff); font-size: 16px; font-weight: 600; line-height: 1.6; resize: vertical; box-sizing: border-box;">${scene.prompt || ''}</textarea>
            </div>
            <div>
                <label style="color: var(--text-secondary, #e0e0e0); font-size: 15px; font-weight: 600; display: block; margin-bottom: 6px;">Audio:</label>
                <input type="text" class="scene-audio" value="${scene.audio || ''}" style="width: 100%; background: var(--input-bg, rgba(0,0,0,0.5)); border: 2px solid var(--input-border, rgba(255,255,255,0.3)); border-radius: 8px; padding: 12px; color: var(--text-primary, #fff); font-size: 16px; font-weight: 600; box-sizing: border-box;">
            </div>
        `;

        sceneDiv.addEventListener('mouseenter', () => {
            sceneDiv.style.borderColor = 'var(--accent-color, #3498db)';
            sceneDiv.style.transform = 'translateY(-2px)';
            sceneDiv.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
        });

        sceneDiv.addEventListener('mouseleave', () => {
            sceneDiv.style.borderColor = 'var(--border-color, rgba(255,255,255,0.2))';
            sceneDiv.style.transform = 'translateY(0)';
            sceneDiv.style.boxShadow = 'none';
        });

        fragment.appendChild(sceneDiv);
    });

    // Xóa container và append fragment trong một lần để tránh scroll nhảy
    sceneContainer.innerHTML = '';
    sceneContainer.appendChild(fragment);

    // Bind sự kiện xóa sau khi append
    sceneContainer.querySelectorAll('.delete-scene-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const sceneIndex = parseInt(this.dataset.sceneIndex);
            deleteScene(sceneIndex);
        });
    });

    makeScenesDraggable();
    updateButtonStates();

    // Khôi phục scroll position sau khi render xong
    const newScrollHeight = sceneContainer.scrollHeight;
    const newClientHeight = sceneContainer.clientHeight;
    if (newScrollHeight > newClientHeight) {
        const newScrollTop = savedRelativeScroll * (newScrollHeight - newClientHeight);
        sceneContainer.scrollTop = Math.max(0, newScrollTop);
    }
}

function deleteScene(sceneIndex) {
    // Không cho xóa nếu chỉ còn 1 cảnh
    if (currentScriptData.length <= 1) {
        return;
    }
    currentScriptData.splice(sceneIndex, 1);
    currentScriptData.forEach((scene, index) => {
        scene.scene = index + 1;
    });
    renderScenes(currentScriptData);
}

function updateButtonStates() {
    const saveScriptBtn = document.getElementById('saveScriptBtn');
    const deleteScriptBtn = document.getElementById('deleteScriptBtn');
    const scriptSelect = document.getElementById('scriptSelect');
    const sceneContainer = document.getElementById('sceneContainer');

    const hasScenes = sceneContainer && sceneContainer.querySelectorAll('.scene-item').length > 0;
    const hasScriptSelected = scriptSelect && scriptSelect.value && scriptSelect.value !== '';

    if (saveScriptBtn) {
        if (hasScenes) {
            saveScriptBtn.disabled = false;
            saveScriptBtn.style.opacity = '1';
            saveScriptBtn.style.cursor = 'pointer';
        } else {
            saveScriptBtn.disabled = true;
            saveScriptBtn.style.opacity = '0.5';
            saveScriptBtn.style.cursor = 'not-allowed';
        }
    }

    if (deleteScriptBtn) {
        if (hasScriptSelected) {
            deleteScriptBtn.disabled = false;
            deleteScriptBtn.style.opacity = '1';
            deleteScriptBtn.style.cursor = 'pointer';
        } else {
            deleteScriptBtn.disabled = true;
            deleteScriptBtn.style.opacity = '0.5';
            deleteScriptBtn.style.cursor = 'not-allowed';
        }
    }
}

function collectScenes() {
    // Đồng bộ hóa từ DOM vào currentScriptData trước khi trả về
    const sceneItems = document.querySelectorAll('.scene-item');
    const scenes = [];

    sceneItems.forEach((item, index) => {
        const prompt = item.querySelector('.scene-prompt')?.value || '';
        const audio = item.querySelector('.scene-audio')?.value || '';

        scenes.push({
            scene: index + 1,
            prompt: prompt,
            audio: audio
        });
    });

    // Cập nhật currentScriptData để giữ đồng bộ với DOM
    currentScriptData = scenes;

    return scenes;
}

function addScene() {
    const newScene = {
        scene: currentScriptData.length + 1,
        prompt: "",
        audio: ""
    };
    currentScriptData.push(newScene);
    renderScenes(currentScriptData);
}

function _parseLinesToScenePrompts(text) {
    return String(text || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line.length > 0);
}

function addManyScenesFromText(text) {
    const prompts = _parseLinesToScenePrompts(text);
    if (prompts.length === 0) {
        return 0;
    }
    prompts.forEach((prompt) => {
        currentScriptData.push({
            scene: currentScriptData.length + 1,
            prompt,
            audio: '',
        });
    });
    currentScriptData.forEach((scene, index) => {
        scene.scene = index + 1;
    });
    renderScenes(currentScriptData);
    return prompts.length;
}

function _readFileAsText(file) {
    return new Promise((resolve, reject) => {
        try {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(reader.error || new Error('Không thể đọc file'));
            reader.readAsText(file);
        } catch (e) {
            reject(e);
        }
    });
}

function _readFileAsArrayBuffer(file) {
    return new Promise((resolve, reject) => {
        try {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error || new Error('Không thể đọc file'));
            reader.readAsArrayBuffer(file);
        } catch (e) {
            reject(e);
        }
    });
}

async function importScenesFromFile(file) {
    const f = file;
    if (!f) return 0;
    const name = String(f.name || '').toLowerCase();
    const ext = name.includes('.') ? name.split('.').pop() : '';

    // Word .doc (binary) not supported reliably in browser
    if (ext === 'doc') {
        alert('File .doc (Word đời cũ) chưa hỗ trợ. Vui lòng lưu lại thành .docx hoặc .txt.');
        return 0;
    }

    let text = '';
    if (ext === 'docx') {
        if (!window.mammoth || typeof window.mammoth.extractRawText !== 'function') {
            alert('Thiếu thư viện đọc .docx. Hãy F5 lại trang hoặc kiểm tra kết nối internet.');
            return 0;
        }
        const buf = await _readFileAsArrayBuffer(f);
        const result = await window.mammoth.extractRawText({ arrayBuffer: buf });
        text = String((result && result.value) ? result.value : '').trim();
    } else {
        // txt / md / csv ...
        text = String(await _readFileAsText(f) || '').trim();
    }

    const count = addManyScenesFromText(text);
    return count;
}

function showAddManyScenesModal() {
    const modal = document.getElementById('addManyScenesModal');
    const input = document.getElementById('addManyScenesInput');
    if (!modal || !input) return;
    input.value = '';
    modal.style.display = 'flex';
    input.focus();
}

function closeAddManyScenesModal() {
    const modal = document.getElementById('addManyScenesModal');
    if (modal) modal.style.display = 'none';
}

function showSaveScriptModal() {
    const modal = document.getElementById('saveScriptModal');
    const input = document.getElementById('saveScriptNameInput');
    const scriptSelect = document.getElementById('scriptSelect');

    if (!modal || !input) return;

    let defaultName = '';
    if (scriptSelect && scriptSelect.value) {
        defaultName = scriptSelect.value.replace('.txt', '');
    }
    input.value = defaultName;

    modal.style.display = 'flex';
    input.focus();
    input.select();
}

function closeSaveScriptModal() {
    const modal = document.getElementById('saveScriptModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function saveScript(fileName) {
    const scenes = collectScenes();

    try {
        const res = await fetch('/save_script', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: fileName,
                scenes: scenes
            })
        });

        const body = await res.json().catch(() => ({}));

        if (!res.ok || !body.ok) {
            console.error('Lưu kịch bản thất bại:', body.error);
            alert('Không thể lưu kịch bản: ' + (body.error || 'Lỗi không xác định'));
            return;
        }

        // Backend removes _temp_prompt.txt on successful save; refresh list
        await loadScriptList();

        const scriptSelect = document.getElementById('scriptSelect');
        if (scriptSelect) {
            const savedFileName = fileName + '.txt';
            scriptSelect.value = savedFileName;
            // Reload lại nội dung kịch bản vừa lưu
            await loadScript(savedFileName);
        }

        showSuccessOverlay('Đã lưu kịch bản thành công!');
    } catch (err) {
        console.error('Lỗi lưu kịch bản:', err);
        alert('Lỗi khi lưu kịch bản');
    }
}

function showDeleteScriptModal() {
    const modal = document.getElementById('deleteScriptModal');
    const scriptSelect = document.getElementById('scriptSelect');

    if (!modal) return;

    if (!scriptSelect || !scriptSelect.value) {
        alert('Vui lòng chọn kịch bản cần xóa');
        return;
    }

    modal.style.display = 'flex';
}

function closeDeleteScriptModal() {
    const modal = document.getElementById('deleteScriptModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function deleteScript() {
    const scriptSelect = document.getElementById('scriptSelect');
    if (!scriptSelect || !scriptSelect.value) {
        alert('Vui lòng chọn kịch bản cần xóa');
        return;
    }

    try {
        const res = await fetch('/delete_script', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: scriptSelect.value
            })
        });

        const body = await res.json().catch(() => ({}));

        if (!res.ok || !body.ok) {
            console.error('Xóa kịch bản thất bại:', body.error);
            alert('Không thể xóa kịch bản: ' + (body.error || 'Lỗi không xác định'));
            return;
        }

        currentScriptData = [];

        const sceneContainer = document.getElementById('sceneContainer');
        if (sceneContainer) {
            sceneContainer.innerHTML = '';
        }

        await loadScriptList();
        scriptSelect.value = '';

        showSuccessOverlay('Đã xóa kịch bản thành công!');
    } catch (err) {
        console.error('Lỗi xóa kịch bản:', err);
        alert('Lỗi khi xóa kịch bản');
    }
}

async function generateScript() {
    const modelSelect = document.getElementById('cloneVideoModelSelect');
    const apiKeyInput = document.getElementById('cloneVideoApiKey');
    const videoPathInput = document.getElementById('cloneVideoPathInput');
    const startBtn = document.getElementById('startBtn');

    if (!modelSelect || !apiKeyInput || !videoPathInput) {
        alert('Vui lòng điền đầy đủ thông tin');
        return;
    }

    const model = modelSelect.value;
    const apiKey = apiKeyInput.value.trim();

    const manualPath = videoPathInput.value.trim();
    const looksLikeAbsWinPath = /^[a-zA-Z]:\\/.test(manualPath);
    const videoPath = looksLikeAbsWinPath
        ? manualPath
        : ((window.__cloneVideoState && window.__cloneVideoState.serverVideoPath)
            ? window.__cloneVideoState.serverVideoPath
            : manualPath);

    if (!model || !apiKey || !videoPath) {
        alert('Vui lòng điền đầy đủ thông tin');
        return;
    }

    try {
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.style.opacity = '0.7';
            startBtn.style.cursor = 'not-allowed';
        }

        const res = await fetch('/generate_script', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                video_path: videoPath,
                model: model,
                api_key: apiKey,
                target_product: 'Video Clone',
                language: 'Vietnamese'
            })
        });

        const body = await res.json().catch(() => ({}));

        if (startBtn) {
            startBtn.disabled = false;
            startBtn.style.opacity = '1';
            startBtn.style.cursor = 'pointer';
        }

        if (!res.ok || !body.ok) {
            console.error('Tạo kịch bản thất bại:', body.error);

            const errMsg = String(body.error || '').trim();
            const isEmptyScenes = errMsg.toLowerCase().includes('empty scenes');
            const isMissingKey = errMsg.toLowerCase().includes('missing api key');
            const isInvalidKey = errMsg.toLowerCase().includes('invalid') && errMsg.toLowerCase().includes('key');

            if (isEmptyScenes || isMissingKey || isInvalidKey) {
                const msg = 'API key đã hết hạn hoặc không hợp lệ. Vui lòng cấp lại API key để tạo kịch bản.';
                if (typeof window.showSuccessOverlay === 'function') {
                    window.showSuccessOverlay(msg);
                } else {
                    alert(msg);
                }
                try { apiKeyInput && apiKeyInput.focus(); } catch (_) { }
                return;
            }

            if (typeof window.showSuccessOverlay === 'function') {
                window.showSuccessOverlay('Không thể tạo kịch bản: ' + (errMsg || 'Lỗi không xác định'));
            } else {
                alert('Không thể tạo kịch bản: ' + (errMsg || 'Lỗi không xác định'));
            }
            return;
        }

        currentScriptData = body.scenes || [];
        renderScenes(body.scenes || []);

        try {
            await loadScriptList();
            const scriptSelect = document.getElementById('scriptSelect');
            if (scriptSelect) {
                scriptSelect.value = '_temp_prompt.txt';
            }

            await loadScript('_temp_prompt.txt');
        } catch (_) {
        }

        await saveToConfig({
            cloneVideoModel: model,
            cloneVideoApiKey: apiKey
        });

        showSuccessOverlay('Đã tạo kịch bản thành công!');
    } catch (err) {
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.style.opacity = '1';
            startBtn.style.cursor = 'pointer';
        }
        console.error('Lỗi tạo kịch bản:', err);
        alert('Lỗi khi tạo kịch bản');
    }
}

async function cleanupTempFile(tempFile) {
    try {
        await fetch('/cleanup_temp', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ temp_file: tempFile })
        });
    } catch (err) {
        console.error('Lỗi cleanup temp file:', err);
    }
}

function makeScenesDraggable() {
    const sceneItems = document.querySelectorAll('.scene-item');
    let draggedElement = null;

    sceneItems.forEach(item => {
        item.draggable = true;

        item.addEventListener('dragstart', function (e) {
            draggedElement = this;
            this.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
        });

        item.addEventListener('dragend', function () {
            this.style.opacity = '';
        });

        item.addEventListener('dragover', function (e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';

            const afterElement = getDragAfterElement(document.getElementById('sceneContainer'), e.clientY);
            if (afterElement == null) {
                document.getElementById('sceneContainer').appendChild(draggedElement);
            } else {
                document.getElementById('sceneContainer').insertBefore(draggedElement, afterElement);
            }
        });

        item.addEventListener('drop', function (e) {
            e.preventDefault();
            updateSceneOrder();
        });
    });
}

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.scene-item:not(.dragging)')];

    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;

        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function updateSceneOrder() {
    const sceneItems = document.querySelectorAll('.scene-item');
    const newOrder = [];

    sceneItems.forEach(item => {
        const index = parseInt(item.dataset.sceneIndex);
        newOrder.push(currentScriptData[index]);
    });

    currentScriptData = newOrder;
    currentScriptData.forEach((scene, index) => {
        scene.scene = index + 1;
    });
}

function initCloneVideoPage() {
    const cloneVideoChooseBtn = document.getElementById('cloneVideoChooseBtn');
    const cloneVideoFileInput = document.getElementById('cloneVideoFileInput');
    const cloneVideoPathInput = document.getElementById('cloneVideoPathInput');
    const cloneVideoPreview = document.getElementById('cloneVideoPreview');
    const cloneVideoPreviewThumb = document.getElementById('cloneVideoPreviewThumb');
    const cloneVideoPreviewVideo = document.getElementById('cloneVideoPreviewVideo');
    const cloneVideoPlayIcon = document.getElementById('cloneVideoPlayIcon');

    if (!window.__cloneVideoState) {
        window.__cloneVideoState = { objectUrl: '', lastFileSig: '', file: null, serverVideoPath: '' };
    }

    const setCloneVideoObjectUrl = (url) => {
        if (window.__cloneVideoState.objectUrl && window.__cloneVideoState.objectUrl !== url) {
            try { URL.revokeObjectURL(window.__cloneVideoState.objectUrl); } catch (_) { }
        }
        window.__cloneVideoState.objectUrl = url;
    };

    const guessMimeTypeFromName = (name) => {
        const lower = String(name || '').toLowerCase();
        if (lower.endsWith('.mp4')) return 'video/mp4';
        if (lower.endsWith('.webm')) return 'video/webm';
        if (lower.endsWith('.ogv') || lower.endsWith('.ogg')) return 'video/ogg';
        if (lower.endsWith('.mov')) return 'video/quicktime';
        return '';
    };

    if (cloneVideoChooseBtn && cloneVideoFileInput) {
        cloneVideoChooseBtn.onclick = function () {
            cloneVideoFileInput.click();
        };

        cloneVideoFileInput.onchange = async function () {
            if (!this.files || !this.files[0]) return;
            const file = this.files[0];
            window.__cloneVideoState.file = file;
            window.__cloneVideoState.serverVideoPath = '';

            if (cloneVideoPathInput) {
                cloneVideoPathInput.value = file.name;
            }

            // Xóa file video cũ trên server trước khi upload file mới
            const oldServerPath = window.__cloneVideoState.serverVideoPath;
            if (oldServerPath) {
                try {
                    await fetch('/cleanup_temp', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ temp_file: oldServerPath })
                    });
                } catch (err) {
                    console.error('Lỗi xóa video cũ:', err);
                }
            }

            // Reset video preview trước khi load video mới
            if (cloneVideoPreviewVideo) {
                cloneVideoPreviewVideo.pause();
                cloneVideoPreviewVideo.removeAttribute('src');
                cloneVideoPreviewVideo.load(); // Force release resources
                cloneVideoPreviewVideo.style.display = 'none';
            }
            if (cloneVideoPreviewThumb) {
                cloneVideoPreviewThumb.removeAttribute('src');
                cloneVideoPreviewThumb.style.display = 'none';
            }
            // Reset container size về mặc định
            if (cloneVideoPreview) {
                cloneVideoPreview.style.maxWidth = '';
                cloneVideoPreview.style.width = '100%';
            }

            // Revoke old blob URL nếu có
            if (window.__cloneVideoState.objectUrl) {
                try {
                    URL.revokeObjectURL(window.__cloneVideoState.objectUrl);
                } catch (_) { }
                window.__cloneVideoState.objectUrl = '';
            }

            try {
                const formData = new FormData();
                formData.append('file', file);

                const uploadRes = await fetch('/upload_temp_video', {
                    method: 'POST',
                    body: formData,
                });
                const uploadBody = await uploadRes.json().catch(() => ({}));

                if (!uploadRes.ok || !uploadBody.ok) {
                    alert('Không thể copy video vào thư mục tạm: ' + (uploadBody.error || 'Lỗi không xác định'));
                    return;
                }

                window.__cloneVideoState.serverVideoPath = uploadBody.video_path;
                const serverFilename = uploadBody.filename || file.name;

                // Tạo server URL để dùng cho cả preview và click xem full
                const serverUrl = `/temp_video/${serverFilename}`;
                setCloneVideoObjectUrl(serverUrl);

                if (cloneVideoPathInput) {
                    const current = String(cloneVideoPathInput.value || '').trim();
                    const isAbs = /^[a-zA-Z]:\\/.test(current);
                    if (!isAbs) {
                        cloneVideoPathInput.value = serverFilename;
                    }
                }

                // Hiển thị video từ server thay vì blob URL
                if (cloneVideoPreviewThumb) {
                    cloneVideoPreviewThumb.removeAttribute('src');
                    cloneVideoPreviewThumb.style.display = 'none';
                }

                if (cloneVideoPreviewVideo) {
                    cloneVideoPreviewVideo.style.display = 'block';
                    // Thêm timestamp để tránh cache browser
                    const timestamp = new Date().getTime();
                    cloneVideoPreviewVideo.src = `${serverUrl}?t=${timestamp}`;
                    cloneVideoPreviewVideo.load();

                    // Tự động điều chỉnh kích thước container dựa trên aspect ratio
                    cloneVideoPreviewVideo.onloadedmetadata = function () {
                        const videoWidth = this.videoWidth;
                        const videoHeight = this.videoHeight;
                        const aspectRatio = videoWidth / videoHeight;

                        if (cloneVideoPreview) {
                            // Video dọc (9:16 hoặc tương tự)
                            if (aspectRatio < 0.75) {
                                cloneVideoPreview.style.maxWidth = '280px';
                                cloneVideoPreview.style.width = '100%';
                            }
                            // Video ngang (16:9 hoặc tương tự)
                            else if (aspectRatio > 1.5) {
                                cloneVideoPreview.style.maxWidth = '100%';
                                cloneVideoPreview.style.width = '100%';
                            }
                            // Video vuông hoặc gần vuông
                            else {
                                cloneVideoPreview.style.maxWidth = '400px';
                                cloneVideoPreview.style.width = '100%';
                            }
                        }
                    };
                }
            } catch (err) {
                console.error('Lỗi gọi /upload_temp_video:', err);
                alert('Lỗi khi copy video vào thư mục tạm');
            }
        };
    }

    if (cloneVideoPreview) {
        cloneVideoPreview.onclick = async function () {
            const url = window.__cloneVideoState?.objectUrl;
            if (!url) return;
            const title = (cloneVideoPathInput && cloneVideoPathInput.value) ? cloneVideoPathInput.value : 'Xem video';
            const serverPath = window.__cloneVideoState?.serverVideoPath;

            // Sử dụng đường dẫn server đã upload thay vì upload lại file
            if (!serverPath) {
                alert('Video chưa được upload. Vui lòng chọn lại video.');
                return;
            }

            try {
                const res = await fetch('/transcode_from_path', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        video_path: serverPath
                    })
                });
                const body = await res.json().catch(() => ({}));

                if (!res.ok || !body.ok) {
                    console.error('Chuyển đổi video thất bại:', body.error);
                    alert('Không thể chuyển đổi video: ' + (body.error || 'Lỗi không xác định'));
                    return;
                }

                openVideoOverlay(body.url, title);
            } catch (err) {
                console.error('Lỗi chuyển đổi video:', err);
                alert('Lỗi khi chuyển đổi video');
            }
        };
    }

    const scriptSelect = document.getElementById('scriptSelect');
    if (scriptSelect) {
        scriptSelect.onchange = async () => {
            await loadScript(scriptSelect.value);
            updateButtonStates();
        };
        // Note: loadScriptList already called once at page init; avoid double load
    }

    const addSceneBtn = document.getElementById('addSceneBtn');
    if (addSceneBtn) {
        addSceneBtn.onclick = () => {
            addScene();
        };
    }

    const addManyScenesBtn = document.getElementById('addManyScenesBtn');
    const addManyScenesConfirmBtn = document.getElementById('addManyScenesConfirmBtn');
    const addManyScenesCancelBtn = document.getElementById('addManyScenesCancelBtn');
    const addManyScenesModal = document.getElementById('addManyScenesModal');
    const addManyScenesInput = document.getElementById('addManyScenesInput');

    if (addManyScenesBtn) {
        addManyScenesBtn.onclick = () => showAddManyScenesModal();
    }
    if (addManyScenesConfirmBtn && addManyScenesInput) {
        addManyScenesConfirmBtn.onclick = () => {
            const count = addManyScenesFromText(addManyScenesInput.value);
            if (count === 0) {
                alert('Vui lòng nhập ít nhất một dòng (mỗi dòng = một cảnh).');
                return;
            }
            closeAddManyScenesModal();
            if (typeof showSuccessOverlay === 'function') {
                showSuccessOverlay(`Đã tạo ${count} cảnh`);
            }
        };
    }
    if (addManyScenesCancelBtn) {
        addManyScenesCancelBtn.onclick = () => closeAddManyScenesModal();
    }
    if (addManyScenesModal) {
        addManyScenesModal.onclick = (e) => {
            if (e && e.target === addManyScenesModal) closeAddManyScenesModal();
        };
    }

    const importScenesBtn = document.getElementById('importScenesBtn');
    const importScenesFileInput = document.getElementById('importScenesFileInput');
    if (importScenesBtn && importScenesFileInput) {
        importScenesBtn.onclick = () => {
            try {
                importScenesFileInput.value = '';
            } catch (_) { }
            importScenesFileInput.click();
        };

        importScenesFileInput.onchange = async function () {
            const file = this.files && this.files[0] ? this.files[0] : null;
            if (!file) return;
            try {
                const count = await importScenesFromFile(file);
                if (count <= 0) {
                    alert('Không tìm thấy dòng nào hợp lệ (mỗi dòng = 1 cảnh).');
                    return;
                }
                if (typeof showSuccessOverlay === 'function') {
                    showSuccessOverlay(`Đã import ${count} cảnh từ file`);
                }
            } catch (e) {
                console.error('Import scenes error:', e);
                alert('Import thất bại: ' + (e && e.message ? e.message : String(e)));
            }
        };
    }

    const startBtn = document.getElementById('startBtn');
    if (startBtn) {
        startBtn.onclick = () => {
            generateScript();
        };
    }

    const saveScriptBtn = document.getElementById('saveScriptBtn');
    if (saveScriptBtn) {
        saveScriptBtn.onclick = () => {
            showSaveScriptModal();
        };
    }

    const saveScriptConfirmBtn = document.getElementById('saveScriptConfirmBtn');
    const saveScriptCancelBtn = document.getElementById('saveScriptCancelBtn');
    const saveScriptNameInput = document.getElementById('saveScriptNameInput');

    if (saveScriptConfirmBtn && saveScriptCancelBtn && saveScriptNameInput) {
        saveScriptConfirmBtn.onclick = async () => {
            const fileName = saveScriptNameInput.value.trim();
            if (!fileName) {
                alert('Vui lòng nhập tên kịch bản');
                return;
            }
            await saveScript(fileName);
            closeSaveScriptModal();
        };

        saveScriptCancelBtn.onclick = () => {
            closeSaveScriptModal();
        };
    }

    const deleteScriptBtn = document.getElementById('deleteScriptBtn');
    const deleteScriptConfirmBtn = document.getElementById('deleteScriptConfirmBtn');
    const deleteScriptCancelBtn = document.getElementById('deleteScriptCancelBtn');

    if (deleteScriptBtn) {
        deleteScriptBtn.onclick = () => {
            showDeleteScriptModal();
        };
    }

    if (deleteScriptConfirmBtn && deleteScriptCancelBtn) {
        deleteScriptConfirmBtn.onclick = async () => {
            await deleteScript();
            closeDeleteScriptModal();
        };

        deleteScriptCancelBtn.onclick = () => {
            closeDeleteScriptModal();
        };
    }

    // Auto-load script list and select _temp_prompt.txt if exists, otherwise None
    loadScriptList();

    updateButtonStates();
}

window.PageInits = window.PageInits || {};
window.PageInits['clone-video'] = initCloneVideoPage;
