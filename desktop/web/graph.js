/* Extend the upstream UI without maintaining a second graph implementation. */
const upstreamCairnApp = window.cairnApp;
window.cairnApp = function () {
  const app = upstreamCairnApp();
  const init = app.init, api = app.api, factLabel = app.summarizeFactLabel;
  const savePrefs = app.saveLocalPrefs, saveWidth = app.saveSidePanelWidth;
  for (const name of ['intentStatusLabel','timelineEventBadge','replayProgressLabel']) {
    if (typeof app[name] !== 'function') continue;
    const original = app[name];
    app[name] = function (...args) {
      const value = original.apply(this, args);
      return translations[value] || String(value).replace(/^Replay /, '回放 ');
    };
  }
  Object.assign(app, {
    desktopRecords: [], desktopRecordId: '', desktopRecordsLinked: false,
    desktopTokenUsage: {project: null, intent: null},
    desktopOutput: {stdout: '', stderr: ''}, desktopRecordTab: '执行输出',
    _desktopLoadSequence: 0, _desktopOutputSequence: 0,
    summarizeFactLabel(fact) {
      return fact.id === 'origin' ? '起点' : fact.id === 'goal' ? '目标' : factLabel.call(this, fact);
    },
    async init() {
      this.localPrefs.layout_mode = 'klay_tb';
      this.sidePanelWidth = 390;
      try {
        const preferences = await (await fetch('/desktop/preferences')).json();
        if (preferences.layout_mode) {
          localStorage.setItem('cairn.localPrefs', JSON.stringify(preferences));
          localStorage.setItem('cairn.sidePanelWidth', String(preferences.sidePanelWidth));
        }
      } catch(e) { console.warn('读取界面偏好失败', e); }
      await init.call(this);
      window.desktopGraphApp = this;
      this.$watch('selectedNode', () => this.loadDesktopRecords());
      this.$watch('selectedProjectId', () => this.loadDesktopRecords());
      // The shell initially hides its iframe; resize after switching tabs.
      window.addEventListener('resize', () => { if (this.cy) this.cy.resize(); });
    },
    actorName() { return this.localPrefs.actor_name === 'Human' ? '用户' : this.localPrefs.actor_name; },
    saveLocalPrefs() { savePrefs.call(this); this.saveDesktopPreferences(); },
    saveSidePanelWidth() { saveWidth.call(this); this.saveDesktopPreferences(); },
    applyDesktopPreferences(preferences) {
      clearTimeout(this._desktopPreferencesTimer);
      Object.assign(this.localPrefs, preferences);
      this.sidePanelWidth = preferences.sidePanelWidth;
      this.layoutMode = preferences.layout_mode;
      savePrefs.call(this);
      saveWidth.call(this);
      if (this.cy) { this.cy.resize(); this.applySelectedLayout(); }
    },
    saveDesktopPreferences() {
      clearTimeout(this._desktopPreferencesTimer);
      this._desktopPreferencesTimer = setTimeout(() => fetch('/desktop/preferences', {method:'PUT',
        headers:{'Content-Type':'application/json','X-Cairn-Token':window.DESKTOP_TOKEN},
        body:JSON.stringify({...this.localPrefs,sidePanelWidth:this.sidePanelWidth})}).catch(console.warn), 250);
    },
    async api(method, path, body) {
      if (method === 'GET') return api.call(this, method, path, body);
      const response = await fetch(path, {method,
        headers: {'Content-Type': 'application/json', 'X-Cairn-Token': window.DESKTOP_TOKEN},
        body: body ? JSON.stringify(body) : undefined});
      if (response.status === 204) return null;
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败');
      return data;
    },
    async loadDesktopRecords() {
      const sequence = ++this._desktopLoadSequence;
      if (!this.selectedProjectId) {
        this.desktopRecords = []; this.desktopRecordId = ''; this.desktopOutput = {stdout:'',stderr:''};
        this.desktopTokenUsage = {project:null,intent:null};
        return;
      }
      let intent = '';
      if (this.selectedNode?.type === 'intent') intent = this.selectedNode.id;
      else if (this.selectedNode?.type === 'fact') intent = this.getProducingIntent(this.selectedFactId())?.id || '';
      try {
        const response = await fetch(`/desktop/projects/${encodeURIComponent(this.selectedProjectId)}/runs?intent_id=${encodeURIComponent(intent)}`);
        if (!response.ok) throw new Error('读取阶段失败');
        const data = await response.json();
        if (sequence !== this._desktopLoadSequence) return;
        this.desktopRecords = data.records; this.desktopRecordsLinked = data.node_linked;
        this.desktopTokenUsage = data.token_usage || {project:null,intent:null};
        if (!this.desktopRecords.some(r => r.record_id === this.desktopRecordId)) this.desktopRecordId = this.desktopRecords[0]?.record_id || '';
        await this.loadDesktopRecord();
      } catch (e) { if (sequence === this._desktopLoadSequence) this.desktopOutput = {stdout:e.message,stderr:''}; }
    },
    desktopSelectedRecord() { return this.desktopRecords.find(r => r.record_id === this.desktopRecordId) || null; },
    formatTokenUsage(usage) {
      if (!usage) return '未提供';
      if (usage.reported_stages === 0) return `未提供 · ${usage.total_stages || 0} 个阶段无用量记录`;
      const fmt = key => Number.isFinite(usage[key]) ? usage[key].toLocaleString('zh-CN') : '—';
      const stages = Number.isFinite(usage.reported_stages) ? ` · ${usage.reported_stages}/${usage.total_stages} 阶段已记录` : '';
      return `输入 ${fmt('input_tokens')} · 输出 ${fmt('output_tokens')} · 合计 ${fmt('total_tokens')}${stages}`;
    },
    async loadDesktopRecord() {
      const sequence = ++this._desktopOutputSequence;
      this.desktopOutput = {stdout:'',stderr:''};
      if (!this.desktopRecordId) return;
      const response = await fetch(`/desktop/projects/${encodeURIComponent(this.selectedProjectId)}/runs/${encodeURIComponent(this.desktopRecordId)}`);
      const data = await response.json();
      if (sequence === this._desktopOutputSequence) this.desktopOutput = response.ok ? data : {stdout:data.detail,stderr:''};
    },
    async openDesktopFolder(recordId) {
      const response = await fetch('/desktop/action', {method:'POST',
        headers:{'Content-Type':'application/json','X-Cairn-Token':window.DESKTOP_TOKEN},
        body:JSON.stringify({action:recordId?'open_run':'open_project',project_id:this.selectedProjectId,record_id:recordId})});
      if (!response.ok) this.showToast((await response.json()).detail, 'error');
    },
  });
  return app;
};

