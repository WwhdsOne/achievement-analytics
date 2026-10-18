const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');const home=path.resolve(__dirname,'..');
const catalog=JSON.parse(fs.readFileSync(path.join(home,'modeling/recommendation/game_aliases.json'),'utf8')).games;
const origin=process.env.DISCOVERY_URL||'http://127.0.0.1:8615';
(async()=>{
 let main=0,baseline=0;const limited=[];
 async function get(route){const r=await fetch(origin+route);assert.equal(r.status,200);return r.json();}
 for(const [id,g] of Object.entries(catalog))for(const alias of g.aliases){
  const q=encodeURIComponent(alias);let found=null,offset=0,data;
  do{data=await get(`/api/search?q=${q}&limit=100&offset=${offset}`);found=data.results.find(r=>r.appid===Number(id));offset+=100;}while(!found&&offset<data.total_matches);
  assert.ok(found,`alias ${alias} finds ${id}`);assert.equal(found.name_en,g.name_en);assert.ok(found.matched_aliases.includes(alias));main++;
  if(found.recommendation_eligible){const hits=await get(`/baseline/api/games?q=${q}`);if(hits.some(r=>r.appid===Number(id)))baseline++;else limited.push({alias,appid:Number(id),reason:'baseline returns only first 20 matches'});}
 }
 const browser=await chromium.launch({channel:'msedge',headless:true});const browserChecks=[];
 for(const [label,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
  const page=await browser.newPage({viewport});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(origin);
  for(const [q,id] of [['茶杯头',268910],['星际拓荒',753640],['小丑牌',2379780],['黑猴',2358720],['Ｐ５Ｒ',1687950]]){
   const response=page.waitForResponse(r=>r.url().includes('/api/search?'));await page.locator('#searchText').fill(q);await page.locator('#searchButton').click();const d=await(await response).json();const i=d.results.findIndex(r=>r.appid===id);assert.ok(i>=0);assert.ok(await page.locator('.search-row').nth(i).isVisible());browserChecks.push(`${label}/search/${q}`);
  }
  await page.locator('.search-row').first().locator('button').click();assert.equal(await page.locator('.seed-card').count(),1);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));assert.deepEqual(errors,[]);browserChecks.push(`${label}/select/layout/no_errors`);await page.close();
 }
 await browser.close();
 const report={status:'passed',date:'2026-10-15',database_access:false,games:Object.keys(catalog).length,main_alias_queries:main,baseline_visible_alias_queries:baseline,baseline_first20_limit:limited,browser_checks:browserChecks};
 fs.writeFileSync(path.join(home,'reports/alias-expansion-check-v7.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
})().catch(e=>{console.error(e.stack);process.exit(1)});
