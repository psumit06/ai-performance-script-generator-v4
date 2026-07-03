// App State
let selectedFile = null;
let selectedCsvFiles = [];
let selectedRulesFile = null;
let functionalParamCandidates = [];
let functionalParamReviewed = false;
let generatedJmxContent = null;
let currentTab = 'dagTab';
let llmProviderStatus = null;

const providerLabels = {
    gemini: 'Gemini',
    claude: 'Claude',
    openai: 'OpenAI',
    grok: 'Grok',
    groq: 'Groq',
    github: 'GitHub Models'
};

// Initialize Lucide Icons on Load
document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();
    initDragAndDrop();
    initCsvDragAndDrop();
    initFunctionalParameterization();
    initAiToggle();
    initAppAlert();
    loadLlmProviderStatus();
});

function initAppAlert() {
    const closeBtn = document.getElementById('appAlertClose');
    closeBtn.addEventListener('click', () => {
        document.getElementById('appAlert').classList.add('hidden');
    });
}

function resetFunctionalParameterizationReview() {
    functionalParamCandidates = [];
    functionalParamReviewed = false;
    const panel = document.getElementById('paramReviewPanel');
    const list = document.getElementById('paramCandidateList');
    const summary = document.getElementById('paramReviewSummary');
    if (panel) panel.classList.add('hidden');
    if (list) list.innerHTML = '';
    if (summary) summary.textContent = 'No candidates analyzed';
    const filterSrc = document.getElementById('paramFilterSource');
    const filterConf = document.getElementById('paramFilterConfidence');
    if (filterSrc) filterSrc.value = 'all';
    if (filterConf) filterConf.value = 'all';
    const selectAll = document.getElementById('paramSelectAll');
    if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
}

function initFunctionalParameterization() {
    const toggle = document.getElementById('functionalParamEnabled');
    const rulesDropzone = document.getElementById('rulesDropzone');
    const rulesFileInput = document.getElementById('rulesFileInput');
    const rulesUploadGroup = document.getElementById('rulesUploadGroup');
    const selectHighConfBtn = document.getElementById('selectHighConfidenceBtn');
    const deselectAllBtn = document.getElementById('deselectAllBtn');
    const selectAllCb = document.getElementById('paramSelectAll');
    const filterSource = document.getElementById('paramFilterSource');
    const filterConfidence = document.getElementById('paramFilterConfidence');

    rulesDropzone.addEventListener('click', () => rulesFileInput.click());
    rulesDropzone.addEventListener('dragover', (e) => { e.preventDefault(); rulesDropzone.classList.add('dragover'); });
    rulesDropzone.addEventListener('dragleave', () => rulesDropzone.classList.remove('dragover'));
    rulesDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        rulesDropzone.classList.remove('dragover');
        const file = Array.from(e.dataTransfer.files).find(f => f.name.endsWith('.json'));
        if (file) handleRulesFileSelect(file);
    });
    rulesFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleRulesFileSelect(e.target.files[0]);
    });

    toggle.addEventListener('change', () => {
        console.log(`[DEBUG] Toggle changed. checked=${toggle.checked}, selectedFile=${selectedFile ? selectedFile.name : 'NULL'}`);
        if (toggle.checked) {
            rulesUploadGroup.classList.remove('hidden');
            if (selectedFile) {
                analyzeParameterizationCandidates();
            } else {
                const panel = document.getElementById('paramReviewPanel');
                const summary = document.getElementById('paramReviewSummary');
                const list = document.getElementById('paramCandidateList');
                panel.classList.remove('hidden');
                summary.textContent = 'Waiting for file';
                list.innerHTML = '<div class="param-empty">Upload a Postman collection or HAR file to auto-detect parameterizable values.</div>';
            }
        } else {
            rulesUploadGroup.classList.add('hidden');
            resetFunctionalParameterizationReview();
            selectedRulesFile = null;
            updateRulesDropzoneUI();
        }
    });

    selectHighConfBtn.addEventListener('click', () => {
        functionalParamCandidates.forEach(c => {
            if (c.confidence === 'high') c.selected_by_default = true;
        });
        renderParamCandidates(getFilteredCandidates());
        syncSelectAllCheckbox();
    });

    deselectAllBtn.addEventListener('click', () => {
        functionalParamCandidates.forEach(c => { c.selected_by_default = false; });
        renderParamCandidates(getFilteredCandidates());
        syncSelectAllCheckbox();
    });

    selectAllCb.addEventListener('change', () => {
        const checked = selectAllCb.checked;
        getFilteredCandidates().forEach(c => { c.selected_by_default = checked; });
        renderParamCandidates(getFilteredCandidates());
    });

    filterSource.addEventListener('change', () => {
        renderParamCandidates(getFilteredCandidates());
        syncSelectAllCheckbox();
    });
    filterConfidence.addEventListener('change', () => {
        renderParamCandidates(getFilteredCandidates());
        syncSelectAllCheckbox();
    });
}

function getFilteredCandidates() {
    const src = document.getElementById('paramFilterSource').value;
    const conf = document.getElementById('paramFilterConfidence').value;
    return functionalParamCandidates.filter(c => {
        if (src !== 'all' && c.source !== src) return false;
        if (conf !== 'all' && c.confidence !== conf) return false;
        return true;
    });
}

function syncSelectAllCheckbox() {
    const filtered = getFilteredCandidates();
    const selectAllCb = document.getElementById('paramSelectAll');
    if (filtered.length === 0) {
        selectAllCb.checked = false;
        selectAllCb.indeterminate = false;
    } else {
        const selectedCount = filtered.filter(c => c.selected_by_default).length;
        selectAllCb.checked = selectedCount === filtered.length;
        selectAllCb.indeterminate = selectedCount > 0 && selectedCount < filtered.length;
    }
}

