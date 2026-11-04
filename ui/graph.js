/* Constellation: SVG lineage graph. Landing state shows the whole corpus web;
   after a search it redraws around the queried kitchen with chef orbits. */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.getElementById('graph');
  const W = svg.clientWidth || 1040, H = 520;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

  const state = { nodes: [], links: [], transform: null };
  const NOISE = /^(a |an |various|unnamed|unknown)/i; // extraction noise, not real kitchens
  const isNoise = s => NOISE.test(s || '');

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(n);
    return n;
  }
  function text(x, y, str, cls, anchor) {
    const t = el('text', { x, y, 'class': cls, 'text-anchor': anchor || 'middle' });
    t.textContent = str;
    return t;
  }

  const layers = { venue: 0, person: 1 };
  function render(nodes, links, center) {
    svg.innerHTML = '';
    state.nodes = nodes; state.links = links;
    const gLinks = el('g', {}), gNodes = el('g', {});
    // draw links under nodes
    links.forEach(L => {
      const a = nodes[L.s], b = nodes[L.t];
      el('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        stroke: L.w > 2 ? 'rgba(139,58,47,.5)' : 'rgba(29,26,21,.18)', 'stroke-width': Math.min(2.5, 0.8 + L.w * 0.4) }, gLinks);
    });
    nodes.forEach((n, i) => {
      if (n.kind === 'venue') {
        const c = el('circle', { cx: n.x, cy: n.y, r: n.id === center ? 13 : 6 + Math.min(6, (n.deg || 1)),
          fill: n.id === center ? 'var(--accent)' : '#fff', stroke: 'var(--accent)', 'stroke-width': 2 }, gNodes);
        c.style.cursor = 'pointer';
        c.addEventListener('click', () => pick(n.label));
        c.addEventListener('mouseenter', () => { tip(n.label + ' — click to trace'); c.setAttribute('r', +c.getAttribute('r') + 2); });
        c.addEventListener('mouseleave', () => { tip(''); c.setAttribute('r', n.id === center ? 13 : 6 + Math.min(6, (n.deg || 1))); });
        const below = n.y > H / 2 + 20; // bottom-half venues label below the circle
        text(n.x, below ? n.y + 22 : n.y - 14, n.label.length > 26 ? n.label.slice(0, 24) + '…' : n.label,
             'lbl venue' + (n.id === center ? ' center' : ''), 'middle');
      } else {
        const dot = el('circle', { cx: n.x, cy: n.y, r: 3.5, fill: 'var(--ink)' }, gNodes);
        // person names shown on hover only — keeps the web legible
        const lbl = text(n.x, n.y + 16, n.label, 'lbl person', 'middle');
        lbl.setAttribute('opacity', '0');
        dot.style.cursor = 'pointer';
        dot.addEventListener('mouseenter', () => lbl.setAttribute('opacity', '1'));
        dot.addEventListener('mouseleave', () => lbl.setAttribute('opacity', '0'));
      }
    });
  }

  function tip(s) {
    let t = document.getElementById('g-tip');
    if (!t) {
      t = document.createElement('div');
      t.id = 'g-tip';
      t.style.cssText = 'position:fixed;pointer-events:none;font:12.5px Georgia,serif;color:#6f675a;background:#fffdf8;border:1px solid #d9d1c0;border-radius:2px;padding:4px 10px;z-index:60;transform:translate(-50%,-130%);white-space:nowrap';
      document.body.appendChild(t);
    }
    t.textContent = s;
    t.style.display = s ? 'block' : 'none';
    if (s) {
      t.style.left = (window.event ? window.event.clientX : 0) + 'px';
      t.style.top = (window.event ? window.event.clientY : 0) + 'px';
    }
  }

  /* ── Corpus web (landing state) ───────────────────────────
     venue nodes sized by degree; chefs drawn as small dots between their venues */
  window.__bfCorpus = function (edges) {
    const venues = new Map(), persons = new Map();
    edges.forEach(e => {
      [e.from_venue, e.to_venue].filter(Boolean).forEach(v => {
        if (isNoise(v)) return;
        const n = venues.get(v) || { id: 'v:' + v, label: v, kind: 'venue', deg: 0 };
        n.deg++; venues.set(v, n);
      });
      if (e.person) persons.set(e.person, (persons.get(e.person) || 0) + 1);
    });
    const vn = [...venues.values()].sort((a, b) => b.deg - a.deg).slice(0, 40);
    const vset = new Set(vn.map(n => n.id));
    // circular layout, biggest venues toward the right half for a newsroom-map feel
    vn.forEach((n, i) => {
      const a = (i / vn.length) * Math.PI * 2 - Math.PI / 2;
      n.x = W / 2 + Math.cos(a) * (W * 0.36);
      n.y = H / 2 + Math.sin(a) * (H * 0.36);
    });
    const nodes = vn, links = [];
    persons.forEach((w, p) => {
      const vs = edges.filter(e => e.person === p && e.from_venue && e.to_venue)
        .map(e => ['v:' + e.from_venue, 'v:' + e.to_venue])
        .filter(([a, b]) => vset.has(a) && vset.has(b));
      const uniq = [...new Set(vs.flat())];
      if (uniq.length < 2) return;
      const idx = nodes.length;
      // person dot sits at centroid of their venues
      const px = uniq.reduce((s, id) => s + nodes.find(n => n.id === id).x, 0) / uniq.length;
      const py = uniq.reduce((s, id) => s + nodes.find(n => n.id === id).y, 0) / uniq.length;
      nodes.push({ id: 'p:' + p, label: p, kind: 'person', x: px, y: py });
      uniq.forEach(id => links.push({ s: idx, t: nodes.findIndex(n => n.id === id), w: 1 }));
    });
    // venue-to-venue edges for chefs with 2+ venues become direct links too
    render(nodes, links, null);
  };

  /* ── Focused view: queried kitchen at center, chefs on a ring, their venues outside ── */
  window.__bfFocus = function (q, edges) {
    const ql = q.toLowerCase();
    const touch = edges.filter(e =>
      (e.from_venue || '').toLowerCase().includes(ql) || (e.to_venue || '').toLowerCase().includes(ql));
    const centerName = touch[0] &&
      (((touch[0].from_venue || '').toLowerCase() === ql ? touch[0].from_venue : touch[0].to_venue) ||
       (touch[0].from_venue || touch[0].to_venue));
    if (!centerName) { window.__bfCorpus(edges); return; }
    const center = centerName;
    const chefs = new Map();
    touch.forEach(e => { if (e.person) chefs.set(e.person, (chefs.get(e.person) || 0) + 1); });
    const chefList = [...chefs.keys()].slice(0, 12);
    const nodes = [{ id: 'v:' + center, label: center, kind: 'venue', deg: touch.length }], links = [];
    const cpos = { x: W / 2, y: H / 2 };
    nodes[0].x = cpos.x; nodes[0].y = cpos.y;
    const R1 = 130, R2 = 240;
    const others = new Map(); // other venue -> node idx
    chefList.forEach((p, i) => {
      const a = (i / chefList.length) * Math.PI * 2 - Math.PI / 2;
      const pi = nodes.length;
      nodes.push({ id: 'p:' + p, label: p, kind: 'person', x: cpos.x + Math.cos(a) * R1, y: cpos.y + Math.sin(a) * R1 * 0.72 });
      links.push({ s: 0, t: pi, w: chefs.get(p) });
      // this chef's other venues (from their edges in this result set)
      const vs = new Map();
      touch.filter(e => e.person === p).forEach(e => {
        [e.from_venue, e.to_venue].filter(Boolean).forEach(v => {
          if (v.toLowerCase() !== center.toLowerCase()) vs.set(v, true);
        });
      });
      [...vs.keys()].slice(0, 3).forEach((v, j) => {
        let vi = others.get(v);
        if (vi === undefined) {
          vi = nodes.length;
          const va = a + (j - 1) * 0.55;
          nodes.push({ id: 'v:' + v, label: v, kind: 'venue', deg: 1, x: cpos.x + Math.cos(va) * R2, y: cpos.y + Math.sin(va) * R2 * 0.72 });
          others.set(v, vi);
        }
        links.push({ s: pi, t: vi, w: 1 });
      });
    });
    render(nodes, links, 'v:' + center);
  };

  // landing state: draw the whole corpus web once this script is live
  fetch('/api/search?q=the&size=300').then(r => r.json()).then(d => {
    if (d.lineage && d.lineage.length > 5) window.__bfCorpus(d.lineage);
  }).catch(() => {});
})();
