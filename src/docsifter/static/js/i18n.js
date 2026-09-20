const I18N_MESSAGES = {
  zh: {},
  en: {
  "审阅范围": "Scope",
  "仅有发现的文件": "Files with findings",
  "全部文件": "Every file",
  "每个文件发送整篇正文（最多 200 行）。默认只审已有发现的文件，成本跟随发现数；选「全部文件」则随文档数增长。": "Sends each file's whole prose body (up to 200 lines). By default only files that already have findings, so cost follows findings; choosing every file makes it follow document count instead.",
  "在 GitHub PR 审阅中也启用以上两层": "Also enable both layers for GitHub pull request reviews",
  "PR 审阅由 webhook 自动触发，没有人在旁边看着。默认关闭，开启后每个 PR 都会产生上面两层的调用。": "Pull request reviews are triggered by webhooks and run unattended. Off by default; enabling this makes every pull request call both layers above.",
  "大模型复核": "LLM review",
  "两层都默认关闭。开启后文档内容会发送到下面配置的端点。": "Both layers are off by default. Enabling one sends document content to the endpoint configured below.",
  "端点地址": "Endpoint URL",
  "模型名称": "Model name",
  "由环境变量锁定": "pinned by environment variable",
  "已配置": "configured",
  "未配置": "not configured",
  "留空则保持不变；只存在内存中，不写入配置文件": "Leave blank to keep the current key. Held in memory only, never written to the config file.",
  "逐条复核": "Per-finding verification",
  "只把小模型改过的那一条发出去：原句 + 建议句。规则命中的不发。": "Sends only what the small model changed: the original sentence plus the suggestion. Rule findings are not sent.",
  "每次上限": "Per-run cap",
  "跨行上下文审阅": "Cross-line context review",
  "文件上限": "File cap",
  "大模型设置保存失败": "Failed to save LLM settings",
  "- 包含所有检测结果，可标记新误报": "- Includes all detections and supports marking new false positives",
  "- 已自动过滤误报，适合分享和下载": "- False positives are filtered automatically; best for sharing and download",
  "DocSifter": "DocSifter",
  "AsciiDoc文件": "AsciiDoc file",
  "GitHub 仓库 URL": "GitHub Repository URL",
  "GitHub 仓库检测完成": "GitHub repository review completed",
  "GitHub Webhook 监控": "GitHub Webhook Monitoring",
  "GitHub 监控停止失败": "Failed to stop GitHub monitoring",
  "GitHub 监控启动失败": "Failed to start GitHub monitoring",
  "GitHub 监控已停止": "GitHub monitoring stopped",
  "GitHub 监控已启动": "GitHub monitoring started",
  "GitHub Webhook": "GitHub Webhook",
  "GitHub Webhook 功能。": "GitHub Webhook feature in the top navigation.",
  "PR 创建": "PR created",
  "PR 更新": "PR update",
  "PR 重开": "PR reopened",
  "SMTP 密码": "SMTP Password",
  "SMTP 服务器": "SMTP Server",
  "SMTP 用户名": "SMTP Username",
  "SMTP 端口": "SMTP Port",
  "Webhook Secret 已重新生成": "Webhook Secret regenerated",
  "事件日志": "Event Logs",
  "Webhook 配置": "Webhook Configuration",
  "上一页": "Previous",
  "下一页": "Next",
  "下载失败:": "Download failed:",
  "下载报告": "Download Report",
  "个)": "items)",
  "中文纠错 - 增强版 (7B)": "Chinese Correction - Enhanced (7B)",
  "中文纠错 - 通用版 (1.5B，推荐，CPU 可尝试)": "Chinese Correction - General (1.5B, recommended, CPU-friendly)",
  "规则预览模式": "Rule preview mode",
  "规则预览模式（默认，无需模型）": "Rule preview mode (default, no model required)",
  "规则预览模式无需模型；安装模型依赖后，推荐先使用 1.5B 小模型进行 AI 审查。": "Rule preview mode does not require a model. After installing model dependencies, start AI review with the recommended 1.5B small model.",
  "已选择模型: {model}": "Selected model: {model}",
  "仅处理变更文件": "Process only changed files",
  "从未检查": "Never checked",
  "仓库信息": "Repository Info",
  "任务ID": "Task ID",
  "任务处理失败": "Task processing failed",
  "任务处理完成": "Task processing completed",
  "任务已删除": "Task deleted",
  "任务已启动": "Task started",
  "任务已取消": "Task cancelled",
  "任务已被取消": "Task has been canceled",
  "任务详情": "Task Details",
  "作为模式匹配": "Use as pattern match",
  "使用 TLS 加密": "Use TLS encryption",
  "保存": "Save",
  "保存失败:": "Save failed:",
  "保存白名单": "Save Allowlist",
  "保存监控配置": "Save monitoring configuration",
  "保存监控配置失败": "Failed to save monitoring settings",
  "保存监控配置错误:": "Failed to save monitoring configuration:",
  "保存邮件配置": "Save Email Settings",
  "保存邮件配置失败": "Failed to save email configuration",
  "保存邮件配置失败:": "Failed to save email configuration:",
  "保存配置": "Save Settings",
  "修正数": "Corrections",
  "修正文本": "Correction",
  "停止 GitHub 监控失败": "Failed to stop GitHub monitoring",
  "停止 GitHub 监控错误:": "Failed to stop GitHub monitoring:",
  "停止监控": "Stop monitoring",
  "全选": "Select All",
  "全部类型": "All Types",
  "关闭": "Close",
  "删除": "Delete",
  "删除任务": "Delete task",
  "删除失败:": "Delete failed:",
  "删除误报记录失败": "Failed to delete false positive record",
  "删除误报记录失败:": "Failed to delete false positive records:",
  "刷新": "Refresh",
  "加载 GitHub 监控状态失败": "Failed to load GitHub monitoring status",
  "加载 GitHub 监控状态失败:": "Failed to load GitHub monitoring status:",
  "加载中...": "Loading...",
  "加载事件日志失败:": "Failed to load event log:",
  "加载仪表板状态失败:": "Failed to load dashboard status:",
  "加载任务日志失败:": "Failed to load task log:",
  "加载任务详情失败:": "Failed to load task details:",
  "加载任务进度失败:": "Failed to load task progress:",
  "加载历史记录失败:": "Failed to load history:",
  "加载执行历史失败": "Failed to load execution history",
  "加载执行历史失败:": "Failed to load execution history:",
  "加载模型状态失败:": "Failed to load model status:",
  "加载白名单失败": "Failed to load whitelist",
  "加载白名单失败:": "Failed to load whitelist:",
  "加载统计信息失败:": "Failed to load statistics:",
  "加载统计数据失败:": "Failed to load statistics:",
  "加载误报历史失败": "Failed to load false positive history",
  "加载误报历史失败:": "Failed to load false positive history:",
  "加载邮件配置失败": "Failed to load email settings",
  "加载邮件配置失败:": "Failed to load email configuration:",
  "加载配置失败:": "Failed to load configuration:",
  "匹配类型": "Match Type",
  "千字缺陷率": "Defect Rate per 1k Characters",
  "历史记录": "History",
  "原文": "Original",
  "原文内容": "Original Text",
  "发件人邮箱": "Sender Email",
  "发送测试邮件": "Send Test Email",
  "发送测试邮件失败": "Failed to send test email",
  "发送测试邮件失败:": "Failed to send test email:",
  "取消": "Cancel",
  "取消任务": "Cancel Task",
  "取消任务失败:": "Failed to cancel task:",
  "取消选择": "Clear Selection",
  "启动 GitHub 监控失败": "Failed to start GitHub monitoring",
  "启动 GitHub 监控错误:": "Failed to start GitHub monitoring:",
  "启动监控": "Start monitoring",
  "启用自动 AI 纠错": "Enable automatic AI review",
  "启用邮件通知": "Enable email notifications",
  "基本信息": "Basic information",
  "基础配置": "Basic configuration",
  "处理中": "Processing",
  "处理中...": "Processing...",
  "处理任务": "Processing Tasks",
  "处理失败:": "Processing failed:",
  "处理完成后自动发送通知邮件": "Send a notification email when review completes",
  "处理文件": "Process files",
  "处理日志": "Processing Log",
  "处理进度": "Progress",
  "处理选项": "Processing options",
  "备注说明（可选）": "Notes (optional)",
  "复制失败": "Copy failed",
  "失败": "Failed",
  "完成后发送邮件通知": "Send email notification when completed",
  "完成时间": "Completed",
  "完整版报告": "Full Report",
  "完整版报告不存在，请重新运行纠错任务": "Full report does not exist. Run the review again.",
  "完整记录每次处理的详细信息": "Keep a detailed record of every review",
  "导入": "Import",
  "导入失败:": "Import failed:",
  "导入失败：文件格式错误": "Import failed: invalid file format",
  "导出": "Export",
  "已取消": "Cancelled",
  "已复制到剪贴板": "Copied to clipboard",
  "已完成": "Completed",
  "已添加到白名单并保存": "Added to whitelist and saved",
  "已设置目录: {path}": "Directory set: {path}",
  "已选择目录: {path}": "Selected directory: {path}",
  "已选择文件: {path}": "Selected file: {path}",
  "已配置": "Configured",
  "开始处理": "Start Review",
  "开始处理文档...": "Starting document review...",
  "开始时间": "Started",
  "当前使用模型:": "Current model:",
  "当前白名单词汇": "Current Allowlist Terms",
  "总计: 0 | 筛选: 0 | 已选: 0": "Total: 0 | Filter: 0 | Selected: 0",
  "执行历史": "Run History",
  "执行历史记录": "Run History",
  "执行日志": "Run Log",
  "扫描文件数": "Scanned Files",
  "批量删除": "Delete Selected",
  "批量删除失败": "Batch deletion failed",
  "批量删除失败:": "Batch deletion failed:",
  "批量删除成功": "Batch deletion successful",
  "找不到GitHub监控设置模态框元素": "GitHub Monitor dialog not found",
  "报告下载成功": "Report download successful",
  "报告文件不存在，请重新运行纠错任务": "Report file does not exist. Run the review again.",
  "报告查看选项": "Report Options",
  "搜索": "Search",
  "搜索修正文本": "Search Correction",
  "搜索原文": "Search Original",
  "操作": "Actions",
  "收件人邮箱": "Recipient Emails",
  "文件数": "Number of files",
  "文档处理完成": "Document review completed",
  "文档纠错任务 [TASK_ID] 完成通知": "Document Correction Task [TASK_ID] Completion Notification",
  "文档纠错处理": "Document Review",
  "无效的JSON格式": "Invalid JSON format",
  "无效的文件格式": "Invalid file format",
  "无法获取目录列表": "Unable to fetch directory list",
  "时间": "Time",
  "显示最近": "Showing recent",
  "Webhook 自动审阅": "Webhook Auto Review",
  "智能纠错": "Intelligent error correction",
  "暂无事件日志": "No event logs yet",
  "暂无执行历史记录": "No run history yet",
  "最后事件时间: 未知": "Last event time: unknown",
  "最后更新": "Last Updated",
  "最后检查": "Last Checked",
  "最多显示最近50条记录": "Showing up to the latest 50 records",
  "有效修改数": "Valid Corrections",
  "未找到完整版报告，请重新运行纠错任务": "Full report was not found. Run the review again.",
  "未知": "Unknown",
  "未知标题": "Untitled",
  "未知错误": "Unknown error",
  "未设置": "Not set",
  "未配置": "Not configured",
  "本地目录处理": "Local Directory Review",
  "本地目录检测完成": "Local directory review completed",
  "条记录": "records",
  "查看报告": "View Report",
  "格式: 错误词汇=正确词汇，每行一个": "Format: Wrong words = Correct words, one per line",
  "检查运行中任务失败:": "Checking running tasks failed:",
  "检测过程出错": "Review failed",
  "模式": "Mode",
  "模式匹配": "Pattern Match",
  "正在处理中，请稍候...": "Processing, please wait...",
  "没有正在运行的任务": "No running task",
  "测试收件人": "Test Recipient",
  "测试邮件": "Test Email",
  "测试邮件发送失败": "Failed to send test email",
  "测试邮件发送失败:": "Test email failed to send:",
  "测试邮件发送成功": "Test email sent",
  "测试邮件发送成功！": "Test email sent!",
  "浏览": "Browse",
  "添加": "Add",
  "添加成功但保存失败:": "Added successfully but failed to save:",
  "添加误报": "Add False Positive",
  "添加误报记录": "Add False Positive",
  "添加误报记录失败": "Failed to add false positive record",
  "添加误报记录失败:": "Failed to add false positive record:",
  "清空": "Clear",
  "状态": "Status",
  "白名单": "Allowlist",
  "白名单保存失败:": "Whitelist saving failed:",
  "白名单保存成功": "Whitelist saved successfully",
  "白名单已导出": "The whitelist has been exported",
  "白名单管理": "Allowlist Management",
  "监控事件": "Monitor events",
  "监控状态": "Monitor status",
  "监控配置保存失败": "Failed to save monitoring settings",
  "监控配置保存成功": "Monitoring settings saved",
  "目录": "Directory",
  "确定要删除这个任务记录吗？此操作不可撤销。": "Are you sure you want to delete this task record? This action cannot be undone.",
  "确定要删除这条误报记录吗？": "Are you sure you want to delete this false positive record?",
  "确定要取消当前任务吗？": "Cancel the current task?",
  "等待中": "Pending",
  "类型": "Type",
  "精确": "Exact",
  "精确匹配": "Exact Match",
  "系统配置": "System Settings",
  "统计": "Stats",
  "统计信息": "Statistics",
  "网络连接失败，请检查网络或刷新页面重试": "Network connection failed, please check the network or refresh the page and try again",
  "耗时": "Duration",
  "自动对变更文件执行 AI 纠错": "Automatically perform AI correction on changed files",
  "自动生成报告": "Generate report automatically",
  "自动监控": "Automatic Monitoring",
  "获取任务日志失败:": "Failed to load task logs:",
  "获取任务进度失败:": "Failed to get task progress:",
  "获取历史总计统计失败:": "Failed to load historical totals:",
  "获取目录列表失败": "Failed to fetch directory list",
  "获取目录列表失败:": "Failed to get directory listing:",
  "该词汇已在白名单中": "The term is already in the whitelist",
  "详细统计": "Detailed Stats",
  "误报数据已导出": "False positive data exported",
  "误报管理": "False Positives",
  "误报记录已删除": "False positive records have been deleted",
  "误报记录已添加": "False positive record added",
  "请先选择要删除的项目": "Please select the items you want to delete first",
  "请填写原文内容和修正文本": "Please fill in the original content and revised text",
  "请输入 GitHub 仓库 URL": "Please enter the GitHub repository URL",
  "请输入 SMTP 服务器地址": "Enter an SMTP server",
  "请输入GitHub仓库URL": "Enter a GitHub repository URL",
  "请输入发件人邮箱": "Enter a sender email",
  "请输入有效的 GitHub 仓库 URL": "Enter a valid GitHub repository URL",
  "请输入测试收件人邮箱": "Enter a test recipient email",
  "请输入用户名": "Enter a username",
  "请输入白名单词汇": "Please enter the whitelist vocabulary",
  "请输入自定义目录路径:": "Enter a custom directory path:",
  "请输入至少一个收件人邮箱": "Enter at least one recipient email",
  "请输入要处理的目录路径": "Enter a directory path to review",
  "调试模式": "Debug mode",
  "输入要监控的 GitHub 仓库完整 URL": "Enter the full URL of the GitHub repository you want to monitor",
  "输入要跳过的文件模式，每行一个": "Enter file patterns to skip, one per line",
  "输入要跳过的文本模式，每行一个": "Enter text patterns to skip, one per line",
  "过滤版报告不存在，请重新运行纠错任务": "Filtered report does not exist. Run the review again.",
  "过滤版报告（推荐）": "Filtered Report (Recommended)",
  "运行中": "Running",
  "运行中任务": "Running Tasks",
  "进度": "Progress",
  "进度记录": "Progress History",
  "选择": "Select",
  "选择处理目录": "Directory to Review",
  "选择纠错模型": "Correction Model",
  "选择要处理的本地目录。如需处理 GitHub 仓库，请使用右上角的": "Choose a local directory to review. To review a GitHub repository, use the",
  "通知触发条件": "Notification Triggers",
  "通知设置": "Notification Settings",
  "通过 Webhook 实时接收 PR 变更事件": "Receive PR change events in real time through webhooks",
  "邮件主题模板": "Email Subject Template",
  "邮件服务配置": "Email Service Settings",
  "邮件通知": "Email Notifications",
  "邮件通知总开关": "Email Notifications Master Switch",
  "邮件通知设置": "Email notification settings",
  "邮件配置保存失败": "Failed to save email settings",
  "邮件配置保存成功": "Email settings saved",
  "配置": "Settings",
  "配置保存失败:": "Configuration save failed:",
  "配置保存成功": "Configuration saved successfully",
  "配置到 GitHub 仓库 Webhooks 的 Payload URL": "Use this as the Payload URL in GitHub repository Webhooks",
  "重新生成 Secret": "Regenerate Secret",
  "重新生成 Secret 失败": "Failed to regenerate Secret",
  "附加HTML报告到邮件": "Attach HTML report to email",
  "项目根目录": "Project Root",
  "高级配置": "Advanced configuration",
  "输入目录路径，如: ./examples/sample-docs": "Enter a directory path, for example ./examples/sample-docs",
  "输入白名单词汇，支持自动建议": "Enter an allowlist term. Suggestions are supported.",
  "搜索白名单词汇": "Search allowlist terms",
  "输入原文内容": "Enter original text",
  "输入修正文本": "Enter corrected text",
  "添加备注说明": "Add notes",
  "输入 SMTP 密码或应用专用密码": "Enter an SMTP password or app-specific password",
  "多个邮箱用逗号分隔": "Separate multiple emails with commas",
  "例如: [DocSifter] {task_type} 检测报告 - {date}": "Example: [DocSifter] {task_type} report - {date}",
  "[DocSifter] {task_type} 检测报告 - {date}": "[DocSifter] {task_type} report - {date}",
  "输入测试邮件收件人": "Enter test email recipient",
  "最后事件时间: {time}": "Last event time: {time}",
  "错误:": "Error:",
  "目录浏览器": "Directory Browser",
  "当前路径:": "Current path:",
  "选择此目录": "Select this directory",
  "进入浏览": "Open",
  "选择此文件": "Select this file",
  "选择当前目录": "Select Current Directory",
  "自定义路径": "Custom Path",
  "加载状态失败": "Failed to load status",
  "监控运行中": "Monitoring is running",
  "正常": "Healthy",
  "监控仓库": "Monitored Repository",
  "触发方式": "Trigger Method",
  "监控未运行": "Monitoring is stopped",
  "停止": "Stopped",
  "请配置仓库信息并启动监控": "Configure repository details and start monitoring",
  "加载事件日志失败": "Failed to load event logs",
  "网络错误，请稍后重试": "Network error. Please try again later.",
  "下载": "Download",
  "以下数据为所有已完成任务的累计统计": "Cumulative statistics for all completed tasks",
  "任务 {id}": "Task {id}",
  "修改统计（总计）": "Correction Statistics (Total)",
  "历史千字缺陷率:": "Historical defect rate per 1k characters:",
  "历史平均修改率:": "Historical average corrections per file:",
  "历史总计统计": "Historical Totals",
  "强制修复规则": "Forced Fix Rules",
  "总计: {total} | 筛选: {filtered} | 已选: {selected}": "Total: {total} | Filtered: {filtered} | Selected: {selected}",
  "文件统计（总计）": "File Statistics (Total)",
  "暂无匹配的白名单词汇": "No matching allowlist terms",
  "暂无历史记录": "No history yet",
  "暂无日志记录": "No logs yet",
  "暂无统计信息": "No statistics yet",
  "暂无误报记录": "No false positive records",
  "暂无进度记录": "No progress records",
  "查看详情": "View Details",
  "检测字符数": "Reviewed Characters",
  "现有白名单中的相似项：": "Similar existing allowlist terms:",
  "确定要删除选中的 {count} 个项目吗？": "Delete the selected {count} item(s)?",
  "确定要删除选中的 {count} 条误报记录吗？": "Delete the selected {count} false positive record(s)?",
  "累计总修改数:": "Total corrections:",
  "累计扫描文件数:": "Total scanned files:",
  "累计有效修改数:": "Total valid corrections:",
  "累计检测字符数:": "Total reviewed characters:",
  "累计空格问题:": "Total whitespace issues:",
  "缺陷率": "Defect Rate",
  "该词汇已存在于白名单中": "This term already exists in the allowlist",
  "质量指标（总计）": "Quality Metrics (Total)",
  "跳过文件模式": "Skip File Patterns",
  "跳过文本模式": "Skip Text Patterns",
  "例如: 587": "Example: 587",
  "例如: smtp.gmail.com": "Example: smtp.gmail.com",
  "例如: user@example.com": "Example: user@example.com",
  "Secret 已配置；重新生成后仅显示一次": "Secret configured; rotate it to display it once",
  "保存配置后生成 Secret": "Save the configuration to generate a secret",
  "保存 Webhook 配置时会记录当前选择。": "The current selection is saved with the Webhook configuration."
}
};

