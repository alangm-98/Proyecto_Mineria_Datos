"""Pagos Lumen · E2 · Punto de entrada único del pipeline.

Lleva los datos de lumen_staging al DW poblado, en pasos separados y
nombrados. Cada paso es idempotente: correr el pipeline dos veces da el
mismo resultado.

Uso (desde la carpeta pipeline/):
    uv run python run_pipeline.py                   # todos los pasos
    uv run python run_pipeline.py --solo-verificar  # credenciales y staging
    uv run python run_pipeline.py --hasta calidad   # de la verificación hasta ese paso
    uv run python run_pipeline.py --desde limpieza  # desde ese paso hasta el final
"""

import argparse
import sys
import time

from src.bq import cliente
from src.config import cargar_config
from src.registro import iniciar_registro
from src.verificacion import verificar_entorno

# Orden de los pasos. Cada uno se implementa en la fase indicada del plan;
# mientras tanto el pipeline lo omite y lo deja en el registro.
PASOS = [
    ("ingesta", "A1"),
    ("calidad", "A1"),
    ("limpieza", "B"),
    ("reduccion", "B"),
    ("muestreo", "B"),
    ("carga", "C"),
]
IMPLEMENTADOS: dict = {}  # nombre del paso -> función(client, cfg, log)


def main() -> int:
    nombres = [p for p, _ in PASOS]
    ap = argparse.ArgumentParser(description="Pipeline de E2: staging -> DW")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--desde", choices=nombres, default=nombres[0])
    ap.add_argument("--hasta", choices=nombres, default=nombres[-1])
    ap.add_argument("--solo-verificar", action="store_true")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    log = iniciar_registro(cfg)
    client = cliente(cfg)

    inicio = time.time()
    try:
        log.info("== Verificación previa ==")
        verificar_entorno(client, cfg, log)
        if args.solo_verificar:
            return 0

        i, j = nombres.index(args.desde), nombres.index(args.hasta)
        assert i <= j, "--desde debe ir antes que --hasta"
        for nombre, fase in PASOS[i : j + 1]:
            log.info("== Paso: %s ==", nombre)
            if nombre not in IMPLEMENTADOS:
                log.warning("  pendiente: se implementa en la fase %s del plan", fase)
                continue
            t0 = time.time()
            IMPLEMENTADOS[nombre](client, cfg, log)
            log.info("  %s terminado en %.0f s", nombre, time.time() - t0)
    except AssertionError as e:
        log.error("Validación fallida: %s", e)
        return 1
    finally:
        log.info("Tiempo total: %.0f s", time.time() - inicio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
