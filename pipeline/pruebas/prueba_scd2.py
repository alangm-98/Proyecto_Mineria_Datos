"""Prueba de la historia (SCD tipo 2) de dim_dominio_correo, en un dataset temporal.

No es un paso del pipeline y no toca el DW: crea un dataset de prueba con el
esquema de E1 y aplica sql/08_scd2_dominio.sql, el mismo archivo que usa el
paso «carga», con dos versiones de la lista de correo gratuito:
  1. La lista real (fuentes.dominios_fecha_carga), dos veces: la segunda no
     debe crear versiones (idempotencia).
  2. Una lista simulada con fecha posterior, donde algunos dominios dejan de
     ser gratuitos y otros pasan a serlo (config.yaml, dw.prueba_scd2), dos
     veces: cada dominio cambiado debe quedar con dos versiones, la anterior
     cerrada el día previo y la nueva vigente.
Guarda las versiones de los dominios cambiados en salidas/prueba_scd2.csv y
borra el dataset al terminar (salvo con --conservar).

Uso (desde pipeline/):
    uv run python pruebas/prueba_scd2.py
"""

import argparse
import copy
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bq import cliente, ejecutar, leer_sql  # noqa: E402
from src.carga import scd2_dominio  # noqa: E402
from src.config import RAIZ, cargar_config, tabla  # noqa: E402
from src.registro import iniciar_registro  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba de SCD 2 de dim_dominio_correo")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument(
        "--conservar", action="store_true", help="no borrar el dataset de prueba"
    )
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    log = iniciar_registro(cfg)
    client = cliente(cfg)
    p = cfg["dw"]["prueba_scd2"]
    ds = f"{cfg['proyecto']['id']}.{p['dataset']}"
    prueba = copy.deepcopy(cfg)
    prueba["datasets"]["dw"] = prueba["datasets"]["mart"] = p["dataset"]
    dim = f"{ds}.dim_dominio_correo"
    lista_real = tabla(cfg, "prep", cfg["tablas_prep"]["dominios_lista"])
    lista_nueva = f"{ds}.lista_simulada"
    f1, f2 = cfg["fuentes"]["dominios_fecha_carga"], p["fecha_lista_nueva"]
    cambiados = list(p["quitar_de_lista"]) + list(p["agregar_a_lista"])

    def versiones() -> int:
        return client.get_table(dim).num_rows

    client.delete_dataset(ds, delete_contents=True, not_found_ok=True)
    try:
        log.info("== Esquema de E1 en el dataset de prueba %s ==", ds)
        ejecutar(client, leer_sql("06_ddl_dw.sql", prueba), log)

        log.info("== Lista real (%s), dos veces ==", f1)
        scd2_dominio(client, prueba, dim, lista_real, f1, log)
        n1 = versiones()
        scd2_dominio(client, prueba, dim, lista_real, f1, log)
        assert versiones() == n1, "La segunda corrida con la misma lista creó versiones"
        log.info("  %d versiones; la segunda corrida no cambió nada", n1)

        log.info(
            "== Lista simulada (%s): quita %s y agrega %s ==",
            f2,
            p["quitar_de_lista"],
            p["agregar_a_lista"],
        )
        quitar = ", ".join(f"'{d}'" for d in p["quitar_de_lista"])
        agregar = ", ".join(f"'{d}'" for d in p["agregar_a_lista"])
        ejecutar(
            client,
            f"""CREATE TABLE `{lista_nueva}` AS
            SELECT dominio FROM `{lista_real}` WHERE dominio NOT IN ({quitar})
            UNION ALL SELECT d FROM UNNEST([{agregar}]) AS d""",
            log,
        )
        scd2_dominio(client, prueba, dim, lista_nueva, f2, log)
        n2 = versiones()
        scd2_dominio(client, prueba, dim, lista_nueva, f2, log)
        assert versiones() == n2, (
            "La segunda corrida con la lista simulada creó versiones"
        )
        assert n2 == n1 + len(cambiados), (
            f"Se esperaban {len(cambiados)} versiones nuevas y hay {n2 - n1}"
        )
        log.info(
            "  %d versiones nuevas (una por dominio cambiado); la segunda corrida no cambió nada",
            n2 - n1,
        )

        lista = ", ".join(f"'{d}'" for d in cambiados)
        df = ejecutar(
            client,
            f"""SELECT dominio_correo_key, dominio, es_gratuito, valido_desde, valido_hasta, es_actual
            FROM `{dim}` WHERE dominio IN ({lista}) ORDER BY dominio, valido_desde""",
            log,
        ).to_dataframe()
        cierre = date.fromisoformat(f2) - timedelta(days=1)
        for d in cambiados:
            v = df[df["dominio"] == d].reset_index(drop=True)
            assert len(v) == 2, f"{d}: se esperaban 2 versiones y hay {len(v)}"
            assert (
                not v.at[0, "es_actual"]
                and str(v.at[0, "valido_hasta"]) == cierre.isoformat()
            ), f"{d}: la versión anterior no quedó cerrada"
            assert v.at[1, "es_actual"] and str(v.at[1, "valido_desde"]) == f2, (
                f"{d}: la versión nueva no quedó vigente"
            )
            assert v.at[0, "es_gratuito"] != v.at[1, "es_gratuito"], (
                f"{d}: la clasificación no cambió"
            )
            assert v.at[0, "dominio_correo_key"] != v.at[1, "dominio_correo_key"], (
                f"{d}: las versiones comparten llave"
            )
        salida = RAIZ / cfg["salidas"]["carpeta"] / "prueba_scd2.csv"
        df.to_csv(salida, index=False, encoding="utf-8", lineterminator="\n")
        log.info("\n%s", df.to_string(index=False))
        log.info("  -> %s", salida.relative_to(RAIZ))
        log.info("Prueba de SCD 2 correcta")
    except AssertionError as e:
        log.error("Prueba fallida: %s", e)
        return 1
    finally:
        if args.conservar:
            log.info("Dataset de prueba conservado: %s", ds)
        else:
            client.delete_dataset(ds, delete_contents=True, not_found_ok=True)
            log.info("Dataset de prueba borrado: %s", ds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
