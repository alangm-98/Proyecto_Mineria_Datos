"""Paso «limpieza»: de analitico_crudo a analitico_limpio, con registro de limpieza.

Crea la tabla con sql/04_limpieza_analitico.sql y después mide, sobre las
dos tablas, cada tratamiento: qué problema, en qué variable, cuántas filas o celdas, cuántas
son fraude, qué se decidió y por qué (PDF de E2: «nada se elimina ni se imputa
en silencio»). El registro se escribe en lumen_prep.registro_limpieza y en
pipeline/salidas/registro_limpieza.csv; son conteos, nunca filas de datos.

Validaciones automáticas: mismas filas y llaves que la tabla cruda, llave
única, partición completa, faltantes iguales columna por columna (no hubo
imputación silenciosa) y marcas de atípicos coherentes con sus límites.
"""

import math
import re

import pandas as pd

from .bq import ejecutar, leer_sql
from .calidad import DERIVADAS, _guardar
from .config import RAIZ, tabla

AGREGADAS = ("particion", "log_importe", "posible_duplicado", "importe_atipico")


def _uno(client, sql: str, log) -> dict:
    return dict(next(iter(ejecutar(client, sql, log))).items())


def _q(nombre: str) -> str:
    return f"`{nombre}`"


def _literal(texto: str) -> str:
    """Cadena de SQL entre comillas simples (las equivalencias vienen de config.yaml)."""
    assert re.fullmatch(r"[A-Za-z0-9.\-]+", texto), f"Valor no permitido: {texto!r}"
    return f"'{texto}'"


def _particion(cfg: dict) -> str:
    """CASE de la partición temporal; valida que los bloques sean contiguos desde el día 1."""
    bloques = sorted(cfg["particion"].items(), key=lambda kv: kv[1][0])
    assert bloques[0][1][0] == 1, "La partición debe empezar en el día 1"
    for (_, (_, fin)), (nombre, (ini, _)) in zip(bloques, bloques[1:]):
        assert ini == fin + 1, (
            f"La partición tiene un hueco o se encima antes de {nombre}"
        )
    casos = "\n".join(
        f"      WHEN c.dia_relativo BETWEEN {ini} AND {fin} THEN '{nombre}'"
        for nombre, (ini, fin) in bloques
    )
    return f"CASE\n{casos}\n    END"


def fragmentos(cfg: dict, columnas: list[str]) -> dict:
    """Partes del SQL que dependen del esquema y de la configuración."""
    lim = cfg["limpieza"]
    for c in lim["columnas_tf"] + lim["columnas_correo"]:
        assert c in columnas, (
            f"La columna {c} de config.yaml no está en analitico_crudo"
        )

    reemplazos = []
    for c in lim["columnas_tf"]:
        reemplazos.append(
            f"      CASE c.{_q(c)} WHEN 'T' THEN TRUE WHEN 'F' THEN FALSE END AS {_q(c)}"
        )
    for c in lim["columnas_correo"]:
        norm = f"NULLIF(LOWER(TRIM(c.{_q(c)})), '')"
        casos = " ".join(
            f"WHEN {_literal(a)} THEN {_literal(b)}"
            for a, b in lim["equivalencias_dominio"].items()
        )
        reemplazos.append(f"      CASE {norm} {casos} ELSE {norm} END AS {_q(c)}")

    sin_id = [f"c.{_q(n)}" for n in columnas if n != "TransactionID"]
    sin_tiempo = [
        f"c.{_q(n)}"
        for n in columnas
        if n not in ("TransactionID", "TransactionDT") + DERIVADAS
    ]
    return {
        "reemplazos": ",\n".join(reemplazos),
        "expr_particion": _particion(cfg),
        "columnas_sin_id": ", ".join(sin_id),
        "columnas_sin_id_ni_tiempo": ", ".join(sin_tiempo),
        "iqr_k": str(float(lim["iqr_k"])),
    }


