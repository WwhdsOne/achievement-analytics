'use strict';
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const fields={tags:'主题标签',genres:'官方类型',developers:'开发商',publishers:'发行商'};
const score=n=>Number(n).toFixed(8);
let generation=0,controller=null,current=null,candidateIndex=0,selectedKey=null;
function valid(){return /^[0-9]{1,10}$/.test($('appid').value)&&Number($('appid').value)>0;}
function invalidate(){generation++;if(controller)controller.abort();current=null;$('result').hidden=true;$('error').hidden=true;$('status').textContent='输入已改变，请重新查看推荐。';$('recommendButton').disabled=!valid();}
async function getJSON(url,signal){const r=await fetch(url,{signal});const data=await r.json();if(!r.ok)throw new Error(data.error||'读取失败，请重试。');return data;}
async function loadMeta(){try{const meta=await getJSON('api/meta');$('version').textContent=JSON.stringify(meta,null,2);if(!current&&generation===0)$('status').textContent=`已验证固定图谱，${meta.candidate_games.toLocaleString('zh-CN')}款推荐候选。`;}catch(e){$('version').textContent='版本信息暂时不可用，重新加载页面可重试。';}}
async function recommend(){if(!valid())return;generation++;const requestId=generation;if(controller)controller.abort();controller=new AbortController();const aborter=controller;current=null;$('result').hidden=true;$('error').hidden=true;$('recommendButton').disabled=true;$('status').textContent='正在计算真实图谱排名并回查来源…';try{const data=await getJSON(`api/recommend?appid=${encodeURIComponent($('appid').value)}&top_k=${$('topK').value}`,aborter.signal);if(requestId!==generation)return;current=data;candidateIndex=0;selectedKey=null;if(!data.ranking.results.length){$('status').textContent=data.ranking.empty_reason||'没有正贡献候选。';return;}$('queryTitle').textContent=`${data.query_game.name} · ${data.query_game.appid}`;$('reference').textContent=`IDF参考库 ${data.ranking.idf_reference_games.toLocaleString('zh-CN')} 款，已排除种子`;$('ranking').replaceChildren();data.ranking.results.forEach((r,i)=>{const b=el('button',undefined,'candidate');b.type='button';b.append(el('span',`${i+1}. ${r.name}`),el('span',`${r.appid} · 分数 ${score(r.score)}`,'rank-score'));b.addEventListener('click',()=>{candidateIndex=i;selectedKey=null;renderCandidate();});$('ranking').append(b);});$('result').hidden=false;renderCandidate();const active=Object.entries(data.ranking.binding.weights).filter(([,weight])=>weight>0).map(([field])=>fields[field]).join('、');$('status').textContent=`当前排名正权重关系：${active}。点击路径查看精确贡献和完整事实来源。`;}catch(e){if(requestId!==generation||e.name==='AbortError')return;$('errorText').textContent=e.message;$('error').hidden=false;$('status').textContent='查询失败，原结果已清除。';}finally{if(requestId===generation)$('recommendButton').disabled=!valid();}}
function selection(){return {result:current.ranking.results[candidateIndex],display:current.explanations[candidateIndex]};}
function rawPath(ref){const {result}=selection();const relations=result.seed_contributions?result.seed_contributions.find(s=>s.appid===ref.seed_appid).relations:result.relations;return {path:relations[ref.field].paths[ref.path_index],component:relations[ref.field]};}
function renderCandidate(){const {result,display}=selection();Array.from($('ranking').children).forEach((n,i)=>n.setAttribute('aria-pressed',String(i===candidateIndex)));$('candidateTitle').textContent=result.name;$('totalScore').textContent=`总分 ${score(result.score)}`;$('evidenceNote').textContent=result.evidence_note;$('relations').replaceChildren();for(const r of display.relations){const tr=el('tr');const title=el('td',fields[r.field]);title.className=r.field;const amount=el('td',`${r.weight} / ${score(r.score)}`);amount.append(el('small',`分子 ${score(r.numerator)} / 分母 ${score(r.denominator)}`));const state=el('td',r.status_note);state.append(el('small',`共同路径 ${r.path_count} 条`));const unique=el('td');unique.append(el('span',`仅种子：${r.query_only_entities.map(e=>e.name).join('、')||'无'}`),el('small',`仅候选：${r.candidate_only_entities.map(e=>e.name).join('、')||'无'}`));tr.append(title,amount,state,unique);$('relations').append(tr);}$('paths').replaceChildren();for(const p of display.path_catalog){const b=el('button',undefined,`path ${p.field}`);b.type='button';b.dataset.key=p.key;b.append(el('span',`${fields[p.field]} · ${p.name}`),el('small',`贡献 ${score(p.contribution)}${p.used_for_score?'':' · 共享事实，不计分'}`));b.addEventListener('click',()=>selectPath(p.key));$('paths').append(b);}if(display.path_catalog.length){selectedKey=selectedKey&&display.path_catalog.some(p=>p.key===selectedKey)?selectedKey:display.path_catalog[0].key;selectPath(selectedKey);}else{$('pathDetail').hidden=true;drawGraph();}}
function selectPath(key){selectedKey=key;const {display}=selection();const ref=display.path_catalog.find(p=>p.key===key);if(!ref)return;const {path,component}=rawPath(ref);$('pathDetail').hidden=false;$('selectedPath').textContent=`${fields[ref.field]}：${current.query_game.name} → ${ref.name} ← ${selection().result.name}`;$('pathFormula').textContent=`本路径贡献 ${score(ref.contribution)} = 关系权重 ${path.relation_weight} × IDF ${score(path.idf)} ÷ 并集IDF和 ${score(component.denominator)}${path.seed_weight!==undefined?` × 种子权重 ${path.seed_weight}`:''}。df=${path.document_frequency}${ref.used_for_score?'，参与当前总分。':'；权重为0，只显示共享事实，不计分。'}`;$('proofs').replaceChildren();for(const [side,label] of [['left_edge','种子端原始事实'],['right_edge','候选端原始事实']]){const edge=path[side],details=el('details');details.append(el('summary',`${label} · ${edge.predicate} · ${edge.evidence.length}项原始证据`),el('pre',JSON.stringify(edge,null,2)));$('proofs').append(details);}for(const b of $('paths').children)b.setAttribute('aria-pressed',String(b.dataset.key===key));drawGraph();}
function svgEl(tag,attrs,text){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs||{}))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;}
function drawGraph(){
  if(!current)return;
  const focusKey=document.activeElement?.closest('#graph')?document.activeElement.getAttribute('data-path-key'):null;
  const {result,display}=selection();
  const limit=$('pathLimit').value==='all'?Infinity:Number($('pathLimit').value);
  const shown=display.path_catalog.slice(0,limit),hidden=display.path_catalog.slice(shown.length);
  const sum=paths=>paths.reduce((n,p)=>n+p.contribution,0);
  $('clipSummary').textContent=`图中 ${shown.length} / 全部 ${display.total_paths} 条路径；显示贡献 ${score(sum(shown))} + 未显示贡献 ${score(sum(hidden))} = 总分 ${score(result.score)}。裁剪不改变排名与分数。${hidden.some(p=>p.key===selectedKey)?' 所选路径在裁剪之外，可选择全部路径显示。':''}`;
  const compact=window.innerWidth<700,width=compact?420:900;
  const height=compact?Math.max(215,shown.length*68+135):Math.max(160,shown.length*64+45);
  const center=compact?45:height/2,entityX=compact?210:450;
  const svg=svgEl('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':'游戏指向共享关系实体的事实路径'});
  const defs=svgEl('defs'),marker=svgEl('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});
  marker.append(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#94b7bb'}));defs.append(marker);svg.append(defs);
  for(const [x,name] of [[100,current.query_game.name],[compact?320:800,result.name]]){
    svg.append(svgEl('rect',{x:x-90,y:center-30,width:180,height:60,rx:10,class:'game-node'}));
    const text=svgEl('text',{x,y:center+4,'text-anchor':'middle'},String(name).slice(0,compact?9:13));
    text.append(svgEl('title',{},String(name)));svg.append(text);
  }
  shown.forEach((p,i)=>{
    const y=compact?145+i*68:45+i*64;
    const endpoints=compact?[[100,140],[320,280]]:[[190,340],[710,560]];
    for(const [side,[x1,x2]] of endpoints.entries()){
      const attrs={'marker-end':'url(#arrow)',class:`fact-edge${p.used_for_score?'':' zero'}`,'data-path-key':p.key};
      if(compact){const bus=side===0?30:390,target=side===0?70:350;svg.append(svgEl('polyline',{...attrs,points:`${x1},75 ${bus},96 ${bus},${y} ${target},${y}`,fill:'none'}));}
      else svg.append(svgEl('line',{...attrs,x1,y1:center,x2,y2:y}));
    }
    const node=svgEl('g',{class:`${p.field}${p.key===selectedKey?' selected':''}`,role:'button',tabindex:0,'aria-label':`${fields[p.field]} ${p.name} 贡献 ${score(p.contribution)}`,'data-path-key':p.key});
    const nodeWidth=compact?280:220;
    node.append(svgEl('rect',{x:entityX-nodeWidth/2,y:y-21,width:nodeWidth,height:42,rx:8}),svgEl('text',{x:entityX,y:y-3,'text-anchor':'middle'},`${fields[p.field]} · ${String(p.name).slice(0,15)}`),svgEl('text',{x:entityX,y:y+13,'text-anchor':'middle',class:'contribution'},`贡献 ${score(p.contribution)}${p.used_for_score?'':' · 不计分'}`),svgEl('title',{},`${p.name} · ${p.predicate}`));
    node.addEventListener('click',()=>selectPath(p.key));node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectPath(p.key);}});svg.append(node);
  });
  $('graph').replaceChildren(svg);
  if(focusKey)Array.from(svg.querySelectorAll('g[role=button]')).find(n=>n.getAttribute('data-path-key')===focusKey)?.focus({preventScroll:true});
}
$('queryForm').addEventListener('submit',e=>{e.preventDefault();recommend();});$('appid').addEventListener('input',invalidate);$('topK').addEventListener('change',invalidate);$('clear').addEventListener('click',()=>{$('appid').value='';invalidate();$('status').textContent='已清空，请输入新的游戏appid。';$('appid').focus();});$('retry').addEventListener('click',recommend);$('pathLimit').addEventListener('change',drawGraph);loadMeta();