function handleRulesFileSelect(file) {
    selectedRulesFile = file;
    updateRulesDropzoneUI();
    logTerminal(`[Functional Param] Loaded replacement rules: ${file.name} (${formatBytes(file.size)})`, 'system');
    if (document.getElementById('functionalParamEnabled').checked && selectedFile) {
        logTerminal(`[Functional Param] Re-analyzing with rules + auto-detected candidates...`, 'system');
        analyzeParameterizationCandidates();
    } else if (document.getElementById('functionalParamEnabled').checked && !selectedFile) {
        logTerminal(`[Functional Param] Rules loaded. Upload a Postman collection to analyze candidates.`, 'system');
    }
}

function updateRulesDropzoneUI() {
    const rulesDropzone = document.getElementById('rulesDropzone');
    const rulesDropzoneText = document.getElementById('rulesDropzoneText');
    if (selectedRulesFile) {
        const maxLen = 22;
        const displayName = selectedRulesFile.name.length > maxLen
            ? selectedRulesFile.name.substring(0, maxLen) + '...'
            : selectedRulesFile.name;
        rulesDropzoneText.textContent = displayName;
        rulesDropzone.classList.add('has-file');
    } else {
        rulesDropzoneText.innerHTML = 'Optional <strong>replacement rules JSON</strong>';
        rulesDropzone.classList.remove('has-file');
    }
}

async function analyzeParameterizationCandidates() {
    console.log(`[DEBUG] analyzeParameterizationCandidates called. selectedFile=${selectedFile ? selectedFile.name : 'NULL'}`);
    if (!selectedFile) return;

    const panel = document.getElementById('paramReviewPanel');
    const summary = document.getElementById('paramReviewSummary');
    const list = document.getElementById('paramCandidateList');

    panel.classList.remove('hidden');
    summary.textContent = 'Analyzing candidates...';
    list.innerHTML = '<div class="param-loading">Scanning requests for parameterizable values...</div>';

    const formData = new FormData();
    formData.append('file', selectedFile);
    selectedCsvFiles.forEach(csv => formData.append('csv_files', csv));
    if (selectedRulesFile) {
        formData.append('replacement_rules', selectedRulesFile);
    }

    try {
        const response = await fetch('/api/analyze-parameterization', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const data = await response.json();
            const detail = data.detail || {};
            const message = detail.message || `Analysis failed with HTTP ${response.status}.`;
            summary.textContent = 'Analysis failed';
            list.innerHTML = `<div class="param-error">${message}</div>`;
            logTerminal(`[Functional Param] ${message}`, 'error');
            return;
        }

        const data = await response.json();
        console.log(`[DEBUG] analyze response: candidate_count=${data.candidate_count}, candidates length=${(data.candidates || []).length}, pre_selected_ids=${(data.pre_selected_ids || []).length}`);
        functionalParamCandidates = data.candidates || [];
        const preSelectedIds = new Set(data.pre_selected_ids || []);

        functionalParamCandidates.forEach(c => {
            if (preSelectedIds.has(c.id)) {
                c.selected_by_default = true;
            }
        });

        functionalParamReviewed = true;

        console.log(`[DEBUG] functionalParamCandidates.length=${functionalParamCandidates.length}, filtered=${getFilteredCandidates().length}`);

        if (functionalParamCandidates.length === 0) {
            summary.textContent = 'No candidates found';
            list.innerHTML = '<div class="param-empty">No parameterizable values detected in the parsed requests.</div>';
            logTerminal(`[Functional Param] No candidates detected.`, 'system');
        } else {
            const ruleCount = functionalParamCandidates.filter(c => c.source === 'rule').length;
            const autoCount = functionalParamCandidates.filter(c => c.source === 'auto_detected').length;
            const selectedCount = functionalParamCandidates.filter(c => c.selected_by_default).length;
            const rulesLoaded = data.rules_loaded || 0;

            let summaryText = `${functionalParamCandidates.length} candidate(s) \u2014 ${autoCount} auto-detected`;
            if (ruleCount > 0) {
                summaryText += `, ${ruleCount} from rules`;
            }
            summaryText += ` \u2014 ${selectedCount} selected`;
            summary.textContent = summaryText;

            renderParamCandidates(getFilteredCandidates());
            syncSelectAllCheckbox();

            let logMsg = `[Functional Param] Detected ${functionalParamCandidates.length} candidates (${ruleCount} rule-based, ${autoCount} auto-detected, ${selectedCount} pre-selected).`;
            if (rulesLoaded > 0 && autoCount > 0) {
                logMsg += ` Rules and auto-detected candidates merged.`;
            } else if (autoCount > 0 && ruleCount === 0) {
                logMsg += ` Upload a rules JSON to add rule-based candidates.`;
            }
            logTerminal(logMsg, 'success');
        }
    } catch (err) {
        summary.textContent = 'Analysis failed';
        list.innerHTML = `<div class="param-error">Network error: ${err.message}</div>`;
        logTerminal(`[Functional Param] Network error: ${err.message}`, 'error');
    }
}