// Translate UI literals, never task descriptions, node IDs or exported records.
const translations = {
  'Detail':'详情','Hints':'提示','Log':'时间线','Replay':'回放','Snapshot':'快照',
  'Stop':'停止','Resume':'继续','Delete':'删除','Reopen':'重新打开','Intent':'行动',
  'Complete':'完成','Hint':'提示','Claim':'领取','Release':'释放','Conclude':'提交结果',
  'Fact':'事实','Origin':'起点','Goal':'目标','From':'输入事实','To':'输出事实',
  'Creator':'创建者','Worker':'执行者','Concluded':'完成时间','Created':'创建时间',
  'Produced by':'来源行动','Produced By':'来源行动','Role':'角色',
  'Project starting point':'任务起点','Project target fact':'任务目标',
  'Click a node or edge':'点击节点或连线查看详情','Shift+click for multi-select':'按住 Shift 点击可多选',
  'Fast':'快速','Normal':'正常','Slow':'慢速','Exit':'退出','Remove':'移除',
  'Cancel':'取消','Save':'保存','Settings':'设置','Server Settings':'服务设置',
  'New Project':'新建任务','New project':'新建任务','Projects':'任务列表',
  'Title':'标题','Origin fact':'起始事实','Goal fact':'目标事实','Create':'创建',
  'Create project':'创建任务','Create Project':'创建任务','Add Hint':'添加提示',
  'Description':'说明','Human':'用户','ACTIVE':'运行中','STOPPED':'已停止','COMPLETED':'已完成',
  'Intent timeout (seconds)':'行动超时（秒）','Reason timeout (seconds)':'规划超时（秒）',
  'Copy':'复制','Close':'关闭','Timeline':'时间线','Default layout':'默认布局',
  'Actor name':'操作人名称','Local preferences':'界面偏好','Local Preferences':'界面偏好',
  'Actor':'操作人','Save Local':'保存界面设置','Save Server':'保存服务设置',
  'Stored only in this browser.':'保存在本机数据目录中。','Shared backend configuration.':'此配置由所有任务共享。',
  'No projects yet':'暂无任务','Create a project to start exploring':'创建任务后即可开始探索',
  'Bootstrap':'初始化','Bootstrap Running':'初始化中','Bootstrap Pending':'等待初始化',
  'In Progress':'处理中','Unclaimed':'待领取','PROJECT':'项目','INTENT':'行动','CONCLUDE':'提交结果',
  'HINT':'提示','REASON':'规划','STOP':'停止','COMPLETE':'完成',
  'Project title':'任务标题','Origin — starting point':'起点：当前已知信息',
  'Goal — what to achieve':'目标：希望达成的结果','Your name':'你的名称',
  'Fit graph':'适应画布','Rename project':'重命名任务','Stop all active projects':'停止所有运行中的任务',
  'Active projects':'运行中的任务','Stopped projects':'已停止的任务','Completed projects':'已完成的任务',
  'What will you explore?':'描述下一步行动','What did you find? (new fact)':'描述本次行动得出的事实',
  'Why is the goal met?':'说明目标已经达成的依据',
};
function translateRoot(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const node of texts) {
    const parent = node.parentElement;
    if (!parent || parent.closest('script,style,pre,[x-text],[x-html]')) continue;
    const literal = node.textContent.trim(), translated = translations[literal];
    if (translated) node.textContent = node.textContent.replace(literal, translated);
  }
  root.querySelectorAll?.('template').forEach(t => translateRoot(t.content));
  root.querySelectorAll?.('[placeholder],[title],[aria-label]').forEach(element => {
    for (const attr of ['placeholder','title','aria-label']) {
      const value = element.getAttribute(attr);
      if (translations[value]) element.setAttribute(attr, translations[value]);
    }
  });
}
translateRoot(document.body);
