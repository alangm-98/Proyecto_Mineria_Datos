"""Estadística descriptiva en las cuatro dimensiones del PDF de E2.

Numéricas (localización y variabilidad):
  media, mediana, moda, media recortada, percentiles; rango, varianza, desviación
  estándar, IQR, MAD, coeficiente de variación; asimetría y curtosis.
Categóricas (heterogeneidad):
  número de categorías, frecuencias relativas, moda y su proporción, entropía de
  Shannon normalizada; además, tasa de fraude por categoría.

Definiciones (las mismas que se citan en eda.qmd):
  MAD = mediana(|x - mediana(x)|), sin factor de escala.
  CV = desviación estándar / media (sobre 1, no en porcentaje).
  Varianza y desviación estándar muestrales (n - 1).
  Asimetría: coeficiente de Fisher-Pearson ajustado (scipy, bias=False).
  Curtosis: exceso de curtosis (0 para la normal), ajustada (scipy, bias=False).
  Media recortada al 10 %: se quita el 10 % de las observaciones de cada extremo.
  Entropía: H = -sum p_k log2 p_k; H_norm = H / log2 K. Los faltantes cuentan como
  una categoría más («(nulo)») cuando existen, y así se declara.
"""

import numpy as np
import pandas as pd
from scipy import stats

from .comun import guardar_tabla


def resumen_numerico(x: pd.Series, cfg: dict) -> dict:
    x = x.dropna().astype(float)
    n = len(x)
    if n == 0:
        return {"n": 0}
    q1, med, q3 = np.percentile(x, [25, 50, 75])
    media, de = x.mean(), x.std(ddof=1)
    r = {
        "n": n,
        "media": media,
        "mediana": med,
        "moda": x.mode().iloc[0],
        "frec_moda": int((x == x.mode().iloc[0]).sum()),
        "media_recortada": stats.trim_mean(x, cfg["eda"]["recorte_media"]),
        "minimo": x.min(),
        "maximo": x.max(),
        "rango": x.max() - x.min(),
        "varianza": x.var(ddof=1),
        "desv_estandar": de,
        "iqr": q3 - q1,
        "mad": np.median(np.abs(x - med)),
        "cv": de / media if media != 0 else np.nan,
        "asimetria": stats.skew(x, bias=False),
        "curtosis_exceso": stats.kurtosis(x, fisher=True, bias=False),
        "media_sobre_mediana": media / med if med != 0 else np.nan,
        "de_sobre_iqr": de / (q3 - q1) if q3 > q1 else np.nan,
    }
    for p, v in zip(
        cfg["eda"]["percentiles"], np.percentile(x, cfg["eda"]["percentiles"])
    ):
        r[f"p{p}"] = v
    return r


def resumen_por_grupo(
    df: pd.DataFrame, variable: str, grupos: list[str], cfg: dict
) -> pd.DataFrame:
    """Una fila global y una por cada valor de cada variable de agrupación."""
    filas = [
        {
            "variable": variable,
            "grupo": "global",
            "valor": "todas",
            **resumen_numerico(df[variable], cfg),
        }
    ]
    for g in grupos:
        for valor, sub in df.groupby(g, dropna=False, sort=True):
            etiqueta = "(nulo)" if pd.isna(valor) else str(valor)
            filas.append(
                {
                    "variable": variable,
                    "grupo": g,
                    "valor": etiqueta,
                    **resumen_numerico(sub[variable], cfg),
                }
            )
    return pd.DataFrame(filas)


def entropia(conteos: pd.Series) -> tuple[float, float]:
    """Entropía de Shannon (bits) y normalizada, a partir de conteos por categoría."""
    p = conteos[conteos > 0] / conteos.sum()
    h = float(-(p * np.log2(p)).sum())
    k = len(p)
    return h, (h / np.log2(k) if k > 1 else 0.0)


