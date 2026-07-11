# PMXT Future Notes

این فایل برای آینده است. پروژه فعلی تا Phase 36 آماده تحویل است و PMXT داخل مسیر اصلی آن فعال نشده است.

هدف این یادداشت این است که اگر بعدا خواستیم PMXT را دوباره اضافه کنیم، تجربه های Phase 37 به بعد را فراموش نکنیم.

## تجربه های مهم

- PMXT برای گرفتن دیتای تحقیقاتی مفید است، اما باید خیلی محدود و کنترل شده استفاده شود.
- مشکل ها بیشتر از شبکه، VPN، timeout، خطای 403 و خطای 429 می آمدند.
- قبل از هر کار شبکه ای با PMXT باید doctor یا preflight اجرا شود.
- اگر doctor یا preflight پاس نشد، نباید سراغ ساخت دیتاست یا بک تست رفت.
- requestها باید کم باشند؛ retry زیاد نباید اضافه شود.
- در پلن رایگان، تعداد درخواست در دقیقه محدود است و هر REST call یک credit مصرف می کند.
- برای orderbook باید outcome token ID استفاده شود، نه market id، slug یا condition id.
- اگر outcome token ID موجود نبود، orderbook باید skip شود و فقط warning ثبت شود.
- دیتای BTC 5m واقعی قابل دریافت بود، اما orderbook همیشه کامل نبود.
- وقتی orderbook کامل نیست، بک تست باید research-only یا approximate باشد، نه مبنای live trading.
- PMXT نباید مسیر live trading، ارسال سفارش، cancel، retry، market making یا automation زنده را تغییر دهد.

## راهنمای ساده برای آینده

1. اول فقط PMXT key diagnostic را اجرا کن.
2. بعد network doctor یا preflight بگیر.
3. فقط یک market و چند ردیف دیتای کوچک تست کن.
4. اگر 403، 429 یا timeout آمد، مشکل را network/rate-limit/VPN فرض کن و stop کن.
5. اگر fetchMarkets جواب داد، از همان خروجی برای انتخاب outcome token ID استفاده کن.
6. اگر orderbook نشد، دیتاست را با trades و reference prices بساز و status را warning بگذار.
7. قبل از هر فاز بعدی، artifact و گزارش sanitized تولید کن.

## تصمیم ایمنی

- PMXT فقط برای data و research استفاده شود.
- live trading با PMXT تایید نشده است.
- live strategy automation با PMXT تایید نشده است.
- اگر PMXT بعدا اضافه شد، باید در branch جدا، با تست جدا و commit جدا انجام شود.

