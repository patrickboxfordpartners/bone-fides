/* Map layer: SF venue pins on Mapbox light basemap; click a pin → popup with lineage count, website, Reserve link. */
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
      center: SF, zoom: 12.4, attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('error', e => console.warn('map error', e && e.error));

    async function openPop(v) {
      // count edges touching this venue, then render the popup
      let hits = [];
      try {
        const r = await fetch('/api/search?q=' + encodeURIComponent(v.name));
        const d = await r.json();
        hits = d.lineage || [];
      } catch (e) { /* popup still opens */ }
      const el = document.createElement('div');
      el.className = 'mappop';
      const chefs = new Set(hits.map(h => h.person).filter(Boolean));
      el.innerHTML = `
        <div class="t">${esc(v.name)}</div>
        <div class="m">${hits.length} cited move${hits.length===1?'':'s'}${chefs.size ? ' · ' + chefs.size + ' chef' + (chefs.size===1?'':'s') + ' in the graph' : ''}</div>
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
      new mapboxgl.Popup({ offset: 14, maxWidth: '280px' })
        .setLngLat([v.lng, v.lat]).setDOMContent(el).addTo(map);
    }

    map.on('load', () => {
      const markers = [];
      window.__bfHighlight = name => {
        markers.forEach(m => m.el.classList.remove('active'));
        const hit = markers.find(m => m.name === name) ||
                    markers.find(m => m.name.toLowerCase().startsWith(name.toLowerCase()));
        if (hit) hit.el.classList.add('active');
      };
      fetch('/api/venues').then(r => r.json()).then(vd => {
        (vd.venues || []).forEach(v => {
          if (typeof v.lat !== 'number') return;
          const pin = document.createElement('div');
          pin.className = 'pin';
          pin.innerHTML = '<div class="d"></div>';
          pin.addEventListener('click', () => openPop(v));
          const marker = new mapboxgl.Marker({ element: pin }).setLngLat([v.lng, v.lat]).addTo(map);
          markers.push({ name: v.name, el: pin, marker });
        });
      });
    });
  }

  function esc(s){ return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
})();
