import asyncio
import logging
import os

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from app.config import settings
from app.db import db
from app.calculations import (
    subscription_economics,
    transactional_economics,
    b2b_economics,
)
from app.ai import ask

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

bot = Bot(settings.bot_token)
dp = Dispatcher()
app = FastAPI(title="Unit Economics Telegram Bot")

_render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
WEBHOOK_BASE_URL = (settings.webhook_base_url.strip() or (f"https://{_render_host}" if _render_host else "")).rstrip("/")
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}/telegram/webhook"
_webhook_task: asyncio.Task | None = None
_db_task: asyncio.Task | None = None




USER_FLOWS: dict[int, dict] = {}

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "Привет! Я консультант по юнит-экономике.\\n\\n"
        "Выберите модель бизнеса:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Подписка", callback_data="model:subscription")],
            [InlineKeyboardButton(text="🛒 Разовые продажи", callback_data="model:transaction")],
            [InlineKeyboardButton(text="🏢 B2B", callback_data="model:b2b")],
        ]),
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("model:"))
async def choose_model(c: CallbackQuery):
    model = c.data.split(":", 1)[1]
    labels = {
        "subscription": ("Подписка", [
            "Выручка за месяц (₽)?",
            "Маркетинговые расходы за месяц (₽)?",
            "Новые клиентов за месяц?",
            "Количество заказов за месяц?",
            "Себестоимость за месяц (₽)?",
            "Месячный churn (например 0.05 = 5%)?",
            "Фиксированные расходы за месяц (₽)?",
        ]),
        "transaction": ("Разовые/повторные продажи", [
            "Выручка за месяц (₽)?",
            "Маркетинговые расходы за месяц (₽)?",
            "Новые клиентов за месяц?",
            "Количество заказов за месяц?",
            "Себестоимость за месяц (₽)?",
            "Сколько заказов в месяц делает один клиент?",
            "Средний срок жизни клиента (месяцев)?",
            "Фиксированные расходы за месяц (₽)?",
        ]),
        "b2b": ("B2B", [
            "Годовая выручка с одного клиента (₽)?",
            "Маркетинговые расходы за год (₽)?",
            "Новых клиентов за год?",
            "Годовая себестоимость на одного клиента (₽)?",
            "Годовой churn (например 0.10 = 10%)?",
            "Фиксированные расходы за месяц (₽)?",
        ]),
    }
    if model not in labels:
        return await c.answer("Неизвестная модель", show_alert=True)
    title, questions = labels[model]
    USER_FLOWS[c.from_user.id] = {"model": model, "values": [], "questions": questions}
    await c.answer()
    await c.message.answer(f"Модель: {title}\\n\\nШаг 1/{len(questions)}\\n{questions[0]}\\n\\nВведите только число.")


@dp.message(Command("help"))
async def help_(m: Message):
    await m.answer(
        "Выберите модель через /calc или /start.\\n\\n"
        "Бот задаст вопросы по одному и после последнего покажет CAC, LTV, LTV/CAC, окупаемость CAC и точку безубыточности.\\n\\n"
        "Для AI: /ask ваш вопрос."
    )


@dp.message(Command("calc"))
async def calc_(m: Message):
    await m.answer(
        "Выберите модель:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Подписка", callback_data="model:subscription")],
            [InlineKeyboardButton(text="🛒 Разовые продажи", callback_data="model:transaction")],
            [InlineKeyboardButton(text="🏢 B2B", callback_data="model:b2b")],
        ]),
    )


def _fmt(r):
    lines = [f"CAC: {r['CAC']:.0f} ₽", f"LTV: {r['LTV']:.0f} ₽", f"LTV/CAC: {r['LTV_CAC']:.2f}"]
    if r.get("average_check") is not None:
        lines += [f"Средний чек: {r['average_check']:.0f} ₽", f"Валовая маржа: {r['gross_margin']:.1%}"]
    if r.get("annual_gross_margin") is not None:
        lines += [f"Годовая валовая маржа: {r['annual_gross_margin']:.1%}"]
    if r.get("expected_lifetime_months") is not None:
        lines.append(f"Ожидаемый срок жизни: {r['expected_lifetime_months']:.1f} мес.")
    if r.get("expected_lifetime_years") is not None:
        lines.append(f"Ожидаемый срок жизни: {r['expected_lifetime_years']:.1f} лет")
    if r.get("payback_months") is not None:
        lines.append(f"Окупаемость CAC: {r['payback_months']:.1f} мес.")
    if r.get("break_even_customers") is not None:
        lines.append(f"Точка безубыточности: {r['break_even_customers']:.1f} клиентов")
    return "\n".join(lines)


@dp.message()
async def text_(m: Message):
    p = (m.text or "").replace(",", ".").split()
    try:
        if len(p) == 7:
            r = subscription_economics(*map(float, p))
        elif len(p) == 8:
            r = transactional_economics(*map(float, p))
        elif len(p) == 6:
            r = b2b_economics(*map(float, p))
        else:
            return await m.answer("Не понял. Используйте /help.")
        await m.answer(_fmt(r))
    except ValueError as e:
        await m.answer(f"Ошибка: {e}")
    except Exception:
        logging.exception("Calculation failed")
        await m.answer("Не удалось выполнить расчёт. Проверьте исходные данные.")


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
    # Do not delete the webhook during a rolling deploy.
    try:
        await bot.session.close()
    finally:
        await db.close()


@app.post("/telegram/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_secret:
        raise HTTPException(403, "Forbidden")
    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}
