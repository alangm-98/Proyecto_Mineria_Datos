"""Brecha entre IEEE-CIS y la referencia de México (Banxico, CF621).

Compromiso de E1 (supuesto 1 y riesgo 1 de E0): medir la brecha, no cerrarla. Se espera
que las cifras no coincidan; el entregable es la magnitud documentada.

Comparación en el mismo tiempo: con el supuesto de fecha (día 1 = 2 dic 2017), los 182 días
caen en tres trimestres de Banxico: oct-dic 2017 (solo diciembre, días 1 a 30), ene-mar
2018 (días 31 a 120) y abr-jun 2018 (días 121 a 182). La asignación depende del supuesto,
que puede estar corrido un día (riesgo 9): afecta a lo más un día por trimestre.

Lo que sí es comparable sin convertir moneda (medidas sin unidades):
  - tasa de fraude o contracargo, por número y por monto;
  - razón crédito / débito de esas tasas;
  - proporción de débito en las operaciones;
  - razón entre el ticket promedio de crédito y el de débito.
Lo que no es comparable: el ticket en niveles (dólares de EUA en 2017-2018 frente a
pesos), y los denominadores no son iguales (IEEE: transacciones del conjunto; Banxico:
operaciones autorizadas). La etiqueta de IEEE incluye además transacciones ligadas a una
cuenta con contracargo (post oficial de Kaggle), y Banxico cuenta todos los contracargos,
no solo los de fraude. Estas diferencias se declaran junto a cada cifra.

Definiciones de Banxico idénticas a la vista p2_referencia_mexico de E1: los porcentajes se
ponderan por autorizaciones (número) o por monto; compra promedio = monto x 1e6 / número.
"""

import numpy as np
import pandas as pd

from .comun import cliente, guardar_tabla, tabla

TRIMESTRES_IEEE = ["2017-10-01", "2018-01-01", "2018-04-01"]
REFERENCIA_ACTUAL = "2026-01-01"


def _ieee_por_trimestre(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    ref = pd.Timestamp(cfg["supuestos"]["fecha_referencia_ieee"])
    fecha = ref + pd.to_timedelta(df["dia_relativo"], unit="D")
    trimestre = fecha.dt.to_period("Q").dt.start_time.dt.strftime("%Y-%m-%d")
    d = df.assign(
        trimestre=trimestre, monto_fraude=df["TransactionAmt"] * df["isFraud"]
    )
    filas = []
    for (trim, tipo), g in [((t, "total"), g) for t, g in d.groupby("trimestre")] + [
        ((t, c), g)
        for (t, c), g in d[d["card6"].isin(["credit", "debit"])].groupby(
            ["trimestre", "card6"]
        )
    ]:
        filas.append(
            {
                "fuente": "IEEE-CIS",
                "trimestre": trim,
                "tipo": {"credit": "crédito", "debit": "débito"}.get(tipo, tipo),
                "operaciones": len(g),
                "dias": g["dia_relativo"].nunique(),
                "pct_num": 100 * g["isFraud"].mean(),
                "pct_monto": 100 * g["monto_fraude"].sum() / g["TransactionAmt"].sum(),
                "ticket_promedio": g["TransactionAmt"].mean(),
                "moneda": "USD",
            }
        )
    return pd.DataFrame(filas)


def _banxico_por_trimestre(cfg: dict, log) -> pd.DataFrame:
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["banxico_trimestres"])
    trabajo = cliente(cfg).query(
        f"SELECT * FROM `{origen}` ORDER BY fecha_inicio_trimestre"
    )
    b = trabajo.result().to_dataframe()
    log.info(
        "  Banxico: %d trimestres (%.1f MB procesados)",
        len(b),
        (trabajo.total_bytes_processed or 0) / 1e6,
    )
    filas = []
    for _, r in b.iterrows():
        for tipo, suf in (
            ("total", "total"),
            ("crédito", "credito"),
            ("débito", "debito"),
        ):
            filas.append(
                {
                    "fuente": "Banxico CF621",
                    "trimestre": r["fecha_inicio_trimestre"].strftime("%Y-%m-%d"),
                    "tipo": tipo,
                    "operaciones": int(r[f"aut_num_{suf}"]),
                    "dias": np.nan,
                    "pct_num": float(r[f"pct_contracargo_num_{suf}"]),
                    "pct_monto": float(r[f"pct_contracargo_monto_{suf}"]),
                    "ticket_promedio": r[f"aut_mdp_{suf}"] * 1e6 / r[f"aut_num_{suf}"],
                    "moneda": "MXN",
                    "monto_mdp": float(r[f"aut_mdp_{suf}"]),
                }
            )
    return pd.DataFrame(filas)


