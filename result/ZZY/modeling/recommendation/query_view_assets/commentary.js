'use strict';
const CommentaryPanel=(()=>{
  const $=id=>document.getElementById(id);
  let configured=false,context=null,identity=null,generation=0,controller=null,busy=false;
  const controls=()=>{$('generateCommentary').disabled=!configured||!context||busy;$('cancelCommentary').hidden=!busy;};
  function clearOutput(){
    $('commentarySummary').textContent='';$('commentaryReasons').replaceChildren();$('commentaryCaution').textContent='';
    $('commentaryEvidence').replaceChildren();$('commentarySources').open=false;$('commentaryOutput').hidden=true;
  }
  function reset(){generation++;controller?.abort();controller=null;busy=false;context=null;identity=null;clearOutput();$('generateCommentary').textContent='生成个性化点评';$('commentaryStatus').textContent=configured?'点击后，根据你选择的游戏与匹配依据生成短评。':'点评暂未启用，先看看下方推荐依据。';controls();}
  function configure(meta){const saved=context,key=identity;configured=meta?.configured===true;reset();context=saved;identity=key;controls();}
  function select(report,candidate){const body={appids:report.ranking.query_appids||report.query_games.map(g=>g.appid),candidate_appid:candidate,top_k:report.ranking.top_k,year_min:report.ranking.filters.year_min,year_max:report.ranking.filters.year_max};const key=JSON.stringify(body)+report.view_version;if(key===identity)return;reset();context=body;identity=key;controls();}
  async function generate(){if(!configured||!context||busy)return;const token=++generation,requested=context;controller=new AbortController();busy=true;controls();$('commentaryStatus').textContent='正在为这次选择写点评…';clearOutput();
    try{const response=await fetch('/api/commentary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requested),signal:controller.signal});const data=await response.json();if(token!==generation)return;if(!response.ok)throw new Error(data.error||'点评暂时无法生成。');
      const c=data.commentary;
      if(data.status!=='ok'||data.candidate_appid!==requested.candidate_appid||!c||typeof c.summary!=='string'||typeof c.caution!=='string'||!Array.isArray(c.reasons)||c.reasons.length<1||c.reasons.length>2||!c.reasons.every(r=>r&&typeof r.title==='string'&&typeof r.text==='string')||!Array.isArray(data.evidence))throw new Error('点评内容暂不可用，请重试。');
      $('commentarySummary').textContent=c.summary;
      for(const r of c.reasons){
        const item=document.createElement('li'),title=document.createElement('strong'),body=document.createElement('p');
        title.textContent=r.title;body.textContent=r.text;item.append(title,body);$('commentaryReasons').append(item);
      }
      $('commentaryCaution').textContent=c.caution;
      for(const e of data.evidence){const item=document.createElement('span');item.className='commentary-proof';item.textContent=`${e.seed_name} · ${DiscoveryPresentation.tagLabel(e.name)}`;$('commentaryEvidence').append(item);}
      $('commentaryOutput').hidden=false;$('commentaryStatus').textContent=data.cached?'已载入这次选择的点评。':'点评已生成。';$('generateCommentary').textContent='再看这次点评';
    }catch(e){if(token!==generation||e.name==='AbortError')return;$('commentaryStatus').textContent=e.message;$('generateCommentary').textContent='重试生成';
    }finally{if(token===generation){busy=false;controller=null;controls();}}
  }
  function init(){$('generateCommentary').addEventListener('click',generate);$('cancelCommentary').addEventListener('click',()=>{const saved=context,key=identity;reset();context=saved;identity=key;$('commentaryStatus').textContent='已停止等待点评，下方推荐依据仍可查看。';controls();});controls();}
  return {configure,select,reset,init};
})();
CommentaryPanel.init();
