"""Lectura de config.yaml y rutas relativas a la carpeta pipeline/."""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent  # carpeta pipeline/


def cargar_config(ruta: str | Path = "config.yaml") -> dict:
    """Lee la configuración. Una ruta relativa se resuelve contra pipeline/."""
    ruta = Path(ruta)
    if not ruta.is_absolute():
        ruta = RAIZ / ruta
    with open(ruta, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for clave in ("proyecto", "datasets", "staging", "semilla"):
        assert clave in cfg, f"Falta la clave '{clave}' en {ruta}"
    return cfg


def tabla(cfg: dict, capa: str, nombre: str) -> str:
    """Nombre completo de una tabla: `proyecto.dataset.tabla`."""
    return f"{cfg['proyecto']['id']}.{cfg['datasets'][capa]}.{nombre}"
