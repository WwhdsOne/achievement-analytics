'use strict';
const QueryRenderer=(()=>{
  const $=id=>document.getElementById(id),fields={tags:'主题标签',genres:'官方类型',developers:'开发商',publishers:'发行商'},score=n=>Number(n).toFixed(8);
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  let current=null,index=0,key=null;
  const seedName=appid=>current.query_games.find(s=>s.appid===appid)?.name||String(appid);
  const selection=()=>({result:current.ranking.results[index],display:current.explanations[index]});
  function show(data){current=data;index=0;key=null;$('queryTitle').textContent=data.query_games.map(s=>`${s.name} · ${s.appid}`).join(' ＋ ');
    const r=data.ranking;$('reference').textContent=`年份 ${r.filters.year_min??'不限'}–${r.filters.year_max??'不限'} · 筛后 ${r.filtered_candidate_games.toLocaleString('zh-CN')} 款 · IDF参考库 ${r.idf_reference_games.toLocaleString('zh-CN')} 款（排除全部种子）`;
    $('rawReport').textContent=JSON.stringify(r,null,2);$('ranking').replaceChildren();r.results.forEach((item,i)=>{const b=el('button',undefined,'candidate');b.type='button';b.append(el('span',`${i+1}. ${item.name}`),el('span',`${item.release_year}年 · ${item.appid} · 分数 ${score(item.score)}`,'rank-score'));b.addEventListener('click',()=>{index=i;key=null;renderCandidate();});$('ranking').append(b);});
    profile(r.preference_profile);renderCandidate();
  }
  function profile(data){$('profile').hidden=!data;$('profileBody').replaceChildren();if(!data)return;
    for(const [field,r] of Object.entries(data.relations)){const box=el('section');box.append(el('h3',fields[field]),el('p',`全部种子共同：${r.common_all.map(e=>e.name).join('、')||'无'}`),el('p',`部分种子共同：${r.common_some.map(e=>`${e.name}（${e.seed_appids.map(seedName).join('、')}）`).join('、')||'无'}`));
      for(const [seed,entities] of Object.entries(r.unique_by_seed))box.append(el('p',`${seedName(Number(seed))} 特有：${entities.map(e=>e.name).join('、')||'无'}`));
      if(r.missing_seed_appids.length)box.append(el('p',`证据不足：${r.missing_seed_appids.map(seedName).join('、')}`));$('profileBody').append(box);
    }
    $('profileBody').append(el('h3','潜在取舍（不扣分）'));for(const item of data.potential_tradeoffs)$('profileBody').append(el('p',`${item.seed_appids.map(seedName).join(' / ')} · ${fields[item.field]}：${item.reason}`));if(!data.potential_tradeoffs.length)$('profileBody').append(el('p','没有命中当前潜在取舍规则。'));$('profileBody').append(el('p',data.evidence_note,'subtle'));
  }
  function renderCandidate(){const {result,display}=selection();Array.from($('ranking').children).forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));$('candidateTitle').textContent=result.name;$('totalScore').textContent=`总分 ${score(result.score)}`;$('evidenceNote').textContent=result.evidence_note;
    $('seedContributions').replaceChildren();const parts=result.seed_contributions||[{appid:current.query_games[0].appid,score:result.score,weight:1,contribution:result.score}];for(const s of parts)$('seedContributions').append(el('p',`${seedName(s.appid)} (${s.appid})：原分 ${score(s.score)} × 种子权重 ${s.weight} = 联合贡献 ${score(s.contribution)}${s.score===0?'，零分份额仍保留。':''}`));
    $('relations').replaceChildren();for(const r of display.relations){const tr=el('tr'),title=el('td',`${seedName(r.seed_appid)} / ${fields[r.field]}`,r.field),amount=el('td',`${r.weight} / ${score(r.score)}`);amount.append(el('small',`种子权重 ${r.seed_weight}；分子 ${score(r.numerator)} / 分母 ${score(r.denominator)}`));const state=el('td',r.status_note);state.append(el('small',`共同路径 ${r.path_count} 条`));const unique=el('td');unique.append(el('span',`仅种子：${r.query_only_entities.map(e=>e.name).join('、')||'无'}`),el('small',`仅候选：${r.candidate_only_entities.map(e=>e.name).join('、')||'无'}`));tr.append(title,amount,state,unique);$('relations').append(tr);}
    $('paths').replaceChildren();for(const p of display.path_catalog){const b=el('button',undefined,`path ${p.field}`);b.type='button';b.dataset.key=p.key;b.append(el('span',`${seedName(p.seed_appid)} · ${fields[p.field]} · ${p.name}`),el('small',`联合贡献 ${score(p.contribution)}${p.used_for_score?'':' · 共享事实，不计分'}`));b.addEventListener('click',()=>selectPath(p.key));$('paths').append(b);}
    if(display.path_catalog.length)selectPath(display.path_catalog[0].key);else{$('pathDetail').hidden=true;draw();}
  }
  function selectPath(nextKey){key=nextKey;const {result,display}=selection(),ref=display.path_catalog.find(p=>p.key===key);if(!ref)return;
    const relations=result.seed_contributions?result.seed_contributions.find(s=>s.appid===ref.seed_appid).relations:result.relations,component=relations[ref.field],path=component.paths[ref.path_index];
    $('pathDetail').hidden=false;$('selectedPath').textContent=`${fields[ref.field]}：${seedName(ref.seed_appid)} (${ref.seed_appid}) → ${ref.name} ← ${result.name} (${result.appid})`;
    $('pathFormula').textContent=`联合贡献 ${score(ref.contribution)} = 关系权重 ${path.relation_weight} × IDF ${score(path.idf)} ÷ 并集IDF和 ${score(component.denominator)} × 种子权重 ${path.seed_weight??1}。原路径贡献 ${score(ref.raw_contribution)}，df=${path.document_frequency}${ref.used_for_score?'。':'；权重0，只显示共享事实，不计分。'}`;
    $('proofs').replaceChildren();for(const [side,label] of [['left_edge','种子端原始事实'],['right_edge','候选端原始事实']]){const edge=path[side],d=el('details');d.append(el('summary',`${label} · ${edge.predicate} · ${edge.evidence.length}项原始证据`),el('pre',JSON.stringify(edge,null,2)));$('proofs').append(d);}for(const b of $('paths').children)b.setAttribute('aria-pressed',String(b.dataset.key===key));draw();
  }
  function svgEl(tag,attrs,text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
  function draw(){if(!current||$('result').hidden&&!current.ranking.results.length)return;const {result,display}=selection();
    const focusKey=document.activeElement?.closest('#graph')?document.activeElement.getAttribute('data-path-key'):null;
    const limit=$('pathLimit').value==='all'?Infinity:Number($('pathLimit').value),shown=display.path_catalog.slice(0,limit),hidden=display.path_catalog.slice(shown.length),sum=ps=>ps.reduce((n,p)=>n+p.contribution,0);
    $('clipSummary').textContent=`图中 ${shown.length} / 全部 ${display.total_paths} 条路径；显示贡献 ${score(sum(shown))} + 未显示贡献 ${score(sum(hidden))} = 总分 ${score(result.score)}。裁剪不改变排名与分数。${hidden.some(p=>p.key===key)?' 所选路径在裁剪之外，完整证据仍可查。':''}`;
    const compact=window.innerWidth<700,width=compact?420:900,row=compact?160:90,height=Math.max(row,shown.length*row);
    const svg=svgEl('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':'各具体种子与候选指向共同实体的事实路径'}),defs=svgEl('defs'),marker=svgEl('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});marker.append(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#94b7bb'}));defs.append(marker);svg.append(defs);
    shown.forEach((p,i)=>{const offset=i*row,gy=offset+(compact?32:44),ey=offset+(compact?112:44),cx=compact?210:450,ex=compact?320:780;
      for(const [x,name,appid] of [[compact?100:120,seedName(p.seed_appid),p.seed_appid],[ex,result.name,result.appid]]){svg.append(svgEl('rect',{x:x-86,y:gy-24,width:172,height:48,rx:8,class:'game-node'}));const t=svgEl('text',{x,y:gy-3,'text-anchor':'middle'},String(name).slice(0,compact?10:13));t.append(svgEl('title',{},name));svg.append(t,svgEl('text',{x,y:gy+14,'text-anchor':'middle',class:'contribution'},`${appid===p.seed_appid?'种子':'候选'} ${appid}`));}
      for(let side=0;side<2;side++){const attrs={'marker-end':'url(#arrow)',class:`fact-edge${p.used_for_score?'':' zero'}`,'data-seed-appid':p.seed_appid,'data-path-key':p.key};if(compact){const x=side?320:100,bus=side?395:25,target=side?350:70;svg.append(svgEl('polyline',{...attrs,points:`${x},${gy+24} ${bus},${gy+40} ${bus},${ey} ${target},${ey}`,fill:'none'}));}else svg.append(svgEl('line',{...attrs,x1:side?694:206,y1:gy,x2:side?560:340,y2:ey}));}
      const node=svgEl('g',{class:`${p.field}${p.key===key?' selected':''}`,role:'button',tabindex:0,'aria-label':`${seedName(p.seed_appid)} ${fields[p.field]} ${p.name} 联合贡献 ${score(p.contribution)}`,'data-path-key':p.key,'data-seed-appid':p.seed_appid}),w=compact?280:220;
      node.append(svgEl('rect',{x:cx-w/2,y:ey-22,width:w,height:44,rx:8}),svgEl('text',{x:cx,y:ey-3,'text-anchor':'middle'},`${fields[p.field]} · ${String(p.name).slice(0,15)}`),svgEl('text',{x:cx,y:ey+14,'text-anchor':'middle',class:'contribution'},`联合贡献 ${score(p.contribution)}${p.used_for_score?'':' · 不计分'}`),svgEl('title',{},`${seedName(p.seed_appid)} → ${p.name} ← ${result.name}`));node.addEventListener('click',()=>selectPath(p.key));node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectPath(p.key);}});svg.append(node);
    });$('graph').replaceChildren(svg);if(focusKey)Array.from(svg.querySelectorAll('g[role=button]')).find(n=>n.getAttribute('data-path-key')===focusKey)?.focus({preventScroll:true});
  }
  return {show,draw};
})();