(function () {
  const DEFAULT_LANGUAGE = 'zh';
  const STORAGE_KEY = 'docsifter.language';
  const LOCALES = { zh: 'zh-CN', en: 'en-US' };
  const TEXT_NODE_SOURCE = new WeakMap();
  const translatedAttrPrefix = 'i18nSource';
  const sortedKeyCache = {};
  let currentLanguage = normalizeLanguage(
    localStorage.getItem(STORAGE_KEY)
      || DEFAULT_LANGUAGE
  );

  function normalizeLanguage(language) {
    return language === 'en' ? 'en' : 'zh';
  }

  function getDictionary(language = currentLanguage) {
    return I18N_MESSAGES[normalizeLanguage(language)] || {};
  }

  function getSortedKeys(language = currentLanguage) {
    const normalized = normalizeLanguage(language);
    if (!sortedKeyCache[normalized]) {
      sortedKeyCache[normalized] = Object.keys(getDictionary(normalized))
        .filter((key) => key && key.trim().length > 1)
        .sort((a, b) => b.length - a.length);
    }
    return sortedKeyCache[normalized];
  }

  // Some labels are rendered through t() and written straight into the DOM, so
  // a node created while the UI is in English arrives already translated. Its
  // English text must not become its recorded source, or switching back to
  // Chinese would leave it in English forever. An English value that more than
  // one Chinese key produces is skipped: picking between two phrasings would
  // put the wrong word on screen, and leaving it alone is what already happens.
  let reverseDictionary = null;

  function getReverseDictionary() {
    if (!reverseDictionary) {
      const seen = new Map();
      reverseDictionary = new Map();
      for (const [key, translated] of Object.entries(getDictionary('en'))) {
        seen.set(translated, (seen.get(translated) || 0) + 1);
        reverseDictionary.set(translated, key);
      }
      for (const [translated, count] of seen) {
        if (count > 1) reverseDictionary.delete(translated);
      }
    }
    return reverseDictionary;
  }

  function sourceValueFor(value) {
    if (currentLanguage !== 'en') return value;
    const text = String(value ?? '');
    const trimmed = text.trim();
    if (!trimmed) return value;
    const original = getReverseDictionary().get(trimmed);
    return original === undefined ? value : text.replace(trimmed, original);
  }

  function interpolate(value, params = {}) {
    return String(value ?? '').replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) => {
      return Object.prototype.hasOwnProperty.call(params, key) ? params[key] : match;
    });
  }

  function t(key, params = {}) {
    const source = String(key ?? '');
    if (currentLanguage === 'zh') {
      return interpolate(source, params);
    }
    const dictionary = getDictionary();
    return interpolate(dictionary[source] || source, params);
  }

  function translateText(value, params = {}) {
    const source = String(value ?? '');
    if (!source || currentLanguage === 'zh') {
      return interpolate(source, params);
    }

    const dictionary = getDictionary();
    const trimmed = source.trim();
    if (dictionary[trimmed]) {
      return source.replace(trimmed, interpolate(dictionary[trimmed], params));
    }

    let translated = source;
    for (const key of getSortedKeys()) {
      if (translated.includes(key)) {
        translated = spliceTranslation(translated, key, dictionary[key]);
      }
    }
    return interpolate(translated, params);
  }

  // A Chinese sentence needs no space after 。, so one text node often holds two
  // sentences that are two separate dictionary keys. Splicing them one at a time
  // would weld the English halves together -- "...1.5B small model.The current
  // selection..." -- so a boundary between sentence punctuation and a word gets
  // the space that English needs.
  const SENTENCE_END = /[.!?,;:]$/;
  const WORD_START = /^[A-Za-z0-9([]/;

  function joinTranslated(left, right) {
    if (!left || !right) return left + right;
    if (SENTENCE_END.test(left) && WORD_START.test(right)) {
      return left + ' ' + right;
    }
    return left + right;
  }

  function spliceTranslation(text, key, value) {
    const parts = text.split(key);
    let out = parts[0];
    for (let index = 1; index < parts.length; index += 1) {
      out = joinTranslated(out, value);
      out = joinTranslated(out, parts[index]);
    }
    return out;
  }

  function sourceDatasetKey(attributeName) {
    return translatedAttrPrefix + attributeName.replace(/(^|-)([a-z])/g, (_, __, char) => char.toUpperCase());
  }

  function setTextFromKey(element, key, asHtml = false) {
    const translated = t(key);
    if (asHtml) {
      if (element.innerHTML !== translated) element.innerHTML = translated;
    } else if (element.textContent !== translated) {
      element.textContent = translated;
    }
  }

  function applyExplicitTranslations(root) {
    const scope = root || document;
    const textElements = collectElements(scope, '[data-i18n]');
    textElements.forEach((element) => setTextFromKey(element, element.getAttribute('data-i18n')));

    const htmlElements = collectElements(scope, '[data-i18n-html]');
    htmlElements.forEach((element) => setTextFromKey(element, element.getAttribute('data-i18n-html'), true));

    const attrMap = [
      ['data-i18n-placeholder', 'placeholder'],
      ['data-i18n-title', 'title'],
      ['data-i18n-aria-label', 'aria-label'],
      ['data-i18n-value', 'value']
    ];
    attrMap.forEach(([keyAttr, targetAttr]) => {
      collectElements(scope, '[' + keyAttr + ']').forEach((element) => {
        const key = element.getAttribute(keyAttr);
        const translated = t(key);
        if (targetAttr === 'value') {
          if (element.value !== translated) element.value = translated;
          element.setAttribute('value', translated);
        } else {
          element.setAttribute(targetAttr, translated);
        }
      });
    });
  }

  function applyFallbackAttributes(root) {
    const scope = root || document;
    ['placeholder', 'title', 'aria-label'].forEach((attributeName) => {
      collectElements(scope, '[' + attributeName + ']').forEach((element) => {
        const dataKey = sourceDatasetKey(attributeName);
        const current = element.getAttribute(attributeName) || '';
        if (!element.dataset[dataKey]) {
          element.dataset[dataKey] = current;
        }
        const source = element.dataset[dataKey];
        const next = currentLanguage === 'zh' ? source : translateText(source);
        if (current !== next) element.setAttribute(attributeName, next);
      });
    });
  }

  function collectElements(root, selector) {
    if (!root) return [];
    const elements = [];
    if (root.nodeType === Node.ELEMENT_NODE && root.matches(selector)) {
      elements.push(root);
    }
    if (typeof root.querySelectorAll === 'function') {
      elements.push(...root.querySelectorAll(selector));
    }
    return elements;
  }

  function shouldSkipTextNode(node) {
    const parent = node.parentElement;
    if (!parent) return true;
    if (parent.closest('script, style, textarea, code, pre, [data-i18n], [data-i18n-html]')) {
      return true;
    }
    return !node.nodeValue || !node.nodeValue.trim();
  }

  function applyTextNodes(root) {
    const scope = root && root.nodeType !== Node.DOCUMENT_NODE ? root : document.body;
    if (!scope) return;

    if (scope.nodeType === Node.TEXT_NODE) {
      translateTextNode(scope);
      return;
    }

    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      translateTextNode(node);
    }
  }

  function translateTextNode(node) {
    if (shouldSkipTextNode(node)) return;
    if (!TEXT_NODE_SOURCE.has(node)) {
      TEXT_NODE_SOURCE.set(node, sourceValueFor(node.nodeValue));
    }
    const source = TEXT_NODE_SOURCE.get(node);
    const next = currentLanguage === 'zh' ? source : translateText(source);
    if (node.nodeValue !== next) {
      node.nodeValue = next;
    }
  }

  function updateLanguageButton() {
    const button = document.getElementById('langToggleBtn');
    if (!button) return;
    const label = currentLanguage === 'en' ? '中文' : 'English';
    const nextHtml = '<i class="fas fa-language mr-2"></i>' + label;
    const nextLabel = currentLanguage === 'en' ? 'Switch to Chinese' : 'Switch to English';
    if (button.innerHTML !== nextHtml) {
      button.innerHTML = nextHtml;
    }
    if (button.getAttribute('aria-label') !== nextLabel) {
      button.setAttribute('aria-label', nextLabel);
    }
  }

  function apply(root = document) {
    if (document.documentElement) {
      document.documentElement.lang = LOCALES[currentLanguage];
    }
    if (document.title) {
      document.title = t('DocSifter');
    }
    applyExplicitTranslations(root);
    applyFallbackAttributes(root);
    applyTextNodes(root);
    updateLanguageButton();
  }

  function setLanguage(language) {
    const nextLanguage = normalizeLanguage(language);
    if (nextLanguage === currentLanguage) {
      apply(document);
      return;
    }
    currentLanguage = nextLanguage;
    localStorage.setItem(STORAGE_KEY, currentLanguage);
    apply(document);
    window.dispatchEvent(new CustomEvent('i18n:change', { detail: { language: currentLanguage } }));
  }

  function localizeHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    apply(template.content);
    return template.innerHTML;
  }

  function locale() {
    return LOCALES[currentLanguage];
  }

  function formatDateTime(value, options) {
    if (!value) return '';
    const date = value instanceof Date ? value : new Date(value);
    return date.toLocaleString(locale(), options);
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'childList') {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === Node.TEXT_NODE) {
            translateTextNode(node);
          } else if (node.nodeType === Node.ELEMENT_NODE || node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
            apply(node);
          }
        });
      } else if (mutation.type === 'characterData') {
        if (!TEXT_NODE_SOURCE.has(mutation.target)) {
          TEXT_NODE_SOURCE.set(mutation.target, sourceValueFor(mutation.target.nodeValue));
        }
        translateTextNode(mutation.target);
      }
    }
  });

  document.addEventListener('DOMContentLoaded', () => {
    const toggleButton = document.getElementById('langToggleBtn');
    if (toggleButton) {
      toggleButton.addEventListener('click', () => setLanguage(currentLanguage === 'en' ? 'zh' : 'en'));
    }
    apply(document);
    if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }
  });

  window.I18n = {
    t,
    translateText,
    apply,
    setLanguage,
    getLanguage: () => currentLanguage,
    locale,
    formatDateTime,
    localizeHtml,
    messages: I18N_MESSAGES
  };
  window.t = t;
  window.setLanguage = setLanguage;
  window.i18nInitialized = true;
})();
