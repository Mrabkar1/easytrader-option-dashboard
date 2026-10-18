#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyTrader Option — System App (Local Server)
=============================================
یک وب‌سرور محلی که داشبورد رصد بازار آپشن EasyTrader را روی `localhost` سرو می‌کند.

چرا سرور محلی؟
  - مرورگر بخاطر CORS نمی‌تواند مستقیم به API سایت وصل شود؛ این سرور نقش پروکسی دارد.
  - توکن احراز هویت در سرور محلی می‌ماند و به مرورگر/وب‌سایت دیگری نمی‌رود.
  - کش و محدودیت نرخ (rate-limit) باعث می‌شود درخواست‌ها به سایت «کم‌فشار» بماند.

فقط از کتابخانهٔ استاندارد Python استفاده می‌شود؛ نیاز به `pip install` نیست.

اجرا:
    python server.py
سپس مرورگر خودکار روی http://127.0.0.1:8787 باز می‌شود.

نحوهٔ ورود توکن (یک‌بار):
    ۱) وارد https://d.easytrader.ir/option شو و لاگین کن.
    ۲) بوکمارکلت «دریافت توکن EasyTrader» را (از صفحهٔ راهنما/get-token) اجرا کن.
    ۳) توکن به‌خودکار به سرور محلی ارسال و ذخیره می‌شود.
