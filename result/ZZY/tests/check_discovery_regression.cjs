const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const home=path.resolve(__dirname,'..');
const old=path.resolve(home,'../../../交付版-单服务入口/result/ZZY');
const history=path.resolve(home,'../../../achievement-analytics/data/processed/recommendation/query-view-check/replay-v2');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
(async()=>{
 const protectedFiles=fs.readdirSync(path.join(old,'modeling/recommendation')).filter(f=>f.endsWith('.py')&&f!=='query_view.py');
 for(const f of protectedFiles)assert.equal(sha(path.join(home,'modeling/recommendation',f)),sha(path.join(old,'modeling/recommendation',f)),`protected module ${f}`);
 const queries=JSON.parse(fs.readFileSync(path.join(history,'protocol.json'),'utf8')).queries;
 const checks=[];
 for(let i=0;i<queries.length;i++){
  const q=queries[i],params=new URLSearchParams({appids:q.seeds.join(','),top_k:'5',path_limit:'all'});
  for(const key of ['year_min','year_max'])if(q[key]!=null)params.set(key,q[key]);
  const response=await fetch('http://127.0.0.1:8615/api/recommend?'+params);assert.equal(response.status,200);
  const actual=await response.json(),expected=JSON.parse(fs.readFileSync(path.join(history,'queries',`${i+1}.json`),'utf8'));
  // replay-v2 predates v5 Chinese aliases, which changed service binding/version
  // metadata without changing scoring. Compare every non-version field, and
  // independently require all v5 calculation modules above to be byte-identical.
  const withoutIdentity=r=>Object.fromEntries(Object.entries(r).filter(([k])=>!['algorithm_version','query_service_version','binding','query_binding'].includes(k)));
  assert.deepEqual(withoutIdentity(actual.ranking),withoutIdentity(expected.ranking),`historical query ${i+1} all ranking content apart from version bindings`);
  assert.deepEqual(actual.explanations,expected.explanations,`historical query ${i+1} full paths/evidence projection`);
  checks.push({query:i+1,seeds:q.seeds,results:actual.ranking.results.length,ranking_content_and_paths_identical:true});
 }
 const out={status:'passed',protected_modules:protectedFiles.length,protected_module_sha_identical:true,database_access:false,comparison:'frozen replay-v2 query reports; pre-v5 alias version bindings excluded, all actual ranking fields and paths compared',checks};
 fs.mkdirSync(path.join(home,'reports'),{recursive:true});fs.writeFileSync(path.join(home,'reports/discovery-regression.json'),JSON.stringify(out,null,2)+'\n');console.log(JSON.stringify(out));
})().catch(e=>{console.error(e.stack);process.exit(1)});
