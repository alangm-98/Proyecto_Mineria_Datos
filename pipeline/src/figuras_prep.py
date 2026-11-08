"""Figuras de la preparación de los datos (PNG para el sitio Quarto).

Mismo estilo y paleta que las figuras del EDA (eda/figuras.py): un solo eje
vertical, título que enuncia lo que muestra, y la identidad nunca solo en el
color (forma del marcador y etiquetas directas).
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter

from eda.figuras import AZUL, NARANJA, TEXTO_2  # también aplica el estilo común

from .config import RAIZ

FAMILIAS = ["C", "D", "M", "V", "id", "card", "addr y dist", "otras"]


def _carpeta(cfg: dict):
    p = (RAIZ / cfg["reduccion"]["figuras"]).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _guardar(fig, cfg: dict, nombre: str, log) -> None:
    p = _carpeta(cfg) / f"{nombre}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("  -> %s", p.name)


def _familia(f: str) -> str:
    if f in ("C", "D", "M", "V", "id", "card"):
        return f
    if f in ("addr", "dist"):
        return "addr y dist"
    return "otras"


def f12_v_cramer(dec, cfg, log):
    """V de Cramér de cada variable contra isFraud, por familia, con el umbral de relevancia."""
    d = dec[dec["v_cramer"].notna() & (dec["regla"] != "protegida")].copy()
    d["grupo"] = d["familia"].map(_familia)
    umbral = cfg["reduccion"]["min_v_cramer"]
    rng = np.random.default_rng(cfg["semilla"])
    fig, ax = plt.subplots(figsize=(9, 4.6))
    estilos = {
        "conservar": dict(color=AZUL, marker="o", label="Se conserva"),
        "descartar": dict(
            color=NARANJA, marker="x", label="Se descarta (cualquier regla)"
        ),
    }
    for decision, est in estilos.items():
        s = d[d["decision"] == decision]
        x = s["grupo"].map(FAMILIAS.index) + rng.uniform(-0.28, 0.28, len(s))
        ax.scatter(x, s["v_cramer"], s=14, alpha=0.75, linewidths=1.2, **est)
    ax.axhline(umbral, color=TEXTO_2, linestyle="--", linewidth=1)
    ax.annotate(
        f"Umbral: V = {umbral:g}",
        (1.0, umbral),
        xycoords=("axes fraction", "data"),
        xytext=(4, 0),
        textcoords="offset points",
        ha="left",
        va="center",
        color=TEXTO_2,
        fontsize=9,
    )
    ax.set_xticks(
        range(len(FAMILIAS)), [f"{f}\n({(d['grupo'] == f).sum()})" for f in FAMILIAS]
    )
    ax.set_xlim(-0.6, len(FAMILIAS) - 0.4)
    ax.set_ylim(0, None)
    ax.set_xlabel("Familia de variables (número de variables)")
    ax.set_ylabel("V de Cramér con isFraud")
    ax.set_title("Relación de cada variable con el fraude, por familia (entrenamiento)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    ax.grid(axis="x", visible=False)
    _guardar(fig, cfg, "f12_v_cramer", log)


def f13_pca_varianza(var, cfg, log):
    """Varianza acumulada del PCA del bloque V, con la meta de varianza."""
    meta = cfg["reduccion"]["pca_varianza"]
    k = int(np.searchsorted(var["varianza_acumulada"].to_numpy(), meta) + 1)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(var["componente"], var["varianza_acumulada"], color=AZUL, linewidth=2)
    ax.axhline(meta, color=TEXTO_2, linestyle="--", linewidth=1)
    ax.axvline(k, color=TEXTO_2, linestyle=":", linewidth=1)
    ax.plot(
        [k], [var["varianza_acumulada"].iloc[k - 1]], "o", color=NARANJA, markersize=8
    )
    derecha = k > 0.6 * len(var)  # el texto va del lado con espacio
    ax.annotate(
        f"{k} componentes de {len(var)} explican el {100 * meta:.0f} %",
        (k, var["varianza_acumulada"].iloc[k - 1]),
        xytext=(-10 if derecha else 10, -18),
        textcoords="offset points",
        ha="right" if derecha else "left",
        color=TEXTO_2,
        fontsize=9,
    )
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.set_ylim(0, 1.02)
    ax.set_xlim(0, len(var) + 1)
    ax.set_xlabel("Número de componentes principales")
    ax.set_ylabel("Varianza explicada acumulada")
    ax.set_title(
        "Varianza explicada acumulada del PCA del bloque de columnas V (entrenamiento)"
    )
    _guardar(fig, cfg, "f13_pca_varianza", log)


def figuras_reduccion(dec, var, cfg, log) -> None:
    f12_v_cramer(dec, cfg, log)
    f13_pca_varianza(var, cfg, log)


def f14_tasas_antes_despues(t, cfg, log):
    """Tasa de fraude por categoría antes y después de preparar: si los puntos coinciden, se conservó."""
    d = t[t["grupo"] == "Tasa de fraude por categoría (%)"].iloc[::-1]
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(d) + 1.4))
    ax.scatter(
        d["antes"],
        y,
        s=110,
        facecolors="none",
        edgecolors=AZUL,
        linewidths=2,
        label="Antes (analitico_crudo)",
        zorder=3,
    )
    ax.scatter(
        d["despues"],
        y,
        s=28,
        color=NARANJA,
        marker="D",
        label="Después (analitico_reducido)",
        zorder=4,
    )
    for yi, (a, b) in enumerate(zip(d["antes"], d["despues"])):
        ax.annotate(
            f"{b:.2f} %",
            (max(a, b), yi),
            xytext=(10, 0),
            textcoords="offset points",
            va="center",
            color=TEXTO_2,
            fontsize=9,
        )
    ax.set_yticks(y, d["medida"])
    ax.set_xlim(0, d[["antes", "despues"]].to_numpy().max() * 1.18)
    ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.set_xlabel("Tasa de fraude")
    ax.set_title(
        "La tasa de fraude por categoría es la misma antes y después de preparar"
    )
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    ax.grid(axis="y", visible=False)
    _guardar(fig, cfg, "f14_tasas_antes_despues", log)


def f15_columnas_antes_despues(t, cfg, log):
    """Columnas por familia antes y después de la reducción."""
    d = t[t["medida"].str.startswith("Columnas de la familia")].copy()
    d["familia"] = d["medida"].str.replace("Columnas de la familia ", "", regex=False)
    d = d.sort_values("antes")
    y = np.arange(len(d))
    alto = 0.38
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(d) + 1.4))
    ax.barh(
        y + alto / 2,
        d["antes"],
        height=alto,
        color=AZUL,
        label="Antes",
        edgecolor="white",
        linewidth=2,
    )
    ax.barh(
        y - alto / 2,
        d["despues"],
        height=alto,
        color=NARANJA,
        label="Después",
        hatch="//",
        edgecolor="white",
        linewidth=2,
    )
    for yi, (a, b) in enumerate(zip(d["antes"], d["despues"])):
        ax.annotate(
            f"{a:.0f}",
            (a, yi + alto / 2),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            color=TEXTO_2,
            fontsize=9,
        )
        ax.annotate(
            f"{b:.0f}",
            (b, yi - alto / 2),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            color=TEXTO_2,
            fontsize=9,
        )
    ax.set_yticks(y, d["familia"])
    ax.set_xlabel("Número de columnas")
    total = t.set_index("medida").loc["Columnas", ["antes", "despues"]]
    ax.set_title(
        f"Columnas por familia: de {total['antes']:.0f} a {total['despues']:.0f} tras la reducción"
    )
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    _guardar(fig, cfg, "f15_columnas_antes_despues", log)


def figuras_antes_despues(t, cfg, log) -> None:
    f14_tasas_antes_despues(t, cfg, log)
    f15_columnas_antes_despues(t, cfg, log)
