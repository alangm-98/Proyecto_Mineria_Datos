"""Paso «calidad»: diagnóstico de la capa de preparación, sin corregir nada.

Mide lo que la limpieza tendrá que decidir (PDF de E2, «Calidad de los datos y
tratamiento del ruido»: primero se diagnostica, después se decide):

  1. Por columna del dataset analítico: faltantes (en total y entre las
     transacciones con identidad), ceros, valores distintos, mínimo y máximo.
     Los valores distintos son exactos en columnas de texto, lógicas y de
     fecha, donde el número de categorías decide el tratamiento, y
     aproximados (APPROX_COUNT_DISTINCT) en las numéricas: 400 conteos exactos
     en una sola consulta tardan más de 5 minutos.
  2. Duplicados: registros idénticos salvo el identificador, y salvo el
     identificador y el tiempo.
  3. Frecuencia de cada valor en las columnas de texto con pocas categorías.
  4. Llaves que no coinciden: dominios de correo de A que no están en la lista D.
  5. Consistencia interna de Banco de México.

Escribe cuatro tablas en lumen_prep y una copia CSV de cada una en
pipeline/salidas/. Son conteos agregados, nunca filas de datos.

Las consultas se generan por código a partir del esquema de la tabla, porque
son 438 columnas; el texto de cada consulta queda en el registro de la corrida.
"""

import re
import warnings

import pandas as pd
from google.cloud import bigquery

from .bq import ejecutar
from .config import RAIZ, tabla

DERIVADAS = ("tiene_identidad", "dia_relativo", "fecha", "hora")
NUMERICOS = ("INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC")


def grupo(columna: str) -> str:
    """Familia de la variable, según la nomenclatura de la fuente A."""
    if columna in DERIVADAS:
        return "derivada"
    reglas = [
        (
            r"^(TransactionID|TransactionDT|TransactionAmt|isFraud|ProductCD)$",
            "transaccion",
        ),
        (r"^card\d$", "card"),
        (r"^addr\d$", "addr"),
        (r"^dist\d$", "dist"),
        (r"^[PR]_emaildomain$", "correo"),
        (r"^C\d+$", "C"),
        (r"^D\d+$", "D"),
        (r"^M\d$", "M"),
        (r"^V\d+$", "V"),
        (r"^id_\d+$", "id"),
        (r"^Device(Type|Info)$", "dispositivo"),
    ]
    for patron, nombre in reglas:
        if re.match(patron, columna):
            return nombre
    return "otra"


def _df(client, sql: str, log) -> pd.DataFrame:
    log.info(
        "  SQL: %s", " ".join(sql.split())[:300] + (" ..." if len(sql) > 300 else "")
    )
    return ejecutar(client, sql, log).to_dataframe()


def _guardar(client, cfg: dict, df: pd.DataFrame, clave: str, log) -> None:
    """Escribe la tabla en lumen_prep (reemplazándola) y su copia CSV en salidas/."""
    destino = tabla(cfg, "prep", cfg["tablas_prep"][clave])
    with warnings.catch_warnings():
        # Aviso de versiones futuras de google-cloud-bigquery sobre pandas-gbq; las versiones
        # del proyecto están fijadas en uv.lock, así que no aplica.
        warnings.filterwarnings(
            "ignore", message=".*pandas-gbq.*", category=FutureWarning
        )
        trabajo = client.load_table_from_dataframe(
            df,
            destino,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        )
    trabajo.result()
    carpeta = RAIZ / cfg["salidas"]["carpeta"]
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{clave}.csv"
    df.to_csv(ruta, index=False, encoding="utf-8", lineterminator="\n")
    log.info("  -> %s (%s filas) y %s", destino, f"{len(df):,}", ruta.relative_to(RAIZ))