def _nulos_por_columna(client, origen: str, columnas: list[str], log) -> dict:
    exprs = ", ".join(
        f"COUNTIF({_q(c)} IS NULL) AS n{k}" for k, c in enumerate(columnas)
    )
    fila = _uno(client, f"SELECT {exprs} FROM `{origen}`", log)
    return {c: int(fila[f"n{k}"]) for k, c in enumerate(columnas)}


def limpieza(client, cfg: dict, log) -> None:
    crudo = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    limpio = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])
    lista = tabla(cfg, "prep", cfg["tablas_prep"]["dominios_lista"])
    ident = tabla(cfg, "staging", cfg["staging"]["ieee_identidad"])
    trans = tabla(cfg, "staging", cfg["staging"]["ieee_transaccion"])
    lim = cfg["limpieza"]

    esquema = client.get_table(crudo).schema
    columnas = [c.name for c in esquema]
    filas_in = client.get_table(crudo).num_rows
    log.info(
        "  entrada: %s (%s filas, %d columnas)", crudo, f"{filas_in:,}", len(columnas)
    )

    # Antes de convertir: las columnas T/F no traen otros valores
    otros = _uno(
        client,
        "SELECT "
        + ", ".join(
            f"COUNTIF({_q(c)} IS NOT NULL AND {_q(c)} NOT IN ('T', 'F')) AS o{k}"
            for k, c in enumerate(lim["columnas_tf"])
        )
        + f" FROM `{crudo}`",
        log,
    )
    assert sum(otros.values()) == 0, f"Hay valores distintos de T/F: {otros}"

    sql = leer_sql("04_limpieza_analitico.sql", cfg, fragmentos(cfg, columnas))
    generado = RAIZ / cfg["registro"]["carpeta"] / "04_limpieza_analitico_generado.sql"
    generado.write_text(sql, encoding="utf-8")
    log.info("  SQL generado (%s caracteres) en %s", f"{len(sql):,}", generado)
    ejecutar(client, sql, log)

    t = client.get_table(limpio)
    log.info(
        "  salida: %s (%s filas, %d columnas)", limpio, f"{t.num_rows:,}", len(t.schema)
    )

    # ---------------------------------------------------------------- validaciones
    v = _uno(
        client,
        f"""
        SELECT COUNT(*) AS filas, COUNT(DISTINCT TransactionID) AS ids,
               SUM(isFraud) AS fraudes, COUNTIF(tiene_identidad) AS con_identidad,
               COUNTIF(particion IS NULL) AS sin_particion,
               COUNTIF(log_importe IS NULL) AS sin_log
        FROM `{limpio}`
        """,
        log,
    )
    esperado = cfg["esperado"]
    assert v["filas"] == filas_in == esperado["ieee_transaccion_filas"], (
        f"La limpieza cambió el número de filas: {v['filas']:,} != {filas_in:,}"
    )
    assert v["ids"] == v["filas"], "TransactionID no es único en analitico_limpio"
    assert v["fraudes"] == esperado["ieee_fraudes"], f"Fraudes: {v['fraudes']:,}"
    assert v["con_identidad"] == esperado["ieee_identidad_filas"], (
        "Cambió tiene_identidad"
    )
    assert v["sin_particion"] == 0, f"{v['sin_particion']} filas sin partición"
    assert v["sin_log"] == 0, "Hay importes sin logaritmo (¿importe <= 0?)"
    assert len(t.schema) == len(columnas) + len(AGREGADAS), (
        f"Columnas: {len(t.schema)} != {len(columnas)} + {len(AGREGADAS)}"
    )

    # Ninguna imputación silenciosa: faltantes iguales columna por columna
    n_crudo = _nulos_por_columna(client, crudo, columnas, log)
    n_limpio = _nulos_por_columna(client, limpio, columnas, log)
    distintos = {
        c: (n_crudo[c], n_limpio[c]) for c in columnas if n_crudo[c] != n_limpio[c]
    }
    assert not distintos, f"Cambiaron los faltantes de: {distintos}"
    log.info("  faltantes idénticos a la tabla cruda en las %d columnas", len(columnas))

    # ---------------------------------------------------------------- registro
    reg: list[dict] = []

    def anotar(
        problema, variable, afectadas, unidad, decision, justificacion, fraudes=None
    ):
        reg.append(
            {
                "orden": len(reg) + 1,
                "problema": problema,
                "variable": variable,
                "afectadas": int(afectadas),
                "unidad": unidad,
                "fraudes": None if fraudes is None else int(fraudes),
                "decision": decision,
                "justificacion": justificacion,
            }
        )

    # Partición (no es un tratamiento, pero condiciona los que aprenden de los datos)
    part = ejecutar(
        client,
        f"""SELECT particion, COUNT(*) AS filas, SUM(isFraud) AS fraudes,
                   MIN(dia_relativo) AS desde, MAX(dia_relativo) AS hasta
            FROM `{limpio}` GROUP BY particion ORDER BY desde""",
        log,
    ).to_dataframe()
    for r in part.itertuples():
        anotar(
            "Partición temporal",
            f"particion = {r.particion}",
            r.filas,
            "filas",
            f"Días {r.desde} a {r.hasta}",
            "Bloques contiguos de días; los parámetros que se aprenden de los datos se ajustan solo con entrenamiento",
            r.fraudes,
        )

    # Faltantes
    cols_ident = [
        c.name for c in client.get_table(ident).schema if c.name != "TransactionID"
    ]
    sin_ident = filas_in - esperado["ieee_identidad_filas"]
    estructurales = _uno(
        client,
        "SELECT "
        + " + ".join(
            f"COUNTIF({_q(c)} IS NULL AND NOT tiene_identidad)" for c in cols_ident
        )
        + f" AS n FROM `{limpio}`",
        log,
    )["n"]
    assert estructurales == sin_ident * len(cols_ident), (
        "Hay valores de identidad en filas sin registro de identidad"
    )
    total_nulos = sum(n_limpio.values())
    anotar(
        "Faltantes estructurales",
        f"{len(cols_ident)} columnas de identidad",
        estructurales,
        "celdas",
        "Conservar NULL",
        f"Las {sin_ident:,} transacciones sin registro de identidad no pueden tener esos valores; "
        "la ausencia es informativa (H3: 7.85 % de fraude con identidad, 2.09 % sin ella)",
    )
    anotar(
        "Faltantes",
        "resto de las celdas nulas",
        total_nulos - estructurales,
        "celdas",
        "Conservar NULL; sin imputar en la tabla limpia",
        "Imputar con un valor global mezclaría días de prueba (fuga) y borraría patrones de ausencia "
        "por bloques; si un método lo necesita, se ajusta en «reduccion» con entrenamiento",
    )

    # Duplicados
    dup = _uno(
        client,
        f"""SELECT COUNTIF(posible_duplicado = 'exacto') AS exacto,
                   COUNTIF(posible_duplicado = 'exacto' AND isFraud = 1) AS exacto_f,
                   COUNTIF(posible_duplicado = 'sin_tiempo') AS sin_tiempo,
                   COUNTIF(posible_duplicado = 'sin_tiempo' AND isFraud = 1) AS sin_tiempo_f
            FROM `{limpio}`""",
        log,
    )
    anotar(
        "Duplicados por llave",
        "TransactionID",
        0,
        "filas",
        "Ninguna acción",
        "La llave es única (validación automática)",
    )
    anotar(
        "Posibles duplicados",
        "todas salvo TransactionID",
        dup["exacto"],
        "filas",
        "Conservar y marcar posible_duplicado = 'exacto'",
        "Cada fila tiene su propio TransactionID y el grano es la transacción; un cobro repetido puede "
        "ser legítimo o un intento de fraude. Se marcan todas las filas del grupo",
        dup["exacto_f"],
    )
    anotar(
        "Posibles duplicados",
        "todas salvo TransactionID y el tiempo",
        dup["sin_tiempo"],
        "filas",
        "Conservar y marcar posible_duplicado = 'sin_tiempo'",
        "Misma razón; además pueden ser compras iguales en momentos distintos",
        dup["sin_tiempo_f"],
    )

    # Atípicos del importe
    q = _uno(
        client,
        f"""SELECT ANY_VALUE(q1) AS q1, ANY_VALUE(q3) AS q3 FROM (
              SELECT PERCENTILE_CONT(log_importe, 0.25) OVER () AS q1,
                     PERCENTILE_CONT(log_importe, 0.75) OVER () AS q3
              FROM `{limpio}` WHERE particion = 'entrenamiento')""",
        log,
    )
    k = float(lim["iqr_k"])
    inf, sup = q["q1"] - k * (q["q3"] - q["q1"]), q["q3"] + k * (q["q3"] - q["q1"])
    at = _uno(
        client,
        f"""SELECT COUNTIF(importe_atipico = 'bajo') AS bajo,
                   COUNTIF(importe_atipico = 'bajo' AND isFraud = 1) AS bajo_f,
                   COUNTIF(importe_atipico = 'alto') AS alto,
                   COUNTIF(importe_atipico = 'alto' AND isFraud = 1) AS alto_f,
                   COUNTIF(log_importe < {inf!r}) AS bajo_chk,
                   COUNTIF(log_importe > {sup!r}) AS alto_chk,
                   SUM(IF(importe_atipico = 'alto', TransactionAmt * isFraud, 0)) / SUM(TransactionAmt * isFraud) AS monto_fraude_alto
            FROM `{limpio}`""",
        log,
    )
    assert (at["bajo"], at["alto"]) == (at["bajo_chk"], at["alto_chk"]), (
        "Las marcas de atípicos no coinciden con sus límites"
    )
    limites = f"{math.exp(inf):,.2f} y {math.exp(sup):,.2f} USD"
    log.info("  límites de atípicos (entrenamiento): %s", limites)
    for lado, n, f in (
        ("bajo", at["bajo"], at["bajo_f"]),
        ("alto", at["alto"], at["alto_f"]),
    ):
        anotar(
            f"Importe atípico {lado}",
            "TransactionAmt",
            n,
            "filas",
            f"Conservar sin acotar y marcar importe_atipico = '{lado}'",
            f"Regla del IQR (k = {k:g}) sobre ln(importe), cuartiles de entrenamiento: límites {limites}. "
            "El monto es medida aditiva de P2; acotarlo cambiaría el monto defraudado"
            + (
                f" (los altos son {100 * at['monto_fraude_alto']:.1f} % del monto defraudado)"
                if lado == "alto"
                else ""
            ),
            f,
        )
    anotar(
        "Transformación",
        "log_importe",
        filas_in,
        "filas",
        "Agregar ln(TransactionAmt)",
        "Escala más simétrica para la regla de atípicos y para «reduccion»; el DW usa el importe original",
    )

    # Negativos en las columnas D
    cols_d = [c for c in columnas if re.fullmatch(r"D\d+", c)]
    neg = _uno(
        client,
        "SELECT "
        + ", ".join(
            f"COUNTIF({_q(c)} < 0) AS n{i}, COUNTIF({_q(c)} < 0 AND isFraud = 1) AS f{i}"
            for i, c in enumerate(cols_d)
        )
        + f" FROM `{limpio}`",
        log,
    )
    for i, c in enumerate(cols_d):
        if neg[f"n{i}"] > 0:
            anotar(
                "Valores negativos",
                c,
                neg[f"n{i}"],
                "celdas",
                "Conservar",
                "La fuente describe las D como intervalos de tiempo y no declara error un negativo "
                "(supuesto: referencia distinta); sin fuente que lo justifique no se corrige",
                neg[f"f{i}"],
            )

    # Categorías: correo
    for c in lim["columnas_correo"]:
        corr = _uno(
            client,
            f"""SELECT
                  COUNTIF(l.{_q(c)} IS DISTINCT FROM r.{_q(c)}) AS cambiadas,
                  COUNTIF(l.{_q(c)} IS DISTINCT FROM r.{_q(c)} AND l.isFraud = 1) AS cambiadas_f,
                  COUNTIF(l.{_q(c)} = {_literal(lim["dominio_anonimizado"])}) AS anonimo,
                  COUNTIF(l.{_q(c)} = {_literal(lim["dominio_anonimizado"])} AND l.isFraud = 1) AS anonimo_f,
                  COUNTIF(l.{_q(c)} IS NOT NULL AND d.dominio IS NULL) AS fuera,
                  COUNTIF(l.{_q(c)} IS NOT NULL AND d.dominio IS NULL AND l.isFraud = 1) AS fuera_f
                FROM `{limpio}` AS l
                JOIN `{crudo}` AS r USING (TransactionID)
                LEFT JOIN `{lista}` AS d ON d.dominio = l.{_q(c)}""",
            log,
        )
        equiv = ", ".join(f"{a} → {b}" for a, b in lim["equivalencias_dominio"].items())
        anotar(
            "Categorías inconsistentes",
            c,
            corr["cambiadas"],
            "filas",
            f"Minúsculas, sin espacios y equivalencias ({equiv})",
            "Mismo proveedor escrito de dos formas; la tabla de equivalencias vive en config.yaml",
            corr["cambiadas_f"],
        )
        anotar(
            "Dominio anonimizado",
            c,
            corr["anonimo"],
            "filas",
            f"Conservar {lim['dominio_anonimizado']} como dominio propio",
            "Parece una etiqueta de anonimización de la fuente, no un proveedor; no está en la lista D "
            "y queda con es_gratuito = FALSE por la regla de la lista",
            corr["anonimo_f"],
        )
        anotar(
            "Llaves que no coinciden",
            f"{c} frente a la lista D",
            corr["fuera"],
            "filas",
            "Conservar; es_gratuito = FALSE",
            f"Tras normalizar, los dominios fuera de la lista son proveedores de internet o institucionales "
            f"(y {lim['dominio_anonimizado']}); no son correo gratuito",
            corr["fuera_f"],
        )

    # Categorías: T/F a BOOL
    tf = _uno(
        client,
        "SELECT "
        + " + ".join(f"COUNTIF({_q(c)} IS NOT NULL)" for c in lim["columnas_tf"])
        + f" AS n FROM `{limpio}`",
        log,
    )["n"]
    anotar(
        "Tipos",
        ", ".join(lim["columnas_tf"]),
        tf,
        "celdas",
        "Texto T/F a BOOL; el NULL se conserva",
        "Son indicadores lógicos; no hay otros valores (validación automática previa)",
    )

    # Llaves de la unión transacción-identidad
    huerf = _uno(
        client,
        f"""SELECT COUNTIF(t.TransactionID IS NULL) AS sin_transaccion, COUNT(*) AS identidad
            FROM `{ident}` AS i LEFT JOIN `{trans}` AS t USING (TransactionID)""",
        log,
    )
    assert huerf["sin_transaccion"] == 0, (
        f"{huerf['sin_transaccion']} identidades sin transacción"
    )
    anotar(
        "Llaves que no coinciden",
        "TransactionID de identidad",
        huerf["sin_transaccion"],
        "filas",
        "Ninguna acción",
        f"Los {huerf['identidad']:,} registros de identidad tienen su transacción; la unión no pierde filas",
    )

    df = pd.DataFrame(reg)
    df["fraudes"] = df["fraudes"].astype("Int64")
    _guardar(client, cfg, df, "registro_limpieza", log)
    log.info("  registro de limpieza: %d tratamientos", len(df))
