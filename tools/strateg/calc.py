"""Воспроизводимые расчёты для продуктовых решений (только stdlib).

Каждая функция возвращает словарь: {"value": ..., "formula": "...", "details": {...}}.
Расчёт описывается спецификацией analysis/K*.json и запускается через `st.py calc run`.
Результат и хэш входов пишутся в K*.out.json, поэтому любой человек может повторить расчёт.
"""
from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()


def _z(q: float) -> float:
    return _N.inv_cdf(q)


# ---------------------------------------------------------------- эксперименты

def n_two_proportions(p1: float, p2: float, alpha: float = 0.05, power: float = 0.8,
                      two_sided: bool = True) -> dict:
    """Размер выборки на одно плечо для сравнения двух долей (нормальное приближение)."""
    if not (0 < p1 < 1 and 0 < p2 < 1) or p1 == p2:
        raise ValueError("нужны доли в (0;1), p1 != p2")
    za = _z(1 - alpha / 2) if two_sided else _z(1 - alpha)
    zb = _z(power)
    pbar = (p1 + p2) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    n = math.ceil(num / (p1 - p2) ** 2)
    return {"value": n, "unit": "единиц наблюдения на плечо",
            "formula": "n = [z(1-a/2)*sqrt(2*pbar*(1-pbar)) + z(1-b)*sqrt(p1(1-p1)+p2(1-p2))]^2 / (p1-p2)^2",
            "details": {"p1": p1, "p2": p2, "alpha": alpha, "power": power, "two_sided": two_sided,
                        "diff_pp": round((p2 - p1) * 100, 4), "diff_rel": round((p2 - p1) / p1, 4)}}


def design_effect(m: float, icc: float) -> dict:
    """DEFF = 1 + (m - 1) * ICC для кластерной рандомизации (кластер = семья/владелец)."""
    if m < 1 or not (0 <= icc <= 1):
        raise ValueError("m >= 1, 0 <= icc <= 1")
    return {"value": 1 + (m - 1) * icc, "unit": "множитель", "formula": "DEFF = 1 + (m-1)*ICC",
            "details": {"m": m, "icc": icc}}


def cluster_sample(p1: float, p2: float, m: float, icc: float, alpha: float = 0.05,
                   power: float = 0.8, arms: int = 2) -> dict:
    """Сколько кластеров (групп) нужно при кластерной рандомизации."""
    n = n_two_proportions(p1, p2, alpha, power)["value"]
    d = design_effect(m, icc)["value"]
    units = math.ceil(n * d)
    clusters = math.ceil(units / m)
    return {"value": clusters * arms, "unit": "кластеров всего",
            "formula": "кластеров на плечо = ceil(ceil(n*DEFF)/m); всего = на плечо * плеч",
            "details": {"n_individual_per_arm": n, "deff": round(d, 4), "units_per_arm": units,
                        "clusters_per_arm": clusters, "arms": arms, "m": m, "icc": icc}}


def mde_for_n(p1: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.8,
              direction: str = "down") -> dict:
    """Минимальный обнаружимый эффект при заданном n на плечо (поиск делением пополам)."""
    lo, hi = 1e-6, (p1 - 1e-6) if direction == "down" else (1 - p1 - 1e-6)
    for _ in range(200):
        mid = (lo + hi) / 2
        p2 = p1 - mid if direction == "down" else p1 + mid
        need = n_two_proportions(p1, p2, alpha, power)["value"]
        if need > n_per_arm:
            lo = mid
        else:
            hi = mid
    p2 = p1 - hi if direction == "down" else p1 + hi
    return {"value": round(hi * 100, 3), "unit": "п.п.",
            "formula": "наименьшее |p1-p2|, при котором n_two_proportions(p1,p2) <= n",
            "details": {"p1": p1, "p2": round(p2, 5), "n_per_arm": n_per_arm, "rel": round(hi / p1, 4)}}


def recruitment(required: float, weeks: float = None, rate_per_week: float = None,
                follow_up_weeks: float = 0) -> dict:
    """Темп набора: либо нужный темп за срок, либо срок при известном темпе (+ наблюдение)."""
    if weeks:
        r = required / weeks
        return {"value": math.ceil(r), "unit": "впервые подходящих в неделю",
                "formula": "темп = требуется / недель набора",
                "details": {"required": required, "weeks": weeks,
                            "total_weeks_with_follow_up": weeks + follow_up_weeks}}
    if rate_per_week:
        w = required / rate_per_week
        return {"value": round(w, 2), "unit": "недель набора",
                "formula": "недель = требуется / темп; итог = набор + наблюдение",
                "details": {"required": required, "rate_per_week": rate_per_week,
                            "total_weeks_with_follow_up": round(w + follow_up_weeks, 2)}}
    raise ValueError("нужно weeks или rate_per_week")


