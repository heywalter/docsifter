// DocSifter front-end logic

const docsifterNativeFetch = window.fetch.bind(window);
window.fetch = (resource, options = {}) => {
    const method = String(options.method || (resource && resource.method) || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const headers = new Headers(options.headers || {});
        headers.set('X-DocSifter-Request', '1');
        options = { ...options, headers };
    }
    return docsifterNativeFetch(resource, options);
};

class DocumentReviewerApp {
    constructor() {
        this.isProcessing = false;
        this.currentStats = {};
        this.currentWhitelist = [];
        this.whitelistSearchTerm = '';
        this.whitelistCurrentPage = 1;
        this.selectedWhitelistItems = new Set();
        
        this.init();
    }

    t(key, params = {}) {
        return window.I18n ? window.I18n.t(key, params) : key;
    }

    translate(message) {
        return window.I18n ? window.I18n.translateText(message) : message;
    }

    locale() {
        return window.I18n ? window.I18n.locale() : 'zh-CN';
    }

    localize(root = document) {
        if (window.I18n) {
            window.I18n.apply(root);
        }
        return root;
    }

    formatSelectionStats(total, filtered, selected) {
        return this.t('总计: {total} | 筛选: {filtered} | 已选: {selected}', {
            total,
            filtered,
            selected
        });
    }

    init() {
        this.bindEvents();
        this.loadStats();
        this.loadDashboardStatus();
        this.updateLastUpdateTime();
        this.startDashboardRefresh();
        this.loadCurrentModelStatus();

        this.checkAndRestoreRunningTask();
        
        this.loadGithubMonitorStatus();
        
        setInterval(() => {
            this.loadGithubMonitorStatus();
        }, 5000);

        window.addEventListener('i18n:change', () => {
            this.updateLastUpdateTime();
            this.updateProcessButton(this.isProcessing);
            this.refreshLocalizedViews();
            this.localize(document.body);
        });
    }

    refreshLocalizedViews() {
        this.updateWhitelistStats();

        if (!document.getElementById('whitelistModal')?.classList.contains('hidden')) {
            this.renderWhitelistItems();
        }
        if (!document.getElementById('falsePositiveModal')?.classList.contains('hidden')) {
            this.renderFalsePositiveList();
            this.updateFalsePositiveStats();
        }
        if (!document.getElementById('statsModal')?.classList.contains('hidden')) {
            this.loadDetailedStats();
        }
        if (!document.getElementById('configModal')?.classList.contains('hidden')) {
            this.loadConfig();
        }
        if (!document.getElementById('githubMonitorModal')?.classList.contains('hidden')) {
            this.loadGithubMonitorStatus();
            this.loadMonitorLogs();
        }
        if (!document.getElementById('emailNotificationModal')?.classList.contains('hidden')) {
            this.loadEmailConfig();
        }
    }

