"""Paso «antes_despues»: ¿la preparación conservó el fenómeno que se quiere estudiar?

Calcula las mismas medidas sobre analitico_crudo (antes de preparar) y sobre la
vista analitico_reducido (después de limpiar y reducir), con todas las filas.
Las medidas son las que sostienen los hallazgos del EDA: el importe y su
concentración (Gini), la tasa de fraude global, por partición y por categoría,
los dominios de correo y el tamaño del dataset.

Cada medida declara si se espera que cambie. La limpieza no elimina filas ni
modifica importes y la reducción solo quita columnas, así que todo debe quedar
igual salvo el correo (normalización de dominios) y el número de columnas y de
celdas nulas. Si una medida que debía quedar igual cambia, el paso falla.

Escribe lumen_prep.antes_despues, su copia CSV en salidas/ y las figuras f14 y f15.
"""

import math
import re

import pandas as pd

from .bq import ejecutar
from .calidad import _guardar
from .config import tabla
from .limpieza import _particion

FAMILIA = re.compile(r"(V|C|D|M|id|card|addr|dist)_?\d+$")
CATEGORIAS = {
    "ProductCD": "ProductCD",
    "card6": "card6",
    "tiene_identidad": "Registro de identidad",
}


def _uno(client, sql: str, log) -> dict:
    return dict(next(iter(ejecutar(client, sql, log))).items())


def _medidas(client, cfg: dict, origen: str, columnas: list[str], log) -> list[tuple]:
    """Lista de (grupo, medida, valor) para una tabla o vista."""
    part = _particion(cfg).replace("c.dia_relativo", "dia_relativo")
    dominio = cfg["limpieza"]["equivalencias_dominio"].get("gmail", "gmail.com")
    m: list[tuple] = []

    g = _uno(
        client,
        f"""
        WITH t AS (SELECT isFraud, TransactionAmt FROM `{origen}`),
        r AS (SELECT TransactionAmt AS x, ROW_NUMBER() OVER (ORDER BY TransactionAmt) AS i FROM t),
        rf AS (SELECT TransactionAmt AS x, ROW_NUMBER() OVER (ORDER BY TransactionAmt) AS i
               FROM t WHERE isFraud = 1)
        SELECT
          (SELECT COUNT(*) FROM t) AS filas,
          (SELECT SUM(isFraud) FROM t) AS fraudes,
          (SELECT SUM(TransactionAmt) FROM t) AS monto,
          (SELECT SUM(TransactionAmt * isFraud) FROM t) AS monto_fraude,
          (SELECT AVG(TransactionAmt) FROM t) AS media,
          (SELECT STDDEV_SAMP(TransactionAmt) FROM t) AS de,
          (SELECT ANY_VALUE(med) FROM (SELECT PERCENTILE_CONT(TransactionAmt, 0.5) OVER () AS med FROM t)) AS mediana,
          (SELECT 2 * SUM(i * x) / (COUNT(*) * SUM(x)) - (COUNT(*) + 1) / COUNT(*) FROM r) AS gini,
          (SELECT 2 * SUM(i * x) / (COUNT(*) * SUM(x)) - (COUNT(*) + 1) / COUNT(*) FROM rf) AS gini_fraude
        """,
        log,
    )
    m += [
        ("Variable objetivo", "Transacciones", g["filas"]),
        ("Variable objetivo", "Fraudes", g["fraudes"]),
        ("Variable objetivo", "Tasa de fraude (%)", 100 * g["fraudes"] / g["filas"]),
        ("Importe", "Monto total (USD)", g["monto"]),
        ("Importe", "Monto defraudado (USD)", g["monto_fraude"]),
        ("Importe", "Media (USD)", g["media"]),
        ("Importe", "Mediana (USD)", g["mediana"]),
        ("Importe", "Desviación estándar (USD)", g["de"]),
        ("Importe", "Gini, todas las transacciones", g["gini"]),
        ("Importe", "Gini, solo fraudes", g["gini_fraude"]),
    ]

    for r in ejecutar(
        client,
        # Alias distinto de «particion»: la vista después ya tiene una columna con ese nombre
        f"""SELECT {part} AS bloque, COUNT(*) AS filas, AVG(isFraud) AS tasa, MIN(dia_relativo) AS desde
            FROM `{origen}` GROUP BY bloque ORDER BY desde""",
        log,
    ):
        m += [
            ("Partición", f"Transacciones, {r['bloque']}", r["filas"]),
            ("Partición", f"Tasa de fraude (%), {r['bloque']}", 100 * r["tasa"]),
        ]

    for col, nombre in CATEGORIAS.items():
        for r in ejecutar(
            client,
            f"""SELECT CAST({col} AS STRING) AS valor, COUNT(*) AS filas, AVG(isFraud) AS tasa
                FROM `{origen}` GROUP BY valor ORDER BY valor""",
            log,
        ):
            valor = {"true": "con identidad", "false": "sin identidad"}.get(
                r["valor"], r["valor"] or "NULL"
            )
            m.append(
                (
                    "Tasa de fraude por categoría (%)",
                    f"{nombre} = {valor}",
                    100 * r["tasa"],
                )
            )

    c = _uno(
        client,
        f"""
        WITH f AS (SELECT P_emaildomain AS d, COUNT(*) AS n FROM `{origen}`
                   WHERE P_emaildomain IS NOT NULL GROUP BY d)
        SELECT
          (SELECT COUNT(*) FROM f) AS dominios,
          (SELECT -SUM(n / s * LOG(n / s, 2)) FROM f, (SELECT SUM(n) AS s FROM f)) AS entropia,
          (SELECT COUNTIF(P_emaildomain = '{dominio}') FROM `{origen}`) AS filas_dominio,
          (SELECT AVG(isFraud) FROM `{origen}` WHERE P_emaildomain = '{dominio}') AS tasa_dominio
        """,
        log,
    )
    m += [
        ("Correo del comprador", "Dominios distintos", c["dominios"]),
        ("Correo del comprador", "Entropía (bits)", c["entropia"]),
        ("Correo del comprador", f"Transacciones con {dominio}", c["filas_dominio"]),
        (
            "Correo del comprador",
            f"Tasa de fraude (%), {dominio}",
            100 * c["tasa_dominio"],
        ),
    ]

    familias = pd.Series(
        [m_.group(1) if (m_ := FAMILIA.match(x)) else "otras" for x in columnas]
    ).value_counts()
    m.append(("Dimensión", "Columnas", len(columnas)))
    m += [
        ("Dimensión", f"Columnas de la familia {f}", int(n))
        for f, n in familias.items()
    ]
    nulos = _uno(
        client,
        "SELECT "
        + " + ".join(f"COUNTIF(`{x}` IS NULL)" for x in columnas)
        + f" AS n FROM `{origen}`",
        log,
    )["n"]
    m.append(("Dimensión", "Celdas nulas", nulos))
    return m


