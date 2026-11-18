"""Approved fictional configuration through Admin HTTP API; no SQL/schema changes."""
import argparse,json
from pathlib import Path
import httpx

def configure(base):
    assert base in {'http://127.0.0.1:58090','http://127.0.0.1:58092'}
    with httpx.Client(base_url=base) as client:
        login=client.post('/auth/login',json={'email':'admin.demo@petops.example','password':'DemoPass!123'});login.raise_for_status()
        rows=client.get('/admin/services');rows.raise_for_status();rows=rows.json();evidence=[]
        for name,kind,duration in [('Essential Tidy','GROOMING',30),('Basic Grooming','GROOMING',60),('Full Grooming','GROOMING',90),('Standard Boarding','BOARDING',None)]:
            found=[r for r in rows if r['name']==name]
            if found:
                assert len(found)==1 and found[0]['service_type']==kind and found[0]['duration_minutes']==duration and found[0]['is_active'], 'Existing configuration mismatch: '+name
                row=found[0];action='existing, unchanged'
            else:
                response=client.post('/admin/services',json={'name':name,'service_type':kind,'duration_minutes':duration,'is_active':True});response.raise_for_status();row=response.json();action='created through Admin API'
            evidence.append({'action':action,'record':row})
        client.post('/auth/logout').raise_for_status()
    return {'base':base,'scope':'FICTIONAL DEVELOPMENT/DEMO CONFIGURATION; not RS Pet House commercial services','fields':'name, service_type, duration_minutes (Grooming only), is_active; no schema change','records':evidence}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:58090');parser.add_argument('--out',required=True);args=parser.parse_args()
    result=configure(args.base);out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print('Verified four approved fictional services; saved exact creation/retention evidence.')
