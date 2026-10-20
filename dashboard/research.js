/* 五个方向的成果目录；推荐结果直接使用 ZZY 原服务的排名与解释。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = escapeHtml;
  const fields = {tags: '玩家标签', genres: '游戏类型', developers: '开发商', publishers: '发行商'};
  const topics = [
    {id: 'trends', tab: '类型潮流', title: '发售年份与潮流类型演变', kind: '主线', owner: '杨金辉', scope: '按发售年份比较游戏类型、题材和玩家模式的构成变化。', outputs: ['类型占比趋势', '官方分类对照', '题材与玩家模式']},
    {id: 'clusters', tab: '画像聚类', title: '游戏画像聚类', kind: '扩展', owner: '耶美田', scope: '把成就解锁情况相近的游戏分成五类，看看各类的分布、常见标签和热门作品。', outputs: ['五类成就分布', '类型关联', '热门作品']},
    {id: 'recommendation', tab: '可解释推荐', title: '可解释推荐', kind: '主线', owner: '朱政宇', scope: '选几款你喜欢的游戏，从共同的标签、类型与创作者关系中，发现下一款。', outputs: ['相似游戏', '推荐理由']},
    {id: 'retention', tab: '实际完成曲线', title: '实际完成曲线与游戏用户粘性分析', kind: '主线', owner: '王文海、刘宇翔', scope: '直接嵌入刘宇翔的原始交互简报：六项分析串成一页，可自选 1–5 款游戏联动查看阶段推进、时长投入、口碑与同类参照。', outputs: ['主线指标', '玩法比较', '完整过程', '游玩投入', '口碑关联', '同类参照']},
    {id: 'reputation', tab: '口碑预测', title: '游戏口碑预测与关联因素', kind: '扩展', owner: '王文海', scope: '以简单基线为对照，评估游戏口碑预测效果，分析与口碑相关的游戏特征。', outputs: ['预测评估', '相关因素']},
  ];
  const BADGES = {
    recommendation: '交互成果',
    clusters: '图解报告 · 2026-10-17',
    trends: '图解报告 · 2026-10-16',
    retention: '原始交付页 · 2026-10-20',
  };
  let active = '', selected = [], meta = null, metaPromise = null;
  let searchData = null, searchTerm = '', searchOffset = 0;
  let searchToken = 0, recommendToken = 0, searchAbort = null, recommendAbort = null;
  const title = (game, names = {}) => names[String(game.appid)]?.display_name || game.display_name || game.name_zh || game.name || game.name_en || `游戏 ${game.appid}`;
  const score = n => typeof n === 'number' && Number.isFinite(n) ? n.toFixed(6) : '—';
  const number = n => Number(n || 0).toLocaleString('zh-CN');

  /** 封面沿用 ZZY 的 Steam 图片来源，加载失败时保留游戏名占位。 */
  function cover(game, names = {}, compact = false) {
    const id = Number(game.appid);
    if (!Number.isSafeInteger(id) || id <= 0) return '';
    const name = esc(title(game, names));
    return `<a class="rec-cover${compact ? ' rec-cover-compact' : ''}" href="#explore/game/${id}" aria-label="查看《${name}》游戏数据"><span aria-hidden="true">${name}</span><img src="https://cdn.akamai.steamstatic.com/steam/apps/${id}/header.jpg" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" width="460" height="215"></a>`;
  }

  /** 原交付图示与实时推荐分开标注，避免把历史辅助评价当作当前效果。 */
  function figures() {
    const images = [
      ['current-knowledge-graph.png', '一份推荐，经过哪些关系', '以艾尔登法环与 DARK SOULS II: Scholar of the First Sin 为例，展示开发商、类型和标签路径及其贡献。'],
      ['current-path-explanation.png', '从路径回查原始事实', '展开同开发商路径，查看贡献计算及双端来源；这是一张历史解释界面的截图。'],
      ['ai-method-comparison.png', '标签基线与图谱方法对照', '14 个共同完整查询，Top-5 的 AI 辅助相关性评价；不是独立真人评价或总体准确率。'],
      ['ai-unknown-bounds.png', '资料不足时，结果有多不确定', '全部 24 个查询的 unknown 上下界；图中区间不是置信区间。'],
    ];
    return `<section id="recFigures" class="rec-figures"><div class="rec-result-heading"><h3>成果图示</h3><span>朱政宇 · 原交付图</span></div><p class="research-note">以下为 2026-10-14 冻结成果的图示，不随当前推荐条件更新。点击图片可在新标签页查看原图。</p><div class="rec-figure-grid">${images.map(([file, heading, caption]) => `<figure class="rec-figure"><a href="/assets/research/zzy/${file}" target="_blank" rel="noopener noreferrer" aria-label="查看原图：${heading}"><img src="/assets/research/zzy/${file}" alt="${heading}" loading="lazy" decoding="async"></a><figcaption><strong>${heading} ↗</strong><p>${caption}</p></figcaption></figure>`).join('')}</div><p class="research-note">评价标签由外部 AI 生成，来源未逐条独立核实。方法间差异不足以证明稳定提升，不能解释为玩家满意度或真实游玩效果。</p></section>`;
  }

  async function request(endpoint, params = {}, signal) {
    const query = new URLSearchParams(params).toString();
    const response = await fetch('/api/research/recommendation/' + endpoint + (query ? '?' + query : ''), {signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '暂时无法读取推荐成果，请重试。');
    return data;
  }

  function open() {
    const id = location.hash.split('/')[1];
    const topic = topics.find(t => t.id === id);
    if (!topic) { location.hash = '#research/recommendation'; return; }
    if (active === topic.id) return;
    active = topic.id;
    ++searchToken; ++recommendToken;
    searchAbort?.abort(); recommendAbort?.abort();
    // 顶部标签条：只放序号与短名，全名和负责人在 title 与正文标题里
    $('researchNav').innerHTML = topics.map((t, i) => `<a href="#research/${t.id}" title="${esc(t.title)} · ${esc(t.owner)}" ${t.id === active ? 'aria-current="page"' : ''}><span>0${i+1}</span><strong>${esc(t.tab)}</strong></a>`).join('');
    $('researchContent').innerHTML = `<header class="research-intro"><span class="research-kicker">RESEARCH / 0${topics.indexOf(topic)+1}</span><h2>${topic.title}</h2><p>${topic.scope}</p><div class="research-byline"><span>研究者 · ${topic.owner}</span><span class="research-badge">${topic.kind}</span><span class="research-badge">${BADGES[active] || '待接入'}</span></div></header>`;
    if (active === 'recommendation') {
      mountRecommendation();
    } else if (active === 'clusters') {
      window.ClusterResearch.mount($('researchContent'));
    } else if (active === 'trends') {
      window.TrendResearch.mount($('researchContent'));
    } else if (active === 'retention') {
      window.RetentionResearch.mount($('researchContent'));
    } else {
      $('researchContent').insertAdjacentHTML('beforeend', `<section class="card research-empty"><div class="research-empty-mark">0${topics.indexOf(topic)+1} /</div><h3>这个方向的成果，正在汇集。</h3><p class="research-note">这里将展示${topic.owner}的研究结果。当前尚未接入展示内容。</p><div class="research-deliverables">${topic.outputs.map(s => `<span>${s}</span>`).join('')}</div></section>`);
    }
  }

  function mountRecommendation() {
    $('researchContent').insertAdjacentHTML('beforeend', `<div id="recService" class="rec-service" role="status">正在连接推荐成果…</div>
      <section class="card"><h3><span class="rec-step">01 /</span>从你喜欢的游戏开始</h3><p class="research-note">选择 1–3 款游戏，组合你的偏好。支持中文名、英文名、常见别名和 AppID。</p>
      <form id="recSearch" class="rec-search"><label class="sr-only" for="recInput">搜索喜欢的游戏</label><input id="recInput" placeholder="例如：空洞骑士 / Elden Ring" maxlength="200" autocomplete="off" required><button type="submit">搜索 ↗</button></form>
      <div class="rec-examples"><span>试着搜索</span><button class="ghost" data-example="空洞骑士">空洞骑士</button><button class="ghost" data-example="艾尔登法环">艾尔登法环</button><button class="ghost" data-example="星露谷物语">星露谷物语</button></div>
      <div id="recSearchResults" aria-live="polite"></div><div id="recSelected" class="rec-selected" aria-label="已选游戏"></div>
      <form id="recForm"><h3><span class="rec-step">02 /</span>找哪一年的新选择？</h3><p class="research-note">年份筛选推荐对象；留空表示不限。已选游戏不会出现在推荐结果中。</p>
      <div class="rec-filters"><label>起始年份<input id="recYearMin" type="number" min="1" max="9999" placeholder="不限"></label><label>结束年份<input id="recYearMax" type="number" min="1" max="9999" placeholder="不限"></label><label>推荐数量<select id="recCount"><option>3</option><option selected>5</option><option>1</option></select></label><button id="recSubmit" type="submit" disabled>发现相似游戏 ↗</button></div></form>
      <p id="recMessage" class="rec-message" role="status"></p></section>
      <section id="recResults" aria-live="polite"></section>
      ${figures()}
      <details class="card rec-method"><summary>这些推荐是怎么来的？</summary><p class="research-note">朱政宇的知识图谱连接游戏与玩家标签、官方类型、开发商和发行商。推荐沿用原服务的权重与相似度评分，多款游戏按原算法合并贡献，年份先筛选再排名；展开每款结果可回查关系贡献及双端事实编号。</p><p class="research-note">简单对照组为标签相似度基线，本页展示知识图谱推荐。关系相似度不是喜欢概率，当前权重未经独立人工效果验证。共同开发商或发行商也不直接证明玩法相似。</p><p class="research-note">只搜索本次加载的数据快照；可搜索到不代表符合推荐资格。缺少标签、成就摘要或映射未解决的游戏会说明原因。没有符合条件的候选时保留空结果。</p></details>`);
    $('recSearch').addEventListener('submit', event => { event.preventDefault(); search($('recInput').value.trim(), 0); });
    $('recForm').addEventListener('submit', recommend);
    for (const id of ['recYearMin', 'recYearMax', 'recCount']) $(id).addEventListener('input', invalidateResults);
    renderSelected();
    loadMeta();
  }

  async function loadMeta() {
    if (active !== 'recommendation') return;
    $('recService').textContent = '正在连接推荐成果…';
    try {
      if (!metaPromise) metaPromise = request('meta').finally(() => { metaPromise = null; });
      meta = await metaPromise;
      if (active !== 'recommendation') return;
      const loading = meta.data_loading || {};
      const version = loading.snapshot_version || meta.view_binding?.query_binding?.snapshot_version || '见算法版本';
      const dataSource = loading.source === 'persistent_cache' ? '来自服务端持久化快照，重启复用；数据通过显式刷新更新。' : loading.source === 'group_database' ? '来自共享数据库的只读提取，快照与图谱已保存到持久化缓存。' : '使用推荐服务提供的固定快照。';
      $('recService').innerHTML = `已连接 · 可搜索 ${number(meta.snapshot_games)} 款 · 推荐候选 ${number(meta.candidate_games)} 款 <button type="button" class="ghost" data-retry-meta>重新连接</button><details><summary>数据版本与范围</summary><p>${dataSource}${loading.finished_at ? ' 原数据加载完成：' + esc(loading.finished_at) : ''}</p><code>快照：${esc(version)}</code><code>算法：${esc(meta.algorithm_version || '未提供')}</code><p>${esc(meta.limits || '')}</p></details>`;
    } catch (error) {
      if (active === 'recommendation') $('recService').innerHTML = `${esc(error.message)} <button type="button" class="ghost" data-retry-meta>重新连接</button>`;
    }
  }

  function invalidateResults() {
    ++recommendToken; recommendAbort?.abort();
    $('recResults').replaceChildren();
    $('recMessage').textContent = '';
    $('recSubmit').disabled = selected.length === 0;
    $('recSubmit').textContent = '发现相似游戏 ↗';
  }

  function renderSelected() {
    $('recSelected').innerHTML = selected.map(g => `<button type="button" data-remove="${g.appid}" aria-label="移除 ${esc(title(g))}">${esc(title(g))}<span aria-hidden="true">×</span></button>`).join('');
    $('recSubmit').disabled = selected.length === 0;
    if (searchData) renderSearch();
  }

  function renderSearch() {
    const data = searchData;
    const total = data.total_matches;
    $('recSearchResults').innerHTML = `<p class="research-note">${total ? `找到 ${number(total)} 款，显示 ${searchOffset+1}–${searchOffset+data.results.length}` : '没有找到匹配的游戏，试试其他名称或 AppID。'}</p>` + data.results.map(g => {
      const exists = selected.some(s => s.appid === g.appid);
      const disabled = exists || selected.length >= 3 || !g.recommendation_eligible;
      return `<div class="rec-search-result">${cover(g, {}, true)}<div class="rec-search-info"><strong>${esc(title(g))}</strong><p>${esc(g.display_name_en || g.name_en || '')} · ${g.release_year || '年份未知'} · ${Number(g.appid)}</p>${!g.recommendation_eligible ? `<p>${(g.ineligible_reasons || []).map(r => esc(r.message)).join(' ')}</p>` : ''}</div><button type="button" class="ghost" data-add="${g.appid}" ${disabled ? 'disabled' : ''}>${exists ? '已选择' : !g.recommendation_eligible ? '暂不可选' : selected.length >= 3 ? '已选满' : '加入 +'}</button></div>`;
    }).join('') + (total > 10 ? `<div class="rec-search-pages"><button type="button" class="ghost" data-search-page="${searchOffset-10}" ${searchOffset === 0 ? 'disabled' : ''}>上一页</button><span>${Math.floor(searchOffset/10)+1} / ${Math.ceil(total/10)}</span><button type="button" class="ghost" data-search-page="${searchOffset+10}" ${searchOffset+10 >= total ? 'disabled' : ''}>下一页</button></div>` : '');
  }

  async function search(term, offset) {
    if (!term) { $('recSearchResults').textContent = '请输入游戏名称或 AppID。'; return; }
    searchAbort?.abort(); searchAbort = new AbortController();
    const token = ++searchToken;
    searchTerm = term; searchOffset = offset;
    searchData = null;
    $('recSearchResults').innerHTML = '<p class="research-note">正在搜索…</p>';
    try {
      const data = await request('search', {q: term, limit: 10, offset}, searchAbort.signal);
      if (token !== searchToken) return;
      searchData = data; renderSearch();
    } catch (error) {
      if (token === searchToken && error.name !== 'AbortError') $('recSearchResults').innerHTML = `<p class="rec-message">${esc(error.message)} <button class="ghost" type="button" data-retry-search>重试搜索</button></p>`;
    }
  }

  async function recommend(event) {
    event.preventDefault();
    if (!selected.length) return;
    invalidateResults();
    const min = $('recYearMin').value, max = $('recYearMax').value;
    if (min && max && Number(min) > Number(max)) { $('recMessage').textContent = '起始年份不能晚于结束年份。'; return; }
    const token = ++recommendToken;
    recommendAbort = new AbortController();
    const params = {appids: selected.map(g => g.appid).join(','), top_k: $('recCount').value, path_limit: '8'};
    if (min) params.year_min = min;
    if (max) params.year_max = max;
    $('recSubmit').disabled = true; $('recSubmit').textContent = '正在寻找…';
    $('recMessage').textContent = '正在计算相似关系与推荐依据…';
    try {
      const data = await request('recommend', params, recommendAbort.signal);
      if (token !== recommendToken) return;
      renderRecommendations(data);
      $('recMessage').textContent = '';
    } catch (error) {
      if (token === recommendToken && error.name !== 'AbortError') $('recMessage').textContent = error.message + ' 可再次点击「发现相似游戏」重试。';
    } finally {
      if (token === recommendToken) { $('recSubmit').disabled = false; $('recSubmit').textContent = '发现相似游戏 ↗'; }
    }
  }

  function renderRecommendations(data) {
    const ranking = data.ranking, names = data.display_names || {};
    const seedName = id => title((data.query_games || []).find(g => g.appid === id) || {appid: id}, names);
    const results = ranking.results || [];
    $('recResults').innerHTML = `<div class="rec-result-heading"><h3>你的下一款游戏</h3><span>${results.length} 个推荐</span></div><p class="research-note">根据${(data.query_games || []).map(g => '《' + esc(title(g, names)) + '》').join('、')} · 年份 ${ranking.filters?.year_min ?? '不限'}–${ranking.filters?.year_max ?? '不限'} · 筛后候选 ${number(ranking.filtered_candidate_games)} 款</p>`;
    if (!results.length) { $('recResults').insertAdjacentHTML('beforeend', '<section class="card"><h3>这个范围内，暂时没有合适的推荐。</h3><p class="research-note">试着放宽年份范围，或换几款喜欢的游戏。</p></section>'); return; }
    $('recResults').insertAdjacentHTML('beforeend', results.map((g, index) => {
      const explanation = (data.explanations || []).find(e => e.appid === g.appid);
      const paths = explanation?.path_catalog || [];
      const positive = paths.filter(p => p.contribution > 0);
      const tags = [...new Set(positive.map(p => `${fields[p.field] || p.field} · ${p.name}`))].slice(0, 4);
      const maxScore = Math.max(...results.map(r => r.score), 0.000001);
      const contributions = g.seed_contributions || [];
      const pathHTML = p => `<div class="rec-evidence"><p>《${esc(seedName(p.seed_appid))}》 → ${esc(fields[p.field] || p.field)}「${esc(p.name)}」 ← 《${esc(title(g, names))}》</p><small>贡献 ${score(p.contribution)}${p.contribution === 0 ? ' · 共同事实，未计分' : ''}</small><details class="rec-source"><summary>核查事实来源</summary><small>已选游戏：${esc(p.left_fact_id)}<br>推荐游戏：${esc(p.right_fact_id)}</small></details></div>`;
      return `<article class="rec-candidate" data-recommendation="${g.appid}"><div class="rec-candidate-overview">${cover(g, names)}<div class="rec-candidate-head"><span class="rec-rank">${String(index+1).padStart(2, '0')}</span><div><h4>${esc(title(g, names))}</h4><p>${esc(names[String(g.appid)]?.display_name_en || g.name_en || g.name || '')} · ${g.release_year || '发售年份未知'}</p></div><div class="rec-score"><strong>${score(g.score)}</strong><small>关系相似度</small><div class="rec-score-bar"><i style="width:${Math.max(0, Math.min(100, g.score/maxScore*100))}%"></i></div></div></div></div>
      <div class="rec-reasons">${tags.map(t => `<span>${esc(t)}</span>`).join('') || '<p class="research-note">暂无正向共同关系，查看依据了解数据情况。</p>'}</div>
      <p class="research-note">${positive.length ? positive.slice(0, 2).map(p => `与《${esc(seedName(p.seed_appid))}》共享${fields[p.field] || '关系'}「${esc(p.name)}」`).join('；') + '。' : '当前关系没有正向计分依据。'}</p>
      <div class="rec-game-links"><a href="#explore/game/${Number(g.appid)}">查看成就与口碑 ↗</a><a href="https://store.steampowered.com/app/${Number(g.appid)}/" target="_blank" rel="noopener noreferrer">Steam 商店 ↗</a></div>
      <details><summary>为什么推荐 · 查看贡献与来源</summary>
      <p class="research-note">${esc(g.evidence_note || '')}</p>
      ${contributions.map(s => `<p class="research-note">《${esc(seedName(s.appid))}》：相似度 ${score(s.score)} × 权重 ${s.weight} = 贡献 ${score(s.contribution)}</p>`).join('')}
      <div class="rec-table-wrap"><table class="rec-table"><thead><tr><th>已选游戏 / 关系</th><th>联合贡献</th><th>证据情况</th></tr></thead><tbody>${(explanation?.relations || []).map(r => `<tr><td>${esc(seedName(r.seed_appid))}<br>${esc(fields[r.field] || r.label)}</td><td>${score(r.score)}</td><td>${esc(r.status_note)}</td></tr>`).join('')}</tbody></table></div>
      <p class="research-note">共同关系路径 · ${number(paths.length)} 条；正向贡献 ${number(positive.length)} 条。事实编号对应推荐服务的固定图谱。</p>
      ${paths.slice(0, 8).map(pathHTML).join('')}
      ${paths.length > 8 ? `<details><summary>展开其余 ${paths.length-8} 条路径</summary>${paths.slice(8).map(pathHTML).join('')}</details>` : ''}
      </details></article>`;
    }).join(''));
    $('recResults').insertAdjacentHTML('beforeend', '<p class="research-note">条长相对于本次最高分；分数不是喜欢概率。结果保持原推荐顺序。</p>');
  }

  $('researchContent').addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.hasAttribute('data-retry-meta')) loadMeta();
    if (button.hasAttribute('data-retry-search')) search(searchTerm, searchOffset);
    if (button.dataset.example) { $('recInput').value = button.dataset.example; search(button.dataset.example, 0); }
    if (button.hasAttribute('data-search-page')) search(searchTerm, Number(button.dataset.searchPage));
    if (button.dataset.add) {
      const game = searchData?.results.find(g => g.appid === Number(button.dataset.add));
      if (game?.recommendation_eligible && selected.length < 3 && !selected.some(g => g.appid === game.appid)) { selected.push(game); invalidateResults(); renderSelected(); }
    }
    if (button.dataset.remove) { selected = selected.filter(g => g.appid !== Number(button.dataset.remove)); invalidateResults(); renderSelected(); }
  });
  $('researchContent').addEventListener('error', event => {
    const img = event.target;
    if (img.tagName !== 'IMG' || !img.closest('.rec-cover')) return;
    img.hidden = true;
    img.closest('.rec-cover').classList.add('cover-missing');
  }, true);
  window.Research = {open};
})();
