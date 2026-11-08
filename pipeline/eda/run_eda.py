"""Pagos Lumen · E2 · Análisis exploratorio.

No es un paso del pipeline: lee lumen_prep.analitico_crudo (que crea el paso
«ingesta») y escribe tablas agregadas en salidas/eda/ y figuras en
entregas/E2_eda_preparacion/img/eda/. No modifica BigQuery.

Uso (desde pipeline/):
    uv run python eda/run_eda.py                      # todos los pasos
    uv run python eda/run_eda.py --pasos extraer      # solo descargar el extracto
    uv run python eda/run_eda.py --pasos descriptiva  # usa el extracto local ya descargado
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eda.comun import cargar, extraer  # noqa: E402
from eda.concentracion import concentracion  # noqa: E402
from eda.descriptiva import descriptiva  # noqa: E402
from eda.figuras import figuras  # noqa: E402
from eda.mexico import mexico  # noqa: E402
from eda.tramo import tramo  # noqa: E402
from src.config import cargar_config  # noqa: E402
from src.registro import iniciar_registro  # noqa: E402

PASOS = [
    "extraer",
    "descriptiva",
    "concentracion",
    "figuras",
    "mexico",
    "tramo",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="EDA de E2")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--pasos", nargs="+", choices=PASOS, default=PASOS)
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    log = iniciar_registro(cfg)
    inicio = time.time()
    try:
        if "extraer" in args.pasos:
            log.info("== EDA: extraer ==")
            extraer(cfg, log)
        df = cargar(cfg)
        if "descriptiva" in args.pasos:
            log.info("== EDA: descriptiva ==")
            descriptiva(df, cfg, log)
        if "concentracion" in args.pasos:
            log.info("== EDA: concentración (Gini, Lorenz) y entropía ==")
            concentracion(df, cfg, log)
        if "figuras" in args.pasos:
            log.info("== EDA: figuras ==")
            figuras(df, cfg, log)
        if "mexico" in args.pasos:
            log.info("== EDA: brecha con México (Banxico CF621) ==")
            mexico(df, cfg, log)
        if "tramo" in args.pasos:
            log.info("== EDA: líneas base del tramo revisado ==")
            tramo(df, cfg, log)
    except AssertionError as e:
        log.error("Validación fallida: %s", e)
        return 1
    finally:
        log.info("Tiempo total: %.0f s", time.time() - inicio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
