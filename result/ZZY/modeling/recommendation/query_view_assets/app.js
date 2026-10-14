'use strict';
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let seeds=[],replacing=null,queryGeneration=0,searchGeneration=0,queryController=null,searchController=null;
let busy=false,searchBusy=false,searchDirty=false,searchOffset=0,searchData=null,current=null;
const pageSize=10;
async function getJSON(url,signal){const r=await fetch(url,{signal});const data=await r.json();if(!r.ok)throw new Error(data.error||'读取失败，请重试。');return data;}
function validYears(){const values=[$('yearMin').value,$('yearMax').value];return values.every(v=>v===''||(/^[0-9]{1,4}$/.test(v)&&Number(v)>=1))&&(!values[0]||!values[1]||Number(values[0])<=Number(values[1]));}
function ready(){return seeds.length>0&&validYears()&&!searchDirty&&replacing===null;}
function controls(){$('recommendButton').disabled=busy||!ready();$('cancel').hidden=!busy;$('cancelSearch').hidden=!searchBusy;}
function invalidate(message='选择已改变，请重新查看推荐。'){queryGeneration++;queryController?.abort();queryController=null;busy=false;current=null;$('result').hidden=true;$('error').hidden=true;$('status').textContent=message;controls();}
function resetSearch(message){searchGeneration++;searchController?.abort();searchController=null;searchBusy=false;searchData=null;$('searchResults').replaceChildren();$('pageInfo').textContent='';$('previous').disabled=true;$('next').disabled=true;$('searchError').hidden=true;if(message)$('searchStatus').textContent=message;controls();}
function renderSeeds(){
  $('seedCount').textContent=`${seeds.length} / 3`;$('seeds').replaceChildren();
  seeds.forEach((game,index)=>{const card=el('div',undefined,'seed-card');card.append(el('strong',game.name),el('small',`${game.appid} · ${game.release_year??'年份未知'}`));
    const replace=el('button',replacing===index?'正在替换此游戏':'替换','secondary');replace.type='button';replace.setAttribute('aria-label',`替换 ${game.name}`);
    replace.addEventListener('click',()=>{replacing=index;invalidate();renderSeeds();$('searchText').focus();});
    const remove=el('button','移除','secondary');remove.type='button';remove.setAttribute('aria-label',`移除 ${game.name}`);
    remove.addEventListener('click',()=>{seeds.splice(index,1);replacing=null;invalidate();renderSeeds();});card.append(replace,remove);$('seeds').append(card);
  });
  $('cancelReplace').hidden=replacing===null;$('selectionStatus').textContent=replacing!==null?`正在替换 ${seeds[replacing].name}，请从搜索结果选择另一款。`:seeds.length?`已选择 ${seeds.length} 款，${seeds.length===1?'按单游戏评分。':'各种子等权平均。'}`:'请添加至少一款游戏。';
  if(searchData)renderSearch();controls();
}
function choose(game){
  if(!game.recommendation_eligible||seeds.some(s=>s.appid===game.appid))return;
  if(replacing!==null){seeds[replacing]=game;replacing=null;}else if(seeds.length<3)seeds.push(game);else return;
  searchDirty=false;invalidate();renderSeeds();
}
function renderSearch(){
  $('searchResults').replaceChildren();
  for(const game of searchData.results){const row=el('article',undefined,'search-row');row.append(el('strong',game.name),el('small',`${game.appid} · ${game.release_year??'年份未知'} · 英文名：${game.name_en||'缺失'}`));
    if(!game.recommendation_eligible)row.append(el('p',`不能作为种子：${game.ineligible_reasons.map(r=>r.message).join(' ')}`,'notice'));
    const chosen=seeds.some(s=>s.appid===game.appid),full=seeds.length>=3&&replacing===null;
    const button=el('button',!game.recommendation_eligible?'不满足推荐条件':chosen?'已选择':full?'已选满3款':replacing!==null?'替换为这款':'添加为种子');button.type='button';button.disabled=!game.recommendation_eligible||chosen||full;
    button.setAttribute('aria-label',`${button.textContent} ${game.name}`);button.addEventListener('click',()=>choose(game));row.append(button);$('searchResults').append(row);
  }
  const {total_matches:total,offset,results}=searchData;
  $('pageInfo').textContent=total?`${offset+1}–${offset+results.length} / ${total} 款`:'0 款';
  $('previous').disabled=offset===0;$('next').disabled=offset+results.length>=total;
}
async function search(offset=0){
  resetSearch();const token=searchGeneration;searchOffset=offset;const aborter=new AbortController();searchController=aborter;searchBusy=true;controls();$('searchStatus').textContent='正在搜索完整快照…';
  try{const params=new URLSearchParams({q:$('searchText').value,limit:pageSize,offset});const data=await getJSON(`/api/search?${params}`,aborter.signal);if(token!==searchGeneration)return;
    searchData=data;searchDirty=false;renderSearch();$('searchStatus').textContent=`完整快照 ${data.snapshot_games.toLocaleString('zh-CN')} 款，命中 ${data.total_matches.toLocaleString('zh-CN')} 款。${data.results.length?'请选择要加入的游戏。':'没有匹配游戏，请更换搜索词。'}`;
  }catch(e){if(token!==searchGeneration||e.name==='AbortError')return;$('searchErrorText').textContent=e.message;$('searchError').hidden=false;$('searchStatus').textContent='搜索失败，可重试当前搜索。';
  }finally{if(token===searchGeneration){searchBusy=false;searchController=null;controls();}}
}
async function recommend(){
  if(!ready())return;invalidate();const token=queryGeneration;const aborter=new AbortController();queryController=aborter;busy=true;controls();$('status').textContent='正在筛选年份、计算排名并回查完整来源…';
  const params=new URLSearchParams({appids:seeds.map(s=>s.appid).join(','),top_k:$('topK').value,path_limit:'all'});
  if($('yearMin').value)params.set('year_min',$('yearMin').value);if($('yearMax').value)params.set('year_max',$('yearMax').value);
  try{const data=await getJSON(`/api/recommend?${params}`,aborter.signal);if(token!==queryGeneration)return;
    if(!data.ranking.results.length){current=null;const reasons=data.ranking.seed_checks.filter(s=>!s.recommendation_eligible).map(s=>`${s.name}：${s.ineligible_reasons.map(r=>r.message).join(' ')}`).join(' ');$('status').textContent=[data.ranking.empty_reason,reasons].filter(Boolean).join(' ');return;}
    current=data;QueryRenderer.show(data);$('result').hidden=false;$('status').textContent=`已返回 ${data.ranking.results.length} 款；先筛年份再评分，已排除全部种子。点击路径查看每款种子的贡献与原始来源。`;
  }catch(e){if(token!==queryGeneration||e.name==='AbortError')return;current=null;$('result').hidden=true;$('errorText').textContent=e.message;$('error').hidden=false;$('status').textContent='查询失败，可重试当前选择。';
  }finally{if(token===queryGeneration){busy=false;queryController=null;controls();}}
}
async function loadMeta(){try{const data=await getJSON('/api/meta');$('version').textContent=JSON.stringify(data,null,2);if(searchGeneration===0)$('searchStatus').textContent=`完整快照 ${data.snapshot_games.toLocaleString('zh-CN')} 款；其中 ${data.candidate_games.toLocaleString('zh-CN')} 款满足推荐条件。`;}catch(e){$('version').textContent='版本暂时不可用，请重新加载页面重试。';}}
$('searchForm').addEventListener('submit',e=>{e.preventDefault();search(0);});
$('searchText').addEventListener('input',()=>{searchDirty=true;resetSearch('搜索词已改变，请重新搜索。');invalidate('搜索输入已改变，请完成搜索和选择后重新推荐。');});
$('cancelSearch').addEventListener('click',()=>resetSearch('搜索已取消。'));
$('retrySearch').addEventListener('click',()=>search(searchOffset));$('previous').addEventListener('click',()=>search(Math.max(0,searchOffset-pageSize)));$('next').addEventListener('click',()=>search(searchOffset+pageSize));
$('cancelReplace').addEventListener('click',()=>{replacing=null;invalidate();renderSeeds();});
$('queryForm').addEventListener('submit',e=>{e.preventDefault();recommend();});
for(const id of ['yearMin','yearMax'])$(id).addEventListener('input',()=>invalidate(validYears()?'年份已改变，请重新查看推荐。':'年份须为1–9999，且起始年份不能晚于结束年份。'));
$('topK').addEventListener('change',()=>invalidate());$('retry').addEventListener('click',recommend);$('cancel').addEventListener('click',()=>invalidate('查询已取消。'));
$('clearYears').addEventListener('click',()=>{$('yearMin').value='';$('yearMax').value='';invalidate('年份已清除，请重新推荐。');});
$('clear').addEventListener('click',()=>{seeds=[];replacing=null;searchDirty=false;$('searchText').value='';$('yearMin').value='';$('yearMax').value='';resetSearch('已清空搜索。');invalidate('已清空全部，请重新选择游戏。');renderSeeds();$('searchText').focus();});
$('pathLimit').addEventListener('change',()=>QueryRenderer.draw());window.addEventListener('resize',()=>{if(current)QueryRenderer.draw();});renderSeeds();loadMeta();
