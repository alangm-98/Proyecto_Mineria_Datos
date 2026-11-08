"""Genera el esquema explícito de las dos tablas de IEEE-CIS a partir de los CSV completos.

Por qué: la detección automática de BigQuery infiere el tipo de cada columna
con una muestra de las primeras filas. En un archivo de 590,540 filas, una
columna que empieza con enteros puede traer decimales más abajo, y la carga
fallaría o leería mal. Aquí el tipo se infiere leyendo el archivo completo.

Regla de tipos (pandas -> BigQuery):
    enteros sin faltantes -> INTEGER
    números con decimales o con faltantes -> FLOAT
    todo lo demás (texto) -> STRING

Uso (desde pipeline/):
    uv run python bootstrap/generar_esquema_ieee.py RUTA/train_transaction.csv RUTA/train_identity.csv

Escribe esquemas/ieee_train_transaction.json y esquemas/ieee_train_identity.json.
Los esquemas solo contienen nombres y tipos de columnas, no datos.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent


def tipo_bq(serie: pd.Series) -> str:
    k = serie.dtype.kind
    if k in "iu":
        return "INTEGER"
    if k == "f":
        return "FLOAT"
    if k == "b":
        return "BOOLEAN"
    return "STRING"


def esquema(ruta_csv: Path) -> list[dict]:
    df = pd.read_csv(ruta_csv, low_memory=False)
    print(f"{ruta_csv.name}: {len(df):,} filas, {df.shape[1]} columnas")
    campos = [
        {"name": c, "type": tipo_bq(df[c]), "mode": "NULLABLE"} for c in df.columns
    ]
    print("  tipos:", dict(Counter(c["type"] for c in campos)))
    return campos


def main() -> None:
    assert len(sys.argv) == 3, (
        "Uso: generar_esquema_ieee.py train_transaction.csv train_identity.csv"
    )
    salida = RAIZ / "esquemas"
    salida.mkdir(exist_ok=True)
    for ruta, nombre in zip(
        sys.argv[1:], ("ieee_train_transaction", "ieee_train_identity")
    ):
        campos = esquema(Path(ruta))
        destino = salida / f"{nombre}.json"
        destino.write_text(
            json.dumps(campos, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"  -> {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
