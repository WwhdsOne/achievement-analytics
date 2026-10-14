/* 当前库的描述性总览；数值来自只读API，所有比例标明自己的统计分母。 */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const esc = escapeHtml;
  const valid = n => typeof n === 'number' && Number.isFinite(n);
  const num = n => valid(n) ? n.toLocaleString('zh-CN', {maximumFractionDigits:1}) : '—';
  const percent = (part,total) => total > 0 ? part/total*100 : null;
  const pct = n => valid(n) ? n.toFixed(1)+'%' : '—';
  let request = null, loadedAt = 0;

  function stat(label,value,note) {
    return `<div class="overview-stat"><span>${esc(label)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`;
  }

  function bars(rows,total) {
    return `<div class="overview-bars">${rows.map(([label,n]) => `<div class="overview-bar-row">
      <div><span>${esc(label)}</span><b>${num(n)} 款 <small>· ${pct(percent(n,total))}</small></b></div>
      <div class="overview-track"><span style="width:${percent(n,total) || 0}%"></span></div></div>`).join('')}</div>`;
  }

  function render(data) {
    const c = data.counts, r = data.reviews, p = data.payments;
    const under100 = r.zero+r.one_to_99;
    const share = percent(r.top_reviews,r.total);
    const rare = percent(c.rare_achievements,c.achievements);
    const common = percent(c.common_achievements,c.achievements);
    const knownPayments = p.free+p.paid;
    const cells = Array.from({length:100},(_,i) => `<i class="${valid(share) && i < Math.round(share) ? 'filled' : ''}"></i>`).join('');
    el('overviewContent').innerHTML = `
      <section class="overview-totals" aria-label="数据库规模">
        ${stat('收录的游戏',num(c.games),'款游戏')}
        ${stat('成就记录',num(c.achievements),`${num(c.games_with_achievements)} 款游戏有成就记录`)}
        ${stat('玩家标签关系',num(c.tag_relations),`${num(c.games_with_tags)} 款游戏有玩家标签`)}
        ${stat('不同的玩家标签',num(c.distinct_tags),'同名标签只计一次')}
      </section>
      <section class="overview-section"><div class="overview-section-head"><span>01 / 评价</span><h2>热闹的游戏之外，还有许多安静的角落。</h2></div>
        ${r.games > 0 ? `<div class="overview-columns"><div class="overview-highlight"><strong>${pct(percent(under100,r.games))}</strong><p>的游戏，评价还不到 100 条。</p><div class="overview-fact">评价数量中位数 <b>${num(r.median)}</b> 条</div></div>
        <div>${bars([['尚无评价',r.zero],['1–99 条',r.one_to_99],['100–999 条',r.hundred_to_999],['1,000–9,999 条',r.thousand_to_9999],['10,000 条及以上',r.ten_thousand_plus]],r.games)}</div></div>` : '<p class="explore-note">暂无有效评价数量。</p>'}
        <p class="explore-note">分母：${num(r.games)} 款具有有效评价数量的游戏，包含零评价记录；${num(c.games-r.games)} 款缺少有效计数，未计入比例。评价数优先取 SteamSpy 好评+差评，缺失时使用商店搜索记录。</p>
      </section>
      <section class="overview-section"><div class="overview-section-head"><span>02 / 聚光灯</span><h2>评价有多集中？</h2></div>
        ${r.total > 0 ? `<div class="overview-columns"><div class="overview-highlight"><strong>${pct(share)}</strong><p>的评价，集中在评价量最多的约 1% 游戏里。</p><div class="overview-fact">${num(r.top_games)} 款游戏 · ${num(r.top_reviews)} 条评价</div></div>
          <figure class="overview-waffle"><div role="img" aria-label="评价量最多的约百分之一游戏占总评价的${pct(share)}">${cells}</div><figcaption><i></i> 深色格：这 ${num(r.top_games)} 款游戏的评价份额，每格约代表全部有效评价的 1%。</figcaption></figure></div>` : '<p class="explore-note">暂无可统计的评价总量。</p>'}
        <p class="explore-note">在上述 ${num(r.games)} 款游戏内按评价数排序，取前 1%（向上取整）。这里只描述已收录评价的集中程度，不代表销量或全平台市场份额。</p>
      </section>
      <section class="overview-section"><div class="overview-section-head"><span>03 / 成就清单</span><h2>上万条的清单很显眼，普通游戏又有多少？</h2></div>
        <div class="overview-columns"><div class="overview-highlight"><strong>${num(c.median_achievements)}<em>个</em></strong><p>是一款游戏成就数量的中位数。</p></div>
          <div class="overview-fact-panel"><b>${num(c.thousand_achievement_games)} 款</b><p>游戏拥有至少 1,000 个成就，占有成就记录游戏的 ${pct(percent(c.thousand_achievement_games,c.games_with_achievements))}。</p></div></div>
        <p class="explore-note">分母：${num(c.games_with_achievements)} 款有成就记录的游戏；${num(c.games-c.games_with_achievements)} 款未获得成就记录，未计入。成就数量不直接代表内容长度或难度。</p>
      </section>
      <section class="overview-section"><div class="overview-section-head"><span>04 / 稀有与常见</span><h2>成就清单里，有多少稀有的一项？</h2></div>
        <div class="overview-columns"><div class="overview-highlight"><strong>${pct(rare)}</strong><p>的成就，全局解锁率低于 1%。</p><div class="overview-fact">${num(c.rare_achievements)} 条成就记录</div></div>
          <div class="overview-fact-panel"><b>${pct(common)}</b><p>的成就，全局解锁率达到 50% 或以上。</p><small>${num(c.common_achievements)} 条成就记录</small></div></div>
        <p class="explore-note">分母：${num(c.achievements)} 条成就记录，每条成就计一次。不同游戏中的同名成就分别计数；解锁率是各游戏的全局比例，稀有不直接等于更难。</p>
      </section>
      <section class="overview-section"><div class="overview-section-head"><span>05 / 免费与付费</span><h2>不花钱，也能找到不少游戏。</h2></div>
        <div class="overview-columns"><div class="overview-highlight"><strong>${num(p.free)}<em>款</em></strong><p>游戏被商店标记为免费。</p><div class="overview-fact">占付费标记已知游戏的 ${pct(percent(p.free,knownPayments))}</div></div>
          <div>${bars([['免费',p.free],['付费',p.paid]],knownPayments)}<p class="explore-note">另有 ${num(p.unknown)} 款付费标记缺失。</p></div></div>
        <p class="explore-note">免费 / 付费来自采集时的商店标记；免费游戏仍可能包含内购，当前状态请以商店为准。</p>
      </section>
      <p class="overview-dateline">汇总生成：${esc(new Date(data.generated_at).toLocaleString('zh-CN'))} · 汇总结果最多保留五分钟。各源实际采集时间不同。</p>`;
  }

  async function open() {
    if (request) return request;
    if (loadedAt && Date.now()-loadedAt < 5*60*1000) return;
    el('overviewContent').innerHTML = '<p class="overview-loading">正在汇总游戏、成就和评价…</p>';
    request = (async () => {
      try {
        const response = await fetch('/api/overview');
        if (!response.ok) throw new Error(response.status === 429 ? '查询有点频繁，请稍后再试。' : '暂时无法读取总览数据。');
        const data = await response.json();
        render(data);
        loadedAt = Date.now();
      } catch (error) {
        el('overviewContent').innerHTML = `<p class="overview-loading">${esc(error.message)} <button class="text-button" id="overviewRetry">重试</button></p>`;
        el('overviewRetry').onclick = open;
      } finally { request = null; }
    })();
    return request;
  }
  window.Overview = {open};
})();
