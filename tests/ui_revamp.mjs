// Frontend checks against the shipped ES modules (no copies, no source slicing).
// Usage: node tests/ui_revamp.mjs [races|queue|all]
import assert from 'node:assert/strict';

const only = process.argv[2] || 'all';
const base = new URL('../app/static/js/', import.meta.url);
const mod = (p) => import(new URL(p, base).href);
let checks = 0;
const ok = (label) => { checks += 1; if (process.env.VERBOSE) console.log('ok', label); };

// Minimal browser globals for modules that touch location/history only when called.
globalThis.window = { addEventListener() {}, innerWidth: 1440 };
globalThis.location = { hash: '#/home' };
globalThis.history = { replaceState(_s, _t, url) { globalThis.location.hash = url.startsWith('#') ? url : `#${url}`; } };

if (only === 'all' || only === 'races') {
  // Late responses must not render into a newer view or a newer session (intent of the retired ui_races.mjs).
  const { session } = await mod('core/session.js');
  const router = await mod('core/router.js');
  const seen = [];
  session.user = { id: 'c1', role: 'CUSTOMER' };
  router.start((route, ctx) => seen.push({ route, ctx }));
  const first = seen.at(-1).ctx;
  assert.equal(seen.at(-1).route.pattern, '/home'); assert.ok(first.alive()); ok('initial route alive');
  location.hash = '#/bookings/grooming/abc'; router.render();
  const detail = seen.at(-1).ctx;
  assert.equal(first.alive(), false, 'older view must be stale after navigation'); assert.ok(detail.alive());
  assert.deepEqual(detail.params, { type: 'grooming', id: 'abc' }); ok('newer view wins');
  location.hash = '#/bookings/boarding/def'; router.render();
  assert.equal(detail.alive(), false, 'the latest opened detail wins'); ok('latest detail wins');
  const beforeLogout = seen.at(-1).ctx;
  session.user = null; session.generation += 1;
  assert.equal(beforeLogout.alive(), false, 'responses arriving after sign-out are discarded'); ok('logout invalidates');
  session.user = { id: 's1', role: 'STAFF' }; session.generation += 1;
  location.hash = '#/insights'; router.render();
  assert.equal(seen.at(-1).route.pattern, '/work', 'Staff cannot open Admin destinations; falls back to My work'); ok('staff route policy');
  session.user = { id: 'c1', role: 'CUSTOMER' }; session.generation += 1;
  location.hash = '#/today'; router.render();
  assert.equal(seen.at(-1).route.pattern, '/home'); ok('customer route policy');
  const { navItems } = await mod('core/routes.js');
  assert.ok(!navItems('STAFF').some((i) => i.path.startsWith('/settings') || i.path === '/insights')); ok('staff nav has no admin items');
  assert.deepEqual(navItems('CUSTOMER').map((i) => i.path), ['/home', '/bookings', '/pets'], 'booking is one header action, not a nav item'); ok('customer nav');
  const admin = navItems('ADMIN').map((i) => i.path);
  assert.ok(admin.includes('/today') && admin.includes('/settings/services') && admin.indexOf('/insights') < admin.indexOf('/settings/services')); ok('admin ops before settings');
}

