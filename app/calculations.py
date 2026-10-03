"""Unit-economics calculations for subscription, transactional and B2B models."""

def _validate_common(marketing_spend, new_customers, fixed_costs):
    if marketing_spend < 0:
        raise ValueError("Маркетинговые расходы не могут быть отрицательными")
    if new_customers <= 0:
        raise ValueError("Новые клиенты должны быть больше 0")
    if fixed_costs < 0:
        raise ValueError("Фиксированные расходы не могут быть отрицательными")


def _base_metrics(revenue, marketing_spend, new_customers, orders, cogs):
    if revenue <= 0:
        raise ValueError("Выручка должна быть больше 0")
    if orders <= 0:
        raise ValueError("Количество заказов должно быть больше 0")
    if cogs < 0:
        raise ValueError("Себестоимость не может быть отрицательной")
    if cogs > revenue:
        raise ValueError("Себестоимость не может быть больше выручки")

    cac = marketing_spend / new_customers
    average_check = revenue / orders
    gross_margin = (revenue - cogs) / revenue
    contribution_per_order = average_check * gross_margin

    return {
        "CAC": cac,
        "average_check": average_check,
        "gross_margin": gross_margin,
        "contribution_per_order": contribution_per_order,
    }


def subscription_economics(
    revenue, marketing_spend, new_customers, orders, cogs, monthly_churn, fixed_costs
):
    """Monthly recurring subscription model.

    Churn is monthly customer churn as a fraction (0.05 = 5%).
    LTV is gross-profit contribution over the expected customer lifetime.
    """
    _validate_common(marketing_spend, new_customers, fixed_costs)
    if not 0 < monthly_churn < 1:
        raise ValueError("Месячный отток укажите долей: 0.05 = 5%")

    r = _base_metrics(revenue, marketing_spend, new_customers, orders, cogs)
    contribution_per_customer_month = r["contribution_per_order"]
    expected_lifetime_months = 1 / monthly_churn
    ltv = contribution_per_customer_month * expected_lifetime_months
    payback_months = r["CAC"] / contribution_per_customer_month if contribution_per_customer_month > 0 else None
    break_even_customers = fixed_costs / contribution_per_customer_month if contribution_per_customer_month > 0 else None

    return {
        **r,
        "business_type": "subscription",
        "churn": monthly_churn,
        "expected_lifetime_months": expected_lifetime_months,
        "LTV": ltv,
        "LTV_CAC": ltv / r["CAC"] if r["CAC"] else None,
        "payback_months": payback_months,
        "break_even_customers": break_even_customers,
        "break_even_revenue": break_even_customers * r["average_check"] if break_even_customers else None,
        "fixed_costs": fixed_costs,
        "revenue": revenue,
        "current_customers": revenue / r["average_check"],
    }


def transactional_economics(
    revenue, marketing_spend, new_customers, orders, cogs,
    orders_per_customer_month, lifetime_months, fixed_costs
):
    """Transactional model with repeat purchase frequency and customer lifetime."""
    _validate_common(marketing_spend, new_customers, fixed_costs)
    if orders_per_customer_month <= 0:
        raise ValueError("Повторных заказов на клиента в месяц должно быть больше 0")
    if lifetime_months <= 0:
        raise ValueError("Срок жизни клиента в месяцах должен быть больше 0")

    r = _base_metrics(revenue, marketing_spend, new_customers, orders, cogs)
    monthly_contribution = r["contribution_per_order"] * orders_per_customer_month
    ltv = monthly_contribution * lifetime_months
    payback_months = r["CAC"] / monthly_contribution if monthly_contribution > 0 else None
    break_even_customers = fixed_costs / monthly_contribution if monthly_contribution > 0 else None

    return {
        **r,
        "business_type": "transactional",
        "orders_per_customer_month": orders_per_customer_month,
        "lifetime_months": lifetime_months,
        "monthly_contribution": monthly_contribution,
        "LTV": ltv,
        "LTV_CAC": ltv / r["CAC"] if r["CAC"] else None,
        "payback_months": payback_months,
        "break_even_customers": break_even_customers,
        "break_even_revenue": break_even_customers * r["average_check"] if break_even_customers else None,
        "fixed_costs": fixed_costs,
        "revenue": revenue,
        "current_customers": revenue / (r["average_check"] * orders_per_customer_month),
    }


