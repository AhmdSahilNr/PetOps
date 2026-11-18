// Small in-house SVG charts (CSP-safe, no libraries). One y-axis, thin marks, 2px gaps, legend for >= 2 series,
// hover titles on every column, and a table view so values are never colour-only.
import { h } from '../core/dom.js';
import { svgEl } from '../core/icons.js';

function niceMax(v) {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}
function topRounded(x, y, w, hgt, r) {
  const rr = Math.min(r, w / 2, hgt);
  return `M${x},${y + hgt}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + hgt}Z`;
}

export function legend(series) {
  return h('div', { class: 'chart-legend' }, series.map((s) => h('span', {}, h('i', { class: s.swatch }), s.label)));
}

/**
 * Stacked columns. buckets: [{label, ...values}], series: [{key, label, cls, swatch}].
 */
export function stackedColumns(buckets, series, { height = 220, caption, valueLabel = 'bookings' } = {}) {
  const W = 640, H = height, padL = 34, padB = 26, padT = 10, padR = 6;
  const totals = buckets.map((b) => series.reduce((sum, s) => sum + (b[s.key] || 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const band = plotW / Math.max(1, buckets.length);
  const barW = Math.max(4, Math.min(28, band * 0.6));
  const y = (v) => padT + plotH - (v / max) * plotH;
  const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': caption || 'Chart' });
  for (let i = 0; i <= 4; i += 1) {
    const v = (max / 4) * i, yy = y(v);
    svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: yy, y2: yy, class: i === 0 ? 'axis' : 'grid', 'stroke-width': 1 }));
    svg.appendChild(svgEl('text', { x: padL - 6, y: yy + 4, 'text-anchor': 'end' }, String(Math.round(v))));
  }
  const every = Math.ceil(buckets.length / 10);
  buckets.forEach((b, i) => {
    const x = padL + band * i + (band - barW) / 2;
    const g = svgEl('g', { class: 'chart-col' });
    let acc = 0;
    const visible = series.filter((s) => (b[s.key] || 0) > 0);
    series.forEach((s) => {
      const v = b[s.key] || 0;
      if (!v) return;
      const y0 = y(acc), y1 = y(acc + v);
      const isTop = s === visible[visible.length - 1];
      const hgt = Math.max(1, y0 - y1 - (acc > 0 ? 2 : 0)); // 2px surface gap between stacked segments
      g.appendChild(isTop ? svgEl('path', { d: topRounded(x, y1, barW, hgt, 4), class: s.cls }) : svgEl('rect', { x, y: y1, width: barW, height: hgt, class: s.cls }));
      acc += v;
    });
    const hit = svgEl('rect', { x: padL + band * i, y: padT, width: band, height: plotH, fill: 'transparent' });
    hit.appendChild(svgEl('title', {}, `${b.label}: ${series.map((s) => `${s.label} ${b[s.key] || 0}`).join(', ')} (total ${totals[i]} ${valueLabel})`));
    g.appendChild(hit);
    svg.appendChild(g);
    if (i % every === 0) svg.appendChild(svgEl('text', { x: padL + band * i + band / 2, y: H - 8, 'text-anchor': 'middle' }, b.short || b.label));
  });
  const table = h('details', { class: 'chart-table' }, h('summary', { class: 'small strong' }, 'Show as table'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table' }, h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Period'), series.map((s) => h('th', { scope: 'col' }, s.label)), h('th', { scope: 'col' }, 'Total'))),
      h('tbody', {}, buckets.map((b, i) => h('tr', {}, h('td', {}, b.label), series.map((s) => h('td', { class: 'num' }, String(b[s.key] || 0))), h('td', { class: 'num strong' }, String(totals[i]))))))));
  return h('div', { class: 'chart-block' }, series.length > 1 ? legend(series) : null, svg, table);
}

/** Horizontal magnitude bars with values in text ink; optional drill-down per row. */
export function hbars(items, { max } = {}) {
  const top = max || Math.max(1, ...items.map((i) => i.value));
  return h('div', { class: 'hbars' }, items.map((it) => {
    const fill = h('i'); fill.style.setProperty('width', `${Math.round((it.value / top) * 100)}%`);
    if (it.color) fill.style.setProperty('background', it.color);
    return h('div', { class: 'hbar' },
      it.onClick ? h('button', { type: 'button', on: { click: it.onClick } }, it.label) : h('span', {}, it.label),
      h('div', { class: 'meter', role: 'img', 'aria-label': `${it.label}: ${it.value}` }, fill),
      h('span', { class: 'v' }, String(it.value)));
  }));
}

/** Two-part split bar (Grooming vs Boarding) with text values beside it. */
export function split(a, b, labels) {
  const total = a + b;
  const ga = h('i', { class: 'g' }), gb = h('i', { class: 'b' });
  ga.style.setProperty('width', total ? `${(a / total) * 100}%` : '0');
  gb.style.setProperty('width', total ? `${(b / total) * 100}%` : '0');
  if (a && b) gb.style.setProperty('border-left', '2px solid var(--surface)');
  return h('div', { class: 'stack stack--sm' }, h('div', { class: 'split', role: 'img', 'aria-label': `${labels[0]} ${a}, ${labels[1]} ${b}` }, ga, gb),
    h('div', { class: 'row row--between small' }, h('span', {}, h('i', { class: 'sw-grooming', style: { display: 'inline-block', width: '10px', height: '10px', 'border-radius': '3px', 'margin-right': '6px' } }), `${labels[0]} ${a}${total ? ` (${Math.round((a / total) * 100)}%)` : ''}`),
      h('span', {}, h('i', { class: 'sw-boarding', style: { display: 'inline-block', width: '10px', height: '10px', 'border-radius': '3px', 'margin-right': '6px' } }), `${labels[1]} ${b}${total ? ` (${Math.round((b / total) * 100)}%)` : ''}`)));
}
