"""Paso «ingesta»: de lumen_staging a la capa de preparación (lumen_prep).

Une y tipa los datos para poder leerlos; no limpia ni imputa nada. Cada
subpaso registra filas de entrada y de salida y termina con validaciones
automáticas (asserts). Staging solo se lee.
"""

from .bq import ejecutar, leer_sql
from .config import tabla


def _uno(client, sql: str, log) -> dict:
    """Ejecuta una consulta que devuelve una sola fila y la regresa como diccionario."""
    return dict(next(iter(ejecutar(client, sql, log))).items())


def ingesta_analitico(client, cfg: dict, log) -> None:
    """Fuente A: transacciones + identidad al grano de E1 (sql/01_ingesta_analitico.sql)."""
    origen_t = tabla(cfg, "staging", cfg["staging"]["ieee_transaccion"])
    origen_i = tabla(cfg, "staging", cfg["staging"]["ieee_identidad"])
    destino = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])

    filas_t = client.get_table(origen_t).num_rows
    filas_i = client.get_table(origen_i).num_rows
    log.info(
        "  entrada: %s transacciones, %s registros de identidad",
        f"{filas_t:,}",
        f"{filas_i:,}",
    )

    ejecutar(client, leer_sql("01_ingesta_analitico.sql", cfg), log)

    t = client.get_table(destino)
    log.info(
        "  salida: %s (%s filas, %d columnas)",
        destino,
        f"{t.num_rows:,}",
        len(t.schema),
    )

    v = _uno(
        client,
        f"""
        SELECT COUNT(*) AS filas,
               COUNT(DISTINCT TransactionID) AS ids,
               COUNTIF(tiene_identidad) AS con_identidad,
               MIN(dia_relativo) AS dia_min, MAX(dia_relativo) AS dia_max,
               MIN(fecha) AS fecha_min, MAX(fecha) AS fecha_max,
               COUNTIF(hora NOT BETWEEN 0 AND 23) AS horas_fuera
        FROM `{destino}`
        """,
        log,
    )
    log.info(
        "  verificación: %s filas, %s ids, %s con identidad, días %s a %s (%s a %s)",
        f"{v['filas']:,}",
        f"{v['ids']:,}",
        f"{v['con_identidad']:,}",
        v["dia_min"],
        v["dia_max"],
        v["fecha_min"],
        v["fecha_max"],
    )

    # Validaciones: la unión no pierde ni duplica transacciones
    columnas_esperadas = (
        len(client.get_table(origen_t).schema)
        + len(client.get_table(origen_i).schema)
        - 1
        + 4
    )
    assert v["filas"] == filas_t, (
        f"La unión cambió el número de filas: {v['filas']:,} != {filas_t:,}"
    )
    assert v["ids"] == v["filas"], "TransactionID no es único en el dataset analítico"
    assert v["con_identidad"] == filas_i, (
        f"Con identidad: {v['con_identidad']:,} != {filas_i:,}"
    )
    assert len(t.schema) == columnas_esperadas, (
        f"Columnas: {len(t.schema)} != {columnas_esperadas}"
    )
    assert v["horas_fuera"] == 0, "Hay horas fuera de 0 a 23"


def ingesta_banxico(client, cfg: dict, log) -> None:
    """Fuente B: CF621 con fecha explícita y series renombradas (sql/02_ingesta_banxico.sql)."""
    origen = tabla(cfg, "staging", cfg["staging"]["banxico"])
    destino = tabla(cfg, "prep", cfg["tablas_prep"]["banxico_trimestres"])

    filas_in = client.get_table(origen).num_rows
    vacias = _uno(
        client,
        f"SELECT COUNTIF(Fecha IS NULL OR TRIM(Fecha) = '') AS vacias FROM `{origen}`",
        log,
    )["vacias"]
    log.info(
        "  entrada: %s filas de %s (%s sin fecha)",
        filas_in,
        cfg["staging"]["banxico"],
        vacias,
    )
    ejecutar(client, leer_sql("02_ingesta_banxico.sql", cfg), log)

    v = _uno(
        client,
        f"""
        SELECT COUNT(*) AS filas,
               COUNT(DISTINCT fecha_inicio_trimestre) AS trimestres,
               MIN(fecha_inicio_trimestre) AS desde, MAX(fecha_inicio_trimestre) AS hasta,
               DATE_DIFF(MAX(fecha_inicio_trimestre), MIN(fecha_inicio_trimestre), QUARTER) + 1 AS esperados,
               COUNTIF(EXTRACT(DAY FROM fecha_inicio_trimestre) != 1
                       OR EXTRACT(MONTH FROM fecha_inicio_trimestre) NOT IN (1, 4, 7, 10)) AS fechas_raras
        FROM `{destino}`
        """,
        log,
    )
    log.info(
        "  salida: %s trimestres, de %s a %s; %s fila(s) vacía(s) excluida(s)",
        v["filas"],
        v["desde"],
        v["hasta"],
        filas_in - v["filas"],
    )
    assert v["trimestres"] == v["filas"], "Hay trimestres repetidos"
    assert v["filas"] == v["esperados"], (
        f"Faltan trimestres: {v['filas']} de {v['esperados']}"
    )
    assert v["fechas_raras"] == 0, (
        "Hay fechas que no son inicio de trimestre (¿día y mes invertidos?)"
    )
    assert filas_in - v["filas"] == vacias, (
        f"Se excluyeron {filas_in - v['filas']} filas, pero solo {vacias} no tienen fecha"
    )


def ingesta_dominios(client, cfg: dict, log) -> None:
    """Fuente D: un dominio por fila, desde las líneas crudas del JSON (sql/03_ingesta_dominios.sql)."""
    origen = tabla(cfg, "staging", cfg["staging"]["dominios"])
    destino = tabla(cfg, "prep", cfg["tablas_prep"]["dominios_lista"])

    lineas = _uno(
        client,
        f"""
        SELECT COUNT(*) AS lineas,
               COUNTIF(TRIM(linea) IN ('[', ']')) AS corchetes
        FROM `{origen}`
        """,
        log,
    )
    log.info(
        "  entrada: %s líneas crudas (%s de corchetes)",
        f"{lineas['lineas']:,}",
        lineas["corchetes"],
    )
    ejecutar(client, leer_sql("03_ingesta_dominios.sql", cfg), log)

    v = _uno(
        client,
        f"SELECT COUNT(*) AS filas, COUNT(DISTINCT dominio) AS distintos FROM `{destino}`",
        log,
    )
    excluidas = lineas["lineas"] - v["filas"]
    log.info(
        "  salida: %s dominios (%s distintos); %s líneas excluidas",
        f"{v['filas']:,}",
        f"{v['distintos']:,}",
        excluidas,
    )
    assert v["distintos"] == v["filas"], "Hay dominios repetidos"
    assert excluidas == lineas["corchetes"] == 2, (
        "Se excluyeron líneas que no son los dos corchetes del arreglo"
    )


def ingesta(client, cfg: dict, log) -> None:
    log.info("  -- A: dataset analítico")
    ingesta_analitico(client, cfg, log)
    log.info("  -- B: Banco de México")
    ingesta_banxico(client, cfg, log)
    log.info("  -- D: dominios de correo")
    ingesta_dominios(client, cfg, log)