def perfil_columnas(client, cfg: dict, log) -> pd.DataFrame:
    """Faltantes, ceros, distintos y rango de cada columna del dataset analítico."""
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    esquema = client.get_table(origen).schema
    cols_t = {
        c.name
        for c in client.get_table(
            tabla(cfg, "staging", cfg["staging"]["ieee_transaccion"])
        ).schema
    }

    exprs = ["COUNT(*) AS filas", "COUNTIF(tiene_identidad) AS filas_con_identidad"]
    for k, c in enumerate(esquema):
        q = f"`{c.name}`"
        distintos = (
            f"APPROX_COUNT_DISTINCT({q})"
            if c.field_type in NUMERICOS
            else f"COUNT(DISTINCT {q})"
        )
        exprs += [
            f"COUNTIF({q} IS NULL) AS n{k}",
            f"COUNTIF({q} IS NULL AND tiene_identidad) AS ni{k}",
            f"{distintos} AS d{k}",
        ]
        if c.field_type in NUMERICOS:
            exprs += [
                f"COUNTIF({q} = 0) AS z{k}",
                f"MIN({q}) AS mn{k}",
                f"MAX({q}) AS mx{k}",
            ]
    fila = _df(client, f"SELECT {', '.join(exprs)} FROM `{origen}`", log).iloc[0]

    filas, con_id = int(fila["filas"]), int(fila["filas_con_identidad"])
    registros = []
    for k, c in enumerate(esquema):
        numerica = c.field_type in NUMERICOS
        origen_col = (
            "derivada"
            if c.name in DERIVADAS
            else ("transaccion" if c.name in cols_t else "identidad")
        )
        nulos = int(fila[f"n{k}"])
        registros.append(
            {
                "orden": k + 1,
                "columna": c.name,
                "tipo": c.field_type,
                "tabla_origen": origen_col,
                "grupo": grupo(c.name),
                "filas": filas,
                "nulos": nulos,
                "pct_nulos": round(100 * nulos / filas, 4),
                "nulos_con_identidad": int(fila[f"ni{k}"]),
                "pct_nulos_con_identidad": round(100 * int(fila[f"ni{k}"]) / con_id, 4),
                "ceros": int(fila[f"z{k}"]) if numerica else None,
                "distintos": int(fila[f"d{k}"]),
                "distintos_aproximado": numerica,
                "minimo": float(fila[f"mn{k}"])
                if numerica and pd.notna(fila[f"mn{k}"])
                else None,
                "maximo": float(fila[f"mx{k}"])
                if numerica and pd.notna(fila[f"mx{k}"])
                else None,
            }
        )
    df = pd.DataFrame(registros)
    df["ceros"] = df["ceros"].astype("Int64")

    assert len(df) == len(esquema), "No se diagnosticaron todas las columnas"
    sin_nulos = int((df["nulos"] == 0).sum())
    log.info(
        "  %d columnas: %d sin faltantes; %d con más del 50 %% de faltantes",
        len(df),
        sin_nulos,
        int((df["pct_nulos"] > 50).sum()),
    )
    return df


def duplicados(client, cfg: dict, log) -> list[dict]:
    """Registros idénticos salvo el identificador (y salvo identificador y tiempo)."""
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    nombres = [c.name for c in client.get_table(origen).schema]
    sin_id = [f"`{n}`" for n in nombres if n != "TransactionID"]
    sin_id_tiempo = [
        f"`{n}`"
        for n in nombres
        if n not in ("TransactionID", "TransactionDT") + DERIVADAS
    ]
    sql = f"""
        SELECT COUNT(*) AS filas,
               COUNT(DISTINCT TransactionID) AS ids,
               COUNT(DISTINCT FARM_FINGERPRINT(TO_JSON_STRING(STRUCT({", ".join(sin_id)})))) AS distintas_sin_id,
               COUNT(DISTINCT FARM_FINGERPRINT(TO_JSON_STRING(STRUCT({", ".join(sin_id_tiempo)})))) AS distintas_sin_id_ni_tiempo
        FROM `{origen}`
    """
    v = _df(client, sql, log).iloc[0]
    filas = int(v["filas"])
    res = [
        {
            "prueba": "duplicados_por_llave",
            "valor": filas - int(v["ids"]),
            "detalle": "Filas con TransactionID repetido",
        },
        {
            "prueba": "duplicados_exactos_sin_id",
            "valor": filas - int(v["distintas_sin_id"]),
            "detalle": "Filas idénticas a otra en todas las columnas salvo TransactionID",
        },
        {
            "prueba": "duplicados_sin_id_ni_tiempo",
            "valor": filas - int(v["distintas_sin_id_ni_tiempo"]),
            "detalle": "Filas idénticas a otra salvo TransactionID, TransactionDT y sus derivadas",
        },
    ]
    for r in res:
        log.info("  %s: %s", r["prueba"], f"{r['valor']:,}")
    return res


def valores(client, cfg: dict, perfil: pd.DataFrame, log) -> pd.DataFrame:
    """Frecuencia de cada valor en columnas de texto con pocas categorías."""
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    limite = cfg["umbrales"]["calidad_max_categorias"]
    cols = perfil[(perfil["tipo"] == "STRING") & (perfil["distintos"] <= limite)][
        "columna"
    ].tolist()
    partes = [
        f"SELECT '{c}' AS columna, `{c}` AS valor, COUNT(*) AS filas, SUM(isFraud) AS fraudes "
        f"FROM `{origen}` GROUP BY valor"
        for c in cols
    ]
    df = _df(client, " UNION ALL ".join(partes), log)
    df["valor"] = df["valor"].fillna("(nulo)")
    df = df.sort_values(
        ["columna", "filas", "valor"], ascending=[True, False, True]
    ).reset_index(drop=True)
    log.info(
        "  %d columnas de texto con a lo más %d categorías: %s",
        len(cols),
        limite,
        ", ".join(cols),
    )
    return df


