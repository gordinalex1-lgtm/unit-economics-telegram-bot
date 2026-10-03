def unit_economics(revenue, marketing_spend, new_customers, orders, cogs, churn, fixed_costs):
    if revenue <= 0: raise ValueError("Выручка должна быть больше 0")
    if new_customers <= 0: raise ValueError("Новые клиенты должны быть больше 0")
    if orders <= 0: raise ValueError("Количество заказов должно быть больше 0")
    if not 0 < churn < 1: raise ValueError("Отток укажите долей: 0.05 = 5%")
    cac=marketing_spend/new_customers
    avg= revenue/orders
    margin=(revenue-cogs)/revenue
    contribution=avg*margin
    ltv=contribution/churn
    payback=cac/contribution if contribution>0 else None
    be=fixed_costs/contribution if contribution>0 else None
    return {"CAC":cac,"average_check":avg,"gross_margin":margin,"LTV":ltv,"LTV_CAC":ltv/cac if cac else None,"payback_months":payback,"break_even_customers":be,"break_even_revenue":be*avg if be else None}