def b2b_economics(
    annual_revenue_per_customer, marketing_spend, new_customers,
    annual_cogs_per_customer, annual_churn, fixed_costs
):
    """B2B model using annual economics per customer.

    Annual churn is the fraction of customers lost during a year.
    LTV is annual contribution divided by annual churn.
    """
    _validate_common(marketing_spend, new_customers, fixed_costs)
    if annual_revenue_per_customer <= 0:
        raise ValueError("Годовая выручка с клиента должна быть больше 0")
    if annual_cogs_per_customer < 0:
        raise ValueError("Годовая себестоимость не может быть отрицательной")
    if annual_cogs_per_customer > annual_revenue_per_customer:
        raise ValueError("Годовая себестоимость не может быть больше годовой выручки")
    if not 0 < annual_churn < 1:
        raise ValueError("Годовой отток укажите долей: 0.10 = 10%")

    cac = marketing_spend / new_customers
    annual_contribution = annual_revenue_per_customer - annual_cogs_per_customer
    annual_margin = annual_contribution / annual_revenue_per_customer
    lifetime_years = 1 / annual_churn
    ltv = annual_contribution * lifetime_years
    payback_months = cac / (annual_contribution / 12) if annual_contribution > 0 else None
    break_even_customers = fixed_costs / (annual_contribution / 12) if annual_contribution > 0 else None

    return {
        "business_type": "b2b",
        "CAC": cac,
        "annual_revenue_per_customer": annual_revenue_per_customer,
        "annual_gross_margin": annual_margin,
        "annual_contribution": annual_contribution,
        "churn": annual_churn,
        "expected_lifetime_years": lifetime_years,
        "LTV": ltv,
        "LTV_CAC": ltv / cac if cac else None,
        "payback_months": payback_months,
        "break_even_customers": break_even_customers,
        "break_even_revenue": break_even_customers * annual_revenue_per_customer if break_even_customers else None,
        "fixed_costs": fixed_costs,
    }


def unit_economics(revenue, marketing_spend, new_customers, orders, cogs, churn, fixed_costs):
    """Backward-compatible wrapper: the legacy calculation is subscription-style."""
    return subscription_economics(
        revenue, marketing_spend, new_customers, orders, cogs, churn, fixed_costs
    )


def target_profit_scenario(result: dict, target_monthly_profit: float) -> dict:
    """Calculate deterministic operating targets for a desired monthly profit."""
    if target_monthly_profit < 0:
        raise ValueError("Целевая прибыль не может быть отрицательной")

    business_type = result.get("business_type")
    fixed_costs = result.get("fixed_costs", 0)
    if fixed_costs is None:
        fixed_costs = 0

    if business_type == "b2b":
        monthly_contribution = result["annual_contribution"] / 12
        monthly_revenue_per_customer = result["annual_revenue_per_customer"] / 12
    else:
        if business_type == "transactional":
            monthly_contribution = result["monthly_contribution"]
            monthly_revenue_per_customer = (
                result["average_check"] * result["orders_per_customer_month"]
            )
        else:
            monthly_contribution = result["contribution_per_order"]
            monthly_revenue_per_customer = result["average_check"]

    if monthly_contribution <= 0:
        raise ValueError("Нельзя рассчитать цель: вклад клиента в прибыль должен быть больше 0")

    required_customers = (fixed_costs + target_monthly_profit) / monthly_contribution
    required_revenue = required_customers * monthly_revenue_per_customer
    current_revenue = result.get("revenue")
    current_customers = result.get("current_customers")
    additional_customers = (
        max(0, required_customers - current_customers)
        if current_customers is not None
        else None
    )

    return {
        "target_monthly_profit": target_monthly_profit,
        "required_customers": required_customers,
        "required_monthly_revenue": required_revenue,
        "additional_customers": additional_customers,
        "monthly_contribution_per_customer": monthly_contribution,
        "max_cac_6m_payback": monthly_contribution * 6,
        "max_cac_12m_payback": monthly_contribution * 12,
        "business_type": business_type,
    }
