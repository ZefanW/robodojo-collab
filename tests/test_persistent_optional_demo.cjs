'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),test=require('node:test');
const script=fs.readFileSync(require('node:path').join(__dirname,'../web/publications.js'),'utf8');
const start=script.indexOf('  function renderVideos('),end=script.indexOf('  function renderFiles(',start);
function render(m){const ctx={m,nativeVLA:()=>false,renderVideo:a=>`<video data-original="${a.path}"></video>`,esc:s=>String(s).replaceAll('<','&lt;')};vm.createContext(ctx);vm.runInContext(script.slice(start,end)+';result=renderVideos(m, "https://example.org/")',ctx);return ctx.result;}
const cameras=['head','left_wrist','right_wrist'].map(view=>({kind:'native_video',path:view+'.mp4',view}));
const declared={artifacts:cameras,audit:{media_policy:'persistent-original-nine-cameras-v1',original_demo_available:false,original_demo_note:'此记录未提供额外演示剪辑；三路原始视频和动作轨迹可查阅。'}};
test('explicit original-camera policy shows all three real camera entries and availability note',()=>{const html=render(declared);assert.equal((html.match(/data-original=/g)||[]).length,3);for(const c of cameras)assert.ok(html.includes(c.path));assert.ok(html.includes(declared.audit.original_demo_note));assert.ok(html.includes('不参与实验执行或成绩计算'));assert.ok(!html.includes('对照动作与当时的公开说明。'));});
test('undeclared missing clip uses original default UI without claiming a reviewed exception',()=>{const html=render({artifacts:cameras});assert.ok(html.includes('清单中未登记演示视频。'));assert.ok(!html.includes('此记录未提供额外演示剪辑'));});
test('an existing demo renders unchanged even if stale absent metadata is supplied',()=>{const html=render({...declared,artifacts:[...cameras,{kind:'public_demo',path:'original-demo.mp4'}]});assert.ok(html.includes('original-demo.mp4'));assert.ok(html.includes('对照动作与当时的公开说明。'));assert.ok(!html.includes('不参与实验执行或成绩计算'));});
test('availability note is escaped as text',()=>{const html=render({...declared,audit:{...declared.audit,original_demo_note:'<img src=x>'}});assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));});
