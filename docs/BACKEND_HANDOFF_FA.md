# سند تحویل Backend — Rastinax Agent AI v2

**وضعیت تحویل:** AI source آماده برای بررسی و یکپارچه‌سازی؛ تست End-to-End زنده و آزمایش مسیر سرور ایران تا دریافت Credential انجام نشده است. نباید قبل از آن Production-ready اعلام شود.

## مرز مسئولیت

فرانت سایت ← Backend سازمان ← **RastinaxAgent-AI** ← Provider خارجی یا Ollama داخلی.

Backend مسئول احراز هویت کاربر نهایی، مجوزها، محدودیت درخواست کاربران، مدیریت مکالمه، ثبت گفتگو و رضایت حریم خصوصی است. AI service مسئول prompt معتبر شرکت، محدودیت تاریخچه، Routing مدل، اجرای ابزارهای allowlisted، مدیریت خطا و Streaming است. API Key Provider و `AI_SERVICE_TOKEN` نباید وارد Frontend شوند.

## تنظیمات مشترک

- `AI_BASE_URL`: URL خصوصی AI از دید Backend، مثلاً `http://127.0.0.1:8000` وقتی هر دو در یک host هستند. این متغیر متعلق به Backend است، نه الزام AI service.
- `AI_SERVICE_TOKEN`: Secret مشترک؛ فقط در Secret store دو سرویس. پیشنهاد حداقل ۳۲ بایت تصادفی، چرخش دوره‌ای و عدم نمایش در لاگ.
- `AI_ENVIRONMENT=production`: جلوی Anonymous را می‌گیرد.
- `AI_PRIMARY_PROVIDER=kilo`, `KILO_MODEL=kilo-auto/free`, `KILO_API_KEY` جداگانه در Secret store AI.
- `AI_FALLBACK_PROVIDER=ollama` فقط وقتی Ollama مدل مناسب را آماده دارد. `AI_ALLOW_PRIVATE_HTTP=true` فقط برای شبکه خصوصی کنترل‌شده؛ ترجیح HTTPS یا loopback.

## Contract درخواست

`POST /api/v2/chat`

Headers:

    Authorization: Bearer <AI_SERVICE_TOKEN>
    Content-Type: application/json

Body:

    {"user_input":"لطفاً خدمات سئو را معرفی کن","chat_history":[{"role":"user","content":"سلام"},{"role":"assistant","content":"سلام، خوش آمدید."}]}

فیلد `user_input`: اجباری، رشته ۱ تا ۳۰۰۰ کاراکتر. `chat_history`: اختیاری؛ آرایه حداکثر ۱۶ پیام و مجموع حداکثر ۱۶۰۰۰ کاراکتر (قابل تنظیم)، هر پیام حداکثر ۴۰۰۰ کاراکتر. فقط `role=user|assistant` و `content` متنی مجازند؛ Roleهای system/developer/tool و کلیدهای اضافی رد می‌شوند. چت‌هیستوری فقط توسط Backend از پایگاه داده معتبر ساخته شود؛ تاریخچه فرانت را بدون تأیید منتقل نکنید.

Success (200):

    {"request_id":"d4fcd5c0f4b8424b8b59f8e5720d7c61","content":"...","provider":"kilo","model":"kilo-auto/free"}

`request_id` برای رهگیری داخلی است؛ `provider/model` برای گزارش‌دهی و عیب‌یابی است، نه ذخیره Secret.

## Streaming واقعی

`POST /api/v2/chat/stream` با همان Body و Header؛ `Content-Type: text/event-stream`. نمونه رویدادهای واقعی:

    event: start
    data: {"request_id":"abc123"}

    event: delta
    data: {"text":"سلام"}

    event: delta
    data: {"text":"، خوش آمدید."}

    event: done
    data: {"request_id":"abc123","provider":"kilo","model":"kilo-auto/free"}

در خطا:

    event: error
    data: {"request_id":"abc123","code":"PROVIDER_RATE_LIMITED"}

**نکته مهم:** پس از شروع Stream، HTTP معمولاً 200 می‌ماند؛ Backend باید event `error` را بخواند و آن را به وضعیت خطای کاربر ترجمه کند. تکمیل موفق تنها با `done` تأیید می‌شود. برای نیاز به کد وضعیت واقعی HTTP از Endpoint غیر-Streaming استفاده کنید.

**V1 Legacy:** `/api/v1/chat` ورودی را حفظ کرده و متن خام را در جریان خروجی می‌دهد؛ به عنوان API قدیمی نگه داشته شده، اما قرار نیست برای مصرف‌کننده جدید استفاده شود. این مسیر خطای داخلی را به متن عمومی تبدیل می‌کند و برای قرارداد دقیق مناسب نیست.

