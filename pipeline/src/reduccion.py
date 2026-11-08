"""Paso «reduccion»: qué variables del dataset analítico se conservan y por qué.

Todo se calcula con la partición de entrenamiento de analitico_limpio, completa
(sin muestrear), para que ningún parámetro aprenda de los días de validación o
prueba. El resultado es una tabla de decisión con una fila por columna y la
vista analitico_reducido con las columnas conservadas. El DW no cambia: solo usa
columnas protegidas.

Orden de las reglas (umbrales en config.yaml, sección reduccion):
  0. Protegidas: llaves, variable objetivo, campos que usa el DW y columnas
     derivadas de la limpieza. Se conservan siempre.
  1. Faltantes: se descarta la columna si falta en más de `max_faltantes` de
     las filas donde aplica (las columnas de identidad solo aplican a las
     transacciones con registro de identidad).
  2. Casi constante: se descarta si un mismo valor, contando el NULL como
     valor, ocupa al menos `max_valor_dominante` de las filas.
  3. Relevancia: χ² de independencia y V de Cramér contra isFraud. Las
     numéricas con más de `grupos_numericas` valores distintos se agrupan en
     cuantiles; las categorías de menos de `umbral_otros` se juntan en «Otros»
     y el NULL es un grupo propio. Un grupo con frecuencia esperada menor que
     `min_esperada` en alguna celda se une a «Otros» (y, si aun así no
     alcanza, al grupo más grande), porque el χ² no es confiable con celdas
     esperadas pequeñas. Se descarta si p >= `alfa` / m (Bonferroni, m =
     número de pruebas) o si V < `min_v_cramer`: con cientos de miles de filas
     casi todo es significativo, así que en la práctica decide el tamaño del
     efecto.
  4. Redundancia: correlación de Spearman entre las numéricas que quedan,
     calculada en las filas donde ambas columnas existen. Se recorren las
     columnas de mayor a menor V (empates: menos faltantes, luego nombre) y se
     descarta una columna si tiene |ρ| >= `max_spearman` con otra ya
     conservada.
  5. PCA del bloque de columnas V conservadas (Vesta no publica qué mide cada
     una): mediana y estandarización de entrenamiento, varianza explicada y
     pesos. Es diagnóstico y representación disponible para el modelado; no
     cambia la tabla de decisión.
"""

import re
from itertools import combinations_with_replacement

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, rankdata

from .bq import ejecutar, leer_sql
from .calidad import _guardar
from .config import RAIZ, tabla


# ------------------------------------------------------------------ extracto
def _extracto(client, cfg: dict, log) -> pd.DataFrame:
    """Partición de entrenamiento de analitico_limpio, guardada en una caché local.

    El nombre del archivo lleva la fecha de modificación de la tabla: si la tabla
    cambia, se descarga de nuevo. La caché contiene datos reales de IEEE-CIS y
    vive en una carpeta que .gitignore excluye.
    """
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])
    modificada = client.get_table(origen).modified
    carpeta = RAIZ / cfg["reduccion"]["cache"]
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"entrenamiento_{modificada:%Y%m%d_%H%M%S}.parquet"
    if archivo.exists():
        log.info("  extracto local vigente: %s", archivo.name)
        return pd.read_parquet(archivo)
    for viejo in carpeta.glob("entrenamiento_*.parquet"):
        viejo.unlink()
    trabajo = client.query(
        f"SELECT * FROM `{origen}` WHERE particion = 'entrenamiento' ORDER BY TransactionID"
    )
    df = trabajo.result().to_dataframe()
    log.info(
        "  extracto: %s filas x %d columnas (%.1f MB procesados) -> %s",
        f"{len(df):,}",
        df.shape[1],
        (trabajo.total_bytes_processed or 0) / 1e6,
        archivo.name,
    )
    df.to_parquet(archivo, index=False)
    return df


