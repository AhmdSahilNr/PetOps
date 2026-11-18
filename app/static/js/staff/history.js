// Staff history \u2014 completed work this Staff member is still entitled to see (server scope decides).
import { h, replace } from '../core/dom.js';
import { pageHead, panel, empty, skeleton, errorState } from '../core/ui.js';
import { mytDate } from '../core/format.js';
import { loadWork, workRow } from './work.js';
import { workStart, TERMINAL } from './queue.js';

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(5));
  root.append(pageHead({ title: 'My history' }), host);
  let all;
  try { all = await loadWork(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const done = all.filter((b) => TERMINAL.has(b.status)).sort((a, b) => workStart(b) - workStart(a));
  if (!done.length) { replace(host, h('div', { class: 'panel' }, empty({ icon: 'history', title: 'No completed work yet', text: 'Finished grooming and stays you handled will be listed here.' }))); return; }
  const months = new Map();
  for (const b of done) {
    const key = new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', month: 'long', year: 'numeric' }).format(new Date(workStart(b)));
    if (!months.has(key)) months.set(key, []);
    months.get(key).push(b);
  }
  replace(host, h('div', { class: 'stack' }, [...months].map(([m, list]) => panel({ title: m, count: list.length, flush: true,
    body: h('div', { class: 'rows' }, list.map((b) => workRow(b, ctx.user.id, ctx.refresh, mytDate()))) }))));
}