def dominios(client, cfg: dict, log) -> tuple[pd.DataFrame, list[dict]]:
    """Dominios de correo de A (comprador y receptor) frente a la lista D."""
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    lista = tabla(cfg, "prep", cfg["tablas_prep"]["dominios_lista"])
    partes = [
        f"""SELECT '{c}' AS columna, `{c}` AS dominio, isFraud,
                   `{c}` IN (SELECT dominio FROM `{lista}`) AS en_lista
            FROM `{origen}` WHERE `{c}` IS NOT NULL"""
        for c in ("P_emaildomain", "R_emaildomain")
    ]
    sql = (
        "SELECT columna, dominio, COUNT(*) AS filas, SUM(isFraud) AS fraudes, LOGICAL_AND(en_lista) AS en_lista "
        f"FROM ({' UNION ALL '.join(partes)}) GROUP BY columna, dominio"
    )
    df = _df(client, sql, log)
    df = df.sort_values(
        ["columna", "filas", "dominio"], ascending=[True, False, True]
    ).reset_index(drop=True)

    res = []
    for c, g in df.groupby("columna"):
        fuera = g[~g["en_lista"]]
        res.append(
            {
                "prueba": f"{c}_dominios_sin_pareja",
                "valor": len(fuera),
                "detalle": f"Dominios distintos de {c} que no están en la lista D, de {len(g)}",
            }
        )
        res.append(
            {
                "prueba": f"{c}_filas_sin_pareja",
                "valor": int(fuera["filas"].sum()),
                "detalle": f"Filas con {c} no nulo cuyo dominio no está en la lista D, de {int(g['filas'].sum())}",
            }
        )
        log.info(
            "  %s: %d de %d dominios sin pareja en D (%s filas)",
            c,
            len(fuera),
            len(g),
            f"{int(fuera['filas'].sum()):,}",
        )
    return df, res


def banxico(client, cfg: dict, log) -> list[dict]:
    """Consistencia interna de CF621: totales = crédito + débito; porcentajes en [0, 100]; faltantes."""
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["banxico_trimestres"])
    nombres = [c.name for c in client.get_table(origen).schema]
    pct = [n for n in nombres if n.startswith("pct_")]
    fuera = " OR ".join(f"{n} NOT BETWEEN 0 AND 100" for n in pct)
    nulos = " + ".join(f"COUNTIF({n} IS NULL)" for n in nombres)
    sql = f"""
        SELECT COUNT(*) AS trimestres,
               COUNTIF(aut_num_total != aut_num_credito + aut_num_debito) AS dif_num,
               MAX(ABS(aut_num_total - aut_num_credito - aut_num_debito)) AS max_dif_num,
               COUNTIF(aut_mdp_total != aut_mdp_credito + aut_mdp_debito) AS dif_mdp,
               MAX(ABS(aut_mdp_total - aut_mdp_credito - aut_mdp_debito)) AS max_dif_mdp,
               COUNTIF({fuera}) AS pct_fuera,
               {nulos} AS celdas_nulas
        FROM `{origen}`
    """
    v = _df(client, sql, log).iloc[0]
    res = [
        {
            "prueba": "banxico_total_num_distinto_de_suma",
            "valor": int(v["dif_num"]),
            "detalle": f"Trimestres con autorizaciones totales distintas de crédito + débito (máxima diferencia: {int(v['max_dif_num'])})",
        },
        {
            "prueba": "banxico_total_mdp_distinto_de_suma",
            "valor": int(v["dif_mdp"]),
            "detalle": f"Trimestres con monto total distinto de crédito + débito (máxima diferencia: {int(v['max_dif_mdp'])} mdp)",
        },
        {
            "prueba": "banxico_porcentajes_fuera_de_rango",
            "valor": int(v["pct_fuera"]),
            "detalle": "Trimestres con algún porcentaje fuera de [0, 100]",
        },
        {
            "prueba": "banxico_celdas_nulas",
            "valor": int(v["celdas_nulas"]),
            "detalle": f"Celdas nulas en {int(v['trimestres'])} trimestres × {len(nombres)} columnas",
        },
    ]
    for r in res:
        log.info("  %s: %s", r["prueba"], r["valor"])
    return res


def calidad(client, cfg: dict, log) -> None:
    log.info("  -- 1. Perfil de columnas del dataset analítico")
    perfil = perfil_columnas(client, cfg, log)
    _guardar(client, cfg, perfil, "calidad_columnas", log)

    log.info("  -- 2. Duplicados")
    resumen = duplicados(client, cfg, log)

    log.info("  -- 3. Valores de columnas de texto con pocas categorías")
    _guardar(client, cfg, valores(client, cfg, perfil, log), "calidad_valores", log)

    log.info("  -- 4. Dominios de correo frente a la lista D")
    dom, res_dom = dominios(client, cfg, log)
    _guardar(client, cfg, dom, "calidad_dominios", log)
    resumen += res_dom

    log.info("  -- 5. Consistencia de Banco de México")
    resumen += banxico(client, cfg, log)

    _guardar(client, cfg, pd.DataFrame(resumen), "calidad_resumen", log)