def _agregado(
    t: pd.DataFrame, fuente: str, trimestres: list[str], etiqueta: str
) -> pd.DataFrame:
    """Promedio del periodo ponderado por operaciones (número) y por monto (monto), por tipo."""
    s = t[(t["fuente"] == fuente) & (t["trimestre"].isin(trimestres))].copy()
    monto = (
        s["monto_mdp"]
        if "monto_mdp" in s and s["monto_mdp"].notna().all()
        else s["operaciones"] * s["ticket_promedio"]
    )
    s = s.assign(_monto=monto)
    filas = []
    for tipo, g in s.groupby("tipo"):
        filas.append(
            {
                "fuente": fuente,
                "trimestre": etiqueta,
                "tipo": tipo,
                "operaciones": int(g["operaciones"].sum()),
                "dias": g["dias"].sum() if g["dias"].notna().all() else np.nan,
                "pct_num": np.average(g["pct_num"], weights=g["operaciones"]),
                "pct_monto": np.average(g["pct_monto"], weights=g["_monto"]),
                "ticket_promedio": g["_monto"].sum() / g["operaciones"].sum()
                if fuente == "IEEE-CIS"
                else g["_monto"].sum() * 1e6 / g["operaciones"].sum(),
                "moneda": g["moneda"].iloc[0],
            }
        )
    return pd.DataFrame(filas)


def _razones(t: pd.DataFrame) -> pd.DataFrame:
    """Medidas sin unidades por fuente y periodo: crédito/débito y proporción de débito."""
    filas = []
    for (fuente, trim), g in t.groupby(["fuente", "trimestre"]):
        g = g.set_index("tipo")
        if not {"crédito", "débito", "total"} <= set(g.index):
            continue
        filas.append(
            {
                "fuente": fuente,
                "trimestre": trim,
                "razon_tasa_num_credito_debito": g.loc["crédito", "pct_num"]
                / g.loc["débito", "pct_num"],
                "razon_tasa_monto_credito_debito": g.loc["crédito", "pct_monto"]
                / g.loc["débito", "pct_monto"],
                "razon_ticket_credito_debito": g.loc["crédito", "ticket_promedio"]
                / g.loc["débito", "ticket_promedio"],
                "prop_debito": g.loc["débito", "operaciones"]
                / (g.loc["débito", "operaciones"] + g.loc["crédito", "operaciones"]),
            }
        )
    return pd.DataFrame(filas)