"""

import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib import error as urlerror
from urllib.parse import urlparse, parse_qs, urlencode

# ── کدگذاری کنسول: در ویندوز پیش‌فرض cp1252 است و متن فارسی خطا می‌دهد.
#    خروجی را به UTF-8 تغییر می‌دهیم تا لاگ‌های فارسی چاپ شوند.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    # در بدترین حالت، لاگ‌های فارسی را به ASCII کوتاه می‌کنیم
    pass

# ───────────────────────── پیکربندی ─────────────────────────
HOST = "127.0.0.1"
PORT = 8787
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE = os.path.join(BASE_DIR, "auth.json")

API_BASE = "https://api-mts.orbis.easytrader.ir"
ORIGIN = "https://d.easytrader.ir"
TOKEN_STORAGE_KEY = "oidc.user:https://login.emofid.com:easy_pkce"

# حداقل فاصلهٔ میان درخواست‌های خروجی به هر endpoint (برای احترام به سرور / جلوگیری از فشار)
MIN_GAP_SECONDS = 3.0

# کش داده‌ها: هر مسیر چند ثانیه معتبر بماند؟ (تا درخواست تکراری به سایت نرود)
CACHE_TTL = {
    "/option/api/Positions": 30,
    "/option-asset/api/Assets/positions-profit-loss": 30,
    "/symbols/api/symbols/all": 600,       # سنگین‌ترین داده؛ ۱۰ دقیقه
    "/core/api/order": 30,
    "/easy/api/money": 60,
    "/symbols/api/MarketData/tse-index": 30,
    "/easy/api/MarketWatch": 30,
    "/contract/api/contract": 120,
    "/symbols/api/TradingTime": 600,
    "/easy/api/StockCondition": 300,
    "/option/api/Positions/settlements/gathering/status": 30,
    "_default": 60,
}
DEFAULT_TTL = CACHE_TTL["_default"]

# واحدهای بازار مربوط به قراردادهای آپشن
OPTION_MARKET_UNITS = [45, 46, 47, 48]

# ───────────────────────── وضعیت مشترک ─────────────────────────
_lock = threading.Lock()
_cache = {}            # key -> {"ts": float, "data": any}
_last_call = {}        # host+path -> float (epoch)  برای rate-limit
_token = {"access_token": None, "expires_at": None, "updated_at": None}


def log(msg):
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        # اگر کنسول از UTF-8 پشتیبانی نکند، متن را با جایگزین امن چاپ می‌کنیم
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(f"[{ts}] {msg}".encode(enc, "replace").decode(enc, "replace"), flush=True)


# ───────────────────────── مدیریت توکن ─────────────────────────
def load_token_from_disk():
    try:
        if os.path.exists(AUTH_FILE):
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _lock:
                _token["access_token"] = data.get("access_token")
                _token["expires_at"] = data.get("expires_at")
                _token["updated_at"] = data.get("updated_at")
            log("توکن از auth.json بارگذاری شد.")
    except Exception as e:
        log(f"خطا در خواندن auth.json: {e}")


def save_token(access_token, expires_at=None):
    rec = {
        "access_token": access_token,
        "expires_at": expires_at,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with _lock:
        _token["access_token"] = rec["access_token"]
        _token["expires_at"] = rec["expires_at"]
        _token["updated_at"] = rec["updated_at"]
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        log("توکن ذخیره شد.")
    except Exception as e:
        log(f"خطا در ذخیرهٔ توکن: {e}")


def token_expired():
    with _lock:
        exp = _token.get("expires_at")
        tok = _token.get("access_token")
    if not tok:
        return True
    if not exp:
        return False
    try:
        # expires_at ممکن است ثانیه یا میلی‌ثانیه باشد
        exp_i = int(exp)
        if exp_i > 10**12:      # میلی‌ثانیه
            exp_i = exp_i // 1000
        return exp_i <= time.time()
    except Exception:
        return False


def get_token():
    with _lock:
        return _token.get("access_token")


# ───────────────────────── کلاینت API (با کش + rate-limit) ─────────────────────────
def _throttle(host_path):
    """حداقل فاصله را بین درخواست‌های متوالی به یک مسیر اجرا می‌کند."""
    now = time.time()
    with _lock:
        last = _last_call.get(host_path, 0)
        wait = MIN_GAP_SECONDS - (now - last)
        if wait > 0:
            time.sleep(wait)
        _last_call[host_path] = time.time()


def fetch_api(path, method="GET", body=None, use_cache=True):
    """
    درخواست به EasyTrader. اگر کش معتبر باشد، از کش برمی‌گرداند
    تا فشار کمتری به سایت وارد شود.
    خروجی: (data, from_cache)
    """
    cache_key = path
    ttl = CACHE_TTL.get(path, DEFAULT_TTL)

    if use_cache:
        with _lock:
            entry = _cache.get(cache_key)
        if entry and (time.time() - entry["ts"]) < ttl:
            return entry["data"], True

    tok = get_token()
    if not tok:
        raise RuntimeError("NO_TOKEN")

    # اعمال محدودیت نرخ پیش از ارسال درخواست
    _throttle(API_BASE + path)

    url = API_BASE + path
    headers = {
        "Authorization": "Bearer " + tok,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fa",
        "Origin": ORIGIN,
        "Referer": ORIGIN + "/",
        "User-Agent": "EasyTraderLocalDash/1.0",
    }
    data_bytes = None
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urlrequest.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urlerror.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("UNAUTHORIZED")
        raise RuntimeError(f"HTTP_{e.code}")
    except urlerror.URLError as e:
        raise RuntimeError(f"NETWORK_{getattr(e, 'reason', e)}")

    try:
        data = json.loads(raw)
    except Exception:
        data = raw

    with _lock:
        _cache[cache_key] = {"ts": time.time(), "data": data}
    return data, False


# ───────────────────────── آماده‌سازی پاسخ‌های داشبورد ─────────────────────────
def build_summary():
    """جمع‌آوری داده‌های خلاصه: موقعیت‌ها + سود/زیان + شاخص + پول."""
    out = {}
    errors = {}

    def safe(key, fn):
        try:
            out[key] = fn()
        except Exception as e:
            errors[key] = str(e)
            out[key] = None

    safe("positions", lambda: fetch_api("/option/api/Positions", use_cache=True)[0])
    safe("pnl", lambda: fetch_api("/option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod=false", use_cache=True)[0])
    safe("money", lambda: fetch_api("/easy/api/money", use_cache=True)[0])
    safe("tseIndex", lambda: fetch_api("/symbols/api/MarketData/tse-index", use_cache=True)[0])
    safe("settlementStatus", lambda: fetch_api("/option/api/Positions/settlements/gathering/status", use_cache=True)[0])

    out["_errors"] = errors
    return out


def build_chain():
    """زنجیرهٔ آپشن: فقط قراردادهای آپشن از لیست کامل نمادها."""
    data, _ = fetch_api("/symbols/api/symbols/all", method="POST", body={"hash": "null"}, use_cache=True)
    symbols = data.get("symbols") if isinstance(data, dict) else None
    if not isinstance(symbols, list):
        symbols = []
    options = [s for s in symbols if s.get("marketUnit") in OPTION_MARKET_UNITS]
    return {
        "totalSymbols": len(symbols),
        "optionCount": len(options),
        "options": options,
    }


def build_orders():
    return fetch_api("/core/api/order", use_cache=True)[0]


def build_positions():
    return fetch_api("/option/api/Positions", use_cache=True)[0]


# ───────────────────────── هندلر HTTP ─────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self):
        # قطع‌شدن اتصال توسط کلاینت (مرورگر) خطای ناوارد بشمار؛ لاگ مزاحم نکن
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            log(f"خطای هندلر: {e}")

    # ── helpers ──
    def _send(self, code, obj, content_type="application/json; charset=utf-8"):
        body = obj if isinstance(obj, (bytes, bytearray)) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _send_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self._send(404, {"error": "not found"}, "text/plain; charset=utf-8")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        # لاگ پیش‌فرض سرور HTTP را خاموش می‌کنیم تا کنسول تمیز بماند
        pass

    # ── CORS preflight ──
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── GET ──
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # فایل‌های استاتیک داشبورد
        if path in ("/", "/index.html"):
            self._send_file(os.path.join(BASE_DIR, "dashboard.html"), "text/html; charset=utf-8")
            return
        if path == "/style.css":
            self._send_file(os.path.join(BASE_DIR, "static", "style.css"), "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_file(os.path.join(BASE_DIR, "static", "app.js"), "application/javascript; charset=utf-8")
            return
        if path == "/get-token":
            self._send_file(os.path.join(BASE_DIR, "get-token.html"), "text/html; charset=utf-8")
            return
        if path == "/save-token":
            self._send_file(os.path.join(BASE_DIR, "save-token.html"), "text/html; charset=utf-8")
            return

        # ── API های داشبورد ──
        if path == "/api/status":
            self._send(200, {
                "hasToken": bool(get_token()),
                "tokenExpired": token_expired(),
                "tokenUpdated": _token.get("updated_at"),
                "serverTime": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "cacheEntries": len(_cache),
            })
            return

        if path == "/api/summary":
            try:
                self._send(200, {"ok": True, "data": build_summary()})
            except RuntimeError as e:
                self._handle_runtime_error(e)
            return

        if path == "/api/positions":
            try:
                self._send(200, {"ok": True, "data": build_positions()})
            except RuntimeError as e:
                self._handle_runtime_error(e)
            return

        if path == "/api/orders":
            try:
                self._send(200, {"ok": True, "data": build_orders()})
            except RuntimeError as e:
                self._handle_runtime_error(e)
            return

        if path == "/api/chain":
            try:
                self._send(200, {"ok": True, "data": build_chain()})
            except RuntimeError as e:
                self._handle_runtime_error(e)
            return

        self._send(404, {"error": "unknown endpoint"}, "text/plain; charset=utf-8")

    # ── POST ──
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/token":
            ctype = (self.headers.get("Content-Type") or "").lower()
            wants_html = False
            if "application/json" in ctype:
                # درخواست JSON (از داخل داشبورد)
                body = self._read_json_body()
                tok = body.get("access_token")
                exp = body.get("expires_at")
            else:
                # درخواست فرم urlencoded (از بوکمارکلت در سایت EasyTrader)
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length).decode("utf-8", "replace") if length > 0 else ""
                params = parse_qs(raw, keep_blank_values=True)
                tok = (params.get("access_token") or [""])[0]
                exp = (params.get("expires_at") or [""])[0] or None
                wants_html = "_html" in params or (params.get("_format") or [""])[0] == "html"

            if not tok:
                self._send(400, {"ok": False, "error": "access_token خالی است"})
                return

            save_token(tok, exp if exp else None)

            if wants_html:
                # صفحهٔ موفقیت که به والد (سایت EasyTrader) پیام می‌دهد
                html = self._token_saved_html()
                self._send_raw(200, html.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send(200, {"ok": True, "message": "توکن ذخیره شد."})
            return

        self._send(404, {"error": "unknown endpoint"}, "text/plain; charset=utf-8")

    @staticmethod
    def _token_saved_html():
        return ("<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>"
                "<title>ذخیره شد</title>"
                "<body style='font-family:Tahoma,sans-serif;background:#0f1620;color:#1bbf89;"
                "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
                "<div style='text-align:center'>"
                "<div style='font-size:44px'>✅</div>"
                "<h2 style='color:#1bbf89'>توکن با موفقیت ذخیره شد</h2>"
                "<p style='color:#8fa1b8'>پنجره خودکار بسته می‌شود…</p>"
                "</div><script>"
                "try{parent.postMessage({type:'et-token-saved',ok:true},'*');}catch(e){}"
                "setTimeout(function(){try{parent.postMessage({type:'et-token-saved-done',ok:true},'*');}catch(e){}},350);"
                "</script></body></html>")

    def _send_raw(self, code, body_bytes, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body_bytes)
        except BrokenPipeError:
            pass

    def _handle_runtime_error(self, e):
        msg = str(e)
        if msg == "NO_TOKEN":
            self._send(401, {"ok": False, "error": "NO_TOKEN",
                             "message": "هنوز توکنی ثبت نشده. بوکمارکلت دریافت توکن را اجرا کنید."})
        elif msg == "UNAUTHORIZED":
            self._send(401, {"ok": False, "error": "UNAUTHORIZED",
                             "message": "توکن منقضی شده. دوباره لاگین کنید و بوکمارکلت را اجرا کنید."})
        else:
            self._send(502, {"ok": False, "error": msg})


# ───────────────────────── اجرای سرور ─────────────────────────
def main():
    load_token_from_disk()

    # جلوگیری از اجرای چند نمونه روی یک پورت
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        print(f"خطا در باز کردن پورت {PORT}: {e}")
        print("احتمالاً نمونهٔ دیگری از سرور در حال اجراست. آن را ببندید یا پورت را تغییر دهید.")
        sys.exit(1)

    httpd.daemon_threads = True
    url = f"http://{HOST}:{PORT}"
    log("=" * 58)
    log("  EasyTrader Option — Local Dashboard")
    log(f"  آدرس داشبورد:  {url}")
    log(f"  راهنمای توکن:  {url}/get-token")
    log("  برای توقف: Ctrl+C")
    log("=" * 58)

    # باز کردن خودکار مرورگر (بعد از ۰.۵ ثانیه تا سرور آماده شود)
    threading.Timer(0.5, lambda: _open_browser(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\nسرور متوقف شد. خداحافظ!")
        httpd.shutdown()


def _open_browser(url):
    target = url
    tok = get_token()
    if not tok or token_expired():
        # اگر توکن نداریم، اول صفحهٔ راهنمای دریافت توکن را باز می‌کنیم
        target = url + "/get-token"
    try:
        webbrowser.open(target)
    except Exception:
        pass


if __name__ == "__main__":
    main()
