/* ui/lineage.js — shared renderers for the showpiece views (plan section 6).
 *
 * A plain script: no framework, no build step. It exposes one global,
 * window.Lineage, with the helpers three pages share: escaping, number
 * formatting, the citation card, the ARIA-combobox picker, the chain
 * renderer (renderLine) and the tree-list renderer (renderTreeList).
 * Page-specific code stays inline in each page.
 *
 * Safety: every scraped name and quotation goes through esc(), which
 * escapes by numeric entity. A source or booking link renders only when
 * it starts with http:// or https://.
 */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return '&#' + c.charCodeAt(0) + ';';
    });
  }
  function fmt(n) { return Number(n).toLocaleString('en-US'); }
  function starsTxt(n) { return n > 0 ? new Array(n + 1).join('\u2605') : ''; }
  function starsLabel(n) {
    return n === 1 ? '1 Michelin star' : n + ' Michelin stars';
  }
  function safeUrl(u) { return /^https?:\/\//.test(u || '') ? u : null; }
  function hostOf(u) {
    try { return new URL(u).host; } catch (e) { return u; }
  }

  /* The citation card: person, role, year, the quotation, the outlet and
   * the source link. `v` is one `via` object from the API. */
  function citeCard(v) {
    var u = safeUrl(v.source_url);
    var html = '<div class="who"><a class="pname" href="/explorer?q=' +
      encodeURIComponent(v.person) + '">' + esc(v.person) + '</a>' +
      (v.homonym ? '<span class="hom">possibly two people</span>' : '') +
      (v.role ? '<span class="role">' + esc(v.role) + '</span>' : '') +
      (v.year ? '<span class="yr">' + esc(v.year) + '</span>' : '') + '</div>' +
      '<blockquote class="ev">\u201c' + esc(v.evidence) + '\u201d</blockquote>' +
      '<div class="src">\u00a7 ' +
      (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener">' +
          esc(hostOf(u)) + ' \u2197</a>' : esc(v.outlet || '')) +
      '<span class="srcbadge ' + esc(v.outlet || 'other') + '">' +
      esc(v.outlet || 'source') + '</span></div>';
    return html;
  }

  /* The picker: an ARIA combobox over /api/nodes. `input` is the text
   * field; `onPick(node)` runs when a suggestion is chosen. Requests are
   * guarded by a counter and by the input's current value, so a slow
   * earlier response cannot replace a newer one. */
  function picker(input, onPick, opts) {
    opts = opts || {};
    var kind = opts.kind || 'kitchen';
    var form = input.closest('form');
    var list = document.getElementById(input.getAttribute('aria-controls'));
    var state = { items: [], active: -1, req: 0 };
    var timer = null;

    function close() {
      if (list) list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      state.active = -1;
    }
    function render() {
      if (!list) return;
      list.innerHTML = '';
      state.items.forEach(function (n, i) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        var b = document.createElement('button');
        b.type = 'button';
        b.id = (input.id || 'pk') + '-opt-' + i;
        b.innerHTML = esc(n.name) +
          (n.stars ? ' <span class="st">' + starsTxt(Math.min(n.stars, 3)) + '</span>' : '') +
          (n.joined === false ? ' <span class="nonote">no cited chain yet</span>' : '');
        b.addEventListener('click', function () { pick(n); });
        li.appendChild(b);
        list.appendChild(li);
      });
      list.hidden = state.items.length === 0;
      input.setAttribute('aria-expanded', String(state.items.length > 0));
    }
    function pick(n) {
      close();
      input.value = n.name;
      if (opts.afterPick) opts.afterPick(n);
      onPick(n);
    }
    function move(d) {
      var n = state.items.length;
      if (!n) return;
      state.active = (state.active + d + n) % n;
      list.querySelectorAll('button').forEach(function (b, i) {
        b.setAttribute('aria-selected', String(i === state.active));
      });
      input.setAttribute('aria-activedescendant',
        (input.id || 'pk') + '-opt-' + state.active);
    }

    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) { state.req++; close(); return; }
      var myReq = ++state.req;
      var near = opts.near ? '&near=' + encodeURIComponent(opts.near()) : '';
      timer = setTimeout(function () {
        fetch('/api/nodes?kind=' + kind + '&q=' + encodeURIComponent(q) +
              '&limit=8' + near)
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (myReq !== state.req) return;
            if (input.value.trim() !== q) return;
            state.items = d.nodes || [];
            state.active = -1;
            render();
          })
          .catch(function () {});
      }, 120);
    });
    input.addEventListener('keydown', function (ev) {
      if (!list || list.hidden) {
        if (ev.key === 'Enter') { ev.preventDefault(); if (form) form.requestSubmit(); }
        return;
      }
      if (ev.key === 'ArrowDown') { ev.preventDefault(); move(1); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); move(-1); }
      else if (ev.key === 'Escape') { close(); }
      else if (ev.key === 'Enter') {
        ev.preventDefault();
        if (state.active >= 0) { pick(state.items[state.active]); }
        else if (form) form.requestSubmit();
      }
    });
    return { close: close };
  }

  /* The chain: <ol class="line"> with a station for each kitchen and a hop
   * card between two stations (plan section 9). `data` is the /api/connect
   * payload. `root` is the <ol> element. Horizontal at 900px+ for chains of
   * five hops or fewer (CSS); the markup is the same either way. */
  function renderLine(root, data, opts) {
    opts = opts || {};
    root.innerHTML = '';
    var hops = data.hops || [];
    var stations = [];
    if (!data.found || !hops.length) return;
    hops.forEach(function (h, i) {
      if (h.stint) {
        // a stint row joins the chef to one kitchen: it is the first or
        // the last row of the chain
        if (i === 0) {
          stations.push({ kitchen: h.kitchen, person: h });
        } else {
          // trailing stint: its kitchen is the end station; attach the
          // chef to that station instead of duplicating it
          var last = null;
          for (var j = stations.length - 1; j >= 0; j--) {
            if (!stations[j].hop) { last = stations[j]; break; }
          }
          if (last && !last.person) { last.person = h; }
          else { stations.push({ kitchen: h.kitchen, person: h }); }
        }
        return;
      }
      // a station for the from-kitchen, unless the previous station (or
      // stint) already shows it
      var prev = stations[stations.length - 1];
      if (!prev || prev.hop || prev.kitchen.id !== h.from.id) {
        stations.push({ kitchen: h.from });
      }
      stations.push({ hop: h });
      var next = hops[i + 1];
      if (!next || next.stint) {
        // the end station, or the kitchen a trailing stint will attach to
        stations.push({ kitchen: h.to });
      }
    });

    stations.forEach(function (s) {
      if (s.hop) {
        var li = document.createElement('li');
        li.className = 'hop';
        var h = s.hop;
        var sent = document.createElement('p');
        sent.className = 'sent';
        var v0 = h.via && h.via[0];
        if (v0) {
          // a reverse hop traces from -> to, but the cited person moved
          // the other way: the sentence gives the true direction
          var left = h.direction === 'reverse' ? h.to.name : h.from.name;
          var right = h.direction === 'reverse' ? h.from.name : h.to.name;
          sent.innerHTML = '<a href="/explorer?q=' + encodeURIComponent(v0.person) +
            '">' + esc(v0.person) + '</a> went from ' + esc(left) +
            ' to ' + esc(right) + '.';
        } else {
          sent.textContent = 'No citation recorded for this link.';
        }
        var dirm = document.createElement('span');
        dirm.className = 'dirmark' + (h.direction === 'reverse' ? ' rev' : '');
        dirm.setAttribute('aria-hidden', 'true');
        dirm.textContent = h.direction === 'reverse' ? '\u2190' : '\u2192';
        li.appendChild(dirm);
        li.appendChild(sent);
        if (v0) {
          var role = document.createElement('p');
          role.className = 'role';
          role.innerHTML = (v0.role ? esc(v0.role) : '') +
            (v0.year ? ' <span class="yr">' + esc(v0.year) + '</span>' : '');
          if (role.textContent) li.appendChild(role);
          var ev = document.createElement('blockquote');
          ev.className = 'ev';
          ev.textContent = '\u201c' + (v0.evidence || '') + '\u201d';
          li.appendChild(ev);
          var u = safeUrl(v0.source_url);
          var src = document.createElement('div');
          src.className = 'src';
          src.innerHTML = '\u00a7 ' +
            (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener">' +
                esc(hostOf(u)) + ' \u2197</a>' : esc(v0.outlet || '')) +
            '<span class="srcbadge ' + esc(v0.outlet || 'other') + '">' +
            esc(v0.outlet || 'source') + '</span>';
          li.appendChild(src);
        }
        var rest = (h.via || []).slice(1);
        if (rest.length) {
          var more = document.createElement('details');
          more.className = 'morecite';
          var sum = document.createElement('summary');
          sum.textContent = '+' + rest.length + ' more citation' +
            (rest.length > 1 ? 's' : '') + (h.more_via ? ' · ' + h.more_via +
            ' more on the record' : '');
          more.appendChild(sum);
          var body = document.createElement('div');
          body.className = 'citebody';
          body.innerHTML = h.via.slice(1).map(citeCard).join('');
          more.appendChild(body);
          li.appendChild(more);
        }
        root.appendChild(li);
      } else {
        var st = document.createElement('li');
        st.className = 'station' + (s.kitchen.stars ? ' star' : '');
        var a = document.createElement('a');
        if (s.kitchen.slug) {
          a.href = '/tree?k=' + encodeURIComponent(s.kitchen.slug);
        } else if (s.kitchen.id) {
          a.href = '/tree?k=' + encodeURIComponent(s.kitchen.id);
        } else {
          a.href = '/explorer?q=' + encodeURIComponent(s.kitchen.name);
        }
        a.innerHTML = esc(s.kitchen.name) +
          (s.kitchen.stars ? '<span class="st" aria-label="' +
            esc(starsLabel(s.kitchen.stars)) + '">' +
            starsTxt(Math.min(s.kitchen.stars, 3)) + '</span>' : '');
        st.appendChild(a);
        if (s.person && s.person.stint) {
          var sp = document.createElement('p');
          sp.className = 'stint';
          sp.innerHTML = '<a href="/explorer?q=' +
            encodeURIComponent(s.person.person) + '">' + esc(s.person.person) +
            '</a> is cited at ' + esc(s.kitchen.name) + '.';
          st.appendChild(sp);
          if (s.person.via && s.person.via[0]) {
            var sv = s.person.via[0];
            var bev = document.createElement('blockquote');
            bev.className = 'ev';
            bev.textContent = '\u201c' + (sv.evidence || '') + '\u201d';
            st.appendChild(bev);
            var su = safeUrl(sv.source_url);
            var ssrc = document.createElement('div');
            ssrc.className = 'src';
            ssrc.innerHTML = '\u00a7 ' +
              (su ? '<a href="' + esc(su) + '" target="_blank" rel="noopener">' +
                  esc(hostOf(su)) + ' \u2197</a>' : esc(sv.outlet || '')) +
              '<span class="srcbadge ' + esc(sv.outlet || 'other') + '">' +
              esc(sv.outlet || 'source') + '</span>';
            st.appendChild(ssrc);
          }
        }
        root.appendChild(st);
      }
    });
  }

  /* The tree list: the same tree as nested <ul> lists, every kitchen and
   * citation visible (plan section 8: the non-visual equivalent). */
  function renderTreeList(rootEl, tree, opts) {
    opts = opts || {};
    var phone = !!opts.phone;
    rootEl.innerHTML = '';
    var head = document.createElement('div');
    head.className = 'listhead';
    head.innerHTML = '<p>Every branch of the <b>' + esc(tree.root.name) +
      '</b> tree, as a list: ' + fmt(tree.summary.reach) +
      ' kitchens within three cited moves, each branch a quoted move by a ' +
      'named person. Open a row for its sentence and its article.</p>';
    rootEl.appendChild(head);
    var ul = document.createElement('ul');
    ul.className = 'tl';
    ul.appendChild(listNode(tree.root, tree.children, 0, phone, true));
    rootEl.appendChild(ul);
    var foot = document.createElement('p');
    foot.className = 'lfoot';
    foot.innerHTML = 'Stars: Michelin Guide 2026, San Francisco kitchens only. ' +
      'Generations follow cited moves, not dates: <b>' +
      fmt(tree.corpus.moves_with_year) + '</b> of <b>' +
      fmt(tree.corpus.moves_displayed) + '</b> displayed moves carry a year. ' +
      'Built from the record on ' + esc(tree.built_at || '') + '.';
    rootEl.appendChild(foot);
  }

  function listNode(node, children, depth, phone, isRoot) {
    var li = document.createElement('li');
    if (node.stars) li.className = 'star';
    var row = document.createElement('div');
    row.className = 'row';
    var k = document.createElement('a');
    k.className = 'k';
    k.href = '/tree?k=' + encodeURIComponent(node.slug || node.name);
    k.innerHTML = esc(node.name) +
      (node.stars ? '<span class="st" aria-label="' +
        esc(starsLabel(node.stars)) + '">' +
        starsTxt(Math.min(node.stars, 3)) + '</span>' : '');
    row.appendChild(k);
    if (!isRoot && node.via && node.via.length) {
      var v0 = node.via[0];
      var via = document.createElement('span');
      via.className = 'via';
      via.innerHTML = 'via <a href="/explorer?q=' + encodeURIComponent(v0.person) +
        '">' + esc(v0.person) + '</a>' +
        (v0.homonym ? '<span class="hom"> possibly two people</span>' : '');
      if (v0.role) via.appendChild(document.createTextNode(', ' + v0.role));
      if (v0.year) via.insertAdjacentHTML('beforeend',
        ' <span class="yr">' + esc(v0.year) + '</span>');
      row.appendChild(via);
    }
    li.appendChild(row);
    if (phone && !isRoot && children.length) {
      var more = document.createElement('button');
      more.type = 'button';
      more.className = 'more';
      more.setAttribute('aria-expanded', 'false');
      more.setAttribute('aria-label', 'Show the ' + children.length +
        ' kitchens beyond ' + node.name);
      more.textContent = '+' + children.length;
      li.appendChild(more);
      var sub = document.createElement('ul');
      sub.hidden = true;
      more.addEventListener('click', function () {
        var open = !sub.hidden;
        sub.hidden = open;
        more.setAttribute('aria-expanded', String(!open));
        more.textContent = open ? '+' + children.length : '\u25b4';
        more.setAttribute('aria-label', (open ? 'Show' : 'Hide') +
          ' the ' + children.length + ' kitchens beyond ' + node.name);
      });
      children.forEach(function (c) {
        sub.appendChild(listNode(c, c.children || [], depth + 1, phone, false));
      });
      li.appendChild(sub);
    } else if (children.length) {
      var sub2 = document.createElement('ul');
      children.forEach(function (c) {
        sub2.appendChild(listNode(c, c.children || [], depth + 1, phone, false));
      });
      li.appendChild(sub2);
    }
    if (!isRoot && node.via && node.via.length) {
      var det = document.createElement('details');
      det.className = 'cite';
      var sum = document.createElement('summary');
      sum.textContent = 'the citation';
      det.appendChild(sum);
      var body = document.createElement('div');
      body.className = 'citebody';
      var html = node.via.map(citeCard).join('');
      if (node.more_via) {
        html += '<p class="src">' + node.more_via + ' more citation' +
          (node.more_via > 1 ? 's' : '') + ' on the record.</p>';
      }
      html += '<div class="rowlinks"><a class="textlink" href="/explorer?q=' +
        encodeURIComponent(node.name) + '">Open dossier \u2192</a>' +
        '<a class="textlink" href="/tree?k=' +
        encodeURIComponent(node.slug || node.name) +
        '">Grow the tree from here \u2192</a></div>';
      body.innerHTML = html;
      det.appendChild(body);
      li.appendChild(det);
    }
    return li;
  }

  window.Lineage = {
    esc: esc, fmt: fmt, starsTxt: starsTxt, starsLabel: starsLabel,
    safeUrl: safeUrl, hostOf: hostOf, citeCard: citeCard, picker: picker,
    renderLine: renderLine, renderTreeList: renderTreeList
  };
})();
