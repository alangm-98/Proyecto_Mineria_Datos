"""Conexión a BigQuery y ejecución de archivos SQL con parámetros de la configuración.

La autenticación usa las credenciales de aplicación por defecto (ADC) del
usuario: `gcloud auth application-default login`. No se lee ninguna llave
de cuenta de servicio ni se guarda ninguna credencial en el repositorio.
"""

from pathlib import Path
from string import Template

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery

from .config import RAIZ


def cliente(cfg: dict) -> bigquery.Client:
    try:
        return bigquery.Client(
            project=cfg["proyecto"]["id"], location=cfg["proyecto"]["ubicacion"]
        )
    except DefaultCredentialsError:
        raise SystemExit(
            "No se encontraron credenciales de Google Cloud. Ejecutar:\n"
            "  gcloud auth application-default login\n"
            f"  gcloud auth application-default set-quota-project {cfg['proyecto']['id']}"
        ) from None


def parametros_sql(cfg: dict) -> dict:
    """Valores que pueden aparecer en los .sql como ${proyecto}, ${staging}, etc.

    ${proyecto}, ${ubicacion}: proyecto y ubicación
    ${staging}, ${prep}, ${dw}, ${mart}: nombres de los datasets
    ${t_<clave>}: tablas de staging; ${p_<clave>}: tablas de lumen_prep
    ${<clave>}: cada valor de las secciones `supuestos` y `fuentes`
    """
    p = {
        "proyecto": cfg["proyecto"]["id"],
        "ubicacion": cfg["proyecto"]["ubicacion"],
        **cfg["datasets"],
    }
    p.update({f"t_{k}": v for k, v in cfg["staging"].items()})
    p.update({f"p_{k}": v for k, v in cfg.get("tablas_prep", {}).items()})
    p.update({k: str(v) for k, v in cfg.get("supuestos", {}).items()})
    p.update({k: str(v) for k, v in cfg.get("fuentes", {}).items()})
    return p


def leer_sql(ruta: str | Path, cfg: dict, extra: dict | None = None) -> str:
    """Lee un .sql de la carpeta sql/ de la raíz del repositorio y sustituye ${...}.

    `extra`: fragmentos de SQL generados por código a partir del esquema y de
    la configuración (por ejemplo, listas de 438 columnas). Falla si queda
    algún ${...} sin valor.
    """
    ruta = Path(ruta)
    if not ruta.is_absolute():
        ruta = RAIZ.parent / "sql" / ruta
    return Template(ruta.read_text(encoding="utf-8")).substitute(
        {**parametros_sql(cfg), **(extra or {})}
    )


def ejecutar(client: bigquery.Client, sql: str, log=None) -> bigquery.table.RowIterator:
    """Ejecuta una consulta y registra los bytes procesados (BigQuery cobra por ellos)."""
    trabajo = client.query(sql)
    filas = trabajo.result()
    if log is not None:
        mb = (trabajo.total_bytes_processed or 0) / 1e6
        log.info("  consulta terminada: %.1f MB procesados", mb)
    return filas
