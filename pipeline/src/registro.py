"""Registro del pipeline: consola y archivo con fecha, uno por corrida."""

import logging
from datetime import datetime
from pathlib import Path

from .config import RAIZ


def iniciar_registro(cfg: dict) -> logging.Logger:
    carpeta = RAIZ / cfg.get("registro", {}).get("carpeta", "logs")
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"

    log = logging.getLogger("pipeline")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    formato = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S")
    for manejador in (
        logging.StreamHandler(),
        logging.FileHandler(archivo, encoding="utf-8"),
    ):
        manejador.setFormatter(formato)
        log.addHandler(manejador)
    log.info("Registro en %s", archivo.relative_to(RAIZ))
    return log
