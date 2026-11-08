"""Paso «carga»: pobla el esquema estrella de E1 con los datos preparados.

  1. sql/06_ddl_dw.sql crea los datasets y las siete tablas si no existen, y se
     comprueba que el esquema de cada tabla sea el del DDL de E1.
  2. sql/07_carga_dimensiones.sql: dimensiones de tipo 1 (se vacían y se llenan).
  3. sql/08_scd2_dominio.sql: dim_dominio_correo con historia (SCD tipo 2).
  4. sql/09_carga_hechos.sql: los dos hechos (se vacían y se llenan).
  5. Validaciones: filas por tabla, grano único, llaves únicas en las
     dimensiones, ninguna llave huérfana, totales iguales a analitico_limpio y
     transacciones por miembro iguales a las publicadas en E1.

Las validaciones se guardan en lumen_prep.carga_validaciones y en
salidas/carga_validaciones.csv; si alguna falla, el paso termina con error.
"""

import math
import re

import pandas as pd

from .bq import ejecutar, leer_sql
from .calidad import _guardar
from .config import RAIZ, tabla

TIPOS_BQ = {
    "INT64": "INTEGER",
    "FLOAT64": "FLOAT",
    "BOOL": "BOOLEAN",
    "STRING": "STRING",
    "DATE": "DATE",
    "NUMERIC": "NUMERIC",
}
LLAVES = {  # llave foránea del hecho -> dimensión
    "fecha_key": "dim_fecha",
    "tipo_tarjeta_key": "dim_tipo_tarjeta",
    "producto_key": "dim_producto",
    "dispositivo_key": "dim_dispositivo",
    "dominio_correo_key": "dim_dominio_correo",
}


def _uno(client, sql: str, log) -> dict:
    return dict(next(iter(ejecutar(client, sql, log))).items())


def esquema_ddl() -> dict[str, list[tuple[str, str]]]:
    """Columnas y tipos de cada tabla según sql/06_ddl_dw.sql."""
    texto = (RAIZ.parent / "sql" / "06_ddl_dw.sql").read_text(encoding="utf-8")
    tablas = {}
    for nombre, cuerpo in re.findall(
        r"CREATE TABLE IF NOT EXISTS `[^`]+\.(\w+)` \((.*?)\n\)\nOPTIONS", texto, re.S
    ):
        tablas[nombre] = [
            (c, TIPOS_BQ[t])
            for c, t in re.findall(
                r"^\s+(\w+)\s+(INT64|FLOAT64|BOOL|STRING|DATE|NUMERIC)\b", cuerpo, re.M
            )
        ]
    assert len(tablas) == 7, f"Se esperaban 7 tablas en el DDL y hay {len(tablas)}"
    return tablas


def parametros(cfg: dict) -> dict:
    return {
        "dw_fecha_inicio": cfg["dw"]["fecha_inicio"],
        "dw_fecha_fin": cfg["dw"]["fecha_fin"],
    }


def scd2_dominio(
    client, cfg: dict, dim: str, lista: str, fecha_lista: str, log
) -> None:
    """Actualiza la dimensión de dominio (SCD 2) con una versión de la lista."""
    ejecutar(
        client,
        leer_sql(
            "08_scd2_dominio.sql",
            cfg,
            {"dim": dim, "lista": lista, "fecha_lista": fecha_lista},
        ),
        log,
    )


