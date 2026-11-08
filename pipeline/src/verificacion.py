"""Verificación previa: credenciales, datasets y tablas de staging.

Solo lee metadatos (get_dataset, get_table), que BigQuery no cobra.
"""

from google.api_core.exceptions import NotFound

from .config import tabla


def verificar_entorno(client, cfg: dict, log) -> None:
    proyecto = cfg["proyecto"]["id"]
    log.info("Proyecto: %s (ubicación %s)", proyecto, cfg["proyecto"]["ubicacion"])

    # 1. Staging debe existir y estar en la ubicación configurada
    ds = client.get_dataset(f"{proyecto}.{cfg['datasets']['staging']}")
    assert ds.location == cfg["proyecto"]["ubicacion"], (
        f"{ds.dataset_id} está en {ds.location}, no en {cfg['proyecto']['ubicacion']}"
    )
    log.info("Dataset %s encontrado en %s", ds.dataset_id, ds.location)

    # 2. Tablas de staging presentes, con sus filas
    filas = {}
    for clave, nombre in cfg["staging"].items():
        try:
            t = client.get_table(tabla(cfg, "staging", nombre))
        except NotFound as e:
            raise AssertionError(
                f"No existe {nombre} en staging. Ver README, sección «Proyecto propio»."
            ) from e
        filas[clave] = t.num_rows
        log.info(
            "  %-34s %9s filas  %4d columnas", nombre, f"{t.num_rows:,}", len(t.schema)
        )

    # 3. La fuente A debe estar completa
    esp = cfg["esperado"]
    assert filas["ieee_transaccion"] == esp["ieee_transaccion_filas"], (
        f"ieee_transaccion tiene {filas['ieee_transaccion']:,} filas; se esperaban {esp['ieee_transaccion_filas']:,}"
    )
    assert filas["ieee_identidad"] == esp["ieee_identidad_filas"], (
        f"ieee_identidad tiene {filas['ieee_identidad']:,} filas; se esperaban {esp['ieee_identidad_filas']:,}"
    )
    log.info("Verificación previa correcta")