function renderParamCandidates(candidates) {
    const list = document.getElementById('paramCandidateList');
    list.innerHTML = '';

    if (candidates.length === 0) {
        list.innerHTML = '<div class="param-empty">No candidates match the current filters.</div>';
        return;
    }

    candidates.forEach((candidate, idx) => {
        const card = document.createElement('div');
        card.className = 'param-candidate-card';
        if (candidate.selected_by_default) card.classList.add('selected');

        const confClass = candidate.confidence === 'high' ? 'high'
            : candidate.confidence === 'medium' ? 'medium'
            : 'low';
        const srcClass = candidate.source === 'rule' ? 'rule' : 'auto';
        const checkedAttr = candidate.selected_by_default ? 'checked' : '';
        const srcLabel = candidate.source === 'rule' ? 'Rule' : 'Auto';

        card.innerHTML = `
            <div class="param-card-header">
                <input type="checkbox" id="paramCandidate_${idx}" ${checkedAttr} data-candidate-id="${candidate.id}">
                <span class="param-card-req-name" title="${escapeHtml(candidate.request_name || '')}">${escapeHtml(candidate.request_name || 'Request ' + candidate.request_index)}</span>
                <span class="param-loc-badge">${candidate.location}</span>
                <div class="param-card-badges">
                    <span class="param-badge ${srcClass}">${srcLabel}</span>
                    <span class="param-badge ${confClass}">${candidate.confidence}</span>
                </div>
            </div>
            <div class="param-card-body">
                <div class="param-card-row">
                    <span class="param-card-label">Field</span>
                    <span class="param-card-value" title="${escapeHtml(candidate.field_path)}">${escapeHtml(candidate.field_path)}</span>
                </div>
                <div class="param-card-row">
                    <span class="param-card-label">Value</span>
                    <span class="param-card-value" title="${escapeHtml(candidate.original_value)}">${escapeHtml(candidate.original_value)}</span>
                    <span class="param-card-arrow">&rarr;</span>
                    <span class="param-card-value param-card-replacement">${escapeHtml(candidate.replacement)}</span>
                </div>
                <div class="param-card-row">
                    <span class="param-card-label">Reason</span>
                    <span class="param-card-reason">${escapeHtml(candidate.reason)}</span>
                </div>
            </div>
        `;

        const checkbox = card.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', () => {
            candidate.selected_by_default = checkbox.checked;
            card.classList.toggle('selected', checkbox.checked);
            syncSelectAllCheckbox();
            updateParamSummaryCount();
        });

        list.appendChild(card);
    });
}

function updateParamSummaryCount() {
    const summary = document.getElementById('paramReviewSummary');
    const total = functionalParamCandidates.length;
    const selected = functionalParamCandidates.filter(c => c.selected_by_default).length;
    const ruleCount = functionalParamCandidates.filter(c => c.source === 'rule').length;
    const autoCount = functionalParamCandidates.filter(c => c.source === 'auto_detected').length;
    let text = `${total} candidate(s) \u2014 ${autoCount} auto-detected`;
    if (ruleCount > 0) {
        text += `, ${ruleCount} from rules`;
    }
    text += ` \u2014 ${selected} selected`;
    summary.textContent = text;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function truncateValue(val, maxLen) {
    if (!val) return '';
    return val.length > maxLen ? val.substring(0, maxLen) + '...' : val;
}

function getSelectedParamCandidateIds() {
    return functionalParamCandidates
        .filter(c => c.selected_by_default)
        .map(c => c.id);
}

function initAiToggle() {
    const aiEnabled = document.getElementById('aiEnabled');
    const llmProvider = document.getElementById('llmProvider');
    const llmModel = document.getElementById('llmModel');

    function syncAiControls() {
        const enabled = aiEnabled.checked;
        llmProvider.disabled = !enabled;
        llmModel.disabled = !enabled;
    }

    aiEnabled.addEventListener('change', syncAiControls);
    syncAiControls();
}

async function loadLlmProviderStatus() {
    try {
        const response = await fetch('/api/llm-providers');
        const data = await response.json();
        llmProviderStatus = data;
        const statusText = document.querySelector('.status-text');
        const providerSelect = document.getElementById('llmProvider');
        const modelInput = document.getElementById('llmModel');
        const defaultOption = providerSelect.querySelector('option[value=""]');
        const defaultHint = document.getElementById('llmDefaultHint');
        const configured = data.providers.filter(p => p.configured).length;
        const activeLabel = providerLabels[data.active_provider] || data.active_provider || 'Environment Default';
        statusText.textContent = configured > 0
            ? 'LLM Ready'
            : 'Deterministic Core Ready';
        if (defaultOption) {
            defaultOption.textContent = `Environment Default (${activeLabel})`;
        }
        if (data.active_provider && providerSelect.querySelector(`option[value="${data.active_provider}"]`)) {
            providerSelect.value = data.active_provider;
        }
        if (data.active_model) {
            modelInput.placeholder = `Default: ${data.active_model}`;
        }
        if (defaultHint) {
            defaultHint.textContent = `Default: ${activeLabel}${data.active_model ? ` / ${data.active_model}` : ''}`;
        }
        document.getElementById('llmProvider').addEventListener('change', validateSelectedProvider);
        validateSelectedProvider();
    } catch (err) {
        console.warn('Unable to load LLM provider status', err);
        const defaultHint = document.getElementById('llmDefaultHint');
        if (defaultHint) {
            defaultHint.textContent = 'Default provider unavailable. Check backend connection.';
        }
    }
}

function showUserAlert(message) {
    const alertBox = document.getElementById('appAlert');
    const alertMessage = document.getElementById('appAlertMessage');
    alertMessage.textContent = message;
    alertBox.classList.remove('hidden');
    try {
        window.alert(message);
    } catch (err) {
        console.warn('Browser alert was blocked or unavailable', err);
    }
    logTerminal(`[Configuration Alert] ${message}`, 'error');
}

function validateSelectedProvider() {
    const aiEnabled = document.getElementById('aiEnabled').checked;
    const providerSelect = document.getElementById('llmProvider');
    const selectedProvider = providerSelect.value;
    const alertBox = document.getElementById('appAlert');

    if (!aiEnabled || !selectedProvider || !llmProviderStatus) {
        return true;
    }

    const selected = llmProviderStatus.providers.find(p => p.name === selectedProvider);
    if (selected && !selected.configured) {
        showUserAlert(`The selected LLM provider '${providerLabels[selectedProvider] || selectedProvider}' is not configured properly. Please select a different LLM provider.`);
        return false;
    }

    alertBox.classList.add('hidden');
    return true;
}

// Drag and Drop Ingestion
function initDragAndDrop() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const generateBtn = document.getElementById('generateBtn');

    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });
}

