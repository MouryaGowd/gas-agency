/* Tiny dependency-free SVG charts. Markup: <div class="chart" data-chart="bars|hbars|line" data-config='{...}'> */
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var tip = document.getElementById('tip');
  var css = function (n) { return 'var(' + n + ')'; };

  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function inrCompact(v) {
    var a = Math.abs(v), s = v < 0 ? '-' : '';
    if (a >= 1e7) return s + '₹' + +(a / 1e7).toFixed(2) + ' Cr';
    if (a >= 1e5) return s + '₹' + +(a / 1e5).toFixed(2) + ' L';
    if (a >= 1e3) return s + '₹' + +(a / 1e3).toFixed(1) + 'k';
    return s + '₹' + Math.round(a);
  }
  function inrFull(v) { return '₹' + Math.round(v).toLocaleString('en-IN'); }
  var fmt = { inr: inrFull, num: function (v) { return Math.round(v).toLocaleString('en-IN'); } };
  var axisFmt = { inr: inrCompact, num: function (v) { return Math.round(v).toLocaleString('en-IN'); } };

  function nice(max) {
    if (max <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(max))), f = max / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  function showTip(evt, html) {
    tip.innerHTML = html; tip.style.display = 'block';
    var x = evt.clientX + 14, y = evt.clientY + 14;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - 14;
    if (y + h > window.innerHeight - 8) y = evt.clientY - h - 14;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  /* vertical grouped bars: config {labels:[], series:[{name,color,values:[]}], unit:'inr'|'num'} */
  function bars(root, c) {
    var W = 640, H = 260, m = { l: 52, r: 8, t: 10, b: 28 };
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': c.title || 'bar chart' }, root);
    var max = nice(Math.max.apply(null, [0].concat.apply([], c.series.map(function (s) { return s.values; }))));
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    for (var i = 0; i <= 4; i++) {
      var y = m.t + ih - (ih * i) / 4;
      el('line', { x1: m.l, x2: W - m.r, y1: y, y2: y, class: i ? 'grid-line' : 'axis-line' }, svg);
      var t = el('text', { x: m.l - 6, y: y + 4, 'text-anchor': 'end' }, svg); t.textContent = axisFmt[c.unit](max * i / 4);
    }
    var n = c.labels.length, slot = iw / n, k = c.series.length;
    var bw = Math.min(22, (slot * 0.72) / k), gap = 2;
    c.labels.forEach(function (lab, idx) {
      var cx = m.l + slot * idx + slot / 2, gw = bw * k + gap * (k - 1);
      if (n <= 12 || idx % 2 === 0) { var tx = el('text', { x: cx, y: H - 8, 'text-anchor': 'middle' }, svg); tx.textContent = lab; }
      c.series.forEach(function (s, si) {
        var v = Math.max(0, s.values[idx]), h = (v / max) * ih, x = cx - gw / 2 + si * (bw + gap);
        if (h > 0) {
          var r = Math.min(4, h, bw / 2);
          el('path', { d: 'M' + x + ' ' + (m.t + ih) + 'V' + (m.t + ih - h + r) + 'Q' + x + ' ' + (m.t + ih - h) + ' ' + (x + r) + ' ' + (m.t + ih - h) +
            'H' + (x + bw - r) + 'Q' + (x + bw) + ' ' + (m.t + ih - h) + ' ' + (x + bw) + ' ' + (m.t + ih - h + r) + 'V' + (m.t + ih) + 'Z', fill: s.color }, svg);
        }
      });
      var hit = el('rect', { x: m.l + slot * idx, y: m.t, width: slot, height: ih, fill: 'transparent' }, svg);
      hit.addEventListener('mousemove', function (e) {
        showTip(e, '<b>' + esc(lab) + '</b>' + c.series.map(function (s) {
          return '<span style="color:' + s.color + '">&#9632;</span> ' + esc(s.name) + ': ' + fmt[c.unit](s.values[idx]);
        }).join('<br>'));
      });
      hit.addEventListener('mouseleave', hideTip);
    });
  }

  /* line with crosshair: config {labels, series:[{name,color,values}], unit} */
  function line(root, c) {
    var W = 640, H = 220, m = { l: 44, r: 12, t: 10, b: 26 };
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': c.title || 'line chart' }, root);
    var max = nice(Math.max.apply(null, [0].concat.apply([], c.series.map(function (s) { return s.values; }))));
    var iw = W - m.l - m.r, ih = H - m.t - m.b, n = c.labels.length;
    for (var i = 0; i <= 4; i++) {
      var y = m.t + ih - (ih * i) / 4;
      el('line', { x1: m.l, x2: W - m.r, y1: y, y2: y, class: i ? 'grid-line' : 'axis-line' }, svg);
      var t = el('text', { x: m.l - 6, y: y + 4, 'text-anchor': 'end' }, svg); t.textContent = axisFmt[c.unit](max * i / 4);
    }
    var X = function (i) { return m.l + (n === 1 ? iw / 2 : (iw * i) / (n - 1)); };
    var Y = function (v) { return m.t + ih - (v / max) * ih; };
    c.labels.forEach(function (lab, i) {
      if (n <= 12 || i % 2 === 0) { var tx = el('text', { x: X(i), y: H - 6, 'text-anchor': 'middle' }, svg); tx.textContent = lab; }
    });
    c.series.forEach(function (s) {
      el('path', { d: s.values.map(function (v, i) { return (i ? 'L' : 'M') + X(i) + ' ' + Y(v); }).join(''), fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round' }, svg);
    });
    var cross = el('line', { y1: m.t, y2: m.t + ih, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden' }, svg);
    var dots = c.series.map(function (s) { return el('circle', { r: 4.5, fill: s.color, stroke: 'var(--surface)', 'stroke-width': 2, visibility: 'hidden' }, svg); });
    var hit = el('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' }, svg);
    hit.addEventListener('mousemove', function (e) {
      var r = svg.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
      var i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / iw) * (n - 1))));
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
      dots.forEach(function (d, si) { d.setAttribute('cx', X(i)); d.setAttribute('cy', Y(c.series[si].values[i])); d.setAttribute('visibility', 'visible'); });
      showTip(e, '<b>' + esc(c.labels[i]) + '</b>' + c.series.map(function (s) {
        return '<span style="color:' + s.color + '">&#9632;</span> ' + esc(s.name) + ': ' + fmt[c.unit](s.values[i]);
      }).join('<br>'));
    });
    hit.addEventListener('mouseleave', function () { hideTip(); cross.setAttribute('visibility', 'hidden'); dots.forEach(function (d) { d.setAttribute('visibility', 'hidden'); }); });
  }

  /* horizontal single-series bars with direct value labels: config {labels, values, color, unit} */
  function hbars(root, c) {
    var rowH = 30, m = { l: 128, r: 78, t: 4, b: 4 }, W = 560, n = c.labels.length, H = m.t + m.b + rowH * n;
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': c.title || 'bar chart' }, root);
    var max = Math.max.apply(null, [1].concat(c.values)), iw = W - m.l - m.r;
    el('line', { x1: m.l, x2: m.l, y1: m.t, y2: H - m.b, class: 'axis-line' }, svg);
    c.labels.forEach(function (lab, i) {
      var y = m.t + rowH * i, w = (c.values[i] / max) * iw, bh = 14, by = y + (rowH - bh) / 2;
      var tl = el('text', { x: m.l - 8, y: y + rowH / 2 + 4, 'text-anchor': 'end', class: 'lbl' }, svg);
      tl.textContent = lab.length > 18 ? lab.slice(0, 17) + '…' : lab;
      if (w > 0) {
        var r = Math.min(4, w, bh / 2);
        el('path', { d: 'M' + m.l + ' ' + by + 'H' + (m.l + w - r) + 'Q' + (m.l + w) + ' ' + by + ' ' + (m.l + w) + ' ' + (by + r) + 'V' + (by + bh - r) + 'Q' + (m.l + w) + ' ' + (by + bh) + ' ' + (m.l + w - r) + ' ' + (by + bh) + 'H' + m.l + 'Z', fill: (c.colors && c.colors[i]) || c.color }, svg);
      }
      var tv = el('text', { x: m.l + w + 6, y: y + rowH / 2 + 4, class: 'lbl' }, svg); tv.textContent = axisFmt[c.unit](c.values[i]);
      var hit = el('rect', { x: 0, y: y, width: W, height: rowH, fill: 'transparent' }, svg);
      hit.addEventListener('mousemove', function (e) { showTip(e, '<b>' + esc(lab) + '</b>' + fmt[c.unit](c.values[i]) + (c.notes ? '<br>' + esc(c.notes[i]) : '')); });
      hit.addEventListener('mouseleave', hideTip);
    });
  }

  var kinds = { bars: bars, line: line, hbars: hbars };
  document.querySelectorAll('[data-chart]').forEach(function (root) {
    try { kinds[root.dataset.chart](root, JSON.parse(root.dataset.config)); }
    catch (e) { root.textContent = 'Chart unavailable'; }
  });
})();