def ci_diff_proportions(x1: int, n1: int, x2: int, n2: int, conf: float = 0.95) -> dict:
    """Доверительный интервал разности долей (Ньюкомб, гибрид Уилсона) — п.п."""
    z = _z(1 - (1 - conf) / 2)

    def wilson(x, n):
        p = x / n
        den = 1 + z * z / n
        c = (p + z * z / (2 * n)) / den
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
        return p, c - h, c + h

    p1, l1, u1 = wilson(x1, n1)
    p2, l2, u2 = wilson(x2, n2)
    d = p2 - p1
    lo = d - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2)
    hi = d + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)
    return {"value": round(d * 100, 3), "unit": "п.п. (p2 - p1)",
            "formula": "Newcombe hybrid score interval",
            "details": {"p1": round(p1, 5), "p2": round(p2, 5), "ci_low_pp": round(lo * 100, 3),
                        "ci_high_pp": round(hi * 100, 3), "conf": conf}}


def pp_vs_relative(p_before: float, p_after: float) -> dict:
    return {"value": round((p_after - p_before) * 100, 4), "unit": "п.п.",
            "formula": "абсолютная = (после-до)*100 п.п.; относительная = (после-до)/до",
            "details": {"relative": round((p_after - p_before) / p_before, 4)}}


# ---------------------------------------------------------------- воронки и потоки

def funnel(top: float, rates: list, names: list = None) -> dict:
    """Воронка: top * r1 * r2 ... Возвращает число на каждом шаге."""
    steps, cur = [], float(top)
    names = names or [f"шаг{i + 1}" for i in range(len(rates))]
    for name, r in zip(names, rates):
        cur = cur * r
        steps.append({"step": name, "rate": r, "count": round(cur, 2)})
    return {"value": round(cur, 2), "unit": "на выходе воронки",
            "formula": "count_k = top * prod(rate_1..rate_k)", "details": {"top": top, "steps": steps}}


def stock_flow(start: float, new: float, churn: float) -> dict:
    """Сведение: конец = начало + новые - выбывшие."""
    return {"value": start + new - churn, "unit": "на конец периода",
            "formula": "end = start + new - churn",
            "details": {"start": start, "new": new, "churn": churn, "net": new - churn}}


def required_share(target: float, base: float) -> dict:
    """Какая доля базы должна выполнить условие (напр. 8000 активных из 12000 подключённых)."""
    return {"value": round(target / base, 4), "unit": "доля", "formula": "share = target / base",
            "details": {"target": target, "base": base}}


def incremental_cost(cost: float, conv_treated: float, conv_baseline: float) -> dict:
    """Стоимость дополнительного подключения относительно обычного обслуживания."""
    inc = conv_treated - conv_baseline
    if inc <= 0:
        return {"value": None, "unit": "руб. за доп. подключение",
                "formula": "cost / (conv_treated - conv_baseline)",
                "details": {"incremental": inc, "note": "прироста нет — стоимость не определена"}}
    return {"value": round(cost / inc, 2), "unit": "руб. за доп. подключение",
            "formula": "cost / (conv_treated - conv_baseline)",
            "details": {"cost": cost, "incremental": inc}}


# ---------------------------------------------------------------- экономика

def extra_paid_months_profit(numbers: float, extra_months: float, rate: float = 500.0) -> dict:
    """Вклад дополнительных оплаченных месяцев: номера * месяцы * ставка."""
    v = numbers * extra_months * rate
    return {"value": v, "unit": "руб.", "formula": "numbers * extra_months * rate",
            "details": {"numbers": numbers, "extra_months": extra_months, "rate": rate}}


def retention_gain(cohorts: list, rate: float = 500.0, months_in_year: int = 12) -> dict:
    """Помесячная сумма разниц удержания по когортам.

    cohorts: [{"start_month": 4, "size": 1000, "keep_new": [..], "keep_base": [..]}] —
    keep_*: доли продолжающих платить в 1-й, 2-й ... месяц после старта.
    Учитываются только месяцы, попадающие в плановый год (<= months_in_year).
    """
    total_months, rows = 0.0, []
    for c in cohorts:
        for k, (kn, kb) in enumerate(zip(c["keep_new"], c["keep_base"])):
            month = c["start_month"] + k
            if month > months_in_year:
                break
            extra = c["size"] * (kn - kb)
            total_months += extra
            rows.append({"month": month, "extra_paid_months": round(extra, 2)})
    return {"value": round(total_months * rate, 2), "unit": "руб. в плановом году",
            "formula": "sum_months size*(keep_new-keep_base) * rate",
            "details": {"extra_paid_months": round(total_months, 2), "rate": rate, "rows": rows}}


def break_even_months(target_profit: float, rate: float = 500.0, direct_costs: float = 0.0) -> dict:
    """Сколько доп. оплаченных месяцев нужно для прибавки target при прямых расходах."""
    need = math.ceil((target_profit + direct_costs) / rate)
    return {"value": need, "unit": "доп. оплаченных месяцев",
            "formula": "ceil((target + direct_costs) / rate)",
            "details": {"target_profit": target_profit, "direct_costs": direct_costs, "rate": rate}}


