"""Paso «datamart»: ejecuta las consultas del DataMart de E1 y guarda sus resultados.

sql/10_vistas_mart.sql crea las vistas de E1 si no existen (en el proyecto del
equipo ya existen y no se tocan). El paso consulta cada vista, guarda su
resultado en salidas/mart_<vista>.csv y cruza los totales con el DW y con el
EDA, para comprobar que el mart responde con los datos cargados:
  - p1_tasa_por_segmento: la fila de totales tiene todas las transacciones y fraudes.
  - p2_tramo_diario: la fila de totales reproduce el tramo del EDA
    (transacciones en el tramo y fracción del monto defraudado).
  - p2_referencia_mexico: el total de autorizaciones es el de Banxico.
  - p3_identidad: las tasas con y sin identidad son las del dataset limpio.
"""

import math

import pandas as pd

from .bq import ejecutar, leer_sql
from .config import RAIZ, tabla

VISTAS = {
    "p1_tasa_por_segmento": "producto, tipo_tarjeta, dispositivo, correo",
    "p2_tramo_diario": "fecha",
    "p2_referencia_mexico": "anio, tipo_tarjeta",
    "p3_identidad": "registro_identidad, dispositivo",
}


def _uno(client, sql: str, log) -> dict:
    return dict(next(iter(ejecutar(client, sql, log))).items())


def datamart(client, cfg: dict, log) -> None:
    ejecutar(client, leer_sql("10_vistas_mart.sql", cfg), log)
    carpeta = RAIZ / cfg["salidas"]["carpeta"]
    res: dict[str, pd.DataFrame] = {}
    for vista, orden in VISTAS.items():
        df = ejecutar(
            client, f"SELECT * FROM `{tabla(cfg, 'mart', vista)}` ORDER BY {orden}", log
        ).to_dataframe()
        df.to_csv(
            carpeta / f"mart_{vista}.csv",
            index=False,
            encoding="utf-8",
            lineterminator="\n",
            float_format="%.6g",
        )
        res[vista] = df
        log.info(
            "  %-22s %4d filas -> %s/mart_%s.csv",
            vista,
            len(df),
            cfg["salidas"]["carpeta"],
            vista,
        )

    hechos = tabla(cfg, "dw", "hechos_transaccion")
    h = _uno(
        client,
        f"SELECT COUNT(*) AS filas, SUM(es_fraude) AS fraudes FROM `{hechos}`",
        log,
    )

    p1 = res["p1_tasa_por_segmento"]
    total = p1[
        (p1[["producto", "tipo_tarjeta", "dispositivo", "correo"]] == "Todos").all(
            axis=1
        )
    ]
    assert len(total) == 1, "p1: falta la fila de totales del CUBE"
    assert (
        int(total["transacciones"].iloc[0]) == h["filas"]
        and int(total["fraudes"].iloc[0]) == h["fraudes"]
    ), "p1: los totales no coinciden con hechos_transaccion"

    p2 = res["p2_tramo_diario"]
    t = p2[p2["fecha"].isna()]
    assert len(t) == 1, "p2_tramo_diario: falta la fila de totales del ROLLUP"
    eda = (
        pd.read_csv(carpeta / "eda" / "tramo_resumen.csv")
        .set_index("grupo")
        .loc["todos los días"]
    )
    assert int(t["transacciones_en_tramo"].iloc[0]) == int(eda["k_total"]), (
        f"p2: {int(t['transacciones_en_tramo'].iloc[0])} transacciones en el tramo; el EDA tiene {int(eda['k_total'])}"
    )
    assert math.isclose(
        float(t["fraccion_monto_en_tramo"].iloc[0]),
        float(eda["monto_cubierto_regla"]),
        rel_tol=1e-5,
    ), "p2: la fracción del monto defraudado en el tramo no es la del EDA"
    log.info(
        "  p2_tramo_diario reproduce el EDA: %d transacciones en el tramo, %.2f %% del monto defraudado",
        int(eda["k_total"]),
        100 * float(eda["monto_cubierto_regla"]),
    )

    pm = res["p2_referencia_mexico"]
    tm = pm[(pm["anio"] == "Todos") & (pm["tipo_tarjeta"] == "Todos")]
    b = _uno(
        client,
        f"""SELECT SUM(aut_num_credito + aut_num_debito) AS num
        FROM `{tabla(cfg, "prep", cfg["tablas_prep"]["banxico_trimestres"])}`""",
        log,
    )
    assert len(tm) == 1 and int(tm["num_autorizaciones"].iloc[0]) == b["num"], (
        "p2_referencia_mexico: el total de autorizaciones no es el de Banxico"
    )

    p3 = res["p3_identidad"].set_index(["registro_identidad", "dispositivo"])
    a = {
        bool(r["tiene_identidad"]): float(r["tasa"])
        for r in ejecutar(
            client,
            f"""SELECT tiene_identidad, AVG(isFraud) AS tasa
            FROM `{tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])}` GROUP BY tiene_identidad""",
            log,
        )
    }
    for etiqueta, valor in (("Con identidad", True), ("Sin identidad", False)):
        assert math.isclose(
            float(p3.loc[(etiqueta, "Todos"), "tasa_fraude"]), a[valor], rel_tol=1e-9
        ), f"p3: la tasa {etiqueta.lower()} no coincide con analitico_limpio"
    log.info(
        "  p3_identidad: con identidad %.2f %%, sin identidad %.2f %%",
        100 * a[True],
        100 * a[False],
    )
    log.info("  las 4 consultas del DataMart responden con los datos cargados")
