"""Líneas base del tramo revisado (0.75 % de cada día), sin modelo.

Compromiso de E0 y E1: fijar los umbrales de las medidas técnicas con la línea base del
dataset. El PDF de E2 no pide modelado, pero las dos líneas base del ajuste de P1 (E1) se
calculan sin modelo:
  - orden aleatorio: esperado analítico, sin simulación. Si el tramo toma k_d de las n_d
    transacciones del día al azar, contiene en promedio k_d/n_d de los fraudes del día y
    k_d/n_d de su monto; sus aciertos esperados son la tasa de fraude del día.
  - regla simple «mayor importe primero»: la misma de la vista p2_tramo_diario de E1
    (k_d = techo(0.0075 n_d); orden por importe descendente y, en empate, por identificador).

Medidas de E0 (sección 5.3 del contexto), por día y agregadas:
  aciertos en el tramo   = fraudes en el tramo / k            (precisión en el tramo superior)
  monto cubierto         = monto defraudado en el tramo / monto defraudado del día
  fraude cubierto        = fraudes en el tramo / fraudes del día

Prevalencia ajustada (puente 2 del contexto): los aciertos dependen de cuánto fraude hay.
Con la tasa de detección (TPR) y la de falsos positivos (FPR) medidas, la precisión que
tendría la misma regla con otra prevalencia p es TPR p / (TPR p + FPR (1 - p)). Las
prevalencias de config.yaml son escenarios ilustrativos, no cifras de una institución.
"""

import numpy as np
import pandas as pd

from .comun import guardar_tabla


