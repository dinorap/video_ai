// ===============================
// SCRIPT MANAGER
// ===============================
let currentScriptData = [];

async function loadScriptList() {
    try {
        const res = await fetch('/listscripts');
        const names = await res.json().catch(() => []);
        const scriptSelect = document.getElementById('scriptSelect');
        if (!scriptSelect) return;
        scriptSelect.innerHTML = '<option value="" selected>None</option>';
        names.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name.endsWith('.txt') ? name.slice(0, -4) : name;
            scriptSelect.appendChild(opt);
        });
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
    sceneContainer.innerHTML = '';
    
    // Set dynamic height based on viewport
    const viewportHeight = window.innerHeight;
    const containerTop = sceneContainer.getBoundingClientRect().top;
    const availableHeight = viewportHeight - containerTop - 100; // Leave some margin
    sceneContainer.style.maxHeight = Math.max(300, availableHeight) + 'px';
    sceneContainer.style.overflowY = 'auto';
    sceneContainer.style.paddingRight = '8px'; // Space for scrollbar
    
    // Custom scrollbar styling
    const style = document.createElement('style');
    style.textContent = `
        #sceneContainer::-webkit-scrollbar {
            width: 8px;
        }
        #sceneContainer::-webkit-scrollbar-track {
            background: var(--input-bg, rgba(0,0,0,0.3));
            border-radius: 4px;
        }
        #sceneContainer::-webkit-scrollbar-thumb {
            background: var(--border-color, rgba(255,255,255,0.3));
            border-radius: 4px;
        }
        #sceneContainer::-webkit-scrollbar-thumb:hover {
            background: var(--accent-color, #3498db);
        }
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
        
        sceneDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div style="color: var(--text-primary, #fff); font-weight: bold; font-size: 18px;">Cảnh ${scene.scene}</div>
                <button class="delete-scene-btn" data-scene-index="${index}" style="background: var(--accent-red, #e74c3c); color: white; border: none; border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.2s;">Xóa</button>
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
        
        // Add hover effect
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
        
        sceneContainer.appendChild(sceneDiv);
    });
    
    // Bind delete buttons
    document.querySelectorAll('.delete-scene-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const sceneIndex = parseInt(this.dataset.sceneIndex);
            deleteScene(sceneIndex);
        });
    });
    
    // Make scenes draggable
    makeScenesDraggable();
    
    // Update button states after rendering
    updateButtonStates();
}

function deleteScene(sceneIndex) {
    currentScriptData.splice(sceneIndex, 1);
    // Renumber scenes
    currentScriptData.forEach((scene, index) => {
        scene.scene = index + 1;
    });
    renderScenes(currentScriptData);
}

function showDeleteSceneModal(sceneIndex) {
    const modal = document.getElementById('deleteSceneModal');
    const confirmBtn = document.getElementById('deleteSceneConfirmBtn');
    const cancelBtn = document.getElementById('deleteSceneCancelBtn');
    
    if (!modal || !confirmBtn || !cancelBtn) return;
    
    // Remove old event listeners
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
    
    // Add new event listener
    newConfirmBtn.addEventListener('click', () => {
        deleteScene(sceneIndex);
        modal.style.display = 'none';
    });
    
    cancelBtn.onclick = () => {
        modal.style.display = 'none';
    };
    
    modal.style.display = 'flex';
}

function updateButtonStates() {
    const saveScriptBtn = document.getElementById('saveScriptBtn');
    const deleteScriptBtn = document.getElementById('deleteScriptBtn');
    const scriptSelect = document.getElementById('scriptSelect');
    const sceneContainer = document.getElementById('sceneContainer');
    
    // Check if sceneContainer has content (has scene items)
    const hasScenes = sceneContainer && sceneContainer.querySelectorAll('.scene-item').length > 0;
    
    // Check if scriptSelect has a value (not None)
    const hasScriptSelected = scriptSelect && scriptSelect.value && scriptSelect.value !== '';
    
    // Update save button state
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
    
    // Update delete button state
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

function showSaveScriptModal() {
    const modal = document.getElementById('saveScriptModal');
    const input = document.getElementById('saveScriptNameInput');
    const scriptSelect = document.getElementById('scriptSelect');
    
    if (!modal || !input) return;
    
    // Set default filename (without .txt)
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

function showDeleteScriptModal() {
    const modal = document.getElementById('deleteScriptModal');
    const scriptSelect = document.getElementById('scriptSelect');
    
    if (!modal) return;
    
    // Check if there's a script selected
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
        
        // Clear current script data
        currentScriptData = [];
        
        // Clear scene container
        const sceneContainer = document.getElementById('sceneContainer');
        if (sceneContainer) {
            sceneContainer.innerHTML = '';
        }
        
        // Reload script list
        await loadScriptList();
        
        // Reset select to None
        scriptSelect.value = '';
        
        // Show success message
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
    
    if (!modelSelect || !apiKeyInput || !videoPathInput) {
        alert('Vui lòng điền đầy đủ thông tin');
        return;
    }
    
    const model = modelSelect.value;
    const apiKey = apiKeyInput.value.trim();
    const videoPath = videoPathInput.value.trim();
    
    if (!model || !apiKey || !videoPath) {
        alert('Vui lòng điền đầy đủ thông tin');
        return;
    }
    
    try {
        // Show processing overlay
        showProcessingOverlay('Đang tạo kịch bản...');
        
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
        
        closeProcessingOverlay();
        
        if (!res.ok || !body.ok) {
            console.error('Tạo kịch bản thất bại:', body.error);
            alert('Không thể tạo kịch bản: ' + (body.error || 'Lỗi không xác định'));
            return;
        }
        
        // Display generated scenes
        currentScriptData = body.scenes || [];
        renderScenes(body.scenes || []);
        
        // Save to config.json
        await saveToConfig({
            cloneVideoModel: model,
            cloneVideoApiKey: apiKey
        });
        
        // Show success message
        showSuccessOverlay('Đã tạo kịch bản thành công!');
        
        // Clean up temp file after delay
        setTimeout(async () => {
            await cleanupTempFile(body.temp_file);
        }, 5000);
        
    } catch (err) {
        closeProcessingOverlay();
        console.error('Lỗi tạo kịch bản:', err);
        alert('Lỗi khi tạo kịch bản');
    }
}

async function saveToConfig(data) {
    try {
        const res = await fetch('/save_config', {
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

async function cleanupTempFile(tempFile) {
    try {
        const res = await fetch('/cleanup_temp', {
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

async function saveScript(fileName) {
    try {
        // Collect current data from editable forms
        const scenes = collectScenes();
        
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
        
        // Update currentScriptData with saved data
        currentScriptData = scenes;
        
        // Reload script list to show the new file
        await loadScriptList();
        
        // Select the newly saved script
        const scriptSelect = document.getElementById('scriptSelect');
        if (scriptSelect) {
            scriptSelect.value = fileName + '.txt';
            await loadScript(fileName + '.txt');
        }
        
        // Show success message in overlay
        showSuccessOverlay('Đã lưu kịch bản thành công!');
    } catch (err) {
        console.error('Lỗi lưu kịch bản:', err);
        alert('Lỗi khi lưu kịch bản');
    }
}

function showSuccessOverlay(message) {
    // Create overlay element
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
    
    // Auto remove after 2 seconds
    setTimeout(() => {
        overlay.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => {
            document.body.removeChild(overlay);
        }, 300);
    }, 2000);
    
    // Add click to close
    overlay.addEventListener('click', () => {
        overlay.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => {
            if (document.body.contains(overlay)) {
                document.body.removeChild(overlay);
            }
        }, 300);
    });
}

// Add animations
if (!document.getElementById('success-overlay-styles')) {
    const style = document.createElement('style');
    style.id = 'success-overlay-styles';
    style.textContent = `
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        @keyframes fadeOut {
            from { opacity: 1; }
            to { opacity: 0; }
        }
        @keyframes slideUp {
            from { transform: translateY(20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);
}

function makeScenesDraggable() {
    const sceneItems = document.querySelectorAll('.scene-item');
    let draggedElement = null;
    
    sceneItems.forEach(item => {
        item.draggable = true;
        
        item.addEventListener('dragstart', function(e) {
            draggedElement = this;
            this.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
        });
        
        item.addEventListener('dragend', function() {
            this.style.opacity = '';
        });
        
        item.addEventListener('dragover', function(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            
            const afterElement = getDragAfterElement(document.getElementById('sceneContainer'), e.clientY);
            if (afterElement == null) {
                document.getElementById('sceneContainer').appendChild(draggedElement);
            } else {
                document.getElementById('sceneContainer').insertBefore(draggedElement, afterElement);
            }
        });
        
        item.addEventListener('drop', function(e) {
            e.preventDefault();
            // Update scene order in data
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
    // Renumber scenes
    currentScriptData.forEach((scene, index) => {
        scene.scene = index + 1;
    });
}

// ===============================
// COPY USER ID
// ===============================
function copyId(event) {

    if (event) event.stopPropagation();

    const idText = document.getElementById('userId').innerText;

    navigator.clipboard.writeText(idText).then(() => {
        alert('Đã sao chép User ID thành công!');
    });

}



// ===============================
// THEME LIST + CHANGE THEME
// ===============================
// Danh sách theme sẽ được load từ API /listthemes
let THEMES = [];

function changeTheme(themeName) {

    document.body.classList.remove(
        'theme-default',
        'theme-hacker',
        'theme-tech',
        'theme-princess'
    );

    document.body.classList.add(themeName);

    localStorage.setItem('selectedTheme', themeName);

    // Đồng bộ radio trong grid
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
        // dùng url do backend trả về nếu có
        img.src = theme.url || `/templaces/img/${theme.file}`;
        img.style.width = '100px';
        img.style.display = 'block';
        img.style.borderRadius = '6px';
        img.style.border = '2px solid transparent';

        // Click vào ảnh để mở xem lớn trong overlay
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


// ===============================
// IMAGE OVERLAY
// ===============================
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


// ===============================
// AUDIO OVERLAY (NGHE THỬ NHẠC)
// ===============================
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
    console.log('openVideoOverlay called with:', { src, title });
    const overlay = document.getElementById('videoOverlay');
    const video = document.getElementById('videoPlayer');
    const titleEl = document.getElementById('videoTitle');
    
    if (!overlay || !video || !titleEl) {
        console.error('Missing elements:', { overlay: !!overlay, video: !!video, titleEl: !!titleEl });
        return;
    }

    // Set video source and title
    video.src = src;
    video.currentTime = 0;
    if (titleEl && title) {
        titleEl.textContent = title;
    }

    // Show overlay and play
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

function initTabBindings() {
    const tabs = document.querySelectorAll('.horizontal-tabs .tab-item');
    if (!tabs || tabs.length === 0) return;

    tabs.forEach(tab => {
        tab.onclick = async function () {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            const label = (tab.textContent || '').trim();
            const slug = slugifyTabLabel(label);
            const page = `${slug}.html`;

            await loadWorkspace(page);
            initWorkspaceBindings();
        };
    });
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

async function loadWorkspace(page) {
    const root = document.getElementById('workspace-root');
    if (!root) return;

    try {
        const res = await fetch(`/templaces/html/${page}`);
        if (!res.ok) return;
        const html = await res.text();
        root.innerHTML = html;
    } catch (err) {
        console.error('Không thể tải workspace:', err);
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

function initConfirmModalBindings() {
    const btn = document.getElementById('confirmSaveBtn');
    if (!btn) return;

    btn.onclick = function(){

        const userIdSpan = document.getElementById("userId");

        const newId = userIdSpan.innerText.trim();

        if(!newId){

        document.getElementById("modalMessage").innerText="User ID không hợp lệ";

        return;

        }


        // LƯU

        userIdSpan.contentEditable = "false";

        document.getElementById("btn-copy").style.display="inline-block";

        document.getElementById("btn-save").style.display="none";


        // ĐỔI NỘI DUNG MODAL

        document.getElementById("modalMessage").innerText="Lưu thành công ✔";


        // ẨN BUTTON

        const modalButtons = document.querySelector(".modal-buttons");
        if (modalButtons) {
            modalButtons.style.display="none";
        }


        // TỰ ĐÓNG

        setTimeout(()=>{

        closeModal();

        document.getElementById("modalMessage").innerText="Lưu ID mới?";
        if (modalButtons) {
            modalButtons.style.display="flex";
        }

        },1500);

        }
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
// XÓA FILE NHẠC ĐANG CHỌN (CÓ XÁC NHẬN)
// ===============================
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
                        try { musicList.removeChild(opt); } catch (e) {}
                    }
                });
            } catch (e) {}

            try {
                if (window.__musicUrlByName && window.__musicUrlByName[name]) {
                    delete window.__musicUrlByName[name];
                }
                if (Array.isArray(window.__musicList)) {
                    window.__musicList = window.__musicList.filter((x) => x && String(x.name || '').trim() !== name);
                }
            } catch (e) {}

            try {
                if (String(musicInput.value || '').trim() === name) {
                    musicInput.value = '';
                }
            } catch (e) {}

            // Hiển thị "đã xóa" ngay trong overlay
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



// ===============================
// LOAD CONFIG JSON
// ===============================
async function loadConfig() {

    try {

        const response = await fetch('/config/config.json');

        if (!response.ok) {
            throw new Error('Không thể tải file config.json');
        }

        const data = await response.json();


        // VERSION
        const versionElements = document.querySelectorAll('.app-version');

        versionElements.forEach(el => {
            el.innerText = `v${data.VERSION}`;
        });


        // USER ID
        const userIdElement = document.getElementById('userId');

        if (userIdElement) {
            userIdElement.innerText = data.ACCOUNT_ID;
        }


        // Clone Video settings
        const cloneVideoModelSelect = document.getElementById('cloneVideoModelSelect');
        if (cloneVideoModelSelect && data.cloneVideoModel !== undefined && data.cloneVideoModel !== null) {
            try {
                const desired = String(data.cloneVideoModel);
                for (let i = 0; i < cloneVideoModelSelect.options.length; i++) {
                    const opt = cloneVideoModelSelect.options[i];
                    if (String(opt.value) === desired || String(opt.textContent || '').includes(desired)) {
                        cloneVideoModelSelect.selectedIndex = i;
                        break;
                    }
                }
            } catch (_) {}
        }

        const cloneVideoApiKey = document.getElementById('cloneVideoApiKey');
        if (cloneVideoApiKey) {
            cloneVideoApiKey.value = data.cloneVideoApiKey || '';
        }


        console.log("System Ready.");

        window.configData = data;

    }

    catch (error) {

        console.error("Lỗi loading config:", error);

        const versionElements = document.querySelectorAll('.app-version');

        versionElements.forEach(el => el.innerText = "Error");

    }

}



// ===============================
// ENABLE EDIT USER ID
// ===============================
function enableEdit() {

    const userIdSpan = document.getElementById('userId');

    if (userIdSpan.contentEditable === "true") return;

    userIdSpan.contentEditable = "true";

    userIdSpan.focus();


    document.getElementById('btn-copy').style.display = 'none';
    document.getElementById('btn-save').style.display = 'inline-block';

}



// ===============================
// SAVE USER ID
// ===============================
function saveUserId(event){

    if(event) event.stopPropagation();
    
    const modal = document.getElementById("confirmModal");
    
    if (modal) {
        modal.style.display = "flex";
    }
    
    }

    function closeModal(){

        document.getElementById("confirmModal").style.display = "none";
        
        }
// ===============================
// CANCEL EDIT
// ===============================
function cancelEdit() {

    const userIdSpan = document.getElementById('userId');

    userIdSpan.contentEditable = "false";

    document.getElementById('btn-copy').style.display = 'inline-block';
    document.getElementById('btn-save').style.display = 'none';

}



// ===============================
// KEYBOARD CONTROL
// ===============================
document.addEventListener("keydown", function(e) {

    const userIdSpan = document.getElementById("userId");

    if (!userIdSpan) return;


    // ENTER = SAVE
    if (userIdSpan.contentEditable === "true" && e.key === "Enter") {

        e.preventDefault();

        saveUserId(e);

    }


    // ESC = CANCEL
    if (userIdSpan.contentEditable === "true" && e.key === "Escape") {

        cancelEdit();

    }

});



// ===============================
// PAGE LOAD
// ===============================
window.onload = async function() {

    await loadOverlays();
    initConfirmModalBindings();

    initTabBindings();

    await loadWorkspace('home.html');

    // LOAD THEME
    const savedTheme = localStorage.getItem('selectedTheme');

    if (savedTheme) {
        document.body.classList.add(savedTheme);
    }

    initWorkspaceBindings();
};

function initWorkspaceBindings() {
    console.log('initWorkspaceBindings called');
    const cloneVideoChooseBtn = document.getElementById('cloneVideoChooseBtn');
    const cloneVideoFileInput = document.getElementById('cloneVideoFileInput');
    const cloneVideoPathInput = document.getElementById('cloneVideoPathInput');
    const cloneVideoPreview = document.getElementById('cloneVideoPreview');
    const cloneVideoPreviewThumb = document.getElementById('cloneVideoPreviewThumb');
    const cloneVideoPreviewVideo = document.getElementById('cloneVideoPreviewVideo');
    const cloneVideoPlayIcon = document.getElementById('cloneVideoPlayIcon');
    
    console.log('Clone Video elements found:', {
        cloneVideoChooseBtn: !!cloneVideoChooseBtn,
        cloneVideoFileInput: !!cloneVideoFileInput,
        cloneVideoPathInput: !!cloneVideoPathInput,
        cloneVideoPreview: !!cloneVideoPreview,
        cloneVideoPreviewThumb: !!cloneVideoPreviewThumb,
        cloneVideoPreviewVideo: !!cloneVideoPreviewVideo,
        cloneVideoPlayIcon: !!cloneVideoPlayIcon
    });

    if (!window.__cloneVideoState) {
        window.__cloneVideoState = { objectUrl: '', lastFileSig: '', file: null };
    }

    const setCloneVideoObjectUrl = (url) => {
        if (window.__cloneVideoState.objectUrl && window.__cloneVideoState.objectUrl !== url) {
            try { URL.revokeObjectURL(window.__cloneVideoState.objectUrl); } catch (_) {}
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

    const openVideoInOsPlayer = async (file) => {
        if (!file) return;
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/open_video', { method: 'POST', body: formData });
            const body = await res.json().catch(() => ({}));
            if (!res.ok || !body.ok) {
                console.error('Không mở được video bằng hệ điều hành:', body.error);
            }
        } catch (err) {
            console.error('Lỗi gọi /open_video:', err);
        }
    };

    const tryExtractCloneVideoFrame = async (file) => {
        if (!file) return null;

        // tránh gọi lại nếu cùng 1 file (tên + size + lastModified)
        const sig = `${file.name}:${file.size}:${file.lastModified}`;
        if (window.__cloneVideoState.lastFileSig === sig && cloneVideoPreviewThumb && cloneVideoPreviewThumb.src) {
            return cloneVideoPreviewThumb.src;
        }
        window.__cloneVideoState.lastFileSig = sig;

        try {
            const formData = new FormData();
            formData.append('file', file);

            const res = await fetch('/extract_frame', {
                method: 'POST',
                body: formData,
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok || !body.ok || !body.data_url) {
                return null;
            }
            return body.data_url;
        } catch (err) {
            console.error('Lỗi gọi /extract_frame:', err);
            return null;
        }
    };

    if (cloneVideoChooseBtn && cloneVideoFileInput) {
        cloneVideoChooseBtn.onclick = function () {
            cloneVideoFileInput.click();
        };

        cloneVideoFileInput.onchange = async function () {
            if (!this.files || !this.files[0]) return;
            const file = this.files[0];
            window.__cloneVideoState.file = file;
            const url = URL.createObjectURL(file);
            setCloneVideoObjectUrl(url);

            if (cloneVideoPathInput) {
                cloneVideoPathInput.value = file.name;
            }

            // Thumbnail bằng ffmpeg (backend). Nếu có thumb thì ưu tiên hiển thị ảnh để tránh lỗi codec trên browser
            const thumbUrl = await tryExtractCloneVideoFrame(file);
            if (thumbUrl && cloneVideoPreviewThumb) {
                cloneVideoPreviewThumb.src = thumbUrl;
                cloneVideoPreviewThumb.style.display = 'block';
                if (cloneVideoPreviewVideo) {
                    cloneVideoPreviewVideo.style.display = 'none';
                    cloneVideoPreviewVideo.removeAttribute('src');
                    cloneVideoPreviewVideo.load();
                }
            } else {
                if (cloneVideoPreviewThumb) {
                    cloneVideoPreviewThumb.removeAttribute('src');
                    cloneVideoPreviewThumb.style.display = 'none';
                }

                // Chỉ preview bằng <video> nếu browser hỗ trợ, tránh lỗi "No video with supported format..."
                if (cloneVideoPreviewVideo) {
                    const mime = file.type || guessMimeTypeFromName(file.name);
                    const playable = mime ? cloneVideoPreviewVideo.canPlayType(mime) : '';

                    if (playable) {
                        cloneVideoPreviewVideo.style.display = 'block';
                        cloneVideoPreviewVideo.src = url;
                        cloneVideoPreviewVideo.load();
                    } else {
                        cloneVideoPreviewVideo.style.display = 'none';
                        cloneVideoPreviewVideo.removeAttribute('src');
                        cloneVideoPreviewVideo.load();
                    }
                }
            }

            if (cloneVideoPlayIcon) {
                cloneVideoPlayIcon.style.display = 'flex';
            }
        };
    }

    if (cloneVideoPreview) {
        cloneVideoPreview.onclick = async function () {
            const url = window.__cloneVideoState?.objectUrl;
            if (!url) return;
            const title = (cloneVideoPathInput && cloneVideoPathInput.value) ? cloneVideoPathInput.value : 'Xem video';
            const file = window.__cloneVideoState?.file;

            if (!file) return;

            try {
                const formData = new FormData();
                formData.append('file', file);

                const res = await fetch('/transcode_for_web', {
                    method: 'POST',
                    body: formData
                });
                const body = await res.json().catch(() => ({}));

                if (!res.ok || !body.ok) {
                    console.error('Chuyển đổi video thất bại:', body.error);
                    alert('Không thể chuyển đổi video: ' + (body.error || 'Lỗi không xác định'));
                    return;
                }

                // Mở video đã chuyển đổi
                openVideoOverlay(body.url, title);
            } catch (err) {
                console.error('Lỗi chuyển đổi video:', err);
                alert('Lỗi khi chuyển đổi video');
            }
        };
    }

    // Bind script select
    const scriptSelect = document.getElementById('scriptSelect');
    if (scriptSelect) {
        scriptSelect.onchange = async () => {
            await loadScript(scriptSelect.value);
            updateButtonStates();
        };
        // Load script list on init
        loadScriptList();
    }

    // Bind Add Scene button
    const addSceneBtn = document.getElementById('addSceneBtn');
    if (addSceneBtn) {
        addSceneBtn.onclick = () => {
            addScene();
        };
    }

    // Bind Start button
    const startBtn = document.querySelector('.btn-settings');
    if (startBtn) {
        startBtn.onclick = () => {
            generateScript();
        };
    }

    // Bind Save Script button
    const saveScriptBtn = document.getElementById('saveScriptBtn');
    if (saveScriptBtn) {
        saveScriptBtn.onclick = () => {
            showSaveScriptModal();
        };
    }

    // Bind save script modal buttons
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

    // Bind delete script modal buttons
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
    
    // Initial button state update
    updateButtonStates();

    // RENDER THEME GRID (đọc từ danh sách file)
    // tạm thời render (có thể rỗng) rồi sẽ cập nhật sau khi fetch list
    renderThemes();

    // LOAD THEME LIST từ API local /listthemes
    fetch('/listthemes')
        .then(res => res.json())
        .then(list => {
            // map danh sách ảnh thành THEMES
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

    // Đồng bộ radio với theme đang áp dụng
    const currentThemeClass = Array.from(document.body.classList)
        .find(cls => ['theme-default', 'theme-hacker', 'theme-tech', 'theme-princess'].includes(cls)) || 'theme-default';
    const themeInputs = document.querySelectorAll('input[name="theme"]');
    themeInputs.forEach(input => {
        if (input.value === currentThemeClass) input.checked = true;
    });

    // GÁN SỰ KIỆN CHỌN THƯ MỤC KẾT QUẢ
    const resultBtn = document.getElementById('resultFolderBtn');
    const resultInput = document.getElementById('resultFolderInput');
    const resultLabel = document.getElementById('resultFolderLabel');

    if (resultBtn && resultInput && resultLabel) {
        resultBtn.onclick = function () {
            resultInput.click();
        };

        resultInput.onchange = function () {
            if (!this.files || this.files.length === 0) return;

            // Lấy "đường dẫn" thư mục tương đối từ file đầu tiên
            const firstFile = this.files[0];
            let folderPath = '';

            if (firstFile.webkitRelativePath) {
                const parts = firstFile.webkitRelativePath.split('/');
                // Bỏ tên file, chỉ giữ lại phần thư mục
                if (parts.length > 1) {
                    folderPath = parts.slice(0, -1).join('/');
                } else {
                    folderPath = parts[0];
                }
            }

            if (!folderPath) {
                folderPath = 'Đã chọn thư mục';
            }

            // Hiển thị lại "đường dẫn" thư mục lên nút
            resultLabel.textContent = folderPath;
        };
    }

    const uninstallBtn = document.getElementById('uninstallBtn');
    if (uninstallBtn) {
        uninstallBtn.onclick = async function () {
            const ok = await askUninstallConfirm();
            if (!ok) return;

            fetch('/uninstall', {
                method: 'POST',
            })
                .then(res => res.json().then(body => ({ ok: res.ok, body })))
                .then(({ ok, body }) => {
                    if (!ok || !body.ok) {
                        console.error('Gỡ cài đặt thất bại:', body.error);
                        return;
                    }
                })
                .catch(err => {
                    console.error('Lỗi gọi /uninstall:', err);
                });
        };
    }

    // LOAD CONFIG (thông tin từ config.json)
    loadConfig();

    // LOAD MUSIC LIST từ API local /listmusic
    fetch('/listmusic')
        .then(res => res.json())
        .then(list => {
            const musicSelect = document.getElementById('musicSelect');
            if (!musicSelect) return;

            // đảm bảo option đầu tiên là None
            let first = musicSelect.options[0];
            if (!first) {
                first = document.createElement('option');
                first.textContent = 'None (Mặc định)';
                musicSelect.appendChild(first);
            }
            first.value = '';

            // xóa các option nhạc cũ
            while (musicSelect.options.length > 1) {
                musicSelect.remove(1);
            }

            list.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.url;      // URL để phát nhạc
                opt.textContent = item.name;
                musicSelect.appendChild(opt);
            });
        })
        .catch(err => {
            console.error('Không load được danh sách nhạc:', err);
        });

    // GÁN SỰ KIỆN "NGHE THỬ"
    const previewBtn = document.querySelector('.btn-preview');
    if (previewBtn) {
        previewBtn.onclick = function () {
            const musicSelect = document.getElementById('musicSelect');
            if (!musicSelect) return;

            const opt = musicSelect.options[musicSelect.selectedIndex];
            if (!opt || !opt.value) return;

            openAudioOverlay(opt.value, opt.textContent);
        };
    }

    // GÁN SỰ KIỆN "THÊM ÂM THANH"
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
                    if (!musicSelect) return;

                    const opt = document.createElement('option');
                    opt.value = body.url;
                    opt.textContent = body.name;
                    musicSelect.appendChild(opt);
                    musicSelect.value = body.url;

                    // reset input để có thể chọn lại cùng file nếu cần
                    addMusicInput.value = '';
                })
                .catch(err => {
                    console.error('Lỗi gọi /uploadmusic:', err);
                });
        };
    }
}