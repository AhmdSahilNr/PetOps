// One stroke icon family (24 grid, 1.75 stroke, round caps), drawn for PetOps. Built with DOM APIs (CSP-safe).
const NS = 'http://www.w3.org/2000/svg';
const P = (d) => ['path', { d }];
const C = (cx, cy, r) => ['circle', { cx, cy, r }];
const R = (x, y, width, height, rx) => ['rect', { x, y, width, height, rx }];

export const ICONS = {
  home: [P('M3 10.5 12 3l9 7.5'), P('M5 9v11h5v-6h4v6h5V9')],
  calendar: [R(3, 5, 18, 16, 2.5), P('M3 10h18M8 3v4M16 3v4')],
  agenda: [R(3, 5, 18, 16, 2.5), P('M3 10h18M8 3v4M16 3v4M7 14h4M7 17h7')],
  scissors: [C(6, 7, 2.8), C(6, 17, 2.8), P('M8.4 8.6 20 18M8.4 15.4 20 6')],
  bed: [P('M3 6v13M3 14h18v5M21 14v-2.5A2.5 2.5 0 0 0 18.5 9H11v5'), C(7, 11, 1.8)],
  paw: [C(6.5, 10, 1.7), C(10, 6, 1.7), C(14, 6, 1.7), C(17.5, 10, 1.7), P('M8 17c0-2.5 1.8-4.5 4-4.5s4 2 4 4.5c0 1.4-1 2-2.2 1.7a7 7 0 0 0-3.6 0C9 19 8 18.4 8 17z')],
  bell: [P('M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z'), P('M10 20.5a2 2 0 0 0 4 0')],
  users: [C(9, 8, 3.4), P('M2.5 20c.6-3.4 3.3-5.5 6.5-5.5s5.9 2.1 6.5 5.5'), P('M16 4.7a3.4 3.4 0 0 1 0 6.6M18 14.8c2 .7 3.2 2.6 3.5 5.2')],
  user: [C(12, 8, 4), P('M4 21c.8-4 4-6.5 8-6.5s7.2 2.5 8 6.5')],
  chart: [P('M4 4v16h16'), P('M8 16v-4M12 16V8M16 16v-6')],
  history: [P('M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5'), P('M3.5 3.5v5h5M12 7.5v4.8l3 2')],
  settings: [P('M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1'), C(15, 6, 2), C(9, 12, 2), C(17, 18, 2)],
  door_in: [P('M14 4h5v16h-5'), P('M3 12h10M9.5 8.5 13 12l-3.5 3.5')],
  door_out: [P('M10 4H5v16h5'), P('M10 12h10M16.5 8.5 20 12l-3.5 3.5')],
  clock: [C(12, 12, 8.5), P('M12 7.5v4.8l3 2')],
  check: [P('M5 12.5 10 17l9-10')],
  check_circle: [C(12, 12, 8.5), P('M8 12.3l2.8 2.7L16 9.5')],
  x: [P('M6.5 6.5l11 11M17.5 6.5l-11 11')],
  x_circle: [C(12, 12, 8.5), P('M9 9l6 6M15 9l-6 6')],
  ban: [C(12, 12, 8.5), P('M6 6l12 12')],
  alert: [P('M12 4 2.8 19.5h18.4z'), P('M12 10v4M12 17h.01')],
  info: [C(12, 12, 8.5), P('M12 11v5.5M12 7.8h.01')],
  search: [C(11, 11, 6.5), P('M20 20l-4.2-4.2')],
  chevron_right: [P('M9.5 6l6 6-6 6')],
  chevron_left: [P('M14.5 6l-6 6 6 6')],
  chevron_down: [P('M6 9.5l6 6 6-6')],
  plus: [P('M12 5v14M5 12h14')],
  logout: [P('M10 4H5v16h5'), P('M15.5 8l4 4-4 4M19.5 12H10')],
  list: [P('M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01')],
  board: [R(3, 4, 18, 16, 2.5), P('M3 9.5h18M8.5 9.5V20M14.5 9.5V20')],
  play: [P('M8 5.5v13l10.5-6.5z')],
  note: [P('M5 4h10l4 4v12H5z'), P('M15 4v4h4M8.5 12.5h7M8.5 16h4.5')],
  refresh: [P('M19.5 11A7.5 7.5 0 0 0 6.2 7L4 9'), P('M4 4.5V9h4.5M4.5 13A7.5 7.5 0 0 0 17.8 17l2.2-2'), P('M20 19.5V15h-4.5')],
  menu: [P('M4 7h16M4 12h16M4 17h16')],
  arrow_up: [P('M12 19V5M6 11l6-6 6 6')],
  arrow_down: [P('M12 5v14M6 13l6 6 6-6')],
  swap: [P('M4 8h14l-3.5-3.5M20 16H6l3.5 3.5')],
  edit: [P('M4 20h4L19 9l-4-4L4 16z'), P('M13.5 6.5l4 4')],
  sun: [C(12, 12, 4), P('M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4')],
  archive: [R(3, 4, 18, 5, 1.5), P('M5 9v10.5h14V9M10 13h4')],
  key: [C(8, 15, 4), P('M11 12l9-9M17 6l2.5 2.5M14.5 8.5 17 11')],
  tag: [P('M3 12V4h8l9.5 9.5-8 8z'), C(7.5, 8, 1.3)],
  home_care: [P('M3 10.5 12 3l9 7.5V20H3z'), P('M9 20v-5h6v5')],
};

export function icon(name, { label, className } = {}) {
  const spec = ICONS[name] || ICONS.info;
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.75');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  if (className) svg.setAttribute('class', className);
  if (label) { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label); }
  else { svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false'); }
  for (const [tag, attrs] of spec) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    svg.appendChild(el);
  }
  return svg;
}

export function svgEl(tag, attrs = {}, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) el.setAttribute(k, String(v));
  for (const c of children.flat()) if (c != null && c !== false) el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  return el;
}
