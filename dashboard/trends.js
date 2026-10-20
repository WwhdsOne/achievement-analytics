/* YJH 第二版冻结成果：原图与汇总只读展示，不重新查询或计算研究模型。 */
(() => {
  'use strict';
  const esc = escapeHtml;
  const number = value => Number(value).toLocaleString('zh-CN');
  const pct = (value, digits = 1) => Number(value).toFixed(digits) + '%';
  const files = {genre: 'genre-share.png', official: 'official-genre.png', theme: 'theme-growth.png', players: 'player-growth.png'};
  let dataPromise;

  /** loadData 缓存冻结汇总；失败后允许重试。 */
  function loadData() {
    if (!dataPromise) {
      dataPromise = fetch('/assets/research/yjh/trend-data.json', {signal: AbortSignal.timeout(15000)})
        .then(async response => {
          if (!response.ok) throw new Error('趋势汇总暂时无法读取');
          const data = await response.json();
          if (!Number.isInteger(data.meta?.games) || data.figures?.length !== 4
            || new Set(data.figures.map(row => row.id)).size !== 4
            || data.figures.some(row => files[row.id] !== row.file)
            || [2014, 2020, 2024, 2025].some(year => !data.coverage?.[year])
            || data.theme_growth?.length !== 10 || data.player_growth?.length !== 7) {
            throw new Error('趋势研究汇总不完整');
          }
          return data;
        }).catch(error => { dataPromise = null; throw error; });
    }
    return dataPromise;
  }

  /** explanation 沿用用户指定的“详情说明”图注。 */
  function explanation(text) {
    return `<figcaption class="trend-explanation"><b>详情说明</b><p>${text}</p></figcaption>`;
  }

  /** labelKey 给保留英文标签的原图附上中文对照。 */
  function labelKey(records, labels) {
    return `<div class="trend-label-key" aria-label="原图英文标签中文对照">${records.map(row => `<span><b>${esc(labels[row.tag])}</b><small>${esc(row.tag)}</small></span>`).join('')}</div>`;
  }

  /** charts 原字节展示第二版四张图，解释时间窗口、轴、分母及图示结论。 */
  function charts(data) {
    const casual = data.casual_comparison;
    const anime = data.theme_growth.find(row => row.tag === 'Anime');
    const space = data.theme_growth.find(row => row.tag === 'Space');
    const single = data.player_growth.find(row => row.tag === 'Singleplayer');
    const multi = data.player_growth.find(row => row.tag === 'Multiplayer');
    const official = data.official_share;
    const configs = [
      {
        id: 'genre', step: '01 / 游戏类型', title: '哪些类型，在不同年份的新游戏里更常见？',
        purpose: '2014–2024 年 · 按 SteamSpy 玩家标签中的“类型与子类型”统计。',
        finding: `休闲类从 2014 年的 ${pct(casual.base_pct, 2)} 升到 2024 年的 ${pct(casual.end_pct, 2)}；动作和冒险的曲线总体下移。这里看到的是不同发售批次的类型构成变化，不是这些类型的销量、在线人数或历史热度变化。`,
        note: `为什么没画 2025 年？原图使用的是 2026-10-16 的旧快照，其中 2025 年 ${number(data.coverage[2025].games)} 款样本只有 ${number(data.coverage[2025].with_tags)} 款有玩家标签（${pct(data.coverage[2025].coverage_pct)}），原作者把趋势窗口设到 2024 年。这不代表 2025 年没有游戏数据，也不代表当前云库仍是这个覆盖情况。标签是抓取时的属性，不能直接解释成当年的热度。`,
      },
      {
        id: 'official', step: '02 / 官方分类作对照', title: '换成 Steam 官方分类，变化方向是否相似？',
        purpose: '2014–2024 年 · 保留作者的官方分类对照原图。',
        finding: `休闲这条线从 ${pct(official[2014].Casual)} 上升到 ${pct(official[2024].Casual)}，模拟也从 ${pct(official[2014].Simulation)} 上升到 ${pct(official[2024].Simulation)}。休闲在两套分类中都呈上升方向，但具体比例的含义不同。图中的“独立”和“免费游玩”描述制作或发行属性，要与玩法类型分开读。`,
        note: '保留原作者的统计结果，没有用当前数据库重算或改写这张图。其官方类型计数范围与分母差别依据原统计代码核对后，在此明确标注。',
      },
      {
        id: 'theme', step: '03 / 题材与设定', title: '日系动画、心理恐怖等题材，占比怎样变化？',
        purpose: '2014→2020 年 · 图中展示 10 个题材设定标签，英文名见图下中文对照。',
        finding: `日系动画从 ${pct(anime.base_pct, 2)} 升到 ${pct(anime.end_pct, 2)}，增加 ${anime.delta_pp.toFixed(2)} 个百分点。太空题材的游戏数虽然从 ${space.base_games} 款增到 ${space.end_games} 款，占比却从 ${pct(space.base_pct, 2)} 降到 ${pct(space.end_pct, 2)}：数量变多，不一定代表在新游戏中的份额变大。`,
        note: '原图把百分比取整，所以“4%→4%”也可能有小幅变化。柱长来自未取整的占比差；这里展示的是该题材维度中选出的条目，不是全部题材或完整 Steam 的排名。',
        records: data.theme_growth,
      },
      {
        id: 'players', step: '04 / 玩家模式与支持', title: '单人、多人与合作标签，各占多大份额？',
        purpose: '2014→2020 年 · 玩家模式及支持功能标签，按原作者维度归类。',
        finding: `单人标签从 ${pct(single.base_pct, 2)} 升到 ${pct(single.end_pct, 2)}；多人标签从 ${pct(multi.base_pct, 2)} 降到 ${pct(multi.end_pct, 2)}，但带多人标签的游戏数从 ${multi.base_games} 款增到了 ${multi.end_games} 款。这说明它在这批新游戏中的份额下降，不能据此说“多人游戏没人玩了”。`,
        note: '统计的是游戏带不带这些标签，不是实际选择单人或多人模式的玩家比例。一款游戏可以同时拥有单人、多人、合作等标签。',
        records: data.player_growth,
      },
    ];
    return configs.map(chart => {
      const file = data.figures.find(row => row.id === chart.id);
      return `<section class="card trend-section" aria-labelledby="trend-${chart.id}-title"><p class="trend-step">${chart.step}</p><h3 id="trend-${chart.id}-title">${chart.title}</h3><p class="trend-purpose">${chart.purpose}</p>
        ${chart.id === 'official' ? '<p class="trend-definition">这张原图与玩家标签图的统计范围不同，只比较走势，不直接比较百分比。</p>' : ''}
        <figure data-trend-chart="${chart.id}"><a class="trend-image" href="/assets/research/yjh/${file.file}" target="_blank" rel="noopener noreferrer" aria-label="打开原图：${chart.title}"><img src="/assets/research/yjh/${file.file}" alt="${chart.title}，${chart.purpose}" width="${file.width}" height="${file.height}" loading="lazy" decoding="async"><span>打开原图放大查看 ↗</span></a>
        ${chart.records ? labelKey(chart.records, data.labels) : ''}
        ${explanation(chart.finding)}<p class="trend-figure-note">${chart.note}</p></figure></section>`;
    }).join('');
  }

  /** render 给出时间范围和读图说明，避免把发行结构解释为历史玩家偏好。 */
  function render(data) {
    return `<div class="trend-lead"><p class="trend-step">这项研究在做什么</p><h3>按发售年份分组，<br>看看游戏的类型构成怎么变。</h3>
      <p>把项目数据库中的游戏按发售年份分组，统计各类标签有多常见。这里反映的是不同年份发售的游戏有什么属性；它没有记录当年的销量、在线人数或玩家偏好。</p>
      <div class="trend-kpis"><div><strong>${number(data.meta.games)}</strong><span>款游戏构成整体快照样本</span></div><div><strong>2014–2024</strong><span>类型折线图的发售年份</span></div><div><strong>2014–2020</strong><span>增长榜的两个比较年份</span></div></div>
      <p class="research-note">杨金辉（YJH）· 第二版冻结成果 · 2026-10-16 提取 · 仅含 2026 年以前发售的游戏</p></div>
      ${charts(data)}
      <footer class="trend-footer research-note">来源：Steam 商店的发售日期与官方分类、SteamSpy 玩家标签。标签抓取窗口为 2026-09-18 至 2026-10-01。<br>本页为固定研究快照，不随游戏探索页刷新；输入指纹 ${esc(data.meta.input_sha256.slice(0, 12))}。</footer>`;
  }

  /**
   * mount 加载趋势报告，离开路由后不写入旧节点；失败可原位重试。
   * @param {HTMLElement} container 研究页内容容器。
   * @returns {Promise<void>}
   */
  async function mount(container) {
    const root = document.createElement('div');
    root.id = 'trendReport';
    root.innerHTML = '<p class="research-note" role="status">正在读取发售年份研究…</p>';
    container.append(root);
    try {
      const data = await loadData();
      if (!root.isConnected) return;
      root.innerHTML = render(data);
    } catch (_) {
      if (!root.isConnected) return;
      root.innerHTML = '<section class="card trend-error" role="alert"><h3>年份趋势汇总暂时没加载出来</h3><p class="research-note">请重试一次，其他研究入口仍可使用。</p><button class="ghost" type="button">重新加载</button></section>';
      root.querySelector('button').addEventListener('click', () => { root.remove(); mount(container); });
    }
  }

  window.TrendResearch = {mount};
})();
