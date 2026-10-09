import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from server import app, init_db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or "0")
PORT = int(os.environ.get("PORT", "8080"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEBAPP_URL.startswith("https://"):
        await update.message.reply_text(
            "أهلًا بك في عجلة الحظ 🎡\n"
            "الموقع لم يُضبط بعد. على مدير البوت تعيين WEBAPP_URL إلى رابط HTTPS للاستضافة."
        )
        return
    keyboard = [[InlineKeyboardButton("🎡 افتح عجلة الحظ", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        "مرحبًا بك في عجلة الحظ! 🎁\n\n"
        "اجمع النقاط من الجوائز، واحصل على محاولة مجانية كل 24 ساعة.\n"
        "يمكنك أيضًا استخدام نقاطك لشراء محاولات إضافية.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "الأوامر:\n/start — فتح عجلة الحظ\n/balance — عرض رصيدك\n"
        "للمشرف: /addpoints USER_ID AMOUNT"
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from server import get_balance
    user = update.effective_user
    points = get_balance(user.id)
    await update.message.reply_text(f"💰 رصيدك الحالي: {points} نقطة")

async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("هذا الأمر مخصص للمشرف فقط.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("الاستخدام: /addpoints USER_ID AMOUNT")
        return
    try:
        user_id, amount = int(context.args[0]), int(context.args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("تأكد من إدخال رقم المستخدم ومقدار نقاط موجب.")
        return
    from server import add_points
    add_points(user_id, amount, "admin")
    await update.message.reply_text(f"تمت إضافة {amount} نقطة إلى المستخدم {user_id}.")

def run_web():
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in the hosting environment.")
    init_db()
    threading.Thread(target=run_web, daemon=True).start()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("addpoints", addpoints))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("Bot polling started.")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
