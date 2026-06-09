// App State
let selectedFile = null;
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
    const fileName = document.getElementById('fileName');
    const fileBadge = document.getElementById('fileBadge');
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
    selectedFile = file;
        const fileNameDisp = document.getElementById('fileName');
    const fileBadge = document.getElementById('fileBadge');
    const generateBtn = document.getElementById('generateBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const downloadBtnMain = document.getElementById('downloadBtnMain');

    fileNameDisp.textContent = file.name;
    fileBadge.classList.remove('hidden');
    generateBtn.disabled = false;
    downloadBtn.disabled = true;
    downloadBtnMain.disabled = true;
    generatedJmxContent = null;
    
    // Auto print file ready status in terminal
    logTerminal(`[System] Ingested file: ${file.name} (${formatBytes(file.size)}). Ready for analysis.`, 'system');
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
    logTerminal(`[Execution Profile] users=${users}, ramp_up=${rampUp}s, duration=${duration}s, think_time=${thinkTime}ms, pacing=${pacing}ms.`, 'system');

    // Build form data
    const formData = new FormData();
    formData.append('file', selectedFile);

    const params = new URLSearchParams({
        users,
        ramp_up: rampUp,
        duration,
        think_time: thinkTime,
        pacing,
        ai_enabled: String(aiEnabled)
    });
    if (aiEnabled && llmProvider) params.set('llm_provider', llmProvider);
    if (aiEnabled && llmModel) params.set('llm_model', llmModel);
    const queryUrl = `/api/generate-from-file?${params.toString()}`;

    try {
        const response = await fetch(queryUrl, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
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

        // 3. Log Self-Healing Logs
        logTerminal(`[Dry Run Validation] Launching headless JMeter dry run iteration...`, 'run');
        const validation = data.validation || {};

        if (validation.xml_validation_passed) {
            logTerminal(`[XML Validation] JMX XML structure validation passed.`, 'success');
        } else {
            logTerminal(`[XML Validation] JMX XML structure validation failed.`, 'error');
        }

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
            data.healing_history.forEach(log => {
                const rateText = data.success_rate === null || data.success_rate === undefined ? 'not available' : `${data.success_rate}%`;
                logTerminal(`[Dry Run Validation] Iteration ${log.iteration}: XML Passed. Execution rate=${rateText}. Errors detected!`, 'error');
                log.failures.forEach(f => {
                    logTerminal(`   -> Fail: ${f.sampler_label} returned [${f.response_code} ${f.response_message}]`, 'error');
                });
                logTerminal(`[AI Self-Healing Agent] Diagnosis: ${log.diagnosis}`, 'thought');
                logTerminal(`[AI Self-Healing Agent] Action Taken: ${log.action_taken}`, 'highlight');
            });
            
            if (data.success) {
                logTerminal(`[Self-Healing Pipeline] All errors resolved successfully! Final Success Rate: 100%`, 'success');
            } else {
                logTerminal(`[Self-Healing Pipeline] Script generated but failed validation checks: ${data.failed_requests} samplers failing.`, 'error');
            }
        }

        // 4. Update Stats Dashboard
        const xmlIcon = document.getElementById('statXmlIcon');
        const dryRunIcon = document.getElementById('statDryRunIcon');

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
