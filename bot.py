import base64
import logging
import os
import re
from urllib.parse import urlparse, unquote, parse_qs

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TIMEOUT_SECONDS = 12
MAX_RESULTS = 8

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("botID")


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 البحث عن قروبات وقنوات عامة", callback_data="help_search")],
        [InlineKeyboardButton("📖 الأوامر", callback_data="help_commands")],
    ])


def is_telegram_public_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
    except ValueError:
        return False



def is_valid_identifier(value: str) -> bool:
    """Return whether a value looks like a Telegram username or numeric ID."""
    return re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}|-?\d{5,20}", value) is not None


def unwrap_search_result_url(url: str, provider: str) -> str:
    """Convert supported search-engine redirect links into their destination URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    if "uddg" in params:
        return unquote(params["uddg"][0])
    if provider == "Bing":
        if params.get("url"):
            return unquote(params["url"][0])
        encoded = params.get("u", [""])[0]
        if encoded.startswith("a1"):
            payload = encoded[2:]
            try:
                padded = payload + "=" * ((4 - len(payload) % 4) % 4)
                decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
                if decoded.startswith(("http://", "https://")):
                    return decoded
            except (ValueError, UnicodeError):
                pass
    return url


def search_public_telegram(query: str, kind: str = "all") -> list[tuple[str, str]]:
    """Search several web indexes for public Telegram pages; never claims complete coverage."""
    cleaned = re.sub(r"\s+", " ", query).strip()[:120]
    if not cleaned:
        return []

    suffix = {
        "group": " (group OR chat)",
        "channel": " (channel OR news)",
        "all": "",
    }.get(kind, "")
    search_query = f"site:t.me {cleaned}{suffix}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.8",
    }
    providers = [
        ("DuckDuckGo", "https://html.duckduckgo.com/html/", {"q": search_query},
         ("a.result__a", "a.result-link")),
        ("DuckDuckGo Lite", "https://lite.duckduckgo.com/lite/", {"q": search_query},
         ("a.result-link", "a.result__a")),
        ("Bing", "https://www.bing.com/search", {"q": search_query},
         ("li.b_algo h2 a",)),
        # RSS is a separate fallback in case Bing's HTML page changes or blocks scraping.
        ("Bing RSS", "https://www.bing.com/search", {"q": search_query, "format": "rss"},
         ()),
    ]

    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    failures: list[str] = []

    for provider, endpoint, params, selectors in providers:
        # Keep RSS as a true fallback: avoid an extra request when HTML search already
        # returned results, or when all providers returned cleanly with no results.
        if provider == "Bing RSS" and (results or not failures):
            break
        try:
            response = requests.get(
                endpoint, params=params, headers=headers, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            if provider == "Bing RSS":
                soup = BeautifulSoup(response.text, "xml")
                entries = [
                    (item.title.get_text(" ", strip=True) if item.title else "",
                     item.link.get_text(strip=True) if item.link else "")
                    for item in soup.find_all("item")
                ]
            else:
                soup = BeautifulSoup(response.text, "html.parser")
                anchors = []
                for selector in selectors:
                    anchors = soup.select(selector)
                    if anchors:
                        break
                entries = [
                    (anchor.get_text(" ", strip=True), (anchor.get("href") or "").strip())
                    for anchor in anchors
                ]

            for title, url in entries:
                url = url.strip()
                if not url:
                    continue

                url = unwrap_search_result_url(url, provider)

                if not is_telegram_public_url(url):
                    continue
                path = urlparse(url).path.strip("/")
                if not path or path.startswith(("s/", "iv/")):
                    continue
                canonical = url.split("?")[0].rstrip("/")
                if canonical in seen:
                    continue
                seen.add(canonical)
                results.append((title[:180] or path, canonical))
                if len(results) >= MAX_RESULTS:
                    return results
        except Exception as exc:
            failures.append(f"{provider}: {type(exc).__name__}")
            logger.warning("%s public search failed (%s)", provider, type(exc).__name__)

    if not results and failures:
        raise RuntimeError("; ".join(failures))
    return results

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "أهلًا بك في botID 🤖\n\n"
        "أقدر أبحث عن روابط القروبات والقنوات العامة المفهرسة على الويب. "
        "النتائج ليست كاملة ولا تشمل القروبات الخاصة.\n\n"
        "جرّب:\n"
        "/search ألعاب\n"
        "/group ألعاب\n"
        "/channel أخبار التقنية\n"
        "/resolve @username\n\n"
        "لا أملك قاعدة بيانات عضويات مثل TgDB، لذلك لن أدّعي أنني أستطيع استخراج "
        "كل القروبات التي دخلها شخص من ID وحده."
    )
    await update.effective_message.reply_text(text, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "الأوامر:\n"
        "/search كلمة — البحث عن قروبات وقنوات عامة\n"
        "/group كلمة — البحث عن مجموعات عامة\n"
        "/channel كلمة — البحث عن قنوات عامة\n"
        "/resolve @username أو ID — البحث عن معلومات عامة مفهرسة\n"
        "/where ID — البحث عن ظهور عام للاسم أو المعرّف، وليس كشف العضويات\n"
        "/about — معلومات عن حدود البحث"
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "botID يستخدم بحث الويب للعثور على روابط Telegram العامة. "
        "ليس تابعًا لتيليجرام أو لأي خدمة بحث أخرى. النتائج تعتمد على فهرسة محرك البحث "
        "وقد تكون ناقصة أو قديمة. لا يمكن للبوت الوصول إلى المجموعات الخاصة أو قائمة "
        "عضويات أي حساب عشوائي من خلال Telegram Bot API."
    )


async def run_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    kind: str = "all",
    query_override: str | None = None,
) -> None:
    query = query_override if query_override is not None else " ".join(context.args)
    query = query.strip()
    if not query:
        await update.effective_message.reply_text(
            "اكتب كلمة البحث بعد الأمر. مثال: /search ألعاب"
        )
        return

    msg = await update.effective_message.reply_text("🔎 أبحث في صفحات Telegram العامة...")
    try:
        results = await context.application.create_task(
            __import__("asyncio").to_thread(search_public_telegram, query, kind)
        )
    except Exception as exc:
        logger.warning("Public search failed: %s", exc)
        # Keep the user-facing message useful while recording provider-level failures in logs.
        await msg.edit_text(
            "تعذّر الاتصال بمصادر البحث حاليًا. جرّب بعد قليل.\n"
            "إذا استمرت المشكلة، افتح سجلّ الخدمة (Logs) لمعرفة أي مصدر يرفض الطلبات."
        )
        return

    if not results:
        await msg.edit_text(
            "ما لقيت نتائج عامة مناسبة في فهرس الويب لهذه الكلمة. "
            "هذا لا يعني أن القروب غير موجود؛ جرّب كلمة أخرى أو اسمًا أدق."
        )
        return

    labels = {"all": "نتائج عامة", "group": "نتائج بحث المجموعات", "channel": "نتائج بحث القنوات"}
    lines = [f"🔎 {labels.get(kind, 'نتائج البحث')} عن: {query}", ""]
    for i, (title, url) in enumerate(results, 1):
        safe_title = title.replace("[", "(").replace("]", ")")
        lines.append(f"{i}. {safe_title}\n{url}")
    lines.append("\nقد تكون النتائج ناقصة أو قديمة؛ هذه روابط عامة مفهرسة وليست قائمة كاملة.")
    await msg.edit_text("\n".join(lines), disable_web_page_preview=True)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_search(update, context, "all")


async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_search(update, context, "group")


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_search(update, context, "channel")


async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    value = " ".join(context.args).strip()
    if not value:
        await update.effective_message.reply_text("مثال: /resolve @username أو /resolve 123456789")
        return
    if not is_valid_identifier(value):
        await update.effective_message.reply_text("أرسل username أو ID رقميًا بشكل صحيح.")
        return
    await run_search(update, context, "all", query_override=value)


async def where_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    value = " ".join(context.args).strip()
    if not value or not is_valid_identifier(value):
        await update.effective_message.reply_text(
            "استخدم الأمر هكذا: /where ID أو /where @username"
        )
        return
    # This searches only publicly indexed pages mentioning the identifier.
    # It cannot verify that a person is/was a member of the resulting groups.
    await run_search(
        update,
        context,
        "all",
        query_override=f'"{value}"'
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    value = (update.effective_message.text or "").strip()
    if not value:
        return
    # A bare numeric ID or @username should work without a command.
    if is_valid_identifier(value):
        await run_search(update, context, "all", query_override=f'"{value}"')
        return
    # Otherwise, treat plain text as a public group/channel search query.
    await run_search(update, context, "all", query_override=value)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "help_search":
        await query.message.reply_text(
            "أرسل /search كلمة للبحث العام، أو /group كلمة للمجموعات، أو /channel كلمة للقنوات."
        )
    elif query.data == "help_commands":
        await query.message.reply_text(
            "/search كلمة — البحث العام\n/group كلمة — مجموعات عامة\n/channel كلمة — قنوات عامة\n/resolve @username — بحث عن معرّف\n/where ID — غير متاح حاليًا"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled bot exception", exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير مضبوط. عيّن متغير البيئة BOT_TOKEN.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("group", group_command))
    app.add_handler(CommandHandler("channel", channel_command))
    app.add_handler(CommandHandler("resolve", resolve_command))
    app.add_handler(CommandHandler("where", where_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("botID public search bot is starting")
    app.run_polling()


if __name__ == "__main__":
    main()
