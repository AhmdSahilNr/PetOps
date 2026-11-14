// Exercise the shipped queue classifier without recreating its implementation.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../app/static/staff.js',import.meta.url),'utf8');
const lines=source.split('\n').filter(s=>s.startsWith('const staffTerminal=')||s.startsWith('const staffOngoing=')||s.startsWith('function staffGroup('));
const context=vm.createContext({Date,user:{id:'one'},businessDate:()=>new Date().toISOString().slice(0,10),staffDay:value=>value.slice(0,10)});
vm.runInContext(lines.join('\n'),context);
const future=new Date(Date.now()+86400000).toISOString(),past=new Date(Date.now()-86400000).toISOString(),end=new Date(Date.now()+172800000).toISOString();
function classify(b){context.booking=b;return vm.runInContext('staffGroup(booking)',context);}
const period={staff_user_id:'one',starts_at:future,effective_end:end,released_at:null};
assert.equal(classify({booking_type:'GROOMING',status:'IN_PROGRESS',responsibility_periods:[period]}),'today');
assert.equal(classify({booking_type:'BOARDING',status:'STAYING',current_staff_user_id:'one',responsibility_periods:[{...period,starts_at:past}]}),'today');
assert.equal(classify({booking_type:'BOARDING',status:'STAYING',current_staff_user_id:'other',responsibility_periods:[period]}),'upcoming');
assert.equal(classify({booking_type:'GROOMING',status:'COMPLETED',responsibility_periods:[period]}),'history');
assert.equal(classify({booking_type:'GROOMING',status:'CONFIRMED',grooming_start:future,responsibility_periods:[period]}),'upcoming');
console.log('5 product queue classification checks passed');