def figura(tabla_t: pd.DataFrame, raz: pd.DataFrame, cfg: dict, log) -> None:
    """f10: tasas por tipo de tarjeta (IEEE frente a Banxico, escala log) y razones sin unidades."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    from .figuras import AZUL, FONDO, NARANJA, TEXTO_2, _guardar

    per = tabla_t[tabla_t["trimestre"].str.startswith("periodo")]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    tipos = ["total", "crédito", "débito"]
    x = np.arange(len(tipos))
    for k, (fuente, color, trama) in enumerate(
        (("IEEE-CIS", NARANJA, "//"), ("Banxico CF621", AZUL, ""))
    ):
        s = per[per["fuente"] == fuente].set_index("tipo").loc[tipos]
        b = a1.bar(
            x + (k - 0.5) * 0.36,
            s["pct_num"],
            width=0.34,
            color=color,
            hatch=trama,
            edgecolor=FONDO,
            label=f"{fuente}: {'fraude' if fuente == 'IEEE-CIS' else 'contracargos'}, % del número",
        )
        a1.bar_label(b, fmt="%.2f %%", fontsize=8, padding=2)
    a1.set_yscale("log")
    a1.set_ylim(0.05, 30)
    a1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g} %"))
    a1.set_xticks(x, ["Todas", "Crédito", "Débito"])
    a1.set_ylabel("Porcentaje de operaciones (escala logarítmica)")
    a1.set_title("Tasas en el periodo de IEEE (dic 2017 a jun 2018)", fontsize=11)
    a1.legend(loc="upper right", fontsize=8)
    r = raz[raz["trimestre"].str.startswith("periodo")].set_index("fuente")
    medidas = [
        ("razon_tasa_num_credito_debito", "Tasa por número"),
        ("razon_tasa_monto_credito_debito", "Tasa por monto"),
        ("razon_ticket_credito_debito", "Ticket promedio"),
    ]
    x2 = np.arange(len(medidas))
    for k, (fuente, color, trama) in enumerate(
        (("IEEE-CIS", NARANJA, "//"), ("Banxico CF621", AZUL, ""))
    ):
        vals = [r.loc[fuente, m] for m, _ in medidas]
        b = a2.bar(
            x2 + (k - 0.5) * 0.36,
            vals,
            width=0.34,
            color=color,
            hatch=trama,
            edgecolor=FONDO,
            label=fuente,
        )
        a2.bar_label(b, fmt="%.2f", fontsize=8, padding=2)
    a2.axhline(1, color=TEXTO_2, linestyle=":", linewidth=1)
    a2.set_ylim(0, 1.3 * max(r.loc[f, m] for f in r.index for m, _ in medidas))
    a2.set_xticks(x2, [e for _, e in medidas])
    a2.set_ylabel("Crédito ÷ débito (1 = iguales)")
    a2.set_title("Razones crédito / débito (sin unidades)", fontsize=11)
    a2.legend(loc="upper left", fontsize=8, ncol=2)
    fig.suptitle(
        "IEEE-CIS frente a México: niveles muy distintos, mismo patrón crédito > débito",
        fontweight="bold",
        fontsize=12,
    )
    fig.tight_layout()
    _guardar(fig, cfg, "f10_brecha_mexico", log)


def mexico(df: pd.DataFrame, cfg: dict, log) -> None:
    ieee = _ieee_por_trimestre(df, cfg)
    banx = _banxico_por_trimestre(cfg, log)
    assert int(ieee.loc[ieee["tipo"] == "total", "operaciones"].sum()) == len(df), (
        "IEEE: trimestres incompletos"
    )
    assert set(TRIMESTRES_IEEE) <= set(banx["trimestre"]), (
        "Faltan en Banxico trimestres del periodo de IEEE"
    )

    tabla_t = pd.concat(
        [
            ieee,
            banx[banx["trimestre"].isin(TRIMESTRES_IEEE + [REFERENCIA_ACTUAL])],
            _agregado(
                ieee.assign(monto_mdp=np.nan),
                "IEEE-CIS",
                TRIMESTRES_IEEE,
                "periodo IEEE (dic 2017 a jun 2018)",
            ),
            _agregado(
                banx,
                "Banxico CF621",
                TRIMESTRES_IEEE,
                "periodo IEEE (oct 2017 a jun 2018)",
            ),
        ],
        ignore_index=True,
    ).drop(columns=["monto_mdp"], errors="ignore")
    guardar_tabla(tabla_t, cfg, "brecha_mexico_tasas", log)

    raz = _razones(tabla_t)
    guardar_tabla(raz, cfg, "brecha_mexico_razones", log)
    figura(tabla_t, raz, cfg, log)

    p = tabla_t[
        (tabla_t["trimestre"].str.startswith("periodo")) & (tabla_t["tipo"] == "total")
    ].set_index("fuente")
    log.info(
        "  Prevalencia, periodo de IEEE: IEEE %.2f %% (núm.) / %.2f %% (monto); Banxico %.2f %% / %.2f %%",
        p.loc["IEEE-CIS", "pct_num"],
        p.loc["IEEE-CIS", "pct_monto"],
        p.loc["Banxico CF621", "pct_num"],
        p.loc["Banxico CF621", "pct_monto"],
    )
    log.info(
        "  Veces IEEE sobre Banxico: %.1f (número), %.1f (monto)",
        p.loc["IEEE-CIS", "pct_num"] / p.loc["Banxico CF621", "pct_num"],
        p.loc["IEEE-CIS", "pct_monto"] / p.loc["Banxico CF621", "pct_monto"],
    )
    for _, r in raz[raz["trimestre"].str.startswith("periodo")].iterrows():
        log.info(
            "  %-14s crédito/débito: tasa núm. %.2f, tasa monto %.2f, ticket %.2f; débito %.1f %%",
            r["fuente"],
            r["razon_tasa_num_credito_debito"],
            r["razon_tasa_monto_credito_debito"],
            r["razon_ticket_credito_debito"],
            100 * r["prop_debito"],
        )
    act = tabla_t[
        (tabla_t["trimestre"] == REFERENCIA_ACTUAL) & (tabla_t["tipo"] == "total")
    ].iloc[0]
    log.info(
        "  Banxico ene-mar 2026: contracargos %.2f %% / %.2f %%; compra promedio %.0f MXN",
        act["pct_num"],
        act["pct_monto"],
        act["ticket_promedio"],
    )