if (only === 'all' || only === 'queue') {
  const { staffSection, staffNextAction } = await mod('staff/queue.js');
  const now = new Date();
  const future = new Date(Date.now() + 86400000).toISOString(), past = new Date(Date.now() - 86400000).toISOString(), end = new Date(Date.now() + 172800000).toISOString();
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kuala_Lumpur' }).format(now);
  const period = { staff_user_id: 'one', starts_at: future, effective_end: end, released_at: null };
  // The five classifications of the retired ui_product.mjs, renamed: today->active/today, history->completed.
  assert.equal(staffSection({ booking_type: 'GROOMING', status: 'IN_PROGRESS', responsibility_periods: [period] }, 'one', today, now), 'active');
  assert.equal(staffSection({ booking_type: 'BOARDING', status: 'STAYING', current_staff_user_id: 'one', responsibility_periods: [{ ...period, starts_at: past }] }, 'one', today, now), 'active');
  assert.equal(staffSection({ booking_type: 'BOARDING', status: 'STAYING', current_staff_user_id: 'other', responsibility_periods: [period] }, 'one', today, now), 'upcoming');
  assert.equal(staffSection({ booking_type: 'GROOMING', status: 'COMPLETED', responsibility_periods: [period] }, 'one', today, now), 'completed');
  assert.equal(staffSection({ booking_type: 'GROOMING', status: 'CONFIRMED', grooming_start: future, responsibility_periods: [period] }, 'one', today, now), 'upcoming');
  ok('five queue classifications');
  const g = { booking_type: 'GROOMING', status: 'CONFIRMED', grooming_start: future, responsibility_periods: [{ ...period, starts_at: past }] };
  assert.equal(staffNextAction(g, 'one', today, now).action, 'start');
  assert.equal(staffNextAction({ ...g, status: 'IN_PROGRESS' }, 'one', today, now).action, 'complete');
  assert.equal(staffNextAction({ ...g, status: 'SUBMITTED' }, 'one', today, now).action, null);
  assert.equal(staffNextAction({ ...g, responsibility_periods: [period] }, 'one', today, now).action, 'start', 'Grooming has no clock cutoff (17 Nov QA)');
  assert.equal(staffNextAction({ ...g, responsibility_periods: [{ ...period, released_at: past }] }, 'one', today, now).action, null, 'released responsibility cannot act');
  assert.equal(staffNextAction({ booking_type: 'BOARDING', status: 'STAYING', boarding_start: today, boarding_end: '2999-01-01', current_staff_user_id: 'other', responsibility_periods: [period] }, 'one', today, now).action, null, 'future handover cannot act early');
  const b = { booking_type: 'BOARDING', status: 'CONFIRMED', boarding_start: today, boarding_end: '2999-01-01', current_staff_user_id: 'one', responsibility_periods: [{ ...period, starts_at: past }] };
  assert.equal(staffNextAction(b, 'one', today, now).action, 'check-in');
  assert.equal(staffNextAction({ ...b, boarding_start: '2999-01-01' }, 'one', today, now).action, null, 'no check-in before the stay');
  assert.equal(staffNextAction({ ...b, current_staff_user_id: 'other' }, 'one', today, now).action, null);
  assert.deepEqual(staffNextAction({ ...g, status: 'COMPLETED', responsibility_periods: [{ ...period, released_at: past }] }, 'one', today, now), { action: null, reason: '' }, 'QA F-05: own completed work shows no ownership message');
  const s = staffNextAction({ ...b, status: 'STAYING' }, 'one', today, now);
  assert.equal(s.action, 'note'); assert.equal(s.secondary.action, 'check-out');
  ok('next permitted actions');

  // Assignment payloads never carry derived duty windows (re-points the boarding.js regression).
  const { staffAssignmentPayload, decisionPayload } = await mod('admin/payloads.js');
  assert.deepEqual(staffAssignmentPayload({ booking_type: 'BOARDING', status: 'SUBMITTED' }, 'x'), { staff_user_id: 'x' });
  assert.deepEqual(staffAssignmentPayload({ booking_type: 'GROOMING', status: 'CONFIRMED' }, 'x'), { staff_user_id: 'x' });
  assert.deepEqual(Object.keys(staffAssignmentPayload({ booking_type: 'BOARDING', status: 'STAYING' }, 'x', '2026-11-18T10:00:00Z')), ['staff_user_id', 'effective_at']);
  assert.throws(() => staffAssignmentPayload({ booking_type: 'BOARDING', status: 'STAYING' }, null));
  assert.deepEqual(decisionPayload(false), { status: 'REJECTED' });
  ok('payload builders');

  // One vocabulary: every backend status has exactly one label; legacy CHECKED_OUT is not called Completed.
  const { STATUS, customerNextStep, trackerSteps, customerGroup } = await mod('core/labels.js');
  for (const k of ['SUBMITTED', 'CONFIRMED', 'IN_PROGRESS', 'CHECKED_IN', 'STAYING', 'CHECKED_OUT', 'COMPLETED', 'REJECTED', 'CANCELLED']) assert.ok(STATUS[k] && STATUS[k].label, k);
  assert.equal(STATUS.CHECKED_OUT.label, 'Checked out');
  assert.equal(STATUS.CHECKED_IN.label, 'Staying', 'legacy arrival records read as Staying (PS addendum; QA F-17)');
  assert.match(customerNextStep({ status: 'CHECKED_OUT', booking_type: 'BOARDING' }).text, /completion is still pending/);
  assert.equal(customerGroup({ status: 'CHECKED_OUT' }), 'past');
  assert.deepEqual(trackerSteps({ status: 'REJECTED', booking_type: 'GROOMING' }).map((x) => x.state), ['done', 'stopped']);
  assert.equal(trackerSteps({ status: 'STAYING', booking_type: 'BOARDING' }).find((x) => x.state === 'current').label, 'Staying');
  ok('labels and next steps');
  const { isOverdueStay } = await mod('core/labels.js'); const fm = await mod('core/format.js');
  const stay = (status, end) => ({ booking_type: 'BOARDING', status, boarding_end: end });
  assert.equal(isOverdueStay(stay('STAYING', '2026-11-18'), '2026-11-18'), false, 'departure today is not overdue');
  assert.equal(isOverdueStay(stay('STAYING', '2026-11-17'), '2026-11-18'), true);
  assert.equal(isOverdueStay(stay('CHECKED_IN', '2026-11-10'), '2026-11-18'), true);
  for (const s of ['CHECKED_OUT', 'COMPLETED', 'CANCELLED', 'REJECTED', 'CONFIRMED']) assert.equal(isOverdueStay(stay(s, '2026-11-17'), '2026-11-18'), false, s);
  assert.equal(isOverdueStay(stay('STAYING', '2026-11-18'), fm.mytDate('2026-11-18T15:59:59Z')), false, 'still the 18th in MYT');
  assert.equal(isOverdueStay(stay('STAYING', '2026-11-18'), fm.mytDate('2026-11-18T16:00:00Z')), true, 'the 19th in MYT');
  ok('overdue stay rule');

  // Business time: MYT day boundaries and explicit +08:00 instants.
  const f = await mod('core/format.js');
  assert.equal(fm.mytDate('2026-11-18T15:59:59Z'), '2026-11-18'); assert.equal(fm.mytDate('2026-11-18T16:00:00Z'), '2026-11-19');
  assert.equal(f.mytInstant('2026-11-20', '10:00'), '2026-11-20T10:00:00+08:00');
  assert.equal(f.addDays('2026-11-30', 1), '2026-12-01'); assert.equal(f.nights('2026-11-18', '2026-11-20'), 2);
  assert.deepEqual(f.changeVersus(5, 0), { diff: 5, pct: null }); assert.deepEqual(f.changeVersus(15, 10), { diff: 5, pct: 50 });
  assert.equal(f.changeVersus(3, null), null);
  ok('MYT formatting and safe comparisons');

  const { agendaEntries } = await mod('staff/agenda.js');
  const ag = agendaEntries([{ booking_type: 'BOARDING', status: 'CONFIRMED', boarding_start: '2026-11-20', boarding_end: '2026-11-22', responsibility_periods: [
    { staff_user_id: 'one', starts_at: '2026-11-19T16:00:00Z', effective_end: '2026-11-21T16:00:00Z', released_at: null },
    { staff_user_id: 'one', starts_at: '2026-11-19T16:00:00Z', effective_end: '2026-11-21T16:00:00Z', released_at: '2026-11-18T00:00:00Z' }] }], 'one', '2026-11-18', 14, new Date('2026-11-18T00:00:00Z'));
  assert.equal([...ag.values()].flat().length, 2, 'two nights of one unreleased responsibility; released rows excluded');
  ok('agenda');

  const { assignLanes } = await mod('admin/boarding.js');
  const lanes = assignLanes([{ starts_on: '2026-11-18', ends_on: '2026-11-20' }, { starts_on: '2026-11-20', ends_on: '2026-11-22' }, { starts_on: '2026-11-19', ends_on: '2026-11-21' }], '2026-11-18');
  assert.equal(lanes.length, 2, 'end-exclusive stays share a lane; overlaps get a new lane');
  ok('lodging lanes');

  const { presetRange } = await mod('admin/insights.js');
  assert.deepEqual(presetRange('7', '2026-11-18'), ['2026-11-12', '2026-11-18']);
  assert.deepEqual(presetRange('last-month', '2026-11-18'), ['2026-10-01', '2026-10-31']);
  assert.deepEqual(presetRange('month', '2026-11-18'), ['2026-11-01', '2026-11-18']);
  ok('insight periods');

  // Supervisor corrections (Nov 2026): the changed pages still load as modules. Their rendered behaviour (no Admin
  // password field when editing Staff, Staff-only password form, four Insights tiles) is covered in a real browser by
  // .local/corrections_staff_password_e2e.cjs and the capture/E2E runs recorded in docs/evidence/corrections-2026-11/.
  for (const p of ['shared/account.js', 'admin/settings.js', 'admin/insights.js']) assert.equal(typeof (await mod(p)).render, 'function', p);
  ok('corrected pages load');

  const { friendly } = await mod('core/api.js');
  assert.match(friendly(409, 'No active available Staff without a conflicting assignment for the full Grooming duration'), /No groomer is free/);
  assert.equal(friendly(404, 'Permitted Grooming booking not found'), 'This record is not available to you, or it no longer exists.');
  ok('plain-language errors');
}

console.log(`${checks} frontend check groups passed`);
