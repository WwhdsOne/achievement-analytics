/* 一个入口串起发现、搜索、详情与对比；不依赖分析报告。 */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const esc = escapeHtml;
  const valid = value => typeof value === 'number' && Number.isFinite(value);
  const num = value => valid(value) ? value.toLocaleString('zh-CN') : '—';
  const pct = value => valid(value) ? value.toFixed(1) + '%' : '—';
  // HowLongToBeat 时长（小时）。名称匹配导入、覆盖不全，缺数据显示「无」。
  const hours = value => valid(value) && value >= 0 ? value.toFixed(1) + '<em>小时</em>' : '无';
  const title = game => game.name_zh || game.name || '未命名游戏';
  // 旧价格字段未保存货币，现有数据混有不同地区金额；不据此标美元价。
  const payment = game => game.is_free === true ? '免费' : game.is_free === false ? '付费' : '—';
  const cache = new Map();
  let started = false, discoveryToken = 0, searchToken = 0, gameToken = 0, lastGame = null;
  let discovered = [], mode = 'popular', metric = 'reviews';

  async function json(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(res.status === 404 ? '这款游戏尚未收录，试试其他名称或 AppID。' : res.status === 429 ? '查询有点频繁，请稍后再试。' : '暂时无法读取数据，请稍后重试。');
    return data;
  }

  function message(text) { el('exploreMessage').textContent = text; }

  // 搜索与发现分成两个标签页；提示区在两页共用（见 index.html）。
  function switchExploreTab(name) {
    document.querySelectorAll('[data-explore-tab]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.exploreTab === name)));
    el('exploreTabSearch').classList.toggle('hidden', name !== 'search');
    el('exploreTabDiscover').classList.toggle('hidden', name !== 'discover');
  }

  function gameButton(game) { return `<button type="button" class="text-button" data-game="${Number(game.appid)}">${esc(title(game))}</button>`; }

  /** 与 ZZY 推荐页使用同一 Steam 封面地址；列表进入详情，详情封面进入商店。 */
  function cover(game, detail = false) {
    const id = Number(game.appid);
    if (!Number.isSafeInteger(id) || id <= 0) return '';
    const name = esc(title(game));
    const content = `<span aria-hidden="true">${name}</span><img src="https://cdn.akamai.steamstatic.com/steam/apps/${id}/header.jpg" alt="" width="460" height="215" loading="${detail ? 'eager' : 'lazy'}" decoding="async" referrerpolicy="no-referrer">`;
    return detail ? `<a class="game-cover game-story-cover" href="https://store.steampowered.com/app/${id}/" target="_blank" rel="noopener noreferrer" aria-label="在 Steam 查看《${name}》">${content}</a>` : `<button type="button" class="game-cover game-card-cover" data-game="${id}" aria-label="查看《${name}》的游戏数据">${content}</button>`;
  }

  function cards(games) {
    return games.map(game => `<article class="explore-game">
      ${cover(game)}
      <div class="game-card-top"><span>${esc(game.release_date?.slice(0,4) || '发售日未知')} · ${game.is_free === true ? '免费游戏' : 'Steam'}</span></div>
      <h3>${gameButton(game)}</h3><div class="game-card-numbers">
        <div><strong>${num(game.reviews)}</strong><span>条评价</span></div>
        <div><strong>${pct(game.approval)}</strong><span>好评率</span></div>
        <div><strong>${num(game.ach_count)}</strong><span>个成就</span></div>
      </div></article>`).join('');
  }

  function renderDiscovery() {
    const sorted = [...discovered].sort((a,b) => (valid(b[metric]) ? b[metric] : -1) - (valid(a[metric]) ? a[metric] : -1) || a.appid-b.appid);
    el('discoveryGames').innerHTML = sorted.length ? cards(sorted) : '<p class="explore-note">暂时没有符合条件的游戏。</p>';
  }

  async function discover(next) {
    mode = next;
    const token = ++discoveryToken;
    document.querySelectorAll('[data-discovery]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.discovery === mode)));
    el('discoveryGames').innerHTML = '<p class="explore-note">正在寻找游戏…</p>';
    try {
      const data = await json('/api/explore?mode=' + mode);
      if (token !== discoveryToken) return;
      discovered = data.games;
      metric = mode === 'achievements' ? 'ach_count' : 'reviews';
      el('discoveryMetric').value = metric;
      renderDiscovery();
    } catch (error) {
      if (token === discoveryToken) el('discoveryGames').innerHTML = `<p>${esc(error.message)} <button class="text-button" data-retry="discovery">重试</button></p>`;
    }
  }

  // AppID/商店链接只解析身份；名称搜索不请求 Steam 外部页面。
  function parseAppID(value) {
    if (/^[1-9]\d{0,9}$/.test(value) && Number(value) <= 2147483647) return Number(value);
    try {
      const url = new URL(value);
      if (url.hostname !== 'store.steampowered.com' || !['http:', 'https:'].includes(url.protocol)) return null;
      const match = url.pathname.match(/^\/app\/([1-9]\d*)(?:\/|$)/);
      return match && Number(match[1]) <= 2147483647 ? Number(match[1]) : null;
    } catch { return null; }
  }

  async function search(event) {
    event?.preventDefault();
    const value = el('exploreInput').value.trim();
    const token = ++searchToken;
    if (!value) { message('输入游戏名称、AppID 或 Steam 商店链接。'); return; }
    const id = parseAppID(value);
    if (id) {
      el('searchResults').classList.add('hidden');
      message('');
      navigate(id);
      return;
    }
    if (/^https?:\/\//i.test(value) || /^\d+$/.test(value) || [...value].length > 100) {
      message('请输入有效的 AppID、Steam 商店链接，或 100 字以内的游戏名称。'); return;
    }
    el('searchResults').classList.remove('hidden');
    el('searchResults').innerHTML = '<p class="explore-note">正在搜索…</p>';
    message('');
    try {
      const data = await json('/api/explore?mode=search&q=' + encodeURIComponent(value));
      if (token !== searchToken) return;
      el('searchResults').innerHTML = `<div class="section-heading"><h2>“${esc(value)}”的搜索结果</h2><span>${data.games.length ? '最多显示 20 款' : '没有找到匹配的游戏'}</span></div><div class="game-grid">${cards(data.games)}</div>`;
    } catch (error) {
      if (token === searchToken) el('searchResults').innerHTML = `<p>${esc(error.message)} <button class="text-button" data-retry="search">重试</button></p>`;
    }
  }

  async function random() {
    el('randomGame').disabled = true;
    const token = ++searchToken;
    message('给你找一款游戏…');
    try {
      const data = await json('/api/explore?mode=random');
      if (token !== searchToken) return;
      if (!data.games.length) { message('暂时没有可查看的游戏。'); return; }
      el('searchResults').classList.add('hidden');
      el('exploreInput').value = title(data.games[0]);
      message('');
      navigate(data.games[0].appid);
    } catch (error) { if (token === searchToken) message(error.message); }
    finally { el('randomGame').disabled = false; }
  }

  async function bundle(id) {
    if (cache.has(id)) return cache.get(id);
    const pending = (async () => {
      const [base, extra] = await Promise.allSettled([json('/api/game?appid=' + id), json('/api/explore?appid=' + id)]);
      if (base.status === 'rejected') throw base.reason;
      const d = base.value;
      const x = extra.status === 'fulfilled' ? extra.value : null;
      // 附加查询失败时无法核实映射台账，具名故事暂不展示。
      if (!x || x.mapping_unresolved) d.achievements_list = (d.achievements_list || []).map(ach => ({...ach, display_name: ''}));
      const s = d.steamspy;
      const reviews = valid(s?.positive) && valid(s?.negative) ? s.positive+s.negative : null;
      const g = x?.games[0] || {appid: id, name:d.name, name_zh:d.name_zh, ...d.appdetails, ach_count:d.counts.achievements,
        reviews, approval:reviews > 0 ? s.positive/reviews*100 : null};
      return {d, x, g};
    })();
    cache.set(id, pending);
    try {
      const result = await pending;
      if (!result.x) cache.delete(id);
      if (cache.size > 30) cache.delete(cache.keys().next().value);
      return result;
    } catch (error) { cache.delete(id); throw error; }
  }

  function stat(label, value, note = '') { return `<div class="game-stat"><span>${esc(label)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`; }
  function storySection(heading, body, note = '') { return `<section class="game-story-section"><h3>${esc(heading)}</h3>${body}${note ? `<p class="explore-note">${esc(note)}</p>` : ''}</section>`; }
  function achievementTile(ach, label) {
    return `<div class="achievement-tile"><span>${esc(label)}</span><strong>${esc(ach.display_name)}</strong><b>${pct(ach.percent)}</b><small>Steam 全局解锁率</small></div>`;
  }

  function renderStory({d,x,g}) {
    const achievements = (d.achievements_list || []).filter(ach => ach.display_name && valid(ach.percent)).sort((a,b) => b.percent-a.percent || a.position-b.position);
    const rare = (d.achievements_list || []).filter(ach => valid(ach.percent) && ach.percent < 1).length;
    const rawg = d.rawg;
    const tags = x?.tags || [];
    const maxVotes = Math.max(1, ...tags.map(tag => tag.votes || 0));
    const meta = [g.release_date || '发售日暂无', ...(g.developers || [])].map(esc).join(' · ');
    let html = `<article class="game-story"><header class="game-story-header"><div class="game-story-identity">${cover(g, true)}<div class="game-story-heading"><span class="explore-eyebrow">GAME / ${Number(g.appid)}</span>
      <h2>${esc(title(g))}</h2>${g.name_zh && g.name_zh !== g.name ? `<p class="game-english">${esc(g.name)}</p>` : ''}<p class="explore-note">${meta}</p></div></div>
      <div class="game-actions"><a href="https://store.steampowered.com/app/${Number(g.appid)}/" target="_blank" rel="noopener noreferrer">去 Steam ↗</a><a href="#explore">换款游戏 ↑</a></div></header>
      <div class="game-stat-grid">${stat('成就清单',num(g.ach_count),'个成就')}${stat('Steam 好评率',pct(g.approval),`${num(g.reviews)} 条评价`)}${stat('付费方式',payment(g),'当前售价请查看 Steam 商店')}${stat('采集时在线',num(d.steamspy?.ccu),'人 · 非实时在线')}${stat('主线时长',hours(g.hltb_main),'HowLongToBeat 玩家提交')}${stat('主线+支线',hours(g.hltb_extra),'HowLongToBeat 玩家提交')}${stat('完美通关',hours(g.hltb_completionist),'HowLongToBeat 玩家提交')}</div>`;
    html += storySection('成就里藏着的小数字', achievements.length ?
      `<div class="achievement-pair">${achievementTile(achievements[0],'最常见的具名成就')}${achievementTile(achievements[achievements.length-1],'最稀有的具名成就')}</div>
      <p class="story-sentence">这款游戏有 <b>${num(rare)}</b> 个成就的全局解锁率低于 1%。</p>` :
      `<p class="explore-note">${x?.mapping_unresolved ? '成就名称映射待核对，暂不展示具名成就故事。' : !x ? '暂时无法核对成就名称，请重试读取游戏。' : '暂无可展示的具名成就。'}</p>`,
      '常见与稀有按具名成就的解锁率排序。稀有度不直接代表难度，也不能推出全成就玩家比例。');
    html += storySection('玩家与媒体，各打几分', `<div class="score-grid">
      ${stat('Steam 好评率',pct(g.approval),`${num(g.reviews)} 条评价`)}
      ${stat('Metacritic 媒体评分',valid(rawg?.metacritic) && rawg.metacritic > 0 ? num(rawg.metacritic) + '<em>/100</em>' : '—','来源：RAWG')}
      ${stat('RAWG 用户评分',valid(rawg?.rating) && rawg.rating > 0 ? rawg.rating.toFixed(2) + '<em>/5</em>' : '—',`${num(rawg?.ratings_count)} 条评分`)}</div>`,
      '各平台量纲、样本与采集时点不同，三个数字分别阅读。评价数较少时，好评率容易受少数评价影响。');
    html += storySection('玩家用哪些词形容它', tags.length ? `<div class="tag-votes">${tags.map(tag => `<div><span>${esc(tag.tag)}</span><b>${num(tag.votes)} 票</b><i style="width:${(tag.votes || 0)/maxVotes*100}%"></i></div>`).join('')}</div>` : '<p class="explore-note">暂无玩家标签票数。</p>', '来源：SteamSpy 玩家标签，按投票数排列；票数不是玩家人数。');
    html += storySection('这家工作室还做过什么', x?.related.length ? `<div class="game-grid">${cards(x.related)}</div>` : '<p class="explore-note">当前数据库中暂无同开发商的其他作品。</p>', '按商店记录中的相同开发商名称查找；展示与当前游戏至少共享一位开发商的作品。');
    if (x?.shared.length) {
      const first = achievements[0];
      html += storySection('名字一样，稀有度不同', `<p class="story-sentence">“${esc(first.display_name)}”也出现在这些游戏里：</p>
        <div class="shared-rows"><div><strong>${esc(title(g))}</strong><b>${pct(first.percent)}</b></div>
        ${x.shared.map(ach => `<div>${gameButton({appid:ach.appid,name:ach.game})}<b>${pct(ach.percent)}</b>${ach.description ? `<p>${esc(ach.description)}</p>` : ''}</div>`).join('')}</div>`,
        '仅比较相同的展示名。名称相同不代表任务相同，不用于判断哪款游戏更难。');
    }
    html += `<p class="explore-note">${!x ? '部分附加信息读取失败。' : ''}最近抓取：${d.last_fetched_at ? esc(new Date(d.last_fetched_at).toLocaleString('zh-CN')) : '暂无记录'} · <button class="text-button" data-retry="game">重新读取</button></p></article>`;
    el('gameStory').innerHTML = html;
  }

  async function selectGame(id) {
    lastGame = id;
    const token = ++gameToken;
    el('appidInput').value = id;
    el('gameStory').classList.remove('hidden');
    el('gameStory').innerHTML = '<p class="explore-note loading-story">正在读取游戏详情…</p>';
    for (const key of ['resultCard','infoCard','achCard']) el(key).classList.add('hidden');
    try {
      const data = await bundle(id);
      if (token !== gameToken) return;
      renderStory(data);
      await lookup(id, data.d);
    } catch (error) {
      if (token !== gameToken) return;
      el('gameStory').innerHTML = `<p class="explore-note">${esc(error.message)} <button class="text-button" data-retry="game">重试</button></p>`;
    }
    if (token === gameToken) el('gameStory').scrollIntoView({behavior:'smooth',block:'start'});
  }

  function navigate(id) {
    ++searchToken;
    const hash = '#explore/game/' + id;
    if (location.hash === hash) selectGame(id);
    else location.hash = hash;
  }

  function open() {
    if (!started) { started = true; discover('popular'); }
    if (!location.hash.startsWith('#explore')) location.hash = '#explore';
  }

  function route() {
    const hash = location.hash;
    if (/^#research(?:\/|$)/.test(hash)) { ++gameToken; switchView('research'); return; }
    if (hash === '#cloud') { location.hash = '#overview'; return; }
    if (hash === '#queue' || hash === '#overview') { ++gameToken; switchView(hash.slice(1)); return; }
    if (!/^#explore(?:\/game\/[1-9]\d*)?$/.test(hash)) { location.hash = '#explore'; return; }
    switchView('analysis');
    const match = hash.match(/^#explore\/game\/([1-9]\d*)$/);
    if (match) selectGame(Number(match[1]));
    else {
      ++gameToken; lastGame = null;
      el('gameStory').classList.add('hidden');
      for (const key of ['resultCard','infoCard','achCard']) el(key).classList.add('hidden');
      window.scrollTo({top:0, behavior:'smooth'});
    }
  }

  // 复用单款详情的三个折叠块，入口与路由只有一份。
  for (const key of ['achCard','infoCard','resultCard']) el('gameDetailMount').appendChild(el(key));
  const sort = document.createElement('label');
  sort.className = 'discovery-sort';
  sort.innerHTML = '换个数字，看看顺序怎么变 <select id="discoveryMetric"><option value="reviews">评价数量</option><option value="approval">好评率</option><option value="ach_count">成就数量</option></select><small>只调整当前展示游戏的顺序</small>';
  el('discoveryGames').before(sort);
  el('discoveryMetric').addEventListener('change', event => { metric = event.target.value; renderDiscovery(); });
  el('exploreSearch').addEventListener('submit', search);
  el('randomGame').addEventListener('click', random);
  el('viewAnalysis').addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.game) navigate(Number(button.dataset.game));
    if (button.dataset.exploreTab) switchExploreTab(button.dataset.exploreTab);
    if (button.dataset.discovery) discover(button.dataset.discovery);
    if (button.dataset.retry === 'discovery') discover(mode);
    if (button.dataset.retry === 'search') search();
    if (button.dataset.retry === 'game' && lastGame) { cache.delete(lastGame); selectGame(lastGame); }
  });
  el('viewAnalysis').addEventListener('error', event => {
    const img = event.target;
    if (img.tagName !== 'IMG' || !img.closest('.game-cover')) return;
    img.hidden = true;
    img.closest('.game-cover').classList.add('cover-missing');
  }, true);
  window.Explore = {open};
  window.addEventListener('hashchange', route);
  route();
})();
