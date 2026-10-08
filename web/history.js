'use strict';
// Historical inventory is an optional, independent data source. It never enters db.runs or statistics.
(() => {
  const host = document.querySelector('#history-coverage');
  const pageSize = 100;
  const text = value => String(value ?? '未知');
  const escape = value => text(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value.toLocaleString('zh-CN');
  const statuses = {
    public_verified: '公开证据已核验',
    import_pending: '待导入公开看板',
    evidence_missing: '缺少必要证据',
    in_progress: '进行中 / 尚未完成',
    legacy_unclassified: '历史记录待分类'
  };
  const reasons = {
    native_result: '缺少原生结果', episode_complete: '缺少原生完成事件',
    native_ack: '缺少执行确认记录', archive_marker: '缺少已核验的归档标记',
    public_transcript: '缺少公开过程记录', native_videos: '缺少完整三视角录像',
    public_demo: '缺少公开说明演示', receipts: '缺少调用与用量凭据',
    scene_identity: '场景身份尚未核验', source_lock: '缺少源码版本锁定记录',
    upload: '文件尚未上传完成', public_download: '公开下载尚未核验'
  };
  const statusLabel = value => statuses[value] ?? '历史记录待分类';
  const missing = run => Array.isArray(run.missing) ? run.missing.map(value => reasons[value] ?? text(value)).join('；') : '';
  const familyLabel = family => family.label || family.family_id || '未命名实验批次';
  function counts(family) {
    const runs = family.runs;
    return [runs.length, runs.filter(run => run.local_complete === true).length,
      ...['public_verified', 'import_pending', 'evidence_missing'].map(status => runs.filter(run => run.status === status).length)];
  }
  function mountFamily(details, family) {
    if (details.dataset.loaded) return;
    details.dataset.loaded = 'true';
    const body = details.querySelector('.history-family-body');
    body.innerHTML = `<label class="history-search">搜索本批次的运行 ID、任务、场景或状态<input type="search" placeholder="输入任务 ID、种子、状态或缺失原因…"></label><div class="history-pagebar"><span role="status"></span><div><button type="button" data-page="previous">上一页</button><button type="button" data-page="next">下一页</button></div></div><div class="table-wrap"><table class="history-runs"><thead><tr><th>运行 ID</th><th>任务</th><th>官方种子 / 布局</th><th>盘点状态</th><th>待补项与说明</th></tr></thead><tbody></tbody></table></div>`;
    const input = body.querySelector('input');
    const previous = body.querySelector('[data-page="previous"]');
    const next = body.querySelector('[data-page="next"]');
    const rows = body.querySelector('tbody');
    const pageLabel = body.querySelector('[role="status"]');
    let page = 0;
    function render() {
      const query = input.value.trim().toLowerCase();
      const matches = family.runs.filter(run => !query || [run.run_id, run.task,
        run.official_seed == null ? '' : '种子 ' + run.official_seed,
        run.layout_ordinal == null ? '' : '布局 ' + run.layout_ordinal,
        run.status, statusLabel(run.status), missing(run)].join(' ').toLowerCase().includes(query));
      const pages = Math.max(1, Math.ceil(matches.length / pageSize));
      page = Math.min(page, pages - 1);
      const start = page * pageSize;
      rows.innerHTML = matches.slice(start, start + pageSize).map(run => `<tr><td><code>${escape(run.run_id)}</code></td><td>${escape(run.task)}</td><td>${escape(run.official_seed)} / ${escape(run.layout_ordinal)}</td><td><span class="pill ${run.status === 'public_verified' ? '' : 'warn'}">${escape(statusLabel(run.status))}</span></td><td>${escape(missing(run) || (run.status === 'evidence_missing' ? '尚未列出缺失项' : '—'))}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">本批次没有符合搜索条件的记录。</td></tr>';
      pageLabel.textContent = matches.length ? `显示 ${number(start + 1)}–${number(Math.min(start + pageSize, matches.length))} / ${number(matches.length)} 条 · 第 ${page + 1} / ${pages} 页` : '显示 0 条';
      previous.disabled = page === 0;
      next.disabled = page >= pages - 1;
    }
    input.addEventListener('input', () => { page = 0; render(); });
    previous.addEventListener('click', () => { if (page > 0) page--; render(); });
    next.addEventListener('click', () => { page++; render(); });
    render();
  }
  async function bootHistory() {
    try {
      const response = await fetch('data/history-coverage.json');
      if (response.status === 404) {
        host.innerHTML = '<p class="muted">尚未发布历史覆盖盘点；上方公开结果可正常查看。</p>';
        return;
      }
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const inventory = await response.json();
      if (inventory.schema_version !== '1.0' || !Array.isArray(inventory.families) ||
          inventory.families.some(family => !family || !Array.isArray(family.runs) || family.runs.some(run => !run || typeof run.run_id !== 'string'))) {
        throw new Error('历史盘点格式不符合约定');
      }
      const families = inventory.families;
      if (!families.length) {
        host.innerHTML = '<p class="muted">历史覆盖盘点中暂无记录。</p>';
        return;
      }
      const timestamp = new Date(inventory.generated_at);
      if (Number.isFinite(timestamp.getTime())) document.querySelector('#history-updated').textContent = '盘点时间：' + timestamp.toLocaleString('zh-CN');
      host.innerHTML = `${Array.isArray(inventory.limitations) && inventory.limitations.length ? `<div class="notice"><strong>盘点范围说明</strong><ul>${inventory.limitations.map(item => `<li>${escape(item)}</li>`).join('')}</ul></div>` : ''}<div class="table-wrap"><table class="history-summary"><thead><tr><th>实验批次 / 系列</th><th>发现记录数</th><th>本地完成数</th><th>公开详细记录数</th><th>待导入数</th><th>缺证据数</th></tr></thead><tbody>${families.map((family, index) => `<tr><td><button type="button" data-history-open="${index}">${escape(familyLabel(family))} ↓</button><small>${escape(family.family_id)}</small></td>${counts(family).map(count => `<td>${number(count)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="footnote">数量按各批次记录计算；本地完成与发布状态可能重叠，不能将各列相加。公开详细记录数仅统计盘点中标记为“公开证据已核验”的记录。进行中和待分类记录计入发现数。展开批次后可搜索，每页最多显示 ${pageSize} 条。</p><div class="history-families">${families.map((family, index) => `<details class="history-family" id="history-family-${index}"><summary>${escape(familyLabel(family))}<span class="muted">${number(family.runs.length)} 条记录</span></summary><div class="history-family-body"></div></details>`).join('')}</div>`;
      const details = Array.from(host.querySelectorAll('.history-family'));
      details.forEach((element, index) => element.addEventListener('toggle', () => { if (element.open) mountFamily(element, families[index]); }));
      host.querySelectorAll('[data-history-open]').forEach(button => button.addEventListener('click', () => {
        const element = details[Number(button.dataset.historyOpen)];
        element.open = true;
        mountFamily(element, families[Number(button.dataset.historyOpen)]);
        element.scrollIntoView({block:'nearest'});
      }));
    } catch (error) {
      host.innerHTML = '<p class="muted">历史覆盖盘点暂时无法加载；上方公开结果不受影响。请稍后重试。</p>';
    }
  }
  bootHistory();
})();
