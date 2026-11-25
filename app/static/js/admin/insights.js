// Admin Insights 2.0 \u2014 period decision support. Every KPI opens /admin/insights/records with the same definition,
// so the list length always equals the number on the tile. No revenue or invented measures.
import { h, icon, replace } from '../core/dom.js';
import { get, qs } from '../core/api.js';
import { replaceQuery, href } from '../core/router.js';
import { pageHead, panel, kpi, segmented, input, button, skeleton, errorState, empty, deltaChip, drawer, field } from '../core/ui.js';
import { mytDate, addDays, fmtShort, fmtDate, changeVersus, fmtStamp, plural } from '../core/format.js';
import { STATUS } from '../core/labels.js';
import { stackedColumns, hbars } from './charts.js';
import { opRow } from './common.js';

// Plain-language definitions (QA F-19); the server keeps the technical definitions in the API response.
const DEFINITIONS = [
  ['Booking requests', 'Bookings requested during the period, whatever has happened to them since. Status and service are their current values.'],
  ['Completed services', 'Grooming and stays actually finished during the period, by the time they were completed.'],
  ['Decision rate', 'Of the confirm or reject decisions recorded in the period, the share that confirmed. A booking confirmed again after a date change counts as another decision; a later cancellation does not undo it. No decisions shows a dash.'],
  ['Cancellations and date changes', 'Each cancellation or date change recorded in the period. A booking whose dates changed twice counts twice; the number of different bookings is shown beside it.'],
  ['Trends', 'Daily for periods up to 31 days, weekly (from Monday) up to 93 days, otherwise monthly. Empty days or weeks are shown as zero.'],
  ['Comparison', 'The same measures for the period of equal length just before. Percentages appear only when the earlier figure is at least 10.'],
  ['Right-now information', 'Pets in care, arrivals and departures, and team workload are live figures, not period measures, so they are shown on Today, the lodging board and Staff work rather than here.'],
  ['Dates and times', 'All dates are Malaysia time. Revenue and other measures PetOps does not record are not shown.'],
];

const PRESETS = [['7', 'Last 7 days'], ['30', 'Last 30 days'], ['month', 'This month'], ['last-month', 'Last month'], ['custom', 'Custom']];

export function presetRange(key, today = mytDate()) {
  if (key === '7') return [addDays(today, -6), today];
  if (key === 'month') return [`${today.slice(0, 8)}01`, today];
  if (key === 'last-month') { const first = `${today.slice(0, 8)}01`; const end = addDays(first, -1); return [`${end.slice(0, 8)}01`, end]; }
  return [addDays(today, -29), today];
}

function bucketLabel(start, size) {
  if (size === 'day') return { label: fmtDate(start), short: fmtShort(start).replace(/\s\w+$/, '') };
  if (size === 'week') return { label: `Week of ${fmtDate(start)}`, short: fmtShort(start) };
  const m = new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', month: 'short', year: '2-digit' }).format(new Date(`${start}T00:00:00+08:00`));
  return { label: m, short: m };
}

