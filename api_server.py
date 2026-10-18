#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyTrader Option — API Server (FastAPI)
========================================
داشبورد + REST API برای اتصال «سیستم‌های دیگر و پروژه‌های دیگر».

ویژگی‌های اتصال:
  - Swagger UI خودکار:      http://127.0.0.1:8787/docs
  - ReDoc:                  http://127.0.0.1:8787/redoc
  - OpenAPI JSON (کد جنریت): http://127.0.0.1:8787/openapi.json
  - CORS سفارشی (config.json)
  - کلید API اختیاری برای دسترسی از روی شبکه (X-API-Key)
  - استریم SSE زنده:        /api/stream  (خروجی periodical — فشار کم)
  - محدودیت نرخ برای کلاینت‌های خارجی

 politeness (کم‌فشار بودن برای سایت):
  - کش هوشمند با TTL برای هر endpoint (زنجیره ۱۰ دقیقه)
  - حداقل ۳ ثانیه فاصله بین درخواست‌های خروجی واقعی
  - فقط GET/خواندن — بدون ثبت/حذف سفارش

config.json (خودکار ساخته می‌شود):
  {
    "host": "127.0.0.1",          // «0.0.0.0» برای دسترسی روی LAN
    "port": 8787,
    "api_key": null,              // مثل "s3cr3t" — وقتی ست باشد، کلاینت‌های غیرlocal باید بفرستند
    "cors_origins": ["*"],        // دامنه‌های مجاز CORS
    "rate_limit_per_min": 120     // درخواست‌در دقیقه به‌ازای هر IP خارجی
  }

اجرا:
    python api_server.py
