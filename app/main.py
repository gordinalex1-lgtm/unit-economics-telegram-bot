import asyncio
import logging

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from app.config import settings
from app.db import db
from app.calculations import unit_economics
from app.ai import ask

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

bot = Bot(settings.bot_token)
dp = Dispatcher()
app = FastAPI(title="Unit Economics Telegram Bot")

WEBHOOK_URL = f"{settings.webhook_base_url.strip().rstrip('/')}/telegram/webhook"
_webhook_task: asyncio.Task | None = None
_db_task: asyncio.Task | None = None


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Привет! Я консультант по юнит-экономике.\n\n/calc — расчёт\n/ask — вопрос AI\n/help — помощь")


@dp.message(Command("help"))
async def help_(m: Message):
    await m.answer("Для AI: /ask У меня CAC 12000, чек 35000, маржа 40%, отток 5%. Что улучшить?")


@dp.message(Command("ask"))
async def ask_(m: Message):
    q = (m.text or "").partition(" ")[2].strip()
    if not q:
        return await m.answer("После /ask напишите вопрос.")
    try:
        await m.answer(await ask(q))
    except Exception:
        logging.exception("AI request failed")
        await m.answer("Ошибка обращения к OpenRouter.")


@dp.message(Command("calc"))
async def calc_(m: Message):
    await m.answer("Пришлите 7 чисел: выручка маркетинг новые_клиенты заказы себестоимость отток фиксированные_расходы\nПример: 1000000 200000 50 100 400000 0.05 250000")


@dp.message()
async def text_(m: Message):
    p = (m.text or "").replace(",", ".").split()
    if len(p) != 7:
        return await m.answer("Не понял. Используйте /help или /ask.")
    try:
        r = unit_economics(*map(float, p))
        await m.answer(
            f"CAC: {r['CAC']:.0f} ₽\n"
            f"Средний чек: {r['average_check']:.0f} ₽\n"
            f"Валовая маржа: {r['gross_margin']:.1%}\n"
            f"LTV: {r['LTV']:.0f} ₽\n"
            f"LTV/CAC: {r['LTV_CAC']:.2f}\n"
            f"Окупаемость CAC: {r['payback_months']:.2f} мес.\n"
            f"Точка безубыточности: {r['break_even_customers']:.1f} клиентов"
        )
    except Exception as e:
        await m.answer(f"Ошибка: {e}")


@app.get("/")
async def root():
    return {"status": "ok", "service": "unit-economics-telegram-bot"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


async def init_database():
    try:
        await asyncio.wait_for(db.init(), timeout=15)
        logging.info("Database initialized successfully")
    except Exception:
        logging.exception("Database initialization failed; application remains available")


async def register_webhook():
    await asyncio.sleep(5)
    for attempt in range(1, 6):
        try:
            logging.info("Registering Telegram webhook: %s", WEBHOOK_URL)
            await bot.set_webhook(
                url=WEBHOOK_URL,
                secret_token=settings.webhook_secret,
                drop_pending_updates=True,
            )
            logging.info("Telegram webhook registered successfully")
            return
        except Exception:
            logging.exception("Telegram webhook registration failed (attempt %s/5)", attempt)
            if attempt < 5:
                await asyncio.sleep(10)


@app.on_event("startup")
async def startup():
    global _webhook_task, _db_task
    _db_task = asyncio.create_task(init_database())
    _webhook_task = asyncio.create_task(register_webhook())
    logging.info("Application started; database and webhook initialization scheduled")


@app.on_event("shutdown")
async def shutdown():
    global _webhook_task, _db_task
    if _db_task is not None:
        _db_task.cancel()
        try:
            await _db_task
        except asyncio.CancelledError:
            pass

    if _webhook_task is not None:
        _webhook_task.cancel()
        try:
            await _webhook_task
        except asyncio.CancelledError:
            pass
    try:
        await bot.delete_webhook()
    finally:
        await bot.session.close()
        await db.close()


@app.post("/telegram/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_secret:
        raise HTTPException(403, "Forbidden")
    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}
