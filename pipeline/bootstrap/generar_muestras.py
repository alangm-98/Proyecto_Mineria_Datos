"""Genera los archivos de muestra de data/sample/ que no son copias de una fuente.

  --sintetico  IEEE-CIS sintético: mismas columnas y tipos que train_transaction.csv
               y train_identity.csv (esquemas de esquemas/), con valores inventados
               por código y semilla fija. No contiene ninguna transacción real: las
               reglas de la competencia prohíben redistribuir los datos de la fuente A.
               No necesita Google Cloud.
  --ulb        Muestra de la fuente C (ULB), con semilla fija, leída de staging en
               BigQuery. Su licencia (ODbL 1.0 / DbCL 1.0) permite redistribuirla.

Los dos sirven para ver el esquema de cada fuente y probar código. Todo el
análisis y el DW usan los datos reales completos en BigQuery.

Uso (desde pipeline/):
    uv run python bootstrap/generar_muestras.py --sintetico
    uv run python bootstrap/generar_muestras.py --ulb
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RAIZ, cargar_config, tabla  # noqa: E402

# Categorías de las columnas de texto que la documentación de la competencia nombra
# (o que el diagnóstico de E2 mostró). Las demás columnas de texto reciben valores
# genéricos «SINTETICO_A», «SINTETICO_B».
CATEGORIAS = {
    "ProductCD": ["W", "C", "R", "H", "S"],
    "card4": ["visa", "mastercard", "american express", "discover"],
    "card6": ["debit", "credit"],
    "P_emaildomain": ["gmail.com", "yahoo.com", "hotmail.com", "anonymous.com"],
    "R_emaildomain": ["gmail.com", "yahoo.com", "hotmail.com", "anonymous.com"],
    "M4": ["M0", "M1", "M2"],
    "DeviceType": ["desktop", "mobile"],
}
VERDADERO_FALSO = {f"M{i}" for i in range(1, 10) if i != 4} | {
    f"id_{i}" for i in range(35, 39)
}
SIEMPRE_PRESENTES = {
    "TransactionID",
    "isFraud",
    "TransactionDT",
    "TransactionAmt",
    "ProductCD",
    "card1",
}


def _esquema(nombre: str) -> list[dict]:
    return json.loads(
        (RAIZ / "esquemas" / f"{nombre}.json").read_text(encoding="utf-8")
    )


def _columna(rng, campo: dict, n: int) -> pd.Series:
    nombre, tipo = campo["name"], campo["type"]
    if nombre in CATEGORIAS:
        valores = rng.choice(CATEGORIAS[nombre], size=n).astype(object)
    elif nombre in VERDADERO_FALSO:
        valores = rng.choice(["T", "F"], size=n).astype(object)
    elif tipo == "STRING":
        valores = rng.choice(["SINTETICO_A", "SINTETICO_B"], size=n).astype(object)
    elif tipo == "INTEGER":
        valores = rng.integers(1000, 20000, size=n).astype(object)
    else:  # FLOAT
        valores = np.round(rng.gamma(1.0, 50.0, size=n), 2).astype(object)
    if nombre not in SIEMPRE_PRESENTES:
        valores[rng.random(n) < 0.3] = None  # faltantes, como en la fuente
    return pd.Series(valores, name=nombre)


def sintetico(cfg: dict) -> None:
    m = cfg["muestra"]
    n = m["sintetico_transacciones"]
    rng = np.random.default_rng(cfg["semilla"])

    trans = pd.concat(
        [_columna(rng, c, n) for c in _esquema("ieee_train_transaction")], axis=1
    )
    trans["TransactionID"] = np.arange(1, n + 1)
    trans["isFraud"] = (rng.random(n) < m["sintetico_pct_fraude"]).astype(int)
    trans["TransactionDT"] = np.sort(rng.integers(86400, 86400 * 15, size=n))
    trans["TransactionAmt"] = np.round(rng.lognormal(4.0, 1.0, size=n), 3)

    con_id = np.sort(
        rng.choice(
            trans["TransactionID"],
            size=int(n * m["sintetico_pct_identidad"]),
            replace=False,
        )
    )
    ident = pd.concat(
        [_columna(rng, c, len(con_id)) for c in _esquema("ieee_train_identity")], axis=1
    )
    ident["TransactionID"] = con_id

    carpeta = RAIZ / "data" / "sample"
    for df, nombre in (
        (trans, "ieee_sintetico_train_transaction.csv"),
        (ident, "ieee_sintetico_train_identity.csv"),
    ):
        df.to_csv(carpeta / nombre, index=False, lineterminator="\n")
        print(f"{nombre}: {len(df):,} filas, {df.shape[1]} columnas (SINTÉTICO)")


def ulb(cfg: dict) -> None:
    from src.bq import cliente

    n = cfg["muestra"]["ulb_filas"]
    origen = tabla(cfg, "staging", cfg["staging"]["ulb"])
    # Muestra aleatoria simple reproducible: se ordena por una huella de cada fila
    # combinada con la semilla y se toman las primeras n.
    sql = (
        f"SELECT * EXCEPT (orden) FROM ("
        f"SELECT t.*, FARM_FINGERPRINT(CONCAT(TO_JSON_STRING(t), '{cfg['semilla']}')) AS orden "
        f"FROM `{origen}` AS t) ORDER BY orden LIMIT {n}"
    )
    df = cliente(cfg).query(sql).result().to_dataframe()
    df = df.sort_values(list(df.columns), kind="stable").reset_index(
        drop=True
    )  # orden reproducible
    ruta = RAIZ / "data" / "sample" / "ulb_muestra.csv"
    df.to_csv(ruta, index=False, lineterminator="\n")
    print(
        f"{ruta.name}: {len(df):,} filas, {df.shape[1]} columnas, {int(df['Class'].sum())} fraude(s)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Muestras de data/sample/")
    ap.add_argument(
        "--sintetico", action="store_true", help="IEEE-CIS sintético (sin Google Cloud)"
    )
    ap.add_argument("--ulb", action="store_true", help="muestra de ULB desde staging")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    assert args.sintetico or args.ulb, "Indicar --sintetico, --ulb o ambos"
    cfg = cargar_config(args.config)
    if args.sintetico:
        sintetico(cfg)
    if args.ulb:
        ulb(cfg)


if __name__ == "__main__":
    main()
