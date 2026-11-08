"""Carga la capa staging en un proyecto de Google Cloud (bootstrap).

No forma parte del pipeline: el pipeline empieza en staging y nunca la
modifica. Este script sirve para dos cosas:
  1. Cargar la fuente A completa en el proyecto del equipo (fase 0 de E2).
  2. Que una persona ajena al equipo reproduzca staging en su propio
     proyecto y después ejecute el pipeline (ver README).

Protección de staging: si una tabla ya existe, el script no la toca, salvo
que se indique --reemplazar. Así no se pueden sobrescribir por accidente las
tablas cargadas en E1.

Fuentes: A desde Cloud Storage (no se redistribuye); B y D desde los archivos
de data/sample/, con las mismas opciones con que se cargaron en E1; C se copia
de la tabla pública de BigQuery.

Uso (desde pipeline/):
    uv run python bootstrap/cargar_staging.py --tablas ieee --simular
    uv run python bootstrap/cargar_staging.py --tablas ieee ulb banxico dominios
    uv run python bootstrap/cargar_staging.py --tablas banxico dominios --dataset lumen_prueba
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.api_core.exceptions import NotFound  # noqa: E402
from google.cloud import bigquery  # noqa: E402

from src.bq import cliente  # noqa: E402
from src.config import RAIZ, cargar_config, tabla  # noqa: E402

HOY = date.today().isoformat()


def existe(client, nombre_completo: str) -> bool:
    try:
        client.get_table(nombre_completo)
        return True
    except NotFound:
        return False


def leer_esquema(ruta: str) -> list[bigquery.SchemaField]:
    campos = json.loads((RAIZ / ruta).read_text(encoding="utf-8"))
    return [bigquery.SchemaField(c["name"], c["type"], mode=c["mode"]) for c in campos]


def cargar_csv_gcs(client, cfg, clave, csv, esquema, descripcion, args):
    destino = tabla(cfg, "staging", cfg["staging"][clave])
    uri = f"{cfg['bootstrap']['bucket'].rstrip('/')}/{cfg['bootstrap'][csv]}"
    if existe(client, destino) and not args.reemplazar:
        print(f"[omitida] {destino} ya existe (usar --reemplazar para sobrescribir)")
        return
    campos = leer_esquema(cfg["bootstrap"][esquema])
    print(f"[carga] {uri} -> {destino} ({len(campos)} columnas, esquema explícito)")
    if args.simular:
        return
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=campos,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=False,
    )
    client.load_table_from_uri(uri, destino, job_config=job_config).result()
    t = client.get_table(destino)
    t.description = f"{descripcion} Cargado el {HOY} con pipeline/bootstrap/cargar_staging.py desde {uri}."
    client.update_table(t, ["description"])
    print(f"  {t.num_rows:,} filas cargadas")


def cargar_ieee(client, cfg, args):
    cargar_csv_gcs(
        client,
        cfg,
        "ieee_transaccion",
        "ieee_transaccion_csv",
        "esquema_transaccion",
        "Fuente A: IEEE-CIS Fraud Detection (Kaggle; datos de Vesta), train_transaction.csv completo.",
        args,
    )
    cargar_csv_gcs(
        client,
        cfg,
        "ieee_identidad",
        "ieee_identidad_csv",
        "esquema_identidad",
        "Fuente A: IEEE-CIS Fraud Detection (Kaggle; datos de Vesta), train_identity.csv completo.",
        args,
    )


def cargar_ulb(client, cfg, args):
    destino = tabla(cfg, "staging", cfg["staging"]["ulb"])
    if existe(client, destino) and not args.reemplazar:
        print(f"[omitida] {destino} ya existe (usar --reemplazar para sobrescribir)")
        return
    sql = (
        f"CREATE OR REPLACE TABLE `{destino}` "
        f"OPTIONS (description = 'Fuente C: copia de bigquery-public-data.ml_datasets.ulb_fraud_detection. Creada el {HOY}.') AS "
        f"SELECT * FROM `bigquery-public-data.ml_datasets.ulb_fraud_detection`"
    )
    print(f"[copia] tabla pública ULB -> {destino}")
    if not args.simular:
        client.query(sql).result()


def cargar_archivo_local(
    client, cfg, clave, archivo, esquema, opciones, descripcion, args
):
    """Carga un archivo de data/sample/ con esquema explícito, como se hizo en E1."""
    destino = tabla(cfg, "staging", cfg["staging"][clave])
    ruta = RAIZ / cfg["bootstrap"][archivo]
    if existe(client, destino) and not args.reemplazar:
        print(f"[omitida] {destino} ya existe (usar --reemplazar para sobrescribir)")
        return
    campos = leer_esquema(cfg["bootstrap"][esquema])
    print(
        f"[carga] {ruta.relative_to(RAIZ)} -> {destino} ({len(campos)} columnas, esquema explícito)"
    )
    if args.simular:
        return
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        schema=campos,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        **opciones,
    )
    with open(ruta, "rb") as f:
        client.load_table_from_file(f, destino, job_config=job_config).result()
    t = client.get_table(destino)
    t.description = f"{descripcion} Cargado el {HOY} con pipeline/bootstrap/cargar_staging.py desde {ruta.relative_to(RAIZ)}."
    client.update_table(t, ["description"])
    print(f"  {t.num_rows:,} filas cargadas")


def cargar_banxico(client, cfg, args):
    # El CSV del SIE: 18 líneas de metadatos y la fila de encabezados (19 en total), en
    # ISO-8859-1. La fecha se carga como texto: la detección automática invertía día y mes.
    # La última línea del archivo está vacía; allow_jagged_rows la acepta como una fila con
    # todas las columnas vacías, igual que la carga de E1 desde la consola (46 filas).
    cargar_archivo_local(
        client,
        cfg,
        "banxico",
        "banxico_csv",
        "esquema_banxico",
        {"skip_leading_rows": 19, "encoding": "ISO-8859-1", "allow_jagged_rows": True},
        "Fuente B: Banco de México, SIE, cuadro CF621, exportado el 9 de octubre de 2026. Fecha como texto.",
        args,
    )


def cargar_dominios(client, cfg, args):
    # Una fila por línea del JSON: delimitador de campo que no aparece en el archivo
    # (tabulador) y sin carácter de comillas, para conservar la línea completa.
    cargar_archivo_local(
        client,
        cfg,
        "dominios",
        "dominios_json",
        "esquema_dominios",
        {"field_delimiter": "\t", "quote_character": "", "skip_leading_rows": 0},
        f"Fuente D: free-email-domains {cfg['fuentes']['dominios_version']}, domains.json. Copia cruda: una fila por línea del archivo.",
        args,
    )


CARGAS = {
    "ieee": cargar_ieee,
    "ulb": cargar_ulb,
    "banxico": cargar_banxico,
    "dominios": cargar_dominios,
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Carga de staging (bootstrap)")
    ap.add_argument("--tablas", nargs="+", choices=sorted(CARGAS), required=True)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument(
        "--dataset",
        help="cargar en este dataset en lugar del de staging (por ejemplo, para probar)",
    )
    ap.add_argument(
        "--reemplazar", action="store_true", help="sobrescribir tablas existentes"
    )
    ap.add_argument(
        "--simular", action="store_true", help="mostrar qué haría, sin cargar nada"
    )
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    if args.dataset:
        cfg["datasets"]["staging"] = args.dataset
    client = cliente(cfg)

    ds_id = f"{cfg['proyecto']['id']}.{cfg['datasets']['staging']}"
    try:
        client.get_dataset(ds_id)
    except NotFound:
        print(f"[dataset] {ds_id} no existe; se crea en {cfg['proyecto']['ubicacion']}")
        if not args.simular:
            ds = bigquery.Dataset(ds_id)
            ds.location = cfg["proyecto"]["ubicacion"]
            client.create_dataset(ds)

    for nombre in args.tablas:
        CARGAS[nombre](client, cfg, args)


if __name__ == "__main__":
    main()
