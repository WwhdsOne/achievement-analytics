/* 固定版本研究报告：导航、结果说明与交互图表。 */
(() => {
  'use strict';
  const pages = {
    overview: ['游戏里的意外发现', '三个故事，看懂这批游戏', '一款游戏能有多少成就？热门之外还有什么？喜欢一款游戏，就一定要玩到通关吗？'],
    structure: ['成就结构', '整体稀有度与尾部挑战', '展示成就完成率分布，比较整体稀有度与尾部结构的预测增益。低完成率是结构代理，不等同于纯技术难度。'],
    types: ['类型对照', '类型内外关系与魂like专题', '展示整体与类型内部的关联，以及加入控制特征后的变化；进一步对照 Souls-like 等标签的游戏级参与度。'],
    reputation: ['口碑与参与度', '好评、时长与状态的分歧', '展示口碑与参与度指标的一致性和分歧，帮助区分“评价好”“投入时间长”和“有通关标记”等不同含义。'],
    models: ['模型归因', 'baseline、树模型与SHAP', '展示三种目标的交叉验证、时间留出表现和随机森林 SHAP，判断模型能解释多少差异以及预测主要依赖什么特征。'],
    robustness: ['方法与数据质量', '样本偏差、稳定性与分类抽查', '展示数据覆盖有哪些偏差、改变样本门槛后结果是否稳定，并提供成就描述分类的人工抽查材料。这些检查说明研究的局限，不是新的玩家偏好结论。'],
    extensions: ['内容与标签', '文本规则和标签交互探索', '展示成就描述的关键词匹配和固定标签组合的预测增益。文本类别尚未独立人工验证，本页结果仅作探索。']
  };
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => value == null ? '—' : Number(value).toLocaleString('en-US');
  const fixed = (value, digits = 3) => value == null ? '—' : Number(value).toFixed(digits);
  const pct = value => value == null ? '—' : (value * 100).toFixed(1) + '%';
  const colors = ['#326963', '#9C423A', '#1C1C1A', '#77766F', '#6D748C'];
  let report = null;
  let request = null;
  let renderToken = 0;
  let plotSequence = 0;
  const plotJobs = [];

  function section(title, content, note = '') {
    return `<section class="analysis-section"><h2>${esc(title)}</h2>${content}${note ? `<p class="analysis-note">${note}</p>` : ''}</section>`;
  }
  function table(headers, rows) {
    const numeric = value => /^(?:[-+]?\d[\d,.]*(?:%| h| pp)?|—)$/.test(String(value));
    return `<div class="analysis-table-wrap"><table class="analysis-table"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(c => `<td${numeric(c) ? ' class="number"' : ''}>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function gameLink(row) {
    return `<button data-game="${Number(row.appid)}" title="查看这款游戏的完整数据">${esc(row.name_zh || row.name_en)} <small>· ${Number(row.appid)}</small></button>`;
  }
  function plot(label, traces, layout = {}) {
    const id = `researchPlot${++plotSequence}`;
    plotJobs.push({id, traces, layout});
    return `<div class="analysis-plot" id="${id}" role="img" aria-label="${esc(label)}"></div>`;
  }
  function bar(label, names, values, color = colors[0]) {
    return plot(label, [{type:'bar', x:names, y:values, marker:{color}, hovertemplate:'%{x}<br>%{y:.3f}<extra></extra>'}]);
  }
  function findings(page) {
    return section('本次结果', `<ul class="findings">${report.conclusions[page].map(s => `<li>${esc(s)}</li>`).join('')}</ul>`);
  }
  function plotLayout(extra) {
    return {paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
      font:{family:'Inter, PingFang SC, sans-serif', size:11, color:'#4A4944'},
      margin:{l:60,r:20,t:28,b:70}, colorway:colors, hovermode:'closest',
      xaxis:{gridcolor:'#DEDDD6', zerolinecolor:'#C6C5BF', automargin:true},
      yaxis:{gridcolor:'#DEDDD6', zerolinecolor:'#C6C5BF', automargin:true},
      legend:{orientation:'h', y:1.13, x:0}, ...extra};
  }
  async function renderPlots() {
    if (!window.Plotly) {
      plotJobs.forEach(job => { $(job.id).innerHTML = '<p class="plot-error">图表组件未加载，数值仍可查看下方表格。</p>'; });
      return;
    }
    for (const job of plotJobs) {
      const node = $(job.id);
      if (!node) continue;
      try {
        await Plotly.newPlot(node, job.traces, plotLayout(job.layout), {responsive:true, displaylogo:false,
          modeBarButtonsToRemove:['select2d','lasso2d'], toImageButtonOptions:{format:'png',scale:2}});
      } catch (_) {
        node.innerHTML = '<p class="plot-error">图表渲染失败，请查看本页数值表。</p>';
      }
    }
  }
  function methods() {
    const m = report.metadata;
    return `<details class="method-details"><summary>这些数字怎么算 · 样本与数据版本</summary>
      <p>首页成就故事使用成就数有效且大于0的游戏；评价故事使用好评、差评数均有效的游戏，零条评价计入，不足100条不含恰好100条。两者不使用模型的样本门槛。星露谷物语是预先选取的案例，要求至少100条Steam评价、20个RAWG通关或弃坑标记。</p>
      <p>范围：商店发售日期早于2026年、成就映射无未解决问题的游戏；固定帧 ${num(m.games)} 款。剔除的映射台账 ${num(m.excluded_mapping)} 条。不同目标分别选取非缺失样本；模型与主线结构比较还要求至少5个成就、100条SteamSpy评价；状态目标要求至少20个通关/弃坑标记。</p>
      <p>状态目标 = dropped / (beaten + dropped)，它是通关或弃坑标记者中的弃坑占比。owned 不用于证明实际游玩；缺失计数不补零。通关占比在同一分母下与弃坑占比互补，不重复作为独立目标。Wilson 95%区间仅反映计数不确定性，不覆盖平台选择偏差。</p>
      <p>每款游戏等权。时长为 RAWG playtime 字段，正值取 log1p；0视为不可用而非零小时玩家。拥有量取估算区间中点再取 log1p，现价以美分转美元，免费与未知价格分别处理。当前价格不代表历史购买价。</p>
      <p>随机五折 random_state=42；填补和标准化仅在训练折拟合。Ridge alpha=10；随机森林160棵树、最大深度9、最小叶节点15。好评目标不使用评价数特征，避免把比例分母作为解释变量。标签使用数据库实测词形Rogue-like，不擅自合并Rogue-lite或Action Roguelike。时间留出：≤2022年训练，2023–2025年测试。SHAP在最后一折未参与训练的最多300款游戏计算；没有执行玩家能力/2PL拟合。</p>
      <p>版本：${esc(m.version)}<br>快照时间：${esc(m.built_at)}<br>SHA256：${esc(m.sha256)}<br>结果生成：${esc(report.generated_at)}</p>
      ${table(['源','首次抓取','末次抓取'],m.source_times.map(r=>[esc(r.source),esc(r.first_fetch),esc(r.last_fetch)]))}
      <p>源时间表为抓取审计范围，不是逐游戏统一采样时刻。各字段仍存在跨源时间差与聚合人群差异。</p>
    </details>`;
  }
  function overview() {
    const stories = report.stories;
    if (!stories) return section('这份报告还没有数据故事',
      '<p>请按命令手册更新同版本故事数据，再刷新页面。原有研究专题仍可从“深入研究”打开。</p>');
    const a = stories.achievements, r = stories.reviews, f = stories.featured;
    const leader = a.leaders[0];
    const filled = r.under_100_ratio == null ? 0 : Math.round(r.under_100_ratio * 100);
    const date = String(report.metadata.built_at || '').slice(0, 10);
    let html = `<p class="story-dateline">${esc(date)} 固定快照 · ${num(report.metadata.games)} 款游戏 · 2026 年前发售、带成就的研究样本</p>`;
    html += `<section class="data-story story-achievements"><div class="story-index">01 / 成就数量奇观</div>
      <h2>一款游戏，能有多少个成就？</h2>`;
    if (leader) html += `<div class="story-split"><div><div class="story-number">${num(leader.ach_count)}</div>
      <p class="story-number-label">个成就 · ${gameLink(leader)}</p></div>
      <div class="story-comparison"><span>而样本里一半游戏的成就数不超过</span><strong>${num(a.median_count)} <small>个</small></strong>
      <p>有 <b>${num(a.thousand_plus)}</b> 款游戏，成就数达到了 1,000 个以上。</p></div></div>
      <p class="story-takeaway">成就多，就一定内容丰富吗？先看看数量最夸张的几款。</p>
      <details class="story-details"><summary>看看成就最多的 5 款游戏</summary>
      ${table(['游戏', '成就数'], a.leaders.map(row=>[gameLink(row),num(row.ach_count)]))}</details>`;
    else html += '<p>当前快照没有有效的成就数量，暂不展示排名。</p>';
    html += `<p class="story-source">来源：Steam 成就记录 · 有效样本 ${num(a.sample_n)} 款。数量不代表质量或难度。</p></section>`;
    html += `<section class="data-story story-reviews"><div class="story-index">02 / 热门之外</div>
      <h2>你熟悉的是大作，还有多少游戏很少被评价？</h2>`;
    if (r.sample_n) html += `<div class="story-split"><div><div class="story-number">${pct(r.under_100_ratio)}</div>
      <p class="story-number-label">的游戏，评价数不足 100 条</p>
      <p>一半游戏的评价数不超过 <b>${num(r.median_count)}</b> 条。</p></div>
      <figure class="story-waffle-figure"><div class="story-waffle" role="img" aria-label="每格表示约百分之一的游戏，${filled}格表示评价不足100条">
      ${Array.from({length:100},(_,i)=>`<span class="waffle-cell${i<filled?' filled':''}" aria-hidden="true"></span>`).join('')}</div>
      <figcaption>每格 ≈ 1% 的游戏<br><i></i> 评价不足 100 条 · 约 ${filled} 格</figcaption></figure></div>
      <p class="story-takeaway">热门游戏之外，还有大量很少被评价的作品。评价少，不等于不好玩。</p>`;
    else html += '<p>当前快照没有有效的评价计数，暂不计算比例。</p>';
    html += `<p class="story-source">来源：SteamSpy 收录的 Steam 好评与差评计数 · ${num(r.under_100)} / ${num(r.sample_n)} 款。缺失不当作零；方格按百分比四舍五入。</p></section>`;
    html += `<section class="data-story story-stardew"><div class="story-index">03 / 喜欢，也可能放下</div>
      <h2>喜欢一款游戏，就一定要玩到通关吗？</h2>`;
    if (f) html += `<div class="story-split"><div><p class="story-game">${gameLink(f)}</p>
      <div class="story-number">${pct(f.approval)}</div><p class="story-number-label">Steam 好评率 · ${num(f.reviews)} 条评价</p></div>
      <div class="story-states"><p>另一个平台 RAWG 上，用户这样标记：</p>
      ${[['通关',f.beaten,'beaten'],['弃坑',f.dropped,'dropped']].map(([label,count,kind])=>
        `<div class="story-state"><div><span>${label}</span><strong>${num(count)} 人</strong></div>
        <div class="story-track"><span class="${kind}" style="width:${count/f.state_total*100}%"></span></div></div>`).join('')}
      </div></div><p class="story-takeaway">高好评和“弃坑”标记可以同时存在。开放式游戏的“玩完”，又该怎么定义？</p>
      <p class="story-caveat">两个平台不是同一批用户。右图只统计 RAWG 的通关或弃坑标记，不能据此推断全部 Steam 玩家的弃坑率，也不能说这些用户“给了好评却弃坑”。</p>`;
    else html += '<p>星露谷物语在当前快照中的有效评价或状态标记不足，暂不展示这个案例。</p>';
    html += `<p class="story-source">来源：SteamSpy / RAWG · 预先选取的单款游戏案例，不是游戏排行榜。</p></section>
      <details class="method-details story-research"><summary>想再深入一点？查看完整研究</summary>
      <div class="page-links">${Object.entries(pages).filter(([key])=>key!=='overview').map(([key,info])=>
        `<a href="#analysis/${key}"><strong>${esc(info[0])}</strong><span>${esc(info[2])}</span></a>`).join('')}</div></details>`;
    return html;
  }
  function scatterControls(id, options) {
    return `<div class="analysis-controls"><label>类型<select id="${id}"><option value="全部">全部有效样本</option>${options.map(g=>`<option>${esc(g)}</option>`).join('')}</select></label></div>`;
  }
  function structure() {
    const hist = report.histogram;
    const labels = hist.counts.map((_,i)=>`${hist.edges[i]}–${hist.edges[i+1]}%`);
    return findings('structure') + section('典型成就完成率分布', bar('游戏的成就完成率中位数直方图',labels,hist.counts),
      `按游戏的完成率中位数分箱，样本 ${num(hist.n)} 款（至少5个成就）。低完成率不直接代表技术难度。`) +
      section('主体与尾部的描述性对照', table(['结构条件','游戏数','稀有度中位数','弃坑占比中位数','时长中位数'],
        report.structures.map(r=>[esc(r.label),num(r.n),fixed(r.median_rarity,1),pct(r.median_drop),fixed(r.median_hours,1)+' h'])),
        `条件可重叠；稀有度=100−中位完成率。小样本条件：${report.structures.filter(r=>r.n<20).map(r=>`${esc(r.label)}（${num(r.n)}款）`).join('、') || '本次均至少20款'}；不能据小样本推广结构差异。这些未控制的中位数不能单独证明尾部设计的效果，预测增益见模型归因。`) +
      section('成就结构 × 弃坑标记占比', scatterControls('structureGenre',['Action','Adventure','RPG','Strategy','Simulation','Casual']) +
        `<div class="analysis-controls"><label><input type="checkbox" id="showIntervals">Wilson 95%区间</label></div><div id="structureScatter" class="analysis-plot"></div>`,
        `图使用种子42抽取的最多1,300款游戏；当前报告 ${num(report.points.length)} 个点。统计与模型使用完整有效样本。横轴越右代表成就越稀有；中线为抽样点中位数，仅辅助观察，不划定真实玩家类型。`);
  }
  function types() {
    const rows = report.types;
    return findings('types') + section('类型内外：稀有度每增加10点对应的比例变化',plot('类型内未控制和控制后关联对照',[
      {type:'bar',name:'仅稀有度',x:rows.map(r=>r.type),y:rows.map(r=>r.raw_slope),marker:{color:colors[2]}},
      {type:'bar',name:'加入控制特征',x:rows.map(r=>r.type),y:rows.map(r=>r.adjusted_slope),marker:{color:colors[0]}}
    ],{barmode:'group',yaxis:{title:{text:'弃坑占比变化 · 百分点'},gridcolor:'#DEDDD6'}}),
      '控制特征含年份、价格、热度代理、类型、标签和成就结构；相关特征间的系数可能不稳定，柱长不是因果效应。多类型游戏可出现在多个类型内分析中。') +
      section('类型内统计',table(['类型','游戏数','Spearman ρ','未控制变化/10点','控制后变化/10点'],rows.map(r=>[
        esc(r.type),num(r.n),fixed(r.rho),fixed(r.raw_slope,2)+' pp',fixed(r.adjusted_slope,2)+' pp']))) +
      section('细粒度标签专题',table(['标签/对照','游戏数','稀有度中位数','弃坑占比中位数','时长中位数','好评率中位数'],
        report.tag_comparison.flatMap(r=>[r.tagged,r.comparison].map(s=>[esc(s.label),num(s.n),fixed(s.median_rarity,1),pct(s.median_drop),fixed(s.median_hours,1)+' h',pct(s.median_approval)]))),
        '标签组与“Action且无该标签”对照来自主线状态样本；该对照对非动作标签仅作展示，未匹配年份和热度，不把差异归因于标签。');
  }
  function reputation() {
    return findings('reputation') + section('指标一致性',table(['指标一','指标二','成对有效游戏数','Spearman ρ'],
      report.correlations.map(r=>[esc(r.left),esc(r.right),num(r.n),fixed(r.rho)]))) +
      section('口碑 × 弃坑标记占比',scatterControls('reputationGenre',['Action','Adventure','RPG','Strategy','Casual'])+
        '<div id="reputationScatter" class="analysis-plot"></div>',
        '仅绘制固定随机样本中的成对有效观测，相关系数使用完整联合样本。Steam好评人与RAWG状态标记者并非同一人群。') +
      section('高好评但仍有弃坑标记的示例',table(['游戏','好评率','弃坑占比','状态分母','RAWG时长'],
        report.discordant.map(r=>[gameLink(r),pct(r.approval),pct(r.drop_ratio),num(r.resolved_total),r.playtime>0?fixed(r.playtime,0)+' h':'—'])),
        '人工选取热门游戏案例，使用中文常用名；仅展示好评率≥90%、至少50个通关/弃坑标记的游戏，按弃坑标记占比降序排列。不是全量弃坑占比最高的排行榜，也不能证明同一个人给好评后弃坑。');
  }
  function modelSelect() {
    return `<div class="analysis-controls"><label>分析目标<select id="modelTarget">${report.models.map(m=>`<option value="${esc(m.target)}">${esc(m.label)}</option>`).join('')}</select></label></div><div id="modelDetails"></div>`;
  }
  function models() {
    return findings('models') + modelSelect();
  }
  function renderModel(target) {
    const m = report.models.find(m=>m.target===target);
    plotJobs.length=0;
    $('modelDetails').innerHTML = section('随机五折：同样本、同划分比较',table(['模型/特征','游戏数','OOF R²','OOF RMSE','各折R²标准差'],
      m.metrics.map(r=>[esc(r.name),num(r.n),fixed(r.r2),fixed(r.rmse),fixed(r.r2_std)])),
      'OOF表示每款游戏的预测来自未训练过它的模型。比例目标的RMSE用0–1单位；时长目标用log1p小时。标准差描述折间变化，不是置信区间。') +
      section('按发售年份的留出评估',table(['模型','训练游戏数','测试游戏数','R²','RMSE'],m.temporal.map(r=>[
        esc(r.name),num(r.train_n),num(r.test_n),fixed(r.r2),fixed(r.rmse)])),
        '≤2022年发售游戏训练，2023–2025年发售游戏测试；这是跨发售年代的泛化检查，所有目标仍来自同一抓取窗口，不是预测未来行为。') +
      section('随机森林 SHAP：模型依赖哪些特征',plot('留出游戏SHAP平均绝对贡献',[{
        type:'bar',orientation:'h',y:m.shap.map(r=>r.feature).reverse(),x:m.shap.map(r=>r.mean_abs_shap).reverse(),marker:{color:colors[0]},
        hovertemplate:'%{y}<br>平均绝对SHAP %{x:.4f}<extra></extra>'
      }],{margin:{l:156,r:20,t:10,b:45},xaxis:{title:{text:'平均绝对SHAP · 目标单位'},gridcolor:'#DEDDD6'}}),
        `归因样本为最后一折留出的 ${num(m.shap_n)} 款游戏。平均绝对SHAP只表示贡献大小，不表示方向，不是因果效应。`) +
      section('SHAP方向与特征值',`<div class="analysis-controls"><label>特征<select id="shapFeature">${Object.keys(m.shap_points).map(f=>`<option>${esc(f)}</option>`).join('')}</select></label></div><div class="analysis-plot" id="shapDependence"></div>`,
        '纵轴正值表示该特征在模型中将预测推高，负值表示推低；相关特征会分担贡献，不解释为可操控的设计效果。');
    renderPlots();
    const dependence = () => {
      if (!window.Plotly) { $('shapDependence').innerHTML='<p class="plot-error">图表组件未加载，模型数值可在上方表格查看。</p>'; return; }
      const feature = $('shapFeature').value;
      const values = m.shap_points[feature];
      Plotly.newPlot('shapDependence',[{type:'scatter',mode:'markers',x:values.x,y:values.y,marker:{size:5,color:colors[0],opacity:.5},
        hovertemplate:'特征值 %{x:.3f}<br>SHAP %{y:.4f}<extra></extra>'}],plotLayout({xaxis:{title:{text:feature},gridcolor:'#DEDDD6'},
        yaxis:{title:{text:'SHAP · 目标单位'},gridcolor:'#DEDDD6'}}),{responsive:true,displaylogo:false});
    };
    $('shapFeature').addEventListener('change',dependence);
    dependence();
  }
  function robustness() {
    return findings('robustness') + section('覆盖样本的分布差异',table(['样本','游戏数','年份中位数','评价数中位数','稀有度中位数','免费比例'],
      report.coverage.map(r=>[esc(r.label),num(r.n),fixed(r.year,0),num(r.reviews),fixed(r.rarity,1),pct(r.free_ratio)])),
      '全量帧已过滤日期和未解决映射；覆盖比较不要求至少5个成就。免费比例仅基于已知is_free；其他中位数按各字段非缺失观测计算。') +
      section('RAWG任务的覆盖来源',table(['任务状态','游戏数'],Object.entries(report.rawg_task_counts).map(([k,v])=>[esc(k),num(v)])),
        '未安排任务主要来自抓取时评价数门槛；任务成功并不保证目标字段有效。未匹配、未安排和状态数据缺失是不同原因。') +
      section('门槛敏感性：改变样本后关联是否保持',table(['最低评价数','最低状态人数','游戏数','Spearman ρ','Ridge OOF R²','RMSE'],
        report.sensitivity.map(r=>[num(r.reviews_min),num(r.states_min),num(r.n),fixed(r.rho),fixed(r.r2),fixed(r.rmse)])),
        '目标始终为dropped/(beaten+dropped)，模型始终为完整结构Ridge；不同门槛对应不同样本。此处没有将其他门槛下的模型表现用作调参选择。') +
      section('分母选择也会改变解释',`<p class="analysis-note">主线比例与 dropped/(owned+playing+beaten+dropped) 在成对可用样本中的 Spearman 相关为 ${fixed(report.denominator_rho)}。后者含拥有状态，不称“实际玩过的人中的弃坑率”；二者均为平台自报状态的条件比例。</p>`) +
      section('成就描述分类抽查',
        '<p class="analysis-note">检查关键词规则有没有明显误判或漏判。例如，“收集全部物品”应归为收集类，“无伤完成关卡”应归为技术挑战类。下面将原始描述与程序判断放在一起，供人工对照；这张表本身不是研究结论。</p>' +
        table(['游戏 / 成就名称','原始描述 / 程序判断'],report.text_examples.slice(0,20).map(r=>[
          `${esc(r.game)}<br>${esc(r.display_name)}`,`${esc(r.description)}<br><span class="analysis-note">程序判断：${esc(r.matches.join('、') || '未命中关键词')}</span>`])),
        '固定抽样：根据游戏编号和成就名称生成稳定的哈希排序，从快照保存的40条中展示前20条；不是按难度或分类是否正确挑选。未命中关键词不代表对应内容不存在。目前没有人工标准答案，也没有计算分类准确率，因此不能凭这张表证明分类可靠。');
  }
  function extensions() {
    const rows = report.models.map(m=> {
      const base=m.metrics.find(r=>r.name==='尾部结构 Ridge');
      const text=m.metrics.find(r=>r.name==='文本规则 Ridge');
      const interaction=m.metrics.find(r=>r.name==='标签交互 Ridge');
      return [esc(m.label),fixed(base.r2),fixed(text.r2),fixed(text.r2-base.r2),fixed(interaction.r2),fixed(interaction.r2-base.r2)];
    });
    return findings('extensions') + section('扩展特征是否提高预测能力',table(['目标','结构R²','加文本R²','文本增量','加交互R²','交互增量'],rows),
      '同样本同五折；很小的增量可能不稳定，不仅凭小数点变化宣称有效。负增量也如实保留。') +
      section('描述关键词规则：匹配与覆盖',table(['类别','有匹配的游戏数','游戏内匹配占比中位数'],report.text_summary.map(r=>[
        esc(r.category),num(r.games_with_match),pct(r.median_share)])),
        `至少5个成就的游戏中，游戏等权的非空描述占比均值为 ${pct(report.description_coverage)}。匹配可多标签，未匹配不等于该内容不存在；规则匹配未作独立精度验证。`) +
      section('固定标签组合的主线样本数',table(['组合','游戏数'],Object.entries(report.models.find(m=>m.target==='drop_ratio').interaction_counts).map(([k,v])=>[esc(k),num(v)])),
        '使用SteamSpy题材标签，组合为Rogue-like×Deckbuilding、Rogue-like×Action、Story Rich×Puzzle；词形经过快照核验，不与Rogue-lite等标签自动合并。') +
      section('这些结果能说明什么',
        '<p class="analysis-note">加入文本类别后的R²增量，表示模型预测是否改善，不表示某种玩法导致玩家更愿意玩。类别仅由关键词判断，可能误判或漏判，尚无人工分类准确率；很小的预测增量也可能不稳定。分类抽查材料见“方法与数据质量”页面。</p>');
  }
  const builders = {overview,structure,types,reputation,models,robustness,extensions};

  function scatter(id, genre, reputationMode = false, intervals = false) {
    if (!window.Plotly) { $(id).innerHTML='<p class="plot-error">图表组件未加载，请查看本页统计表。</p>'; return; }
    const points = report.points.filter(p=>(genre==='全部'||p.genres.includes(genre)) && (!reputationMode || p.approval!=null));
    const x = points.map(p=>reputationMode?p.approval*100:100-p.median_percent);
    const y = points.map(p=>p.drop_ratio*100);
    const sorted = a => [...a].sort((l,r)=>l-r);
    const median = a => a.length?sorted(a)[Math.floor(a.length/2)]:0;
    const mx=median(x), my=median(y);
    const trace = {type:'scatter',mode:'markers',x,y,marker:{size:6,color:colors[0],opacity:.42},
      customdata:points.map(p=>[esc(p.name_zh||p.name_en),p.appid,p.resolved_total,p.ci_low*100,p.ci_high*100]),
      hovertemplate:'%{customdata[0]} · %{customdata[1]}<br>横轴 %{x:.1f}<br>弃坑占比 %{y:.1f}%<br>状态人数 %{customdata[2]}<br>Wilson区间 %{customdata[3]:.1f}–%{customdata[4]:.1f}%<extra></extra>'};
    if(intervals) trace.error_y={type:'data',array:points.map(p=>(p.ci_high-p.drop_ratio)*100),arrayminus:points.map(p=>(p.drop_ratio-p.ci_low)*100),symmetric:false,thickness:.5,color:'#B0AFA9'};
    Plotly.newPlot(id,[trace],plotLayout({xaxis:{title:{text:reputationMode?'Steam 好评率 · %':'成就稀有度 = 100 − 中位完成率'},range:[0,100],gridcolor:'#DEDDD6'},
      yaxis:{title:{text:'弃坑标记占比 · %'},range:[0,100],gridcolor:'#DEDDD6'},
      annotations:[{xref:'paper',yref:'paper',x:1,y:1.08,text:`图示 ${points.length} 款 · ${esc(genre)}`,showarrow:false,xanchor:'right'}],
      shapes:reputationMode?[]:[{type:'line',x0:mx,x1:mx,y0:0,y1:100,line:{color:'#B0AFA9',width:1,dash:'dot'}},
        {type:'line',x0:0,x1:100,y0:my,y1:my,line:{color:'#B0AFA9',width:1,dash:'dot'}}]}),{responsive:true,displaylogo:false});
  }

  async function render(page) {
    const token = ++renderToken;
    if (!pages[page]) page='overview';
    const navLink = ([key,info]) => `<a href="#analysis/${key}" ${key===page?'aria-current="page"':''}><strong>${esc(info[0])}</strong><span>${esc(info[1])}</span></a>`;
    $('analysisNav').innerHTML = '<div class="nav-label">研究分析</div>' + navLink(['overview', pages.overview]) +
      `<details class="research-nav-details" ${page!=='overview'?'open':''}><summary>深入研究 · 方法与专题</summary>${Object.entries(pages).filter(([key])=>key!=='overview').map(navLink).join('')}</details>`;
    if (!report) {
      $('analysisPage').innerHTML='<div class="analysis-status">正在读取固定数据版本的分析报告…</div>';
      try {
        if (!request) request=fetch('/api/analysis').then(async res=>{
          const data=await res.json(); if(!res.ok) throw new Error(data.error||'读取失败'); return data;
        });
        report=await request;
      } catch(error) {
        request=null;
        if(token===renderToken) $('analysisPage').innerHTML=`<div class="analysis-status">${esc(error.message)}<br><button id="retryAnalysis">重新读取报告</button></div>`;
        const retry=$('retryAnalysis'); if(retry) retry.onclick=()=>render(page);
        return;
      }
    }
    if(token!==renderToken) return;
    document.querySelectorAll('.analysis-plot').forEach(node=>{if(window.Plotly)Plotly.purge(node);});
    plotJobs.length=0;
    const info=pages[page];
    $('analysisPage').innerHTML=`<header class="analysis-heading"><div class="eyebrow">STEAM · 游戏级聚合分析</div><h1>${esc(info[0])}</h1><p class="analysis-description">${esc(info[2])}</p></header>`+
      builders[page]()+methods()+`<footer class="analysis-footer">来源：Steam / SteamSpy / <a href="https://rawg.io/" target="_blank" rel="noopener">RAWG</a> · 非商业课程研究 · 模型归因与相关性均非因果效应。<br>固定版本 ${esc(report.metadata.version)} · <a href="/api/analysis" download="analysis-report.json">下载派生分析报告</a></footer>`;
    await renderPlots();
    if(token!==renderToken) return;
    if(page==='structure') {
      const update=()=>scatter('structureScatter',$('structureGenre').value,false,$('showIntervals').checked);
      $('structureGenre').onchange=update; $('showIntervals').onchange=update; update();
    }
    if(page==='reputation') {
      const update=()=>scatter('reputationScatter',$('reputationGenre').value,true);
      $('reputationGenre').onchange=update;update();
    }
    if(page==='models') {
      $('modelTarget').onchange=()=>renderModel($('modelTarget').value);
      renderModel($('modelTarget').value);
    }
    $('analysisPage').querySelectorAll('[data-game]').forEach(button=>button.onclick=()=>{
      const appid=Number(button.dataset.game); $('appidInput').value=appid; switchView('game'); lookup(appid);
    });
  }
  function route() {
    const route=location.hash.slice(1);
    if(['queue','game','cloud'].includes(route)) switchView(route);
    else {
      if(!route.startsWith('analysis/')) history.replaceState(null,'','#analysis/overview');
      switchView('analysis');
    }
  }
  window.Analysis={open() {
    if(!location.hash.startsWith('#analysis/')) { location.hash='analysis/overview'; return; }
    render(location.hash.split('/')[1]||'overview');
  }};
  window.addEventListener('hashchange',route);
  route();
})();
