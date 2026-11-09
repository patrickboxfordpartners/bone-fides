/* Map layer: full SF food-business universe + lineage pins.
   Quiet dots (thousands) render as one GeoJSON circle layer; lineaged venues
   get interactive HTML pins (orange), Michelin-starred ones champagne. */
(function () {
  const TOKEN = window.MAPBOX_TOKEN;
  const el = document.getElementById('map');
  if (!TOKEN || !el) { if (el) el.remove(); return; }

  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = 'https://api.mapbox.com/mapbox-gl-js/v3.9.0/mapbox-gl.css';
  document.head.appendChild(css);
  const js = document.createElement('script');
  js.src = 'https://api.mapbox.com/mapbox-gl-js/v3.9.0/mapbox-gl.js';
  js.onload = init;
  document.head.appendChild(js);

  const SF = [-122.433, 37.78];

  function init() {
    mapboxgl.accessToken = TOKEN;
    const map = new mapboxgl.Map({
      container: 'map',
      style: 'mapbox://styles/mapbox/dark-v11',
      center: SF, zoom: 12.0, attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('error', e => console.warn('map error', e && e.error));
    /* Mobile view switch hooks: the map initializes while its container is
       display:none (List is the default mobile view), so a 0×0 canvas needs
       resize() when Map view reveals it — and a camera animation mid-flight
       must stop when List view hides it again. */
    window.__bfMapResize = () => map.resize();
    window.__bfMapStop = () => map.stop();

    async function openPop(v) {
      let hits = [];
      try {
        const r = await fetch('/api/search?q=' + encodeURIComponent(v.lineage_name || v.name));
        const d = await r.json();
        hits = d.lineage || [];
      } catch (e) { /* popup still opens */ }
      const el = document.createElement('div');
      el.className = 'mappop';
      const chefs = new Set(hits.map(h => h.person).filter(Boolean));
      const badge = v.michelin ? '<div class="badge">★ Michelin starred</div>' : '';
      el.innerHTML = `
        <div class="t">${esc(v.name)}</div>${badge}
        <div class="m">${hits.length ? hits.length + ' cited move' + (hits.length===1?'':'s') + (chefs.size ? ' · ' + chefs.size + ' chef' + (chefs.size===1?'':'s') + ' in the graph' : '') : esc(v.permit_type || 'permitted food business')}${v.neighborhood ? ' · ' + esc(v.neighborhood) : ''}</div>
        <div class="links"></div>`;
      const links = el.querySelector('.links');
      if (v.website) {
        const a = document.createElement('a');
        a.href = v.website; a.target = '_blank'; a.rel = 'noopener';
        a.textContent = 'Website';
        links.appendChild(a);
      }
      const res = document.createElement('a');
      res.href = 'https://www.resy.com/city/san-francisco?query=' + encodeURIComponent(v.name);
      res.target = '_blank'; res.rel = 'noopener'; res.className = 'res';
      res.textContent = 'Book on Resy';
      links.appendChild(res);
      if (hits.length) {
        const tr = document.createElement('a');
        tr.href = '/?q=' + encodeURIComponent(v.lineage_name || v.name);
        tr.className = 'trace';
        tr.textContent = 'Trace lineage';
        tr.onclick = ev => { ev.preventDefault(); window.pick(v.lineage_name || v.name); };
        links.appendChild(tr);
      }
      new mapboxgl.Popup({ offset: 14, maxWidth: '300px' })
        .setLngLat([v.lng, v.lat]).setDOMContent(el).addTo(map);
    }

    map.on('load', async () => {
      // ── universe layer: every permitted food business as a quiet dot ──
      // Shares the roster's /api/venues fetch: await the in-flight promise if
      // one exists (the ~1MB payload downloads once, even when the map loads
      // mid-fetch); fall back to a direct fetch when this page never started
      // one (landing-embedded use).
      let all = [];
      try {
        if (Array.isArray(window.__bfVenues)) {
          all = window.__bfVenues.filter(v => typeof v.lat === 'number');
        } else {
          const p = window.__bfVenuesPromise ||
                    (window.__bfVenuesPromise = fetch('/api/venues').then(r => r.json()));
          const vd = await p;
          all = (vd.venues || []).filter(v => typeof v.lat === 'number');
        }
      } catch (e) { /* map still loads empty */ }

      const special = all.filter(v => v.lineaged || v.michelin);
      const quiet = all.filter(v => !v.lineaged && !v.michelin);

      // one source+layer for the thousands of quiet dots (cheap, one GPU layer)
      map.addSource('quiet', {
        type: 'geojson', data: { type: 'FeatureCollection', features: quiet.map(v => ({
          type: 'Feature', geometry: { type: 'Point', coordinates: [v.lng, v.lat] },
          properties: { name: v.name }
        })) } });
      map.addLayer({
        id: 'quiet-dots', type: 'circle', source: 'quiet',
        paint: {
          'circle-radius': 3, 'circle-color': 'rgba(239,230,211,.22)',
          'circle-stroke-color': 'rgba(239,230,211,.10)', 'circle-stroke-width': 1,
        },
      });
      // hover a quiet dot → name tooltip; tap does the same on touch screens
      const tip = new mapboxgl.Popup({ closeButton: false, offset: 8, maxWidth: '200px' });
      map.on('mousemove', 'quiet-dots', e => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features && e.features[0];
        if (f) tip.setLngLat(e.lngLat).setHTML(
          '<div class="quiettip">' + esc(f.properties.name) + '</div>').addTo(map);
      });
      map.on('mouseleave', 'quiet-dots', () => {
        map.getCanvas().style.cursor = ''; tip.remove();
      });
      map.on('click', 'quiet-dots', e => {
        const f = e.features && e.features[0];
        if (f) tip.setLngLat(e.lngLat).setHTML(
          '<div class="quiettip">' + esc(f.properties.name) + '</div>').addTo(map);
      });
      // tap anywhere else on the map closes a touch-opened tooltip
      map.on('click', e => {
        const pts = map.queryRenderedFeatures(e.point, { layers: ['quiet-dots'] });
        if (!pts.length) tip.remove();
      });

      // ── lineage + michelin pins (interactive HTML markers) ──
      const markers = [];
      special.forEach(v => {
        const pin = document.createElement('div');
        const label = v.name + (v.michelin ? ', Michelin starred' : '') + (v.lineaged ? ', cited lineage' : '');
        pin.className = 'pin' + (v.michelin ? ' star' : '');
        pin.title = label;
        pin.setAttribute('role', 'button');
        pin.setAttribute('aria-label', label);
        pin.tabIndex = 0;
        pin.innerHTML = '<div class="d" aria-hidden="true"></div>';
        const activate = () => openPop(v);
        pin.addEventListener('click', activate);
        pin.addEventListener('keydown', ev => {
          if(ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); activate(); }
        });
        new mapboxgl.Marker({ element: pin }).setLngLat([v.lng, v.lat]).addTo(map);
        markers.push(v);
      });

      window.__bfHighlight = name => {
        document.querySelectorAll('.pin.active').forEach(p => p.classList.remove('active'));
        const nl = name.toLowerCase();
        const hit = special.find(v => v.name.toLowerCase() === nl) ||
                    special.find(v => (v.lineage_name || '').toLowerCase() === nl) ||
                    special.find(v => v.name.toLowerCase().startsWith(nl));
        if (hit) {
          const pinEls = document.querySelectorAll('.pin');
          // markers were added in special order; find by index
          const idx = special.indexOf(hit);
          if (pinEls[idx]) {
            pinEls[idx].classList.add('active');
            map.easeTo({ center: [hit.lng, hit.lat], zoom: Math.max(map.getZoom(), 13.5), duration: 600 });
          }
        }
      };
      // a pick that ran before the map finished loading kept its highlight
      // here; flush it now that the pins exist
      if (window.__bfPendingHighlight) {
        const pending = window.__bfPendingHighlight;
        window.__bfPendingHighlight = null;
        window.__bfHighlight(pending);
      }
    });
  }

  function esc(s){ return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
})();
