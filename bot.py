import logging
import os
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TGDB_URL = "https://www.tgdb.org/bot"
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("botID")


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 فتح بحث TgDB", url=TGDB_URL)],
        [InlineKeyboardButton("📣 بوت البحث الخفيف", url="https://t.me/tgdb_search_bot")],
    ])


START_TEXT = (
    "أهلًا بك في botID 🤖\n\n"
    "أرسل Telegram ID أو @username وسأرشدك إلى خيارات البحث المتاحة.\n\n"
    "⚠️ لا يستطيع بوت تيليجرام العادي استخراج جميع القروبات التي ينتمي إليها "
    "أي حساب من الـID وحده. البحث يعتمد على بيانات عامة مفهرسة لدى خدمات خارجية، "
    "ولا يضمن العثور على كل القروبات أو كشف القروبات الخاصة."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "الأوامر المتاحة:\n"
        "/start — بدء الاستخدام\n"
        "/help — المساعدة\n"
        "/about — معلومات عن البوت\n\n"
        "أرسل ID رقميًا أو @username. botID لا يطلب منك كلمة مرور أو رمز تحقق.",
        reply_markup=main_keyboard(),
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "botID مشروع مستقل غير تابع لتيليجرام أو TelegramDB.\n"
        "النسخة الحالية لا تتصل بقاعدة بيانات خارجية ولا تدّعي استخراج عضويات تلقائيًا؛ "
        "هي واجهة إرشادية إلى أدوات البحث العامة.",
        reply_markup=main_keyboard(),
    )


async def handle_identifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    value = (update.effective_message.text or "").strip()
    is_numeric_id = bool(re.fullmatch(r"-?\d{5,20}", value))
    is_username = bool(re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}", value))

    if not (is_numeric_id or is_username):
        await update.effective_message.reply_text(
            "ما قدرت أتعرف على المعرّف. أرسل ID رقميًا أو اسم مستخدم مثل @example_user.",
            reply_markup=main_keyboard(),
        )
        return

    await update.effective_message.reply_text(
        f"استلمت المعرّف: {value}\n\n"
        "لا يمكنني إظهار قائمة العضويات مباشرة من Telegram Bot API. افتح خدمة البحث "
        "الخارجية وأدخل المعرّف هناك إذا كانت الميزة متاحة. قد تكون النتائج ناقصة ولا "
        "تشمل القروبات الخاصة غير المفهرسة.",
        reply_markup=main_keyboard(),
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_identifier))
    app.add_error_handler(error_handler)
    logger.info("botID is starting")
    app.run_polling()


if __name__ == "__main__":
    main()
