import logging
from fastapi import FastAPI,Request,HTTPException
from aiogram import Bot,Dispatcher,types
from aiogram.filters import CommandStart,Command
from aiogram.types import Message
from app.config import settings
from app.db import db
from app.calculations import unit_economics
from app.ai import ask
logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO))
bot=Bot(settings.bot_token); dp=Dispatcher(); app=FastAPI(title="Unit Economics Telegram Bot")
@dp.message(CommandStart())
async def start(m:Message): await m.answer("Привет! Я консультант по юнит-экономике.\n\n/calc — расчёт\n/ask — вопрос AI\n/help — помощь")
@dp.message(Command("help"))
async def help_(m:Message): await m.answer("Для AI: /ask У меня CAC 12000, чек 35000, маржа 40%, отток 5%. Что улучшить?")
@dp.message(Command("ask"))
async def ask_(m:Message):
    q=(m.text or "").partition(" ")[2].strip()
    if not q: return await m.answer("После /ask напишите вопрос.")
    try: await m.answer(await ask(q))
    except Exception: logging.exception("AI request failed"); await m.answer("Ошибка обращения к OpenRouter.")
@dp.message(Command("calc"))
async def calc_(m:Message): await m.answer("Пришлите 7 чисел: выручка маркетинг новые_клиенты заказы себестоимость отток фиксированные_расходы\nПример: 1000000 200000 50 100 400000 0.05 250000")
@dp.message()
async def text_(m:Message):
    p=(m.text or "").replace(",",".").split()
    if len(p)!=7: return await m.answer("Не понял. Используйте /help или /ask.")
    try:
        r=unit_economics(*map(float,p))
        await m.answer(f"CAC: {r['CAC']:.0f} ₽\nСредний чек: {r['average_check']:.0f} ₽\nВаловая маржа: {r['gross_margin']:.1%}\nLTV: {r['LTV']:.0f} ₽\nLTV/CAC: {r['LTV_CAC']:.2f}\nОкупаемость CAC: {r['payback_months']:.2f} мес.\nТочка безубыточности: {r['break_even_customers']:.1f} клиентов")
    except Exception as e: await m.answer(f"Ошибка: {e}")
@app.get("/")
async def root(): return {"status":"ok","service":"unit-economics-telegram-bot"}
@app.get("/health")
async def health(): return {"status":"healthy"}
@app.on_event("startup")
async def startup():
    await db.init(); await bot.set_webhook(url=f"{settings.webhook_base_url.rstrip('/')}/telegram/webhook",secret_token=settings.webhook_secret,drop_pending_updates=True)
@app.on_event("shutdown")
async def shutdown(): await bot.delete_webhook(); await bot.session.close()
@app.post("/telegram/webhook")
async def webhook(request:Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token")!=settings.webhook_secret: raise HTTPException(403,"Forbidden")
    await dp.feed_update(bot,types.Update.model_validate(await request.json())); return {"ok":True}
