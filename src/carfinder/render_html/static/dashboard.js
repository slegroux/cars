(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────────
  var SERVER_MODE = window.location.protocol !== 'file:' && window.location.hostname === 'localhost';

  // Canonical body-type buckets shown as filter checkboxes. Listings whose
  // raw body_type is a case variant (Craigslist lowercases) or off-list value
  // (Convertible, Minivan, Pickup…) are folded into 'Unknown' so they remain
  // visible instead of being silently filtered out.
  var BODY_TYPES = ['SUV','Sedan','Wagon','Hatchback','Coupe','Truck','Van','Unknown'];
  var BODY_CANON = {};
  BODY_TYPES.forEach(function(b) { BODY_CANON[b.toLowerCase()] = b; });
  function canonBodyType(bt) {
    if (bt == null || bt === '') return 'Unknown';
    return BODY_CANON[String(bt).toLowerCase()] || 'Unknown';
  }

  window.dashboardState = {
    source: 'all',
    minScore: 0,
    bodyTypes: new Set(BODY_TYPES),
    mileMin: 0,
    mileMax: 200000,
    yearMin: 2008,
    sortCol: 'score',
    sortDir: 'desc',
    page: 1,
    pageSize: 25,
    priceMin: 0,
    priceMax: 20000,
    search: '',
  };

  var S = window.dashboardState;
  var scatterChart = null;
  var openRadarChart = null;
  var openRowId = null;

  // ── Filtering ──────────────────────────────────────────────────────────────
  function searchHaystack(d) {
    return [d.make, d.model, d.trim, d.body_type, d.source, d.location,
            d.description, d.year, d.seller_type, d.transmission, d.url]
      .filter(function(v) { return v != null && v !== ''; })
      .join(' ').toLowerCase();
  }

  function matchesFilter(d) {
    if (S.source !== 'all' && d.source !== S.source) return false;
    if (d.score < S.minScore) return false;
    if (!S.bodyTypes.has(canonBodyType(d.body_type))) return false;
    var pr = d.asking_price != null ? d.asking_price : 0;
    if (pr < S.priceMin || pr > S.priceMax) return false;
    var mi = d.mileage != null ? d.mileage : 0;
    if (mi < S.mileMin || mi > S.mileMax) return false;
    var yr = d.year != null ? d.year : 0;
    if (yr < S.yearMin) return false;
    if (S.search) {
      var hay = searchHaystack(d);
      // AND across whitespace-separated terms so "honda civic" requires both.
      var terms = S.search.split(/\s+/);
      for (var i = 0; i < terms.length; i++) {
        if (terms[i] && hay.indexOf(terms[i]) === -1) return false;
      }
    }
    return true;
  }

  function filteredListings() {
    return LISTINGS.filter(matchesFilter);
  }

  // ── Score colour ───────────────────────────────────────────────────────────
  function scoreClass(score) {
    if (score >= 75) return 'score-green';
    if (score >= 60) return 'score-yellow';
    if (score >= 45) return 'score-orange';
    return 'score-red';
  }

  function sourceChipClass(src) {
    if (src === 'craigslist') return 'source-craigslist';
    if (src === 'carmax')     return 'source-carmax';
    if (src === 'carscom')    return 'source-carscom';
    if (src === 'kbb')        return 'source-kbb';
    return 'source-other';
  }

  // ── Format helpers ─────────────────────────────────────────────────────────
  function fmtPrice(p) { return p != null ? '$' + Math.round(p).toLocaleString() : '—'; }
  function fmtMiles(m) { return m != null ? m.toLocaleString() + ' mi' : '—'; }
  function fmtDist(d)  { return d != null ? d.toFixed(0) + ' mi' : '—'; }

  // ── OLS value line ─────────────────────────────────────────────────────────
  function olsLine(pts) {
    var n = pts.length;
    if (n < 2) return null;
    var sumX = 0, sumY = 0, sumXX = 0, sumXY = 0;
    for (var i = 0; i < n; i++) {
      sumX  += pts[i].x; sumY  += pts[i].y;
      sumXX += pts[i].x * pts[i].x;
      sumXY += pts[i].x * pts[i].y;
    }
    var denom = n * sumXX - sumX * sumX;
    if (Math.abs(denom) < 1e-9) return null;
    var m = (n * sumXY - sumX * sumY) / denom;
    var b = (sumY - m * sumX) / n;
    var xs = pts.map(function(p){ return p.x; });
    var xMin = Math.min.apply(null, xs);
    var xMax = Math.max.apply(null, xs);
    return [{ x: xMin, y: m * xMin + b }, { x: xMax, y: m * xMax + b }];
  }

  // Mileage → point size (inverse: low mileage = bigger)
  function mileageSize(mi) {
    if (mi == null) return 7;
    if (mi < 30000)  return 13;
    if (mi < 60000)  return 11;
    if (mi < 90000)  return 9;
    if (mi < 120000) return 7;
    return 5;
  }

  // ── Scatter chart ──────────────────────────────────────────────────────────
  function buildScatter() {
    var fl = filteredListings();
    var pts = fl.map(function(d, idx) {
      return {
        x: d.asking_price,
        y: d.score,
        r: mileageSize(d.mileage),
        dataIdx: idx,
        id: d.id,
      };
    });

    var clPts  = pts.filter(function(p){ return fl[p.dataIdx].source === 'craigslist'; });
    var cmPts  = pts.filter(function(p){ return fl[p.dataIdx].source === 'carmax'; });
    var kbbPts = pts.filter(function(p){ return fl[p.dataIdx].source === 'kbb'; });
    var othPts = pts.filter(function(p){ return fl[p.dataIdx].source !== 'craigslist' && fl[p.dataIdx].source !== 'carmax' && fl[p.dataIdx].source !== 'kbb'; });

    var allXY = fl.filter(function(d){ return d.asking_price != null; }).map(function(d){ return { x: d.asking_price, y: d.score }; });
    var ols = olsLine(allXY);

    var datasets = [
      {
        label: 'Craigslist',
        data: clPts,
        backgroundColor: 'rgba(37,99,235,0.65)',
        borderColor: 'rgba(37,99,235,0.9)',
        borderWidth: 1,
      },
      {
        label: 'CarMax',
        data: cmPts,
        backgroundColor: 'rgba(234,88,12,0.65)',
        borderColor: 'rgba(234,88,12,0.9)',
        borderWidth: 1,
      },
      {
        label: 'KBB',
        data: kbbPts,
        backgroundColor: 'rgba(202,138,4,0.65)',
        borderColor: 'rgba(202,138,4,0.9)',
        borderWidth: 1,
      },
    ];
    if (othPts.length) {
      datasets.push({
        label: 'Other',
        data: othPts,
        backgroundColor: 'rgba(100,100,100,0.55)',
        borderColor: 'rgba(100,100,100,0.8)',
        borderWidth: 1,
      });
    }
    if (ols) {
      datasets.push({
        label: 'Value line',
        type: 'line',
        data: ols,
        borderColor: 'rgba(180,160,120,0.4)',
        borderWidth: 1.5,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
        tension: 0,
        order: -1,
      });
    }

    var canvasEl = document.getElementById('scatterCanvas');
    // Bail out cleanly if the canvas is missing or Chart.js failed to load
    // (the vendored chart.umd.min.js can be absent for offline exports).
    if (!canvasEl || typeof Chart === 'undefined') return;
    var ctx = canvasEl.getContext('2d');
    if (scatterChart) { scatterChart.destroy(); scatterChart = null; }

    scatterChart = new Chart(ctx, {
      type: 'bubble',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 120 },
        plugins: {
          legend: {
            labels: { font: { size: 11 }, color: '#6b6861', usePointStyle: true, pointStyleWidth: 8 }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var raw = ctx.raw;
                var d = fl[raw.dataIdx];
                if (!d) return '';
                var yr  = d.year || '?';
                var mk  = d.make || '';
                var mo  = d.model || '';
                var sc  = d.display_score;
                var pr  = fmtPrice(d.asking_price);
                var mi  = fmtMiles(d.mileage);
                var src = d.source;
                var conf = d.confidence;
                return [yr + ' ' + mk + ' ' + mo, 'Score: ' + sc + '  (' + conf + ')', 'Price: ' + pr, 'Miles: ' + mi, 'Source: ' + src];
              },
            },
            backgroundColor: 'rgba(26,25,23,0.92)',
            titleFont: { size: 11 },
            bodyFont: { size: 11 },
            padding: 10,
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Asking price ($)', font: { size: 11 }, color: '#6b6861' },
            ticks: { font: { size: 10 }, color: '#9c9890', callback: function(v){ return '$' + (v/1000).toFixed(0) + 'k'; } },
            grid: { color: '#e5e3df' },
          },
          y: {
            title: { display: true, text: 'Score', font: { size: 11 }, color: '#6b6861' },
            min: 0, max: 100,
            ticks: { font: { size: 10 }, color: '#9c9890' },
            grid: { color: '#e5e3df' },
          },
        },
        onClick: function(event, elements) {
          if (!elements.length) return;
          var el = elements[0];
          var raw = scatterChart.data.datasets[el.datasetIndex].data[el.index];
          if (raw && raw.id) {
            scrollToRow(raw.id);
          }
        },
      },
    });
  }

  // ── Table rendering ────────────────────────────────────────────────────────
  var COLS = ['photo','year','make','model','trim','body_type','mileage','asking_price','score','source','distance_miles','url'];
  var COL_LABELS = { photo:'Photo', year:'Year', make:'Make', model:'Model', trim:'Trim', body_type:'Body',
                     mileage:'Miles', asking_price:'Price', score:'Score', source:'Src', distance_miles:'Dist', url:'View' };
  var SORTABLE = new Set(['year','make','model','mileage','asking_price','score','source']);

  function renderTable() {
    var fl = filteredListings();

    // Sort
    fl.sort(function(a, b) {
      var av = a[S.sortCol], bv = b[S.sortCol];
      if (av == null) av = S.sortDir === 'asc' ? Infinity : -Infinity;
      if (bv == null) bv = S.sortDir === 'asc' ? Infinity : -Infinity;
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av < bv) return S.sortDir === 'asc' ? -1 : 1;
      if (av > bv) return S.sortDir === 'asc' ? 1 : -1;
      return 0;
    });

    var total = fl.length;
    var start = S.pageSize > 0 ? (S.page - 1) * S.pageSize : 0;
    var end   = S.pageSize > 0 ? start + S.pageSize : total;
    var paginated = fl.slice(start, end);

    var tbody = document.getElementById('listingsTbody');
    tbody.innerHTML = '';

    var countEl = document.getElementById('tableCount');
    if (countEl) countEl.textContent = fl.length + ' listing' + (fl.length !== 1 ? 's' : '');

    // Update sort arrow classes on headers
    document.querySelectorAll('table.listings thead th').forEach(function(th) {
      var col = th.dataset.col;
      th.classList.remove('sort-asc', 'sort-desc');
      if (col === S.sortCol) th.classList.add(S.sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
    });

    paginated.forEach(function(d, i) {
      // Data row
      var tr = document.createElement('tr');
      tr.className = 'data-row';
      tr.dataset.id = d.id;

      // Photo
      var tdPhoto = document.createElement('td');
      tdPhoto.className = 'col-photo';
      if (d.first_photo) {
        var img = document.createElement('img');
        img.src = d.first_photo;
        img.loading = 'lazy';
        img.alt = (d.year || '') + ' ' + (d.make || '') + ' ' + (d.model || '');
        img.addEventListener('click', function(e) {
          e.stopPropagation();
          openLightbox(d.photos, 0);
        });
        tdPhoto.appendChild(img);
      } else {
        var ph = document.createElement('div');
        ph.className = 'photo-placeholder';
        ph.textContent = 'no photo';
        tdPhoto.appendChild(ph);
      }
      tr.appendChild(tdPhoto);

      // Year
      tr.appendChild(_td(d.year || '—'));
      // Make
      tr.appendChild(_td(d.make || '—'));
      // Model
      tr.appendChild(_td(d.model || '—'));
      // Trim
      tr.appendChild(_td(d.trim || '—'));
      // Body
      tr.appendChild(_td(d.body_type || '—'));
      // Miles
      tr.appendChild(_td(fmtMiles(d.mileage)));
      // Price
      tr.appendChild(_td(fmtPrice(d.asking_price)));

      // Score
      var tdScore = document.createElement('td');
      var scoreSpan = document.createElement('span');
      scoreSpan.className = 'score-cell ' + scoreClass(d.score);
      scoreSpan.textContent = d.display_score;
      tdScore.appendChild(scoreSpan);
      tr.appendChild(tdScore);

      // Source
      var tdSrc = document.createElement('td');
      var srcSpan = document.createElement('span');
      srcSpan.className = 'source-chip ' + sourceChipClass(d.source);
      srcSpan.textContent = d.source === 'craigslist' ? 'CL' : d.source === 'carmax' ? 'CMax' : d.source === 'carscom' ? 'Cars' : d.source === 'kbb' ? 'KBB' : d.source;
      tdSrc.appendChild(srcSpan);
      tr.appendChild(tdSrc);

      // Distance
      tr.appendChild(_td(fmtDist(d.distance_miles)));

      // View link
      var tdView = document.createElement('td');
      if (d.url && /^https?:\/\//i.test(d.url)) {
        var a = document.createElement('a');
        a.href = d.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'ext-link';
        a.title = 'Open listing';
        a.textContent = '↗';
        a.addEventListener('click', function(e){ e.stopPropagation(); });
        tdView.appendChild(a);
      } else if (d.source === 'manual' && d.description) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ext-link notes-btn';
        btn.title = 'View notes';
        btn.textContent = '📝';
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          openNotesModal(d);
        });
        tdView.appendChild(btn);
      } else {
        tdView.textContent = '—';
      }
      tr.appendChild(tdView);

      // Delete (col hidden via body.server-mode CSS unless we're in server mode;
      // the × button only renders for manual entries since other sources can be re-scraped).
      var tdDel = document.createElement('td');
      tdDel.className = 'col-actions';
      if (SERVER_MODE && d.source === 'manual') {
        var delBtn = document.createElement('button');
        delBtn.className = 'del-btn';
        delBtn.title = 'Remove listing';
        delBtn.textContent = '×';
        delBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          deleteRow(d.id, tr, expandRow);
        });
        tdDel.appendChild(delBtn);
      }
      tr.appendChild(tdDel);

      // Row click → expand radar
      tr.addEventListener('click', function() { toggleExpand(d, tr, expandRow); });

      tbody.appendChild(tr);

      // Expand row (hidden by default)
      var expandRow = document.createElement('tr');
      expandRow.className = 'expand-row';
      expandRow.dataset.parentId = d.id;
      var expandTd = document.createElement('td');
      // Span every header cell so the detail row stays full-width even when the
      // actions column is shown in server mode.
      expandTd.colSpan = document.querySelectorAll('table.listings thead th').length || 12;
      expandRow.appendChild(expandTd);
      tbody.appendChild(expandRow);
    });

    renderPagination(total);
  }

  function _td(text) {
    var td = document.createElement('td');
    td.textContent = text;
    return td;
  }

  // ── Pagination ─────────────────────────────────────────────────────────────
  function renderPagination(total) {
    var el = document.getElementById('pagination');
    if (!el) return;
    el.innerHTML = '';

    var totalPages = S.pageSize > 0 ? Math.ceil(total / S.pageSize) : 1;
    if (S.page > totalPages) S.page = Math.max(1, totalPages);

    // Per-page selector (right side via margin-left:auto on first element)
    var sel = document.createElement('select');
    sel.className = 'page-size-sel';
    [10, 25, 50, 100].forEach(function(n) {
      var opt = document.createElement('option');
      opt.value = n; opt.textContent = n + ' per page';
      if (n === S.pageSize) opt.selected = true;
      sel.appendChild(opt);
    });
    var optAll = document.createElement('option');
    optAll.value = 0; optAll.textContent = 'All';
    if (S.pageSize === 0) optAll.selected = true;
    sel.appendChild(optAll);
    sel.addEventListener('change', function() {
      S.pageSize = +this.value; S.page = 1;
      renderTable();
    });
    el.appendChild(sel);

    if (S.pageSize <= 0 || total <= S.pageSize) return;

    var prev = document.createElement('button');
    prev.className = 'page-btn';
    prev.textContent = '← Prev';
    prev.disabled = S.page <= 1;
    prev.addEventListener('click', function() {
      if (S.page > 1) { S.page--; renderTable(); window.scrollTo({top: document.getElementById('listingsTbody').getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth'}); }
    });
    el.appendChild(prev);

    var info = document.createElement('span');
    info.className = 'page-info';
    var from = (S.page - 1) * S.pageSize + 1;
    var to   = Math.min(S.page * S.pageSize, total);
    info.textContent = from + '–' + to + ' of ' + total;
    el.appendChild(info);

    var next = document.createElement('button');
    next.className = 'page-btn';
    next.textContent = 'Next →';
    next.disabled = S.page >= totalPages;
    next.addEventListener('click', function() {
      if (S.page < totalPages) { S.page++; renderTable(); window.scrollTo({top: document.getElementById('listingsTbody').getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth'}); }
    });
    el.appendChild(next);
  }

  // ── Expand / radar ─────────────────────────────────────────────────────────
  function toggleExpand(d, dataRow, expandRow) {
    var isOpen = expandRow.classList.contains('open');

    // Close any open row first
    document.querySelectorAll('tr.expand-row.open').forEach(function(r) {
      r.classList.remove('open');
      r.querySelector('td').innerHTML = '';
    });
    document.querySelectorAll('tr.data-row').forEach(function(r) {
      r.classList.remove('highlighted');
    });
    if (openRadarChart) { openRadarChart.destroy(); openRadarChart = null; }
    openRowId = null;

    if (isOpen) return; // was open → just close

    expandRow.classList.add('open');
    dataRow.classList.add('highlighted');
    openRowId = d.id;

    var td = expandRow.querySelector('td');
    var inner = document.createElement('div');
    inner.className = 'expand-inner';

    // Radar chart
    var radarWrap = document.createElement('div');
    radarWrap.className = 'radar-wrap';
    var canvas = document.createElement('canvas');
    canvas.id = 'radarCanvas-' + d.id.replace(/[^a-z0-9]/gi,'_');
    radarWrap.appendChild(canvas);

    var subtitle = document.createElement('div');
    subtitle.className = 'expand-subtitle';
    subtitle.textContent = 'Weighted total: ' + d.display_score + '  ·  Confidence: ' + d.confidence;
    radarWrap.appendChild(subtitle);
    inner.appendChild(radarWrap);

    // Factor breakdown
    var right = document.createElement('div');
    var table = document.createElement('table');
    table.className = 'breakdown-table';
    var thead = table.createTHead();
    var hrow = thead.insertRow();
    ['Factor','Raw','Weight','Weighted','Reason'].forEach(function(h) {
      var th = document.createElement('th');
      th.textContent = h;
      hrow.appendChild(th);
    });
    var tbody2 = table.createTBody();
    d.factors.forEach(function(f) {
      var row = tbody2.insertRow();
      [f.key, f.raw.toFixed(1), f.weight.toFixed(2), f.weighted.toFixed(2), f.reason].forEach(function(v, i) {
        var cell = row.insertCell();
        cell.textContent = v;
      });
    });
    right.appendChild(table);
    inner.appendChild(right);
    td.appendChild(inner);

    // Draw radar (skip if Chart.js is unavailable — the table above still shows)
    if (typeof Chart === 'undefined') return;
    var labels = d.factors.map(function(f){ return f.key.replace(/_/g,' '); });
    var values = d.factors.map(function(f){ return f.raw; });
    openRadarChart = new Chart(canvas.getContext('2d'), {
      type: 'radar',
      data: {
        labels: labels,
        datasets: [{
          label: (d.year || '') + ' ' + (d.make || '') + ' ' + (d.model || ''),
          data: values,
          backgroundColor: 'rgba(217,119,6,0.12)',
          borderColor: 'rgba(217,119,6,0.75)',
          borderWidth: 1.5,
          pointBackgroundColor: 'rgba(217,119,6,0.8)',
          pointRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: { duration: 180 },
        plugins: {
          legend: { display: false },
        },
        scales: {
          r: {
            min: 0, max: 10,
            ticks: { stepSize: 2, font: { size: 9 }, color: '#9c9890', backdropColor: 'transparent' },
            grid: { color: '#e5e3df' },
            angleLines: { color: '#e5e3df' },
            pointLabels: { font: { size: 9 }, color: '#6b6861' },
          },
        },
      },
    });
  }

  // ── Scroll + highlight ─────────────────────────────────────────────────────
  function scrollToRow(id) {
    if (S.pageSize > 0) {
      var sorted = filteredListings();
      sorted.sort(function(a, b) {
        var av = a[S.sortCol], bv = b[S.sortCol];
        if (av == null) av = S.sortDir === 'asc' ? Infinity : -Infinity;
        if (bv == null) bv = S.sortDir === 'asc' ? Infinity : -Infinity;
        if (typeof av === 'string') av = av.toLowerCase();
        if (typeof bv === 'string') bv = bv.toLowerCase();
        if (av < bv) return S.sortDir === 'asc' ? -1 : 1;
        if (av > bv) return S.sortDir === 'asc' ? 1 : -1;
        return 0;
      });
      var idx = -1;
      for (var i = 0; i < sorted.length; i++) {
        if (sorted[i].id === id) { idx = i; break; }
      }
      if (idx >= 0) {
        var targetPage = Math.floor(idx / S.pageSize) + 1;
        if (targetPage !== S.page) { S.page = targetPage; renderTable(); }
      }
    }
    var row = document.querySelector('tr.data-row[data-id="' + CSS.escape(id) + '"]');
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('highlighted');
    setTimeout(function(){ if (openRowId !== id) row.classList.remove('highlighted'); }, 2500);
  }

  // ── Lightbox ───────────────────────────────────────────────────────────────
  var lbPhotos = [], lbIdx = 0;
  function openLightbox(photos, idx) {
    if (!photos || !photos.length) return;
    lbPhotos = photos; lbIdx = idx;
    updateLightbox();
    document.getElementById('lightbox').classList.add('open');
  }
  function updateLightbox() {
    document.getElementById('lbImg').src = lbPhotos[lbIdx];
    document.getElementById('lbCounter').textContent = (lbIdx + 1) + ' / ' + lbPhotos.length;
  }

  // ── Apply all filters ──────────────────────────────────────────────────────
  function applyFilters() {
    S.page = 1;
    renderTable();
    buildScatter();
  }

  // ── Header sort ───────────────────────────────────────────────────────────
  function attachSortHandlers() {
    document.querySelectorAll('table.listings thead th[data-col]').forEach(function(th) {
      var col = th.dataset.col;
      if (!SORTABLE.has(col)) return;
      th.addEventListener('click', function() {
        if (S.sortCol === col) {
          S.sortDir = S.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          S.sortCol = col;
          S.sortDir = col === 'score' ? 'desc' : 'asc';
        }
        renderTable();
      });
    });
  }

  // ── Filter controls wiring ─────────────────────────────────────────────────
  function initFilters() {
    // Search box (debounced so a full table+scatter rebuild doesn't fire on
    // every keystroke)
    var searchInput = document.getElementById('filterSearch');
    if (searchInput) {
      var searchTimer = null;
      searchInput.addEventListener('input', function() {
        var val = this.value.trim().toLowerCase();
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function() {
          S.search = val;
          applyFilters();
        }, 150);
      });
    }

    // Source dropdown
    var selSrc = document.getElementById('filterSource');
    var srcOptions = ['all', 'craigslist', 'carmax', 'carscom', 'kbb'];
    srcOptions.forEach(function(src) {
      var opt = document.createElement('option');
      opt.value = src;
      opt.textContent = src.charAt(0).toUpperCase() + src.slice(1);
      if (src === 'all') opt.selected = true;
      selSrc.appendChild(opt);
    });
    selSrc.addEventListener('change', function() {
      S.source = this.value;
      applyFilters();
    });

    // Score slider
    var scoreSlider = document.getElementById('filterScore');
    var scoreLabel  = document.getElementById('filterScoreLabel');
    scoreSlider.addEventListener('input', function() {
      S.minScore = +this.value;
      scoreLabel.textContent = this.value;
      applyFilters();
    });

    // Body checkboxes
    document.querySelectorAll('.body-cb').forEach(function(cb) {
      cb.parentElement.classList.add('checked'); // all checked initially
      cb.addEventListener('change', function() {
        // From the default "all checked" state, the first click selects only that
        // body type instead of merely toggling the clicked one off.
        if (!this.checked && S.bodyTypes.size === BODY_TYPES.length) {
          var only = this.value;
          S.bodyTypes = new Set([only]);
          document.querySelectorAll('.body-cb').forEach(function(other) {
            var keep = (other.value === only);
            other.checked = keep;
            other.parentElement.classList.toggle('checked', keep);
          });
        } else if (this.checked) {
          S.bodyTypes.add(this.value);
          this.parentElement.classList.add('checked');
        } else {
          S.bodyTypes.delete(this.value);
          this.parentElement.classList.remove('checked');
        }
        applyFilters();
      });
    });

    // Year min
    var yearInput = document.getElementById('filterYear');
    yearInput.addEventListener('change', function() {
      S.yearMin = +this.value || 2008;
      applyFilters();
    });

    // Price range double slider
    var priceMinEl = document.getElementById('priceMin');
    var priceMaxEl = document.getElementById('priceMax');
    var priceLabel = document.getElementById('priceLabel');
    function updatePrice() {
      var lo = +priceMinEl.value, hi = +priceMaxEl.value;
      if (lo > hi) { var t = lo; lo = hi; hi = t; }
      S.priceMin = lo; S.priceMax = hi;
      priceLabel.textContent = '$' + (lo/1000).toFixed(0) + 'k – $' + (hi/1000).toFixed(lo >= 1000 ? 1 : 0) + 'k';
      applyFilters();
    }
    priceMinEl.addEventListener('input', updatePrice);
    priceMaxEl.addEventListener('input', updatePrice);

    // Mileage range double slider
    var mileMin = document.getElementById('mileMin');
    var mileMax = document.getElementById('mileMax');
    var mileLabel = document.getElementById('mileLabel');
    function updateMileage() {
      var lo = +mileMin.value, hi = +mileMax.value;
      if (lo > hi) { var t = lo; lo = hi; hi = t; }
      S.mileMin = lo; S.mileMax = hi;
      mileLabel.textContent = (lo/1000).toFixed(0) + 'k – ' + (hi/1000).toFixed(0) + 'k mi';
      applyFilters();
    }
    mileMin.addEventListener('input', updateMileage);
    mileMax.addEventListener('input', updateMileage);

    // Reset
    document.getElementById('btnReset').addEventListener('click', function() {
      S.source = 'all'; S.minScore = 0;
      S.bodyTypes = new Set(BODY_TYPES);
      S.priceMin = 0; S.priceMax = 20000;
      S.mileMin = 0; S.mileMax = 200000; S.yearMin = 2008;
      S.search = '';
      if (searchInput) searchInput.value = '';
      selSrc.value = 'all';
      scoreSlider.value = 0; scoreLabel.textContent = '0';
      document.querySelectorAll('.body-cb').forEach(function(cb){
        cb.checked = true; cb.parentElement.classList.add('checked');
      });
      yearInput.value = 2008;
      priceMinEl.value = 0; priceMaxEl.value = 20000;
      priceLabel.textContent = '$0k – $20k';
      mileMin.value = 0; mileMax.value = 200000;
      mileLabel.textContent = '0k – 200k mi';
      applyFilters();
    });
  }

  // ── Lightbox wiring ────────────────────────────────────────────────────────
  function initLightbox() {
    document.getElementById('lightbox').addEventListener('click', function(e) {
      if (e.target === this) this.classList.remove('open');
    });
    document.getElementById('lbClose').addEventListener('click', function() {
      document.getElementById('lightbox').classList.remove('open');
    });
    document.getElementById('lbPrev').addEventListener('click', function() {
      lbIdx = (lbIdx - 1 + lbPhotos.length) % lbPhotos.length;
      updateLightbox();
    });
    document.getElementById('lbNext').addEventListener('click', function() {
      lbIdx = (lbIdx + 1) % lbPhotos.length;
      updateLightbox();
    });
    document.addEventListener('keydown', function(e) {
      var lb = document.getElementById('lightbox');
      if (!lb.classList.contains('open')) return;
      if (e.key === 'Escape') lb.classList.remove('open');
      if (e.key === 'ArrowLeft')  { lbIdx = (lbIdx - 1 + lbPhotos.length) % lbPhotos.length; updateLightbox(); }
      if (e.key === 'ArrowRight') { lbIdx = (lbIdx + 1) % lbPhotos.length; updateLightbox(); }
    });
  }

  // ── Notes modal (manual listings) ─────────────────────────────────────────
  function openNotesModal(d) {
    var title = (d.year ? d.year + ' ' : '') + (d.make || '') + ' ' + (d.model || '');
    document.getElementById('notesTitle').textContent = title.trim() || 'Listing notes';
    document.getElementById('notesBody').textContent = d.description || '';
    document.getElementById('notesModal').classList.add('open');
  }
  function closeNotesModal() {
    document.getElementById('notesModal').classList.remove('open');
  }
  document.getElementById('notesClose').addEventListener('click', closeNotesModal);
  document.getElementById('notesModal').addEventListener('click', function(e) {
    if (e.target === this) closeNotesModal();
  });

  // ── Import modal ───────────────────────────────────────────────────────────
  function openImportModal() {
    document.getElementById('importModal').classList.add('open');
    document.getElementById('f-make').focus();
  }
  function closeImportModal() {
    document.getElementById('importModal').classList.remove('open');
    document.getElementById('formMsg').textContent = '';
  }
  function submitImport() {
    var make = document.getElementById('f-make').value.trim();
    var model = document.getElementById('f-model').value.trim();
    var year = document.getElementById('f-year').value.trim();
    var msgEl = document.getElementById('formMsg');
    if (!make || !model || !year) { msgEl.textContent = 'Make, model, and year are required.'; return; }
    var btn = document.getElementById('importSubmit');
    btn.disabled = true; btn.textContent = 'Saving…';
    fetch('/api/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url:         document.getElementById('f-url').value.trim() || null,
        make:        make,
        model:       model,
        year:        +year,
        trim:        document.getElementById('f-trim').value.trim() || null,
        body_type:   document.getElementById('f-body-type').value || null,
        mileage:     document.getElementById('f-mileage').value || null,
        price:       document.getElementById('f-price').value || null,
        location:    document.getElementById('f-location').value.trim() || null,
        seller_type: document.getElementById('f-seller-type').value,
        notes:       document.getElementById('f-notes').value.trim() || null,
      }),
    })
    .then(function(r){ return r.json(); })
    .then(function(data) {
      if (data.ok) { window.location.reload(); }
      else { msgEl.textContent = data.error || 'Error saving listing.'; btn.disabled = false; btn.textContent = 'Save listing'; }
    })
    .catch(function(err) {
      msgEl.textContent = 'Network error: ' + err.message;
      btn.disabled = false; btn.textContent = 'Save listing';
    });
  }
  // ── Listing text parser ────────────────────────────────────────────────────
  function parseListingText(raw) {
    var result = {};

    // 1. Structured key:value pairs (FB Marketplace full-page copy)
    var kv = {
      year:      /\byear\s*[:：]\s*(\d{4})/i,
      make:      /\bmake\s*[:：]\s*([A-Za-z][A-Za-z\s\-]+?)(?:\n|$)/im,
      model:     /\bmodel\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9\s\-]+?)(?:\n|$)/im,
      trim:      /\btrim\s*[:：]\s*([A-Za-z0-9\s\-]+?)(?:\n|$)/im,
      mileage:   /\bmileage\s*[:：]\s*([\d,]+)/i,
      price:     /\bprice\s*[:：]\s*\$?([\d,]+)/i,
      body_type: /\bbody\s*(?:style|type)?\s*[:：]\s*([A-Za-z]+)/i,
      location:  /\blocation\s*[:：]\s*([^\n]+)/i,
    };
    for (var key in kv) {
      var km = raw.match(kv[key]);
      if (km) result[key] = km[1].trim();
    }
    if (result.mileage) result.mileage = result.mileage.replace(/,/g, '');
    if (result.price)   result.price   = result.price.replace(/,/g, '');

    // 2. Free-text fallbacks for missing fields
    var MAKES = ['Acura','Alfa Romeo','Audi','BMW','Buick','Cadillac','Chevrolet','Chevy',
      'Chrysler','Dodge','Fiat','Ford','Genesis','GMC','Honda','Hyundai','Infiniti',
      'Jaguar','Jeep','Kia','Land Rover','Lexus','Lincoln','Mazda','Mercedes-Benz',
      'Mercedes','Mini','Mitsubishi','Nissan','Pontiac','Porsche','Ram','Saturn',
      'Scion','Subaru','Tesla','Toyota','Volkswagen','VW','Volvo'];

    if (!result.year) {
      var ym = raw.match(/\b(20[0-2]\d|199\d|198\d)\b/);
      if (ym) result.year = ym[1];
    }

    if (!result.make || !result.model) {
      // "YYYY Make Model" on one line
      var lineM = raw.match(/\b(20[0-2]\d|199\d)\s+([A-Z][a-zA-Z\-]+)\s+([A-Z][a-zA-Z0-9\-]+)/);
      if (lineM) {
        if (!result.year)  result.year  = lineM[1];
        if (!result.make)  result.make  = lineM[2];
        if (!result.model) result.model = lineM[3];
      } else if (!result.make) {
        for (var i = 0; i < MAKES.length; i++) {
          var mre = new RegExp('\\b' + MAKES[i].replace(/[-\s]/g, '[-\\s]?') + '\\b', 'i');
          if (mre.test(raw)) {
            result.make = MAKES[i];
            var mkIdx = raw.search(mre);
            var afterMake = raw.slice(mkIdx + MAKES[i].length).match(/^\s+([A-Z][a-zA-Z0-9\-]+)/);
            if (afterMake && !result.model) result.model = afterMake[1];
            break;
          }
        }
      }
    }

    if (!result.price) {
      var pm = raw.match(/\$\s*([\d,]+)/);
      if (pm) result.price = pm[1].replace(/,/g, '');
    }

    if (!result.mileage) {
      var mm = raw.match(/([\d,]+)\s*[kK]\s*(?:miles?|mi)\b/i);
      if (mm) {
        result.mileage = String(parseInt(mm[1].replace(/,/g, '')) * 1000);
      } else {
        mm = raw.match(/([\d,]+)\s*miles?\b/i);
        if (mm) result.mileage = mm[1].replace(/,/g, '');
      }
    }

    if (!result.body_type) {
      var bmap = {SUV:/\b(?:suv|crossover|cuv)\b/i, Sedan:/\bsedan\b/i, Wagon:/\bwagon\b/i,
        Hatchback:/\b(?:hatchback|hatch)\b/i, Coupe:/\bcoupe\b/i,
        Truck:/\b(?:truck|pickup)\b/i, Van:/\b(?:van|minivan)\b/i};
      for (var bt in bmap) { if (bmap[bt].test(raw)) { result.body_type = bt; break; } }
    }

    if (!result.location) {
      var lm = raw.match(/([A-Z][a-z][a-zA-Z\s]*),\s*(CA|California|NV|Nevada|AZ|Arizona|OR|Oregon|WA|Washington|TX|Texas|FL|Florida|NY)\b/);
      if (lm) result.location = lm[1].trim() + ', ' + lm[2];
    }

    if (!result.seller_type) {
      if (/\b(?:private\s*(?:seller|party)|personal\s*use|1\s*owner|one\s*owner)\b/i.test(raw)) result.seller_type = 'private';
      else if (/\b(?:dealer|dealership)\b/i.test(raw)) result.seller_type = 'dealer';
      else if (/\b(?:certified|cpo)\b/i.test(raw)) result.seller_type = 'certified';
    }

    // Aliases
    if (result.make === 'Chevy') result.make = 'Chevrolet';
    if (result.make === 'VW') result.make = 'Volkswagen';
    if (result.make === 'Mercedes') result.make = 'Mercedes-Benz';
    if (result.mileage && parseInt(result.mileage) > 500000) delete result.mileage;
    if (result.model) result.model = result.model.split(/\s+/)[0]; // first word only

    return result;
  }

  function deleteRow(listingId, dataRow, expandRow) {
    if (!confirm('Remove this listing from the database?')) return;
    fetch('/api/delete/' + encodeURIComponent(listingId), { method: 'POST' })
    .then(function(r){ return r.json(); })
    .then(function(d) {
      if (!d.ok) { alert(d.error || 'Delete failed'); return; }
      // Remove from the canonical data set so it can't reappear on the next
      // filter/sort/pagination render, then rebuild table + scatter from state.
      for (var i = 0; i < LISTINGS.length; i++) {
        if (LISTINGS[i].id === listingId) { LISTINGS.splice(i, 1); break; }
      }
      if (openRowId === listingId) openRowId = null;
      applyFilters();
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    initFilters();
    initLightbox();
    attachSortHandlers();
    renderTable();
    buildScatter();

    if (SERVER_MODE) {
      document.body.classList.add('server-mode');
      var importBtn = document.getElementById('importBtn');
      if (importBtn) importBtn.style.display = 'block';
      importBtn.addEventListener('click', openImportModal);
      document.getElementById('importCancel').addEventListener('click', closeImportModal);
      document.getElementById('importSubmit').addEventListener('click', submitImport);
      document.getElementById('importModal').addEventListener('click', function(e){ if (e.target === this) closeImportModal(); });
      document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeImportModal(); });
      document.getElementById('parseBtn').addEventListener('click', function() {
        var raw = document.getElementById('f-paste').value.trim();
        var resultEl = document.getElementById('parseResult');
        if (!raw) { resultEl.textContent = 'Paste some text first.'; resultEl.style.color = 'var(--text-faint)'; return; }
        var parsed = parseListingText(raw);
        var map = {year:'f-year', make:'f-make', model:'f-model', trim:'f-trim',
                   body_type:'f-body-type', mileage:'f-mileage', price:'f-price',
                   location:'f-location', seller_type:'f-seller-type'};
        var filled = [];
        for (var k in map) {
          if (parsed[k]) {
            document.getElementById(map[k]).value = parsed[k];
            filled.push(k.replace('_', ' '));
          }
        }
        // Stash the raw pasted text into Notes so it persists as the listing
        // description and surfaces in the dashboard view modal later.
        var notesEl = document.getElementById('f-notes');
        if (!notesEl.value.trim()) notesEl.value = raw;
        if (filled.length) {
          resultEl.style.color = 'var(--green)';
          resultEl.textContent = 'Filled: ' + filled.join(', ') + '. Pasted text saved to Notes. Review before saving.';
        } else {
          resultEl.style.color = 'var(--text-faint)';
          resultEl.textContent = 'Could not extract fields — pasted text saved to Notes. Try pasting more of the listing page.';
        }
      });
    }
  });

}());