def por_dia(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    frac = cfg["tramo_revisado"]
    d = df[["TransactionID", "dia_relativo", "TransactionAmt", "isFraud"]].copy()
    d["monto_fraude"] = d["TransactionAmt"] * d["isFraud"]
    d = d.sort_values(
        ["dia_relativo", "TransactionAmt", "TransactionID"],
        ascending=[True, False, True],
    )
    d["posicion"] = d.groupby("dia_relativo").cumcount() + 1
    n = d.groupby("dia_relativo")["TransactionID"].transform("size")
    d["en_tramo"] = d["posicion"] <= np.ceil(frac * n)
    d["fraude_tramo"] = d["isFraud"] * d["en_tramo"]
    d["monto_fraude_tramo"] = d["monto_fraude"] * d["en_tramo"]
    t = (
        d.groupby("dia_relativo")
        .agg(
            transacciones=("isFraud", "size"),
            fraudes=("isFraud", "sum"),
            monto_fraude=("monto_fraude", "sum"),
            k=("en_tramo", "sum"),
            fraudes_tramo_regla=("fraude_tramo", "sum"),
            monto_fraude_tramo_regla=("monto_fraude_tramo", "sum"),
        )
        .reset_index()
    )
    t["periodo"] = ((t["dia_relativo"] - 1) // cfg["eda"]["periodo_dias"] + 1).clip(
        upper=cfg["eda"]["periodos"]
    )
    t["aciertos_regla"] = t["fraudes_tramo_regla"] / t["k"]
    t["aciertos_azar"] = t["fraudes"] / t["transacciones"]
    t["monto_cubierto_regla"] = t["monto_fraude_tramo_regla"] / t["monto_fraude"]
    t["monto_cubierto_azar"] = t["k"] / t["transacciones"]
    t["fraude_cubierto_regla"] = t["fraudes_tramo_regla"] / t["fraudes"]
    return t


def resumir(t: pd.DataFrame, etiqueta: str, prevalencias: list[float]) -> dict:
    k, n, f = t["k"].sum(), t["transacciones"].sum(), t["fraudes"].sum()
    tp = t["fraudes_tramo_regla"].sum()
    esperado_azar_fraudes = (t["k"] / t["transacciones"] * t["fraudes"]).sum()
    esperado_azar_monto = (t["k"] / t["transacciones"] * t["monto_fraude"]).sum()
    tpr, fpr = tp / f, (k - tp) / (n - f)
    r = {
        "grupo": etiqueta,
        "dias": len(t),
        "transacciones": int(n),
        "k_total": int(k),
        "fraudes": int(f),
        "aciertos_regla": tp / k,
        "aciertos_azar": esperado_azar_fraudes / k,
        "veces_sobre_azar_aciertos": (tp / k) / (esperado_azar_fraudes / k),
        "monto_cubierto_regla": t["monto_fraude_tramo_regla"].sum()
        / t["monto_fraude"].sum(),
        "monto_cubierto_azar": esperado_azar_monto / t["monto_fraude"].sum(),
        "fraude_cubierto_regla": tpr,
        "fraude_cubierto_azar": esperado_azar_fraudes / f,
        "tpr_regla": tpr,
        "fpr_regla": fpr,
        "aciertos_regla_dia_mediana": t["aciertos_regla"].median(),
        "monto_cubierto_regla_dia_mediana": t["monto_cubierto_regla"].median(),
        "monto_cubierto_regla_dia_p10": t["monto_cubierto_regla"].quantile(0.10),
        "monto_cubierto_regla_dia_p90": t["monto_cubierto_regla"].quantile(0.90),
    }
    for p in prevalencias:
        r[f"aciertos_regla_si_prev_{p:g}"] = tpr * p / (tpr * p + fpr * (1 - p))
        r[f"aciertos_azar_si_prev_{p:g}"] = p
    return r


def figura(t: pd.DataFrame, cfg: dict, log) -> None:
    """f11: aciertos y monto cubierto por día, regla simple frente a orden aleatorio (dos paneles)."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    from .figuras import AZUL, NARANJA, TEXTO_2, _guardar

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.8), sharex=True)
    for ax, col, etq in (
        (a1, "aciertos", "Aciertos en el tramo\n(% del tramo que es fraude)"),
        (a2, "monto_cubierto", "Monto cubierto\n(% del monto defraudado del día)"),
    ):
        ax.plot(
            t["dia_relativo"],
            100 * t[f"{col}_regla"],
            color=NARANJA,
            linewidth=1.6,
            label="regla simple: mayor importe primero",
        )
        ax.plot(
            t["dia_relativo"],
            100 * t[f"{col}_azar"],
            color=AZUL,
            linewidth=1.6,
            linestyle="--",
            label="orden aleatorio (esperado)",
        )
        ax.set_ylabel(etq)
        ax.set_ylim(0, None)
        ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        for b in range(
            cfg["eda"]["periodo_dias"],
            cfg["eda"]["periodo_dias"] * cfg["eda"]["periodos"],
            cfg["eda"]["periodo_dias"],
        ):
            ax.axvline(b + 0.5, color=TEXTO_2, linestyle=":", linewidth=1)
    a1.legend(loc="upper right", ncol=2, fontsize=8)
    a2.set_xlabel(
        "Día relativo (el tramo es el 0.75 % de las transacciones de cada día)"
    )
    a1.set_title(
        "Aciertos y monto cubierto en el tramo diario: regla simple frente a orden aleatorio"
    )
    fig.tight_layout()
    _guardar(fig, cfg, "f11_tramo_lineas_base", log)


def tramo(df: pd.DataFrame, cfg: dict, log) -> None:
    t = por_dia(df, cfg)
    assert int(t["transacciones"].sum()) == len(df) and int(t["fraudes"].sum()) == int(
        df["isFraud"].sum()
    )
    assert (t["k"] == np.ceil(cfg["tramo_revisado"] * t["transacciones"])).all(), (
        "k no coincide con la definición de E1"
    )
    guardar_tabla(t, cfg, "tramo_por_dia", log)
    figura(t, cfg, log)

    prev = cfg["eda"]["prevalencias_escenario"]
    filas = [resumir(t, "todos los días", prev)] + [
        resumir(g, f"periodo {p}", prev) for p, g in t.groupby("periodo")
    ]
    res = pd.DataFrame(filas)
    guardar_tabla(res, cfg, "tramo_resumen", log)

    r = res.iloc[0]
    log.info(
        "  k total: %s transacciones en el tramo (%.2f %% de %s)",
        f"{int(r['k_total']):,}",
        100 * r["k_total"] / r["transacciones"],
        f"{int(r['transacciones']):,}",
    )
    log.info(
        "  aciertos: regla %.2f %% · azar %.2f %% (%.2f veces)",
        100 * r["aciertos_regla"],
        100 * r["aciertos_azar"],
        r["veces_sobre_azar_aciertos"],
    )
    log.info(
        "  monto cubierto: regla %.2f %% · azar %.2f %%",
        100 * r["monto_cubierto_regla"],
        100 * r["monto_cubierto_azar"],
    )
    log.info(
        "  fraude cubierto: regla %.2f %% · azar %.2f %%",
        100 * r["fraude_cubierto_regla"],
        100 * r["fraude_cubierto_azar"],
    )
    for p in prev:
        log.info(
            "  con prevalencia %.2f %%: aciertos regla %.2f %% · azar %.2f %%",
            100 * p,
            100 * r[f"aciertos_regla_si_prev_{p:g}"],
            100 * p,
        )
