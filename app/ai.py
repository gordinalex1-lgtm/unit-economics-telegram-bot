import json

from openai import AsyncOpenAI
from app.config import settings

client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": settings.webhook_base_url,
        "X-Title": "Unit Economics Telegram Bot",
    },
)

SYSTEM = """Ты цифровой консультант по юнит-экономике для предпринимателя.
Отвечай по-русски, кратко и практически. Анализируй только переданные цифры.
Не выдумывай отсутствующие данные и явно отмечай важные допущения.
Не давай инвестиционных, юридических или медицинских советов.
Для анализа после расчёта используй структуру:
1. Диагноз — 1-2 предложения о состоянии экономики.
2. Ключевой показатель — какой показатель сильнее всего влияет на ситуацию и почему.
3. Риски — до 3 пунктов.
4. Действия — 3-5 конкретных действий в порядке приоритета.
5. Что проверить — до 3 дополнительных данных/допущений.
Не ставь категоричных оценок при недостатке данных."""


async def ask(prompt):
    r = await client.chat.completions.create(
        model=settings.openrouter_model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return r.choices[0].message.content or "Не удалось получить ответ модели."


async def analyze_unit_economics(result: dict) -> str:
    """Generate a concise business diagnosis from already calculated metrics."""
    prompt = (
        "Проведи анализ рассчитанной юнит-экономики. Ниже JSON с результатами расчёта. "
        "Сначала опирайся на фактические показатели, затем предложи действия.\\n\\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
    )
    return await ask(prompt)
