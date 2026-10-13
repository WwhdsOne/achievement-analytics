/* 固定快照中的名作数据：原生图形、游戏切换与简单对比。 */
(() => {
  'use strict';
  const pages = {
    overview: ['成就清单有多长', '悟空、只狼、法环，放在一起看', '都是你熟悉的游戏，成就数量却很不一样。选两款比一比，再看看其他名作。'],
    reputation: ['这些名作，口碑如何', '好评比例和评价数量分别看', '喜欢的人占多少，讨论的人有多少？切换一个角度，榜单就可能变个样。'],
    states: ['喜欢，也可能放下', '换一款游戏，看看玩家的标记', '一边是 Steam 好评，一边是 RAWG 用户的通关与弃坑标记。高好评不意味着每个人都会玩到最后。'],
    beyond: ['热门之外的世界', '许多游戏，很少被评价', '你熟悉的名作之外，还有大量不常出现在视野里的游戏。']
  };
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => value == null ? '—' : Number(value).toLocaleString('en-US');
  const pct = value => value == null ? '—' : (value * 100).toFixed(1) + '%';
  const available = value => typeof value === 'number' && Number.isFinite(value);
  let report = null, request = null, renderToken = 0;

  function games() { return report.stories?.familiar_games || []; }
  function gameLink(game) {
    return `<button type="button" data-game="${Number(game.appid)}" title="查看游戏详情">${esc(game.name_zh || game.name_en)}</button>`;
  }
  function options(rows, selected) {
    return rows.map(row=>`<option value="${row.appid}" ${row.appid===selected?'selected':''}>${esc(row.name_zh)}</option>`).join('');
  }
  function section(title, body, note = '') {
    return `<section class="data-story"><h2>${esc(title)}</h2>${body}${note?`<p class="story-source">${esc(note)}</p>`:''}</section>`;
  }
  function empty(message) { return `<p class="story-empty">${esc(message)}</p>`; }
  function chart(rows, key, format, ceiling) {
    if (!rows.length) return empty('这些游戏暂时没有足够的有效数据。');
    const max = ceiling || Math.max(...rows.map(row=>row[key]), 1);
    return `<div class="game-bars">${rows.map(row=>
      `<div class="game-bar-row"><div class="game-bar-label">${gameLink(row)}<strong>${format(row[key])}</strong></div>
       <div class="story-track" aria-hidden="true"><span style="width:${Math.max(0,Math.min(100,row[key]/max*100))}%"></span></div></div>`).join('')}</div>`;
  }
  function comparison() {
    const rows = games().filter(game=>available(game.ach_count) && game.ach_count>0);
    if (!rows.length) return empty('这些游戏暂时没有有效的成就数量。');
    const first = rows.find(row=>row.appid===2358720) || rows[0];
    const second = rows.find(row=>row.appid===814380) || rows[1] || rows[0];
    return `<div class="compare-picks"><label>这款游戏<select id="compareFirst">${options(rows,first.appid)}</select></label>
      <span class="compare-vs" aria-hidden="true">与</span><label>那款游戏<select id="compareSecond">${options(rows,second.appid)}</select></label></div>
      <div id="comparisonResult" aria-live="polite"></div>`;
  }
  function updateComparison() {
    const first = games().find(row=>row.appid===Number($('compareFirst').value));
    const second = games().find(row=>row.appid===Number($('compareSecond').value));
    const ratio = first.ach_count / second.ach_count;
    $('comparisonResult').innerHTML = `<div class="story-split compare-numbers">
      <div><div class="story-number">${num(first.ach_count)}</div><p>${esc(first.name_zh)} · 个成就</p></div>
      <div><div class="story-number secondary">${num(second.ach_count)}</div><p>${esc(second.name_zh)} · 个成就</p></div></div>
      <p class="story-takeaway">《${esc(first.name_zh)}》的成就数量，约是《${esc(second.name_zh)}》的 <strong>${ratio.toFixed(1)} 倍</strong>。</p>`;
  }
  function overview() {
    const rows = games().filter(game=>available(game.ach_count)).sort((a,b)=>b.ach_count-a.ach_count || a.appid-b.appid);
    return section('换两款熟悉的游戏，比一比', comparison(), '来源：Steam 成就记录。比较的是成就数量，数量多不等于更难，也不等于内容更多。') +
      section('这些名作的成就清单', chart(rows,'ach_count',value=>num(value)+' 个'),
        `展示预先选取的 ${rows.length} 款游戏，按成就数量排列，不是全 Steam 排行榜。点击游戏名可查看详情。`);
  }
  function reputation() {
    return `<div class="story-controls"><label>看哪个数字<select id="reputationMetric"><option value="approval">好评比例</option><option value="reviews">评价数量</option></select></label></div>
      <div id="reputationResult" aria-live="polite"></div>`;
  }
  function updateReputation() {
    const key = $('reputationMetric').value;
    const rows = games().filter(row=>available(row[key])).sort((a,b)=>b[key]-a[key] || a.appid-b.appid);
    if (!rows.length) { $('reputationResult').innerHTML=empty('这些游戏暂时没有有效的评价数据。'); return; }
    const first=rows[0], approval=key==='approval';
    const format=value=>approval?pct(value):num(value)+' 条';
    $('reputationResult').innerHTML = `<section class="data-story"><div class="story-index">在这 ${rows.length} 款游戏中</div>
      <h2>${esc(first.name_zh)} · ${approval?'好评比例最高':'评价数量最多'}</h2>
      <div class="story-number">${approval?pct(first.approval):num(first.reviews)}</div>
      <p class="story-number-label">${approval?`好评比例 · 共 ${num(first.reviews)} 条评价`:'条 Steam 评价'}</p>
      <p class="story-takeaway">${approval?'比例看口碑，数量看讨论规模。两件事，值得分开看。':'很多人评价，不等于每个人都喜欢。换成好评比例，看看顺序有什么变化。'}</p></section>` +
      section(approval?'好评比例，从高到低':'评价数量，从多到少', chart(rows,key,format,approval?1:undefined),
        '来源：SteamSpy 收录的 Steam 好评与差评。好评比例仅展示至少100条评价的游戏；这里是选定名作之间的对比，不是全站排名。');
    bindGames();
  }
  function states() {
    const rows=games().filter(row=>available(row.state_total) && row.state_total>=20);
    if (!rows.length) return empty('这些游戏暂时没有足够的 RAWG 通关或弃坑标记。');
    const chosen=rows.find(row=>row.appid===413150) || rows[0];
    return `<div class="story-controls"><label>换一款游戏<select id="stateGame">${options(rows,chosen.appid)}</select></label></div>
      <div id="stateResult" aria-live="polite"></div>`;
  }
  function updateState() {
    const game=games().find(row=>row.appid===Number($('stateGame').value));
    $('stateResult').innerHTML = `<section class="data-story story-states"><h2>${gameLink(game)}</h2>
      <div class="story-split"><div><div class="story-number">${pct(game.approval)}</div>
      <p class="story-number-label">Steam 好评率 · ${num(game.reviews)} 条评价</p></div>
      <div><p>另一个平台 RAWG 上，用户这样标记：</p>
      ${[['通关',game.beaten,'beaten'],['弃坑',game.dropped,'dropped']].map(([label,count,kind])=>
        `<div class="story-state"><div><span>${label}</span><strong>${num(count)} 人</strong></div>
         <div class="story-track" aria-hidden="true"><span class="${kind}" style="width:${count/game.state_total*100}%"></span></div></div>`).join('')}
      </div></div><p class="story-takeaway">喜欢一款游戏，不一定要玩到最后。长篇剧情、反复挑战、自由经营，“玩完”的含义也不同。</p>
      <p class="story-caveat">两个平台不是同一批用户。右图只展示 RAWG 的通关或弃坑标记，不包含想玩、正在玩等状态；不能据此说全部 Steam 玩家中有多少人弃坑。</p>
      <p class="story-source">来源：SteamSpy / RAWG · 此游戏有 ${num(game.state_total)} 个通关或弃坑标记。未收录的标记不当作零。</p></section>`;
    bindGames();
  }
  function beyond() {
    const r=report.stories.reviews;
    if (!r?.sample_n || !available(r.under_100_ratio)) return empty('当前快照没有有效的评价计数。');
    const filled=Math.round(r.under_100_ratio*100);
    return `<section class="data-story story-reviews"><h2>很多游戏，连 100 条评价都没有</h2>
      <div class="story-split"><div><div class="story-number">${pct(r.under_100_ratio)}</div>
      <p class="story-number-label">的游戏，评价数不足 100 条</p><p>一半游戏的评价数不超过 <b>${num(r.median_count)}</b> 条。</p></div>
      <figure class="story-waffle-figure"><div class="story-waffle" role="img" aria-label="每格表示约百分之一的游戏，${filled}格表示评价不足100条">
      ${Array.from({length:100},(_,i)=>`<span class="waffle-cell${i<filled?' filled':''}" aria-hidden="true"></span>`).join('')}</div>
      <figcaption>每格 ≈ 1% 的游戏<br><i></i> 评价不足 100 条 · 约 ${filled} 格</figcaption></figure></div>
      <p class="story-takeaway">你熟悉的名作只是游戏世界的一角。评价少，不等于不好玩。</p>
      <p class="story-source">来源：SteamSpy · ${num(r.under_100)} / ${num(r.sample_n)} 款有效样本。缺失不当作零；方格按百分比四舍五入。</p></section>`;
  }
  function sources() {
    return `<details class="method-details"><summary>数据来源与范围</summary>
      <p>展示数字来自 ${esc(String(report.metadata.built_at || '').slice(0,10))} 的固定快照，覆盖 ${num(report.metadata.games)} 款2026年前发售、带Steam成就的游戏，排除了尚未解决的成就名称映射问题。</p>
      <p>名作名单由人工预先选取，未按结果挑选：${games().map(row=>esc(row.name_zh)).join('、') || '当前没有可用游戏'}。不同数字来自各自有效记录；好评率至少需要100条评价，状态对比至少需要20个通关或弃坑标记。</p>
      <p>成就数量不等于难度，好评数量不等于销量。Steam与RAWG的用户不同，这些数字不能代表每一位玩家。</p>
    </details>`;
  }
  function bindGames() {
    $('analysisPage').querySelectorAll('[data-game]').forEach(button=>button.onclick=async()=>{
      $('appidInput').value=Number(button.dataset.game);
      switchView('game');
      try { await doLookup(); } catch (_) { $('gmeta').textContent='游戏详情暂时无法读取，请稍后重试。'; }
    });
  }
  const builders={overview,reputation,states,beyond};
  async function render(page) {
    const token=++renderToken;
    if (!pages[page]) { page='overview'; history.replaceState(null,'','#analysis/overview'); }
    $('analysisNav').innerHTML='<div class="nav-label">游戏数据故事</div>'+Object.entries(pages).map(([key,info])=>
      `<a href="#analysis/${key}" ${key===page?'aria-current="page"':''}><strong>${esc(info[0])}</strong><span>${esc(info[1])}</span></a>`).join('');
    if (!report) {
      $('analysisPage').innerHTML='<div class="analysis-status">正在读取游戏数据…</div>';
      try {
        if (!request) request=fetch('/api/analysis').then(async res=>{
          const data=await res.json(); if (!res.ok) throw new Error(data.error || '读取失败'); return data;
        });
        report=await request;
      } catch(error) {
        request=null;
        if (token!==renderToken) return;
        $('analysisPage').innerHTML=`<div class="analysis-status">${esc(error.message)}<br><button id="retryAnalysis">重新读取数据</button></div>`;
        $('retryAnalysis').onclick=()=>render(page);
        return;
      }
    }
    if (token!==renderToken) return;
    const info=pages[page];
    const ready=Array.isArray(report.stories?.familiar_games);
    $('analysisPage').innerHTML=`<header class="analysis-heading"><div class="eyebrow">STEAM · 熟悉的游戏，意外的数字</div><h1>${esc(info[0])}</h1><p class="analysis-description">${esc(info[2])}</p></header>`+
      `<p class="story-dateline">${esc(String(report.metadata.built_at || '').slice(0,10))} 固定快照 · ${num(games().length)} 款精选名作 · 数字随抓取日期变化</p>`+
      (ready?builders[page]():section('请更新展示数据', '<p>当前文件尚未包含知名游戏对比，请按命令手册生成数据故事后刷新。</p>'))+
      sources()+`<footer class="analysis-footer">来源：Steam / SteamSpy / <a href="https://rawg.io/" target="_blank" rel="noopener">RAWG</a> · 非商业课程展示<br>固定版本 ${esc(report.metadata.version)} · <a href="/api/analysis" download="game-stories.json">下载展示数据</a></footer>`;
    if ($('compareFirst')) {
      $('compareFirst').onchange=updateComparison; $('compareSecond').onchange=updateComparison; updateComparison();
    }
    if ($('reputationMetric')) { $('reputationMetric').onchange=updateReputation; updateReputation(); }
    if ($('stateGame')) { $('stateGame').onchange=updateState; updateState(); }
    bindGames();
  }
  function route() {
    const route=location.hash.slice(1);
    if (['queue','game','cloud'].includes(route)) switchView(route);
    else {
      if (!route.startsWith('analysis/')) history.replaceState(null,'','#analysis/overview');
      switchView('analysis');
    }
  }
  window.Analysis={open() {
    if (!location.hash.startsWith('#analysis/')) { location.hash='analysis/overview'; return; }
    render(location.hash.split('/')[1] || 'overview');
  }};
  window.addEventListener('hashchange',route);
  route();
})();
