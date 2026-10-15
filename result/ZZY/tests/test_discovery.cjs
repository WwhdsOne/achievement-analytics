const {test}=require('node:test');
const assert=require('node:assert/strict');
const p=require('../modeling/recommendation/query_view_assets/discovery.js');
const games=[{appid:1,name:'我的游戏'},{appid:2,name:'另一款游戏'}];
const path=(field,name,contribution,seed_appid=1,used_for_score=true)=>({field,name,contribution,seed_appid,used_for_score});
test('reason uses only actual positive scored paths and names the specific seed',()=>{
 const paths=[path('publishers','不计分发行商',9,1,false),path('tags','无贡献',0),path('genres','Action',.5),path('tags','Exploration',.2,2)];
 const result=p.describe({path_catalog:paths},games);
 assert.match(result.reason,/另一款游戏/);assert.match(result.reason,/探索/);assert.equal(result.reasons[0].name,'Exploration');assert.doesNotMatch(result.reason,/Exploration/);
 assert.doesNotMatch(result.reason,/我的游戏|全部|无贡献|不计分/);
 assert.deepEqual(result.tags,['Exploration']);assert.equal(result.paths[0].seed_appid,2);
});
test('templates distinguish developer and genre facts from gameplay claims',()=>{
 assert.match(p.describe({path_catalog:[path('developers','Studio A',.1)]},games).reason,/同一开发商/);
 assert.match(p.describe({path_catalog:[path('genres','RPG',.1)]},games).reason,/同属.*角色扮演/);
});
test('fallback avoids invention for empty, zero, unscored or unknown seed paths',()=>{
 for(const paths of [[],[path('tags','Zero',0)],[path('tags','Fake',1,99)],[path('tags','Fact',1,1,false)]]){
  const out=p.describe({path_catalog:paths},games);assert.deepEqual(out.tags,[]);assert.match(out.reason,/依据较少/);
 }
});
test('tags are unique, capped at three and input is not mutated',()=>{
 const data={path_catalog:['a','b','a','c','d'].map((s,i)=>path('tags',s,1/(i+1)))};
 const original=JSON.stringify(data);assert.deepEqual(p.describe(data,games).tags,['a','b','c']);assert.equal(JSON.stringify(data),original);
});
test('official URLs accept only positive safe numeric integer ids',()=>{
 assert.equal(p.storeURL(367520),'https://store.steampowered.com/app/367520/');
 assert.match(p.coverURL(367520),/^https:\/\/cdn\.akamai\.steamstatic\.com\/steam\/apps\/367520\/header\.jpg$/);
 for(const v of ['367520','1/evil',0,-1,NaN,1.5,Number.MAX_SAFE_INTEGER+1]){
  assert.equal(p.storeURL(v),null);assert.equal(p.coverURL(v),null);
 }
});
test('bilingual title is a display projection and leaves game data unchanged',()=>{
 const game={appid:1,name:'English title'};const before=JSON.stringify(game);
 assert.equal(p.title(game,{'1':{display_name:'中文名'}}),'中文名');assert.equal(JSON.stringify(game),before);
});
test('multi-seed explanations cover distinct contributing games and keep original labels',()=>{
 const paths=[path('tags','Exploration',.4,1),path('tags','Metroidvania',.3,1),path('tags','Farming Sim',.2,2),path('tags','Publisher fact',0,2,false)];
 const out=p.describe({path_catalog:paths},games);
 assert.ok(out.reasons.length>=2&&out.reasons.length<=3);
 assert.deepEqual(new Set(out.reasons.slice(0,2).map(r=>r.seed_appid)),new Set([1,2]));
 assert.ok(out.reasons.every(r=>paths.some(p=>p.name===r.name&&p.seed_appid===r.seed_appid&&p.contribution>0)));
 assert.match(out.reason,/探索/);assert.doesNotMatch(out.reason,/全部|Publisher fact/);
 assert.equal(p.tagLabel('Unknown Tag'),'Unknown Tag');
});
test('secondary reasons prefer distinctive actual evidence across returned games',()=>{
 const common=[path('tags','Exploration',.5),path('tags','Metroidvania',.4),path('tags','Dark Fantasy',.3)];
 const display={path_catalog:[...common,path('tags','Hand-drawn',.1)]};
 const others=[display,{path_catalog:common},{path_catalog:common}];
 const out=p.describe(display,games,{},others);
 assert.equal(out.reasons[0].name,'Exploration');assert.ok(out.reasons.some(r=>r.name==='Hand-drawn'));
});