# ------------------------------------------------------------------ medidas
def _grupos(s: pd.Series, r: dict) -> pd.Series:
    """Agrupa una columna para la tabla de contingencia: cuantiles u originales, «Otros» y NULL."""
    nulo = s.isna()
    k = r["grupos_numericas"]
    if (
        pd.api.types.is_numeric_dtype(s)
        and not pd.api.types.is_bool_dtype(s)
        and s.nunique() > k
    ):
        # Un valor muy frecuente (por ejemplo, el cero) colapsaría los cuantiles: va en su propio grupo
        x = s.astype(float)
        moda = x.mode().iloc[0]
        es_moda = x == moda
        g = pd.Series("NULL", index=s.index, dtype=object)
        if es_moda.mean() >= 1 / k:
            g[es_moda] = f"= {moda:g}"
            resto = ~es_moda & ~nulo
        else:
            resto = ~nulo
        g[resto] = pd.qcut(x[resto], k, duplicates="drop").astype(str)
    else:
        g = s.astype(str)
        frec = g[~nulo].value_counts(normalize=True)
        raras = frec.index[frec < r["umbral_otros"]]
        g = g.where(~g.isin(raras), "Otros")
    return g.where(~nulo, "NULL")


def _v_cramer(
    g: pd.Series, y: pd.Series, min_esperada: float
) -> tuple[float, float, int, float]:
    """χ² y V de Cramér; une los grupos cuya frecuencia esperada no alcanza el mínimo.

    Devuelve V, p, número de grupos y la menor frecuencia esperada de la tabla final.
    """
    prop = min(
        y.mean(), 1 - y.mean()
    )  # la clase minoritaria fija la menor celda esperada
    tamanos = g.value_counts()
    cortos = tamanos.index[tamanos * prop < min_esperada]
    if len(cortos):
        g = g.where(~g.isin(cortos), "Otros")
        tamanos = g.value_counts()
        if tamanos["Otros"] * prop < min_esperada:
            mayor = tamanos.drop("Otros").idxmax()
            g = g.where(g != "Otros", mayor)
    tab = pd.crosstab(g, y)
    if tab.shape[0] < 2:
        return 0.0, 1.0, tab.shape[0], float("nan")
    chi2, p, _, esperada = chi2_contingency(tab.to_numpy(), correction=False)
    n = tab.to_numpy().sum()
    v = float(np.sqrt(chi2 / (n * (min(tab.shape) - 1))))
    return v, float(p), tab.shape[0], float(esperada.min())


