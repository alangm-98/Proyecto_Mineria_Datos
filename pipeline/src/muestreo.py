"""Paso «muestreo»: evalúa si hace falta muestrear y registra la decisión.

El PDF de E2 justifica el muestreo solo por tres razones. El paso mide cada
una sobre analitico_limpio con datos que no dependen de la máquina (metadatos
de BigQuery y conteos) y las compara con los umbrales de config.yaml:
  1. Volumen: tamaño de la tabla frente a `max_gb_tabla`.
  2. Clase desbalanceada: prevalencia de fraude. Se registra, pero no
     justifica muestrear en E2: balancear clases es una técnica del modelado y
     se haría solo dentro de la partición de entrenamiento, después de separar
     validación y prueba (hacerlo antes filtraría información).
  3. Redundancia entre registros: filas con posible duplicado frente a
     `max_pct_duplicados`.

El pipeline no implementa muestreo (`aplicar: false`): si el volumen o la
redundancia lo justificaran, el paso falla para que la decisión se revise.
Escribe lumen_prep.muestreo_decision y su copia CSV en salidas/.
"""

import pandas as pd

from .bq import ejecutar
from .calidad import _guardar
from .config import tabla


def muestreo(client, cfg: dict, log) -> None:
    m = cfg["muestreo"]
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])
    t = client.get_table(origen)
    gb = t.num_bytes / 1e9
    r = dict(
        next(
            iter(
                ejecutar(
                    client,
                    f"""
        SELECT AVG(isFraud) AS prevalencia, AVG(IF(posible_duplicado IS NULL, 0, 1)) AS duplicados
        FROM `{origen}`""",
                    log,
                )
            )
        ).items()
    )

    criterios = [
        (
            "Volumen",
            f"{t.num_rows:,} filas; {gb:.2f} GB",
            f"más de {m['max_gb_tabla']} GB",
            gb > m["max_gb_tabla"],
        ),
        (
            "Clase desbalanceada",
            f"{100 * r['prevalencia']:.2f} % de fraude",
            "se trata en el modelado, solo con entrenamiento",
            False,
        ),
        (
            "Redundancia entre registros",
            f"{100 * r['duplicados']:.2f} % de filas con posible duplicado",
            f"más de {100 * m['max_pct_duplicados']:.0f} %",
            r["duplicados"] > m["max_pct_duplicados"],
        ),
    ]
    d = pd.DataFrame(
        criterios, columns=["criterio", "medida", "umbral", "justifica_muestrear"]
    )
    decision = "muestrear" if d["justifica_muestrear"].any() else "no muestrear"
    d["decision"] = decision
    for c in d.itertuples():
        log.info(
            "  %-28s %-40s -> %s",
            c.criterio,
            c.medida,
            "sí" if c.justifica_muestrear else "no",
        )
    _guardar(client, cfg, d, "muestreo_decision", log)

    assert not m["aplicar"], (
        "muestreo.aplicar es true, pero el pipeline no implementa muestreo"
    )
    assert decision == "no muestrear", (
        "Un criterio justifica muestrear y el pipeline no lo implementa: revisar la decisión"
    )
    log.info("  decisión: no se muestrea; se conservan las %s filas", f"{t.num_rows:,}")