"""

import asyncio
import json
import os
import sys
import threading
import time
import subprocess
from collections import defaultdict, deque

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import urllib.request as urlrequest
import urllib.error as urlerror

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

# ───────────────────────── مسیرها/پیکربندی ─────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
AUTH_FILE = os.path.join(BASE_DIR, "auth.json")

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8787,
    "api_key": None,
    "cors_origins": ["*"],
    "rate_limit_per_min": 120,
    "debug": False,
    "auto_update": True,
    "update_check_on_startup": True,
    "expose_docs": True,
    "max_request_bytes": 1048576,
}

def _load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    except Exception:
        pass
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cfg

CFG = _load_config()
DEBUG = bool(CFG.get("debug", False)) or os.environ.get("EASYTRADER_DEBUG", "").lower() in ("1","true","yes")

# ───────────────────────── توکن ─────────────────────────
_lock = threading.Lock()
_token = {"access_token": None, "expires_at": None, "updated_at": None}

def load_token_from_disk():
    try:
        if os.path.exists(AUTH_FILE):
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _token.update({
                "access_token": data.get("access_token"),
                "expires_at": data.get("expires_at"),
                "updated_at": data.get("updated_at"),
            })
    except Exception:
        pass

def token_expired() -> bool:
    tok, exp = _token.get("access_token"), _token.get("expires_at")
    if not tok: return True
    if not exp: return False
    try:
        e = int(exp)
        if e > 10**12: e //= 1000
        return e <= time.time()
    except Exception:
        return False

# ───────────────────────── کلاینت API سایت (کش + throttle) ─────────────────────────
API_BASE = "https://api-mts.orbis.easytrader.ir"
ORIGIN = "https://d.easytrader.ir"
OPTION_MARKET_UNITS = [45, 46, 47, 48]

MIN_GAP = 3.0
CACHE_TTL = {
    "/option/api/Positions": 30,
    "/option-asset/api/Assets/positions-profit-loss": 30,
    "/symbols/api/symbols/all": 600,
    "/core/api/order": 30,
    "/easy/api/money": 60,
    "/symbols/api/MarketData/tse-index": 30,
    "/option/api/Positions/settlements/gathering/status": 30,
}
DEFAULT_TTL = 60
_cache: dict = {}
_last_call: dict = {}

class ApiError(Exception):
    def __init__(self, code: str, http: int):
        self.code, self.http = code, http
        super().__init__(code)

def _throttle(key: str):
    now = time.time()
    with _lock:
        last = _last_call.get(key, 0)
        wait = MIN_GAP - (now - last)
        if wait > 0: time.sleep(wait)
        _last_call[key] = time.time()

def fetch_site(path: str, method: str = "GET", body=None):
    with _lock:
        entry = _cache.get(path)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL.get(path, DEFAULT_TTL):
        return entry["data"]

    tok = _token.get("access_token")
    if not tok: raise ApiError("NO_TOKEN", 401)
    _throttle(API_BASE + path)

    headers = {
        "Authorization": "Bearer " + tok,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fa",
        "Origin": ORIGIN, "Referer": ORIGIN + "/",
        "User-Agent": "EasyTraderLocalDash/1.1",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(API_BASE + path, data=data, headers=headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urlerror.HTTPError as e:
        if e.code in (401, 403): raise ApiError("UNAUTHORIZED", 401)
        raise ApiError(f"HTTP_{e.code}", 502)
    except urlerror.URLError as e:
        raise ApiError(f"NETWORK_{getattr(e, 'reason', e)}", 502)
    try: parsed = json.loads(raw)
    except Exception: parsed = raw
    with _lock:
        _cache[path] = {"ts": time.time(), "data": parsed}
    return parsed

# ───────────────────────── builderها ─────────────────────────
def build_summary() -> dict:
    out, errs = {}, {}
    def safe(k, path, **kw):
        try: out[k] = fetch_site(path, **kw)
        except ApiError as e: errs[k] = e.code; out[k] = None
    safe("positions", "/option/api/Positions")
    safe("pnl", "/option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod=false")
    safe("money", "/easy/api/money")
    safe("tseIndex", "/symbols/api/MarketData/tse-index")
    safe("settlementStatus", "/option/api/Positions/settlements/gathering/status")
    out["_errors"] = errs
    return out

def build_chain() -> dict:
    data = fetch_site("/symbols/api/symbols/all", method="POST", body={"hash": "null"})
    symbols = data.get("symbols") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    options = [s for s in symbols if s.get("marketUnit") in OPTION_MARKET_UNITS]
    return {"totalSymbols": len(symbols), "optionCount": len(options), "options": options}

def is_call(s) -> bool: return s.get("marketUnit") in (45, 48)

def filter_chain(q: str, ctype: str, target_units, limit: int, offset: int) -> dict:
    options = build_chain()["options"]
    if q:
        ql = q.lower()
        options = [s for s in options if ql in (str(s.get("title","")) + str(s.get("companyTitle","")) +
                   str(s.get("enTitle","")) + str(s.get("symbolIsin","")) + str(s.get("strikePrice",""))).lower()]
    if ctype == "call":  options = [s for s in options if is_call(s)]
    if ctype == "put":   options = [s for s in options if not is_call(s)]
    if target_units:     options = [s for s in options if s.get("marketUnit") in target_units]
    total = len(options)
    return {"total": total, "count": len(options[offset:offset+limit]),
            "items": options[offset:offset+limit]}

# ───────────────────────── rate-limit (کلاینت خارجی) ─────────────────────────
_hits: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
_rl_lock = threading.Lock()

def _is_local(request: Request) -> bool:
    ip = (request.client.host if request.client else "") or ""
    return ip in ("127.0.0.1", "::1", "localhost")

def _check_rate(request: Request):
    if _is_local(request): return
    limit = int(CFG.get("rate_limit_per_min") or 120)
    ip = request.client.host
    now = time.time()
    with _rl_lock:
        dq = _hits[ip]
        while dq and now - dq[0] > 60: dq.popleft()
        if len(dq) >= limit:
            raise HTTPException(429, "rate limit exceeded for external client")
        dq.append(now)

def _check_key(request: Request):
    """کلید API فقط برای کلاینت‌های غیرlocal لازم است."""
    if not CFG.get("api_key"): return
    if _is_local(request): return
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if key != CFG["api_key"]:
        raise HTTPException(401, "invalid or missing API key")

api_guard = [Depends(_check_rate), Depends(_check_key)]

def ok(data) -> dict: return {"ok": True, "data": data}
def fail(code: str, http: int):
    return JSONResponse({"ok": False, "error": code},
                        status_code=http if code not in ("NO_TOKEN","UNAUTHORIZED") else 401)

# ───────────────────────── FastAPI app ─────────────────────────
load_token_from_disk()
app = FastAPI(
    title="EasyTrader Option — Local API",
    description="REST API برای داده‌های بازار آپشن EasyTrader (فقط خواندن). "
                "مستندات تعاملی همین صفحه (Swagger) — برای اتصال از سایر سیستم‌ها به openapi.json کد بسازید.",
    version="1.3.0",
    debug=DEBUG,
    docs_url="/docs" if CFG.get("expose_docs", True) else None,
    redoc_url="/redoc" if CFG.get("expose_docs", True) else None,
)

# ── middleware: امنیت + محدودیت حجم + لاگ درخواست‌ها ──
@app.middleware("http")
async def security_and_log(request: Request, call_next):
    t0 = time.time()
    # محدودیت حجم body برای جلوگیری از سوءاستفاده
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > int(CFG.get("max_request_bytes") or 1048576):
        return JSONResponse({"ok": False, "error": "payload too large"}, status_code=413)
    try:
        response = await call_next(request)
    except Exception as e:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        response = JSONResponse(
            {"ok": False, "error": "INTERNAL", "detail": (str(e) if DEBUG else "internal error")},
            status_code=500,
        )
    # هدرهای امنیتی
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    dt = round((time.time() - t0) * 1000, 1)
    logger.debug("%s %s %s %sms (%s)", request.client.host if request.client else "-", request.method,
                 request.url.path, dt, response.status_code)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=CFG.get("cors_origins") or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return fail(exc.code, exc.http)

# ── مدل‌های پاسخ (برای Swagger خوانا) ──
class Envelope(BaseModel):
    ok: bool
    data: dict | list | None = None
    error: str | None = None

# ── صفحات داشبورد و حدس‌ها ──
@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))

@app.get("/style.css", include_in_schema=False)
def style(): return FileResponse(os.path.join(BASE_DIR, "static", "style.css"), media_type="text/css")

@app.get("/app.js", include_in_schema=False)
def appjs(): return FileResponse(os.path.join(BASE_DIR, "static", "app.js"), media_type="application/javascript")

@app.get("/get-token", include_in_schema=False)
def get_token_page(): return FileResponse(os.path.join(BASE_DIR, "get-token.html"))

@app.get("/save-token", include_in_schema=False)
def save_token_page(): return FileResponse(os.path.join(BASE_DIR, "save-token.html"))

@app.post("/api/token", include_in_schema=False)
async def post_token(request: Request):
    """دریافت توکن (از save-token.html) — همان behavior سرور قبلی."""
    body = await request.json()
    tok = (body or {}).get("access_token")
    if not tok:
        return JSONResponse({"ok": False, "error": "access_token خالی است"}, status_code=400)
    _token.update({"access_token": tok,
                   "expires_at": (body or {}).get("expires_at"),
                   "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({"access_token": tok, "expires_at": _token["expires_at"],
                       "updated_at": _token["updated_at"]}, f, ensure_ascii=False, indent=2)
    except Exception: pass
    _cache.clear()
    return {"ok": True, "message": "توکن ذخیره شد."}

# ═══════════════════ API عمومی (برای اتصال پروژه‌های دیگر) ═══════════════════
@app.get("/api/health", dependencies=api_guard, tags=["system"],
         summary="پراب زنده بودن — بدون توکن لازم")
def health():
    return {"status": "up", "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "token": "none" if not _token.get("access_token") else ("expired" if token_expired() else "valid"),
            "version": "1.3.1",
            "debug": DEBUG,
            "cacheEntries": len(_cache),
            "python": sys.version.split()[0]}

@app.get("/api/security/audit", dependencies=api_guard, tags=["security"],
         summary="گزارش امنیتی (وضعیت توکن، کلید، CORS، rate-limit، لاگ)")
def security_audit():
    import os as _os
    log_path = os.path.join(BASE_DIR, "server.log")
    log_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    auth_perms = None
    try:
        if os.path.exists(AUTH_FILE):
            import stat as _st
            auth_perms = oct(os.stat(AUTH_FILE).st_mode & 0o777)
    except Exception:
        pass
    return {
        "token": "none" if not _token.get("access_token") else ("expired" if token_expired() else "valid"),
        "api_key_set": bool(CFG.get("api_key")),
        "host_binding": CFG.get("host"),
        "cors_origins": CFG.get("cors_origins"),
        "rate_limit_per_min": CFG.get("rate_limit_per_min"),
        "max_request_bytes": CFG.get("max_request_bytes"),
        "expose_docs": CFG.get("expose_docs", True),
        "auto_update": CFG.get("auto_update", True),
        "debug": DEBUG,
        "log_file_bytes": log_size,
        "auth_file_perms": auth_perms,
        "uptime_check": "ok",
    }

@app.get("/api/update/check", dependencies=api_guard, tags=["update"],
         summary="بررسی وجود نسخهٔ جدیدتر روی GitHub")
def update_check():
    try:
        import updater
        remote, url, tag = updater.latest_release()
        cur = updater.current_version()
        return {"current": cur, "latest": remote, "tag": tag,
                "updateAvailable": updater._newer(remote, cur), "downloadUrl": url}
    except Exception as e:
        return {"current": "unknown", "latest": None, "error": str(e)}

@app.post("/api/update/apply", dependencies=api_guard, tags=["update"],
          summary="اعمال به‌روزرسانی (در پس‌زمینه؛ سرور پس از جایگزینی ری‌استارت می‌شود)")
def update_apply():
    def _run():
        try:
            import updater
            updater.check_and_apply(force=True, interactive=False)
        except Exception as e:
            logger.exception("update apply failed: %s", e)
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": "update started in background; server will restart"}

@app.get("/api/status", dependencies=api_guard, tags=["system"],
         summary="وضعیت اتصال و توکن")
def status():
    return {"hasToken": bool(_token.get("access_token")),
            "tokenExpired": token_expired(),
            "tokenUpdated": _token.get("updated_at"),
            "serverTime": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cacheEntries": len(_cache),
            "version": "1.1.0"}

@app.get("/api/summary", response_model=None, dependencies=api_guard, tags=["data"],
         summary="خلاصه: موقعیت‌ها + سود/زیان + موجودی + شاخص + تسویع")
def summary():
    return ok(build_summary())

@app.get("/api/positions", dependencies=api_guard, tags=["data"],
         summary="موقعیت‌های باز آپشن")
def positions():
    return ok(fetch_site("/option/api/Positions"))

@app.get("/api/pnl", dependencies=api_guard, tags=["data"],
         summary="سود/زیان باز و بسته")
def pnl():
    return ok(fetch_site("/option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod=false"))

@app.get("/api/orders", dependencies=api_guard, tags=["data"],
         summary="سفارش‌های در جریان")
def orders():
    return ok(fetch_site("/core/api/order"))

@app.get("/api/money", dependencies=api_guard, tags=["data"],
         summary="موجودی و خریدگان (t0/t1/t2)")
def money():
    return ok(fetch_site("/easy/api/money"))

@app.get("/api/index", dependencies=api_guard, tags=["data"],
         summary="شاخص کل بورس")
def index():
    return ok(fetch_site("/symbols/api/MarketData/tse-index"))

@app.get("/api/chain", dependencies=api_guard, tags=["option-chain"],
         summary="زنجیرهٔ آپشن با فیلتر (q / type / marketUnit / limit / offset)")
def chain(q: str = "", type: str = "", marketUnit: str = "", limit: int = 50, offset: int = 0):
    units = [int(x) for x in marketUnit.split(",") if x.strip().lstrip("-").isdigit()]
    return ok(filter_chain(q, type.lower(), units, min(max(limit,1),1000), max(offset,0)))

@app.get("/api/symbol/{ident}", dependencies=api_guard, tags=["option-chain"],
         summary="یک قرارداد: با ISIN یا بخشی از عنوان نماد")
def symbol(ident: str):
    options = build_chain()["options"]
    il = ident.strip().lower()
    hits = [s for s in options if il in (str(s.get("symbolIsin","")).lower(),
             str(s.get("title","")).lower(), str(s.get("enTitle","")).lower(),
             str(s.get("symbolName","")).lower(), str(s.get("strikePrice","")).lower())] if il else []
    if not hits: raise HTTPException(404, "no option contract matched")
    return ok(hits[:20])

@app.get("/api/stream", tags=["realtime"],
         summary="استریم SSE زنده (دادهٔ هر ۳۰ ثانیه از کش — بدون فشار اضافه)")
async def stream(request: Request):
    _check_key(request); _check_rate(request)
    async def gen():
        n = 0
        while True:
            if await request.is_disconnected(): break
            try:
                data = await asyncio.to_thread(build_summary)
                yield f"id: {n}\nevent: summary\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            except ApiError as e:
                yield f"event: error\ndata: {json.dumps({'error': e.code})}\n\n"
                break
            n += 1
            await asyncio.sleep(30)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store"})

# ───────────────────────── راه‌اندازی ─────────────────────────
import logging
import traceback

# ───────────────────────── لاگ (فایل + کنسول) ─────────────────────────
_log_handler = logging.FileHandler(os.path.join(BASE_DIR, "server.log"), encoding="utf-8")
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger = logging.getLogger("easytrader")
logger.setLevel(logging.DEBUG)
logger.addHandler(_log_handler)
logger.addHandler(_console)
logger.propagate = False

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    logger.info(msg)

def main():
    import uvicorn
    host, port = CFG.get("host") or "127.0.0.1", int(CFG.get("port") or 8787)
    log("=" * 58)
    log("EasyTrader Option — FastAPI Server")
    log(f"  داشبورد:    http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}")
    log(f"  Swagger:    http://127.0.0.1:{port}/docs")
    log(f"  ReDoc:      http://127.0.0.1:{port}/redoc")
    log(f"  OpenAPI:    http://127.0.0.1:{port}/openapi.json")
    log(f"  SSE اسریم:  http://127.0.0.1:{port}/api/stream")
    log(f"  Debug:      EASYTRADER_DEBUG=1  یا config.json -> debug:true")
    log(f"  لاگ فایل:   {os.path.join(BASE_DIR, 'server.log')}")
    if host == "0.0.0.0":
        key = CFG.get("api_key")
        if key:
            log(f"  دسترسی شبکه: فعال (کلید API تنظیم شده)")
        else:
            log("  ⚠ دسترسی روی شبکه فعال است ولی api_key ست نشده — در config.json ست کنید")
    log("=" * 58)
    # راه‌اندازی بررسی خودکار به‌روزرسانی در پس‌زمینه (غیرمسدودکننده)
    if CFG.get("auto_update", True) and CFG.get("update_check_on_startup", True):
        def _bg_update():
            time.sleep(8)  # بگذار سرور کاملاً بالا بیاید
            try:
                import updater
                updater.check_and_apply(force=False, interactive=False)
            except Exception as e:
                logger.exception("auto-update check failed: %s", e)
        threading.Thread(target=_bg_update, daemon=True).start()

    # محدودیت حجم لاگ فایل (حداکثر ~5MB)
    try:
        lp = os.path.join(BASE_DIR, 'server.log')
        if os.path.exists(lp) and os.path.getsize(lp) > 5 * 1024 * 1024:
            backup = lp + '.old'
            if os.path.exists(backup): os.remove(backup)
            os.replace(lp, backup)
    except Exception:
        pass

    uvicorn.run(app, host=host, port=port, log_level='debug' if DEBUG else 'warning')

if __name__ == "__main__":
    main()
