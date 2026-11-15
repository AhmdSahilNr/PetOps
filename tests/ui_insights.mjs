// Actual shipped handlers with delayed reads; no network/database/browser claims.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../app/static/overview.js',import.meta.url),'utf8');
const demo=fs.readFileSync(new URL('../app/static/demo.js',import.meta.url),'utf8');
const sharedActions=demo.slice(demo.indexOf('function action('),demo.indexOf('function option('));
class Element {
 constructor(tag,text='',cls=''){this.tag=tag;this.tagName=tag.toUpperCase();this.text=text;this.cls=cls;this.children=[];this.dataset={};this.events={};this.attrs={};this.value='';}
 append(...values){this.children.push(...values);}
 setAttribute(k,v){this.attrs[k]=v;}
 removeAttribute(k){delete this.attrs[k];}
 addEventListener(k,v){this.events[k]=v;}
 get textContent(){return this.text+this.children.map(x=>x.textContent??x).join(' ');}
}
function fixture(){
 const messages=[];let calls=0;
 const context=vm.createContext({console,user:{id:'admin',role:'ADMIN'},activePage:'admin-insights',viewRevision:1,
  el:(t,v,c)=>new Element(t,v,c),option:(v,t)=>Object.assign(new Element('option',t),{value:v}),
  quiet:(label,handler)=>Object.assign(new Element('button',label),{handler}),message:(...args)=>messages.push(args),
  adminError:()=>"Couldn’t load current data.",human:s=>s,recordDate:s=>s,recordTime:s=>s,recordDefinition:rows=>new Element('dl',rows.map(r=>r.join(': ')).join(' ')),
  recordLabel:s=>s,adminGo(){},refresh:async()=>{calls++;vm.runInContext('viewRevision++;overviewLoaded()',context);}});
 vm.runInContext(sharedActions,context);
 context.quiet=(label,handler)=>{const b=vm.runInContext('button',context)(label,handler);b.handler=()=>b.events.click({preventDefault(){},currentTarget:b});return b;};
 vm.runInContext(source,context);
 return {context,messages,run:s=>vm.runInContext(s,context),calls:()=>calls};
}
const tests=[];
tests.push(['refresh retains committed custom period and session',async()=>{
 const f=fixture();f.run('insightDates={preset:"custom",from_date:"2026-11-01",to_date:"2026-11-15"}');
 const b=f.run('refreshDataControl()');await b.handler();
 assert.equal(f.calls(),1);assert.equal(f.context.user.id,'admin');assert.equal(f.context.activePage,'admin-insights');
 assert.equal(f.run('insightDates.from_date'),'2026-11-01');assert.equal(f.run('insightDates.to_date'),'2026-11-15');
 assert(f.messages.some(([s])=>s==='Data refreshed.'));assert.equal(b.disabled,false);
}]);
tests.push(['handled server failure cannot announce refresh success',async()=>{
 const f=fixture();f.context.refresh=async()=>{f.run('viewRevision++;overviewState=null');f.context.message('Server unavailable',true);};
 await f.run('refreshDataControl()').handler();assert(!f.messages.some(([s])=>s==='Data refreshed.'));assert.equal(f.messages.at(-1)[0],'Server unavailable');
}]);
tests.push(['thrown error is visible and restores control',async()=>{
 const f=fixture();f.context.refresh=async()=>{throw new Error('offline');};const b=f.run('refreshDataControl()');await b.handler();
 assert.equal(f.messages.at(-1)[1],true);assert(!f.messages.some(([s])=>s==='Data refreshed.'));assert.equal(b.disabled,false);
}]);
tests.push(['delayed refresh cannot report into a different user or page',async()=>{
 const f=fixture();let resolve;f.context.refresh=()=>new Promise(r=>resolve=r);const b=f.run('refreshDataControl()');const pending=b.handler();
 f.context.user={id:'customer',role:'CUSTOMER'};f.context.activePage='customer-home';resolve();await pending;
 assert(!f.messages.some(([s])=>s==='Data refreshed.'));
}]);
tests.push(['double click starts only one pending refresh',async()=>{
 const f=fixture();let resolve,calls=0;f.context.refresh=()=>{calls++;return new Promise(r=>resolve=r);};const b=f.run('refreshDataControl()');const first=b.handler();await b.handler();assert.equal(calls,1);resolve();await first;
}]);
tests.push(['custom period rejects reversed dates without fetching',async()=>{
 const f=fixture();f.run('insightDates={preset:"custom",from_date:"2026-11-20",to_date:"2026-11-01"}');const form=f.run('insightPeriodForm()');
 form.events.submit({preventDefault(){}});assert.equal(f.calls(),0);assert.equal(f.messages.at(-1)[1],true);
}]);
tests.push(['zero-decision dashboard displays dash and honest empty trend',async()=>{
 const f=fixture();f.context.target=new Element('section');f.context.data={total_bookings:0,completed_services_by_type:{GROOMING:0,BOARDING:0},confirmation_decisions:{confirmation_rate_percent:null},booking_change_events:{BOOKING_CANCELLED:0,BOOKING_RESCHEDULED:0},bookings_by_type:{GROOMING:0,BOARDING:0},bookings_by_status:{SUBMITTED:0,CONFIRMED:0,COMPLETED:0},booking_volume:{bucket_size:'week',buckets:[]},staff_workload:[],boarding_current:{as_of:'now',configured_active_capacity:0,physically_occupied:0,available_places:0,utilisation_percent:null,units:[]},next_seven_days:{from_date:'2026-11-15',to_date:'2026-11-21',grooming_appointments:0,boarding_arrivals:0,boarding_departures:0,active_boarding_stays:0,requests_needing_review:0}};
 f.run('drawInsightDashboard(target,data)');const text=f.context.target.textContent;assert(text.includes('—'));assert(text.includes('No booking requests in this period.'));assert(text.includes('Independent of the selected reporting period.'));assert(text.includes('Booking status'));assert(!text.includes('NaN'));assert(!text.includes('Staff Utilisation'));
}]);
let failures=0;for(const [name,fn] of tests){try{await fn();console.log('Verified '+name);}catch(e){failures++;console.log('FAILED '+name+': '+e.message);}}
console.log(`${tests.length-failures} Insights checks passed, ${failures} failed`);process.exitCode=failures?1:0;
