from openai import AsyncOpenAI
from app.config import settings
client=AsyncOpenAI(api_key=settings.openrouter_api_key,base_url="https://openrouter.ai/api/v1",default_headers={"HTTP-Referer":settings.webhook_base_url,"X-Title":"Unit Economics Telegram Bot"})
SYSTEM="""Ты цифровой консультант по юнит-экономике. Отвечай по-русски, кратко и практично. Объясняй расчёты и допущения. Если данных недостаточно — перечисли, что нужно добавить."""
async def ask(prompt):
    r=await client.chat.completions.create(model=settings.openrouter_model,messages=[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}],temperature=0.2)
    return r.choices[0].message.content or "Не удалось получить ответ модели."
