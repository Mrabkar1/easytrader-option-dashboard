## اتصال از سیستم‌های دیگر / پروژه‌های دیگر (REST API)

نسخهٔ FastAPI یک REST API کامل + مستندات تعاملی (Swagger) ارائه می‌دهد:

- **Swagger UI:** `http://127.0.0.1:8787/docs`
- **ReDoc:** `http://127.0.0.1:8787/redoc`
- **OpenAPI (کد جنریت):** `http://127.0.0.1:8787/openapi.json`
- **استریم زنده (SSE):** `GET /api/stream` — هر ۳۰ ثانیهٔ یک‌بار دادهٔ خلاصه (بدون فشار اضافه به سایت)

### endpointهای اصلی

| متد | مسیر | توضیح |
|---|---|---|
| GET | `/api/health` | پراب زنده بودن + وضعیت توکن + نسخه (بدون توکن لازم) |
| GET | `/api/status` | وضعیت اتصال و توکن |
| GET | `/api/summary` | موقعیت‌ها + سود/زیان + موجودی + شاخص + تسویع |
| GET | `/api/positions` | موقعیت‌های باز |
| GET | `/api/pnl` | سود/زیان باز و بسته |
| GET | `/api/orders` | سفارش‌های در جریان |
| GET | `/api/money` | موجودی (t0/t1/t2) |
| GET | `/api/index` | شاخص کل |
| GET | `/api/chain?q=&type=call\|put&limit=&offset=` | زنجیرهٔ آپشن با فیلتر |
| GET | `/api/symbol/{ident}` | قرارداد با ISIN یا بخشی از عنوان/قیمت اعمال |
| GET | `/api/debug/ping` | echo برای تست اتصال |
| GET | `/api/debug/cache` | وضعیت کش (کلیدها + سن) |

تمام پاسخ‌های داده‌ای شکل `{ok: true, data: …}` دارند.

### نمونهٔ Python (httpx)
```python
import httpx
base = "http://127.0.0.1:8787"
r = httpx.get(base + "/api/summary").json()
print(r["data"]["pnl"]["openPositionsProfitLoss"])
```

### نمونهٔ JavaScript
```js
const r = await fetch("http://127.0.0.1:8787/api/chain?q=8500&limit=10");
const { data } = await r.json();
console.log(data.total, data.items.map(x => x.title));
```

### نمونهٔ cURL
```bash
curl -s http://127.0.0.1:8787/api/status
curl -s "http://127.0.0.1:8787/api/chain?type=call&limit=20"
```

### اتصال از دستگاه‌های دیگر (LAN)
در `config.json`:
```json
{
  "host": "0.0.0.0",
  "port": 8787,
  "api_key": "یک-کلید-قوی",
  "cors_origins": ["*"]
}
```
سپس کلاینت خارجی باید هدر `X-API-Key: یک-کلید-قوی` را بفرستد. بدون کلید فقط `127.0.0.1` دسترسی دارد.

### دیباگ
- `EASYTRADER_DEBUG=1 python api_server.py` → لاگ per-request + traceback کامل در 500
- لاگ فایل: `server.log` (در کنار سرور)
- `/api/health` فیلد `debug` را نشان می‌دهد
- `/api/debug/cache` سن کش هر endpoint را نمایش می‌دهد (برای اطمینان از freshness)

### محدودیت نرخ
کلاینت‌های غیرlocal: ۱۲۰ درخواست/دقیقه (configurable). کش سمت سرور هم همچنان فعال است.