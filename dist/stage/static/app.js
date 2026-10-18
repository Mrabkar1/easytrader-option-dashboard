/* EasyTrader Option — Local Dashboard front-end (نسخهٔ تمیز و مقاوم)
 * داده‌ها را از سرور محلی می‌گیرد (پروکسی امن به API سایت).
 * قواعد پاسخ سرور:
 *   /api/status  → جیسون مستقیم {hasToken, tokenExpired, ...}
 *   /api/… داده‌ها → {ok:true, data:…} یا {ok:false, error, message}
 * خطاها همیشه در خود صفحه نشان داده می‌شوند؛ هیچ چیز بی‌صدا قورت داده نمی‌شود.
 */
(function () {
  'use strict';

  var CFG = {
    refreshMs: 45000,      // فاصلهٔ رفرش خودکار
    minRefreshMs: 15000,   // کمینهٔ مجاز
    statusMs: 20000,       // چک وضعیت/توکن
    clockMs: 1000
  };

  var state = {
    tab: 'summary', paused: false, busy: false, timer: null, nextAt: 0,
    status: null, summary: null, orders: null, chain: null,
    chainQuery: '', lastOk: null, lastError: ''
  };

  // ── کمکی‌ها ──
  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function num(n, dec) {
    if (n == null || n === '' || isNaN(Number(n))) return '—';
    var v = Number(n);
    if (dec == null) dec = (Math.abs(v) < 100 && v !== 0) ? 2 : 0;
    try { return v.toLocaleString('fa-IR', { minimumFractionDigits: dec, maximumFractionDigits: dec }); }
    catch (e) { return String(v); }
  }

  // مبالغ سایت معمولاً «ریال» است؛ برای خوانایی به تومان
  function money(r) {
    if (r == null || r === '' || isNaN(Number(r))) return '—';
    var v = Number(r), sign = v < 0 ? '−' : '';
    return sign + num(Math.abs(v) / 10, 0) + ' تومان';
  }

  function cls(v) { v = Number(v); return v > 0 ? 'pos' : (v < 0 ? 'neg' : ''); }
  function arrow(v) { v = Number(v); return v > 0 ? '▲' : (v < 0 ? '▼' : '–'); }

  function pick(o, keys) {
    if (!o) return null;
    for (var i = 0; i < keys.length; i++) { if (o[keys[i]] != null) return o[keys[i]]; }
    return null;
  }

  function setConn(kind, txt) {
    var d = $('connDot'); if (d) d.className = 'dot ' + kind;
    var t = $('connTxt'); if (t) t.textContent = txt;
  }

  function showOverlay(showBool, title, msg) {
    var ov = $('tokenOverlay');
    if (!ov) return;
    ov.hidden = !showBool;
    if (title != null) $('tokTitle').textContent = title;
    if (msg != null) $('tokMsg').textContent = msg;
  }

  // ── ارتباط با سرور محلی ──
  function getJSON(path) {
    return fetch(path, { cache: 'no-store' }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) {
          var err = new Error(j && (j.message || j.error) || ('HTTP_' + r.status));
          err.http = r.status; err.body = j;
          throw err;
        }
        return j;
      });
    });
  }

  // اندپوینت‌های داده: {ok, data}
  function apiData(path) {
    return getJSON(path).then(function (j) {
      if (j && j.ok === false) {
        var err = new Error(j.message || j.error || 'خطای سرور');
        err.http = (j.error === 'UNAUTHORIZED') ? 401 : (j.error === 'NO_TOKEN' ? 401 : 502);
        err.body = j; throw err;
      }
      return (j && j.data != null) ? j.data : j;
    });
  }

  // اندپوینت وضعیت: جیسون مستقیم
  function apiStatus() { return getJSON('/api/status'); }

  // ── وضعیت اتصال/توکن ──
  function refreshConnFromStatus() {
    var s = state.status || {};
    if (!s.hasToken) {
      setConn('bad', 'بدون اتصال حساب');
    } else if (s.tokenExpired) {
      setConn('bad', 'توکن منقضی');
    } else {
      setConn('ok', 'متصل به حساب');
    }
  }

  function loadStatus() {
    return apiStatus().then(function (s) {
      state.status = s;
      refreshConnFromStatus();
      var fc = $('footCache'); if (fc) fc.textContent = 'کش سرور: ' + num(s.cacheEntries, 0) + ' مورد';
      // اورلی توکن: فقط اگر واقعاً لازم است
      if (!s.hasToken) showOverlay(true, 'اتصال حساب لازم است', 'برای دریافت داده‌ها، یک‌بار باید توکن نشست خود را به سرور محلی بدهید.');
      else if (s.tokenExpired) showOverlay(true, 'توکن منقضی شده', 'توکن نشست شما منقضی شده. دوباره لاگین کنید و بوکمارکلت دریافت توکن را اجرا کنید.');
      else { var ov = $('tokenOverlay'); if (ov && !ov.hidden) { ov.hidden = true; } }
      return s;
    });
  }

  // ── بارگیری داده‌ها ──
  function loadSummary() {
    return apiData('/api/summary').then(function (d) { state.summary = d; state.lastOk = new Date(); });
  }
  function loadPositions() {
    return apiData('/api/positions').then(function (d) { state.positions = d; state.lastOk = new Date(); });
  }
  function loadOrders() {
    return apiData('/api/orders').then(function (d) { state.orders = d; state.lastOk = new Date(); });
  }
  function loadChain() {
    return apiData('/api/chain').then(function (d) { state.chain = d; state.lastOk = new Date(); });
  }

  function jobsForTab() {
    switch (state.tab) {
      case 'positions': return [loadSummary(), loadPositions()];
      case 'chain': return [loadChain()];
      case 'orders': return [loadOrders()];
      case 'market': return [loadSummary()];
      default: return [loadSummary()];
    }
  }

  function loadData(force) {
    if (state.busy) return;
    state.busy = true;
    if (force) setConn('busy', 'در حال دریافت…');
    var errs = [];

    var tasks = [loadStatus()].concat(jobsForTab());
    // هر خطا را ثبت می‌کنیم بدون اینکه بقیه متوقف شوند
    var guarded = tasks.map(function (p) {
      return p.catch(function (e) { errs.push(e); });
    });

    Promise.all(guarded).then(function () {
      state.busy = false;
      // مهم‌ترین خطا (توکن) را نشان بده
      var authErr = errs.filter(function (e) { return e.http === 401; })[0];
      var otherErr = errs.filter(function (e) { return e.http !== 401; })[0];
      if (authErr) {
        var msg = (authErr.body && authErr.body.message) || 'توکن منقضی یا ثبت نشده است.';
        showOverlay(true, authErr.body && authErr.body.error === 'NO_TOKEN' ? 'اتصال حساب لازم است' : 'توکن منقضی شده', msg);
        state.lastError = msg;
        // اگر چند بار 401 دادیم، رفرش دور را همیشگی می‌کنیم و پیام می‌دهیم
        state.lastErrorAt = new Date();
      } else if (otherErr) {
        state.lastError = (otherErr.message || String(otherErr));
        setConn('bad', 'خطا: ' + arrow(0));
        $('connTxt').textContent = 'خطا';
      } else {
        state.lastError = '';
      }
      schedule(nextDelay(errs));
      render();
    });
  }

  function nextDelay(errs) {
    var s = state.status;
    if (!s || !s.hasToken) return CFG.statusMs;                    // توکن نیست → وضعیت سریع چک شود
    if (errs.length) return Math.min(CFG.refreshMs * 3, 300000);   // خطا → backoff
    return CFG.refreshMs;
  }

  // ── زمان‌بندی ──
  function schedule(ms) {
    stopTimer();
    if (state.paused) { $('footNext').textContent = 'رفرش خودکار متوقف'; return; }
    ms = Math.max(ms || CFG.refreshMs, CFG.minRefreshMs);
    state.nextAt = Date.now() + ms;
    state.timer = setTimeout(function () { loadData(false); }, ms);
    tick();
  }
  function stopTimer() {
    if (state.timer) { clearTimeout(state.timer); state.timer = null; }
    state.nextAt = 0;
  }

  function tick() {
    var c = $('clock'); if (c) c.textContent = new Date().toLocaleTimeString('fa-IR');
    if (state.nextAt && !state.paused) {
      var s = Math.max(0, Math.round((state.nextAt - Date.now()) / 1000));
      var n = $('footNext');
      if (n) n.textContent = 'رفرش بعدی: ' + num(s, 0) + ' ثانیه';
    }
    var u = $('footUpdated');
    if (u) u.textContent = state.lastOk ? 'آخرین داده: ' + state.lastOk.toLocaleTimeString('fa-IR') : '';
  }

  // ── رندر ──
  function paneEl() { return $('pane-' + state.tab); }

  function skeleton(msg) {
    return '<div class="empty"><div class="big">◌</div>' + (msg || 'در حال بارگذاری…') + '</div>';
  }

  function errBox() {
    if (!state.lastError) return '';
    return '<div class="err" style="margin-bottom:12px">⚠ ' + esc(state.lastError) + '</div>';
  }

  function box(title, valHtml, sub) {
    return '<div class="card stat"><h3>' + title + '</h3>' +
      '<div class="val">' + valHtml + '</div>' +
      (sub ? '<div class="sub">' + sub + '</div>' : '') + '</div>';
  }

  function render() {
    var st = $('footStatus');
    if (st) st.innerHTML = state.lastError
      ? '<span class="badge bad"></span>' + esc(state.lastError)
      : '<span class="badge ok"></span>آماده';

    var p = paneEl();
    if (!p) return;

    switch (state.tab) {
      case 'summary': renderSummary(p); break;
      case 'positions': renderPositions(p); break;
      case 'chain': renderChain(p); break;
      case 'orders': renderOrders(p); break;
      case 'market': renderMarket(p); break;
    }
  }

  function positionRowHtml(p) {
    var title = pick(p, ['symbolTitle', 'title', 'symbolName', 'contractTitle', 'symbol']) || '—';
    var side = pick(p, ['side', 'orderSide', 'positionSide']);
    var isBuy = (side === 1 || side === 'Buy' || side === 'buy');
    var isSell = (side === 2 || side === 'Sell' || side === 'sell');
    var sideTxt = isBuy ? 'خرید' : (isSell ? 'فروش' : '—');
    var sideKind = isBuy ? 'buy' : (isSell ? 'sell' : 'gray');
    var qty = pick(p, ['quantity', 'executedQuantity', 'volume', 'count']);
    var price = pick(p, ['averagePrice', 'avgPrice', 'price']);
    var pl = pick(p, ['profitLoss', 'pnl', 'openPositionProfitLoss', 'closedPositionProfitLoss']);
    return '<tr>' +
      '<td>' + esc(title) + '</td>' +
      '<td><span class="chip ' + sideKind + '">' + sideTxt + '</span></td>' +
      '<td class="num">' + num(qty, 0) + '</td>' +
      '<td class="num">' + (price != null ? num(price, 1) : '—') + '</td>' +
      '<td class="num ' + cls(pl) + '">' + (pl == null ? '—' : arrow(pl) + ' ' + money(pl)) + '</td>' +
      '</tr>';
  }

  var POSITION_HEAD =
    '<thead><tr><th>قرارداد</th><th>طرف</th><th>تعداد</th><th>میانگین قیمت</th><th>سود/زیان</th></tr></thead>';
  var ORDER_HEAD =
    '<thead><tr><th>نماد</th><th>طرف</th><th>قیمت</th><th>تعداد</th><th>وضعیت</th></tr></thead>';

  function positionsTable(arr) {
    return '<div class="tbl-wrap"><table class="tbl">' + POSITION_HEAD +
      '<tbody>' + arr.map(positionRowHtml).join('') + '</tbody></table></div>';
  }

  function renderSummary(p) {
    if (!state.summary) { p.innerHTML = errBox() + skeleton(); return; }
    var s = state.summary;
    var pnl = s.pnl || {};
    var openPL = pnl.openPositionsProfitLoss;
    var closedPL = pnl.closedPositionsProfitLoss;
    var total = (Number(openPL) || 0) + (Number(closedPL) || 0);
    var pos = Array.isArray(s.positions) ? s.positions : [];
    var cash = pick(s.money || {}, ['cash', 'balance', 'availableBalance', 'freeCash', 't0', 't1', 'amount']);
    var idx = s.tseIndex || {};
    var idxVal = pick(idx, ['price', 'value', 'last', 'closingPrice', 'tseIndex']);
    var idxChg = pick(idx, ['change', 'priceChange', 'variation', 'closeChange']);
    var settle = s.settlementStatus;

    var html = errBox();
    html += '<div class="grid c4" style="margin-bottom:12px">' +
      box('سود/زیان باز', '<span class="' + cls(openPL) + '">' + arrow(openPL) + ' ' + money(openPL) + '</span>', 'موقعیت‌های باز آپشن') +
      box('سود/زیان بسته', '<span class="' + cls(closedPL) + '">' + arrow(closedPL) + ' ' + money(closedPL) + '</span>', 'تسویه‌شده') +
      box('مجموع سود/زیان', '<span class="' + cls(total) + '">' + arrow(total) + ' ' + money(total) + '</span>', 'باز + بسته') +
      box('موقعیت‌های باز', num(pos.length, 0), 'قرارداد در جریان') +
      '</div>';
    html += '<div class="grid c3" style="margin-bottom:12px">' +
      box('موجودی نقد', cash != null ? money(cash) : '—', 'حساب معاملاتی') +
      box('شاخص کل', idxVal != null ? num(idxVal, 0) : '—',
        idxChg != null ? '<span class="' + cls(idxChg) + '">' + arrow(idxChg) + ' ' + num(idxChg, 0) + '</span>' : '') +
      box('وضعیت تسویع', settle == null ? '—' : esc(typeof settle === 'object' ? 'فعال' : String(settle)), 'گردآوری تسویه') +
      '</div>';

    // پیش‌نمایش موقعیت‌ها
    if (pos.length) {
      var rows = pos.slice(0, 8).map(positionRowHtml).join('');
      html += '<div style="margin:14px 0 10px;font-size:13px;color:var(--muted)">موقعیت‌های باز (نگاه سریع)</div>' +
        '<div class="tbl-wrap"><table class="tbl">' + POSITION_HEAD + '<tbody>' + rows + '</tbody></table></div>';
    } else {
      html += '<div class="empty"><div class="big">◈</div>موقعیت باز آپشنی وجود ندارد.</div>';
    }
    html += '<div class="note" style="margin-top:12px">فقط خواندن • بدون ثبت سفارش' +
      (state.lastOk ? ' • آخرین دریافت: ' + state.lastOk.toLocaleTimeString('fa-IR') : '') + '</div>';
    p.innerHTML = html;
  }

  function renderPositions(p) {
    if (!state.positions) { p.innerHTML = errBox() + skeleton(); return; }
    var pos = Array.isArray(state.positions) ? state.positions : [];
    if (!pos.length) {
      p.innerHTML = errBox() + '<div class="empty"><div class="big">◈</div>هیچ موقعیت باز آپشنی ثبت نشده است.</div>';
      return;
    }
    p.innerHTML = errBox() + positionsTable(pos) +
      '<div class="note" style="margin-top:10px">تعداد کل: ' + num(pos.length, 0) + ' موقعیت</div>';
  }

  function optionRow(s) {
    var isCall = (s.marketUnit === 45 || s.marketUnit === 48);
    return '<tr>' +
      '<td>' + esc(s.title || s.symbolName || '—') + '</td>' +
      '<td>' + esc(s.companyTitle || '—') + '</td>' +
      '<td><span class="chip ' + (isCall ? 'buy' : 'sell') + '">' + (isCall ? 'اختیار خرید' : 'اختیار فروش') + '</span></td>' +
      '<td class="num">' + (s.strikePrice != null ? num(s.strikePrice, 0) : '—') + '</td>' +
      '<td class="num">' + esc(s.symbolIsin || '—') + '</td>' +
      '<td class="num">' + num(s.marketUnit, 0) + '</td>' +
      '</tr>';
  }

  function renderChain(p) {
    if (!state.chain) { p.innerHTML = errBox() + skeleton('در حال بارگذاری زنجیره… (اولین بار کمی طول می‌کشد)'); return; }
    var opts = state.chain.options || [];
    var q = state.chainQuery.toLowerCase();
    var list = opts;
    if (q) {
      list = opts.filter(function (s) {
        return (String(s.title || '').toLowerCase() + String(s.companyTitle || '').toLowerCase() +
          String(s.enTitle || '').toLowerCase() + String(s.strikePrice || ''))
          .toLowerCase().indexOf(q) !== -1;
      });
    }

    var html = errBox();
    html += '<input class="search" id="chainQ" placeholder="جستجو: نماد، شرکت، قیمت اعمال…" value="' + esc(state.chainQuery) + '">';
    html += '<div class="note" style="margin-bottom:12px">کل قراردادهای آپشن: <b>' +
      num(state.chain.optionCount, 0) + '</b> از ' + num(state.chain.totalSymbols, 0) +
      ' نماد • نمایش: ' + num(list.length, 0) +
      (list.length > 200 ? ' (۲۰۰ ردیف اول — با جستجو دقیق‌تر شوید)' : '') + '</div>';

    if (!list.length) {
      html += '<div class="empty"><div class="big">⌕</div>موردی یافت نشد.</div>';
    } else {
      html += '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
        '<th>قرارداد</th><th>شرکت</th><th>نوع</th><th>قیمت اعمال</th><th>ISIN</th><th>واحد</th>' +
        '</tr></thead><tbody>' + list.slice(0, 200).map(optionRow).join('') + '</tbody></table></div>';
    }
    p.innerHTML = html;

    var inp = $('chainQ');
    if (inp) {
      inp.addEventListener('input', function () {
        state.chainQuery = inp.value;
        var pos = inp.selectionStart;
        renderChain(p);
        var nq = $('chainQ');
        if (nq) { nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { } }
      });
    }
  }

  function renderOrders(p) {
    if (!state.orders) { p.innerHTML = errBox() + skeleton(); return; }
    var list = Array.isArray(state.orders) ? state.orders : (state.orders && state.orders.items) || [];
    if (!list.length) {
      p.innerHTML = errBox() + '<div class="empty"><div class="big">◇</div>سفارش بازی وجود ندارد.</div>';
      return;
    }
    var rows = list.map(function (o) {
      var title = pick(o, ['symbolTitle', 'title', 'symbolName']) || '—';
      var side = pick(o, ['side', 'orderSide']);
      var isBuy = (side === 1 || side === 'Buy' || side === 'buy');
      var isSell = (side === 2 || side === 'Sell' || side === 'sell');
      var sideTxt = isBuy ? 'خرید' : (isSell ? 'فروش' : String(side != null ? side : '—'));
      var sideKind = isBuy ? 'buy' : (isSell ? 'sell' : 'gray');
      var price = pick(o, ['price', 'orderPrice']);
      var qty = pick(o, ['quantity', 'volume', 'count']);
      var stt = pick(o, ['statusText', 'status', 'state']);
      return '<tr>' +
        '<td>' + esc(title) + '</td>' +
        '<td><span class="chip ' + sideKind + '">' + esc(sideTxt) + '</span></td>' +
        '<td class="num">' + (price != null ? num(price, 1) : '—') + '</td>' +
        '<td class="num">' + (qty != null ? num(qty, 0) : '—') + '</td>' +
        '<td>' + esc(stt == null ? '—' : stt) + '</td>' +
        '</tr>';
    }).join('');
    p.innerHTML = errBox() + '<div class="tbl-wrap"><table class="tbl">' + ORDER_HEAD +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function renderMarket(p) {
    if (!state.summary) { p.innerHTML = errBox() + skeleton(); return; }
    var s = state.summary;
    var idx = s.tseIndex || {};
    var idxVal = pick(idx, ['price', 'value', 'last', 'closingPrice', 'tseIndex']);
    var idxChg = pick(idx, ['change', 'priceChange', 'variation']);
    var cash = pick(s.money || {}, ['cash', 'balance', 'availableBalance', 't0', 'freeCash']);
    var pos = Array.isArray(s.positions) ? s.positions : [];

    var html = errBox();
    html += '<div class="grid c3" style="margin-bottom:12px">' +
      box('شاخص کل', idxVal != null ? num(idxVal, 0) : '—',
        idxChg != null ? '<span class="' + cls(idxChg) + '">' + arrow(idxChg) + ' ' + num(idxChg, 0) + '</span>' : '') +
      box('موجودی نقد', cash != null ? money(cash) : '—', 'آزاد برای معامله') +
      box('موقعیت‌های باز', num(pos.length, 0), 'قرارداد آپشن در جریان') +
      '</div>';
    html += '<div class="note">برای قیمت‌های لحظه‌ای هر قرارداد از تب «زنجیرهٔ آپشن» استفاده کنید. ' +
      'قیمت‌های زنده (Lightstreamer) مانند خودِ سایت در نسخهٔ بعد اضافه می‌شود.</div>';
    p.innerHTML = html;
  }

  // ── رویدادها ──
  function bindTabs() {
    var tabs = document.querySelectorAll('.tab');
    Array.prototype.forEach.call(tabs, function (t) {
      t.addEventListener('click', function () {
        Array.prototype.forEach.call(tabs, function (x) { x.classList.remove('on'); });
        t.classList.add('on');
        state.tab = t.getAttribute('data-tab');
        state.chainQuery = '';
        render();
        loadData(true);
      });
    });
  }

  function bindControls() {
    $('btnRefresh').addEventListener('click', function () { loadData(true); });
    var pause = $('btnPause');
    pause.addEventListener('click', function () {
      state.paused = !state.paused;
      if (state.paused) {
        stopTimer(); pause.textContent = '▶'; pause.classList.remove('btn-active');
        $('footNext').textContent = 'رفرش خودکار متوقف';
      } else {
        pause.textContent = '⏸'; pause.classList.add('btn-active');
        loadData(true);
      }
    });
    $('tokClose').addEventListener('click', function () { $('tokenOverlay').hidden = true; });
    $('tokRetry').addEventListener('click', function () {
      loadStatus().catch(function (e) { state.lastError = e.message; }).then(function () { loadData(true); });
    });
  }

  // ── شروع ──
  function boot() {
    loadStatus().then(function () {
      return loadData(true);
    }).catch(function (e) {
      // اگر حتی status هم نیامد
      state.lastError = e && e.message || String(e);
      setConn('bad', 'سرور محلی در دسترس نیست — server.py را اجرا کنید');
      var p = paneEl();
      if (p) p.innerHTML = '<div class="err">اتصال به سرور محلی برقرار نشد:<br>' + esc(state.lastError) +
        '<br><br>مطمئن شوید <b>server.py</b> در حال اجراست.</div>';
    });
    bindTabs();
    bindControls();
    setInterval(tick, CFG.clockMs);
    setInterval(function () {
      if (!state.paused && !state.busy && state.status && state.status.hasToken) loadData(false);
    }, CFG.statusMs);
    tick();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
