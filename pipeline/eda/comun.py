"""Utilidades del EDA: extracto local, periodos, rutas de salida y registro."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bq import cliente  # noqa: E402
from src.config import RAIZ, tabla  # noqa: E402


def ruta(cfg: dict, clave: str) -> Path:
    """Ruta de una carpeta o archivo de la sección eda de config.yaml (relativa a pipeline/)."""
    p = (RAIZ / cfg["eda"][clave]).resolve()
    (p.parent if p.suffix else p).mkdir(parents=True, exist_ok=True)
    return p


def periodo(dia_relativo: pd.Series, cfg: dict) -> pd.Series:
    """Bloque de días relativos: 1 = días 1 a 30, 2 = días 31 a 60, ...; el último absorbe el resto."""
    e = cfg["eda"]
    return ((dia_relativo - 1) // e["periodo_dias"] + 1).clip(upper=e["periodos"]).astype(int)


def extraer(cfg: dict, log) -> pd.DataFrame:
    """Descarga las columnas del EDA desde lumen_prep.analitico_crudo y las guarda en la caché local.

    La caché contiene datos reales de IEEE-CIS: vive en eda/cache/, que .gitignore excluye.
    """
    origen = tabla(cfg, "prep", cfg["tablas_prep"]["analitico_crudo"])
    cols = ", ".join(f"`{c}`" for c in cfg["eda"]["columnas"])
    trabajo = cliente(cfg).query(f"SELECT {cols} FROM `{origen}` ORDER BY TransactionID")
    df = trabajo.result().to_dataframe()
    log.info("  extracto: %s filas x %d columnas (%.1f MB procesados)",
             f"{len(df):,}", df.shape[1], (trabajo.total_bytes_processed or 0) / 1e6)
    assert len(df) == cfg["esperado"]["ieee_transaccion_filas"], "El extracto no tiene todas las transacciones"
    assert int(df["isFraud"].sum()) == cfg["esperado"]["ieee_fraudes"], "El extracto no tiene todos los fraudes"
    df.to_parquet(ruta(cfg, "extracto"), index=False)
    return df


def cargar(cfg: dict) -> pd.DataFrame:
    """Lee el extracto local y agrega el periodo y la clase como texto."""
    p = ruta(cfg, "extracto")
    assert p.exists(), "No hay extracto local: ejecutar primero el paso «extraer»"
    df = pd.read_parquet(p)
    df["periodo"] = periodo(df["dia_relativo"], cfg)
    df["clase"] = df["isFraud"].map({0: "legítima", 1: "fraude"})
    return df


def guardar_tabla(df: pd.DataFrame, cfg: dict, nombre: str, log) -> None:
    p = ruta(cfg, "tablas") / f"{nombre}.csv"
    df.to_csv(p, index=False, encoding="utf-8", lineterminator="\n", float_format="%.6g")
    log.info("  -> %s (%d filas)", p.relative_to(RAIZ), len(df))
