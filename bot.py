import logging
import os
import re
from urllib.parse import urlparse, unquote

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SEARCH_URL = "https://html.duckduckgo.com/html/"
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


def search_public_telegram(query: str, kind: str = "all") -> list[tuple[str, str]]:
    """Search web-indexed public Telegram pages. This is not a complete Telegram index."""
    cleaned = re.sub(r"\s+", " ", query).strip()[:120]
    if not cleaned:
        return []

    suffix = {
        "group": " (group OR chat)",
        "channel": " (channel OR news)",
        "all": "",
    }.get(kind, "")
    params = {"q": f"site:t.me {cleaned}{suffix}"}
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; botID-public-search/1.0)",
        "Accept-Language": "en-US,en;q=0.8",
    }
    response = requests.get(SEARCH_URL, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a.result__a"):
        title = anchor.get_text(" ", strip=True)
        url = anchor.get("href", "").strip()
        if not url:
            continue
        # DuckDuckGo may wrap result URLs in a redirect URL.
        if "uddg=" in url:
            from urllib.parse import parse_qs
            parsed = urlparse(url)
            url = unquote(parse_qs(parsed.query).get("uddg", [url])[0])
        if not is_telegram_public_url(url):
            continue
        path = urlparse(url).path.strip("/")
        if not path or path.startswith(("s/", "iv/")):
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append((title[:180] or path, url))
        if len(results) >= MAX_RESULTS:
            break
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
        "/where ID — غير متاح حاليًا؛ يحتاج قاعدة بيانات عضويات عامة مستقلة\n"
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
        await msg.edit_text(
            "تعذّر البحث الآن؛ قد يكون محرك البحث غير متاح أو يحدّ الطلبات. حاول لاحقًا."
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
    if not re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}|-?\d{5,20}", value):
        await update.effective_message.reply_text("أرسل username أو ID رقميًا بشكل صحيح.")
        return
    await run_search(update, context, "all", query_override=value)


async def where_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "ميزة /where غير متوفرة بعد. تحتاج قاعدة بيانات مستقلة تجمع بيانات المجموعات العامة "
        "وتربطها بمعرّفات المستخدمين، ولا يمكن استخراجها من Telegram Bot API وحده. "
        "لن أعرض نتائج مخمّنة أو أدّعي كشف عضويات غير متاحة."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    value = (update.effective_message.text or "").strip()
    if not value:
        return
    # Treat a plain text message as a public-group/channel search query.
    await run_search(update, context, "all", query_override=value)


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("botID public search bot is starting")
    app.run_polling()


if __name__ == "__main__":
    main()