def payback(profit_by_q: list, invest_by_q: list) -> dict:
    """Квартал окупаемости: накопленная доп. прибыль после прямых расходов >= накопленные вложения."""
    cp = ci = 0.0
    rows, q_pay = [], None
    for i, (p, inv) in enumerate(zip(profit_by_q, invest_by_q), start=1):
        cp += p
        ci += inv
        rows.append({"q": i, "cum_profit": cp, "cum_invest": ci, "gap": cp - ci})
        if q_pay is None and cp >= ci and ci > 0:
            q_pay = i
    return {"value": q_pay, "unit": "номер квартала (None — не окупилось в горизонте)",
            "formula": "min q: sum(profit_1..q) >= sum(invest_1..q)", "details": {"rows": rows}}


def max_investment(profit_by_q: list, quarters: int) -> dict:
    """Предельная сумма вложений, которая вернётся за заданное число кварталов."""
    v = sum(profit_by_q[:quarters])
    return {"value": v, "unit": "руб.", "formula": "sum(profit_1..q)",
            "details": {"quarters": quarters, "profit_by_q": profit_by_q[:quarters]}}


def ltv(profit_per_period: float, survival: list, discount: float = 0.0) -> dict:
    """LTV = sum_t profit * S(t) / (1+d)^t (условный расчёт при нехватке данных об удержании)."""
    v = sum(profit_per_period * s / (1 + discount) ** t for t, s in enumerate(survival, start=1))
    return {"value": round(v, 2), "unit": "руб. за срок жизни",
            "formula": "sum_t profit*S(t)/(1+d)^t",
            "details": {"periods": len(survival), "discount": discount}}


def sensitivity(fn: str, base_args: dict, vary: dict) -> dict:
    """Пересчёт функции при разных значениях одного или нескольких параметров."""
    f = REGISTRY[fn]
    rows = []
    for name, values in vary.items():
        for v in values:
            args = dict(base_args, **{name: v})
            rows.append({"param": name, "value": v, "result": f(**args)["value"]})
    return {"value": rows, "unit": "таблица", "formula": f"{fn} при варьировании {list(vary)}",
            "details": {"base_args": base_args}}


def arithmetic(expr: str, names: dict) -> dict:
    """Простое выражение над именованными входами (+-*/ и скобки), без eval-кода."""
    import ast
    import operator as op
    if len(expr) > 400:
        raise ValueError("слишком длинное выражение")
    for k, v in names.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"вход {k} должен быть числом")

    def safe_pow(a, b):
        if abs(b) > 12 or abs(a) > 1e9:
            raise ValueError("степень вне допустимого диапазона")
        return a ** b

    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
           ast.USub: op.neg, ast.Pow: safe_pow}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.operand))
        raise ValueError(f"недопустимое выражение: {ast.dump(node)}")

    v = ev(ast.parse(expr, mode="eval"))
    return {"value": round(v, 6), "unit": "", "formula": expr, "details": {"inputs": names}}


def pool_recruitment(pool: float, monthly_prob: float, weeks: float, inflow_per_week: float = 0.0) -> dict:
    """Сколько единиц из КОНЕЧНОЙ базы войдёт в проверку за срок, если каждая входит один раз
    (первый подходящий случай с вероятностью monthly_prob в месяц) плюс приток новых единиц."""
    months = weeks / (52 / 12)
    from_pool = pool * (1 - (1 - monthly_prob) ** months)
    # новые единицы приходят равномерно; в среднем им доступна половина срока
    inflow = inflow_per_week * weeks * (1 - (1 - monthly_prob) ** (months / 2))
    total = from_pool + inflow
    return {"value": round(total, 1), "unit": "единиц вошло за срок",
            "formula": "pool*(1-(1-p)^мес) + приток*недель*(1-(1-p)^(мес/2))",
            "details": {"from_pool": round(from_pool, 1), "from_inflow": round(inflow, 1), "months": round(months, 2),
                        "share_of_pool": round(from_pool / pool, 4) if pool else None}}


def power_two_proportions(p1: float, p2: float, n_per_arm: float, alpha: float = 0.05) -> dict:
    """Мощность (вероятность обнаружить разницу p1→p2) при заданном n на плечо."""
    za = _z(1 - alpha / 2)
    pbar = (p1 + p2) / 2
    se0 = math.sqrt(2 * pbar * (1 - pbar) / n_per_arm)
    se1 = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n_per_arm)
    pw = _N.cdf((abs(p1 - p2) - za * se0) / se1)
    return {"value": round(pw, 4), "unit": "мощность", "formula": "Phi((|p1-p2| - z*se0)/se1)",
            "details": {"p1": p1, "p2": p2, "n_per_arm": n_per_arm, "alpha": alpha}}


REGISTRY = {f.__name__: f for f in [
    n_two_proportions, design_effect, cluster_sample, mde_for_n, recruitment, ci_diff_proportions,
    pp_vs_relative, funnel, stock_flow, required_share, incremental_cost, extra_paid_months_profit,
    retention_gain, break_even_months, payback, max_investment, ltv, sensitivity, arithmetic, pool_recruitment, power_two_proportions]}
