"""Authorized Batch9 fictional retained demo. No status/time/history SQL edits.

Existing approved seed helper creates base accounts. Name-only seed maintenance is
restricted to @petops.example profiles/pets; all Staff/service/unit/workflow writes
use supported HTTP APIs. Private database URL and credentials are never exported.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import json,os,time
import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url

def main():
 root=Path.cwd();assert not (root/'docs/evidence/uiux/batch9/demo-data.json').exists(),'Demo already configured; review current records before any rerun';config=json.loads((root/'.local/final-config.json').read_text(encoding='utf-8'));url=make_url(config['runtime_url']);assert url.host in {'127.0.0.1','localhost'} and not url.database.endswith('_test')
 os.environ['PETOPS_DATABASE_URL']=config['runtime_url']
 from scripts.seed_demo import main as seed
 from app.database import SessionLocal
 from app.models import User,Customer,Pet,Role
 seed();renamed=[]
 # Existing seed maintenance: names only, no account email/credential/status/time edits.
 with SessionLocal() as db:
  for i,(c,u) in enumerate(db.execute(select(Customer,User).join(User,Customer.user_id==User.id).order_by(User.email))):
   assert u.email.endswith('@petops.example'),'Stop: this dedicated demo contains a non-fictional account domain'
   name='Nadia Zainal' if u.email=='customer.demo@petops.example' else ['Sofia Tan','Irfan Hamid'][i%2]
   if c.display_name!=name:renamed.append({'kind':'fictional Customer display name','from':c.display_name,'to':name,'mechanism':'name-only approved seed maintenance'});c.display_name=name
   for j,p in enumerate(db.scalars(select(Pet).where(Pet.customer_id==c.id).order_by(Pet.created_at))):
    if any(v in p.name.lower() for v in ['fictional','test','demo','fixture','long']):
     name=['Poppy','Biscuit','Pepper'][j%3];renamed.append({'kind':'fictional pet name','from':p.name,'to':name,'mechanism':'name-only seed maintenance'});p.name=name
  db.commit()
 base='http://127.0.0.1:58090';admin=httpx.Client(base_url=base,timeout=30);owner=httpx.Client(base_url=base,timeout=30)
 def call(c,method,path,body=None,code=200):
  r=c.request(method,path,json=body);assert r.status_code==code,(path,r.status_code,r.text);return None if code==204 else r.json()
 call(admin,'POST','/auth/login',{'email':'admin.demo@petops.example','password':'DemoPass!123'})
 call(owner,'POST','/auth/login',{'email':'customer.demo@petops.example','password':'DemoPass!123'})
 now=datetime.now(timezone.utc);today=(now+timedelta(hours=8)).date();staff=call(admin,'GET','/admin/staff');staff.sort(key=lambda v:v['email']);names=['amir.hakim@petops.example','hana.aziz@petops.example']
 for s,name in zip(staff,names):
  if s['email']!=name:renamed.append({'kind':'fictional Staff account','from':s['email'],'to':name,'mechanism':'Admin Staff API'});s.update(call(admin,'PUT','/admin/staff/'+s['id'],{'email':name,'is_active':True}))
 # Two weeks of ordinary day shifts; historic windows retained if the server needs them.
 for s in staff:
  windows=call(admin,'GET',f"/admin/staff/{s['id']}/availability")
  for w in windows:
   if w['is_active'] and datetime.fromisoformat(w['ends_at'])-datetime.fromisoformat(w['starts_at'])>timedelta(days=2):
    r=admin.put(f"/admin/staff/{s['id']}/availability/{w['id']}",json={'starts_at':w['starts_at'],'ends_at':w['ends_at'],'is_active':False});assert r.status_code in [200,409]
  for n in range(15):
   d=today+timedelta(days=n);lo=d.isoformat()+'T08:00:00+08:00';hi=d.isoformat()+'T19:00:00+08:00'
   if not any(datetime.fromisoformat(w['starts_at'])==datetime.fromisoformat(lo) and w['is_active'] for w in windows):call(admin,'POST',f"/admin/staff/{s['id']}/availability",{'starts_at':lo,'ends_at':hi,'is_active':True},201)
 services=call(admin,'GET','/admin/services')
 for s in services:
  if s['name'] in ['Inactive Demo Service','Fictional Admin Grooming updated']:
   name='Express Grooming (retired)' if s['duration_minutes']==30 else 'Classic Grooming (retired)';renamed.append({'kind':'retired fictional service','from':s['name'],'to':name,'mechanism':'Admin Service API'});call(admin,'PUT','/admin/services/'+s['id'],{'name':name,'duration_minutes':s['duration_minutes'],'is_active':False})
 units=call(admin,'GET','/admin/accommodations');unit=units[0]
 if unit['name']!='Standard Unit A':renamed.append({'kind':'accommodation','from':unit['name'],'to':'Standard Unit A','mechanism':'Admin Accommodation API'});unit=call(admin,'PUT','/admin/accommodations/'+unit['id'],{'name':'Standard Unit A','category':'Standard','capacity':unit['capacity'],'is_active':True,'notes':None})
 units=call(admin,'GET','/admin/accommodations');second=next((u for u in units if u['name']=='Quiet Unit'),None)
 if not second:second=call(admin,'POST','/admin/accommodations',{'name':'Quiet Unit','category':'Quiet','capacity':3,'is_active':True,'notes':None},201)
 pets=call(owner,'GET','/pets')
 for name in ['Poppy','Biscuit','Pepper']:
  if not any(p['name']==name for p in pets):pets.append(call(owner,'POST','/pets',{'name':name},201))
 gs=next(s for s in services if s['name']=='Essential Tidy');bs=next(s for s in services if s['name']=='Standard Boarding');basic=next(s for s in services if s['name']=='Basic Grooming');full=next(s for s in services if s['name']=='Full Grooming')
 def groom(service,pet,start):return call(owner,'POST','/bookings',{'pet_id':pet['id'],'service_id':service['id'],'grooming_start':start},201)
 def board(pet,n,length):return call(owner,'POST','/bookings',{'pet_id':pet['id'],'service_id':bs['id'],'boarding_start':(today+timedelta(days=n)).isoformat(),'boarding_end':(today+timedelta(days=n+length)).isoformat()},201)
 def assign(b,s,**duty):return call(admin,'PUT',f"/admin/bookings/{b['id']}/staff",{'staff_user_id':s['id'],**duty})
 def confirm(b):return call(admin,'POST',f"/admin/bookings/{b['id']}/status",{'status':'CONFIRMED'})
 def allocate(b,u):return call(admin,'PUT',f"/admin/bookings/{b['id']}/accommodation",{'accommodation_id':u['id']})
 def act(b,a,data={}):return call(admin,'POST',f"/boarding/bookings/{b['id']}/{a}",data,201 if a=='notes' else 200)
 records={};future=lambda n,h:(today+timedelta(days=n)).isoformat()+f'T{h:02}:00:00+08:00'
 records['grooming_request']=groom(basic,pets[0],future(3,11));records['grooming_request_second']=groom(full,pets[2],future(4,10))
 g=groom(full,pets[1],future(2,10));assign(g,staff[1]);confirm(g);records['future_grooming']=g
 # Accelerated fictional walkthrough: real timestamps, ordinary API actions, not elapsed service-time proof.
 for i,key in enumerate(['completed_grooming','active_grooming']):
  start=(datetime.now(timezone.utc)+timedelta(seconds=12)).isoformat();g=groom(gs,pets[i],start);assign(g,staff[i]);confirm(g)
  while datetime.now(timezone.utc)<datetime.fromisoformat(start):time.sleep(.5)
  call(admin,'POST',f"/grooming/bookings/{g['id']}/start",{})
  if key=='completed_grooming':call(admin,'POST',f"/grooming/bookings/{g['id']}/complete",{'service_notes':'Coat brushed and tidy completed. Accelerated fictional demonstration.'})
  records[key]=g
 records['boarding_request']=board(pets[2],5,2)
 b=board(pets[1],3,2);allocate(b,second);confirm(b);records['planned_boarding']=b
 for i,key in enumerate(['completed_boarding','current_boarding']):
  b=board(pets[i],0,2+i);allocate(b,unit if i==0 else second)
  # Optional duty is a recorded interval, not a clock-time access gate.
  assign(b,staff[0],starts_at=future(0,9),ends_at=future(0,10));confirm(b);act(b,'check-in');act(b,'notes',{'note':'Settled in and comfortable. Water refreshed.'})
  if key=='completed_boarding':act(b,'check-out')
  records[key]=b
 report=call(admin,'GET',f'/admin/dashboard?from_date={today.replace(day=1)}&to_date={today+timedelta(days=14)}')
 result={'recorded_utc':datetime.now(timezone.utc).isoformat(),'environment':'retained fictional demo / loopback58090; main8000 personal account database unchanged','fictional_only':True,'mechanisms':'existing seed helper, fictional name-only seed maintenance, supported Admin/Customer lifecycle APIs; no status/time/history SQL edits','renamed_records':renamed,'staff':staff,'services':call(admin,'GET','/admin/services'),'accommodation':call(admin,'GET','/admin/accommodations'),'customer':'Nadia Zainal','pets':pets,'records':records,'report':report,'limitations':['Accelerated fictional lifecycle actions use actual timestamps; not elapsed-care evidence','Historic management events preserve original names; never edited or deleted']}
 (root/'docs/evidence/uiux/batch9/demo-data.json').write_text(json.dumps(result,indent=2),encoding='utf-8');(root/'.local/batch9-demo-records.json').write_text(json.dumps(result),encoding='utf-8');print('Configured fictional retained demonstration; real API records',len(records))

if __name__=='__main__':main()