def _spearman(df: pd.DataFrame, cols: list[str], min_filas: int, umbral: float, log):
    """Spearman exacto en las filas donde ambas columnas existen.

    Agrupa las columnas por patrón de faltantes: dentro de un par de patrones,
    las filas comunes son las mismas para todas sus columnas, así que basta un
    cálculo de rangos y una matriz de correlación por par de patrones.
    Devuelve los pares con |ρ| >= umbral y, por columna, la |ρ| máxima y con quién.
    """
    presente = df[cols].notna().to_numpy()
    patrones: dict[bytes, list[int]] = {}
    for j in range(len(cols)):
        patrones.setdefault(np.packbits(presente[:, j]).tobytes(), []).append(j)
    claves = list(patrones)
    log.info(
        "  Spearman: %d columnas numéricas en %d patrones de faltantes",
        len(cols),
        len(claves),
    )
    maximo = {c: (0.0, None) for c in cols}
    pares = []
    for a, b in combinations_with_replacement(range(len(claves)), 2):
        ja, jb = patrones[claves[a]], patrones[claves[b]]
        filas = presente[:, ja[0]] & presente[:, jb[0]]
        if filas.sum() < min_filas:
            continue
        idx = sorted(set(ja) | set(jb))
        x = df[[cols[j] for j in idx]].to_numpy(dtype=float)[filas]
        rangos = rankdata(x, axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            rho = np.corrcoef(rangos, rowvar=False)
        rho = np.atleast_2d(rho)
        pos = {j: k for k, j in enumerate(idx)}
        for i in ja:
            for j in jb:
                if i >= j and a == b:
                    continue
                r = rho[pos[i], pos[j]]
                if not np.isfinite(r):
                    continue
                ci, cj = cols[i], cols[j]
                for c, otra in ((ci, cj), (cj, ci)):
                    if abs(r) > abs(maximo[c][0]):
                        maximo[c] = (float(r), otra)
                if abs(r) >= umbral:
                    pares.append(
                        {
                            "columna_a": ci,
                            "columna_b": cj,
                            "rho": float(r),
                            "filas_comunes": int(filas.sum()),
                        }
                    )
    return pd.DataFrame(
        pares, columns=["columna_a", "columna_b", "rho", "filas_comunes"]
    ), maximo


# ------------------------------------------------------------------ paso
def reduccion(client, cfg: dict, log) -> None:
    r = cfg["reduccion"]
    df = _extracto(client, cfg, log)
    n = len(df)
    esperado = int(
        next(
            iter(
                ejecutar(
                    client,
                    f"""SELECT COUNT(*) AS n FROM `{tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])}`
                                      WHERE particion = 'entrenamiento'""",
                    log,
                )
            )
        )["n"]
    )
    assert n == esperado, f"El extracto tiene {n:,} filas y entrenamiento {esperado:,}"
    y = df["isFraud"]

    esquema = {
        c.name: c.field_type
        for c in client.get_table(
            tabla(cfg, "prep", cfg["tablas_prep"]["analitico_limpio"])
        ).schema
    }
    identidad = {
        c.name
        for c in client.get_table(
            tabla(cfg, "staging", cfg["staging"]["ieee_identidad"])
        ).schema
    } - {"TransactionID"}
    protegidas = set(r["protegidas"])
    faltan = protegidas - set(esquema)
    assert not faltan, f"Columnas protegidas que no existen: {faltan}"
    con_ident = df["tiene_identidad"].to_numpy(dtype=bool)

    filas = []
    for c, tipo in esquema.items():
        s = df[c]
        aplica = con_ident if c in identidad else np.ones(n, dtype=bool)
        falt = float(s[aplica].isna().mean())
        dominante = float(s.value_counts(dropna=False, normalize=True).iloc[0])
        fila = {
            "variable": c,
            "familia": m.group(1)
            if (m := re.match(r"(V|C|D|M|id|card|addr|dist)_?\d+$", c))
            else c,
            "tipo": tipo,
            "aplica_a": "con identidad" if c in identidad else "todas",
            "pct_faltantes": falt,
            "pct_valor_dominante": dominante,
        }
        if c in protegidas:
            fila.update(
                decision="conservar",
                regla="protegida",
                detalle="Llave, variable objetivo, campo del DW o columna de la limpieza",
            )
        elif falt > r["max_faltantes"]:
            fila.update(
                decision="descartar",
                regla="faltantes",
                detalle=f"Falta en {100 * falt:.1f} % de las filas donde aplica",
            )
        elif dominante >= r["max_valor_dominante"]:
            fila.update(
                decision="descartar",
                regla="casi constante",
                detalle=f"Un valor ocupa {100 * dominante:.2f} % de las filas",
            )
        if c not in ("isFraud",) and tipo != "DATE":
            v, p, k, esp = _v_cramer(_grupos(s, r), y, r["min_esperada"])
            fila.update(v_cramer=v, p_valor=p, grupos_chi2=k, min_esperada=esp)
        filas.append(fila)
    dec = pd.DataFrame(filas).set_index("variable")

    # Relevancia: Bonferroni sobre todas las pruebas χ² y tamaño del efecto
    m = int(dec["p_valor"].notna().sum())
    p_umbral = r["alfa"] / m
    assert (dec["min_esperada"].dropna() >= r["min_esperada"]).all(), (
        "Hay celdas esperadas menores al mínimo"
    )
    log.info("  χ²: %d pruebas; umbral de p con Bonferroni = %.2e", m, p_umbral)
    pendientes = dec["decision"].isna() & dec["p_valor"].notna()
    irrelevante = pendientes & (
        (dec["p_valor"] >= p_umbral) | (dec["v_cramer"] < r["min_v_cramer"])
    )
    dec.loc[irrelevante, "decision"] = "descartar"
    dec.loc[irrelevante, "regla"] = "relevancia"
    dec.loc[irrelevante, "detalle"] = [
        f"V de Cramér {v:.4f}; p = {p:.2g} (umbral {p_umbral:.1e})"
        for v, p in dec.loc[irrelevante, ["v_cramer", "p_valor"]].itertuples(
            index=False
        )
    ]
    for regla in ("faltantes", "casi constante", "relevancia"):
        log.info("  %-15s %d descartadas", regla, int((dec["regla"] == regla).sum()))

    # Redundancia entre las numéricas que siguen en pie (incluidas las protegidas)
    numericas = [
        c
        for c in dec.index
        if esquema[c] in ("INTEGER", "FLOAT")
        and dec.at[c, "decision"] != "descartar"
        and c not in ("isFraud", "TransactionID")
    ]
    pares, maximo = _spearman(
        df, numericas, r["min_filas_correlacion"], r["max_spearman"], log
    )
    dec["rho_max"] = pd.Series({c: m[0] for c, m in maximo.items()})
    dec["rho_con"] = pd.Series({c: m[1] for c, m in maximo.items()})
    vecinos: dict[str, list[tuple[str, float]]] = {}
    for p in pares.itertuples():
        vecinos.setdefault(p.columna_a, []).append((p.columna_b, p.rho))
        vecinos.setdefault(p.columna_b, []).append((p.columna_a, p.rho))
    orden = sorted(
        numericas,
        key=lambda c: (
            c not in protegidas,
            -(dec.at[c, "v_cramer"] if pd.notna(dec.at[c, "v_cramer"]) else 0),
            dec.at[c, "pct_faltantes"],
            c,
        ),
    )
    conservadas: set[str] = set()
    for c in orden:
        choque = [(o, rho) for o, rho in vecinos.get(c, []) if o in conservadas]
        if choque and c not in protegidas:
            o, rho = max(choque, key=lambda t: abs(t[1]))
            dec.loc[c, ["decision", "regla", "detalle"]] = [
                "descartar",
                "redundancia",
                f"ρ = {rho:.3f} con {o}",
            ]
        else:
            conservadas.add(c)
    log.info(
        "  %-15s %d descartadas (%d pares con |ρ| >= %g)",
        "redundancia",
        int((dec["regla"] == "redundancia").sum()),
        len(pares),
        r["max_spearman"],
    )
    dec["decision"] = dec["decision"].fillna("conservar")
    dec["regla"] = dec["regla"].fillna("pasa los filtros")
    dec["detalle"] = dec["detalle"].fillna("")

    # PCA del bloque V conservado
    bloque = [
        c
        for c in dec.index
        if re.fullmatch(r["pca_columnas"], c) and dec.at[c, "decision"] == "conservar"
    ]
    assert bloque, "No quedó ninguna columna para el PCA"
    pca_var, cargas, k = _pca(df, bloque, r["pca_varianza"], cfg["semilla"])
    log.info(
        "  PCA: %d columnas V conservadas; %d componentes explican %.0f %% de la varianza",
        len(bloque),
        k,
        100 * r["pca_varianza"],
    )

    # Técnicas aplicadas a cada variable (columna de la tabla de decisión)
    def tecnicas(c: str) -> str:
        t = ["faltantes y valor dominante"] if c not in protegidas else []
        if pd.notna(dec.at[c, "p_valor"]):
            t.append("χ² + V de Cramér")
        if c in numericas:
            t.append("Spearman")
        if c in bloque:
            t.append("PCA")
        return ", ".join(t) if t else "ninguna (protegida)"

    dec.insert(2, "tecnicas", [tecnicas(c) for c in dec.index])

    # Validaciones
    assert len(dec) == len(esquema), "La tabla de decisión no cubre todas las columnas"
    assert (dec.loc[list(protegidas), "decision"] == "conservar").all(), (
        "Se descartó una columna protegida"
    )
    assert dec["v_cramer"].dropna().between(0, 1).all(), "V de Cramér fuera de [0, 1]"
    assert pca_var["varianza_acumulada"].is_monotonic_increasing, (
        "Varianza acumulada no creciente"
    )

    dec = dec.reset_index()
    dec.insert(0, "orden", range(1, len(dec) + 1))
    _guardar(client, cfg, dec, "reduccion_decision", log)
    carpeta = RAIZ / cfg["salidas"]["carpeta"]
    for nombre, t in (
        ("reduccion_pares_redundantes", pares),
        ("reduccion_pca_varianza", pca_var),
        ("reduccion_pca_cargas", cargas),
    ):
        t.to_csv(
            carpeta / f"{nombre}.csv",
            index=False,
            encoding="utf-8",
            lineterminator="\n",
            float_format="%.6g",
        )
        log.info("  -> %s/%s.csv (%d filas)", cfg["salidas"]["carpeta"], nombre, len(t))

    columnas = dec.loc[dec["decision"] == "conservar", "variable"].tolist()
    ejecutar(
        client,
        leer_sql(
            "05_vista_reducido.sql",
            cfg,
            {"columnas": ",\n  ".join(f"`{c}`" for c in columnas)},
        ),
        log,
    )
    log.info(
        "  vista %s: %d de %d columnas",
        cfg["tablas_prep"]["analitico_reducido"],
        len(columnas),
        len(dec),
    )

    _tabla_md(dec, cfg, log)

    from .figuras_prep import figuras_reduccion

    figuras_reduccion(dec, pca_var, cfg, log)


def _pca(df: pd.DataFrame, cols: list[str], meta: float, semilla: int):
    """PCA con mediana y estandarización de entrenamiento. Devuelve varianza, pesos y k para la meta."""
    from sklearn.decomposition import PCA

    x = df[cols].to_numpy(dtype=float)
    mediana = np.nanmedian(x, axis=0)
    x = np.where(np.isnan(x), mediana, x)
    media, de = x.mean(axis=0), x.std(axis=0)
    de[de == 0] = 1.0
    z = (x - media) / de
    pca = PCA(svd_solver="full", random_state=semilla).fit(z)
    acum = np.cumsum(pca.explained_variance_ratio_)
    k = int(np.searchsorted(acum, meta) + 1)
    var = pd.DataFrame(
        {
            "componente": np.arange(1, len(acum) + 1),
            "varianza": pca.explained_variance_ratio_,
            "varianza_acumulada": acum,
        }
    )
    cargas = pd.DataFrame(
        pca.components_[:k].T, index=cols, columns=[f"CP{i + 1}" for i in range(k)]
    )
    cargas.insert(0, "desviacion", de)
    cargas.insert(0, "media", media)
    cargas.insert(0, "mediana", mediana)
    return var, cargas.reset_index(names="variable"), k


RAZON_PROTEGIDA = {
    "TransactionID": "Llave de la transacción; dimensión degenerada del DW",
    "isFraud": "Variable objetivo",
    "tiene_identidad": "La usa el DW (dimensión de dispositivo)",
    "dia_relativo": "Tiempo derivado de TransactionDT; fecha del DW",
    "fecha": "Tiempo derivado de TransactionDT; fecha del DW",
    "hora": "Tiempo derivado de TransactionDT",
}


def _tabla_md(dec: pd.DataFrame, cfg: dict, log) -> None:
    """Tabla de decisión completa en Markdown, para incluirla en la página de preparación."""
    filas = []
    for r in dec.itertuples():
        if r.regla == "protegida":
            if r.variable in RAZON_PROTEGIDA:
                razon = RAZON_PROTEGIDA[r.variable]
            elif r.variable in (
                "particion",
                "log_importe",
                "posible_duplicado",
                "importe_atipico",
            ):
                razon = "Columna creada por la limpieza"
            else:
                razon = "La usa el DW (E1)"
            just = f"Protegida: {razon[0].lower()}{razon[1:]}"
        elif r.decision == "conservar":
            just = f"V = {r.v_cramer:.3f}"
            if pd.notna(r.rho_max) and r.rho_con:
                just += f"; \\|ρ\\| máxima {abs(r.rho_max):.2f} con `{r.rho_con}`"
        else:
            just = f"{r.regla.capitalize()}: {r.detalle[0].lower()}{r.detalle[1:]}"
            for c in re.findall(r"con (\S+)$", r.detalle):
                just = just.replace(f"con {c}", f"con `{c}`")
        filas.append(
            f"| `{r.variable}` | {r.tipo} | {r.tecnicas} | {r.decision.capitalize()} | {just} |"
        )
    texto = (
        "<!-- Generado por el paso «reduccion» del pipeline: no editar a mano -->\n\n"
        "| Variable | Tipo | Técnicas | Decisión | Justificación |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n" + "\n".join(filas) + "\n"
    )
    ruta = (RAIZ / cfg["reduccion"]["tabla_md"]).resolve()
    ruta.write_text(texto, encoding="utf-8")
    log.info("  -> %s (%d variables)", ruta.name, len(filas))