function handleFileSelect(file) {
    console.log(`[DEBUG] handleFileSelect called. file=${file ? file.name : 'NULL'}, toggle=${document.getElementById('functionalParamEnabled').checked}`);
    selectedFile = file;
    const dropzoneText = document.getElementById('dropzoneText');
    const dropzone = document.getElementById('dropzone');
    const generateBtn = document.getElementById('generateBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const downloadBtnMain = document.getElementById('downloadBtnMain');

    // Truncate filename to prevent overflow
    const maxLen = 22;
    const displayName = file.name.length > maxLen 
        ? file.name.substring(0, maxLen) + '...' 
        : file.name;
    
    dropzoneText.textContent = displayName;
    dropzone.classList.add('has-file');
    generateBtn.disabled = false;
    downloadBtn.disabled = true;
    downloadBtnMain.disabled = true;
    generatedJmxContent = null;
    
    logTerminal(`[System] Ingested file: ${file.name} (${formatBytes(file.size)}). Ready for analysis.`, 'system');

    // Re-analyze functional parameterization if toggle is enabled
    if (document.getElementById('functionalParamEnabled').checked) {
        console.log(`[DEBUG] handleFileSelect: toggle is checked, calling analyzeParameterizationCandidates`);
        analyzeParameterizationCandidates();
    } else {
        console.log(`[DEBUG] handleFileSelect: toggle is NOT checked, skipping analysis`);
    }
}

// CSV File Drag and Drop
function initCsvDragAndDrop() {
    const csvDropzone = document.getElementById('csvDropzone');
    const csvFileInput = document.getElementById('csvFileInput');
    const csvFileList = document.getElementById('csvFileList');

    csvDropzone.addEventListener('click', () => csvFileInput.click());

    csvDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        csvDropzone.classList.add('dragover');
    });

    csvDropzone.addEventListener('dragleave', () => {
        csvDropzone.classList.remove('dragover');
    });

    csvDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        csvDropzone.classList.remove('dragover');
        const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.csv'));
        if (files.length > 0) {
            handleCsvFileSelect(files);
        }
    });

    csvFileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files).filter(f => f.name.endsWith('.csv'));
        if (files.length > 0) {
            handleCsvFileSelect(files);
        }
    });
}

function handleCsvFileSelect(files) {
    // Add new files to the list (avoid duplicates)
    files.forEach(file => {
        if (!selectedCsvFiles.find(f => f.name === file.name)) {
            selectedCsvFiles.push(file);
        }
    });
    
    updateCsvFileList();
    
    // Log to terminal
    files.forEach(file => {
        logTerminal(`[CSV] Added parameterization file: ${file.name} (${formatBytes(file.size)})`, 'system');
    });
}

function updateCsvFileList() {
    const csvFileList = document.getElementById('csvFileList');
    csvFileList.innerHTML = '';
    
    selectedCsvFiles.forEach((file, index) => {
        const fileItem = document.createElement('div');
        fileItem.className = 'csv-file-item';
        fileItem.innerHTML = `
            <span class="csv-file-name">${file.name}</span>
            <span class="csv-file-size">${formatBytes(file.size)}</span>
            <button type="button" class="csv-file-remove" onclick="removeCsvFile(${index})" title="Remove file">×</button>
        `;
        csvFileList.appendChild(fileItem);
    });
    
    // Show/hide hint
    const hint = document.getElementById('csvHint');
    if (selectedCsvFiles.length > 0) {
        hint.textContent = `${selectedCsvFiles.length} CSV file(s) will be added as JMeter CSV Data Set Config elements`;
        hint.classList.add('csv-active');
    } else {
        hint.textContent = 'CSV files will be added as JMeter CSV Data Set Config elements';
        hint.classList.remove('csv-active');
    }
}

function removeCsvFile(index) {
    const removed = selectedCsvFiles.splice(index, 1);
    if (removed.length > 0) {
        logTerminal(`[CSV] Removed parameterization file: ${removed[0].name}`, 'system');
    }
    updateCsvFileList();
}

// Stats Range Sliders Value Updater
function updateVal(badgeId, val) {
    const badge = document.getElementById(badgeId);
    if (badgeId === 'rampUpVal') badge.textContent = val + 's';
    else if (badgeId === 'durationVal') badge.textContent = val + 's';
    else if (badgeId === 'thinkTimeVal') badge.textContent = val + 'ms';
    else if (badgeId === 'pacingVal') badge.textContent = val + 'ms';
    else badge.textContent = val;
}

// Tab switcher
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));

    const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(btn => (btn.getAttribute('onclick') || '').includes(tabId));
    if (activeBtn) activeBtn.classList.add('active');

    const activePane = document.getElementById(tabId);
    if (activePane) activePane.classList.add('active');
    
    currentTab = tabId;
}

