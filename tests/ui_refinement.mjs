// Execute the shipped Customer renderer against bounded fictional states.
// No HTTP requests, PostgreSQL connection or browser substitute.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
  constructor(tag, text='', cls='') { this.tag=tag;this.text=text;this.children=[];this.attrs={};this.dataset={};this.classes=new Set(cls.split(' ').filter(Boolean));this.classList={add:(...values)=>values.forEach(v=>this.classes.add(v))}; }
  append(...values) { this.children.push(...values); }
  prepend(...values) { this.children.unshift(...values); }
  replaceChildren(...values) { this.children=values; }
  setAttribute(key,value) { this.attrs[key]=value; }
  removeAttribute(key) { delete this.attrs[key]; }
  get childElementCount() { return this.children.length; }
}
const source=fs.readFileSync(new URL('../app/static/customer.js',import.meta.url),'utf8');
const walk=node=>[node,...node.children.flatMap(walk)];
const pet={id:'pet',name:'Fictional Pet'};
const booking={id:'booking',pet_name:pet.name,service_name:'Fictional Grooming',booking_type:'GROOMING',grooming_start:'2099-11-16T02:00:00Z'};
let checks=0;
for(const state of [
  {name:'no pets or bookings',pets:[],rows:[]},
  {name:'pet without bookings',pets:[pet],rows:[]},
  {name:'upcoming booking',pets:[pet],rows:[{...booking,status:'CONFIRMED'}]},
  {name:'completed history',pets:[pet],rows:[{...booking,status:'COMPLETED'}]},
]) {
  const elements=new Map();
  const el=(tag,text,cls)=>new Element(tag,text,cls);
  const get=id=>{if(!elements.has(id))elements.set(id,el('div'));return elements.get(id);};
  const apiCalls=[];
  const context=vm.createContext({Date,Intl,Array,console,el,$:get,
    button:(label,handler)=>Object.assign(el('button',label),{handler}),
    shellNav:{insertBefore(){}},shellMain:{focus(){}},message(){},
    user:{id:'fictional-customer',role:'CUSTOMER'},activePage:'customer-home',viewRevision:1,selected:null,
    refresh:async()=>{},human:value=>value,
    api:async route=>{apiCalls.push(route);return route==='/customer/profile'?{display_name:'Fictional Customer'}:route==='/pets'?state.pets:route==='/grooming/bookings'?state.rows:[];},
  });
  vm.runInContext(source,context);
  await vm.runInContext('renderCustomerPage(1)',context);
  const panel=vm.runInContext('customerPanel',context),nodes=walk(panel);
  const bookingButtons=nodes.filter(n=>n.tag==='button'&&n.text==='Book a service');
  assert.equal(bookingButtons.length,1,state.name+': one Home booking action');
  assert.equal(nodes.filter(n=>n.tag==='button'&&!n.classes.has('secondary')).length,1,state.name+': one primary action');
  assert.deepEqual(apiCalls.sort(),['/boarding/bookings','/customer/profile','/grooming/bookings','/pets']);
  await bookingButtons[0].handler();
  assert.equal(context.activePage,'customer-book',state.name+': existing booking route');
  checks++;
  console.log('Verified Home action hierarchy and existing route: '+state.name);
}
console.log(`${checks} refinement state checks passed`);