def _cambia(grupo: str, medida: str) -> bool:
    """Medidas que la preparación modifica a propósito."""
    return grupo in ("Correo del comprador", "Dimensión")


def antes_despues(client, cfg: dict, log) -> None:
    crudo = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    reducido = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_reducido"])
    col_antes = [c.name for c in client.get_table(crudo).schema]
    col_despues = [c.name for c in client.get_table(reducido).schema]

    log.info("  -- antes: %s (%d columnas)", crudo, len(col_antes))
    antes = _medidas(client, cfg, crudo, col_antes, log)
    log.info("  -- después: %s (%d columnas)", reducido, len(col_despues))
    despues = _medidas(client, cfg, reducido, col_despues, log)

    a = pd.DataFrame(antes, columns=["grupo", "medida", "antes"])
    d = pd.DataFrame(despues, columns=["grupo", "medida", "despues"])
    t = a.merge(d, on=["grupo", "medida"], how="outer")
    # Orden de presentación: el de las medidas de antes; las que solo existen después, al final de su grupo
    orden = {
        k: i
        for i, k in enumerate(
            list(zip(a["grupo"], a["medida"])) + list(zip(d["grupo"], d["medida"]))
        )
    }
    t = t.iloc[
        sorted(
            range(len(t)), key=lambda i: orden[(t["grupo"].iat[i], t["medida"].iat[i])]
        )
    ].reset_index(drop=True)
    t[["antes", "despues"]] = t[["antes", "despues"]].astype(float).fillna(0.0)
    t["diferencia"] = t["despues"] - t["antes"]
    t["se_espera"] = [
        "cambia" if _cambia(g, x) else "igual" for g, x in zip(t["grupo"], t["medida"])
    ]

    distintas = t[
        (t["se_espera"] == "igual")
        & ~pd.Series(
            [
                math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9)
                for x, y in zip(t["antes"], t["despues"])
            ],
            index=t.index,
        )
    ]
    assert distintas.empty, (
        "Cambiaron medidas que debían quedar igual:\n" + distintas.to_string()
    )
    iguales = int((t["se_espera"] == "igual").sum())
    log.info("  %d medidas que debían quedar igual: idénticas", iguales)
    for r in t[(t["se_espera"] == "cambia") & (t["diferencia"] != 0)].itertuples():
        log.info(
            "  cambia: %-45s %14s -> %14s",
            r.medida,
            f"{r.antes:,.4g}",
            f"{r.despues:,.4g}",
        )

    t.insert(0, "orden", range(1, len(t) + 1))
    _guardar(client, cfg, t, "antes_despues", log)

    from .figuras_prep import figuras_antes_despues

    figuras_antes_despues(t, cfg, log)