## جدول خطاها

| موقعیت | JSON HTTP | SSE event |
| --- | --- | --- |
| Bearer اشتباه/غایب | 401 UNAUTHORIZED | 401 قبل از شروع stream |
| توکن سرویس تنظیم نیست | 503 SERVICE_AUTH_NOT_CONFIGURED | 503 قبل از شروع stream |
| درخواست یا تاریخچه نامعتبر | 422 INVALID_INPUT/INVALID_HISTORY | 422 قبل از شروع stream |
| درخواست همزمان فراتر از حد | 503 AI_BUSY | 503 قبل از شروع stream |
| بدون Provider فعال | 503 AI_NOT_CONFIGURED | error: AI_NOT_CONFIGURED |
| اتمام سهمیه Provider | 429 PROVIDER_RATE_LIMITED | error: PROVIDER_RATE_LIMITED |
| رد شدن کلید Provider | 503 PROVIDER_AUTH_FAILED | error: PROVIDER_AUTH_FAILED |
| Provider 402 | 503 PROVIDER_BILLING_REQUIRED | error: PROVIDER_BILLING_REQUIRED |
| اختلال شبکه/Provider | 503 PROVIDER_UNAVAILABLE | error: PROVIDER_UNAVAILABLE |
| پاسخ خالی مدل | 503 EMPTY_PROVIDER_RESPONSE | error: EMPTY_PROVIDER_RESPONSE |

برای 429 می‌توانید به کاربر پیام «سهمیه موقتاً تکمیل است، بعداً تلاش کنید» نشان دهید. Retry کور با همان کلید، مخصوصاً برای RPD پایین، توصیه نمی‌شود. خطای 5xx را با backoff محدود در Backend مدیریت کنید؛ درخواست چندباره می‌تواند مصرف سهمیه را بالا ببرد.

## حداقل وظایف Backend برای پایان ادغام

1. پیاده‌سازی `IAiAgentClient` با Bearer سرویس؛ اتصال فقط Backend → AI. مقدار Key در Config server؛ هیچ Secrets داخل Repository/Frontend.
2. مسیر `POST /api/v2/chat` و برای چت زنده `POST /api/v2/chat/stream` را Consume کند. SSE decoder با پشتیبانی از split chunks، line endings و `event:error|done` نوشته شود.
3. ConversationId را در دیتابیس Backend مدیریت کند و تاریخچه مجاز user/assistant را با طول محدود بفرستد؛ System prompt ارسالی از فرانت نپذیرد.
4. Rate Limit فردی/سازمانی، anti-abuse، سقف روزانه، زمان انتظار و cancellation را در Backend فعال کند.
5. رویدادهای error را به خطاهای ثابت قرارداد داخلی تبدیل کند؛ PII و متن حساس را در لاگ رها نکند؛ request_id را برای tracing ثبت کند.
6. سیاست رضایت و نگهداری داده ارائه‌دهنده رایگان را تأیید کند؛ اطلاعات حساس نباید بدون موافقت به Gateway رایگان ارسال شود.
7. Integration tests با Mock و Live (روی سرور واقعی شبکه ایران) اجرا کند. وضعیت فیلتربودن سرویس و tool calling را در همان محیط بسنجد.
8. نسخه قدیمی v1 را پس از انتقال کامل کلاینت‌ها و دریافت تأیید Backend به صورت جداگانه حذف کند.

## چک‌‌های AI قبل از تحویل Production

- `GET /health/live` و `/health/ready` دو چیز متفاوت‌اند؛ Ready فقط صحت پیکربندی را می‌سنجد و تضمین E2E نیست.
- از محیط مقصد `python -m scripts.provider_probe` را با Key واقعی اجرا کنید؛ از خارج ایران به عنوان شاهد دسترسی ایران استفاده نکنید.
- تست در حالت بدون Key با پاسخ 503، حالت Key غلط با خطای provider، و 429 با fallback واقعی بررسی شود.
- در صورت تغییر مدل رایگان Kilo، tool calling و خروجی فارسی مجدداً Acceptance شوند.

## نکته هزینه و حریم خصوصی

سرویس رایگان دائمی با دسترسی ایران و پاسخ تضمین‌شده برای ترافیک Production اثبات نشده است. Kilo Gateway طبق مستندات رسمی ۲۰۰ request/hour/IP برای free دارد اما تضمین ظرفیت یا مدل خاص نمی‌دهد. برخی مدل‌های رایگان محتوای درخواست را برای بهبود سرویس پردازش یا ذخیره می‌کنند. در صورت نیاز امنیت بالا، مدل self-hosted با منابع کافی یا Gateway قراردادی پیشنهاد می‌شود.