export async function render(root, ctx) {
  let preset = PRESETS.some(([k]) => k === ctx.query.period) ? ctx.query.period : '30';
  let [from, to] = preset === 'custom' && ctx.query.from && ctx.query.to ? [ctx.query.from, ctx.query.to] : presetRange(preset);
  const controls = h('div');
  const body = h('div', {}, skeleton(10));
  root.append(pageHead({ title: 'Insights' }), controls, body);

  const fromIn = input({ type: 'date', value: from }); const toIn = input({ type: 'date', value: to, max: mytDate() });
  const drawControls = () => replace(controls, h('div', { class: 'period-bar' },
    h('div', { class: 'stack stack--sm' }, h('span', { class: 'small strong' }, 'Period'), segmented(PRESETS.map(([value, label]) => ({ value, label })), preset, (v) => {
      preset = v; if (v !== 'custom') { [from, to] = presetRange(v); fromIn.value = from; toIn.value = to; load(); } else drawControls(); }, 'Period')),
    preset === 'custom' ? [field({ label: 'From', input: fromIn }), field({ label: 'To', input: toIn }), button('Apply', { onClick: () => {
      if (!fromIn.value || !toIn.value || fromIn.value > toIn.value) return; from = fromIn.value; to = toIn.value; load(); } })] : null,
    h('p', { class: 'basis' }, `${fmtDate(from)} to ${fmtDate(to)}, Malaysia time. Each measure uses the date it happened: requests by date requested, completions by completion time, decisions and changes by when they were recorded.`)));

  const records = async (title, metric, extra = {}, definition) => {
    const { body: b } = drawer({ title });
    b.append(skeleton(4));
    try {
      const r = await get(`/admin/insights/records${qs({ metric, from_date: from, to_date: to, ...extra })}`);
      replace(b, h('p', { class: 'small muted' }, `${plural(r.total, 'record')}. ${definition || ''}`),
        r.items.length ? h('div', { class: 'panel' }, h('div', { class: 'rows' }, r.items.map((x) => h('div', {}, opRow(x), h('div', { class: 'small muted', style: { padding: '0 20px 10px 104px' } }, `Counted at ${fmtStamp(x.counted_at)}`)))))
          : h('div', { class: 'panel' }, empty({ icon: 'search', title: 'No records in this period', compact: true })));
    } catch (e) { replace(b, errorState(e)); }
  };

  async function load() {
    replaceQuery(preset === 'custom' ? { period: preset, from, to } : { period: preset });
    drawControls();
    replace(body, skeleton(10));
    // Supervisor correction (Nov 2026): a simpler period review. Only the presentation changed: the same
    // /admin/dashboard figures and /admin/insights/records drill-downs (same definitions) are used.
    // Right-now information (in care, occupancy, workload) stays on Today, the lodging board and Staff work.
    let d;
    try { d = await get(`/admin/dashboard${qs({ from_date: from, to_date: to })}`); }
    catch (e) { if (ctx.alive()) replace(body, errorState(e, load)); return; }
    if (!ctx.alive()) return;
    const cur = d.period_totals, prev = d.previous_period;
    const delta = (k) => (prev ? deltaChip(changeVersus(cur[k], prev[k])) : null);
    const rate = d.confirmation_decisions.confirmation_rate_percent;
    const prevRate = prev ? prev.decision_rate_percent : null;
    const rateDelta = rate !== null && prevRate !== null && prevRate !== undefined ? h('span', { class: 'delta' }, icon(rate >= prevRate ? 'arrow_up' : 'arrow_down'), `${rate >= prevRate ? '+' : ''}${Math.round((rate - prevRate) * 10) / 10} points vs previous`) : null;
    const trend = d.trend;
    const tb = trend ? trend.buckets.map((b) => ({ ...b, ...bucketLabel(b.period_start, trend.bucket_size) })) : [];
    const statusRows = Object.entries(d.bookings_by_status).filter(([, v]) => v > 0).map(([k, v]) => ({ label: STATUS[k] ? STATUS[k].label : k, value: v,
      onClick: () => records(`Requested in period, now ${STATUS[k] ? STATUS[k].label : k}`, 'created', { status: k }) }));
    const figure = ([k, v, m]) => h('div', {}, h('dt', {}, k),
      h('dd', {}, h('button', { type: 'button', class: 'link-btn num', style: { 'font-size': '1.5rem', color: 'var(--ink)' }, on: { click: () => records(k, m) } }, String(v))));
    replace(body,
      h('section', { class: 'kpis kpis--four', 'aria-label': 'Key measures' },
        kpi({ label: 'Booking requests', icon: 'list', value: d.total_bookings, meaning: `${d.bookings_by_type.GROOMING} grooming, ${d.bookings_by_type.BOARDING} boarding`, delta: delta('bookings_created'),
          onClick: () => records('Booking requests', 'created', {}, 'Every booking requested in the period, shown with its current status.') }),
        kpi({ label: 'Completed services', icon: 'check_circle', value: cur.completed_services, meaning: `${d.completed_services_by_type.GROOMING} grooming, ${plural(d.completed_services_by_type.BOARDING, 'stay')}`,
          delta: delta('completed_services'), onClick: () => records('Completed services', 'completed', {}, 'Every grooming appointment or stay finished in the period, by completion time.') }),
        kpi({ label: 'Decision rate', icon: 'check', value: rate === null ? null : `${Math.round(rate)}%`, meaning: rate === null ? 'No decisions in this period' : `${d.confirmation_decisions.confirmed} confirmed of ${d.confirmation_decisions.decided} decisions`,
          delta: rateDelta, onClick: () => records('Confirmations', 'decisions_confirmed', {}, 'Every confirmation recorded in the period. A booking confirmed again after a date change appears once per confirmation.') }),
        kpi({ label: 'Cancellations', icon: 'ban', value: cur.cancellations, meaning: 'Bookings cancelled in the period', delta: delta('cancellations'),
          onClick: () => records('Cancellations', 'cancellations', {}, 'Every booking cancelled in the period, by the time of cancellation.') })),
      prev ? h('p', { class: 'small muted', style: { 'margin-top': '8px' } }, `Compared with ${fmtDate(prev.from_date)} to ${fmtDate(prev.to_date)} (same length). Percentages are shown only when the earlier value is 10 or more.${d.period_complete ? '' : ' This period includes today, so it may still change.'}`) : null,
      h('div', { class: 'insight-grid' },
        h('div', { class: 'span-7' }, panel({ title: 'Booking requests over time', icon: 'chart', body: trend ? stackedColumns(tb,
          [{ key: 'created_grooming', label: 'Grooming', cls: 'c-grooming', swatch: 'sw-grooming' }, { key: 'created_boarding', label: 'Boarding', cls: 'c-boarding', swatch: 'sw-boarding' }],
          { caption: `Booking requests per ${trend.bucket_size}`, valueLabel: 'requests' }) : empty({ icon: 'chart', title: 'Choose a period of up to two years to see trends', compact: true }) })),
        h('div', { class: 'span-5' }, panel({ title: 'Completed by service', icon: 'check_circle', body: d.completed_by_service.length
          ? hbars(d.completed_by_service.map((s) => ({ label: s.name, value: s.completed, color: s.service_type === 'GROOMING' ? 'var(--series-grooming)' : 'var(--series-boarding)' })))
          : empty({ icon: 'check_circle', title: 'Nothing completed in this period', compact: true }) })),
        h('details', { class: 'span-12 panel more-detail' }, h('summary', { class: 'panel__head' }, h('h2', {}, 'More detail')),
          h('div', { class: 'panel__body stack' },
            h('div', { class: 'stack stack--sm' }, h('h3', {}, 'Where those requests are now'),
              statusRows.length ? hbars(statusRows) : empty({ icon: 'list', title: 'No requests in this period', compact: true })),
            h('div', { class: 'stack stack--sm' }, h('h3', {}, 'Decisions and date changes'),
              h('dl', { class: 'facts' }, [['Confirmed', d.confirmation_decisions.confirmed, 'decisions_confirmed'], ['Rejected', d.confirmation_decisions.rejected, 'decisions_rejected'],
                ['Date changes', cur.reschedules, 'reschedules']].map(figure)),
              h('p', { class: 'small muted' }, `${plural(cur.rescheduled_bookings, 'booking')} had their dates changed in this period.`)),
            h('div', { class: 'stack stack--sm' }, h('h3', {}, 'How each measure is defined'),
              h('dl', { class: 'stack stack--sm' }, DEFINITIONS.map(([title, text]) => h('div', {},
                h('dt', { class: 'strong' }, title), h('dd', { class: 'muted' }, text))))),
            h('p', { class: 'small muted' }, 'For right-now information see ', h('a', { href: href('/today') }, 'Today'), ', ',
              h('a', { href: href('/boarding') }, 'the lodging board'), ' and ', h('a', { href: href('/staff-work') }, 'Staff work'), '.')))));
  }
  load();
}
