"""Synthetic pre0007 fixtures under original guards; no production history rewrite."""
from pathlib import Path
from datetime import datetime,timezone
import re,uuid
import pytest
from sqlalchemy import text
from app.database import SessionLocal
from tests.test_slice2 import case
from tests.test_slice4 import stay,act

@pytest.mark.parametrize('state',['CHECKED_IN','CHECKED_OUT'])
def test_pre0007_legacy_facts_and_bounded_compatibility(stay,state):
    c=stay;bid=uuid.UUID(c['b']['id']);actor=c['seed']['staff1'].id
    root=Path(__file__).resolve().parents[1]
    old=(root/'alembic/versions/0005_rules.sql').read_text()
    with SessionLocal() as db:
        for name in ['petops_guard_boarding_booking','petops_guard_boarding_stay','petops_validate_boarding']:
            sql=re.search(r'CREATE FUNCTION '+name+r'\(.*?\$\$;',old,re.S).group().replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1)
            db.execute(text(sql))
        aid=db.execute(text('SELECT id FROM boarding_allocations WHERE booking_id=:b AND released_at IS NULL'),{'b':bid}).scalar_one()
        sid=uuid.uuid4();now=datetime.now(timezone.utc)
        args={'b':bid,'a':aid,'s':sid,'actor':actor,'at':now}
        db.execute(text("UPDATE bookings SET status='CHECKED_IN' WHERE id=:b"),args)
        db.execute(text('INSERT INTO boarding_stays(id,booking_id,allocation_id,checked_in_by_user_id,checked_in_at) VALUES (:s,:b,:a,:actor,:at)'),args)
        def event(kind,source,target):
            db.execute(text('INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:id,:b,:kind,:source,:target,:actor,:at)'),{**args,'id':uuid.uuid4(),'kind':kind,'source':source,'target':target})
        event('BOARDING_CHECKED_IN','CONFIRMED','CHECKED_IN')
        if state=='CHECKED_OUT':
            db.execute(text("UPDATE bookings SET status='STAYING' WHERE id=:b"),args)
            db.execute(text('UPDATE boarding_stays SET stay_started_at=:at,stay_started_by_user_id=:actor WHERE id=:s'),args)
            event('BOARDING_STAY_STARTED','CHECKED_IN','STAYING')
            db.execute(text("UPDATE bookings SET status='CHECKED_OUT' WHERE id=:b"),args)
            db.execute(text('UPDATE boarding_stays SET checked_out_at=:at,checked_out_by_user_id=:actor WHERE id=:s'),args)
            db.execute(text('UPDATE boarding_allocations SET released_at=:at,released_by_user_id=:actor WHERE id=:a'),args)
            event('BOARDING_CHECKED_OUT','STAYING','CHECKED_OUT')
        db.execute(text((root/'alembic/versions/0007_rules.sql').read_text()))
        product=(root/'alembic/versions/0008_rules.sql').read_text()
        for name in ['petops_guard_boarding_booking','petops_guard_boarding_stay']:
            db.execute(text(re.search(r'CREATE OR REPLACE FUNCTION '+name+r'\(.*?\$\$;',product,re.S).group()))
        db.commit()
    path=f'/boarding/bookings/{bid}'
    before=c['client'].get(path,headers=c['staff']).json()
    assert before['booking']['status']==state
    assert c['client'].get(path,headers=c['owner']).json()==before
    assert before['boarding_stay']['checked_in_at']==now.isoformat()
    if state=='CHECKED_IN':
        act(c,'complete',expected=409)
        act(c,'start-stay')
        done=act(c,'check-out').json()
    else:
        act(c,'start-stay',expected=409)
        done=act(c,'complete').json()
        assert done['boarding_stay']['checked_out_at']==before['boarding_stay']['checked_out_at']
    assert done['boarding_stay']['checked_in_at']==before['boarding_stay']['checked_in_at']
    assert done['history'][:len(before['history'])]==before['history']
    act(c,'start-stay',expected=409);act(c,'complete',expected=409)
