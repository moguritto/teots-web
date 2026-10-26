const { chromium } = require('playwright');
const http=require('http'),fs=require('fs'),path=require('path');(async()=>{
const ROOT=process.argv[2], PREF=process.env.PREF||'/espacioteots-web/';
const types={'.html':'text/html','.css':'text/css','.js':'application/javascript','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.mp4':'video/mp4','.gif':'image/gif','.json':'application/json'};
const srv=http.createServer((q,r)=>{let u=decodeURIComponent(q.url.split('?')[0]);if(!u.startsWith(PREF)){r.writeHead(404);return r.end()}let p=path.join(ROOT,u.slice(PREF.length));if(fs.existsSync(p)&&fs.statSync(p).isDirectory())p=path.join(p,'index.html');if(!fs.existsSync(p)){r.writeHead(404);return r.end()}r.writeHead(200,{'content-type':types[path.extname(p).toLowerCase()]||'application/octet-stream'});fs.createReadStream(p).pipe(r)}).listen(8099);
const pages=JSON.parse(process.argv[3]); const shots=process.argv[4];
const b=await chromium.launch(); const bad=new Set(); const ext=new Set(); const errs=new Set();
for(const [w,h,tag] of [[1280,800,'d'],[390,844,'m']]){
 const ctx=await b.newContext({viewport:{width:w,height:h},isMobile:tag==='m',hasTouch:tag==='m'});
 for(const pg of pages){const p=await ctx.newPage();
  p.on('response',r=>{if(r.status()>=400&&r.url().includes('127.0.0.1'))bad.add(decodeURIComponent(r.url().replace('http://127.0.0.1:8099'+PREF,'').split('?')[0]))});
  p.on('requestfailed',r=>{if(!r.url().includes('127.0.0.1'))ext.add(new URL(r.url()).hostname)});
  p.on('pageerror',e=>errs.add(String(e).slice(0,120)));
  await p.goto('http://127.0.0.1:8099'+PREF+pg,{waitUntil:'load',timeout:60000}).catch(e=>{});
  await p.evaluate(async()=>{for(let y=0;y<document.body.scrollHeight;y+=600){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,100))}window.scrollTo(0,0)}).catch(()=>{});
  await p.waitForTimeout(1200);
  if(shots) await p.screenshot({path:`${shots}/${tag}_${(pg||'inicio').replace(/\//g,'_')}.png`});
  await p.close()}
 await ctx.close()}
await b.close(); srv.close();
console.log(JSON.stringify({bad:[...bad],ext:[...ext],errs:[...errs]},null,1));
})();