def carga(client, cfg: dict, log) -> None:
    dw = lambda t: tabla(cfg, "dw", t)  # noqa: E731
    limpio = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])
    banxico = tabla(cfg, "prep", cfg["tablas_prep"]["banxico_trimestres"])
    lista = tabla(cfg, "prep", cfg["tablas_prep"]["dominios_lista"])

    # 1. Esquema
    ejecutar(client, leer_sql("06_ddl_dw.sql", cfg), log)
    for nombre, columnas in esquema_ddl().items():
        actual = [(f.name, f.field_type) for f in client.get_table(dw(nombre)).schema]
        assert actual == columnas, (
            f"El esquema de {nombre} no es el del DDL de E1:\n{actual}\n{columnas}"
        )
    log.info("  esquema de las 7 tablas idéntico al DDL de E1")

    # 2 a 4. Carga
    ejecutar(client, leer_sql("07_carga_dimensiones.sql", cfg, parametros(cfg)), log)
    antes = client.get_table(dw("dim_dominio_correo")).num_rows
    scd2_dominio(
        client,
        cfg,
        dw("dim_dominio_correo"),
        lista,
        cfg["fuentes"]["dominios_fecha_carga"],
        log,
    )
    despues = client.get_table(dw("dim_dominio_correo")).num_rows
    log.info(
        "  dim_dominio_correo: %d versiones nuevas (%d en total)",
        despues - antes,
        despues,
    )
    ejecutar(client, leer_sql("09_carga_hechos.sql", cfg), log)

    # 5. Validaciones
    v: list[dict] = []

    def comprobar(tabla_, validacion, esperado, obtenido, tol=0.0):
        ok = (
            math.isclose(float(obtenido), float(esperado), rel_tol=tol, abs_tol=tol)
            if tol
            else obtenido == esperado
        )
        v.append(
            {
                "tabla": tabla_,
                "validacion": validacion,
                "esperado": str(esperado),
                "obtenido": str(obtenido),
                "correcto": bool(ok),
            }
        )

    for nombre in esquema_ddl():
        log.info(
            "  %-24s %9s filas", nombre, f"{client.get_table(dw(nombre)).num_rows:,}"
        )

    # dim_fecha: días contiguos, llave única, ventana de IEEE-CIS completa
    f = _uno(
        client,
        f"""SELECT COUNT(*) AS filas, COUNT(DISTINCT fecha_key) AS llaves,
            DATE_DIFF(MAX(fecha), MIN(fecha), DAY) + 1 AS dias, MIN(fecha) AS desde, MAX(fecha) AS hasta,
            COUNTIF(dia_relativo_ieee IS NOT NULL) AS dias_ieee,
            COUNT(DISTINCT dia_relativo_ieee) AS dias_ieee_distintos
        FROM `{dw("dim_fecha")}`""",
        log,
    )
    comprobar(
        "dim_fecha", "días sin huecos (filas = días del rango)", f["dias"], f["filas"]
    )
    comprobar("dim_fecha", "llave única", f["filas"], f["llaves"])
    comprobar(
        "dim_fecha",
        "rango",
        f"{cfg['dw']['fecha_inicio']} a {cfg['dw']['fecha_fin']}",
        f"{str(f['desde'])[:10]} a {str(f['hasta'])[:10]}",
    )
    dias = _uno(
        client,
        f"SELECT MAX(dia_relativo) - MIN(dia_relativo) + 1 AS n FROM `{limpio}`",
        log,
    )["n"]
    comprobar(
        "dim_fecha",
        "días de IEEE-CIS con fecha asignada",
        dias,
        f["dias_ieee_distintos"],
    )

    # Dimensiones: llave única y miembro 0
    for nombre, llave in (
        ("dim_tipo_tarjeta", "tipo_tarjeta_key"),
        ("dim_producto", "producto_key"),
        ("dim_dispositivo", "dispositivo_key"),
        ("dim_dominio_correo", "dominio_correo_key"),
    ):
        d = _uno(
            client,
            f"""SELECT COUNT(*) AS filas, COUNT(DISTINCT {llave}) AS llaves,
                COUNTIF({llave} = 0) AS cero FROM `{dw(nombre)}`""",
            log,
        )
        comprobar(nombre, "llave única", d["filas"], d["llaves"])
        comprobar(nombre, "miembro 0 presente", 1, d["cero"])
    dom = _uno(
        client,
        f"""SELECT COUNT(DISTINCT dominio) AS dominios, COUNTIF(es_actual) AS vigentes,
            COUNTIF(es_actual AND dominio IS NOT NULL) AS vigentes_con_dominio,
            COUNTIF(NOT es_actual AND valido_hasta >= valido_desde) AS cerradas_bien,
            COUNTIF(NOT es_actual) AS cerradas
        FROM `{dw("dim_dominio_correo")}`""",
        log,
    )
    comprobar(
        "dim_dominio_correo",
        "una versión vigente por dominio",
        dom["dominios"],
        dom["vigentes_con_dominio"],
    )
    comprobar(
        "dim_dominio_correo",
        "versiones cerradas con fechas coherentes",
        dom["cerradas"],
        dom["cerradas_bien"],
    )
    clas = _uno(
        client,
        f"""SELECT COUNTIF(d.es_gratuito IS DISTINCT FROM (l.dominio IS NOT NULL)) AS distintos
        FROM `{dw("dim_dominio_correo")}` AS d
        LEFT JOIN (SELECT DISTINCT dominio FROM `{lista}`) AS l USING (dominio)
        WHERE d.es_actual AND d.dominio IS NOT NULL""",
        log,
    )["distintos"]
    comprobar(
        "dim_dominio_correo",
        "versión vigente clasificada con la lista actual "
        "(si falla: la lista cambió sin cambiar fuentes.dominios_fecha_carga)",
        0,
        clas,
    )

    # hechos_transaccion: grano, totales y llaves huérfanas
    h = _uno(
        client,
        f"""SELECT COUNT(*) AS filas, COUNT(DISTINCT transaccion_id) AS ids,
            SUM(es_fraude) AS fraudes, CAST(SUM(monto_usd) AS FLOAT64) AS monto,
            CAST(SUM(monto_fraude_usd) AS FLOAT64) AS monto_fraude,
            COUNTIF(monto_fraude_usd != monto_usd * es_fraude) AS mal_derivada
        FROM `{dw("hechos_transaccion")}`""",
        log,
    )
    a = _uno(
        client,
        f"""SELECT COUNT(*) AS filas, SUM(isFraud) AS fraudes, SUM(TransactionAmt) AS monto,
            SUM(TransactionAmt * isFraud) AS monto_fraude FROM `{limpio}`""",
        log,
    )
    comprobar("hechos_transaccion", "filas = analitico_limpio", a["filas"], h["filas"])
    comprobar(
        "hechos_transaccion",
        "grano único (una fila por transaccion_id)",
        h["filas"],
        h["ids"],
    )
    comprobar(
        "hechos_transaccion", "fraudes = analitico_limpio", a["fraudes"], h["fraudes"]
    )
    comprobar(
        "hechos_transaccion",
        "monto (USD) = analitico_limpio",
        round(a["monto"], 2),
        round(h["monto"], 2),
        tol=1e-9,
    )
    comprobar(
        "hechos_transaccion",
        "monto defraudado (USD) = analitico_limpio",
        round(a["monto_fraude"], 2),
        round(h["monto_fraude"], 2),
        tol=1e-9,
    )
    comprobar(
        "hechos_transaccion",
        "monto_fraude_usd = monto_usd × es_fraude",
        0,
        h["mal_derivada"],
    )
    for llave, dim in LLAVES.items():
        n = _uno(
            client,
            f"""SELECT COUNTIF(d.{llave} IS NULL) AS n FROM `{dw("hechos_transaccion")}` AS h
                LEFT JOIN `{dw(dim)}` AS d USING ({llave})""",
            log,
        )["n"]
        comprobar("hechos_transaccion", f"sin llaves huérfanas en {llave}", 0, n)
    for llave, esperado in (
        ("tipo_tarjeta_key", cfg["dw"]["esperado_tipo_tarjeta"]),
        ("dispositivo_key", cfg["dw"]["esperado_dispositivo"]),
    ):
        obtenido = {
            int(r[llave]): int(r["n"])
            for r in ejecutar(
                client,
                f"SELECT {llave}, COUNT(*) AS n FROM `{dw('hechos_transaccion')}` GROUP BY {llave}",
                log,
            )
        }
        comprobar(
            "hechos_transaccion",
            f"transacciones por {llave} = E1 (estrella.qmd)",
            dict(sorted(esperado.items())),
            dict(sorted(obtenido.items())),
        )

    # hechos_pagos_trimestre: grano, totales y llaves
    p = _uno(
        client,
        f"""SELECT COUNT(*) AS filas, COUNT(DISTINCT CONCAT(CAST(fecha_key AS STRING), '-', CAST(tipo_tarjeta_key AS STRING))) AS granos,
            SUM(num_autorizaciones) AS num, SUM(monto_autorizado_mdp) AS mdp,
            COUNTIF(pct_contracargo_num NOT BETWEEN 0 AND 100 OR pct_aceptacion_num NOT BETWEEN 0 AND 100) AS fuera_rango
        FROM `{dw("hechos_pagos_trimestre")}`""",
        log,
    )
    b = _uno(
        client,
        f"""SELECT COUNT(*) AS trimestres, SUM(aut_num_credito + aut_num_debito) AS num,
            SUM(aut_mdp_credito + aut_mdp_debito) AS mdp FROM `{banxico}`""",
        log,
    )
    comprobar(
        "hechos_pagos_trimestre",
        "filas = trimestres × 2 (crédito y débito)",
        2 * b["trimestres"],
        p["filas"],
    )
    comprobar(
        "hechos_pagos_trimestre",
        "grano único (trimestre y tipo de tarjeta)",
        p["filas"],
        p["granos"],
    )
    comprobar(
        "hechos_pagos_trimestre",
        "autorizaciones = banxico_trimestres",
        b["num"],
        p["num"],
    )
    comprobar(
        "hechos_pagos_trimestre",
        "monto autorizado (mdp) = banxico_trimestres",
        b["mdp"],
        p["mdp"],
    )
    comprobar(
        "hechos_pagos_trimestre", "porcentajes entre 0 y 100", 0, p["fuera_rango"]
    )
    for llave in ("fecha_key", "tipo_tarjeta_key"):
        n = _uno(
            client,
            f"""SELECT COUNTIF(d.{llave} IS NULL) AS n FROM `{dw("hechos_pagos_trimestre")}` AS h
                LEFT JOIN `{dw(LLAVES[llave])}` AS d USING ({llave})""",
            log,
        )["n"]
        comprobar("hechos_pagos_trimestre", f"sin llaves huérfanas en {llave}", 0, n)

    t = pd.DataFrame(v)
    t.insert(0, "orden", range(1, len(t) + 1))
    _guardar(client, cfg, t, "carga_validaciones", log)
    malas = t[~t["correcto"]]
    assert malas.empty, "Validaciones de la carga que fallaron:\n" + malas.to_string(
        index=False
    )
    log.info("  %d validaciones correctas", len(t))