// Helper: Format Bytes
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Logger helper for terminal
function logTerminal(message, type = 'system') {
    const terminal = document.getElementById('terminalLogs');
    const line = document.createElement('p');
    line.className = `terminal-line ${type}`;
    
    // Add current time prefix
    const time = new Date().toLocaleTimeString();
    line.innerHTML = `<span style="color: #645f8a">[${time}]</span> ${message}`;
    
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
}

// Trigger Pipeline Generation
document.getElementById('generateBtn').addEventListener('click', async () => {
    if (!selectedFile) return;

    const generateBtn = document.getElementById('generateBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const downloadBtnMain = document.getElementById('downloadBtnMain');
    const users = document.getElementById('users').value;
    const rampUp = document.getElementById('rampUp').value;
    const duration = document.getElementById('duration').value;
    const thinkTime = document.getElementById('thinkTime').value;
    const pacing = document.getElementById('pacing').value;
    const aiEnabled = document.getElementById('aiEnabled').checked;
    const llmProvider = document.getElementById('llmProvider').value;
    const llmModel = document.getElementById('llmModel').value.trim();

    if (!validateSelectedProvider()) {
        return;
    }

    // Reset UI state
    generateBtn.disabled = true;
    generateBtn.querySelector('span').textContent = 'Processing Pipeline...';
    hideGithubUpload();
    downloadBtn.disabled = true;
    downloadBtnMain.disabled = true;
    
    document.getElementById('statXmlValue').textContent = '--';
    document.getElementById('statXmlIcon').className = 'stat-detail-icon';
    document.getElementById('statDryRunValue').textContent = '--';
    document.getElementById('statDryRunIcon').className = 'stat-detail-icon';
    document.getElementById('statNoise').textContent = '--';
    document.getElementById('statCorrelations').textContent = '--';
    document.getElementById('statHealed').textContent = '--';

    // Clear previous results
    document.getElementById('terminalLogs').innerHTML = '';
    document.getElementById('dagNodes').innerHTML = '';
    document.getElementById('codeBlock').textContent = '';
    generatedJmxContent = null;

    // Move to logs tab
    switchTab('logsTab');
    
    logTerminal(`[Cognitive Pipeline] Starting JMeter Hybrid Script Generation...`, 'thought');
    logTerminal(aiEnabled
        ? `[LLM Router] AI enabled. Provider=${llmProvider}${llmModel ? `, model=${llmModel}` : ''}.`
        : `[LLM Router] AI disabled. Running deterministic core only.`,
        'system'
    );
    logTerminal(`[Ingestion] Parsing spec: ${selectedFile.name}...`, 'system');
    if (selectedCsvFiles.length > 0) {
        logTerminal(`[CSV Data] Loading ${selectedCsvFiles.length} CSV file(s) for parameterization...`, 'system');
        selectedCsvFiles.forEach(csv => {
            logTerminal(`   -> ${csv.name}`, 'success');
        });
    }
    logTerminal(`[Execution Profile] users=${users}, ramp_up=${rampUp}s, duration=${duration}s, think_time=${thinkTime}ms, pacing=${pacing}ms.`, 'system');

    // Build form data
    const formData = new FormData();
    formData.append('file', selectedFile);
    
    // Add CSV files if any
    selectedCsvFiles.forEach(csvFile => {
        formData.append('csv_files', csvFile);
    });

    const functionalParamEnabled = document.getElementById('functionalParamEnabled').checked;

    const params = new URLSearchParams({
        users,
        ramp_up: rampUp,
        duration,
        think_time: thinkTime,
        pacing,
        ai_enabled: String(aiEnabled),
        functional_parameterization: String(functionalParamEnabled)
    });
    if (aiEnabled && llmProvider) params.set('llm_provider', llmProvider);
    if (aiEnabled && llmModel) params.set('llm_model', llmModel);

    if (functionalParamEnabled) {
        const selectedIds = getSelectedParamCandidateIds();
        params.set('selected_parameterization_ids', JSON.stringify(selectedIds));
        if (selectedRulesFile) {
            formData.append('replacement_rules', selectedRulesFile);
        }
    }

    const queryUrl = `/api/generate-from-file?${params.toString()}`;

    try {
        const response = await fetch(queryUrl, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const data = await response.json();
            const detail = data.detail || {};
            const message = detail.message || data.error || `Generation failed with HTTP ${response.status}.`;
            showUserAlert(message);
            if (detail.code === 'LLM_PROVIDER_NOT_CONFIGURED') {
                document.getElementById('llmProvider').focus();
            }
            generateBtn.disabled = false;
            generateBtn.querySelector('span').textContent = 'Analyze & Generate Script';
            return;
        }

        // Consume SSE stream for real-time logs
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let data = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line in buffer

            let eventType = '';
            let eventData = '';

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    eventData = line.slice(6);
                } else if (line === '' && eventType && eventData) {
                    // Empty line = end of SSE event
                    try {
                        const parsed = JSON.parse(eventData);
                        if (eventType === 'log') {
                            // Real-time log from self-healing loop
                            const logType = parsed.log_type || 'system';
                            if (logType === 'healing') {
                                // Parse healing entry JSON and display with color
                                try {
                                    const entry = JSON.parse(parsed.message);
                                    if (entry.failures && Array.isArray(entry.failures)) {
                                        entry.failures.forEach(f => {
                                            logTerminal(`   -> Fail: ${f.sampler_label} returned [${f.response_code} ${f.response_message}]`, 'error');
                                        });
                                    }
                                    logTerminal(`[AI Self-Healing Agent] Diagnosis: ${entry.diagnosis}`, 'thought');
                                    logTerminal(`[AI Self-Healing Agent] Action Taken: ${entry.action_taken}`, 'highlight');
                                } catch (e) {
                                    logTerminal(parsed.message, 'thought');
                                }
                            } else {
                                logTerminal(parsed.message, logType);
                            }
                        } else if (eventType === 'result') {
                            data = parsed;
                        } else if (eventType === 'error') {
                            showUserAlert(parsed.error || 'An error occurred during generation.');
                            generateBtn.disabled = false;
                            generateBtn.querySelector('span').textContent = 'Analyze & Generate Script';
                            return;
                        }
                    } catch (e) {
                        console.warn('SSE parse error:', e);
                    }
                    eventType = '';
                    eventData = '';
                }
            }
        }

        if (!data) {
            showUserAlert('No result received from server.');
            generateBtn.disabled = false;
            generateBtn.querySelector('span').textContent = 'Analyze & Generate Script';
            return;
        }

        if (data.error) {
            showUserAlert(data.error);
            if (data.traceback) {
                console.error(data.traceback);
            }
            generateBtn.disabled = false;
            generateBtn.querySelector('span').textContent = 'Analyze & Generate Script';
            return;
        }

        // 1. Log Noise Filtering stats
        const allCount = data.endpoints.length;
        const keptCount = data.endpoints.filter(e => e.kept).length;
        const noiseRatio = (((allCount - keptCount) / allCount) * 100).toFixed(1);
        
        logTerminal(`[Smart Filter] Identified ${allCount - keptCount} third-party/noise entries out of ${allCount} total.`, 'highlight');
        logTerminal(`[Smart Filter] Generated HTTP Request Defaults Exclusion Regex: ${data.exclusion_regex}`, 'run');

        // 2. Log Correlation Stats
        logTerminal(`[Correlation Engine] Scanned downstream parameters for high-entropy values.`, 'system');
        logTerminal(`[Correlation Engine] Successfully traced and injected ${data.correlations.length} dynamic tokens upstream.`, 'thought');
        
        data.correlations.forEach(corr => {
            logTerminal(`   -> Birth index [${corr.source_index}] (${corr.extractor_type}) -> downstream index [${corr.target_index}] replaced with \${${corr.var_name}}`, 'success');
        });

        // 3. Log Self-Healing summary
        const validation = data.validation || {};

        if (validation.dry_run_skipped) {
            logTerminal(`[Dry Run Validation] JMeter execution was skipped: ${validation.skip_reason || 'No skip reason provided.'}`, 'error');
            logTerminal(`[Dry Run Validation] Configure JMETER_BIN on the backend to run sampler-level validation.`, 'highlight');
        } else if (validation.jmeter_executed) {
            logTerminal(`[Dry Run Validation] JMeter executed validation JMX.`, 'run');
            if (validation.jtl_path) {
                logTerminal(`[Dry Run Validation] JTL results: ${validation.jtl_path}`, 'system');
            }
            if (validation.log_path) {
                logTerminal(`[Dry Run Validation] JMeter log: ${validation.log_path}`, 'system');
            }
        }
        
        if (data.healing_history.length === 0 && validation.jmeter_executed) {
            logTerminal(`[Dry Run Validation] Iteration 1: XML Passed. Execution ${data.success_rate}% success rate. Script clean.`, 'success');
        } else {
            if (data.success) {
                logTerminal(`[Self-Healing Pipeline] All errors resolved successfully! Final Success Rate: 100%`, 'success');
            } else {
                logTerminal(`[Self-Healing Pipeline] Script generated but failed validation checks: ${data.failed_requests} samplers failing.`, 'error');
            }
        }

        // 4. Update Stats Dashboard
        const xmlIcon = document.getElementById('statXmlIcon');
        const dryRunIcon = document.getElementById('statDryRunIcon');

        // Log CSV files info if any
        if (data.csv_files && data.csv_files.length > 0) {
            logTerminal(`[CSV Data] ${data.csv_files.length} CSV file(s) added to JMX:`, 'success');
            data.csv_files.forEach(csv => {
                logTerminal(`   -> ${csv.filename}: ${csv.variables.length} variables, ${csv.row_count} rows`, 'success');
            });
        }

        // Log functional parameterization info
        if (data.functional_parameterization && data.functional_parameterization.enabled) {
            const fp = data.functional_parameterization;
            logTerminal(`[Functional Param] Applied ${fp.applied_count} of ${fp.candidate_count} candidate(s).`, 'success');
        }

        // XML Validation status
        if (validation.xml_validation_passed) {
            document.getElementById('statXmlValue').textContent = 'Passed';
            xmlIcon.className = 'stat-detail-icon pass';
        } else {
            document.getElementById('statXmlValue').textContent = 'Failed';
            xmlIcon.className = 'stat-detail-icon fail';
        }

        // Dry Run Execution status
        if (validation.dry_run_skipped) {
            document.getElementById('statDryRunValue').textContent = 'Skipped';
            dryRunIcon.className = 'stat-detail-icon skip';
        } else if (data.success_rate === null || data.success_rate === undefined) {
            document.getElementById('statDryRunValue').textContent = '--';
            dryRunIcon.className = 'stat-detail-icon';
        } else {
            const passed = Math.max(0, data.total_requests - data.failed_requests);
            document.getElementById('statDryRunValue').textContent = data.success_rate + '% (' + passed + '/' + data.total_requests + ')';
            dryRunIcon.className = data.success_rate >= 100 ? 'stat-detail-icon pass' : 'stat-detail-icon fail';
        }

        document.getElementById('statNoise').textContent = noiseRatio + '%';
        document.getElementById('statCorrelations').textContent = data.correlations.length;
        document.getElementById('statHealed').textContent = data.healing_history.length;

        // 5. Load Code Tab
        generatedJmxContent = data.jmx_content;
        if (data.execution_profile) {
            const ep = data.execution_profile;
            logTerminal(`[JMX Profile] Applied users=${ep.users}, ramp_up=${ep.ramp_up}s, duration=${ep.duration}s, think_time=${ep.think_time}ms, pacing=${ep.pacing}ms.`, 'success');
        }
        document.getElementById('codeBlock').textContent = data.jmx_content;
        downloadBtn.disabled = false;
        downloadBtnMain.disabled = false;

        // 6. Draw Visual DAG
        drawVisualDAG(data.flow, data.endpoints, data.correlations);
        
        logTerminal(`[System] JMX Generation complete! Ready for download.`, 'success');
        showGithubUpload();
        
        // Auto switch back to DAG Visualizer tab
        setTimeout(() => switchTab('dagTab'), 1200);

    } catch (err) {
        logTerminal(`[Network Error] Failed to communicate with server: ${err.message}`, 'error');
    } finally {
        generateBtn.disabled = false;
        generateBtn.querySelector('span').textContent = 'Analyze & Generate Script';
    }
});

