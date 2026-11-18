// Admin Boarding \u2014 lodging board (accommodation x night) + arrivals, in care and departures with quick actions.
// Every number comes from /admin/boarding/board (unreleased allocations, the same inputs as capacity checks).
import { h, icon, replace } from '../core/dom.js';
import { get, qs } from '../core/api.js';
import { href, replaceQuery } from '../core/router.js';
import { pageHead, panel, empty, skeleton, errorState, pips, button, select, updatedStamp, chip } from '../core/ui.js';
import { mytDate, addDays, daysBetween, fmtDayNum, fmtWeekday, fmtShort, scheduleText } from '../core/format.js';
import { opRow, workspacePath } from './common.js';
import { runAction } from '../staff/actions.js';

export function assignLanes(stays, start) {
  const lanes = [];
  for (const s of [...stays].sort((a, b) => a.starts_on.localeCompare(b.starts_on) || a.ends_on.localeCompare(b.ends_on))) {
    const from = s.starts_on < start ? start : s.starts_on;
    let lane = lanes.find((l) => l.end <= from);
    if (!lane) { lane = { end: '', items: [] }; lanes.push(lane); }
    lane.items.push(s); lane.end = s.ends_on;
  }
  return lanes;
}

export async function render(root, ctx) {
  const today = mytDate();
  let start = /^\d{4}-\d{2}-\d{2}$/.test(ctx.query.start || '') && ctx.query.start >= today ? ctx.query.start : today;
  let nightsN = [7, 14, 21, 28].includes(Number(ctx.query.nights)) ? Number(ctx.query.nights) : 14;
  const host = h('div', {}, skeleton(8));
  const stamp = updatedStamp(() => ctx.refresh());
  root.append(pageHead({ title: 'Boarding', context: stamp.el,
    actions: h('a', { class: 'btn btn--secondary', href: href('/settings/accommodation') }, icon('settings'), 'Boarding setup') }), host);
  let board, ops;
  const load = async () => { [board, ops] = await Promise.all([get(`/admin/boarding/board${qs({ start, nights: nightsN })}`), get('/admin/operations')]); };
  try { await load(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const boardHost = h('div');
  const after = () => ctx.refresh();
  const quick = (b, kind, label, ic, variant = '') => button(label, { size: 'sm', icon: ic, variant, onClick: (e) => runAction(kind, b, e.currentTarget, after) });

  const drawBoard = () => {
    const days = board.units.length ? board.units[0].nights.map((n) => n.date) : Array.from({ length: board.nights }, (_, i) => addDays(board.start, i));
    const unitCol = window.innerWidth < 768 ? 140 : 210;
    // Columns share the width (no empty trailing space) but never shrink below a readable night.
    const template = `${unitCol}px repeat(${days.length}, minmax(52px, 1fr))`;
    const row = (cls, ...cells) => { const r = h('div', { class: ['board__row', cls], role: 'row' }, cells); r.style.setProperty('display', 'grid'); r.style.setProperty('grid-template-columns', template); return r; };
    const dayClass = (d) => { const wd = fmtWeekday(d); return [d === today && 'is-today', (wd === 'Sat' || wd === 'Sun') && 'is-weekend']; };
    const month = new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', month: 'long', year: 'numeric' }).format(new Date(`${board.start}T00:00:00+08:00`));
    const head = row('board__headrow', h('div', { class: 'board__corner', role: 'columnheader' }, month),
      days.map((d) => { const wd = fmtWeekday(d); return h('div', { class: ['board__day', ...dayClass(d)], role: 'columnheader', 'aria-label': `${wd} ${fmtShort(d)}${d === today ? ', today' : ''}` },
        h('span', {}, d === today ? 'Today' : wd), h('b', {}, fmtDayNum(d))); }));
    const unitBlocks = board.units.map((u) => {
      const lanes = assignLanes(u.stays, board.start);
      const tonight = u.nights[0] || { reserved: 0, capacity: u.capacity };
      const unitRow = row('board__unitrow', h('div', { class: 'board__unit', role: 'rowheader' },
        h('b', {}, u.name, u.is_active ? null : h('span', { class: 'tag', style: { 'margin-left': '6px' } }, 'Inactive')),
        h('span', { class: 'sub' }, `${u.category}, ${u.capacity} place${u.capacity === 1 ? '' : 's'}`),
        h('span', { class: ['board__tonight', tonight.capacity && tonight.reserved >= tonight.capacity && 'is-full'] }, `${tonight.reserved} of ${tonight.capacity} on ${fmtShort(board.start)}`)),
      u.nights.map((n) => {
        const covering = u.stays.filter((s) => s.starts_on <= n.date && n.date < s.ends_on);
        const here = covering.filter((s) => s.flags.includes('in_care')).length;
        const requested = covering.filter((s) => s.status === 'SUBMITTED').length;
        return h('div', { class: ['board__cell', n.date === today && 'is-today', n.capacity && n.reserved >= n.capacity && 'is-full'], role: 'cell' },
          pips(n.capacity || u.capacity, n.reserved, here, { requested, label: `${u.name}, ${fmtShort(n.date)}: ${n.reserved} of ${n.capacity} places reserved (${here} in care, ${requested} requested)` }));
      }));
      const laneRows = lanes.map((lane) => {
        const r = row('board__lanerow', h('div', { class: 'board__lanepad', 'aria-hidden': 'true' }),
          // Empty night slots keep every lane on the same grid as the date header (lines, weekend and today shading).
          days.map((d, i) => { const slot = h('div', { class: ['board__slot', ...dayClass(d)], 'aria-hidden': 'true' }); slot.style.setProperty('grid-column', String(i + 2)); slot.style.setProperty('grid-row', '1'); return slot; }));
        for (const s of lane.items) {
          const from = Math.max(0, daysBetween(board.start, s.starts_on));
          const to = Math.min(days.length, daysBetween(board.start, s.ends_on));
          if (to <= from) continue;
          const here = s.flags.includes('in_care');
          const bar = h('a', { class: ['board__bar', here ? 'board__bar--here' : s.status === 'SUBMITTED' ? 'board__bar--requested' : null, s.flags.includes('past_planned_checkout') && 'board__bar--over'],
            href: href(workspacePath(s)), title: `${s.pet_name}: ${scheduleText(s)}`, 'aria-label': `${s.pet_name}, ${s.service_name}, ${scheduleText(s)}, ${here ? 'in care' : s.status === 'SUBMITTED' ? 'requested' : 'confirmed'}` },
          icon(s.flags.includes('past_planned_checkout') ? 'alert' : here ? 'home_care' : s.status === 'SUBMITTED' ? 'clock' : 'bed'),
          h('span', { class: 'board__bar-text' }, `${s.starts_on < board.start ? '\u2190 ' : ''}${s.pet_name}${s.flags.includes('past_planned_checkout') ? ', overdue' : ''}`));
          bar.style.setProperty('grid-column', `${from + 2} / ${to + 2}`);
          bar.style.setProperty('grid-row', '1');
          r.appendChild(bar);
        }
        return r;
      });
      return [unitRow, ...laneRows];
    });
    const totals = row('board__totals', h('div', { class: 'board__unit', role: 'rowheader' }, h('b', {}, 'All accommodation'), h('span', { class: 'sub' }, 'Reserved of active places')),
      board.totals.map((t) => h('div', { class: ['board__cell', t.date === today && 'is-today', t.capacity && t.reserved >= t.capacity && 'is-full'], role: 'cell' }, `${t.reserved}/${t.capacity}`)));
    const boardEl = h('div', { class: 'board', role: 'table', 'aria-label': `Reserved places per night from ${fmtShort(board.start)}` }, head, unitBlocks, totals);
    boardEl.style.setProperty('min-width', `${unitCol + days.length * 52}px`);
    replace(boardHost, board.units.length
      ? h('div', { class: 'board-wrap', tabIndex: 0, 'aria-label': 'Lodging board, scroll sideways for more nights' }, boardEl)
      : h('div', { class: 'panel' }, empty({ icon: 'bed', title: 'No accommodation set up', text: 'Add accommodation units in Settings, Boarding setup, to see the lodging board.' })));
  };

  const startInput = h('input', { class: 'input', type: 'date', value: start, min: today, 'aria-label': 'Board start date' });
  const nightsSel = select([7, 14, 21, 28].map((n) => ({ value: String(n), label: `${n} nights` })), { 'aria-label': 'Nights shown', value: String(nightsN) });
  const reload = async () => {
    replaceQuery({ start, nights: nightsN });
    try { const b2 = await get(`/admin/boarding/board${qs({ start, nights: nightsN })}`); if (!ctx.alive()) return; board = b2; drawBoard(); }
    catch (e) { replace(boardHost, errorState(e, reload)); }
  };
  startInput.addEventListener('change', () => { if (startInput.value) { start = startInput.value < today ? today : startInput.value; reload(); } });
  nightsSel.addEventListener('change', () => { nightsN = Number(nightsSel.value); reload(); });
  const shift = (n) => () => { start = addDays(start, n) < today ? today : addDays(start, n); startInput.value = start; reload(); };

  const arrivals = ops.arrivals_today, care = ops.in_care, departures = ops.departures_due;
  const lane = (title, ic, list, emptyText, action) => [h('div', { class: 'lane-title' }, icon(ic), `${title} (${list.length})`),
    list.length ? list.map((b) => opRow(b, { actions: [action(b), h('a', { class: 'btn btn--ghost btn--sm', href: href(workspacePath(b)) }, 'Open')] }))
      : h('div', { class: 'lane-empty' }, emptyText)];
  replace(host,
    h('div', { class: 'board-toolbar' },
      h('div', { class: 'board-toolbar__nav', role: 'group', 'aria-label': 'Dates shown' },
        button('', { variant: 'secondary', icon: 'chevron_left', ariaLabel: 'Previous week', onClick: shift(-7) }),
        button('Today', { variant: 'secondary', onClick: () => { start = today; startInput.value = today; reload(); } }),
        button('', { variant: 'secondary', icon: 'chevron_right', ariaLabel: 'Next week', onClick: shift(7) }), startInput, nightsSel),
      h('div', { class: 'legend' }, h('span', {}, h('i', { class: 'l-here' }), 'In care'), h('span', {}, h('i', { class: 'l-held' }), 'Confirmed'),
        h('span', {}, h('i', { class: 'l-req' }), 'Requested'), h('span', {}, h('i', { class: 'l-free' }), 'Free'))),
    boardHost,
    h('details', { class: 'board-note' }, h('summary', {}, 'How places are counted'), h('p', {}, board.definition)),
    panel({ title: 'Today', icon: 'sun', flush: true, body: h('div', {},
      lane('Arrivals', 'door_in', arrivals, 'No arrivals today.', (b) => quick(b, 'check-in', 'Check in', 'door_in')),
      lane('In care', 'home_care', care, 'No pets in care.', (b) => quick(b, 'note', 'Update', 'note', 'secondary')),
      lane('Departures due', 'door_out', departures, 'No departures due.', (b) => quick(b, 'check-out', 'Check out', 'door_out'))) }));
  drawBoard();
  void chip;
}