    bindEvents() {
        document.getElementById('startProcessBtn').addEventListener('click', () => this.startProcessing());
        document.getElementById('viewReportBtn').addEventListener('click', () => this.viewReport());
        document.getElementById('downloadLatestReportBtn').addEventListener('click', () => this.downloadReport());
        document.getElementById('browseBtn').addEventListener('click', () => this.browseDirectory());
        document.getElementById('cancelTaskBtn').addEventListener('click', () => this.cancelCurrentTask());
        
        
        document.getElementById('modelSelect').addEventListener('change', (e) => this.onModelChange(e));

        document.getElementById('configBtn').addEventListener('click', () => this.showConfigModal());
        document.getElementById('statsBtn').addEventListener('click', () => this.showStatsModal());
        document.getElementById('githubMonitorBtn').addEventListener('click', () => this.showGithubMonitorModal());
        document.getElementById('emailNotificationBtn').addEventListener('click', () => this.showEmailNotificationModal());

        const saveRepoConfigBtn = document.getElementById('saveRepoConfigBtn');
        if (saveRepoConfigBtn) {
            saveRepoConfigBtn.addEventListener('click', () => this.saveMonitorRepoConfig());
        }
        const startMonitoringBtn = document.getElementById('startMonitoringBtn');
        if (startMonitoringBtn) {
            startMonitoringBtn.addEventListener('click', () => this.startGithubMonitor());
        }
        const stopMonitoringBtn = document.getElementById('stopMonitoringBtn');
        if (stopMonitoringBtn) {
            stopMonitoringBtn.addEventListener('click', () => this.stopGithubMonitor());
        }
        const refreshTaskHistoryBtn = document.getElementById('refreshTaskHistoryBtn');
        if (refreshTaskHistoryBtn) {
            refreshTaskHistoryBtn.addEventListener('click', () => this.loadTaskHistory());
        }
        const refreshReviewHistoryBtn = document.getElementById('refreshReviewHistoryBtn');
        if (refreshReviewHistoryBtn) {
            refreshReviewHistoryBtn.addEventListener('click', () => this.loadReviewHistory());
        }
        const refreshMonitorLogsBtn = document.getElementById('refreshMonitorLogsBtn');
        if (refreshMonitorLogsBtn) {
            refreshMonitorLogsBtn.addEventListener('click', () => this.loadMonitorLogs());
        }
        const copyMonitorWebhookUrlBtn = document.getElementById('copyMonitorWebhookUrlBtn');
        if (copyMonitorWebhookUrlBtn) {
            copyMonitorWebhookUrlBtn.addEventListener('click', () => this.copyFromInput('monitorWebhookUrl'));
        }
        const copyMonitorWebhookSecretBtn = document.getElementById('copyMonitorWebhookSecretBtn');
        if (copyMonitorWebhookSecretBtn) {
            copyMonitorWebhookSecretBtn.addEventListener('click', () => this.copyFromInput('monitorWebhookSecret'));
        }
        const regenerateMonitorWebhookSecretBtn = document.getElementById('regenerateMonitorWebhookSecretBtn');
        if (regenerateMonitorWebhookSecretBtn) {
            regenerateMonitorWebhookSecretBtn.addEventListener('click', () => this.regenerateWebhookSecret());
        }
        document.getElementById('closeConfigModal').addEventListener('click', () => this.hideConfigModal());
        document.getElementById('closeStatsModal').addEventListener('click', () => this.hideStatsModal());
        document.getElementById('saveConfigBtn').addEventListener('click', () => this.saveConfig());
        document.getElementById('cancelConfigBtn').addEventListener('click', () => this.hideConfigModal());
        
        document.getElementById('whitelistBtn').addEventListener('click', () => this.showWhitelistModal());
        document.getElementById('closeWhitelistModal').addEventListener('click', () => this.hideWhitelistModal());
        document.getElementById('addWhitelistBtn').addEventListener('click', () => this.addWhitelistItem());
        document.getElementById('selectAllWhitelistBtn').addEventListener('click', () => this.selectAllWhitelistItems());
        document.getElementById('clearWhitelistSelectionBtn').addEventListener('click', () => this.clearWhitelistSelection());
        document.getElementById('batchDeleteWhitelistBtn').addEventListener('click', () => this.batchDeleteWhitelist());
        document.getElementById('saveWhitelistBtn').addEventListener('click', () => this.saveWhitelist());
        document.getElementById('cancelWhitelistBtn').addEventListener('click', () => this.hideWhitelistModal());
        document.getElementById('exportWhitelistBtn').addEventListener('click', () => this.exportWhitelist());
        document.getElementById('importWhitelistBtn').addEventListener('click', () => this.importWhitelist());
        document.getElementById('whitelistFileInput').addEventListener('change', (e) => this.handleWhitelistFileImport(e));
        
        document.getElementById('falsePositiveBtn').addEventListener('click', () => this.showFalsePositiveModal());
        document.getElementById('closeFalsePositiveModal').addEventListener('click', () => this.hideFalsePositiveModal());
        
        document.getElementById('addFalsePositiveBtn').addEventListener('click', () => this.showAddFalsePositiveModal());
        document.getElementById('closeAddFalsePositiveModal').addEventListener('click', () => this.hideAddFalsePositiveModal());
        document.getElementById('saveFalsePositiveBtn').addEventListener('click', () => this.saveFalsePositive());
        
        document.getElementById('batchDeleteFalsePositiveBtn').addEventListener('click', () => this.batchDeleteFalsePositive());
        document.getElementById('exportFalsePositiveBtn').addEventListener('click', () => this.exportFalsePositive());
        document.getElementById('importFalsePositiveBtn').addEventListener('click', () => this.importFalsePositive());
        document.getElementById('selectAllFalsePositiveBtn').addEventListener('click', () => this.selectAllFalsePositiveItems());
        document.getElementById('clearFalsePositiveSelectionBtn').addEventListener('click', () => this.clearFalsePositiveSelection());
        document.getElementById('searchFalsePositiveBtn').addEventListener('click', () => this.searchFalsePositive());
        
        document.getElementById('falsePositiveFileInput').addEventListener('change', (e) => this.handleFalsePositiveFileImport(e));
        
        document.getElementById('historyBtn').addEventListener('click', () => this.showHistoryModal());
        document.getElementById('closeHistoryModal').addEventListener('click', () => this.hideHistoryModal());
        document.getElementById('closeHistoryFooterBtn').addEventListener('click', () => this.hideHistoryModal());
        document.getElementById('closeTaskDetailModal').addEventListener('click', () => this.hideTaskDetailModal());
        document.getElementById('closeTaskDetailFooterBtn').addEventListener('click', () => this.hideTaskDetailModal());
        document.getElementById('closeGithubMonitorModal').addEventListener('click', () => this.hideGithubMonitorModal());
        document.getElementById('closeGithubMonitorFooterBtn').addEventListener('click', () => this.hideGithubMonitorModal());
        document.getElementById('closeEmailNotificationModal').addEventListener('click', () => this.hideEmailNotificationModal());
        document.getElementById('closeEmailNotificationFooterBtn').addEventListener('click', () => this.hideEmailNotificationModal());
        
        document.getElementById('logsTab').addEventListener('click', () => this.switchTab('logs'));
        document.getElementById('progressTab').addEventListener('click', () => this.switchTab('progress'));
        
        document.getElementById('newWhitelistItem').addEventListener('input', () => this.showWhitelistSuggestions());
        document.getElementById('newWhitelistItem').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.addWhitelistItem();
        });
        document.getElementById('whitelistSearch').addEventListener('input', () => this.searchWhitelist());
        
        document.getElementById('saveEmailConfigBtn').addEventListener('click', () => this.saveEmailConfig());
        document.getElementById('sendTestEmailBtn').addEventListener('click', () => this.sendTestEmail());

        document.getElementById('configModal').addEventListener('click', (e) => {
            if (e.target.id === 'configModal') this.hideConfigModal();
        });
        document.getElementById('statsModal').addEventListener('click', (e) => {
            if (e.target.id === 'statsModal') this.hideStatsModal();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideConfigModal();
                this.hideStatsModal();
                this.hideWhitelistModal();
                this.hideFalsePositiveModal();
                this.hideAddFalsePositiveModal();
                this.hideHistoryModal();
                this.hideTaskDetailModal();
                this.hideGithubMonitorModal();
                this.hideEmailNotificationModal();
            }
        });
    }

    async startProcessing() {
        if (this.isProcessing) {
            this.showNotification('正在处理中，请稍候...', 'warning');
            return;
        }
        
        return this.startLocalProcessing();
    }
    
    async startLocalProcessing() {
        const directory = document.getElementById('directory').value.trim();
        if (!directory) {
            this.showNotification('请输入要处理的目录路径', 'error');
            return;
        }

        const debugMode = document.getElementById('debugMode').checked;
        const autoGenerate = document.getElementById('autoGenerate').checked;
        const selectedModel = document.getElementById('modelSelect').value;

        this.isProcessing = true;
        this.currentTaskId = null;
        this.showProgress();
        this.updateProcessButton(true);
        this.clearLog();
        this.addLog('开始处理文档...');
        this.updateProgress(10);

        try {
            const response = await fetch('/api/process', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    directory: directory,
                    debug: debugMode,
                    auto_generate: autoGenerate,
                    model: selectedModel
                })
            });
            const result = await response.json();
            if (!response.ok || !result.success || !result.data?.task_id) {
                throw new Error(result.message || '处理失败');
            }

            this.currentTaskId = result.data.task_id;
            this.addLog('任务已启动');
            this.showNotification('任务已启动', 'success');
            this.monitorTaskProgress(this.currentTaskId);
            this.monitorTaskLogs(this.currentTaskId);
            await this.loadDashboardStatus();
        } catch (error) {
            this.addLog(`错误: ${error.message}`);
            this.showNotification('处理失败: ' + error.message, 'error');
            this.isProcessing = false;
            this.currentTaskId = null;
            this.hideProgress();
            this.updateProcessButton(false);
        }
    }
    
    async cancelCurrentTask() {
        if (!this.currentTaskId) {
            this.showNotification('没有正在运行的任务', 'warning');
            return;
        }

        if (!confirm(this.t('确定要取消当前任务吗？'))) {
            return;
        }

        try {
            const response = await fetch('/api/cancel_task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    task_id: this.currentTaskId
                })
            });

            const result = await response.json();
            if (result.success) {
                this.addLog('任务已被取消');
                this.showNotification('任务已取消', 'info');
                this.isProcessing = false;
                this.currentTaskId = null;
                this.updateProcessButton(false);
                this.loadDashboardStatus();
                setTimeout(() => {
                    this.hideProgress();
                }, 1000);
            } else {
                this.showNotification('取消任务失败: ' + result.message, 'error');
            }
        } catch (error) {
            this.showNotification('取消任务失败: ' + error.message, 'error');
        }
    }

    viewReport() {
        const reportType = document.querySelector('input[name="reportType"]:checked')?.value || 'filtered';

        if (reportType === 'filtered') {
            const lastTaskId = this.getLastTaskId();
            if (lastTaskId) {
                this.checkReportExists('/report.html').then(exists => {
                    if (exists) {
                        window.open('/report.html', '_blank');
                    } else {
                        this.showNotification('报告文件不存在，请重新运行纠错任务', 'warning');
                    }
                });
            } else {
                window.open('/report.html', '_blank');
            }
        } else {
            const lastTaskId = this.getLastTaskId();
            if (lastTaskId) {
                const fullReportUrl = `/report_full_${lastTaskId}.html`;
                this.checkReportExists(fullReportUrl).then(exists => {
                    if (exists) {
                        window.open(fullReportUrl, '_blank');
                    } else {
                        this.showNotification('完整版报告不存在，请重新运行纠错任务', 'warning');
                    }
                });
            } else {
                this.showNotification('未找到完整版报告，请重新运行纠错任务', 'warning');
            }
        }
    }

    downloadReport() {
        const reportType = document.querySelector('input[name="reportType"]:checked')?.value || 'filtered';

        const link = document.createElement('a');
        if (reportType === 'filtered') {
            this.checkReportExists('/report.html').then(exists => {
                if (exists) {
                    link.href = '/report.html';
                    link.download = 'ai-review-report-filtered.html';
                    link.click();
                } else {
                    this.showNotification('过滤版报告不存在，请重新运行纠错任务', 'warning');
                }
            });
        } else {
            const lastTaskId = this.getLastTaskId();
            if (lastTaskId) {
                const fullReportUrl = `/report_full_${lastTaskId}.html`;
                this.checkReportExists(fullReportUrl).then(exists => {
                    if (exists) {
                        link.href = fullReportUrl;
                        link.download = 'ai-review-report-full.html';
                        link.click();
                    } else {
                        this.showNotification('完整版报告不存在，请重新运行纠错任务', 'warning');
                    }
                });
            } else {
                this.showNotification('未找到完整版报告，请重新运行纠错任务', 'warning');
            }
        }
    }

    getLastTaskId() {
        return localStorage.getItem('lastTaskId') || null;
    }

    async checkReportExists(url) {
        try {
            const response = await fetch(url, { method: 'HEAD' });
            return response.ok;
        } catch (error) {
            return false;
        }
    }

    async browseDirectory() {
        this.currentBrowsePath = './';
        await this.showDirectoryBrowser();
    }

    async showDirectoryBrowser() {
        try {
            const response = await fetch(`/api/directories?path=${encodeURIComponent(this.currentBrowsePath)}`);
            const result = await response.json();
            
            if (result.success && result.directories.length > 0) {
                this.showDirectoryBrowserModal(result.directories, result.current_path || this.currentBrowsePath);
            } else {
                this.showNotification('无法获取目录列表', 'error');
            }
        } catch (error) {
            console.error('获取目录列表失败:', error);
            this.showNotification('获取目录列表失败', 'error');
        }
    }

    async navigateToDirectory(targetPath) {
        this.currentBrowsePath = targetPath;
        await this.showDirectoryBrowser();
    }

    showDirectoryBrowserModal(directories, currentPath) {
        const existingModal = document.getElementById('directoryBrowserModal');
        if (existingModal) {
            document.body.removeChild(existingModal);
        }
        
        const modal = document.createElement('div');
        modal.id = 'directoryBrowserModal';
        modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
        
        let pathParts;
        if (currentPath === './' || currentPath === '.') {
            pathParts = [];
        } else {
            let cleanPath = currentPath.replace(/^\.\//, '').replace(/\/$/, '');
            pathParts = cleanPath ? cleanPath.split('/') : [];
        }
        const breadcrumbs = [this.t('项目根目录')].concat(pathParts);
        const breadcrumbsHtml = breadcrumbs.map((part, index) => {
            const isLast = index === breadcrumbs.length - 1;
            const pathSegments = pathParts.slice(0, index);
            const path = index === 0 ? './' : `./${pathSegments.join('/')}/`;
            const actionAttributes = isLast
                ? ''
                : `data-browser-action="browse" data-path="${this.escapeHtml(path)}"`;
            return `
                <span class="${isLast ? 'font-medium text-blue-600' : 'text-blue-500 hover:text-blue-700 cursor-pointer'}"
                      ${actionAttributes}>${this.escapeHtml(part)}</span>
                ${!isLast ? '<span class="text-gray-400">/</span>' : ''}
            `;
        }).join('');

        const directoryItemsHtml = directories.map(item => {
            const isDirectory = item.type === 'directory';
            const isFile = item.type === 'file';
            const isSpecial = item.type === 'current' || item.type === 'parent';
            const icon = item.type === 'current' ? '📁'
                : item.type === 'parent' ? '⬆️'
                : isDirectory ? '📂' : '📄';
            const bgColor = item.type === 'current' ? 'bg-blue-50'
                : item.type === 'parent' ? 'bg-gray-50'
                : isDirectory ? 'hover:bg-gray-50' : 'hover:bg-green-50';
            const safePath = this.escapeHtml(item.path || '');
            const safeName = this.escapeHtml(item.name || '');
            const browseAttributes = isDirectory || isSpecial
                ? `data-browser-action="browse" data-path="${safePath}"`
                : '';
            const typeLabel = isFile ? this.t('AsciiDoc文件') : isDirectory ? this.t('目录') : '';

            let actions = '';
            if (isDirectory) {
                actions = `
                    <button data-browser-action="select-directory" data-path="${safePath}"
                            class="px-3 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600">${this.t('选择此目录')}</button>
                    <button data-browser-action="browse" data-path="${safePath}"
                            class="px-3 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600">${this.t('进入浏览')}</button>`;
            } else if (isFile) {
                actions = `
                    <button data-browser-action="select-file" data-path="${safePath}"
                            class="px-3 py-1 text-xs bg-purple-500 text-white rounded hover:bg-purple-600">${this.t('选择此文件')}</button>`;
            } else if (isSpecial && item.type !== 'parent') {
                actions = `
                    <button data-browser-action="select-directory" data-path="${safePath}"
                            class="px-3 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600">${this.t('选择')}</button>`;
            }

            return `
                <div class="p-3 ${bgColor} border-b flex items-center justify-between cursor-pointer"
                     ${browseAttributes}>
                    <div class="flex items-center space-x-3">
                        <span class="text-lg">${icon}</span>
                        <div>
                            <div class="font-medium text-gray-900">${safeName}</div>
                            <div class="text-sm text-gray-500">${safePath}</div>
                            ${typeLabel ? `<div class="text-xs text-gray-400">${typeLabel}</div>` : ''}
                        </div>
                    </div>
                    <div class="flex space-x-2">${actions}</div>
                </div>
            `;
        }).join('');
        
        modal.innerHTML = `
            <div class="relative top-10 mx-auto p-6 border w-2/3 max-w-4xl shadow-lg rounded-md bg-white">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-xl font-medium text-gray-900">${this.t('目录浏览器')}</h3>
                    <button data-browser-action="close" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>
                
                <div class="mb-4 p-3 bg-gray-50 rounded-lg">
                    <div class="text-sm text-gray-600 mb-2">${this.t('当前路径:')}</div>
                    <div class="flex items-center space-x-2 text-sm">
                        ${breadcrumbsHtml}
                    </div>
                </div>
                
                <div class="max-h-96 overflow-y-auto border rounded-lg">
                    ${directoryItemsHtml}
                </div>
                
                <div class="mt-6 flex justify-between">
                    <div class="flex space-x-2">
                        <button data-browser-action="select-current" class="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600">
                            ${this.t('选择当前目录')}
                        </button>
                        <button data-browser-action="custom" class="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">
                            ${this.t('自定义路径')}
                        </button>
                    </div>
                    <button data-browser-action="close" class="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400">
                        ${this.t('取消')}
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        this.localize(modal);
        
        this.bindBrowserModalFunctions(modal);
    }
    
    bindBrowserModalFunctions(modal) {
        const self = this;

        const closeModal = () => {
            if (modal && modal.parentNode) {
                document.body.removeChild(modal);
            }
        };

        modal.addEventListener('click', async (event) => {
            const target = event.target.closest('[data-browser-action]');
            if (!target || !modal.contains(target)) return;
            event.preventDefault();
            event.stopPropagation();

            const action = target.dataset.browserAction;
            const path = target.dataset.path || '';
            if (action === 'close') {
                closeModal();
            } else if (action === 'browse') {
                await self.navigateToDirectory(path);
            } else if (action === 'select-directory' || action === 'select-file') {
                document.getElementById('directory').value = path;
                const message = action === 'select-file'
                    ? self.t('已选择文件: {path}', { path })
                    : self.t('已选择目录: {path}', { path });
                self.showNotification(message, 'success');
                closeModal();
            } else if (action === 'select-current') {
                document.getElementById('directory').value = self.currentBrowsePath;
                self.showNotification(
                    self.t('已选择目录: {path}', { path: self.currentBrowsePath }),
                    'success'
                );
                closeModal();
            } else if (action === 'custom') {
                const customPath = prompt(self.t('请输入自定义目录路径:'));
                if (customPath) {
                    document.getElementById('directory').value = customPath;
                    self.showNotification(self.t('已设置目录: {path}', { path: customPath }), 'success');
                    closeModal();
                }
            }
        });
    }

    async showConfigModal() {
        document.getElementById('configModal').classList.remove('hidden');
        await this.loadConfig();
    }

    hideConfigModal() {
        document.getElementById('configModal').classList.add('hidden');
    }

    async showStatsModal() {
        document.getElementById('statsModal').classList.remove('hidden');
        await this.loadDetailedStats();
    }

    hideStatsModal() {
        document.getElementById('statsModal').classList.add('hidden');
    }

    async loadConfig() {
        try {
            const response = await fetch('/config');
            const config = await response.json();
            this.llmConfig = await this.loadLlmConfig();
            this.renderConfigForm(config);
        } catch (error) {
            this.showNotification('加载配置失败: ' + error.message, 'error');
        }
    }

    renderConfigForm(config) {
        const container = document.getElementById('configContent');
        container.innerHTML = `
            <div class="space-y-6">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">${this.t('跳过文件模式')}</label>
                    <textarea id="skipPatterns" rows="3" 
                              class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                              placeholder="${this.t('输入要跳过的文件模式，每行一个')}">${this.escapeHtml(config.skip_file_patterns ? config.skip_file_patterns.join('\n') : '')}</textarea>
                </div>
                

                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">${this.t('强制修复规则')}</label>
                    <textarea id="forcedFixes" rows="5" 
                              class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                              placeholder="${this.t('格式: 错误词汇=正确词汇，每行一个')}">${this.escapeHtml(this.objectToText(config.forced_fixes))}</textarea>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">${this.t('跳过文本模式')}</label>
                    <textarea id="skipTextPatterns" rows="3"
                              class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                              placeholder="${this.t('输入要跳过的文本模式，每行一个')}">${this.escapeHtml(config.skip_text_patterns ? config.skip_text_patterns.join('\n') : '')}</textarea>
                </div>

                ${this.llmConfig ? this.renderLlmPanel(this.llmConfig) : ''}
            </div>
        `;
    }

    renderLlmPanel(llm) {
        const locked = new Set(llm.environment_locked || []);
        const lock = (key) => locked.has(key) ? 'disabled' : '';
        const lockNote = (key) => locked.has(key)
            ? `<span class="ml-2 text-xs text-amber-700">${this.t('由环境变量锁定')}</span>`
            : '';
        const input = 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm disabled:bg-gray-100 disabled:text-gray-500';

        return `
            <div class="border-t border-gray-200 pt-5 mt-2">
                <h4 class="text-sm font-semibold text-gray-800 mb-1">
                    <i class="fas fa-robot mr-2 text-purple-500"></i>${this.t('大模型复核')}
                </h4>
                <p class="text-xs text-gray-500 mb-3">${this.t('两层都默认关闭。开启后文档内容会发送到下面配置的端点。')}</p>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
                    <div>
                        <label class="block text-xs font-medium text-gray-700 mb-1">${this.t('端点地址')}${lockNote('llm_endpoint')}</label>
                        <input id="llmEndpoint" type="text" class="${input}" ${lock('llm_endpoint')}
                               placeholder="https://your-endpoint.example.com/v1"
                               value="${this.escapeHtml(llm.llm_endpoint || '')}">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-gray-700 mb-1">${this.t('模型名称')}${lockNote('llm_model')}</label>
                        <input id="llmModel" type="text" class="${input}" ${lock('llm_model')}
                               placeholder="qwen2.5-72b-instruct"
                               value="${this.escapeHtml(llm.llm_model || '')}">
                    </div>
                </div>

                <div class="mb-4">
                    <label class="block text-xs font-medium text-gray-700 mb-1">
                        API Key${lockNote('llm_api_key')}
                        <span class="ml-2 text-xs ${llm.api_key_configured ? 'text-green-600' : 'text-gray-400'}">
                            ${llm.api_key_configured ? this.t('已配置') : this.t('未配置')}
                        </span>
                    </label>
                    <input id="llmApiKey" type="password" class="${input}" ${lock('llm_api_key')}
                           autocomplete="new-password"
                           placeholder="${this.t('留空则保持不变；只存在内存中，不写入配置文件')}">
                </div>

                <div class="space-y-3">
                    <div class="flex items-start justify-between gap-4 bg-gray-50 rounded-md p-3">
                        <div class="flex-1">
                            <label class="flex items-center text-sm font-medium text-gray-800">
                                <input id="llmReviewEnabled" type="checkbox" class="mr-2" ${lock('llm_review_enabled')}
                                       ${llm.llm_review_enabled ? 'checked' : ''}>
                                ${this.t('逐条复核')}${lockNote('llm_review_enabled')}
                            </label>
                            <p class="text-xs text-gray-500 mt-1 ml-6">${this.t('只把小模型改过的那一条发出去：原句 + 建议句。规则命中的不发。')}</p>
                        </div>
                        <div class="w-28 shrink-0">
                            <label class="block text-xs text-gray-600 mb-1">${this.t('每次上限')}</label>
                            <input id="llmMaxReviews" type="number" min="1" max="1000" class="${input}"
                                   ${lock('llm_max_reviews')} value="${Number(llm.llm_max_reviews) || 20}">
                        </div>
                    </div>

                    <div class="flex items-start justify-between gap-4 bg-gray-50 rounded-md p-3">
                        <div class="flex-1">
                            <label class="flex items-center text-sm font-medium text-gray-800">
                                <input id="contextReviewEnabled" type="checkbox" class="mr-2" ${lock('context_review_enabled')}
                                       ${llm.context_review_enabled ? 'checked' : ''}>
                                ${this.t('跨行上下文审阅')}${lockNote('context_review_enabled')}
                            </label>
                            <p class="text-xs text-amber-700 mt-1 ml-6">${this.t('每个文件发送整篇正文（最多 200 行）。默认只审已有发现的文件，成本跟随发现数；选「全部文件」则随文档数增长。')}</p>
                        </div>
                        <div class="w-44 shrink-0 space-y-2">
                            <div>
                                <label class="block text-xs text-gray-600 mb-1">${this.t('审阅范围')}${lockNote('context_review_scope')}</label>
                                <select id="contextReviewScope" class="${input}" ${lock('context_review_scope')}>
                                    <option value="flagged" ${llm.context_review_scope !== 'all' ? 'selected' : ''}>${this.t('仅有发现的文件')}</option>
                                    <option value="all" ${llm.context_review_scope === 'all' ? 'selected' : ''}>${this.t('全部文件')}</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-xs text-gray-600 mb-1">${this.t('文件上限')}</label>
                                <input id="contextMaxFiles" type="number" min="1" max="10000" class="${input}"
                                       ${lock('context_max_files')} value="${Number(llm.context_max_files) || 50}">
                            </div>
                        </div>
                    </div>
                </div>

                <div class="mt-3 bg-amber-50 border border-amber-200 rounded-md p-3">
                    <label class="flex items-center text-sm font-medium text-gray-800">
                        <input id="prLlmEnabled" type="checkbox" class="mr-2" ${lock('pr_llm_enabled')}
                               ${llm.pr_llm_enabled ? 'checked' : ''}>
                        ${this.t('在 GitHub PR 审阅中也启用以上两层')}${lockNote('pr_llm_enabled')}
                    </label>
                    <p class="text-xs text-gray-600 mt-1 ml-6">${this.t('PR 审阅由 webhook 自动触发，没有人在旁边看着。默认关闭，开启后每个 PR 都会产生上面两层的调用。')}</p>
                </div>
            </div>
        `;
    }

    async loadLlmConfig() {
        try {
            const response = await fetch('/api/llm/config');
            if (!response.ok) return null;
            return await response.json();
        } catch (error) {
            return null;
        }
    }

    async saveLlmConfig() {
        const llm = this.llmConfig;
        if (!llm) return true;
        const locked = new Set(llm.environment_locked || []);
        const payload = {};
        const put = (key, value) => { if (!locked.has(key)) payload[key] = value; };

        put('llm_endpoint', document.getElementById('llmEndpoint').value.trim());
        put('llm_model', document.getElementById('llmModel').value.trim());
        put('llm_review_enabled', document.getElementById('llmReviewEnabled').checked);
        put('context_review_enabled', document.getElementById('contextReviewEnabled').checked);
        put('llm_max_reviews', parseInt(document.getElementById('llmMaxReviews').value, 10));
        put('context_max_files', parseInt(document.getElementById('contextMaxFiles').value, 10));
        put('context_review_scope', document.getElementById('contextReviewScope').value);
        put('pr_llm_enabled', document.getElementById('prLlmEnabled').checked);

        // An empty box means "leave the stored key alone", not "clear it".
        const apiKey = document.getElementById('llmApiKey').value;
        if (apiKey && !locked.has('llm_api_key')) payload.llm_api_key = apiKey;

        const response = await fetch('/api/llm/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!result.success) {
            this.showNotification(this.t('大模型设置保存失败') + ': ' + result.message, 'error');
            return false;
        }
        return true;
    }


    async saveConfig() {
        try {
            const config = {
                skip_file_patterns: this.textToArray(document.getElementById('skipPatterns').value),
                forced_fixes: this.textToObject(document.getElementById('forcedFixes').value),
                skip_text_patterns: this.textToArray(document.getElementById('skipTextPatterns').value)
            };

            const response = await fetch('/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            const result = await response.json();
            if (!result.success) {
                this.showNotification('配置保存失败: ' + result.message, 'error');
                return;
            }
            if (!await this.saveLlmConfig()) {
                return;
            }
            this.showNotification('配置保存成功', 'success');
            this.hideConfigModal();
        } catch (error) {
            this.showNotification('配置保存失败: ' + error.message, 'error');
        }
    }

    async loadStats() {
        try {
            const response = await fetch('/api/current-stats');
            const stats = await response.json();
            this.currentStats = stats;
            this.updateStatsDisplay(stats);
        } catch (error) {
            console.error('加载统计数据失败:', error);
        }
    }

    updateStatsDisplay(stats) {
        // Two endpoints report these numbers under different names:
        // /api/current-stats (a seven-day window) calls them total_changes and
        // avg_defect_rate, /stats (lifetime) calls them valid_changes and
        // defect_rate_per_thousand. Reading only the second pair left both cards
        // on zero for every install, because `|| 0` hid the mismatch.
        const corrections = stats.total_changes ?? stats.valid_changes ?? 0;
        const defectRate = stats.avg_defect_rate ?? stats.defect_rate_per_thousand ?? 0;

        document.getElementById('totalFiles').textContent = stats.total_files || 0;
        document.getElementById('validChanges').textContent = corrections;
        document.getElementById('defectRate').textContent = Number(defectRate).toFixed(1) + '‰';
    }

    async loadDashboardStatus() {
        try {
            const response = await fetch('/api/dashboard/status');
            const result = await response.json();
            if (result.success) {
                this.updateDashboardDisplay(result.data);
            }
        } catch (error) {
            console.error('加载仪表板状态失败:', error);
        }
    }

    updateDashboardDisplay(data) {
        const runningCount = data.running_tasks_count || 0;
        document.getElementById('runningTasksCount').textContent = runningCount;
        
        const icon = document.getElementById('runningTasksIcon');
        const card = document.getElementById('runningTasksCard');
        const details = document.getElementById('runningTasksDetails');
        
        if (runningCount > 0) {
            icon.className = 'fas fa-spinner fa-spin text-orange-500 text-2xl';
            card.classList.add('border-l-4', 'border-orange-500', 'running-task-pulse');
            
            this.updateRunningTasksList(data.running_tasks || []);
            details.classList.remove('hidden');
        } else {
            icon.className = 'fas fa-play-circle text-gray-400 text-2xl';
            card.classList.remove('border-l-4', 'border-orange-500', 'running-task-pulse');
            details.classList.add('hidden');
        }
        
        if (data.recent_stats && data.recent_stats.last_completed) {
            const lastUpdate = new Date(data.recent_stats.last_completed).toLocaleString(this.locale());
            document.getElementById('lastUpdate').textContent = lastUpdate;
        }
    }

    updateRunningTasksList(runningTasks) {
        const container = document.getElementById('runningTasksList');
        container.innerHTML = '';
        
        runningTasks.forEach(task => {
            const taskElement = document.createElement('div');
            taskElement.className = 'text-xs bg-orange-50 p-2 rounded border-l-2 border-orange-300';
            
            const progress = task.progress || 0;
            const currentFile = task.current_file ? task.current_file.split('/').pop() : this.t('处理中...');
            
            taskElement.innerHTML = `
                <div class="flex justify-between items-center mb-1">
                    <span class="font-medium text-orange-700">${this.t('任务 {id}', { id: task.task_id.substring(0, 8) })}</span>
                    <span class="text-orange-600">${progress}%</span>
                </div>
                <div class="text-gray-600 truncate">${this.escapeHtml(currentFile)}</div>
                <div class="w-full bg-orange-200 rounded-full h-1 mt-1">
                    <div class="progress-bar-animated h-1 rounded-full transition-all duration-300" style="width: ${progress}%"></div>
                </div>
            `;
            
            container.appendChild(taskElement);
        });
    }

    startDashboardRefresh() {
        setInterval(() => {
            this.loadDashboardStatus();
        }, 5000);
    }

    async loadCurrentModelStatus() {
        try {
            const response = await fetch('/api/model/status');
            const result = await response.json();
            if (result.success) {
                this.updateModelStatusDisplay(result.data);
            }
        } catch (error) {
            console.error('加载模型状态失败:', error);
        }
    }

    modelDisplayName(model) {
        return model === 'rule-based' ? this.t('规则预览模式') : model;
    }

    updateModelStatusDisplay(data) {
        const statusDiv = document.getElementById('currentModelStatus');
        const modelNameSpan = document.getElementById('currentModelName');
        
        if (data.current_model) {
            modelNameSpan.textContent = this.modelDisplayName(data.current_model);
            statusDiv.classList.remove('hidden');
            
            const modelSelect = document.getElementById('modelSelect');
            if (modelSelect.value !== data.current_model) {
                modelSelect.value = data.current_model;
            }
        } else {
            statusDiv.classList.add('hidden');
        }
    }

    onModelChange(event) {
        const selectedModel = event.target.value;
        const statusDiv = document.getElementById('currentModelStatus');
        const modelNameSpan = document.getElementById('currentModelName');
        
        modelNameSpan.textContent = this.modelDisplayName(selectedModel);
        statusDiv.classList.remove('hidden');
        
        this.showNotification(this.t('已选择模型: {model}', {
            model: this.modelDisplayName(selectedModel)
        }), 'info');
    }

    async checkAndRestoreRunningTask() {
        try {
            const response = await fetch('/api/dashboard/status');
            const result = await response.json();
            if (result.success && result.data.running_tasks_count > 0) {
                const runningTask = result.data.running_tasks[0];
                if (runningTask) {
                    this.isProcessing = true;
                    this.currentTaskId = runningTask.task_id;
                    this.showProgress();
                    this.updateProcessButton(true);
                    
                    this.addLog(`恢复任务进度: ${runningTask.directory}`);
                    this.monitorTaskProgress(runningTask.task_id);
                    this.monitorTaskLogs(runningTask.task_id);
                }
            }
        } catch (error) {
            console.error('检查运行中任务失败:', error);
        }
    }

    async monitorTaskProgress(taskId) {
        const checkProgress = async () => {
            try {
                const statusResponse = await fetch(`/api/history/${taskId}`);
                const statusResult = await statusResponse.json();
                
                if (statusResult.success && statusResult.data) {
                    const taskStatus = statusResult.data.status;
                    
                    if (taskStatus === 'cancelled') {
                        this.isProcessing = false;
                        this.currentTaskId = null;
                        this.updateProcessButton(false);
                        this.addLog('任务已被取消');
                        this.showNotification('任务已取消', 'info');
                        setTimeout(() => this.hideProgress(), 1000);
                        this.loadStats();
                        this.loadDashboardStatus();
                        return;
                    }
                    
                    if (taskStatus === 'completed' || taskStatus === 'failed') {
                        this.isProcessing = false;
                        this.currentTaskId = null;
                        this.updateProcessButton(false);
                        if (taskStatus === 'completed') {
                            this.updateProgress(100);
                            this.addLog('任务处理完成');
                            this.addLog(`扫描文件数: ${statusResult.data.total_files || 0}`);
                            this.addLog(`有效修改数: ${statusResult.data.valid_changes || 0}`);
                            if (statusResult.data.report_path) {
                                localStorage.setItem('lastTaskId', taskId);
                            }
                            this.showNotification('文档处理完成', 'success');
                        } else {
                            this.addLog(`任务处理失败: ${statusResult.data.error_message || '未知错误'}`);
                            this.showNotification('任务处理失败', 'error');
                        }
                        setTimeout(() => this.hideProgress(), 1500);
                        this.loadStats();
                        this.loadDashboardStatus();
                        return;
                    }
                }
                
                const response = await fetch(`/api/history/${taskId}/progress`);
                const result = await response.json();
                if (result.success && Array.isArray(result.data) && result.data.length > 0) {
                    const latestProgress = result.data[result.data.length - 1];
                    this.updateProgress(latestProgress.progress || 0);
                    if (latestProgress.message) {
                        this.addLog(latestProgress.message);
                    }
                }
            } catch (error) {
                console.error('获取任务进度失败:', error);
            }
            
            if (this.isProcessing && this.currentTaskId === taskId) {
                setTimeout(checkProgress, 2000);
            }
        };
        
        checkProgress();
    }

    async monitorTaskLogs(taskId) {
        let lastLogCount = 0;
        
        const checkLogs = async () => {
            try {
                const response = await fetch(`/api/history/${taskId}/logs`);
                const result = await response.json();
                if (result.success && result.data && result.data.length > lastLogCount) {
                    const newLogs = result.data.slice(lastLogCount);
                    newLogs.forEach(log => {
                        this.addLog(`[${log.level}] ${log.message}`);
                    });
                    lastLogCount = result.data.length;
                }
            } catch (error) {
                console.error('获取任务日志失败:', error);
            }
            
            if (this.isProcessing) {
                setTimeout(checkLogs, 1000);
            }
        };
        
        checkLogs();
    }

    async loadDetailedStats() {
        const container = document.getElementById('statsContent');
        
        let stats = this.currentStats;
        try {
            const response = await fetch('/stats');
            if (response.ok) {
                stats = await response.json();
            }
        } catch (error) {
            console.error('获取历史总计统计失败:', error);
        }
        
        container.innerHTML = `
            <div class="mb-4 p-3 bg-blue-50 rounded-lg border border-blue-200">
                <h3 class="text-lg font-medium text-blue-900 mb-1">${this.t('历史总计统计')}</h3>
                <p class="text-sm text-blue-700">${this.t('以下数据为所有已完成任务的累计统计')}</p>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h4 class="font-medium text-gray-900 mb-2">${this.t('文件统计（总计）')}</h4>
                    <div class="space-y-1 text-sm">
                        <div class="flex justify-between">
                            <span>${this.t('累计扫描文件数:')}</span>
                            <span class="font-medium">${stats.total_files || 0}</span>
                        </div>
                        <div class="flex justify-between">
                            <span>${this.t('累计检测字符数:')}</span>
                            <span class="font-medium">${(stats.total_chars || 0).toLocaleString(this.locale())}</span>
                        </div>
                    </div>
                </div>
                
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h4 class="font-medium text-gray-900 mb-2">${this.t('修改统计（总计）')}</h4>
                    <div class="space-y-1 text-sm">
                        <div class="flex justify-between">
                            <span>${this.t('累计总修改数:')}</span>
                            <span class="font-medium">${stats.total_changes || 0}</span>
                        </div>
                        <div class="flex justify-between">
                            <span>${this.t('累计有效修改数:')}</span>
                            <span class="font-medium">${stats.valid_changes || 0}</span>
                        </div>
                        <div class="flex justify-between">
                            <span>${this.t('累计空格问题:')}</span>
                            <span class="font-medium">${stats.total_whitespace_changes || 0}</span>
                        </div>
                    </div>
                </div>
                
                <div class="bg-gray-50 p-4 rounded-lg col-span-2">
                    <h4 class="font-medium text-gray-900 mb-2">${this.t('质量指标（总计）')}</h4>
                    <div class="space-y-1 text-sm">
                        <div class="flex justify-between">
                            <span>${this.t('历史千字缺陷率:')}</span>
                            <span class="font-medium">${(stats.defect_rate_per_thousand || 0).toFixed(1)}‰</span>
                        </div>
                        <div class="flex justify-between">
                            <span>${this.t('历史平均修改率:')}</span>
                            <span class="font-medium">${((stats.valid_changes || 0) / Math.max(1, stats.total_files || 1)).toFixed(1)}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    showProgress() {
        document.getElementById('progressContainer').classList.add('show');
        document.getElementById('logContainer').classList.add('show');
    }

    hideProgress() {
        document.getElementById('progressContainer').classList.remove('show');
        document.getElementById('logContainer').classList.remove('show');
    }

    updateProgress(percent) {
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        progressBar.style.width = percent + '%';
        progressText.textContent = Math.round(percent) + '%';
    }

    updateProcessButton(processing) {
        const btn = document.getElementById('startProcessBtn');
        if (processing) {
            btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>${this.t('处理中...')}`;
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');
        } else {
            btn.innerHTML = `<i class="fas fa-play mr-2"></i>${this.t('开始处理')}`;
            btn.disabled = false;
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    }

    clearLog() {
        document.getElementById('logOutput').innerHTML = '';
    }

    addLog(message) {
        const logOutput = document.getElementById('logOutput');
        const timestamp = new Date().toLocaleTimeString(this.locale());
        const logEntry = document.createElement('div');
        logEntry.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> ${this.escapeHtml(this.translate(message))}`;
        logOutput.appendChild(logEntry);
        logOutput.scrollTop = logOutput.scrollHeight;
    }

    updateLastUpdateTime() {
        const now = new Date();
        document.getElementById('lastUpdate').textContent = now.toLocaleTimeString(this.locale());
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        const colors = {
            success: 'bg-green-500',
            error: 'bg-red-500',
            warning: 'bg-yellow-500',
            info: 'bg-blue-500'
        };
        
        notification.className = `fixed top-4 right-4 ${colors[type]} text-white px-6 py-3 rounded-lg shadow-lg z-50 transform transition-all duration-300 translate-x-full`;
        const content = document.createElement('div');
        content.className = 'flex items-center';
        const text = document.createElement('span');
        text.textContent = this.translate(message);
        const closeButton = document.createElement('button');
        closeButton.className = 'ml-4 text-white hover:text-gray-200';
        closeButton.innerHTML = '<i class="fas fa-times"></i>';
        closeButton.addEventListener('click', () => notification.remove());
        content.appendChild(text);
        content.appendChild(closeButton);
        notification.appendChild(content);
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.classList.remove('translate-x-full');
        }, 100);
        
        setTimeout(() => {
            notification.classList.add('translate-x-full');
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, 300);
        }, 3000);
    }

    textToArray(text) {
        return text.split('\n').map(line => line.trim()).filter(line => line.length > 0);
    }

    textToObject(text) {
        const obj = {};
        text.split('\n').forEach(line => {
            const [key, value] = line.split('=').map(s => s.trim());
            if (key && value) {
                obj[key] = value;
            }
        });
        return obj;
    }

    objectToText(obj) {
        if (!obj) return '';
        return Object.entries(obj).map(([key, value]) => `${key}=${value}`).join('\n');
    }

    async showWhitelistModal() {
        document.getElementById('whitelistModal').classList.remove('hidden');
        this.whitelistSearchTerm = '';
        this.whitelistCurrentPage = 1;
        this.selectedWhitelistItems = new Set();
        await this.loadWhitelist();
    }

    hideWhitelistModal() {
        document.getElementById('whitelistModal').classList.add('hidden');
    }

    async loadWhitelist() {
        try {
            const response = await fetch('/api/whitelist');
            const result = await response.json();
            
            if (result.success) {
                this.currentWhitelist = Array.isArray(result.data) ? result.data : [];
                this.renderWhitelistItems();
                this.updateWhitelistStats();
            } else {
                this.showNotification('加载白名单失败', 'error');
            }
        } catch (error) {
            console.error('加载白名单失败:', error);
            this.showNotification('加载白名单失败: ' + error.message, 'error');
            this.currentWhitelist = [];
            this.renderWhitelistItems();
        }
    }

    filterWhitelist() {
        if (!this.whitelistSearchTerm) {
            return this.currentWhitelist;
        }
        return this.currentWhitelist.filter(item => 
            item.toLowerCase().includes(this.whitelistSearchTerm.toLowerCase())
        );
    }

    renderWhitelistItems() {
        const container = document.getElementById('whitelistContent');
        const count = document.getElementById('whitelistCount');
        const filteredItems = this.filterWhitelist();
        const itemsPerPage = 20;
        const totalPages = Math.ceil(filteredItems.length / itemsPerPage);
        const startIndex = (this.whitelistCurrentPage - 1) * itemsPerPage;
        const endIndex = startIndex + itemsPerPage;
        const pageItems = filteredItems.slice(startIndex, endIndex);
        
        count.textContent = this.currentWhitelist.length;
        
        if (filteredItems.length === 0) {
            container.innerHTML = `<div class="text-gray-500 text-center py-8">${this.t('暂无匹配的白名单词汇')}</div>`;
            this.renderWhitelistPagination(0, 0);
            return;
        }

        const itemsHtml = pageItems.map((item, pageIndex) => {
            const actualIndex = this.currentWhitelist.indexOf(item);
            const isSelected = this.selectedWhitelistItems.has(actualIndex);
            return `
                <div class="whitelist-item flex items-center justify-between p-2 border-b border-gray-100 hover:bg-gray-50 ${isSelected ? 'bg-blue-50' : ''}">
                    <div class="flex items-center space-x-2">
                        <input type="checkbox" class="text-blue-600" 
                               ${isSelected ? 'checked' : ''}
                               data-whitelist-toggle="${actualIndex}">
                        <span class="text-sm text-gray-700" title="${this.escapeHtml(item)}">${this.escapeHtml(item)}</span>
                    </div>
                    <button data-whitelist-remove="${actualIndex}"
                            class="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700" title="${this.t('删除')}">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
        }).join('');
        
        container.innerHTML = `<div class="space-y-1">${itemsHtml}</div>`;
        container.querySelectorAll('[data-whitelist-toggle]').forEach((checkbox) => {
            checkbox.addEventListener('change', () => {
                this.toggleWhitelistItem(Number(checkbox.dataset.whitelistToggle));
            });
        });
        container.querySelectorAll('[data-whitelist-remove]').forEach((button) => {
            button.addEventListener('click', () => {
                this.removeWhitelistItem(Number(button.dataset.whitelistRemove));
            });
        });
        this.renderWhitelistPagination(filteredItems.length, totalPages);
    }

    renderWhitelistPagination(totalItems, totalPages) {
        const container = document.getElementById('whitelistPagination');
        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }
        
        let pagination = '<div class="flex justify-center items-center space-x-2 mt-4">';
        
        if (this.whitelistCurrentPage > 1) {
            pagination += `<button data-whitelist-page="${this.whitelistCurrentPage - 1}" class="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300">${this.t('上一页')}</button>`;
        }
        
        const startPage = Math.max(1, this.whitelistCurrentPage - 2);
        const endPage = Math.min(totalPages, this.whitelistCurrentPage + 2);
        
        for (let i = startPage; i <= endPage; i++) {
            const isActive = i === this.whitelistCurrentPage;
            pagination += `<button data-whitelist-page="${i}" class="px-3 py-1 rounded ${isActive ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}">${i}</button>`;
        }
        
        if (this.whitelistCurrentPage < totalPages) {
            pagination += `<button data-whitelist-page="${this.whitelistCurrentPage + 1}" class="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300">${this.t('下一页')}</button>`;
        }
        
        pagination += '</div>';
        container.innerHTML = pagination;
        container.querySelectorAll('[data-whitelist-page]').forEach((button) => {
            button.addEventListener('click', () => {
                this.goToWhitelistPage(Number(button.dataset.whitelistPage));
            });
        });
    }

    goToWhitelistPage(page) {
        this.whitelistCurrentPage = page;
        this.renderWhitelistItems();
    }

    updateWhitelistStats() {
        const total = this.currentWhitelist.length;
        const selected = this.selectedWhitelistItems.size;
        const filtered = this.filterWhitelist().length;
        
        const statsElement = document.getElementById('whitelistStats');
        if (statsElement) {
            statsElement.textContent = this.formatSelectionStats(total, filtered, selected);
        }
    }

    toggleWhitelistItem(index) {
        if (this.selectedWhitelistItems.has(index)) {
            this.selectedWhitelistItems.delete(index);
        } else {
            this.selectedWhitelistItems.add(index);
        }
        this.updateWhitelistStats();
        this.renderWhitelistItems();
    }

    selectAllWhitelistItems() {
        const filteredItems = this.filterWhitelist();
        filteredItems.forEach(item => {
            const index = this.currentWhitelist.indexOf(item);
            this.selectedWhitelistItems.add(index);
        });
        this.updateWhitelistStats();
        this.renderWhitelistItems();
    }

    clearWhitelistSelection() {
        this.selectedWhitelistItems.clear();
        this.updateWhitelistStats();
        this.renderWhitelistItems();
    }

    async addWhitelistItem() {
        const input = document.getElementById('newWhitelistItem');
        const item = input.value.trim();
        
        if (!item) {
            this.showNotification('请输入白名单词汇', 'error');
            return;
        }
        
        if (this.currentWhitelist.includes(item)) {
            this.showNotification('该词汇已在白名单中', 'warning');
            return;
        }
        
        this.currentWhitelist.push(item);
        this.renderWhitelistItems();
        this.updateWhitelistStats();
        input.value = '';
        const suggestionsContainer = document.getElementById('whitelistSuggestions');
        suggestionsContainer.innerHTML = '';
        suggestionsContainer.classList.add('hidden');
        
        try {
            const response = await fetch('/api/whitelist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ whitelist: this.currentWhitelist })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('已添加到白名单并保存', 'success');
            } else {
                this.showNotification('添加成功但保存失败: ' + result.message, 'warning');
            }
        } catch (error) {
            this.showNotification('添加成功但保存失败: ' + error.message, 'warning');
        }
    }

    async removeWhitelistItem(index) {
        const item = this.currentWhitelist[index];
        this.currentWhitelist.splice(index, 1);
        const newSelectedItems = new Set();
        this.selectedWhitelistItems.forEach(selectedIndex => {
            if (selectedIndex < index) {
                newSelectedItems.add(selectedIndex);
            } else if (selectedIndex > index) {
                newSelectedItems.add(selectedIndex - 1);
            }
        });
        this.selectedWhitelistItems = newSelectedItems;
        
        this.renderWhitelistItems();
        this.updateWhitelistStats();
        
        try {
            const response = await fetch('/api/whitelist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ whitelist: this.currentWhitelist })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification(`已移除 "${item}" 并保存`, 'success');
            } else {
                this.showNotification(`移除成功但保存失败: ${result.message}`, 'warning');
            }
        } catch (error) {
            this.showNotification(`移除成功但保存失败: ${error.message}`, 'warning');
        }
    }

    searchWhitelist() {
        const searchInput = document.getElementById('whitelistSearch');
        this.whitelistSearchTerm = searchInput.value.trim();
        this.whitelistCurrentPage = 1;
        this.renderWhitelistItems();
        this.updateWhitelistStats();
    }

    async batchDeleteWhitelist() {
        if (this.selectedWhitelistItems.size === 0) {
            this.showNotification('请先选择要删除的项目', 'warning');
            return;
        }
        
        if (!confirm(this.t('确定要删除选中的 {count} 个项目吗？', {
            count: this.selectedWhitelistItems.size
        }))) {
            return;
        }
        
        const sortedIndexes = Array.from(this.selectedWhitelistItems).sort((a, b) => b - a);
        const deletedItems = [];
        
        sortedIndexes.forEach(index => {
            deletedItems.push(this.currentWhitelist[index]);
            this.currentWhitelist.splice(index, 1);
        });
        
        this.selectedWhitelistItems.clear();
        this.renderWhitelistItems();
        this.updateWhitelistStats();
        
        try {
            const response = await fetch('/api/whitelist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ whitelist: this.currentWhitelist })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification(`已删除 ${deletedItems.length} 个项目并保存`, 'success');
            } else {
                this.showNotification(`删除成功但保存失败: ${result.message}`, 'warning');
            }
        } catch (error) {
            this.showNotification(`删除成功但保存失败: ${error.message}`, 'warning');
        }
    }

    getWhitelistSuggestions(input) {
        if (!input || input.length === 0) {
            return [];
        }
        
        const value = input.toLowerCase();
        const matchingItems = this.currentWhitelist.filter(item => 
            item.toLowerCase().includes(value)
        );
        
        matchingItems.sort((a, b) => {
            const aLower = a.toLowerCase();
            const bLower = b.toLowerCase();
            
            if (aLower === value) return -1;
            if (bLower === value) return 1;
            
            const aStartsWith = aLower.startsWith(value);
            const bStartsWith = bLower.startsWith(value);
            if (aStartsWith && !bStartsWith) return -1;
            if (!aStartsWith && bStartsWith) return 1;
            
            return a.length - b.length;
        });
        
        return matchingItems.slice(0, 8);
    }

    showWhitelistSuggestions() {
        const input = document.getElementById('newWhitelistItem');
        const suggestionsContainer = document.getElementById('whitelistSuggestions');
        
        if (!input.value.trim()) {
            suggestionsContainer.innerHTML = '';
            suggestionsContainer.classList.add('hidden');
            return;
        }
        
        const inputValue = input.value.trim();
        const suggestions = this.getWhitelistSuggestions(inputValue);
        
        if (suggestions.length === 0) {
            suggestionsContainer.innerHTML = '';
            suggestionsContainer.classList.add('hidden');
            return;
        }
        
        const exactMatch = suggestions.find(item => item.toLowerCase() === inputValue.toLowerCase());
        
        let suggestionsHtml;
        if (exactMatch) {
            suggestionsHtml = `
                <div class="suggestion-item duplicate-warning">
                    <i class="warning-icon">⚠️</i> ${this.t('该词汇已存在于白名单中')}
                </div>
            `;
        } else {
            suggestionsHtml = `
                <div class="suggestion-header">${this.t('现有白名单中的相似项：')}</div>
                ${suggestions.map(item => `
                    <div class="suggestion-item existing-item" data-whitelist-suggestion="${this.escapeHtml(item)}">
                        <i class="info-icon">📋</i> ${this.escapeHtml(item)}
                    </div>
                `).join('')}
            `;
        }
        
        suggestionsContainer.innerHTML = `<div class="suggestions-list">${suggestionsHtml}</div>`;
        suggestionsContainer.querySelectorAll('[data-whitelist-suggestion]').forEach((element) => {
            element.addEventListener('click', () => {
                this.highlightWhitelistItem(element.dataset.whitelistSuggestion);
            });
        });
        suggestionsContainer.classList.remove('hidden');
    }

    highlightWhitelistItem(item) {
        const suggestionsContainer = document.getElementById('whitelistSuggestions');
        suggestionsContainer.innerHTML = '';
        suggestionsContainer.classList.add('hidden');
        
        const whitelistItems = document.querySelectorAll('.whitelist-item');
        whitelistItems.forEach(element => {
            element.classList.remove('highlighted');
            if (element.textContent.includes(item)) {
                element.classList.add('highlighted');
                element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                
                setTimeout(() => {
                    element.classList.remove('highlighted');
                }, 3000);
            }
        });
        
        this.showNotification(`已定位到现有项: "${item}"`, 'info');
    }

    async saveWhitelist() {
        try {
            const response = await fetch('/api/whitelist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ whitelist: this.currentWhitelist })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('白名单保存成功', 'success');
                this.hideWhitelistModal();
            } else {
                this.showNotification('白名单保存失败: ' + result.message, 'error');
            }
        } catch (error) {
            this.showNotification('白名单保存失败: ' + error.message, 'error');
        }
    }

    exportWhitelist() {
        const data = {
            whitelist: this.currentWhitelist,
            exportTime: new Date().toISOString(),
            version: '1.0'
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `whitelist_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        this.showNotification('白名单已导出', 'success');
    }

    importWhitelist() {
        document.getElementById('whitelistFileInput').click();
    }

    async handleWhitelistFileImport(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        try {
            const text = await file.text();
            let importedData;
            
            if (file.name.endsWith('.json')) {
                importedData = JSON.parse(text);
                if (importedData.whitelist && Array.isArray(importedData.whitelist)) {
                    this.currentWhitelist = [...new Set([...this.currentWhitelist, ...importedData.whitelist])];
                } else if (Array.isArray(importedData)) {
                    this.currentWhitelist = [...new Set([...this.currentWhitelist, ...importedData])];
                } else {
                    throw new Error('无效的JSON格式');
                }
            } else {
                const items = text.split('\n').map(line => line.trim()).filter(line => line);
                this.currentWhitelist = [...new Set([...this.currentWhitelist, ...items])];
            }
            
            this.renderWhitelistItems();
            this.showNotification(`成功导入 ${file.name}`, 'success');
        } catch (error) {
            this.showNotification('导入失败: ' + error.message, 'error');
        }
        
        event.target.value = '';
    }

    showFalsePositiveModal() {
        document.getElementById('falsePositiveModal').classList.remove('hidden');
        this.initializeFalsePositiveManagement();
    }

    hideFalsePositiveModal() {
        document.getElementById('falsePositiveModal').classList.add('hidden');
    }
    
    showGithubMonitorModal() {
        document.getElementById('githubMonitorModal').classList.remove('hidden');
        this.loadGithubMonitorStatus();
        this.loadReviewHistory();
        this.loadMonitorLogs();
    }
    
    hideGithubMonitorModal() {
        const modal = document.getElementById('githubMonitorModal');
        if (modal) {
            modal.classList.add('hidden');
        } else {
            console.error('找不到GitHub监控设置模态框元素');
        }
    }
    
    showEmailNotificationModal() {
        document.getElementById('emailNotificationModal').classList.remove('hidden');
        this.loadEmailConfig();
    }
    
    hideEmailNotificationModal() {
        document.getElementById('emailNotificationModal').classList.add('hidden');
    }

    showAddFalsePositiveModal() {
        document.getElementById('addFalsePositiveModal').classList.remove('hidden');
        document.getElementById('newFalsePositiveOriginal').value = '';
        document.getElementById('newFalsePositiveCorrected').value = '';
        document.getElementById('newFalsePositiveIsPattern').checked = false;
        document.getElementById('newFalsePositiveNote').value = '';
    }

    hideAddFalsePositiveModal() {
        document.getElementById('addFalsePositiveModal').classList.add('hidden');
    }

    initializeFalsePositiveManagement() {
        this.falsePositiveData = {
            allItems: [],
            filteredItems: [],
            selectedItems: new Set(),
            currentPage: 1,
            itemsPerPage: 10,
            searchOriginal: '',
            searchCorrected: '',
            filterType: ''
        };
        this.loadFalsePositiveHistory();
    }

    async loadFalsePositiveHistory() {
        try {
            const response = await fetch('/api/false_positives');
            const result = await response.json();
            
            if (result.success && result.data) {
                this.falsePositiveData.allItems = result.data;
            } else {
                this.falsePositiveData.allItems = [];
            }
            
            this.applyFalsePositiveFilters();
        } catch (error) {
            console.error('加载误报历史失败:', error);
            this.showNotification('加载误报历史失败', 'error');
            this.falsePositiveData.allItems = [];
            this.applyFalsePositiveFilters();
        }
    }

    applyFalsePositiveFilters() {
        let filtered = [...this.falsePositiveData.allItems];
        
        if (this.falsePositiveData.searchOriginal) {
            filtered = filtered.filter(item => 
                item.original.toLowerCase().includes(this.falsePositiveData.searchOriginal.toLowerCase())
            );
        }
        
        if (this.falsePositiveData.searchCorrected) {
            filtered = filtered.filter(item => 
                (item.corrected || '').toLowerCase().includes(this.falsePositiveData.searchCorrected.toLowerCase())
            );
        }
        
        if (this.falsePositiveData.filterType) {
            filtered = filtered.filter(item => {
                if (this.falsePositiveData.filterType === 'pattern') {
                    return item.is_pattern;
                } else if (this.falsePositiveData.filterType === 'exact') {
                    return !item.is_pattern;
                }
                return true;
            });
        }
        
        this.falsePositiveData.filteredItems = filtered;
        this.falsePositiveData.currentPage = 1;
        this.renderFalsePositiveList();
        this.updateFalsePositiveStats();
    }

    falsePositiveItemId(item) {
        return JSON.stringify([
            String(item.original || ''),
            String(item.corrected || ''),
            Boolean(item.is_pattern)
        ]);
    }

    renderFalsePositiveList() {
        const startIndex = (this.falsePositiveData.currentPage - 1) * this.falsePositiveData.itemsPerPage;
        const endIndex = startIndex + this.falsePositiveData.itemsPerPage;
        const pageItems = this.falsePositiveData.filteredItems.slice(startIndex, endIndex);
        
        const listElement = document.getElementById('falsePositiveList');
        
        if (pageItems.length === 0) {
            listElement.innerHTML = `<div class="text-gray-500 text-center py-8">${this.t('暂无误报记录')}</div>`;
        } else {
            listElement.innerHTML = pageItems.map((item, index) => {
                const itemId = this.falsePositiveItemId(item);
                const isSelected = this.falsePositiveData.selectedItems.has(itemId);
                
                return `
                    <div class="px-4 py-3 border-b border-gray-200 hover:bg-gray-50">
                        <div class="grid grid-cols-12 gap-2 items-center text-sm">
                            <div class="col-span-1">
                                <input type="checkbox" ${isSelected ? 'checked' : ''} 
                                       data-fp-toggle="${this.escapeHtml(itemId)}"
                                       class="rounded border-gray-300 text-blue-600">
                            </div>
                            <div class="col-span-4">
                                <div class="text-gray-900 break-words">${this.escapeHtml(item.original)}</div>
                                ${item.note ? `<div class="mt-1 text-xs text-gray-500 break-words">${this.escapeHtml(item.note)}</div>` : ''}
                            </div>
                            <div class="col-span-4">
                                <div class="text-gray-900 break-words">${this.escapeHtml(item.corrected || '')}</div>
                            </div>
                            <div class="col-span-1">
                                <span class="px-2 py-1 text-xs rounded ${
                                    item.is_pattern ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'
                                }">
                                    ${item.is_pattern ? this.t('模式') : this.t('精确')}
                                </span>
                            </div>
                            <div class="col-span-1">
                                <div class="text-gray-500 text-xs">
                                    ${item.timestamp ? new Date(item.timestamp).toLocaleDateString(this.locale()) : this.t('未知')}
                                </div>
                            </div>
                            <div class="col-span-1">
                                <div class="flex space-x-1">
                                     <button data-fp-remove="1"
                                             data-original="${this.escapeHtml(item.original)}"
                                             data-corrected="${this.escapeHtml(item.corrected || '')}"
                                             data-is-pattern="${item.is_pattern ? 'true' : 'false'}"
                                             class="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700" title="${this.t('删除')}">
                                         <i class="fas fa-trash"></i>
                                     </button>
                                 </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            listElement.querySelectorAll('[data-fp-toggle]').forEach((checkbox) => {
                checkbox.addEventListener('change', () => {
                    this.toggleFalsePositiveItem(checkbox.dataset.fpToggle);
                });
            });
            listElement.querySelectorAll('[data-fp-remove]').forEach((button) => {
                button.addEventListener('click', () => {
                    this.removeFalsePositive(
                        button.dataset.original,
                        button.dataset.corrected,
                        button.dataset.isPattern === 'true'
                    );
                });
            });
        }
        
        this.renderFalsePositivePagination();
    }

    renderFalsePositivePagination() {
        const totalPages = Math.ceil(this.falsePositiveData.filteredItems.length / this.falsePositiveData.itemsPerPage);
        const currentPage = this.falsePositiveData.currentPage;
        
        if (totalPages <= 1) {
            document.getElementById('falsePositivePagination').innerHTML = '';
            return;
        }
        
        let paginationHtml = '<div class="flex justify-center items-center space-x-2">';
        
        paginationHtml += `
            <button data-fp-page="${currentPage - 1}"
                    ${currentPage === 1 ? 'disabled' : ''}
                    class="px-3 py-1 border rounded text-sm ${currentPage === 1 ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-700 hover:bg-gray-50'}">
                ${this.t('上一页')}
            </button>
        `;
        
        for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
            paginationHtml += `
                <button data-fp-page="${i}"
                        class="px-3 py-1 border rounded text-sm ${
                            i === currentPage ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                        }">
                    ${i}
                </button>
            `;
        }
        
        paginationHtml += `
            <button data-fp-page="${currentPage + 1}"
                    ${currentPage === totalPages ? 'disabled' : ''}
                    class="px-3 py-1 border rounded text-sm ${currentPage === totalPages ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-700 hover:bg-gray-50'}">
                ${this.t('下一页')}
            </button>
        `;
        
        paginationHtml += '</div>';
        const container = document.getElementById('falsePositivePagination');
        container.innerHTML = paginationHtml;
        container.querySelectorAll('[data-fp-page]').forEach((button) => {
            button.addEventListener('click', () => {
                this.goToFalsePositivePage(Number(button.dataset.fpPage));
            });
        });
    }

    goToFalsePositivePage(page) {
        const totalPages = Math.ceil(this.falsePositiveData.filteredItems.length / this.falsePositiveData.itemsPerPage);
        if (page >= 1 && page <= totalPages) {
            this.falsePositiveData.currentPage = page;
            this.renderFalsePositiveList();
        }
    }

    updateFalsePositiveStats() {
        const total = this.falsePositiveData.allItems.length;
        const filtered = this.falsePositiveData.filteredItems.length;
        const selected = this.falsePositiveData.selectedItems.size;
        
        document.getElementById('falsePositiveStats').textContent =
            this.formatSelectionStats(total, filtered, selected);
    }

    toggleFalsePositiveItem(itemId) {
        if (this.falsePositiveData.selectedItems.has(itemId)) {
            this.falsePositiveData.selectedItems.delete(itemId);
        } else {
            this.falsePositiveData.selectedItems.add(itemId);
        }
        this.updateFalsePositiveStats();
    }

    selectAllFalsePositiveItems() {
        const startIndex = (this.falsePositiveData.currentPage - 1) * this.falsePositiveData.itemsPerPage;
        const endIndex = startIndex + this.falsePositiveData.itemsPerPage;
        const pageItems = this.falsePositiveData.filteredItems.slice(startIndex, endIndex);
        
        pageItems.forEach(item => {
            const itemId = this.falsePositiveItemId(item);
            this.falsePositiveData.selectedItems.add(itemId);
        });
        
        this.renderFalsePositiveList();
        this.updateFalsePositiveStats();
    }

    clearFalsePositiveSelection() {
        this.falsePositiveData.selectedItems.clear();
        this.renderFalsePositiveList();
        this.updateFalsePositiveStats();
    }

    searchFalsePositive() {
        this.falsePositiveData.searchOriginal = document.getElementById('falsePositiveSearchOriginal').value;
        this.falsePositiveData.searchCorrected = document.getElementById('falsePositiveSearchCorrected').value;
        this.falsePositiveData.filterType = document.getElementById('falsePositiveFilterType').value;
        this.applyFalsePositiveFilters();
    }

    async saveFalsePositive() {
        const original = document.getElementById('newFalsePositiveOriginal').value.trim();
        const corrected = document.getElementById('newFalsePositiveCorrected').value.trim();
        const isPattern = document.getElementById('newFalsePositiveIsPattern').checked;
        const note = document.getElementById('newFalsePositiveNote').value.trim();
        
        if (!original || !corrected) {
            this.showNotification('请填写原文内容和修正文本', 'error');
            return;
        }
        
        try {
            const response = await fetch('/api/false_positives', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    original: original,
                    corrected: corrected,
                    is_pattern: isPattern,
                    note: note
                })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('误报记录已添加', 'success');
                this.hideAddFalsePositiveModal();
                this.loadFalsePositiveHistory();
            } else {
                this.showNotification('添加误报记录失败: ' + result.message, 'error');
            }
        } catch (error) {
            console.error('添加误报记录失败:', error);
            this.showNotification('添加误报记录失败', 'error');
        }
    }

    async batchDeleteFalsePositive() {
        if (this.falsePositiveData.selectedItems.size === 0) {
            this.showNotification('请先选择要删除的项目', 'warning');
            return;
        }
        
        if (!confirm(this.t('确定要删除选中的 {count} 条误报记录吗？', {
            count: this.falsePositiveData.selectedItems.size
        }))) {
            return;
        }
        
        const itemsToDelete = Array.from(this.falsePositiveData.selectedItems).map(itemId => {
            const [original, corrected, isPattern] = JSON.parse(itemId);
            return { original, corrected, is_pattern: isPattern };
        });
        
        try {
            const response = await fetch('/api/false_positives/batch', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ items: itemsToDelete })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('批量删除成功', 'success');
                this.falsePositiveData.selectedItems.clear();
                this.loadFalsePositiveHistory();
            } else {
                this.showNotification('批量删除失败: ' + result.message, 'error');
            }
        } catch (error) {
            console.error('批量删除失败:', error);
            this.showNotification('批量删除失败', 'error');
        }
    }

    exportFalsePositive() {
        const dataToExport = {
            false_positives: this.falsePositiveData.allItems,
            export_time: new Date().toISOString(),
            total_count: this.falsePositiveData.allItems.length
        };
        
        const blob = new Blob([JSON.stringify(dataToExport, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `false_positives_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        this.showNotification('误报数据已导出', 'success');
    }

    importFalsePositive() {
        document.getElementById('falsePositiveFileInput').click();
    }

    async handleFalsePositiveFileImport(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        try {
            const text = await file.text();
            const data = JSON.parse(text);
            
            if (!data.false_positives || !Array.isArray(data.false_positives)) {
                throw new Error('无效的文件格式');
            }
            
            const response = await fetch('/api/false_positives/import', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ false_positives: data.false_positives })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification(`导入成功：${result.imported_count} 条记录`, 'success');
                this.loadFalsePositiveHistory();
            } else {
                this.showNotification('导入失败: ' + result.message, 'error');
            }
        } catch (error) {
            console.error('导入失败:', error);
            this.showNotification('导入失败：文件格式错误', 'error');
        }
        
        event.target.value = '';
    }

    async removeFalsePositive(original, corrected, isPattern) {
        if (!confirm(this.t('确定要删除这条误报记录吗？'))) {
            return;
        }
        
        try {
            const response = await fetch('/api/false_positives', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    original,
                    corrected,
                    is_pattern: isPattern
                })
            });

            const result = await response.json();
            if (response.ok && result.success) {
                this.showNotification('误报记录已删除', 'success');
                this.loadFalsePositiveHistory();
            } else {
                this.showNotification('删除误报记录失败', 'error');
            }
        } catch (error) {
            console.error('删除误报记录失败:', error);
            this.showNotification('删除误报记录失败', 'error');
        }
    }

    escapeHtml(text) {
        return window.DocSifterSecurity.escapeHtml(text);
    }

    safeExternalUrl(value) {
        try {
            const url = new URL(value);
            return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
        } catch (error) {
            return '';
        }
    }

    
    showHistoryModal() {
        document.getElementById('historyModal').classList.remove('hidden');
        this.loadTaskHistory();
    }

    hideHistoryModal() {
        document.getElementById('historyModal').classList.add('hidden');
    }

    showTaskDetailModal() {
        document.getElementById('taskDetailModal').classList.remove('hidden');
    }

    hideTaskDetailModal() {
        document.getElementById('taskDetailModal').classList.add('hidden');
    }

    async loadTaskHistory(page = 1, pageSize = 10) {
        try {
            const response = await fetch(`/api/history?page=${page}&page_size=${pageSize}`);
            const result = await response.json();
            
            if (result.success) {
                this.renderTaskHistory(result.data.tasks);
                this.renderHistoryPagination(result.data.pagination, page);
            } else {
                this.showNotification('加载历史记录失败: ' + result.message, 'error');
            }
        } catch (error) {
            this.showNotification('加载历史记录失败: ' + error.message, 'error');
        }
    }

    renderTaskHistory(tasks) {
        const tbody = document.getElementById('historyTableBody');
        tbody.innerHTML = '';
        
        if (!tasks || tasks.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="px-6 py-4 text-center text-gray-500">
                        ${this.t('暂无历史记录')}
                    </td>
                </tr>
            `;
            return;
        }
        
        tasks.forEach(task => {
            const row = document.createElement('tr');
            row.className = 'hover:bg-gray-50';
            
            const statusClass = this.getStatusClass(task.status);
            const statusText = this.getStatusText(task.status);
            
            row.innerHTML = `
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900" title="${this.escapeHtml(task.task_id)}">
                    ${this.escapeHtml(task.task_id)}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    ${this.escapeHtml(task.directory)}
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${statusClass}">
                        ${statusText}
                    </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    ${new Date(task.start_time).toLocaleString(this.locale())}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    ${task.end_time ? new Date(task.end_time).toLocaleString(this.locale()) : '-'}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <button data-task-action="view" data-task-id="${this.escapeHtml(task.task_id)}" class="text-blue-600 hover:text-blue-900 mr-3">
                        ${this.t('查看详情')}
                    </button>
                    ${task.report_path ? `<button data-task-action="download" data-task-id="${this.escapeHtml(task.task_id)}" class="text-green-600 hover:text-green-900 mr-3">${this.t('下载')}</button>` : ''}
                    <button data-task-action="delete" data-task-id="${this.escapeHtml(task.task_id)}" class="text-red-600 hover:text-red-900">
                        ${this.t('删除')}
                    </button>
                </td>
            `;
            
            tbody.appendChild(row);
        });

        tbody.querySelectorAll('[data-task-action]').forEach((button) => {
            button.addEventListener('click', () => {
                const taskId = button.dataset.taskId;
                if (button.dataset.taskAction === 'view') this.viewTaskDetail(taskId);
                if (button.dataset.taskAction === 'download') this.downloadTaskReport(taskId);
                if (button.dataset.taskAction === 'delete') this.deleteTask(taskId);
            });
        });
    }

    renderHistoryPagination(pagination, currentPage) {
        const container = document.getElementById('historyPagination');
        
        if (!pagination || pagination.total_pages <= 1) {
            container.innerHTML = '';
            return;
        }
        
        let paginationHtml = '<div class="flex space-x-2">';
        
        if (currentPage > 1) {
            paginationHtml += `<button data-history-page="${currentPage - 1}" class="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300">${this.t('上一页')}</button>`;
        }
        
        for (let i = 1; i <= pagination.total_pages; i++) {
            if (i === currentPage) {
                paginationHtml += `<button class="px-3 py-1 bg-blue-600 text-white rounded">${i}</button>`;
            } else {
                paginationHtml += `<button data-history-page="${i}" class="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300">${i}</button>`;
            }
        }
        
        if (currentPage < pagination.total_pages) {
            paginationHtml += `<button data-history-page="${currentPage + 1}" class="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300">${this.t('下一页')}</button>`;
        }
        
        paginationHtml += '</div>';
        container.innerHTML = paginationHtml;
        container.querySelectorAll('[data-history-page]').forEach((button) => {
            button.addEventListener('click', () => {
                this.loadTaskHistory(Number(button.dataset.historyPage));
            });
        });
    }

    async viewTaskDetail(taskId) {
        try {
            const response = await fetch(`/api/history/${taskId}`);
            const result = await response.json();
            
            if (result.success) {
                this.renderTaskDetail(result.data);
                this.showTaskDetailModal();
                this.loadTaskLogs(taskId);
                this.loadTaskProgress(taskId);
            } else {
                this.showNotification('加载任务详情失败: ' + result.message, 'error');
            }
        } catch (error) {
            this.showNotification('加载任务详情失败: ' + error.message, 'error');
        }
    }

    renderTaskDetail(task) {
        document.getElementById('taskDetailId').textContent = task.task_id;
        document.getElementById('taskDetailStatus').innerHTML = `<span class="px-2 py-1 text-xs font-semibold rounded-full ${this.getStatusClass(task.status)}">${this.getStatusText(task.status)}</span>`;
        document.getElementById('taskDetailDirectory').textContent = task.directory;
        document.getElementById('taskDetailStartTime').textContent = new Date(task.start_time).toLocaleString(this.locale());
        document.getElementById('taskDetailEndTime').textContent = task.end_time ? new Date(task.end_time).toLocaleString(this.locale()) : '-';
        
        const progress = task.progress || 0;
        document.getElementById('taskDetailProgress').style.width = `${progress}%`;
        document.getElementById('taskDetailProgressText').textContent = `${progress}%`;
        
        this.renderTaskStats(task.stats);
        
        const downloadBtn = document.getElementById('downloadTaskReportBtn');
        const deleteBtn = document.getElementById('deleteTaskBtn');
        
        if (task.report_path) {
            downloadBtn.style.display = 'inline-block';
            downloadBtn.onclick = () => this.downloadTaskReport(task.task_id);
        } else {
            downloadBtn.style.display = 'none';
        }
        
        deleteBtn.onclick = () => this.deleteTask(task.task_id);
    }

    renderTaskStats(stats) {
        const container = document.getElementById('taskDetailStats');
        
        if (!stats) {
            container.innerHTML = `<p class="text-gray-500">${this.t('暂无统计信息')}</p>`;
            return;
        }
        
        container.innerHTML = `
            <div class="bg-white p-3 rounded border">
                <div class="text-sm font-medium text-gray-500">${this.t('扫描文件数')}</div>
                <div class="text-lg font-semibold text-gray-900">${stats.total_files || 0}</div>
            </div>
            <div class="bg-white p-3 rounded border">
                <div class="text-sm font-medium text-gray-500">${this.t('有效修改数')}</div>
                <div class="text-lg font-semibold text-gray-900">${stats.valid_changes || 0}</div>
            </div>
            <div class="bg-white p-3 rounded border">
                <div class="text-sm font-medium text-gray-500">${this.t('缺陷率')}</div>
                <div class="text-lg font-semibold text-gray-900">${(stats.defect_rate_per_thousand || 0).toFixed(1)}‰</div>
            </div>
            <div class="bg-white p-3 rounded border">
                <div class="text-sm font-medium text-gray-500">${this.t('检测字符数')}</div>
                <div class="text-lg font-semibold text-gray-900">${(stats.total_chars || 0).toLocaleString(this.locale())}</div>
            </div>
        `;
    }

    async loadTaskLogs(taskId) {
        try {
            const response = await fetch(`/api/history/${taskId}/logs`);
            const result = await response.json();
            
            if (result.success) {
                this.renderTaskLogs(result.data);
            }
        } catch (error) {
            console.error('加载任务日志失败:', error);
        }
    }

    renderTaskLogs(logs) {
        const container = document.getElementById('taskLogs');
        
        if (!logs || logs.length === 0) {
            container.innerHTML = `<p class="text-gray-500">${this.t('暂无日志记录')}</p>`;
            return;
        }
        
        container.innerHTML = logs.map(log => {
            const levelClass = this.getLogLevelClass(log.level);
            return `
                <div class="flex items-start space-x-2 text-sm">
                    <span class="text-xs text-gray-400 whitespace-nowrap">${new Date(log.timestamp).toLocaleTimeString(this.locale())}</span>
                    <span class="px-2 py-1 text-xs font-medium rounded ${levelClass}">${log.level}</span>
                    <span class="text-gray-700">${this.escapeHtml(log.message)}</span>
                </div>
            `;
        }).join('');
    }

    async loadTaskProgress(taskId) {
        try {
            const response = await fetch(`/api/history/${taskId}/progress`);
            const result = await response.json();
            
            if (result.success) {
                this.renderTaskProgress(result.data);
            }
        } catch (error) {
            console.error('加载任务进度失败:', error);
        }
    }

    renderTaskProgress(progressData) {
        const container = document.getElementById('taskProgress');
        
        if (!progressData || progressData.length === 0) {
            container.innerHTML = `<p class="text-gray-500">${this.t('暂无进度记录')}</p>`;
            return;
        }
        
        container.innerHTML = progressData.map(progress => {
            const percentage = Math.max(0, Math.min(100, Number(progress.progress) || 0));
            const message = progress.message ? this.escapeHtml(this.translate(progress.message)) : this.t('处理中...');
            return `
            <div class="flex items-center space-x-3 text-sm">
                <span class="text-xs text-gray-400 whitespace-nowrap">${new Date(progress.timestamp).toLocaleTimeString(this.locale())}</span>
                <div class="flex-1">
                    <div class="flex justify-between items-center mb-1">
                        <span class="text-gray-700">${message}</span>
                        <span class="text-sm font-medium">${percentage}%</span>
                    </div>
                    <div class="bg-gray-200 rounded-full h-2">
                        <div class="bg-blue-600 h-2 rounded-full" style="width: ${percentage}%"></div>
                    </div>
                </div>
            </div>
        `;
        }).join('');
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.remove('active', 'border-blue-500', 'text-blue-600');
            btn.classList.add('border-transparent', 'text-gray-500');
        });
        
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.add('hidden');
        });
        
        const activeTab = document.getElementById(`${tabName}Tab`);
        const activeContent = document.getElementById(`${tabName}Content`);
        
        activeTab.classList.add('active', 'border-blue-500', 'text-blue-600');
        activeTab.classList.remove('border-transparent', 'text-gray-500');
        activeContent.classList.remove('hidden');
    }

    async downloadTaskReport(taskId) {
        try {
            const response = await fetch(`/api/history/${taskId}/download`);
            
            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `report_${taskId}.html`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                this.showNotification('报告下载成功', 'success');
            } else {
                const result = await response.json();
                this.showNotification('下载失败: ' + result.message, 'error');
            }
        } catch (error) {
            this.showNotification('下载失败: ' + error.message, 'error');
        }
    }

    async deleteTask(taskId) {
        if (!confirm(this.t('确定要删除这个任务记录吗？此操作不可撤销。'))) {
            return;
        }
        
        try {
            const response = await fetch(`/api/history/${taskId}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            
            if (result.success) {
                this.showNotification('任务已删除', 'success');
                this.hideTaskDetailModal();
                this.loadTaskHistory();
            } else {
                this.showNotification('删除失败: ' + result.message, 'error');
            }
        } catch (error) {
            this.showNotification('删除失败: ' + error.message, 'error');
        }
    }

    getLogLevelClass(level) {
        switch (level) {
            case 'INFO': return 'bg-blue-100 text-blue-800';
            case 'WARNING': return 'bg-yellow-100 text-yellow-800';
            case 'ERROR': return 'bg-red-100 text-red-800';
            case 'DEBUG': return 'bg-gray-100 text-gray-800';
            default: return 'bg-gray-100 text-gray-800';
        }
    }
    
    async loadGithubMonitorStatus() {
        try {
            const response = await fetch('/api/github/webhook/status');
            const result = await response.json();

            if (result.success && result.data) {
                const data = result.data;

                this.updateMonitorStatusDisplay(data);

                this.updateMonitorConfigForm(data);

                this.updateMonitoringStats(data);

                this.updateWebhookConfigDisplay(data);

            } else {
                this.showMonitorStatusError(result.message || '加载 GitHub 监控状态失败');
            }
        } catch (error) {
            console.error('加载 GitHub 监控状态失败:', error);
            this.showMonitorStatusError('网络连接失败，请检查网络或刷新页面重试');
        }
    }

    updateMonitorStatusDisplay(data) {
        const statusContainer = document.getElementById('githubMonitorStatus');
        const startBtn = document.getElementById('startMonitoringBtn');
        const stopBtn = document.getElementById('stopMonitoringBtn');

        if (data.is_running) {
            statusContainer.innerHTML = `
                <div class="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
                    <div class="flex items-center space-x-3">
                        <div class="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
                        <span class="text-sm font-medium text-green-800">${this.t('监控运行中')}</span>
                    </div>
                    <span class="text-sm text-green-600">${this.t('正常')}</span>
                </div>
                <div class="flex items-center justify-between p-3 bg-blue-50 rounded-lg">
                    <div class="flex items-center space-x-3">
                        <i class="fas fa-link text-blue-500"></i>
                        <span class="text-sm font-medium text-gray-700">${this.t('监控仓库')}</span>
                    </div>
                    <span class="text-sm text-gray-600 truncate max-w-xs">${this.escapeHtml(data.repo_url || this.t('未设置'))}</span>
                </div>
                <div class="flex items-center justify-between p-3 bg-purple-50 rounded-lg">
                    <div class="flex items-center space-x-3">
                        <i class="fas fa-webhook text-purple-500"></i>
                        <span class="text-sm font-medium text-gray-700">${this.t('触发方式')}</span>
                    </div>
                    <span class="text-sm text-gray-600">Webhook</span>
                </div>
            `;

            startBtn.disabled = true;
            startBtn.classList.add('opacity-50', 'cursor-not-allowed');
            stopBtn.disabled = false;
            stopBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        } else {
            statusContainer.innerHTML = `
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div class="flex items-center space-x-3">
                        <div class="w-3 h-3 bg-gray-400 rounded-full"></div>
                        <span class="text-sm font-medium text-gray-700">${this.t('监控未运行')}</span>
                    </div>
                    <span class="text-sm text-gray-600">${this.t('停止')}</span>
                </div>
                <div class="p-3 bg-yellow-50 rounded-lg border border-yellow-200">
                    <p class="text-sm text-yellow-800">
                        <i class="fas fa-info-circle mr-1"></i>
                        ${this.t('请配置仓库信息并启动监控')}
                    </p>
                </div>
            `;

            startBtn.disabled = false;
            startBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            stopBtn.disabled = true;
            stopBtn.classList.add('opacity-50', 'cursor-not-allowed');
        }
    }

    updateMonitorConfigForm(data) {
        if (data.repo_url) {
            document.getElementById('monitorRepoUrl').value = data.repo_url;
        }

        if (data.monitor_events) {
            document.getElementById('monitorPrOpen').checked = data.monitor_events.includes('pr_created');
            document.getElementById('monitorPrUpdate').checked = data.monitor_events.includes('pr_updated');
            document.getElementById('monitorPrReopen').checked = data.monitor_events.includes('pr_reopened');
        }

        document.getElementById('autoReviewEnabled').checked = data.auto_review_enabled !== false;
        document.getElementById('onlyChangedFiles').checked = data.only_changed_files !== false;
        document.getElementById('emailNotificationEnabled').checked = data.email_notification_enabled !== false;
        const modelSelect = document.getElementById('modelSelect');
        if (modelSelect && data.review_model && Array.from(modelSelect.options).some(option => option.value === data.review_model)) {
            modelSelect.value = data.review_model;
        }
    }

    updateWebhookConfigDisplay(data) {
        const url = data.webhook_url || '';
        const secret = data.webhook_secret || '';

        const monitorWebhookUrl = document.getElementById('monitorWebhookUrl');
        if (monitorWebhookUrl) monitorWebhookUrl.value = url;
        const monitorWebhookSecret = document.getElementById('monitorWebhookSecret');
        if (monitorWebhookSecret && secret) monitorWebhookSecret.value = secret;
        if (monitorWebhookSecret) {
            monitorWebhookSecret.placeholder = data.webhook_secret_configured
                ? this.t('Secret 已配置；重新生成后仅显示一次')
                : this.t('保存配置后生成 Secret');
        }
    }

    updateMonitoringStats(data) {
        const lastCheckElement = document.getElementById('lastCheckTime');
        if (lastCheckElement) {
            if (data.last_check) {
                const lastCheck = new Date(data.last_check);
                lastCheckElement.textContent = lastCheck.toLocaleString(this.locale(), {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } else {
                lastCheckElement.textContent = this.t('从未检查');
            }
        }

        this.loadMonitoringStatistics();
    }

    showMonitorStatusError(message) {
        const statusContainer = document.getElementById('githubMonitorStatus');
        statusContainer.innerHTML = `
            <div class="p-4 bg-red-50 border border-red-200 rounded-lg">
                <div class="flex items-center space-x-3">
                    <i class="fas fa-exclamation-triangle text-red-500"></i>
                    <div>
                        <p class="font-medium text-red-800">${this.t('加载状态失败')}</p>
                        <p class="text-sm text-red-600 mt-1">${this.escapeHtml(this.translate(message))}</p>
                    </div>
                </div>
            </div>
        `;
    }
    
    
    async saveMonitorRepoConfig() {
        const repoUrl = document.getElementById('monitorRepoUrl').value.trim();
        if (!repoUrl) {
            this.showNotification('请输入 GitHub 仓库 URL', 'error');
            return false;
        }

        if (!repoUrl.startsWith('https://github.com/')) {
            this.showNotification('请输入有效的 GitHub 仓库 URL', 'error');
            return false;
        }

        const monitorEvents = [];
        if (document.getElementById('monitorPrOpen').checked) monitorEvents.push('pr_created');
        if (document.getElementById('monitorPrUpdate').checked) monitorEvents.push('pr_updated');
        if (document.getElementById('monitorPrReopen').checked) monitorEvents.push('pr_reopened');

        const autoReviewEnabled = document.getElementById('autoReviewEnabled').checked;
        const onlyChangedFiles = document.getElementById('onlyChangedFiles').checked;
        const emailNotificationEnabled = document.getElementById('emailNotificationEnabled').checked;
        const reviewModel = document.getElementById('modelSelect').value;

        try {
            const response = await fetch('/api/github/webhook/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    repo_url: repoUrl,
                    monitor_events: monitorEvents,
                    auto_review_enabled: autoReviewEnabled,
                    only_changed_files: onlyChangedFiles,
                    email_notification_enabled: emailNotificationEnabled,
                    review_model: reviewModel
                })
            });

            const result = await response.json();
            if (result.success) {
                this.showNotification('监控配置保存成功', 'success');
                if (result.data) {
                    this.updateWebhookConfigDisplay({
                        ...result.data,
                        webhook_secret_configured: result.data.webhook_secret_configured === true
                    });
                }
                this.loadGithubMonitorStatus();
                return true;
            } else {
                this.showNotification(result.message || '监控配置保存失败', 'error');
                return false;
            }
        } catch (error) {
            console.error('保存监控配置错误:', error);
            this.showNotification('保存监控配置失败', 'error');
            return false;
        }
    }

    async loadMonitoringStatistics() {
        try {
            const response = await fetch('/api/github/review-history/stats');
            const result = await response.json();

            if (result.success) {
                const stats = result.data;

                const totalTasksElement = document.getElementById('totalTasks');
                const totalFilesElement = document.getElementById('monitorTotalFiles');

                if (totalTasksElement) {
                    totalTasksElement.textContent = stats.total_tasks || 0;
                }
                if (totalFilesElement) {
                    totalFilesElement.textContent = stats.total_files || 0;
                }
            }
        } catch (error) {
            console.error('加载统计信息失败:', error);
        }
    }

    async loadReviewHistory(page = 1, limit = 10) {
        try {
            const response = await fetch(`/api/github/review-history?page=${page}&limit=${limit}`);
            const result = await response.json();

            if (result.success) {
                this.renderReviewHistory(result.data);
                this.updateHistoryPagination(result.pagination);
            } else {
                this.showNotification('加载执行历史失败', 'error');
            }
        } catch (error) {
            console.error('加载执行历史失败:', error);
            this.showNotification('加载执行历史失败', 'error');
        }
    }

    renderReviewHistory(historyData) {
        const tbody = document.getElementById('reviewHistoryList');
        const countElement = document.getElementById('historyCount');

        if (!historyData || historyData.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="px-4 py-8 text-center text-sm text-gray-500">
                        <i class="fas fa-inbox text-gray-300 text-2xl mb-2 block"></i>
                        ${this.t('暂无执行历史记录')}
                    </td>
                </tr>
            `;
            if (countElement) countElement.textContent = '0';
            return;
        }

        tbody.innerHTML = historyData.map(item => {
            const statusClass = this.getStatusClass(item.status);
            const statusText = this.getStatusText(item.status);
            const prUrl = this.safeExternalUrl(item.pr_url);
            const processingTime = item.processing_time ? `${item.processing_time}s` : '-';
            const startTime = new Date(item.started_at).toLocaleString(this.locale(), {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });

            return `
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3 text-sm text-gray-900">
                        ${startTime}
                    </td>
                    <td class="px-4 py-3 text-sm">
                        <div class="max-w-xs">
                            <div class="font-medium text-gray-900">#${item.pr_number}</div>
                            <div class="text-gray-500 truncate">${this.escapeHtml(item.pr_title || this.t('未知标题'))}</div>
                        </div>
                    </td>
                    <td class="px-4 py-3 text-sm">
                        <span class="px-2 py-1 text-xs font-medium rounded-full ${statusClass}">
                            ${statusText}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900">${item.files_processed || 0}</td>
                    <td class="px-4 py-3 text-sm text-gray-900">${item.total_corrections || 0}</td>
                    <td class="px-4 py-3 text-sm text-gray-900">${processingTime}</td>
                    <td class="px-4 py-3 text-sm">
                        <div class="flex space-x-2">
                            ${prUrl ? `<a href="${this.escapeHtml(prUrl)}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-800"><i class="fas fa-external-link-alt"></i></a>` : ''}
                            ${item.report_path ? `<button data-review-report-id="${Number(item.id)}" class="text-green-600 hover:text-green-800" title="${this.t('下载报告')}"><i class="fas fa-download"></i></button>` : ''}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

        tbody.querySelectorAll('[data-review-report-id]').forEach((button) => {
            button.addEventListener('click', () => {
                this.downloadGithubReviewReport(button.dataset.reviewReportId);
            });
        });

        if (countElement) countElement.textContent = historyData.length.toString();
    }

    async downloadGithubReviewReport(historyId) {
        try {
            const response = await fetch(`/api/github/review-history/${historyId}/report`);
            if (!response.ok) {
                const result = await response.json().catch(() => ({}));
                throw new Error(result.message || this.t('报告文件不存在，请重新运行纠错任务'));
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `github-review-${historyId}.html`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(url);
        } catch (error) {
            this.showNotification(`${this.t('下载失败:')} ${this.translate(error.message)}`, 'error');
        }
    }

    getStatusClass(status) {
        const classes = {
            'pending': 'bg-yellow-100 text-yellow-800',
            'running': 'bg-blue-100 text-blue-800',
            'processing': 'bg-blue-100 text-blue-800',
            'completed': 'bg-green-100 text-green-800',
            'failed': 'bg-red-100 text-red-800',
            'cancelled': 'bg-gray-100 text-gray-800'
        };
        return classes[status] || 'bg-gray-100 text-gray-800';
    }

    getStatusText(status) {
        const texts = {
            'pending': this.t('等待中'),
            'running': this.t('运行中'),
            'processing': this.t('处理中'),
            'completed': this.t('已完成'),
            'failed': this.t('失败'),
            'cancelled': this.t('已取消')
        };
        return texts[status] || this.t('未知');
    }

    updateHistoryPagination(pagination) {
        const prevBtn = document.getElementById('prevPageBtn');
        const nextBtn = document.getElementById('nextPageBtn');

        if (prevBtn) {
            prevBtn.disabled = !pagination.has_prev;
            if (pagination.has_prev) {
                prevBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            } else {
                prevBtn.classList.add('opacity-50', 'cursor-not-allowed');
            }
        }

        if (nextBtn) {
            nextBtn.disabled = !pagination.has_next;
            if (pagination.has_next) {
                nextBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            } else {
                nextBtn.classList.add('opacity-50', 'cursor-not-allowed');
            }
        }
    }
    
    async startGithubMonitor() {
        try {
            const repoUrl = document.getElementById('monitorRepoUrl').value.trim();
            
            if (!repoUrl) {
                this.showNotification('请输入GitHub仓库URL', 'error');
                return;
            }

            if (!repoUrl.startsWith('https://github.com/')) {
                this.showNotification('请输入有效的 GitHub 仓库 URL', 'error');
                return;
            }

            const saved = await this.saveMonitorRepoConfig();
            if (!saved) return;
            
            const response = await fetch('/api/github/webhook/enable', {
                method: 'POST'
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('GitHub 监控已启动', 'success');
                if (result.data) {
                    this.updateWebhookConfigDisplay({
                        ...result.data,
                        webhook_enabled: true,
                        webhook_secret_configured: result.data.webhook_secret_configured === true
                    });
                }
                this.loadGithubMonitorStatus();
            } else {
                this.showNotification(result.message || 'GitHub 监控启动失败', 'error');
            }
        } catch (error) {
            console.error('启动 GitHub 监控错误:', error);
            this.showNotification('启动 GitHub 监控失败', 'error');
        }
    }
    
    async stopGithubMonitor() {
        try {
            const response = await fetch('/api/github/webhook/disable', {
                method: 'POST'
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('GitHub 监控已停止', 'success');
                this.loadGithubMonitorStatus();
            } else {
                this.showNotification(result.message || 'GitHub 监控停止失败', 'error');
            }
        } catch (error) {
            console.error('停止 GitHub 监控错误:', error);
            this.showNotification('停止 GitHub 监控失败', 'error');
        }
    }
    
    async loadEmailConfig() {
        try {
            const response = await fetch('/api/email/config');
            const result = await response.json();
            
            if (result.success) {
                document.getElementById('emailSmtpServer').value = result.data.email_smtp_server || '';
                document.getElementById('emailSmtpPort').value = result.data.email_smtp_port || '587';
                document.getElementById('emailUsername').value = result.data.email_username || '';
                document.getElementById('emailPassword').value = result.data.email_password;
                document.getElementById('emailUseTls').checked = result.data.email_use_tls || false;
                
                document.getElementById('emailSender').value = result.data.email_sender || '';
                document.getElementById('emailRecipients').value = Array.isArray(result.data.email_recipients) ? result.data.email_recipients.join(', ') : (result.data.email_recipients || '');
                document.getElementById('emailSubjectTemplate').value = result.data.email_subject_template || this.t('文档纠错任务 [TASK_ID] 完成通知');
                
                document.getElementById('notifyOnLocalComplete').checked = result.data.notify_on_local_complete || false;
                document.getElementById('notifyOnGithubComplete').checked = result.data.notify_on_github_complete || false;
                document.getElementById('notifyOnError').checked = result.data.notify_on_error || false;
                document.getElementById('attachReport').checked = result.data.attach_report || false;
                
                document.getElementById('enableEmailNotifications').checked = result.data.email_notifications_enabled || false;
                
                const configStatus = document.getElementById('emailConfigStatus');
                if (result.data.is_configured) {
                    configStatus.textContent = this.t('已配置');
                    configStatus.className = 'px-2 py-1 rounded-full text-xs bg-green-100 text-green-800';
                } else {
                    configStatus.textContent = this.t('未配置');
                    configStatus.className = 'px-2 py-1 rounded-full text-xs bg-red-100 text-red-800';
                }
            }
        } catch (error) {
            console.error('加载邮件配置失败:', error);
            this.showNotification('加载邮件配置失败', 'error');
        }
    }
    
    async saveEmailConfig() {
        const smtpServer = document.getElementById('emailSmtpServer').value.trim();
        const smtpPort = parseInt(document.getElementById('emailSmtpPort').value.trim()) || 587;
        const username = document.getElementById('emailUsername').value.trim();
        const password = document.getElementById('emailPassword').value.trim();
        const useTls = document.getElementById('emailUseTls').checked;
        
        const sender = document.getElementById('emailSender').value.trim();
        const recipients = document.getElementById('emailRecipients').value.trim()
            .split(',').map(email => email.trim()).filter(email => email);
        const subjectTemplate = document.getElementById('emailSubjectTemplate').value.trim();
        
        const notifyOnLocalComplete = document.getElementById('notifyOnLocalComplete').checked;
        const notifyOnGithubComplete = document.getElementById('notifyOnGithubComplete').checked;
        const notifyOnError = document.getElementById('notifyOnError').checked;
        const attachReport = document.getElementById('attachReport').checked;
        
        const enableNotifications = document.getElementById('enableEmailNotifications').checked;
        
        if (enableNotifications) {
            if (!smtpServer) {
                this.showNotification('请输入 SMTP 服务器地址', 'error');
                return;
            }
            if (!username) {
                this.showNotification('请输入用户名', 'error');
                return;
            }
            if (!sender) {
                this.showNotification('请输入发件人邮箱', 'error');
                return;
            }
            if (recipients.length === 0) {
                this.showNotification('请输入至少一个收件人邮箱', 'error');
                return;
            }
        }
        
        try {
            const response = await fetch('/api/email/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email_smtp_server: smtpServer,
                    email_smtp_port: smtpPort,
                    email_username: username,
                    email_password: password,
                    email_use_tls: useTls,
                    email_sender: sender,
                    email_recipients: recipients,
                    email_subject_template: subjectTemplate,
                    notify_on_local_complete: notifyOnLocalComplete,
                    notify_on_github_complete: notifyOnGithubComplete,
                    notify_on_error: notifyOnError,
                    attach_report: attachReport,
                    email_notifications_enabled: enableNotifications
                })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('邮件配置保存成功', 'success');
                this.loadEmailConfig();
            } else {
                this.showNotification(result.message || '邮件配置保存失败', 'error');
            }
        } catch (error) {
            console.error('保存邮件配置失败:', error);
            this.showNotification('保存邮件配置失败', 'error');
        }
    }
    
    async sendTestEmail() {
        const testRecipient = document.getElementById('testEmailRecipient').value.trim();
        if (!testRecipient) {
            this.showNotification('请输入测试收件人邮箱', 'error');
            return;
        }
        
        try {
            const response = await fetch('/api/email/test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ test_recipient: testRecipient })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showNotification('测试邮件发送成功', 'success');
                document.getElementById('testEmailResult').textContent = this.t('测试邮件发送成功！');
                document.getElementById('testEmailResult').className = 'mt-2 text-sm text-green-600';
            } else {
                this.showNotification(result.message || '测试邮件发送失败', 'error');
                document.getElementById('testEmailResult').textContent = `${this.t('测试邮件发送失败:')} ${this.translate(result.message)}`;
                document.getElementById('testEmailResult').className = 'mt-2 text-sm text-red-600';
            }
        } catch (error) {
            console.error('发送测试邮件失败:', error);
            this.showNotification('发送测试邮件失败', 'error');
            document.getElementById('testEmailResult').textContent = `${this.t('测试邮件发送失败:')} ${this.translate(error.message)}`;
            document.getElementById('testEmailResult').className = 'mt-2 text-sm text-red-600';
        }
    }

    // GitHub monitor event log
    async loadMonitorLogs() {
        try {
            const response = await fetch('/api/github/webhook/logs');
            const result = await response.json();
            
            if (result.success && result.data) {
                const logsList = document.getElementById('monitorLogsList');
                const lastMonitorEventTime = document.getElementById('lastMonitorEventTime');
                
                logsList.innerHTML = '';
                
                if (result.data.logs && result.data.logs.length > 0) {
                    result.data.logs.forEach(log => {
                        const logEntry = document.createElement('div');
                        logEntry.className = 'p-2 border-b border-gray-200 last:border-0';
                        
                        let statusClass = '';
                        let statusIcon = '';
                        switch (log.status) {
                            case 'success':
                                statusClass = 'text-green-600';
                                statusIcon = '<i class="fas fa-check-circle"></i>';
                                break;
                            case 'error':
                                statusClass = 'text-red-600';
                                statusIcon = '<i class="fas fa-exclamation-circle"></i>';
                                break;
                            case 'warning':
                                statusClass = 'text-yellow-600';
                                statusIcon = '<i class="fas fa-exclamation-triangle"></i>';
                                break;
                            default:
                                statusClass = 'text-gray-600';
                                statusIcon = '<i class="fas fa-info-circle"></i>';
                        }
                        
                        const timestamp = new Date(log.timestamp);
                        const formattedTime = timestamp.toLocaleString(this.locale(), {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                        });
                        
                        logEntry.innerHTML = `
                            <div class="flex items-start">
                                <span class="${statusClass} mr-2">${statusIcon}</span>
                                <div class="flex-1">
                                    <div class="flex items-center justify-between">
                                        <span class="text-sm font-medium ${statusClass}">${this.escapeHtml(this.translate(log.message))}</span>
                                        <span class="text-xs text-gray-500">${formattedTime}</span>
                                    </div>
                                    ${log.details ? `<p class="text-xs text-gray-600 mt-1">${this.escapeHtml(this.translate(log.details))}</p>` : ''}
                                </div>
                            </div>
                        `;
                        
                        logsList.appendChild(logEntry);
                    });
                    
                    if (result.data.last_check) {
                        const lastCheck = new Date(result.data.last_check);
                        lastMonitorEventTime.textContent = this.t('最后事件时间: {time}', {
                            time: lastCheck.toLocaleString(this.locale())
                        });
                    } else {
                        lastMonitorEventTime.textContent = this.t('最后事件时间: 未知');
                    }
                } else {
                    logsList.innerHTML = `
                        <div class="text-sm text-gray-500 text-center py-4">
                            <i class="fas fa-inbox mb-2 text-gray-400 text-xl"></i>
                            <p>${this.t('暂无事件日志')}</p>
                        </div>
                    `;
                    lastMonitorEventTime.textContent = this.t('最后事件时间: 未知');
                }
            } else {
                const logsList = document.getElementById('monitorLogsList');
                logsList.innerHTML = `
                    <div class="text-sm text-red-500 text-center py-4">
                        <i class="fas fa-exclamation-circle mb-2 text-xl"></i>
                        <p>${this.t('加载事件日志失败')}</p>
                        <p class="text-xs mt-1">${this.escapeHtml(this.translate(result.message || '未知错误'))}</p>
                    </div>
                `;
                document.getElementById('lastMonitorEventTime').textContent = this.t('最后事件时间: 未知');
            }
        } catch (error) {
            console.error('加载事件日志失败:', error);
            const logsList = document.getElementById('monitorLogsList');
            logsList.innerHTML = `
                <div class="text-sm text-red-500 text-center py-4">
                    <i class="fas fa-exclamation-circle mb-2 text-xl"></i>
                    <p>${this.t('加载事件日志失败')}</p>
                    <p class="text-xs mt-1">${this.t('网络错误，请稍后重试')}</p>
                </div>
            `;
            document.getElementById('lastMonitorEventTime').textContent = this.t('最后事件时间: 未知');
        }
    }

    async regenerateWebhookSecret() {
        try {
            const response = await fetch('/api/github/webhook/secret/regenerate', { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                this.showNotification('Webhook Secret 已重新生成', 'success');
                this.updateWebhookConfigDisplay({
                    ...(result.data || {}),
                    webhook_secret_configured: true
                });
                await this.loadGithubMonitorStatus();
            } else {
                this.showNotification(result.message || '重新生成 Secret 失败', 'error');
            }
        } catch (error) {
            this.showNotification('重新生成 Secret 失败', 'error');
        }
    }

    async copyFromInput(elementId) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const text = (el.value || '').trim();
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            this.showNotification('已复制到剪贴板', 'success');
        } catch (error) {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                this.showNotification('已复制到剪贴板', 'success');
            } catch (e) {
                this.showNotification('复制失败', 'error');
            } finally {
                document.body.removeChild(textarea);
            }
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new DocumentReviewerApp();
});
