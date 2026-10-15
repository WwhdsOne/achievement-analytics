'use strict';
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let seeds=[],replacing=null,queryGeneration=0,searchGeneration=0,queryController=null,searchController=null;
let busy=false,searchBusy=false,searchDirty=false,searchOffset=0,searchData=null,current=null;
let searchTimer=null,composing=false;
const pageSize=10;
async function getJSON(url,signal){const r=await fetch(url,{signal});const data=await r.json();if(!r.ok)throw new Error(data.error||'读取失败，请重试。');return data;}
function validYears(){const values=[$('yearMin').value,$('yearMax').value];return values.every(v=>v===''||(/^[0-9]{1,4}$/.test(v)&&Number(v)>=1))&&(!values[0]||!values[1]||Number(values[0])<=Number(values[1]));}
function ready(){return seeds.length>0&&validYears()&&!searchDirty&&replacing===null;}
function controls(){$('recommendButton').disabled=busy||!ready();$('cancel').hidden=!busy;$('cancelSearch').hidden=!searchBusy;}
function invalidate(message='选择已改变，请重新查看推荐。'){queryGeneration++;CommentaryPanel.reset();queryController?.abort();queryController=null;busy=false;current=null;$('result').hidden=true;$('error').hidden=true;$('status').textContent=message;controls();}
function resetSearch(message){clearTimeout(searchTimer);searchTimer=null;searchGeneration++;searchController?.abort();searchController=null;searchBusy=false;searchData=null;$('searchResults').replaceChildren();$('pageInfo').textContent='';$('previous').disabled=true;$('next').disabled=true;$('searchError').hidden=true;if(message)$('searchStatus').textContent=message;controls();}
function renderSeeds(){
  $('seedCount').textContent=`${seeds.length} / 3`;$('seeds').replaceChildren();
  seeds.forEach((game,index)=>{const card=el('div',undefined,'seed-card');card.append(el('strong',DiscoveryPresentation.title(game)));const original=DiscoveryPresentation.english(game);if(original&&original!==DiscoveryPresentation.title(game))card.append(el('small',original,'seed-original'));
    const replace=el('button',replacing===index?'正在替换此游戏':'替换','secondary');replace.type='button';replace.setAttribute('aria-label',`替换 ${game.name}`);
    replace.addEventListener('click',()=>{replacing=index;invalidate();renderSeeds();$('searchText').focus();});
    const remove=el('button','移除','secondary');remove.type='button';remove.setAttribute('aria-label',`移除 ${game.name}`);
    remove.addEventListener('click',()=>{seeds.splice(index,1);replacing=null;invalidate();renderSeeds();});card.append(replace,remove);$('seeds').append(card);
  });
  $('cancelReplace').hidden=replacing===null;$('selectionStatus').textContent=replacing!==null?`正在替换 ${seeds[replacing].name}，请从搜索结果选择另一款。`:seeds.length?`已选择 ${seeds.length} 款，${seeds.length===1?'开始找相似游戏吧。':'将结合这些游戏一起寻找。'}`:'请添加至少一款游戏。';
  if(searchData)renderSearch();controls();
}
function choose(game){
  if(!game.recommendation_eligible||seeds.some(s=>s.appid===game.appid))return;
  if(replacing!==null){seeds[replacing]=game;replacing=null;}else if(seeds.length<3)seeds.push(game);else return;
  searchDirty=false;$('searchText').value='';resetSearch('已加入喜欢的游戏。还可以继续搜索其他游戏。');invalidate();renderSeeds();$('searchText').focus();
}
function renderSearch(){
  $('searchResults').replaceChildren();
  for(const game of searchData.results){const row=el('article',undefined,'search-row');row.append(el('strong',DiscoveryPresentation.title(game)),el('small',`${game.release_year??'年份未知'}${game.release_year?' 年发售':''} · ${DiscoveryPresentation.english(game)}`));
    if(!game.recommendation_eligible)row.append(el('p',`暂不能用于推荐：${game.ineligible_reasons.map(r=>r.message).join(' ')}`,'notice'));
    const chosen=seeds.some(s=>s.appid===game.appid),full=seeds.length>=3&&replacing===null;
    const button=el('button',!game.recommendation_eligible?'资料不足':chosen?'已选择':full?'已选满3款':replacing!==null?'替换为这款':'加入喜欢');button.type='button';button.disabled=!game.recommendation_eligible||chosen||full;
    button.setAttribute('aria-label',`${button.textContent} ${DiscoveryPresentation.title(game)}`);button.addEventListener('click',()=>choose(game));row.append(button);$('searchResults').append(row);
  }
  const {total_matches:total,offset,results}=searchData;
  $('pageInfo').textContent=total?`${offset+1}–${offset+results.length} / ${total} 款`:'0 款';
  $('previous').disabled=offset===0;$('next').disabled=offset+results.length>=total;
}
async function search(offset=0){
  resetSearch();const token=searchGeneration;searchOffset=offset;const aborter=new AbortController();searchController=aborter;searchBusy=true;controls();$('searchStatus').textContent='正在找这款游戏…';
  try{const params=new URLSearchParams({q:$('searchText').value,limit:pageSize,offset});const data=await getJSON(`/api/search?${params}`,aborter.signal);if(token!==searchGeneration)return;
    searchData=data;searchDirty=false;renderSearch();$('searchStatus').textContent=`找到 ${data.total_matches.toLocaleString('zh-CN')} 款游戏。${data.results.length?'请选择要加入的游戏。':'没有匹配游戏，请更换搜索词。'}`;
  }catch(e){if(token!==searchGeneration||e.name==='AbortError')return;$('searchErrorText').textContent=e.message;$('searchError').hidden=false;$('searchStatus').textContent='搜索失败，可重试当前搜索。';
  }finally{if(token===searchGeneration){searchBusy=false;searchController=null;controls();}}
}
async function recommend(){
  if(!ready())return;invalidate();const token=queryGeneration;const aborter=new AbortController();queryController=aborter;busy=true;controls();$('status').textContent='正在寻找你的下一款游戏…';
  const params=new URLSearchParams({appids:seeds.map(s=>s.appid).join(','),top_k:$('topK').value,path_limit:'all'});
  if($('yearMin').value)params.set('year_min',$('yearMin').value);if($('yearMax').value)params.set('year_max',$('yearMax').value);
  try{const data=await getJSON(`/api/recommend?${params}`,aborter.signal);if(token!==queryGeneration)return;
    if(!data.ranking.results.length){current=null;const reasons=data.ranking.seed_checks.filter(s=>!s.recommendation_eligible).map(s=>`${s.name}：${s.ineligible_reasons.map(r=>r.message).join(' ')}`).join(' ');$('status').textContent=[data.ranking.empty_reason,reasons].filter(Boolean).join(' ');return;}
    current=data;QueryRenderer.show(data);$('result').hidden=false;$('status').textContent=`为你找到 ${data.ranking.results.length} 款游戏。点开“为什么推荐”，了解它与你的选择有什么联系。`;$('result').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
  }catch(e){if(token!==queryGeneration||e.name==='AbortError')return;current=null;$('result').hidden=true;$('errorText').textContent=e.message;$('error').hidden=false;$('status').textContent='查询失败，可重试当前选择。';
  }finally{if(token===queryGeneration){busy=false;queryController=null;controls();}}
}
async function loadMeta(){try{const data=await getJSON('/api/meta');$('version').textContent=JSON.stringify(data,null,2);CommentaryPanel.configure(data.commentary);if(searchGeneration===0)$('searchStatus').textContent=`试试中文名、英文名或常用简称。`;}catch(e){$('version').textContent='版本暂时不可用，请重新加载页面重试。';}}
function scheduleSearch(){const hasText=Boolean($('searchText').value.trim());searchDirty=hasText;resetSearch(hasText?'正在准备搜索…':'输入游戏名即可搜索。');invalidate(hasText?'正在查找游戏，请从候选中选择。':'可以继续添加游戏，或直接查看推荐。');if(hasText&&!composing)searchTimer=setTimeout(()=>search(0),300);}
$('searchForm').addEventListener('submit',e=>{e.preventDefault();if(!composing)search(0);});
$('searchText').addEventListener('input',scheduleSearch);
$('searchText').addEventListener('compositionstart',()=>{composing=true;resetSearch('输入中文名称后自动搜索。');});
$('searchText').addEventListener('compositionend',()=>{composing=false;scheduleSearch();});
$('cancelSearch').addEventListener('click',()=>resetSearch('搜索已取消。'));
$('retrySearch').addEventListener('click',()=>search(searchOffset));$('previous').addEventListener('click',()=>search(Math.max(0,searchOffset-pageSize)));$('next').addEventListener('click',()=>search(searchOffset+pageSize));
$('cancelReplace').addEventListener('click',()=>{replacing=null;searchDirty=false;$('searchText').value='';resetSearch('已取消替换。');invalidate();renderSeeds();});
$('queryForm').addEventListener('submit',e=>{e.preventDefault();recommend();});
for(const id of ['yearMin','yearMax'])$(id).addEventListener('input',()=>invalidate(validYears()?'年份已改变，请重新查看推荐。':'年份须为1–9999，且起始年份不能晚于结束年份。'));
$('topK').addEventListener('change',()=>invalidate());$('retry').addEventListener('click',recommend);$('cancel').addEventListener('click',()=>invalidate('查询已取消。'));
$('clearYears').addEventListener('click',()=>{$('yearMin').value='';$('yearMax').value='';invalidate('年份已清除，请重新推荐。');});
$('clear').addEventListener('click',()=>{seeds=[];replacing=null;searchDirty=false;$('searchText').value='';$('yearMin').value='';$('yearMax').value='';resetSearch('已清空搜索。');invalidate('已清空全部，请重新选择游戏。');renderSeeds();$('searchText').focus();});
$('pathLimit').addEventListener('change',()=>QueryRenderer.draw());window.addEventListener('resize',()=>{if(current)QueryRenderer.draw();});renderSeeds();loadMeta();
