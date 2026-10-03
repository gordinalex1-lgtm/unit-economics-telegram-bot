import json
import logging

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
Структура:
1. Диагноз — 1-2 предложения.
2. Ключевой показатель — какой показатель сильнее всего влияет на ситуацию и почему.
3. Риски — до 3 пунктов.
4. Действия — 3-5 конкретных действий в порядке приоритета.
5. Что проверить — до 3 дополнительных данных.
Всегда давай конкретные рекомендации по цене, марже, CAC, удержанию/churn, повторным продажам или количеству клиентов, только если это следует из цифр.
Не используй общие фразы вроде «улучшить маркетинг» без конкретного действия."""


async def ask(prompt):
    try:
        r = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            timeout=20,
        )
        return r.choices[0].message.content or ""
    except Exception:
        logging.exception("OpenRouter request failed")
        raise


def deterministic_analysis(result: dict) -> str:
    """Fallback recommendations so the bot always returns useful analysis."""
    lines = ["1. Диагноз — анализ выполнен по рассчитанным показателям."]
    cac = result.get("CAC")
    ltv = result.get("LTV")
    ratio = result.get("LTV_CAC")
    margin = result.get("gross_margin", result.get("annual_gross_margin"))
    payback = result.get("payback_months")
    actions = []

    if ratio is not None:
        if ratio < 1:
            actions.append("Приоритет №1 — снизить CAC и/или повысить вклад клиента: текущая экономика не окупает привлечение.")
        elif ratio < 3:
            actions.append("Приоритет №1 — снизить CAC и одновременно увеличить вклад клиента через цену, маржу или повторные продажи.")
        elif ratio > 7:
            actions.append("Проверьте, не занижен ли CAC или завышен LTV; отдельно проверьте удержание и фактическую валовую прибыль.")
        else:
            actions.append("LTV/CAC выглядит рабочим; основной резерв ищите в масштабе привлечения, марже и удержании.")

    if margin is not None:
        if margin < 0.3:
            actions.append("Низкая маржа: пересмотрите цену, себестоимость и скидки; цель — увеличить вклад с каждой продажи.")
        elif margin < 0.5:
            actions.append("Есть резерв маржи: протестируйте повышение цены, комплектацию и снижение прямой себестоимости.")
        else:
            actions.append("Маржа уже существенная; не жертвуйте ею ради роста выручки без проверки вклада после маркетинга.")

    if payback is not None:
        if payback > 12:
            actions.append("Окупаемость CAC слишком длинная для быстрого масштабирования: ограничьте CAC и ищите каналы с более коротким payback.")
        elif payback > 6:
            actions.append("Проверьте возможность сократить payback ниже 6 месяцев за счёт цены, маржи, первого платежа или повторных продаж.")

    if not actions:
        actions.append("Соберите фактические данные по CAC, марже, удержанию и повторным покупкам минимум за 3 месяца.")

    if cac is not None and ltv is not None:
        key = f"CAC {cac:.0f} ₽, LTV {ltv:.0f} ₽"
    else:
        key = "Ключевой показатель определяется доступными данными."
    lines.append(f"2. Ключевой показатель — {key}" + (f", LTV/CAC {ratio:.2f}." if ratio is not None else "."))
    lines.append("3. Риски — " + "; ".join(actions[:3]))
    lines.append("4. Действия — " + " ".join(actions[:5]))
    lines.append("5. Что проверить — фактическую маржу после всех переменных расходов, CAC по каждому каналу и удержание клиентов по когортам.")
    return "\n".join(lines)


async def analyze_unit_economics(result: dict) -> str:
    prompt = (
        "Проведи анализ рассчитанной юнит-экономики. JSON ниже — источник истины. "
        "Не пересчитывай и не выдумывай показатели. Дай практические рекомендации.\n\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
    )
    try:
        answer = await ask(prompt)
        if answer.strip():
            return answer.strip()
    except Exception:
        pass
    return deterministic_analysis(result)
