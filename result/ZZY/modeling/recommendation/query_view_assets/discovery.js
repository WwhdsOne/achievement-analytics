'use strict';
const DiscoveryPresentation=(()=>{
  const priority={tags:0,genres:1,developers:2};
  const labels={'Souls-like':'类魂','Metroidvania':'类银河战士恶魔城','Dark Fantasy':'黑暗奇幻','Exploration':'探索','Farming Sim':'农场模拟','Action RPG':'动作角色扮演','RPG':'角色扮演','Adventure':'冒险','Action':'动作','Indie':'独立','Simulation':'模拟','Strategy':'策略','Casual':'休闲','Rogue-like':'类 Rogue','Rogue-lite':'轻度 Rogue','Roguelike Deckbuilder':'Rogue 牌组构筑','Deckbuilding':'牌组构筑','Card Game':'卡牌','Platformer':'平台跳跃','Puzzle':'解谜','Survival':'生存','Open World':'开放世界','Hand-drawn':'手绘','Pixel Graphics':'像素画面','Singleplayer':'单人','Co-op':'合作','Fishing':'钓鱼','Building':'建造','Agriculture':'农业','Great Soundtrack':'优秀原声','2D':'2D'};
  const tagLabel=name=>labels[name]||name;
  const title=(game,names={})=>game?.display_name||names[String(game?.appid)]?.display_name||game?.name||game?.name_en||'名称暂无资料';
  const english=(game,names={})=>game?.display_name_en||names[String(game?.appid)]?.display_name_en||game?.name_en||game?.name||'';
  function describe(display,games,displayNames={},comparisons=[]){
    const names=new Map(games.map(g=>[g.appid,title(g,displayNames)]));
    const paths=(display?.path_catalog||[]).filter(p=>p.used_for_score===true&&Number.isFinite(p.contribution)&&p.contribution>0&&names.has(p.seed_appid)&&Object.hasOwn(priority,p.field)&&typeof p.name==='string'&&p.name.trim()).slice().sort((a,b)=>priority[a.field]-priority[b.field]||b.contribution-a.contribution||String(a.key||a.name).localeCompare(String(b.key||b.name)));
    const tags=[...new Set(paths.filter(p=>p.field==='tags').map(p=>p.name))].slice(0,3);
    if(!paths.length)return {reason:'当前条件下可解释的相似依据较少。',reasons:[],tags,paths};
    const chosen=[paths[0]],seen=new Set([paths[0].seed_appid]);
    for(const p of paths)if(!seen.has(p.seed_appid)&&chosen.length<3){chosen.push(p);seen.add(p.seed_appid);}
    const frequency=p=>comparisons.filter(d=>(d.path_catalog||[]).some(q=>q.field===p.field&&q.name===p.name&&q.used_for_score&&q.contribution>0)).length||1;
    const alternatives=paths.slice().sort((a,b)=>frequency(a)-frequency(b)||priority[a.field]-priority[b.field]||b.contribution-a.contribution);
    for(const p of alternatives)if(chosen.length<3&&!chosen.some(q=>q.field===p.field&&q.name===p.name)){chosen.push(p);}
    const reasons=chosen.map(p=>{const name=names.get(p.seed_appid),label=tagLabel(p.name);
      const text=p.field==='developers'?`与《${name}》来自同一开发商 ${p.name}。`:p.field==='genres'?`与《${name}》同属 ${label} 类型。`:`与《${name}》共同包含「${label}」标签。`;
      return {seed_appid:p.seed_appid,field:p.field,name:p.name,contribution:p.contribution,text};});
    return {reason:reasons[0].text,reasons,tags,paths};
  }
  const valid=id=>typeof id==='number'&&Number.isSafeInteger(id)&&id>0;
  return {describe,title,english,tagLabel,storeURL:id=>valid(id)?`https://store.steampowered.com/app/${id}/`:null,coverURL:id=>valid(id)?`https://cdn.akamai.steamstatic.com/steam/apps/${id}/header.jpg`:null};
})();
if(typeof module!=='undefined')module.exports=DiscoveryPresentation;
