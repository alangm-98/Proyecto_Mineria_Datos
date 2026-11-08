"""Concentración (Gini, curva de Lorenz, participación del top-k) y heterogeneidad (entropía).

Gini (PDF de E2):  G = sum_i sum_j |x_i - x_j| / (2 n^2 mean(x)).
Se calcula con la fórmula equivalente sobre los valores ordenados,
    G = (2 sum_i i x_(i)) / (n sum x) - (n + 1) / n,
que da el mismo número sin recorrer los n^2 pares; la equivalencia se comprueba
en cada corrida sobre una submuestra (assert).

Unidades y ceros (precaución 1 del PDF), declarados en la tabla de salida:
  G1  importe por transacción. Unidad: la transacción. No hay ceros (mínimo 0.251 USD).
  G2  fraudes por valor de card1. Unidad: cada valor de card1, un atributo enmascarado
      de la tarjeta (no una tarjeta individual). Se incluyen los valores con cero fraudes,
      porque excluirlos ocultaría cuánto se concentra el fraude. Se compara con la
      concentración de la actividad (transacciones por card1) para separar «hay mucho
      fraude ahí» de «hay mucha actividad ahí».
  Se usan conteos y montos, no tasas por valor de card1: con pocas transacciones la tasa
  es inestable (precaución 2).

Entropía normalizada: P_emaildomain se reporta con sus 60 categorías y agrupada (los
dominios con menos del umbral de participación pasan a «Otros»); la comparación entre
grupos se hace siempre con el mismo conjunto de categorías, porque la entropía crece con K.
"""

import numpy as np
import pandas as pd

from .comun import guardar_tabla
from .descriptiva import entropia


def gini(x) -> float:
    x = np.sort(np.asarray(x, dtype=float))
    n, total = len(x), x.sum()
    if n == 0 or total == 0:
        return np.nan
    i = np.arange(1, n + 1)
    return float(2 * (i * x).sum() / (n * total) - (n + 1) / n)


def gini_pares(x) -> float:
    """Fórmula del PDF (doble suma); solo para comprobar la equivalencia en muestras pequeñas."""
    x = np.asarray(x, dtype=float)
    return float(np.abs(x[:, None] - x[None, :]).sum() / (2 * len(x) ** 2 * x.mean()))


def lorenz(x, puntos: int = 201) -> pd.DataFrame:
    """Curva de Lorenz: proporción acumulada de unidades (de menor a mayor) contra proporción del total."""
    x = np.sort(np.asarray(x, dtype=float))
    acum = np.concatenate([[0.0], np.cumsum(x) / x.sum()])
    p = np.linspace(0, 1, len(acum))
    q = np.linspace(0, 1, puntos)
    return pd.DataFrame({"prop_unidades": q, "prop_total": np.interp(q, p, acum)})


def top_k(x, k: float) -> float:
    """Participación del k más alto (k en proporción, por ejemplo 0.10) en el total."""
    x = np.sort(np.asarray(x, dtype=float))[::-1]
    m = max(1, int(round(k * len(x))))
    return float(x[:m].sum() / x.sum())


def fila_gini(variable, unidad, grupo, valor, x, ceros_incluidos: bool) -> dict:
    x = np.asarray(x, dtype=float)
    return {
        "variable": variable,
        "unidad": unidad,
        "grupo": grupo,
        "valor": str(valor),
        "unidades": len(x),
        "unidades_en_cero": int((x == 0).sum()),
        "ceros_incluidos": ceros_incluidos,
        "total": float(x.sum()),
        "gini": gini(x),
        "top1_pct": top_k(x, 0.01),
        "top10_pct": top_k(x, 0.10),
    }