def resumen_categorico(df: pd.DataFrame, variable: str) -> tuple[pd.DataFrame, dict]:
    """Frecuencias y tasa de fraude por categoría, y medidas de heterogeneidad de la variable."""
    v = df[variable].astype("object").where(df[variable].notna(), "(nulo)")
    t = (
        pd.DataFrame({"categoria": v, "isFraud": df["isFraud"]})
        .groupby("categoria")["isFraud"]
        .agg(filas="size", fraudes="sum")
        .reset_index()
        .sort_values(["filas", "categoria"], ascending=[False, True])
    )
    t.insert(0, "variable", variable)
    t["frec_relativa"] = t["filas"] / t["filas"].sum()
    t["tasa_fraude"] = t["fraudes"] / t["filas"]
    h, hn = entropia(t.set_index("categoria")["filas"])
    moda = t.iloc[0]
    res = {
        "variable": variable,
        "filas": int(t["filas"].sum()),
        "categorias": len(t),
        "incluye_nulo": bool((t["categoria"] == "(nulo)").any()),
        "moda": moda["categoria"],
        "prop_moda": moda["frec_relativa"],
        "entropia_bits": h,
        "entropia_norm": hn,
    }
    return t, res


def descriptiva(df: pd.DataFrame, cfg: dict, log) -> None:
    grupos = ["clase", "ProductCD", "card6", "periodo", "tiene_identidad"]

    log.info("  -- Importe (TransactionAmt, USD) por grupo")
    imp = resumen_por_grupo(df, "TransactionAmt", grupos, cfg)
    guardar_tabla(imp, cfg, "descriptiva_importe", log)
    g = imp[imp["grupo"].isin(["global", "clase"])].set_index("valor")
    for valor in g.index:
        r = g.loc[valor]
        log.info(
            "  %-9s n=%s media=%.2f mediana=%.2f DE=%.2f IQR=%.2f asimetría=%.2f",
            valor,
            f"{int(r['n']):,}",
            r["media"],
            r["mediana"],
            r["desv_estandar"],
            r["iqr"],
            r["asimetria"],
        )

    log.info("  -- Otras numéricas (hora, D1, C1) por clase")
    otras = pd.concat(
        [resumen_por_grupo(df, v, ["clase"], cfg) for v in ("hora", "D1", "C1")]
    )
    guardar_tabla(otras, cfg, "descriptiva_otras_numericas", log)

    log.info("  -- Categóricas")
    tablas, resumenes = [], []
    for v in (
        "ProductCD",
        "card4",
        "card6",
        "DeviceType",
        "P_emaildomain",
        "tiene_identidad",
    ):
        t, r = resumen_categorico(df, v)
        tablas.append(t)
        resumenes.append(r)
        log.info(
            "  %-15s K=%3d moda=%s (%.1f %%) H_norm=%.3f",
            v,
            r["categorias"],
            r["moda"],
            100 * r["prop_moda"],
            r["entropia_norm"],
        )
    guardar_tabla(pd.concat(tablas), cfg, "descriptiva_categoricas_frecuencias", log)
    guardar_tabla(pd.DataFrame(resumenes), cfg, "descriptiva_categoricas_resumen", log)

    log.info("  -- Serie diaria")
    diaria = (
        df.assign(monto_fraude=df["TransactionAmt"] * df["isFraud"])
        .groupby("dia_relativo")
        .agg(
            transacciones=("isFraud", "size"),
            fraudes=("isFraud", "sum"),
            monto_usd=("TransactionAmt", "sum"),
            monto_fraude_usd=("monto_fraude", "sum"),
        )
        .reset_index()
    )
    diaria["tasa_fraude"] = diaria["fraudes"] / diaria["transacciones"]
    diaria["periodo"] = (
        (diaria["dia_relativo"] - 1) // cfg["eda"]["periodo_dias"] + 1
    ).clip(upper=cfg["eda"]["periodos"])
    guardar_tabla(diaria, cfg, "serie_diaria", log)
    log.info(
        "  días: %d; transacciones por día de %s a %s",
        len(diaria),
        f"{diaria['transacciones'].min():,}",
        f"{diaria['transacciones'].max():,}",
    )

    assert int(diaria["transacciones"].sum()) == len(df), (
        "La serie diaria no suma todas las transacciones"
    )
    assert int(diaria["fraudes"].sum()) == int(df["isFraud"].sum()), (
        "La serie diaria no suma todos los fraudes"
    )
