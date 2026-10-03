import asyncio
import json
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
    target_profit_scenario,
)
from app.ai import ask, analyze_unit_economics, deterministic_analysis

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


@dp.message(Command("cancel"))
async def cancel_(m: Message):
    if USER_FLOWS.pop(m.from_user.id, None) is not None:
        await m.answer("Расчёт отменён. Для нового расчёта: /calc")
    else:
        await m.answer("Активного расчёта нет.")


@dp.message(Command("history"))
async def history_(m: Message):
    try:
        items = await db.history(m.from_user.id, limit=5)
        if not items:
            return await m.answer("История пока пуста. Сделайте первый расчёт через /calc.")
        lines = ["📚 Последние расчёты:"]
        for i, item in enumerate(items, 1):
            data = json.loads(item.result)
            ltv_cac = data.get("LTV_CAC")
            ltv_cac_text = f"{ltv_cac:.2f}" if isinstance(ltv_cac, (int, float)) else "—"
            created = item.created_at.strftime("%d.%m %H:%M") if item.created_at else "—"
            lines.append(
                f"\\n{i}. {created} · {item.kind}\\n"
                f"CAC {data.get('CAC', 0):.0f} ₽ · "
                f"LTV {data.get('LTV', 0):.0f} ₽ · "
                f"LTV/CAC {ltv_cac_text}"
            )
        await m.answer("".join(lines))
    except Exception:
        logging.exception("History read failed")
        await m.answer("Не удалось загрузить историю. Попробуйте ещё раз.")


@dp.message(Command("goal"))
async def goal_(m: Message):
    try:
        target = float((m.text or "").split(maxsplit=1)[1].replace(",", "."))
    except (IndexError, ValueError):
        return await m.answer(
            "Укажите целевую прибыль в месяц после /goal. Например:\n/goal 500000"
        )

    try:
        items = await db.history(m.from_user.id, limit=1)
        if not items:
            return await m.answer("Сначала сделайте расчёт через /calc, затем задайте цель.")
        latest = json.loads(items[0].result)
        scenario = target_profit_scenario(latest, target)

        lines = [
            f"🎯 Целевая прибыль: {target:,.0f} ₽/мес.",
            "",
            f"Нужно клиентов: {scenario['required_customers']:.1f}",
            f"Нужная выручка: {scenario['required_monthly_revenue']:,.0f} ₽/мес.",
            f"Вклад одного клиента: {scenario['monthly_contribution_per_customer']:,.0f} ₽/мес.",
            f"Максимальный CAC для окупаемости за 6 мес.: {scenario['max_cac_6m_payback']:,.0f} ₽",
            f"Максимальный CAC для окупаемости за 12 мес.: {scenario['max_cac_12m_payback']:,.0f} ₽",
        ]
        if scenario["additional_customers"] is not None:
            lines.insert(3, f"Дополнительно клиентов: {scenario['additional_customers']:.1f}")

        analysis = None
        try:
            analysis = await asyncio.wait_for(
                ask(
                    "Проанализируй детерминированный сценарий достижения целевой месячной прибыли. "
                    "Не пересчитывай цифры и не придумывай данные. "
                    "Кратко укажи, какие рычаги стоит проверить в первую очередь.\n\n"
                    + json.dumps(scenario, ensure_ascii=False, indent=2)
                ),
                timeout=25,
            )
        except Exception:
            logging.exception("AI goal analysis failed")

        response = "📊 Сценарий достижения цели\n\n" + "\n".join(lines)
        if analysis:
            if len(analysis) > 2500:
                analysis = analysis[:2500].rsplit(" ", 1)[0] + "…"
            response += "\n\n🤖 AI-анализ\n" + analysis
        response += "\n\nОснова: последний расчёт из /history."
        await m.answer(response)
    except ValueError as e:
        await m.answer(f"Ошибка: {e}")
    except Exception:
        logging.exception("Goal scenario failed")
        await m.answer("Не удалось рассчитать сценарий. Проверьте последний расчёт через /history.")


@dp.message(Command("help"))
async def help_(m: Message):
    await m.answer(
        "Выберите модель через /calc или /start.\\n\\n"
        "Бот задаст вопросы по одному и после последнего покажет CAC, LTV, LTV/CAC, окупаемость CAC и точку безубыточности.\\n\\n"
        "Для AI: /ask ваш вопрос.\n\nИстория расчётов: /history. Отмена текущего ввода: /cancel."
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
    user_id = m.from_user.id
    flow = USER_FLOWS.get(user_id)
    if flow:
        raw = (m.text or "").replace(",", ".").strip()
        try:
            value = float(raw)
        except ValueError:
            return await m.answer("Введите одно число, например: 250000")

        flow["values"].append(value)
        step = len(flow["values"])
        total = len(flow["questions"])

        if step < total:
            return await m.answer(
                f"Шаг {step + 1}/{total}\n{flow['questions'][step]}\n\nВведите только число."
            )

        try:
            model = flow["model"]
            values = flow["values"]
            if model == "subscription":
                r = subscription_economics(*values)
            elif model == "transaction":
                r = transactional_economics(*values)
            else:
                r = b2b_economics(*values)
            USER_FLOWS.pop(user_id, None)
            metrics = _fmt(r)
            analysis = None
            try:
                analysis = await asyncio.wait_for(analyze_unit_economics(r), timeout=25)
                if len(analysis) > 3200:
                    analysis = analysis[:3200].rsplit(" ", 1)[0] + "…"
            except Exception:
                logging.exception("AI analysis failed after guided calculation")

            try:
                await db.save_calculation(
                    user_id, model, json.dumps(values, ensure_ascii=False),
                    json.dumps(r, ensure_ascii=False)
                )
            except Exception:
                logging.exception("Failed to save calculation history")

            response = "✅ Расчёт готов\\n\\n" + metrics
            if analysis:
                response += "\\n\\n🤖 AI-анализ\\n" + analysis
            else:
                response += "\\n\\n🤖 Анализ и рекомендации\\n" + deterministic_analysis(r)
            response += "\\n\\nИстория: /history · Новый расчёт: /calc"
            return await m.answer(response)

        except ValueError as e:
            USER_FLOWS.pop(user_id, None)
            return await m.answer(f"Ошибка: {e}\nНачните новый расчёт: /calc")
        except Exception:
            logging.exception("Guided calculation failed")
            USER_FLOWS.pop(user_id, None)
            return await m.answer("Не удалось выполнить расчёт. Начните новый: /calc")

    p = (m.text or "").replace(",", ".").split()
    try:
        if len(p) == 7:
            r = subscription_economics(*map(float, p))
        elif len(p) == 8:
            r = transactional_economics(*map(float, p))
        elif len(p) == 6:
            r = b2b_economics(*map(float, p))
        else:
            return await m.answer("Используйте /start или /calc.")
        metrics = _fmt(r)
        try:
            analysis = await asyncio.wait_for(analyze_unit_economics(r), timeout=25)
            if len(analysis) > 3200:
                analysis = analysis[:3200].rsplit(" ", 1)[0] + "…"
            await m.answer(metrics + "\n\n🤖 AI-анализ\n" + analysis)
        except Exception:
            logging.exception("AI analysis failed after legacy calculation")
            await m.answer(metrics + "\n\n🤖 AI-анализ временно недоступен.")
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
