// Admin History \u2014 server-filtered booking records (FR-027/028): owner and pet selectors, search, status,
// service, explicit date basis, sort and paging. Totals come from the server, never from a partial page.
import { h, icon, replace } from '../core/dom.js';
import { get, qs } from '../core/api.js';
import { pageHead, select, input, empty, skeleton, errorState, button, field, notice } from '../core/ui.js';
import { mytDate, addDays } from '../core/format.js';
import { bookingTable } from './common.js';

const STATUSES = [['', 'Any status'], ['SUBMITTED', 'Requested'], ['CONFIRMED', 'Confirmed'], ['IN_PROGRESS', 'In progress'], ['STAYING', 'Staying'],
  ['COMPLETED', 'Completed (includes legacy checked out)'], ['REJECTED', 'Rejected'], ['CANCELLED', 'Cancelled']];

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(6));
  root.append(pageHead({ title: 'History' }), host);
  let customers;
  try { customers = await get('/admin/customers'); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const s = { customer_id: ctx.query.customer || '', pet_id: '', service_type: '', status: ctx.query.status || '', search: '', date_basis: 'service', from_date: '', to_date: '', sort: 'newest', offset: 0, limit: 25 };
  const customerSel = select([{ value: '', label: 'All owners' }, ...customers.map((c) => ({ value: c.id, label: c.display_name }))], { value: s.customer_id });
  const petSel = select([{ value: '', label: 'All pets' }], { disabled: true });
  const typeSel = select([{ value: '', label: 'Both services' }, { value: 'GROOMING', label: 'Grooming' }, { value: 'BOARDING', label: 'Boarding' }]);
  const statusSel = select(STATUSES.map(([value, label]) => ({ value, label })), { value: s.status });
  const search = input({ type: 'search', placeholder: 'Owner or pet name', maxLength: 120 });
  const basisSel = select([{ value: 'service', label: 'Service date' }, { value: 'created', label: 'Date requested' }]);
  const from = input({ type: 'date' }); const to = input({ type: 'date' });
  const sortSel = select([{ value: 'newest', label: 'Newest requests first' }, { value: 'oldest', label: 'Oldest requests first' }, { value: 'service', label: 'Service date' }]);
  const results = h('div');
  const run = async () => {
    replace(results, skeleton(5));
    if ((s.from_date && !s.to_date) || (!s.from_date && s.to_date)) { replace(results, notice('warn', 'Choose both dates', 'A period needs a start and an end date.')); return; }
    try {
      const r = await get(`/admin/history${qs({ customer_id: s.customer_id, pet_id: s.pet_id, service_type: s.service_type, status: s.status, search: s.search.trim(),
        date_basis: s.date_basis, from_date: s.from_date, to_date: s.to_date, sort: s.sort, limit: s.limit, offset: s.offset })}`);
      if (!ctx.alive()) return;
      const pages = Math.max(1, Math.ceil(r.total / s.limit)), page = Math.floor(s.offset / s.limit) + 1;
      replace(results, h('div', { class: 'row row--between', style: { margin: '0 0 8px' } }, h('span', { class: 'small strong' }, `${r.total} booking${r.total === 1 ? '' : 's'}`),
        s.from_date ? h('span', { class: 'small muted' }, `Period by ${r.period_basis}`) : null),
      h('section', { class: 'panel' }, r.items.length ? bookingTable(r.items, { caption: 'Booking history' }) : empty({ icon: 'search', title: 'No bookings match', text: 'Try a different owner, status or period.' })),
      pages > 1 ? h('div', { class: 'row row--between', style: { 'margin-top': '12px' } },
        button('Previous', { variant: 'secondary', size: 'sm', icon: 'chevron_left', disabled: page === 1, onClick: () => { s.offset = Math.max(0, s.offset - s.limit); run(); } }),
        h('span', { class: 'small muted' }, `Page ${page} of ${pages}`),
        button('Next', { variant: 'secondary', size: 'sm', disabled: page === pages, onClick: () => { s.offset += s.limit; run(); } })) : null);
    } catch (e) { if (ctx.alive()) replace(results, errorState(e, run)); }
  };
  const loadPets = async () => {
    replace(petSel, h('option', { value: '' }, 'All pets')); petSel.disabled = !s.customer_id; s.pet_id = '';
    if (!s.customer_id) return;
    try { const pets = await get(`/admin/customers/${s.customer_id}/pets`); for (const p of pets) petSel.appendChild(h('option', { value: p.id }, p.name)); } catch { /* keep All pets */ }
  };
  const on = (el, key, after) => el.addEventListener(el.tagName === 'INPUT' && el.type === 'search' ? 'input' : 'change', async () => { s[key] = el.value; s.offset = 0; if (after) await after(); run(); });
  on(customerSel, 'customer_id', loadPets); on(petSel, 'pet_id'); on(typeSel, 'service_type'); on(statusSel, 'status'); on(basisSel, 'date_basis');
  on(from, 'from_date'); on(to, 'to_date'); on(sortSel, 'sort');
  let timer; search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { s.search = search.value; s.offset = 0; run(); }, 300); });
  const preset = (days) => () => { s.to_date = mytDate(); s.from_date = addDays(s.to_date, -(days - 1)); from.value = s.from_date; to.value = s.to_date; s.offset = 0; run(); };
  replace(host,
    h('div', { class: 'panel panel__body', style: { 'margin-bottom': '16px' } },
      h('div', { class: 'filters', style: { 'margin-bottom': '0' } },
        h('div', { class: 'field field--grow search' }, h('label', { class: 'visually-hidden', for: 'h-search' }, 'Search'), icon('search'), Object.assign(search, { id: 'h-search' })),
        field({ label: 'Owner', input: customerSel }), field({ label: 'Pet', input: petSel }), field({ label: 'Service', input: typeSel }), field({ label: 'Status', input: statusSel })),
      h('div', { class: 'filters', style: { margin: '12px 0 0' } }, field({ label: 'Date basis', input: basisSel }), field({ label: 'From', input: from }), field({ label: 'To', input: to }),
        h('div', { class: 'row row--wrap', style: { 'align-self': 'flex-end' } }, button('Last 30 days', { variant: 'secondary', size: 'sm', onClick: preset(30) }),
          button('Clear dates', { variant: 'ghost', size: 'sm', onClick: () => { s.from_date = s.to_date = ''; from.value = to.value = ''; run(); } })),
        field({ label: 'Sort', input: sortSel }))),
    results);
  if (s.customer_id) await loadPets();
  run();
}
