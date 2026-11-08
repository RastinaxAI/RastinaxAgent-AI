# RastinaxAgent-AI — Marketing chatbot AI service

سرویس مستقل هوش مصنوعی راستیناکس (FastAPI / Python) با API سازگار با OpenAI، مدل رایگان قابل تنظیم، ابزارهای Agent، پاسخ JSON و استریم SSE.

## انتخاب Provider و محدودیت‌های واقعی

- **پیش‌فرض: Kilo Gateway — `kilo-auto/free`**. مستندات رسمی تا ۲۰۰ درخواست مدل رایگان در ساعت *به ازای IP* اعلام می‌کنند. این تضمین پاسخ روزانه یا SLA نیست و ظرفیت واقعی ممکن است با مدل و زمان تغییر کند. حساب کاربری و API Key برای استفاده از OpenAI SDK در این پروژه لازم است.
- **Groq اختیاری**: `openai/gpt-oss-20b` دارای Free Plan با سقف‌های RPM/RPD/TPD است، اما شواهدی از مسدودسازی مستقیم از ایران وجود دارد؛ فقط بعد از تست سرور استفاده شود.
- **OpenRouter Free اختیاری**: `openrouter/free` یا مدل `:free`، بدون انتخاب خودکار مدل پولی؛ سهمیه رایگان کم است و برای Production پرترافیک توصیه نمی‌شود.
- **Ollama اختیاری**: رایگان به ازای درخواست، اما هزینه محاسباتی، استقرار و ظرفیت سخت‌افزاری دارد؛ باید از قبل روی سرور موجود باشد.
- **Custom**: اتصال به Provider مجاز سازگار با OpenAI، از جمله ارائه‌دهندگان داخلی، با `CUSTOM_BASE_URL` و `CUSTOM_MODEL`.

هشدار حریم خصوصی: مدل‌های رایگان Kilo می‌توانند درخواست را به سرویس‌دهنده‌ای هدایت کنند که اطلاعات ورودی و خروجی را ثبت و برای بهبود سرویس استفاده کند. پیش از ورود اطلاعات محرمانه مشتریان، سیاست‌های نگهداری و رضایت/موافقت لازم بررسی شود. راهکار داده حساس: یک مدل self-hosted معتبر یا ارائه‌دهنده دارای قرارداد حفاظت داده.

## اجرای توسعه

1. `cp .env.example .env` (در ویندوز: `copy .env.example .env`)
2. `AI_PRIMARY_PROVIDER=kilo`، `KILO_API_KEY`، و یک `AI_SERVICE_TOKEN` تصادفی قوی را در `.env` تنظیم کنید. کلیدها را در Git یا چت منتشر نکنید.
3. `python -m pip install -r requirements-dev.txt`
4. `python -m pytest -q`
5. `uvicorn app.main:app --host 127.0.0.1 --port 8000`
6. `python -m scripts.provider_probe` را از همان سرور مقصد اجرا کنید تا مسیر شبکه و پذیرش درخواست واقعی بررسی شود.

برای آزمایش توسعه بدون توکن سرویس، فقط `AI_ENVIRONMENT=development` و `AI_ALLOW_ANONYMOUS_DEV=true` مجاز است. در Production فعال‌سازی anonymous ممنوع است.

## اجرای Production

1. مقادیر `.env` را با Secrets manager یا فایل امن تعریف کنید؛ `AI_ENVIRONMENT=production` و `AI_SERVICE_TOKEN` ضروری‌اند.
2. فقط سرویس Backend را قادر به دسترسی به پورت AI کنید؛ وب عمومی مستقیماً به API AI متصل نشود.
3. `docker compose -f docker-compose.example.yml up -d --build`؛ bind پیش‌فرض Docker روی loopback است.
4. `GET /health/live` را برای زنده بودن و `GET /health/ready` را برای کامل بودن پیکربندی بررسی کنید. Ready اتصال زنده به Provider را تضمین نمی‌کند.
5. روی همان سرور `python -m scripts.provider_probe` را اجرا کنید؛ خروجی فقط Provider و وضعیت را نشان می‌دهد نه API Key.
6. سپس Endpointها را از Backend بررسی کنید. به دلیل تغییر احراز هویت، Backend باید هدر Bearer را اضافه کند.

## Endpointهای ارتباطی

- `POST /api/v1/chat` — سازگاری با کلاینت قبلی: داده خام UTF-8 داخل بدنه stream؛ Deprecated. با وجود Content-Type قدیمی `text/event-stream`، رویداد SSE واقعی نیست.
- `POST /api/v2/chat` — خروجی JSON، با statusهای HTTP معتبر برای خطاها. مناسب Backend و عملیات غیرلحظه‌ای.
- `POST /api/v2/chat/stream` — SSE استاندارد: eventهای `start`، `delta`، `done`، `error`. مناسب UX چت زنده.
- `GET /health/live` — تست حیات بدون احراز هویت.
- `GET /health/ready` — بررسی وجود حداقل Provider و تنظیمات auth (بدون تماس خارجی).
- `GET /openapi.json` و `/docs` — قرارداد OpenAPI تولیدشده توسط FastAPI (در Production بهتر است از شبکه خصوصی محدود شود).

همه مسیرهای چت فقط با `Authorization: Bearer <AI_SERVICE_TOKEN>` در اختیار Backend هستند. اعتبارسنجی سهمیه هر کاربر، ذخیره مکالمه، کنترل هویت مشتری، تشخیص سوءاستفاده و گزارش‌گیری باید در Backend انجام شوند.

## اصول طراحی

- دستورات SYSTEM سمت سرویس قرار دارد و Roleهای system/developer/tool از تاریخچه ورودی پذیرفته نمی‌شوند.
- درخواست معمولی یک تماس استریم با مدل دارد؛ تماس دوم فقط برای Tool Calling انجام می‌شود.
- Fallback فقط برای خطای موقت/429 و قبل از انتشار متن به کاربر انجام می‌شود؛ پاسخ نصفه از دو مدل ترکیب نمی‌شود.
- درخواست‌ها بدون retry خودکار OpenAI SDK انجام می‌شوند تا سهمیه بی‌هدف مصرف نشود.
- اطلاعات ساختگی «رشد ۴۵٪ بازار» از ابزار بازاریابی حذف شده است.
- استفاده تصادفی از مدل‌های پولی OpenRouter/Kilo با اعتبارسنجی سخت‌گیرانه مدل ممنوع است.

**تحویل به بک‌اند**: سند کامل در `docs/BACKEND_HANDOFF_FA.md` و چک‌لیست تست پذیرش در `docs/ACCEPTANCE_TESTS_FA.md` است.

### منابع رسمی

- Kilo: https://kilo.ai/docs/gateway/usage-and-billing
- Kilo privacy note: https://kilo.ai/docs/getting-started/using-kilo-for-free
- Groq rate limits: https://console.groq.com/docs/rate-limits
- OpenRouter free: https://openrouter.ai/collections/free-models
