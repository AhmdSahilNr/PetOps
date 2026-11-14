// Deterministic delayed-response tests execute the real shipped scripts.
// Tiny DOM fixture, built-in Node only; this is not a browser/UAT substitute.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
class Element {
  constructor(tag='div') { this.tagName=tag.toUpperCase();this.children=[];this.events={};this.hidden=false;this.value='';this.attributes={};this.elements={};this.ownText=''; }
  set textContent(value) { this.ownText=String(value);this.children=[]; }
  get textContent() { return this.ownText+this.children.map(c=>c.textContent ?? String(c)).join(' '); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.ownText='';this.children=children; }
  setAttribute(key,value) { this.attributes[key]=String(value); }
  addEventListener(event,fn) { (this.events[event]??=[]).push(fn); }
  checkValidity() { return true; }
  reset() {}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const staff={id:'staff-one',email:'staff@petops.example',role:'STAFF'};
const customer={id:'customer-a',email:'a@petops.example',role:'CUSTOMER'};
function fixture() {
  const elements=new Map();
  for(const match of fs.readFileSync(path.join(root,'app/static/index.html'),'utf8').matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g)) elements.set(match[2],new Element(match[1]));
  elements.get('profile').elements.display_name=new Element('input');
  const documentEvents={};
  const document={getElementById:id=>{assert(elements.has(id),'Unexpected DOM id '+id);return elements.get(id);},createElement:tag=>new Element(tag),addEventListener:(event,fn)=>{documentEvents[event]=fn;}};
  const requests=[];
  const context=vm.createContext({document,console,Date,Intl,URLSearchParams,setTimeout,clearTimeout,fetch:url=>new Promise(resolve=>requests.push({url,resolve}))});
  const run=code=>vm.runInContext(code,context);
  for(const name of ['demo.js','boarding.js','operations.js']) vm.runInContext(fs.readFileSync(path.join(root,'app/static',name),'utf8'),context,{filename:name});
  if(documentEvents.DOMContentLoaded) documentEvents.DOMContentLoaded();
  function take(url) { const at=requests.findIndex(r=>r.url===url);assert(at>=0,'Expected request '+url);return requests.splice(at,1)[0]; }
  async function respond(request,body,code=200) { request.resolve({status:code,ok:code>=200&&code<300,json:async()=>body});await flush(); }
  async function drain(promise) {
    let done=false,error;promise.then(()=>{done=true;},e=>{done=true;error=e;});
    for(let i=0;i<30&&!done;i++) {
      await flush();
      while(requests.length) { const r=requests.shift();await respond(r,r.url==='/me'?staff:r.url==='/customer/profile'?{display_name:'Ordinary Customer'}:[]); }
    }
    assert(done,'Pending test operation did not settle');if(error) throw error;
  }
  return {elements,requests,run,take,respond,drain};
}
async function signedOutFixture() {const f=fixture();await f.respond(f.take('/me'),{detail:'No session'},401);return f;}
function detail(type,id='old') {return {customer_name:'PRIVATE_CUSTOMER_A',pet_name:'PRIVATE_PET_A',service_name:'Fictional Service',booking:{id,status:'COMPLETED',booking_type:type,grooming_start:'2026-11-08T00:00:00Z',grooming_duration_minutes:60,boarding_start:'2026-11-08',boarding_end:'2026-11-10'},grooming_record:null,boarding_stay:null,allocation_history:[],stay_notes:[],history:[]};}
const tests=[];
for(const kind of ['GROOMING','BOARDING']) tests.push([kind+' delayed detail cannot repopulate after logout',async()=>{
  const f=await signedOutFixture();f.run(`user=${JSON.stringify(staff)};serviceKind='${kind}';activePage='work'`);
  const pending=f.run("show('old')");const safe=pending.catch(()=>{});const r=f.take('/'+kind.toLowerCase()+'/bookings/old');
  f.run('signedOut()');await f.respond(r,detail(kind));await safe;
  assert(!f.elements.get('detail').textContent.includes('PRIVATE_'),'Private old detail returned after logout');
}]);
tests.push(['late Customer profile cannot return after logout',async()=>{
  const f=await signedOutFixture();const pending=f.run('refresh()');await f.respond(f.take('/me'),customer);
  const profile=f.take('/customer/profile');f.run('signedOut()');await f.respond(profile,{display_name:'PRIVATE_CUSTOMER_A'});await f.drain(pending);
  assert(!f.elements.get('profile').elements.display_name.value.includes('PRIVATE_'),'Old profile repopulated after logout');
}]);
tests.push(['latest opened detail wins when responses arrive in reverse order',async()=>{
  const f=await signedOutFixture();f.run(`user=${JSON.stringify(staff)}`);
  const a=f.run("show('first')"),b=f.run("show('second')");const ra=f.take('/grooming/bookings/first'),rb=f.take('/grooming/bookings/second');
  await f.respond(rb,{...detail('GROOMING','second'),pet_name:'Latest permitted pet'});await b;
  await f.respond(ra,detail('GROOMING','first'));await a;
  assert.equal(f.run('selected'),'second');assert(f.elements.get('detail').textContent.includes('Latest permitted pet'));
}]);
tests.push(['late initial unauthorized response cannot clear a newer authenticated view',async()=>{
  const f=fixture(),initial=f.take('/me');const newer=f.run('refresh()');await f.respond(f.take('/me'),staff);await f.drain(newer);
  await f.respond(initial,{detail:'Old missing session'},401);await flush();
  assert.equal(f.run('user?.id'),staff.id,'Old startup failure erased current session view');
}]);
let failures=0;
for(const [name,test] of tests) {try {await test();console.log('PASS '+name);}catch(error) {failures++;console.log('FAIL '+name+': '+error.message);}}
console.log(`${tests.length-failures} passed, ${failures} failed`);process.exitCode=failures?1:0;