def concentracion(df: pd.DataFrame, cfg: dict, log) -> None:
    rng = np.random.default_rng(cfg["semilla"])
    sub = rng.choice(
        df["TransactionAmt"].to_numpy(), size=min(2000, len(df)), replace=False
    )
    assert abs(gini(sub) - gini_pares(sub)) < 1e-9, (
        "Las dos fórmulas de Gini no coinciden"
    )

    filas, curvas = [], []

    # G1: importe por transacción, global y por grupo
    log.info("  -- G1: importe por transacción")
    filas.append(
        fila_gini(
            "TransactionAmt",
            "transacción",
            "global",
            "todas",
            df["TransactionAmt"],
            True,
        )
    )
    curvas.append(lorenz(df["TransactionAmt"]).assign(curva="G1 importe: todas"))
    for g in ("clase", "periodo", "ProductCD"):
        for valor, s in df.groupby(g)["TransactionAmt"]:
            filas.append(fila_gini("TransactionAmt", "transacción", g, valor, s, True))
            if g == "clase":
                curvas.append(lorenz(s).assign(curva=f"G1 importe: {valor}"))

    # G2: fraudes y monto defraudado por valor de card1 (con ceros), frente a la actividad
    log.info("  -- G2: fraude por valor de card1")
    por_card = (
        df.assign(monto_fraude=df["TransactionAmt"] * df["isFraud"])
        .groupby("card1")
        .agg(
            transacciones=("isFraud", "size"),
            fraudes=("isFraud", "sum"),
            monto_fraude=("monto_fraude", "sum"),
        )
    )
    for var in ("transacciones", "fraudes", "monto_fraude"):
        filas.append(
            fila_gini(
                f"{var} por card1",
                "valor de card1",
                "global",
                "todos",
                por_card[var],
                True,
            )
        )
        curvas.append(lorenz(por_card[var]).assign(curva=f"G2 {var} por card1"))
    for per, d in df.groupby("periodo"):
        pc = d.groupby("card1")["isFraud"].agg(["size", "sum"])
        filas.append(
            fila_gini(
                "transacciones por card1",
                "valor de card1",
                "periodo",
                per,
                pc["size"],
                True,
            )
        )
        filas.append(
            fila_gini(
                "fraudes por card1", "valor de card1", "periodo", per, pc["sum"], True
            )
        )

    gin = pd.DataFrame(filas)
    guardar_tabla(gin, cfg, "concentracion_gini", log)
    guardar_tabla(pd.concat(curvas), cfg, "concentracion_lorenz", log)
    for _, r in gin[gin["grupo"].isin(["global", "clase"])].iterrows():
        log.info(
            "  %-28s %-9s G=%.3f top10%%=%.1f %% (unidades: %s; en cero: %s)",
            r["variable"],
            r["valor"],
            r["gini"],
            100 * r["top10_pct"],
            f"{r['unidades']:,}",
            f"{r['unidades_en_cero']:,}",
        )

    # Entropía normalizada por grupo, con el mismo conjunto de categorías en cada comparación
    log.info("  -- Entropía normalizada")
    umbral = cfg["eda"]["umbral_otros"]
    correo = (
        df["P_emaildomain"]
        .astype("object")
        .where(df["P_emaildomain"].notna(), "(nulo)")
    )
    part = correo.value_counts(normalize=True)
    frecuentes = set(part[part >= umbral].index)
    variables = {
        "ProductCD": df["ProductCD"].astype("object"),
        "card6": df["card6"].astype("object").where(df["card6"].notna(), "(nulo)"),
        "P_emaildomain (60 categorías)": correo,
        f"P_emaildomain (agrupada: < {umbral:.0%} -> Otros)": correo.where(
            correo.isin(frecuentes), "Otros"
        ),
    }
    ent = []
    for nombre, v in variables.items():
        cats = sorted(v.unique())
        for g, idx in [("global", {"todas": df.index})] + [
            (g, df.groupby(g).groups) for g in ("clase", "periodo")
        ]:
            for valor, ix in idx.items():
                conteos = v.loc[ix].value_counts().reindex(cats, fill_value=0)
                h, hn = entropia(conteos)
                ent.append(
                    {
                        "variable": nombre,
                        "grupo": g,
                        "valor": str(valor),
                        "categorias_posibles": len(cats),
                        "categorias_presentes": int((conteos > 0).sum()),
                        "entropia_bits": h,
                        "entropia_norm_sobre_K": h / np.log2(len(cats))
                        if len(cats) > 1
                        else 0.0,
                    }
                )
    ent = pd.DataFrame(ent)
    guardar_tabla(ent, cfg, "entropia", log)
    for _, r in ent[ent["grupo"].isin(["global", "clase"])].iterrows():
        log.info(
            "  %-42s %-9s K=%2d H_norm=%.3f",
            r["variable"],
            r["valor"],
            r["categorias_posibles"],
            r["entropia_norm_sobre_K"],
        )
