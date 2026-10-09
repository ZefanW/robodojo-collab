'use strict';
(() => {
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits:2});
  const percentage = value => value == null ? '—' : `${num(value)}%`;
  const capNames = {'Generalization':'泛化','Memory':'记忆','Precision':'精细操作','Long-Horizon':'长程任务','Open':'开放任务'};
  const viewNames = {head:'头部相机',left_wrist:'左腕相机',right_wrist:'右腕相机'};
  const verificationNames = {remote_sha256:'远端文件 SHA-256 已核验',bundle_remote_sha256:'所在归档包 SHA-256 已核验',local_sha256:'本地 SHA-256 已核验'};
  const pageBase = new URL('.', location.href);
  const selected = new URLSearchParams(location.search).get('panel') || 'astra-l3-cap20-seed0-scene0';
  const panelId = /^[a-zA-Z0-9_-]+$/.test(selected) ? selected : 'astra-l3-cap20-seed0-scene0';
  const cap20Pilot = panelId === 'astra-l3-cap20-seed0-scene0';
  const indexURL = new URL(`data/publications/${panelId}/index.json`, pageBase).href;
  const correctionsURL = new URL('data/publication-metadata-corrections.json', pageBase).href;
  let panel = null, activeRun = null, dialogVersion = 0;
  let correctionsPromise = null;
  const detailCache = new Map();
  const timelineCache = new Map();

  function safeURL(value, base = pageBase) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try { const url = new URL(value, value.startsWith('data/') ? pageBase : base); return ['http:','https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
  }
  function link(value, label, base, className = '') {
    const url = safeURL(value, base);
    return url ? `<a class="${esc(className)}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>` : `<span class="muted">${esc(label)}暂不可用</span>`;
  }
  function isReused(run) { return run.reused_original === true || run.provenance?.reused_original === true || run.provenance?.reused === true; }
  function nativeVLA(data) { return data?.execution_kind === 'native_vla'; }
  function executionSummary(run) { return nativeVLA(run) || nativeVLA(panel) ? `${num(run.policy_action_requests)} 次动作请求 · ${num(run.policy_rpc_calls)} 次策略 RPC` : `${num(run.model_decisions)} 决策 · ${num(run.actual_responses)} 响应`; }
  function score(run) { return run.score_percent ?? (run.score == null ? null : run.score * 100); }
  function successChip(value) { return `<span class="result-chip ${value === true ? 'success' : value == null ? 'unknown' : ''}">${value === true ? '成功' : value === false ? '未成功' : '未记录'}</span>`; }
  function panelSummary(data) {
    if (data.metric_profile === 'standard42') return data.standard42 || data.summary || {};
    if (data.metric_profile === 'devset10') return data.devset10 || data.summary || {};
    return data.official54 || data.summary?.official_summary || data.summary?.official54 || data.official_summary || data.summary || {};
  }
  function simulation(value) { return typeof value === 'object' && value ? value.simulator_version || value.version || value.name || '—' : value || '—'; }
  function assetKind(artifact, native = false) { return /demo|rationale/i.test(artifact.kind) ? native ? '原始三视角合成视频' : '公开说明演示' : /video/i.test(artifact.kind) ? viewNames[artifact.view] || '原生录像' : /timeline/i.test(artifact.kind) ? '可读轨迹 JSON' : artifact.path || artifact.kind; }
  function costSummary(manifest) {
    const costs = manifest.costs || {}, attempts = costs.attempts;
    if (Array.isArray(attempts)) return {known:attempts.reduce((sum,a)=>sum+(a.input_tokens??0)+(a.output_tokens??0),0),cached:attempts.reduce((sum,a)=>sum+(a.cached_input_tokens??0),0),unknown:attempts.filter(a=>a.usage_known===false||a.input_tokens==null||a.output_tokens==null).length};
    return {known:costs.known_total_tokens ?? costs.total_tokens ?? null,cached:costs.known_cached_input_tokens ?? costs.cached_input_tokens ?? null,unknown:costs.unknown_usage_count ?? costs.unknown_attempts ?? null};
  }
  async function getJSON(url, options) { const response = await fetch(url, options); if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }
  async function correctionFor(manifest, run) {
    if (nativeVLA(manifest) || nativeVLA(run) || nativeVLA(panel)) return {status:'none'};
    const resolver = globalThis.PublicationMetadataCorrections;
    if (!resolver) return {status:'unavailable'};
    if (!correctionsPromise) correctionsPromise = (async () => {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 8000);
      try { return {document:await getJSON(correctionsURL,{cache:'no-store',signal:controller.signal})}; }
      catch { return {status:'unavailable'}; }
      finally { clearTimeout(timer); }
    })();
    const loaded = await correctionsPromise;
    if (loaded.status) return loaded;
    if (manifest.run_id !== run.run_id) return {status:'rejected'};
    return resolver.resolve(loaded.document,manifest);
  }
  function renderCorrectionNote(correction) {
    if (correction.status === 'none') return '';
    const text = correction.status === 'applied'
      ? '发布元数据更正：仅提示与工具 SHA。成绩、轨迹、视频不变，原归档保留。新旧值见「来源与文件」。'
      : correction.status === 'rejected' ? '更正条目与原记录不匹配，当前显示原归档元数据。'
      : correction.status === 'invalid' ? '更正清单未通过校验，当前显示原归档元数据。'
      : '更正清单暂不可用，当前显示原归档元数据；尚未核对是否有更正。';
    return `<p class="detail-note metadata-correction-note" role="status">${esc(text)}</p>`;
  }
  function renderCorrectionFiles(correction) {
    if (correction.status !== 'applied') return '';
    return `<section class="metadata-correction-files" aria-label="发布元数据更正"><h3>发布元数据更正</h3><div class="evidence-grid">${correction.fields.map(item=>`<dl><dt>${item.field === 'prompt_sha256' ? '提示' : '工具'} SHA-256${item.changed ? ' · 已更正' : ' · 不变'}</dt><dd>展示值${item.changed ? '（更正后）' : ''}：<br><code class="corrected-hash">${esc(item.corrected)}</code><br>原归档值：<br><code class="original-hash">${esc(item.original)}</code></dd></dl>`).join('')}</div><p class="detail-note">仅核对并展示这两个元数据字段；下方原始清单、证据包与媒体链接均保留原样。<br>${link(correctionsURL,'下载独立更正 JSON',pageBase)}</p></section>`;
  }

  function renderPanel() {
    const summary = panelSummary(panel), runs = panel.runs || [], reused = runs.filter(isReused).length;
    const devset = panel.metric_profile === 'devset10', standard42 = panel.metric_profile === 'standard42';
    const metricLabel = standard42 ? '标准42 · 五项能力各占 20%' : panel.metric_label || (devset ? 'Devset10 · 10-task equal weight' : 'Full54 · 官方五项能力权重');
    const weighting = devset ? `${num(summary.planned ?? 10)} 项任务等权` : '五项能力等权';
    const originalTitle = panel.title || (typeof panel.algorithm === 'object' ? panel.algorithm.algorithm_id : panel.algorithm) || panel.panel_id;
    const title = standard42 ? (/Standard42|标准42/i.test(originalTitle) ? originalTitle.replace(/Standard42/gi,'标准42') : `${originalTitle} · 标准42`) : originalTitle;
    $('#panel-title').textContent = title;
    document.title = `${title} · 公开结果 | RoboDojo`;
    $('#cases-title').textContent = `${num(runs.length)} 个案例，逐个可核验`;
    if (nativeVLA(panel)) $('#hero-description').innerHTML = '查看冻结 checkpoint 的原生 VLA 任务得分、实际动作与录像。<br>轨迹保留原生动作和反馈，没有自然语言理由的记录不会补写。';
    $('#panel-tags').innerHTML = [
      `官方 seed ${panel.official_seed ?? '—'}`, `layout ${panel.layout_ordinal ?? '—'}`, `${num(runs.length)} 个任务`, metricLabel
    ].concat(nativeVLA(panel) ? ['纯 VLA · 冻结 checkpoint'] : []).map(text=>`<span class="tag">${esc(text)}</span>`).join('');
    $('#scope-description').textContent = reused ? `${num(runs.length-reused)} 条本轮记录 + ${num(reused)} 条原记录复用${cap20Pilot ? '（满足 cap20 长度等价条件）' : '（依据见详情）'}。本次发布没有重新运行实验。` : `${num(runs.length)} 条已有实验记录。本次发布没有重新运行实验，保留原得分、执行记录与来源。`;
    $('#scope-note').innerHTML = standard42
      ? `<strong>如何理解这些分数：</strong>这是标准42的 seed${esc(panel.official_seed)} / layout${esc(panel.layout_ordinal)} 样本：12 项标准泛化、6 项记忆、8 项精细操作、8 项长程任务、8 项开放任务。先在各能力内平均，再由五项能力各占 20%；不含 random 随机变体，不属于 Full54，也不等同于官方排行榜认证或跨种子鲁棒性验证。42 项计划任务全部有效后才给出总体分数，缺失或无效结果不计零分，不借用其他 layout 的结果。`
      : devset
      ? `<strong>如何理解这些分数：</strong>这是原定 Devset10 的 seed${esc(panel.official_seed)} / layout${esc(panel.layout_ordinal)} ${num(summary.planned ?? 10)} 任务样本，按任务等权汇总；能力卡仅作分项描述。本结果不属于 Full54，也不等同于官方排行榜认证或跨种子鲁棒性验证。全部计划任务有效后才给出总体分数，缺失或无效结果不计零分。`
      : `<strong>如何理解这些分数：</strong>这是 seed${esc(panel.official_seed)} / layout${esc(panel.layout_ordinal)} 的 ${num(summary.planned ?? runs.length)} 任务样本，按官方五项能力权重汇总${panel.panel_id === 'astra-l3-cap20-seed0-scene0' ? '，属于方法选择基线' : ''}；不等同于官方排行榜认证，也不代表跨种子鲁棒性。完整执行与任务成功分别列示，缺失或无效结果不计零分。`;
    $('#panel-metrics').innerHTML = [
      [standard42 ? '标准42 Score' : devset ? 'Devset10 Score' : '官方加权 Score', num(summary.score), '/ 100',weighting],
      [standard42 ? '标准42 成功率' : devset ? 'Devset10 成功率' : '官方加权成功率', percentage(summary.success_rate), '',`SR · ${weighting}`],
      ['有效原生终态', num(summary.valid ?? summary.completed_tasks), `/ ${num(summary.planned ?? runs.length)}`,'完成 ≠ 任务成功'],
      ['公开案例', num(runs.length), '例',`${num(reused)} 条原记录复用 · 点击按需读取`]
    ].map(([label,value,unit,note])=>`<div class="pub-metric"><span class="metric-label">${esc(label)}</span><strong>${value}<small>${esc(unit)}</small></strong><p>${esc(note)}</p></div>`).join('');
    $('#panel-metrics').hidden = false;
    const capabilities = summary.capabilities || {};
    $('#capability-title').textContent = devset ? '五项能力，分项描述' : '五项能力，各占 20%';
    $('#capability-note').textContent = standard42 ? '仅标准任务 · 12 / 6 / 8 / 8 / 8 · 能力内取平均' : devset ? '总体按任务等权 · 此处分项不另行加权' : '能力内按原协议计算';
    $('#capabilities').innerHTML = Object.entries(capabilities).map(([key,entry])=>`<article class="capability-card"><span class="capability-name">${esc(capNames[key] || key)}<small>${esc(key)}</small></span><span class="capability-score">${num(entry.score)}<small>Score</small></span><div class="capability-bar" aria-hidden="true"><span style="width:${Math.min(100,Math.max(0,Number(entry.score)||0))}%"></span></div><div class="capability-meta"><span>SR ${percentage(entry.success_rate)}</span><span>${num(entry.valid)} / ${num(entry.planned)}</span></div></article>`).join('');
    $('#capability-section').hidden = Object.keys(capabilities).length === 0;
    for (const cap of [...new Set(runs.map(r=>r.capability).filter(Boolean))]) { const option = document.createElement('option'); option.value = cap; option.textContent = capNames[cap] || cap; $('#capability-filter').append(option); }
    const generated = new Date(panel.generated_at);
    $('#generated-at').textContent = Number.isNaN(generated.getTime()) ? '' : `清单更新 ${generated.toLocaleString('zh-CN')}`;
    $('#load-status').hidden = true;
    renderRows();
  }
  function renderRows() {
    const query = $('#case-query').value.trim().toLowerCase(), capability = $('#capability-filter').value, result = $('#result-filter').value;
    const runs = (panel?.runs || []).filter(r=>(!query || `${r.task} ${r.run_id}`.toLowerCase().includes(query)) && (!capability || r.capability===capability) && (!result || result==='success' && r.success===true || result==='not-success' && r.success===false || result==='reused' && isReused(r)));
    $('#case-count').textContent = `显示 ${runs.length} / ${panel?.runs?.length || 0} 个案例`;
    $('#case-rows').innerHTML = runs.map(r=>`<tr><td><strong class="task-name">${esc(r.task)}${isReused(r)?'<span class="reuse-chip">复用原记录</span>':''}</strong><small class="task-meta">${esc(r.variant === 'random' ? '随机变体' : r.variant === 'standard' ? '标准任务' : r.variant || '原始任务')} · ${r.status==='complete'?'原生终态已完成':esc(r.status)}</small></td><td>${esc(capNames[r.capability] || r.capability)}</td><td class="numeric"><span class="table-score">${num(score(r))}</span></td><td>${successChip(r.success)}</td><td>${num(r.control_steps)} 控制步<small class="task-meta">${executionSummary(r)}</small></td><td>${esc(simulation(r.simulator ?? r.simulator_version))}</td><td><button class="detail-button" type="button" data-run="${esc(r.run_id)}" aria-label="查看 ${esc(r.task)} 的视频与轨迹">视频与轨迹 ↗</button></td></tr>`).join('') || '<tr><td colspan="7" class="empty-state">没有符合筛选条件的案例。</td></tr>';
  }

  function renderVideo(artifact, base, native = false) {
    const storage = artifact.storage || {}, verified = safeURL(storage.playback_url,base);
    const candidateValue = storage.playback_candidate_url || (typeof storage.playback_candidate === 'string' ? storage.playback_candidate : storage.playback_candidate?.url) || (storage.playback_candidate === true ? storage.download_url : null);
    const candidate = safeURL(candidateValue,base), playback = verified || candidate;
    const status = verified ? '清单已登记播放直链' : candidate ? '播放器兼容性待确认；可尝试播放或下载' : '尚无可用播放直链；请下载或前往云盘';
    return `<article class="media-card"><h4>${esc(assetKind(artifact,native))}</h4>${playback ? `<video controls preload="none" playsinline src="${esc(playback)}" aria-label="${esc(assetKind(artifact,native))}"></video>` : '<div class="media-placeholder">视频文件已列入清单<br>请使用下方下载或云盘链接</div>'}<div class="media-info"><p class="playback-status ${verified?'verified':''}" role="status">${status}</p><div class="media-links">${link(storage.download_url,'下载视频',base)}${storage.landing_url ? link(storage.landing_url,'云盘页面',base) : ''}</div><p style="margin-top:8px">${num(artifact.bytes / 1048576)} MiB · ${esc(verificationNames[storage.verification] || '远端文件核验待完成')}</p></div></article>`;
  }
  function renderVideos(manifest, base) {
    if (nativeVLA(manifest)) return renderNativeVideos(manifest,base);
    const artifacts = manifest.artifacts || [], native = artifacts.filter(a=>/video/i.test(a.kind)&&!/demo|rationale/i.test(a.kind)), demos = artifacts.filter(a=>/demo|rationale/i.test(a.kind));
    return `<div class="media-heading"><h3>原生三视角录像</h3><span>点击播放才加载视频</span></div><div class="media-grid">${native.map(a=>renderVideo(a,base)).join('') || '<p class="muted">清单中未登记原生录像。</p>'}</div><h3>公开说明演示</h3><div class="media-grid demo-grid">${demos.map(a=>renderVideo(a,base)).join('') || '<p class="muted">清单中未登记演示视频。</p>'}<div class="demo-caption"><strong>对照动作与当时的公开说明。</strong>演示中的说明来自原始工具可见记录，保留当时的文本。更完整的动作参数与原生反馈，可在「可读轨迹」中按时间顺序查看。</div></div>`;
  }
  function renderFiles(manifest, base, correction) {
    if (nativeVLA(manifest)) return renderNativeFiles(manifest,base);
    const algorithm = manifest.algorithm || {}, scene = manifest.scene || {}, protocol = manifest.protocol || {}, environment = manifest.environment || {}, costs = costSummary(manifest), pkg = manifest.package;
    return `${renderCorrectionFiles(correction)}<div class="evidence-grid"><dl><dt>算法与客户端</dt><dd>${esc(algorithm.algorithm_id || algorithm.model)}<br>${esc(algorithm.model)} · ${esc(algorithm.reasoning_effort)}<br>Codex ${esc(algorithm.codex_client_version)}</dd></dl><dl><dt>场景与协议</dt><dd>${esc(manifest.publication_scope?.metric_label || panel.metric_label || (panel.metric_profile === 'devset10' ? 'Devset10 · 10-task equal weight' : 'Full54 · 官方五项能力权重'))}<br>seed ${esc(scene.official_seed)} / layout ${esc(scene.layout_ordinal)}<br>${esc(protocol.id)} · 动作前缀上限 ${num(protocol.action_limit)}<br>场景 SHA-256：${esc(scene.asset_sha256)}</dd></dl><dl><dt>实际环境</dt><dd>${esc(environment.simulator_version)}<br>GPU：${esc(environment.gpu == null ? '历史记录未提供' : typeof environment.gpu === 'object' ? JSON.stringify(environment.gpu) : environment.gpu)}<br>驱动：${esc(environment.driver)}</dd></dl><dl><dt>全部已记录消耗</dt><dd>${num(costs.known)} 个已知输入与输出 token<br>其中缓存输入 ${num(costs.cached)}，已计入总量<br>${num(costs.unknown)} 条未知用量记录</dd></dl></div>${pkg ? `<div class="package-card">${link(pkg.download_url,pkg.scope==='panel'?`下载本轮轨迹与核验证据包（${num(pkg.run_count ?? panel.run_count ?? panel.runs.length)}例，不含视频）`:'下载轨迹与核验证据包',base)}<p>${num(pkg.bytes / 1048576)} MiB · ${esc(pkg.format || '归档包')}<br>SHA-256 ${esc(pkg.sha256)}</p></div>` : ''}<h3>公开文件与核验</h3><ul class="file-list">${(manifest.artifacts||[]).map(a=>{const storage=a.storage||{};return `<li><div><strong>${esc(assetKind(a))}</strong><div class="media-links">${storage.download_url?link(storage.download_url,storage.bundle_member?'下载所在证据包':'下载',base):storage.bundle_member?'<span class="muted">见本轮证据包</span>':'<span class="muted">独立下载未登记</span>'}${storage.timeline_url?link(storage.timeline_url,'轨迹 JSON',base):''}${storage.landing_url?link(storage.landing_url,'云盘页面',base):''}</div><code>${esc(a.path)}<br>SHA-256 ${esc(a.sha256)}</code></div><span>${num(a.bytes)} 字节<br>${esc(verificationNames[storage.verification] || '核验待完成')}</span></li>`;}).join('')}</ul><details><summary>原算法、来源与复用说明（完整公开清单）</summary><pre>${esc(JSON.stringify(manifest,null,2))}</pre></details>`;
  }

  function renderNativeVideos(manifest, base) {
    const artifacts = manifest.artifacts || [], native = artifacts.filter(a=>/video/i.test(a.kind)&&!/demo|rationale/i.test(a.kind)), demos = artifacts.filter(a=>/demo|rationale/i.test(a.kind));
    if (panel.metric_profile === 'standard42' && demos.length === 0) return `<div class="media-heading"><h3>原生三视角录像</h3><span>点击播放才加载视频</span></div><div class="media-grid">${native.map(a=>renderVideo(a,base,true)).join('') || '<p class="muted">清单中未登记原生录像。</p>'}</div><h3>原始三视角合成视频</h3><p class="muted">本案例没有原始合成视频；本次发布未生成演示或补写自然语言理由。可分别查看已登记的原生相机录像，并在「可读轨迹」查看数值动作与原生反馈。</p>`;
    return `<div class="media-heading"><h3>原生三视角录像</h3><span>点击播放才加载视频</span></div><div class="media-grid">${native.map(a=>renderVideo(a,base,true)).join('') || '<p class="muted">清单中未登记原生录像。</p>'}</div><h3>原始三视角合成视频</h3><div class="media-grid demo-grid">${demos.map(a=>renderVideo(a,base,true)).join('') || '<p class="muted">清单中未登记合成视频。</p>'}<div class="demo-caption"><strong>冻结 checkpoint 的原生 VLA 执行记录。</strong>原生 VLA 没有自然语言理由记录。合成视频保留原始三视角；数值动作与原生反馈可在「可读轨迹」中按原顺序查看。</div></div>`;
  }
  function renderNativeFiles(manifest, base) {
    const algorithm = manifest.algorithm || {}, checkpoint = algorithm.checkpoint || {}, scene = manifest.scene || {}, protocol = manifest.protocol || {}, environment = manifest.environment || {}, costs = manifest.costs || {}, pkg = manifest.package;
    const unknown = value => value == null ? '未知（历史记录未提供）' : num(value);
    const attemptCount = Array.isArray(costs.attempts) ? costs.attempts.length : costs.attempt_records;
    return `<div class="evidence-grid"><dl><dt>冻结策略与 checkpoint</dt><dd>${esc(algorithm.algorithm_id || algorithm.model)}<br>策略版本：${esc(algorithm.version)}<br>Checkpoint：${esc(checkpoint.name || '历史记录未提供')}<br>Checkpoint SHA-256：${esc(checkpoint.sha256 || '未知（历史记录未提供）')}<br>Revision：${esc(checkpoint.revision || '历史记录未提供')}<br>策略源码：${esc(algorithm.source_commit || '历史记录未提供')}</dd></dl><dl><dt>场景与协议</dt><dd>${esc(panel.metric_profile === 'standard42' ? '标准42 · 五项能力各占 20%' : manifest.publication_scope?.metric_label || panel.metric_label || 'Full54 · 官方五项能力权重')}<br>seed ${esc(scene.official_seed)} / layout ${esc(scene.layout_ordinal)}<br>${esc(protocol.id)}<br>原动作限制：${protocol.action_limit == null ? '见原策略配置' : num(protocol.action_limit)}<br>场景 SHA-256：${esc(scene.asset_sha256)}</dd></dl><dl><dt>实际环境</dt><dd>${esc(environment.simulator_version)}<br>GPU：${esc(environment.gpu == null ? '历史记录未提供' : typeof environment.gpu === 'object' ? JSON.stringify(environment.gpu) : environment.gpu)}<br>驱动：${esc(environment.driver)}</dd></dl><dl><dt>原生 VLA 消耗记录</dt><dd>语言模型用量：不适用<br>策略动作请求：${num(manifest.outcome?.policy_action_requests ?? costs.policy_action_requests)}<br>全部策略 RPC：${num(manifest.outcome?.policy_rpc_calls ?? costs.policy_rpc_calls)}<br>内部推理次数：未单独计量<br>独立动作块数：未单独计量<br>GPU 小时：${unknown(costs.gpu_hours)}<br>GPU 费用（美元）：${unknown(costs.gpu_dollar_cost)}<br>已保存尝试：${num(attemptCount)}<br>${costs.attempts_complete === true ? '原清单标记尝试记录完整' : '尝试覆盖未确认完整；缺失用量未按零计'}</dd></dl></div>${pkg ? `<div class="package-card">${link(pkg.download_url,pkg.scope==='panel'?`下载本轮轨迹与核验证据包（${num(pkg.run_count ?? panel.run_count ?? panel.runs.length)}例，不含视频）`:'下载轨迹与核验证据包',base)}<p>${num(pkg.bytes / 1048576)} MiB · ${esc(pkg.format || '归档包')}<br>SHA-256 ${esc(pkg.sha256)}</p></div>` : ''}<h3>公开文件与核验</h3><ul class="file-list">${(manifest.artifacts||[]).map(a=>{const storage=a.storage||{};return `<li><div><strong>${esc(assetKind(a,true))}</strong><div class="media-links">${storage.download_url?link(storage.download_url,storage.bundle_member?'下载所在证据包':'下载',base):storage.bundle_member?'<span class="muted">见本轮证据包</span>':'<span class="muted">独立下载未登记</span>'}${storage.timeline_url?link(storage.timeline_url,'轨迹 JSON',base):''}${storage.landing_url?link(storage.landing_url,'云盘页面',base):''}</div><code>${esc(a.path)}<br>SHA-256 ${esc(a.sha256)}</code></div><span>${num(a.bytes)} 字节<br>${esc(verificationNames[storage.verification] || '核验待完成')}</span></li>`;}).join('')}</ul><details><summary>原策略、checkpoint 与来源（完整公开清单）</summary><pre>${esc(JSON.stringify(manifest,null,2))}</pre></details>`;
  }
  function renderNativeTimeline(events) {
    return events.map((event,index)=>{
      const tool = event.tool_call || {}, note = event.public_note ?? event.note, feedback = event.feedback;
      const interval = event.control_start != null && event.control_end != null ? `<span>实际控制区间 ${num(event.control_start)} → ${num(event.control_end)}</span>` : '<span>控制区间未记录</span>';
      return `<li class="timeline-item"><div class="event-heading"><strong>原生动作 ${esc(event.step ?? event.index ?? index + 1)}</strong><span class="event-tool">${esc(tool.name || event.tool || event.kind || '原生事件')}</span>${interval}${event.accepted===false?'<span class="result-chip unknown">未接受</span>':''}</div>${note == null ? '' : `<p class="event-note">${esc(typeof note==='string'?note:JSON.stringify(note,null,2))}</p>`}<details><summary>数值动作与原生反馈（原文）</summary><pre>${esc(JSON.stringify(tool.arguments ?? event.arguments ?? {},null,2))}</pre><p class="feedback">${feedback==null?'此事件没有记录反馈。':esc(typeof feedback==='string'?feedback:JSON.stringify(feedback,null,2))}</p></details></li>`;
    }).join('');
  }

  async function openDetail(run) {
    const version = ++dialogVersion, dialog = $('#case-dialog');
    activeRun = null;
    $('#case-title').textContent = run.task;
    $('#case-subtitle').textContent = `seed ${panel.official_seed} / layout ${panel.layout_ordinal} · ${capNames[run.capability] || run.capability}`;
    $('#case-detail').innerHTML = '<p class="muted">正在读取这个案例的公开清单…</p>';
    if (!dialog.open) dialog.showModal();
    const base = safeURL(run.detail_url,indexURL);
    try {
      if (!base) throw new Error('缺少有效的详情地址');
      let manifest = detailCache.get(base);
      if (!manifest) { manifest = await getJSON(base); detailCache.set(base,manifest); }
      if (version!==dialogVersion) return;
      const correction = await correctionFor(manifest,run);
      if (version!==dialogVersion) return;
      activeRun = {manifest,base,version,timelineLoaded:false};
      const outcome = manifest.outcome || {}, scoreValue = outcome.score_percent ?? (outcome.score == null ? null : outcome.score * 100);
      const metrics = [['原生 Score',num(scoreValue),'/ 100'],['任务结果',outcome.success===true?'成功':outcome.success===false?'未成功':'未记录',outcome.episode_complete?'原生终态已完成':'终态见公开证据'],['控制步',num(outcome.control_steps),'原生实际执行'],...(nativeVLA(manifest) ? [['策略动作请求',num(outcome.policy_action_requests),'依据原策略接口记录'],['全部策略 RPC',num(outcome.policy_rpc_calls),'与实际控制步分别统计']] : [['模型决策',num(outcome.model_decisions),'决策次数'],['实际响应',num(outcome.actual_responses),'保留全部已记录尝试']])];
      $('#case-detail').innerHTML = `<div class="detail-metrics">${metrics.map(([label,value,note])=>`<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join('')}</div>${isReused(run)?`<p class="detail-note reused">本案例复用既有实验记录${cap20Pilot?'：原动作长度满足 cap20 等价条件':''}，原算法与来源身份保留。本次没有重新运行。${run.provenance?.reuse_reason?`<br>原始依据：${esc(run.provenance.reuse_reason)}`:''}</p>`:''}${renderCorrectionNote(correction)}<div class="detail-tabs" role="tablist" aria-label="案例内容"><button id="tab-videos" role="tab" aria-selected="true" aria-controls="pane-videos" data-pane="videos">视频</button><button id="tab-timeline" role="tab" aria-selected="false" aria-controls="pane-timeline" tabindex="-1" data-pane="timeline">可读轨迹</button><button id="tab-files" role="tab" aria-selected="false" aria-controls="pane-files" tabindex="-1" data-pane="files">来源与文件</button></div><section id="pane-videos" role="tabpanel" aria-labelledby="tab-videos">${renderVideos(manifest,base)}</section><section id="pane-timeline" role="tabpanel" aria-labelledby="tab-timeline" hidden><div id="timeline-content"><p class="muted">正在读取原始公开轨迹…</p></div></section><section id="pane-files" role="tabpanel" aria-labelledby="tab-files" hidden>${renderFiles(manifest,base,correction)}</section>`;
      $('#case-detail').querySelectorAll('video').forEach(video=>{
        video.addEventListener('error',()=>{video.closest('.media-card').querySelector('.playback-status').textContent='此浏览器暂无法播放，请下载视频或打开云盘页面。';});
        video.addEventListener('playing',()=>{const status=video.closest('.media-card').querySelector('.playback-status');status.textContent='本次浏览器已开始播放';status.classList.add('verified');});
      });
    } catch (error) { if (version===dialogVersion) $('#case-detail').innerHTML=`<p class="error-message">无法加载此案例的公开清单：${esc(error.message)}。请稍后重试。</p>`; }
  }
  function selectPane(name, focus = false) {
    $('#case-detail').querySelectorAll('[data-pane]').forEach(button=>{const selected=button.dataset.pane===name;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;if(selected&&focus)button.focus();});
    ['videos','timeline','files'].forEach(id=>{$(`#pane-${id}`).hidden=id!==name;});
    if(name!=='videos') $('#case-detail').querySelectorAll('video').forEach(video=>video.pause());
    if(name==='timeline' && activeRun && !activeRun.timelineLoaded) loadTimeline(activeRun);
  }
  async function loadTimeline(context) {
    context.timelineLoaded = true;
    const artifact = (context.manifest.artifacts||[]).find(a=>/timeline|public_audit|trajectory/i.test(a.kind) && (a.storage?.timeline_url||a.storage?.json_url));
    const url = safeURL(artifact?.storage?.timeline_url || artifact?.storage?.json_url,context.base);
    try {
      if(!url) throw new Error('本清单未登记在线轨迹地址；可在「来源与文件」下载公开证据包。');
      let timeline=timelineCache.get(url);if(!timeline){timeline=await getJSON(url);timelineCache.set(url,timeline);}
      if(context.version!==dialogVersion) return;
      const events=Array.isArray(timeline)?timeline:timeline.events||timeline.steps||[];
      if (nativeVLA(context.manifest)) {
        $('#timeline-content').innerHTML = `<div class="timeline-intro"><p>冻结 checkpoint 的原生 VLA 数值动作与原生反馈，按原记录顺序呈现。没有自然语言理由记录，不补写公开说明。每条记录对应一次原始动作提交，不能当成一次内部推理或一个动作块。策略动作请求与全部 RPC 分别列示；内部推理次数和独立动作块数未单独计量。控制区间以原生执行反馈为准。</p>${link(url,'完整轨迹 JSON',context.base)}</div><p class="timeline-count">共 ${num(events.length)} 条原生动作记录</p><ol class="timeline-list">${renderNativeTimeline(events)}</ol>`;
        return;
      }
      $('#timeline-content').innerHTML=`<div class="timeline-intro"><p>按原记录顺序呈现工具调用、当时的公开说明与原生反馈。公开说明是原始工具可见文本，不包含模型私有推理；未记录的说明不会补写。同一决策可能含多次请求；控制区间对应该决策整体，单次请求是否移动以原生反馈为准。</p>${link(url,'完整轨迹 JSON',context.base)}</div><p class="timeline-count">共 ${num(events.length)} 条公开事件</p><ol class="timeline-list">${events.map((event,index)=>{const note=event.public_note??event.note??event.instruction;const feedback=event.feedback;return `<li class="timeline-item"><div class="event-heading"><strong>决策 ${esc(event.policy_step??event.control_step??event.step??event.index??index)}</strong><span class="event-tool">${esc(event.tool||'原生事件')}</span><span>该决策控制区间 ${num(event.control_start)} → ${num(event.control_end)}</span>${event.accepted===false?'<span class="result-chip unknown">未接受</span>':''}</div><p class="event-note">${note==null?'<span class="muted">此事件没有记录公开说明。</span>':esc(typeof note==='string'?note:JSON.stringify(note,null,2))}</p><details><summary>动作参数与原生反馈（原文）</summary><pre>${esc(JSON.stringify(event.arguments??{},null,2))}</pre><p class="feedback">${feedback==null?'此事件没有记录反馈。':esc(typeof feedback==='string'?feedback:JSON.stringify(feedback,null,2))}</p></details></li>`;}).join('')}</ol>`;
    } catch(error) {if(context.version===dialogVersion)$('#timeline-content').innerHTML=`<p class="error-message">${esc(error.message)}${url?' 可在「来源与文件」使用下载链接。':''}</p>`;}
  }
  async function loadCatalog() {
    try {
      const catalog = await getJSON(new URL('data/publications/catalog.json',pageBase), {cache:'no-store'});
      const panels = catalog.panels || []; if(panels.length<2) return;
      const label=document.createElement('label');label.className='panel-switcher';label.textContent='切换公开实验';
      const select=document.createElement('select');select.setAttribute('aria-label','切换公开实验');
      for(const item of panels){const option=document.createElement('option');option.value=item.panel_id;option.textContent=`${item.execution_kind==='native_vla'?'[纯 VLA] ':''}${item.metric_profile==='standard42'?'[标准42] ':item.metric_profile==='devset10'?'[Devset10] ':''}${item.title||item.panel_id}`;option.selected=item.panel_id===panelId;select.append(option);}
      select.addEventListener('change',()=>{location.href=`publications.html?panel=${encodeURIComponent(select.value)}`;});label.append(select);$('.pub-hero').before(label);
    } catch { /* A standalone pilot remains usable without a catalog. */ }
  }
  $('#case-filters').addEventListener('submit',event=>event.preventDefault());
  $('#case-filters').addEventListener('input',renderRows);
  $('#case-filters').addEventListener('reset',()=>setTimeout(renderRows,0));
  $('#case-rows').addEventListener('click',event=>{const button=event.target.closest('[data-run]');if(button){const run=panel.runs.find(r=>r.run_id===button.dataset.run);if(run)openDetail(run);}});
  $('#case-detail').addEventListener('click',event=>{const button=event.target.closest('[data-pane]');if(button)selectPane(button.dataset.pane);});
  $('#case-detail').addEventListener('keydown',event=>{if(!event.target.matches('[data-pane]')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const names=['videos','timeline','files'];const index=names.indexOf(event.target.dataset.pane);selectPane(names[event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3],true);});
  $('#close-case').addEventListener('click',()=>$('#case-dialog').close());
  $('#case-dialog').addEventListener('close',()=>{dialogVersion++;$('#case-detail').querySelectorAll('video').forEach(video=>video.pause());activeRun=null;});
  $('#case-dialog').addEventListener('click',event=>{if(event.target===$('#case-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
  getJSON(indexURL).then(data=>{panel=data;renderPanel();}).catch(error=>{$('#load-status').classList.add('error');$('#load-status').textContent=`公开结果索引暂不可用（${error.message}）。请稍后重试；没有把未加载的结果计为零。`;$('#case-rows').innerHTML='<tr><td colspan="7" class="empty-state">等待公开索引加载。</td></tr>';});
  loadCatalog();
})();
