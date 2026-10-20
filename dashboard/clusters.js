/* YMT 冻结研究成果：只读汇总，不在浏览器重新聚类。 */
(() => {
  'use strict';
  const esc = escapeHtml;
  const number = n => Number(n).toLocaleString('zh-CN');
  const percent = n => Number(n).toFixed(1) + '%';
  const names = ['分布较分散', '中段较集中', '极低解锁型', '两头集中型', '高解锁集中型'];
  const shortNames = ['分布较分散', '中段较集中', '极低解锁', '两头集中', '高解锁集中'];
  const descriptions = [
    '低解锁率和高解锁率的成就都有，分布拉得比较开。',
    '成就更多集中在低到中等解锁率，极低、极高的都少。',
    '柱子挤在最左边：许多成就只有很少的玩家拿到。',
    '左边一堆、右边又一堆，中间反而少。',
    '柱子挤在最右边：大部分成就都有很高的解锁率。',
  ];
  const tagLabels = {
    'Rogue-like': '肉鸽', 'Management': '经营管理', 'Visual Novel': '视觉小说',
    'Story Rich': '剧情丰富', 'VR': '虚拟现实', 'Early Access': '抢先体验',
    'PvP': '玩家对战', 'Local Co-Op': '本地合作', 'Hidden Object': '找物解谜', 'Relaxing': '休闲放松',
  };
  let dataPromise;

  /** loadData 复用同一份冻结汇总；失败后允许重新请求。 */
  function loadData() {
    if (!dataPromise) {
      dataPromise = fetch('/assets/research/ymt/cluster-data.json', {signal: AbortSignal.timeout(15000)})
        .then(async response => {
          if (!response.ok) throw new Error('汇总暂时无法读取');
          const data = await response.json();
          if (data.clusters?.length !== 5 || data.clusters.some((c, i) => c.id !== i || c.density?.length !== 40)
            || data.clusters.reduce((sum, c) => sum + c.games, 0) !== data.meta?.games) {
            throw new Error('研究汇总不完整');
          }
          return data;
        }).catch(error => { dataPromise = null; throw error; });
    }
    return dataPromise;
  }

  /** explanation 统一展示图表的详情说明。 */
  function explanation(finding) {
    return `<figcaption class="cluster-explanation"><p><b>详情说明</b>${finding}</p></figcaption>`;
  }

  /** shares 展示游戏数量分组；比例的分母始终是完整建模帧。 */
  function shares(data) {
    return `<section class="card cluster-section" aria-labelledby="clusterSharesTitle">
      <p class="cluster-step">01 / 先看全貌</p><h3 id="clusterSharesTitle">这 ${number(data.meta.games)} 款游戏，分成了哪五类？</h3>
      <p class="cluster-purpose">这里分的是“成就被拿到的情况”，每款游戏只算一次。</p>
      <figure data-cluster-chart="shares"><div class="cluster-share-chart">${data.clusters.map(c => `<div class="cluster-share-row">
        <a href="#cluster-shape-${c.id}" data-cluster-scroll="cluster-shape-${c.id}"><i style="background:${c.color}"></i>${names[c.id]}</a>
        <span class="cluster-share-track"><span style="width:${c.share * 100}%;background:${c.color}"></span></span>
        <strong>${percent(c.share * 100)}</strong><span class="cluster-count">${number(c.games)} 款</span>
      </div>`).join('')}</div>
      ${explanation('“中段较集中”和“分布较分散”两类最多，合起来约占 72%；“高解锁集中型”只占 1.9%。这是游戏数量的分布，不是玩家喜好投票。')}</figure>
    </section>`;
  }

  /** histogram 绘制原交付的游戏等权直方图，不使用平滑或重新拟合。 */
  function histogram(cluster) {
    const left = 54, top = 18, width = 430, height = 142;
    const ceiling = Math.ceil(Math.max(...cluster.density) * 100 / 5) * 5;
    const x = value => left + width * value / 100;
    const y = value => top + height * (1 - value / ceiling);
    const grid = [0, ceiling / 2, ceiling].map(tick => `<line x1="${left}" x2="${left + width}" y1="${y(tick)}" y2="${y(tick)}" stroke="#e2e1dd"/><text x="${left - 8}" y="${y(tick) + 4}" text-anchor="end">${percent(tick)}</text>`).join('');
    const bars = cluster.density.map((v, i) => `<rect x="${x(i * 2.5) + .7}" y="${y(v * 100)}" width="${width / 40 - 1.4}" height="${height * v * 100 / ceiling}" fill="${cluster.color}"/>`).join('');
    return `<svg class="cluster-histogram" viewBox="0 0 500 212" role="img" aria-label="${names[cluster.id]}：${descriptions[cluster.id]} 横轴为成就解锁率，纵轴为成就占比。">
      <text x="${left}" y="10">成就占比</text>${grid}${bars}
      ${[0, 50, 100].map(t => `<text x="${x(t)}" y="180" text-anchor="${t === 100 ? 'end' : 'middle'}">${t}%</text>`).join('')}
      <text x="${left + width / 2}" y="204" text-anchor="middle">成就解锁率：左边少人拿到 → 右边多人拿到</text></svg>`;
  }

  /** shapes 把五类分布拆成能在手机上独立阅读的图，每张图保留抽样分母。 */
  function shapes(data) {
    const findings = [
      '从左到右都有柱子，说明成就的解锁率跨度大。这张图没有关卡顺序，不能读成“越玩越难”。',
      '柱子更多落在低到中等解锁率，两端少。“好不好玩”和“入坑难不难”还需要另外的证据。',
      `全类平均有 ${percent(data.clusters[2].rare1)} 的成就解锁率不足 1%。这说明成就很少被拿到，单凭它还不知道原因。`,
      '抽样里，0–10% 和 50–80% 附近各有一堆，中间少。这是同一类游戏汇总后的形状，并不保证类内每一款都长这样。',
      `全类平均有 ${percent(data.clusters[4].common80)} 的成就解锁率超过 80%。它们的成就普遍被很多玩家拿到。`,
    ];
    return `<section class="cluster-section" aria-labelledby="clusterShapesTitle">
      <p class="cluster-step">02 / 五类到底长什么样</p><h3 id="clusterShapesTitle">看柱子堆在哪边，就知道成就通常有多少人拿到</h3>
      <p class="cluster-purpose">解锁率 10%，可以理解为 Steam 统计的玩家里，每 100 人约有 10 人拿到这项成就。</p>
      <p class="research-note">下图来自原交付的 ${number(data.meta.density_sample_games)} 款抽样游戏。先算每款游戏自己的分布，再等权平均；成就多的游戏不会因此更有分量。<strong>各小图纵轴刻度不同，比柱高时请先看刻度。</strong></p>
      <div class="cluster-shapes">${data.clusters.map(c => `<figure id="cluster-shape-${c.id}" class="card cluster-shape" data-cluster-chart="shape-${c.id}">
        <div class="cluster-shape-heading"><span class="cluster-dot" style="background:${c.color}"></span><h4>${names[c.id]}</h4></div>
        <p class="cluster-shape-gist">${descriptions[c.id]}</p>
        <p class="cluster-sample">这一类共 ${number(c.games)} 款 · 分布图抽样 ${number(c.sample_games)} 款</p>
        ${histogram(c)}
        ${explanation(findings[c.id])}
      </figure>`).join('')}</div>
    </section>`;
  }

  /** features 用三个有明确单位的指标对照各类，颜色只在同一列内比较。 */
  function features(data) {
    const columns = [['平均解锁率', 'mean'], ['极少人拿到的成就', 'rare1'], ['多数人拿到的成就', 'common50']];
    return `<section class="card cluster-section" aria-labelledby="clusterFeaturesTitle">
      <p class="cluster-step">03 / 用数字对照</p><h3 id="clusterFeaturesTitle">“极少人拿到”和“多数人拿到”，差多少？</h3>
      <p class="cluster-purpose">极少人拿到：解锁率低于 1%。多数人拿到：解锁率超过 50%。</p>
      <figure data-cluster-chart="features"><p class="cluster-scroll-hint">左右滑动看完整对照，左侧类名会保持可见 →</p><div class="cluster-table-scroll" tabindex="0" role="region" aria-label="五类特征对照，可左右滑动"><table class="cluster-table cluster-feature-table">
      <caption class="cluster-sr-only">五类游戏的平均解锁率、极少人拿到的成就占比、多数人拿到的成就占比。</caption>
      <thead><tr><th scope="col">游戏分型</th>${columns.map(([label]) => `<th scope="col">${label}</th>`).join('')}</tr></thead>
      <tbody>${data.clusters.map(c => `<tr><th scope="row">${names[c.id]}</th>${columns.map(([, key]) => {
        const values = data.clusters.map(row => row[key]);
        const relative = (c[key] - Math.min(...values)) / (Math.max(...values) - Math.min(...values) || 1);
        return `<td style="background:rgba(59,110,165,${.04 + relative * .23})">${percent(c[key])}</td>`;
      }).join('')}</tr>`).join('')}</tbody></table></div>
      ${explanation('“极低解锁型”中，平均 55.9% 的成就解锁率低于 1%；“高解锁集中型”中，平均 99.3% 的成就解锁率超过 50%。这里的占比说的是成就，不是弃坑玩家的比例。')}</figure>
    </section>`;
  }

  /** tags 同时展示富集倍数和实际覆盖率，避免把相对富集当作多数。 */
  function tags(data) {
    const heat = data.tags;
    const rows = Object.entries(tagLabels).map(([tag, label]) => {
      const i = heat.tags.indexOf(tag);
      return `<tr><th scope="row">${label}<small>${esc(tag)}</small></th>${heat.lift[i].map((lift, j) => {
        const alpha = lift > 1 ? .06 + Math.min(Math.log2(lift), 3) / 3 * .29 : .025;
        return `<td style="background:rgba(59,110,165,${alpha})"><strong>${lift.toFixed(2)}×</strong><small>${percent(heat.cov[i][j])} 带此标签</small></td>`;
      }).join('')}</tr>`;
    }).join('');
    return `<section class="card cluster-section" aria-labelledby="clusterTagsTitle">
      <p class="cluster-step">04 / 和哪些游戏类型有关</p><h3 id="clusterTagsTitle">哪些标签，在某一类游戏里更常见？</h3>
      <p class="cluster-purpose"><strong>1.00× 读作“1 倍”，表示这个标签在该类中和在全部分析样本中一样常见。</strong>高于 1.00× 表示更常见，低于 1.00× 表示更少见。</p>
      <p class="cluster-tag-key research-note">举个例子：假设全部分析样本中，10% 的游戏带某标签。某一类也有 10%，就是 <b>1.00×</b>；有 20%，就是 <b>2.00×</b>；只有 5%，就是 <b>0.50×</b>。倍数不是游戏数量，也不是玩家占比；表格小字才是该类游戏实际带标签的比例。</p>
      <figure data-cluster-chart="tags"><p class="cluster-scroll-hint">左右滑动看其他类别，左侧标签会保持可见 →</p><div class="cluster-table-scroll" tabindex="0" role="region" aria-label="游戏标签与成就分型关联，可左右滑动"><table class="cluster-table cluster-tag-table">
      <caption class="cluster-sr-only">十个展示标签的富集倍数和各类实际覆盖率。</caption>
      <thead><tr><th scope="col">Steam 玩家标签</th>${shortNames.map(name => `<th scope="col">${name}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>
      ${explanation('VR 在“极低解锁型”里约为整体的 2.8 倍，但实际也只有 9.0% 的游戏带 VR 标签；视觉小说更集中在“中段较集中”，找物解谜更集中在“高解锁集中型”。这是关联，不说明某种类型必然造成这种分布。')}</figure>
      <p class="research-note">标签没有参与分组，而是在分组完成后用来描述各类。这里选取 10 个便于理解的标签，不是全部标签；标签缺失和发售年份差异也会影响比较。</p>
    </section>`;
  }

  /** examples 保留簇内热门挑选规则，链接到面板原有单款详情。 */
  function examples(data) {
    return `<section class="cluster-section" aria-labelledby="clusterExamplesTitle">
      <p class="cluster-step">05 / 对照你认识的游戏</p><h3 id="clusterExamplesTitle">每类挑两款热门作品，看看它们被分到了哪里</h3>
      <p class="cluster-purpose">每类按评价数从高到低取前两款。它们是热门示例，未必最能代表这一类的典型形状。</p>
      <div class="cluster-example-grid">${data.clusters.map(c => `<article class="card cluster-example-group"><h4><i class="cluster-dot" style="background:${c.color}"></i>${names[c.id]}</h4>
      ${c.examples.map(game => `<a class="cluster-game" href="#explore/game/${game.appid}"><strong>${esc(game.name)} <span aria-hidden="true">↗</span></strong><span>${number(game.n_ach)} 个成就 · 平均解锁率 ${percent(game.p_mean)}</span><small>${game.reviews === null ? '评价数缺失' : number(game.reviews) + ' 条评价'} · 查看游戏数据</small></a>`).join('')}</article>`).join('')}</div>
      <p class="research-note">评价数优先使用 SteamSpy 好评＋差评，缺失时回退商店搜索。这里沿用 2026-10-17 快照，点击进入的游戏详情会读取当前数据库，数字可能略有变化。</p>
    </section>`;
  }

  /** pca 展示作者原图，分别解释两遍分组，保留原图与页面类名对照。 */
  function pca() {
    const charts = [
      {
        file: 'tier-pca.png', id: 'pca-tier',
        title: '第一遍：游戏主要按整体解锁率的高、中、低排开',
        purpose: '先把全部成就特征一起放进去，看看最明显的差别是什么。',
        picture: '每个点是一款抽样游戏，三种颜色是按成就特征分出的三档。同色的点是同一组；点挨得近，只表示它们在这张平面图里的综合特征更接近。',
        inputIntro: '主成分 1 和 2 都由下面同一组 10 项指标组成。先把各指标换到可比较的尺度，再分别按两套不同的权重相加，得到横轴和纵轴的位置。',
        inputs: [
          '1 项成就规模：成就总数，先取 log(1＋数量)，压缩特别大的数值。',
          '5 项解锁率统计：平均值、中位数、从低到高排列后 25% 位置的值、75% 位置的值，以及分散程度（标准差）。',
          '4 项成就占比：解锁率低于 1%、低于 5%、超过 50%、超过 80% 的成就，各占这款游戏全部成就的多少。',
        ],
        inputNote: '两条轴不是各选一个指标，而是同一组指标的两种组合。原交付没有保存具体权重，所以不能把主成分 1 或 2 直接等同于某一项指标。',
        horizontal: '“主成分 1”把上面 10 项指标按第一套权重组合，优先展开游戏之间最大的差异。这张图中，左侧整体解锁率较低，右侧较高。0、2 等刻度是综合坐标，不是 0%、2%，也不是难度分数。',
        vertical: '“主成分 2”同样组合上面 10 项指标，但使用另一套权重，展开与横轴不重复的差异。位置越高只代表这项综合坐标越大，不代表更好玩、更难，或成就更多。',
        variance: '方差衡量一组数离平均值有多分散：数值都挤在平均值附近，方差就小；分得越开，方差就越大。图中的百分比是“这条轴保留了多少原始特征差异”。把全部差异看成 100 份：横轴约 57 份，纵轴再约 14 份，合起来约 71 份，剩下约 29 份没有在平面图里展开。这不是玩家比例或分组准确率。',
        finding: '绿色大多在左，橙色在中间，蓝色在右，沿横向形成一条从低解锁到高解锁的带状分布。第一遍主要分出了整体解锁率的档次，还没有单独回答“成就分布形状有什么不同”。',
        note: '原图“大多好拿 / 大多难拿”是作者命名，解锁率高低本身不能直接证明游戏难度。',
      },
      {
        file: 'shape-pca.png', id: 'pca-shape',
        title: '第二遍：扣除一部分整体水平影响，再看五类结构',
        purpose: '尽量减少平均解锁率的影响后，看看分布形状相近的游戏落在哪里。',
        picture: '每个点是一款抽样游戏，五种颜色对应五种成就分布结构。这里先尽量扣除平均解锁率的线性影响，再比较游戏之间的差别；不能把它当成玩家喜好图。',
        inputIntro: '主成分 1 和 2 都由下面同一组 8 项指标组成，分别按两套不同的权重组合。这里更关注成就分布的形状。',
        inputs: [
          '1 项成就规模：成就总数，先取 log(1＋数量)，压缩特别大的数值。',
          '3 项分布形状：解锁率的分散程度（标准差）；中间 50% 的成就解锁率跨度（75% 位置减去 25% 位置）；平均值偏离中位数的程度（再按分散程度调整）。',
          '4 项成就占比：解锁率低于 1%、低于 5%、超过 50%、超过 80% 的成就，各占多少。',
        ],
        inputNote: '后面 7 项分布指标先做调整：估计在这款游戏的平均解锁率下，各项指标通常有多大，再保留实际值比估计值高多少或低多少。成就规模不做这一步；最后把 8 项都换到可比较的尺度。原交付没有保存两条轴的具体权重，不能据此断言哪项指标权重最大。',
        horizontal: '“主成分 1”把这 8 项处理后的指标按第一套权重组合，展示其中最大的差异。0、2 等刻度只是综合坐标，没有百分比或成就个数的单位，不能直接当成某项指标读。',
        vertical: '“主成分 2”仍然使用同一组 8 项指标，但换一套权重，展开与横轴不重复的差异。上面和下面表示综合特征不同，不是游戏质量或难度的高低，也不能拿这一张的坐标去对照上一张。',
        variance: '方差就是数值围绕平均值的分散程度；游戏在这些指标上越不一样，整体差异就越大。图中的百分比表示这条轴保留了多少差异。把全部差异看成 100 份：横轴约 29 份，纵轴约 21 份，合起来大约一半；另一半没有在这张平面图里展开。原图百分比做了取整，不是说 29% 的玩家或 21% 的游戏属于某一类。',
        finding: '能看到不同颜色各自更集中的区域，但部分边界仍挤在一起，并不是五座完全分开的小岛。五类可以用来描述游戏差异，不能把边界当成绝对分界线。',
        note: '这张图只展开了约一半的差异，平面上的重叠不能单独证明原始特征空间中的分组好坏。',
      },
    ];
    return `<section class="cluster-section" aria-labelledby="clusterPcaTitle">
      <p class="cluster-step">06 / 从点图看分组</p><h3 id="clusterPcaTitle">同一批游戏，为什么要分两遍？</h3>
      <p class="cluster-purpose">下面是作者的两张原图。每张抽样 1.2 万款游戏，图例中的数量是各类完整样本量，不是画出来的点数。两张图的坐标和分类各自计算，同一种颜色在两图中含义不同。</p>
      <p class="research-note">图片中的字较小，点击可打开原图放大查看。</p>
      ${charts.map(chart => `<figure class="card cluster-pca" data-cluster-chart="${chart.id}">
        <h4>${chart.title}</h4><p class="cluster-purpose">${chart.purpose}</p>
        <a class="cluster-pca-image" href="/assets/research/ymt/${chart.file}" target="_blank" rel="noopener noreferrer" aria-label="打开原图：${chart.title}"><img src="/assets/research/ymt/${chart.file}" alt="${chart.title}，每个点代表一款抽样游戏，不同颜色代表各自的分组。" loading="lazy" decoding="async" width="1470" height="1050"><span>打开原图放大查看 ↗</span></a>
        <dl class="cluster-pca-guide"><div><dt>这张图画的是什么</dt><dd>${chart.picture}</dd></div><div class="cluster-pca-inputs"><dt>主成分 1、2 分别由什么组成</dt><dd><p>${chart.inputIntro}</p><ul>${chart.inputs.map(input => `<li>${input}</li>`).join('')}</ul><p>${chart.inputNote}</p></dd></div><div><dt>横轴：左右在比较什么</dt><dd>${chart.horizontal}</dd></div><div><dt>纵轴：上下在比较什么</dt><dd>${chart.vertical}</dd></div><div><dt>“方差百分比”是什么意思</dt><dd>${chart.variance}</dd></div></dl>
        ${explanation(chart.finding)}<p class="research-note">${chart.note}</p>
        ${chart.id === 'pca-shape' ? '<p class="cluster-pca-names research-note"><b>原图类名对照：</b>正常型 → 分布较分散；好玩但入坑难型 → 中段较集中；入门劝退型 → 极低解锁型；两极分化型 → 两头集中型；玩家友好型 → 高解锁集中型。旧名仅用于对应原图颜色，不表示本页验证了“好玩”或“劝退”。</p>' : ''}
      </figure>`).join('')}</section>`;
  }

  /** render 组织冻结成果和读图说明，避免把成就分布解释为玩家偏好。 */
  function render(data) {
    return `<div class="cluster-lead"><p class="cluster-step">这项研究在做什么</p><h3>同样有成就，<br>游戏的“解锁情况”也很不一样。</h3><p>有些游戏的成就大多很少被拿到，有些几乎人人都有，还有些两头多、中间少。这项研究把情况相近的游戏放到一组，看看它们有什么共同点。</p>
      <div class="cluster-kpis"><div><strong>${number(data.meta.games)}</strong><span>款游戏参与分组</span></div><div><strong>${(data.meta.achievements / 10000).toFixed(1)} 万</strong><span>条成就记录用于特征统计</span></div><div><strong>5 类</strong><span>成就解锁情况</span></div></div>
      <p class="research-note">2026-10-17 冻结成果 · 每款至少 ${data.meta.minimum_achievements} 个成就 · 分组的是游戏，不是玩家</p></div>
      ${shares(data)}${shapes(data)}${features(data)}${tags(data)}${examples(data)}${pca()}
      <footer class="cluster-footer research-note">研究者：耶美田（YMT） · 来源：Steam 成就全局解锁率、Steam 商店、SteamSpy 玩家标签。原交付另含 <a href="https://rawg.io/" target="_blank" rel="noopener noreferrer">RAWG</a> 事后描述，本页未展示其时长数据。<br>本页为固定研究快照，不随游戏探索页刷新。</footer>`;
  }

  /**
   * mount 路由离开后不再写入旧节点；加载错误提供原位重试。
   * @param {HTMLElement} container 研究页的内容容器。
   * @returns {Promise<void>}
   */
  async function mount(container) {
    const root = document.createElement('div');
    root.id = 'clusterReport';
    root.innerHTML = '<p class="research-note" role="status">正在读取游戏分型研究…</p>';
    container.append(root);
    try {
      const data = await loadData();
      if (!root.isConnected) return;
      root.innerHTML = render(data);
      root.querySelectorAll('[data-cluster-scroll]').forEach(link => link.addEventListener('click', event => {
        event.preventDefault();
        const target = document.getElementById(link.dataset.clusterScroll);
        target?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
        target?.focus({preventScroll: true});
      }));
      root.querySelectorAll('.cluster-shape').forEach(figure => { figure.tabIndex = -1; });
    } catch (_) {
      if (!root.isConnected) return;
      root.innerHTML = '<section class="card cluster-error" role="alert"><h3>研究汇总暂时没加载出来</h3><p class="research-note">请重试一次，其他研究入口仍可使用。</p><button class="ghost" type="button">重新加载</button></section>';
      root.querySelector('button').addEventListener('click', () => { root.remove(); mount(container); });
    }
  }

  window.ClusterResearch = {mount};
})();