// Download JMX click action
function downloadGeneratedJmx() {
    if (!generatedJmxContent) return;
    
    const blob = new Blob([generatedJmxContent], { type: 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = selectedFile ? selectedFile.name.replace(/\.[^/.]+$/, "") + "_generated.jmx" : "generated_test_plan.jmx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    logTerminal(`[System] Downloaded JMX script successfully.`, 'system');
}

document.getElementById('downloadBtn').addEventListener('click', downloadGeneratedJmx);
document.getElementById('downloadBtnMain').addEventListener('click', downloadGeneratedJmx);

// Draw dynamic visual DAG
function drawVisualDAG(flow, endpoints, correlations) {
    const container = document.getElementById('dagNodes');
    container.innerHTML = ''; // Clear empty state
    
    if (!flow || flow.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i data-lucide="database" class="empty-icon animate-pulse"></i>
                <h3>No transaction flow generated</h3>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    // Step 1: Render each transaction block
    flow.forEach((tx, txIdx) => {
        const txBlock = document.createElement('div');
        txBlock.className = 'dag-tx-block';
        
        // Transaction Title
        const txTitle = document.createElement('div');
        txTitle.className = 'dag-tx-title';
        txTitle.innerHTML = `<i data-lucide="package-open"></i> ${tx.transaction_name}`;
        txBlock.appendChild(txTitle);
        
        // Parallel group wrappers
        const groupWrapper = document.createElement('div');
        groupWrapper.className = 'dag-group-wrapper';
        
        tx.groups.forEach((group, grpIdx) => {
            if (group.length > 1) {
                // Parallel Box Wrapper
                const parallelBox = document.createElement('div');
                parallelBox.className = 'dag-parallel-box';
                parallelBox.innerHTML = `<div class="dag-parallel-tag"><i data-lucide="grid"></i> Parallel Sampler (Concurrent Resources)</div>`;
                
                group.forEach(ep => {
                    parallelBox.appendChild(createNodeElement(ep, correlations));
                });
                
                groupWrapper.appendChild(parallelBox);
            } else {
                // Single request node
                groupWrapper.appendChild(createNodeElement(group[0], correlations));
            }
        });
        
        txBlock.appendChild(groupWrapper);
        container.appendChild(txBlock);
        
        // Add think time pacing bar if think_time is configured between transactions
        if (tx.think_time > 300) {
            const pacingBar = document.createElement('div');
            pacingBar.className = 'pacing-bar';
            pacingBar.textContent = `${(tx.think_time / 1000).toFixed(1)}s delay (Uniform Random deviation applied)`;
            container.appendChild(pacingBar);
        }
    });

    // Step 2: Render excluded noise endpoints (collapsible or grouped at bottom)
    const excludedList = endpoints.filter(e => !e.kept);
    if (excludedList.length > 0) {
        const noiseBlock = document.createElement('div');
        noiseBlock.className = 'dag-tx-block';
        noiseBlock.style.borderColor = 'rgba(255, 51, 102, 0.15)';
        noiseBlock.style.background = 'rgba(255, 51, 102, 0.01)';
        
        const noiseTitle = document.createElement('div');
        noiseTitle.className = 'dag-tx-title';
        noiseTitle.style.color = 'var(--neon-red)';
        noiseTitle.innerHTML = `<i data-lucide="trash-2"></i> Excluded Noise & Third-Party Bloat (${excludedList.length} items dropped)`;
        noiseBlock.appendChild(noiseTitle);
        
        const groupWrapper = document.createElement('div');
        groupWrapper.className = 'dag-group-wrapper';
        
        // Only show first 5 to prevent UI cluttering, with a show all indicator
        excludedList.slice(0, 8).forEach(ep => {
            groupWrapper.appendChild(createNodeElement(ep, correlations));
        });
        
        if (excludedList.length > 8) {
            const moreIndicator = document.createElement('div');
            moreIndicator.style.padding = '8px 16px';
            moreIndicator.style.fontSize = '0.75rem';
            moreIndicator.style.color = 'var(--text-muted)';
            moreIndicator.style.fontStyle = 'italic';
            moreIndicator.textContent = `... and ${excludedList.length - 8} more CDNs, fonts, analytics, and static assets filtered out by the AI model.`;
            groupWrapper.appendChild(moreIndicator);
        }
        
        noiseBlock.appendChild(groupWrapper);
        container.appendChild(noiseBlock);
    }
    
    // Re-trigger Lucide icon instantiation on newly injected elements
    lucide.createIcons();
}

function createNodeElement(ep, correlations) {
    ep = ep || {};
    correlations = correlations || [];
    const node = document.createElement('div');
    const isKept = ep.kept !== false;
    const endpointUrl = ep.url || ep.full_url || ep.path || '';
    const endpointName = ep.name || endpointUrl || 'Unnamed request';
    
    // Check if this endpoint has extractors or replacements (correlated)
    const isCorrelated = correlations.some(c => (c.var_name && endpointUrl.includes(c.var_name)) || (ep.extractors && ep.extractors.length > 0));
    
    let nodeClasses = 'dag-node-item';
    if (!isKept) nodeClasses += ' excluded';
    else if (isCorrelated) nodeClasses += ' correlated';
    
    node.className = nodeClasses;
    
    // Left area (method, url)
    const leftArea = document.createElement('div');
    leftArea.className = 'dag-node-left';
    
    const method = ep.method ? ep.method.toUpperCase() : 'GET';
    const methodClass = method.toLowerCase();
    
    leftArea.innerHTML = `
        <span class="method-tag ${methodClass}">${method}</span>
        <span class="node-url" title="${endpointUrl}">${endpointName}</span>
    `;
    
    node.appendChild(leftArea);
    
    // Right area (status badges, token lineages)
    const rightArea = document.createElement('div');
    rightArea.className = 'node-badge-container';
    
    if (!isKept) {
        rightArea.innerHTML = `
            <span class="node-badge noise-badge">Removed</span>
            <span class="node-badge reason-badge" title="${ep.reason}">${ep.reason || 'Static Asset'}</span>
        `;
    } else {
        // If it's a correlated birth endpoint (contains extractor)
        let badgesHtml = '';
        
        // Find if this is birth or target
        const isBirth = correlations.some(c => c.source_url === endpointUrl);
        const isTarget = correlations.some(c => c.target_url === endpointUrl);
        
        if (isBirth) {
            badgesHtml += `<span class="node-badge ext-badge"><i data-lucide="key-round" style="width: 10px; height: 10px; display: inline-block;"></i> AI Extractor Injected</span>`;
        }
        if (isTarget) {
            badgesHtml += `<span class="node-badge ext-badge" style="background: rgba(0, 242, 254, 0.08); border-color: rgba(0, 242, 254, 0.3); color: var(--neon-blue);"><i data-lucide="repeat" style="width: 10px; height: 10px; display: inline-block;"></i> Dynamic Variable</span>`;
        }
        
        rightArea.innerHTML = badgesHtml;
    }
    
    node.appendChild(rightArea);
    return node;
}

// =====================================
// GitHub Upload
// =====================================
const githubUploadGroup = document.getElementById('githubUploadGroup');
const githubRepoInput = document.getElementById('githubRepoName');
const uploadToGithubBtn = document.getElementById('uploadToGithubBtn');

// Show GitHub upload group after successful generation
function showGithubUpload() {
    githubUploadGroup.style.display = 'block';
    uploadToGithubBtn.disabled = false;
    lucide.createIcons();
}

// Hide GitHub upload group
function hideGithubUpload() {
    githubUploadGroup.style.display = 'none';
    uploadToGithubBtn.disabled = true;
}

// Enable/disable upload button based on repo name input
githubRepoInput.addEventListener('input', () => {
    uploadToGithubBtn.disabled = !githubRepoInput.value.trim() || !generatedJmxContent;
});

// Upload to GitHub handler
uploadToGithubBtn.addEventListener('click', async () => {
    const repoName = githubRepoInput.value.trim();
    if (!repoName || !generatedJmxContent) return;

    uploadToGithubBtn.disabled = true;
    uploadToGithubBtn.querySelector('span').textContent = 'Uploading...';

    // Build CSV files dict if any
    let csvFilesDict = null;
    if (selectedCsvFiles && selectedCsvFiles.length > 0) {
        csvFilesDict = {};
        for (const csvFile of selectedCsvFiles) {
            const text = await csvFile.text();
            csvFilesDict[csvFile.name] = text;
        }
    }

    try {
        const response = await fetch('/api/github/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo_name: repoName,
                jmx_content: generatedJmxContent,
                jmx_filename: selectedFile ? selectedFile.name.replace(/\.[^/.]+$/, "") + "_generated.jmx" : "generated_test_plan.jmx",
                csv_files: csvFilesDict,
            })
        });

        const result = await response.json();

        if (!response.ok) {
            const detail = result.detail || {};
            const message = detail.message || result.error || `Upload failed with HTTP ${response.status}.`;
            showUserAlert(message);
            return;
        }

        if (result.success) {
            logTerminal(`[GitHub] Successfully uploaded to ${result.owner}/${result.repo}:`, 'success');
            result.uploaded.forEach(f => {
                logTerminal(`   -> ${f.file}`, 'success');
            });
        } else {
            logTerminal(`[GitHub] Upload completed with errors:`, 'error');
            result.errors.forEach(e => {
                logTerminal(`   -> ${e.file}: ${e.error}`, 'error');
            });
        }
    } catch (err) {
        logTerminal(`[GitHub Upload Error] ${err.message}`, 'error');
        showUserAlert(`GitHub upload failed: ${err.message}`);
    } finally {
        uploadToGithubBtn.disabled = false;
        uploadToGithubBtn.querySelector('span').textContent = 'Upload to GitHub';
    }
});
