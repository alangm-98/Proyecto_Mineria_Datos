"""Figuras del EDA (PNG estáticos para el sitio Quarto) y tablas cruzadas que las sustentan.

Criterios (PDF de E2, tabla «Visualización: elección correcta del gráfico», y la guía de
visualización usada en el proyecto):
  - Cada figura tiene un título que enuncia lo que muestra, ejes con nombre y unidades, y
    se comenta en eda.qmd.
  - Un solo eje vertical por gráfico (nunca dos escalas). El Pareto usa porcentaje de filas
    tanto en las barras como en la línea acumulada.
  - Escala logarítmica solo en el importe, y se justifica: asimetría 14.4 y 4 órdenes de
    magnitud entre el mínimo (0.25 USD) y el máximo (31,937 USD).
  - Colores en orden fijo de una paleta validada para daltonismo; la identidad nunca va
    solo en el color (etiquetas directas, estilos de línea, tramas), para que la figura se
    lea también en escala de grises.
"""

import matplotlib

matplotlib.use("Agg")  # sin ventana: solo archivos
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from .comun import guardar_tabla, ruta  # noqa: E402
from .concentracion import gini  # noqa: E402

# Paleta categórica validada (orden fijo) y tinta de texto
AZUL, NARANJA, AQUA, AMARILLO, MAGENTA = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
)
SERIES = [AZUL, NARANJA, AQUA, AMARILLO, MAGENTA]
TEXTO, TEXTO_2, REJILLA, FONDO = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
COLOR_CLASE = {"legítima": AZUL, "fraude": NARANJA}
LINEA_CLASE = {"legítima": "-", "fraude": "--"}

plt.rcParams.update(
    {
        "figure.facecolor": FONDO,
        "axes.facecolor": FONDO,
        "savefig.facecolor": FONDO,
        "axes.edgecolor": TEXTO_2,
        "axes.labelcolor": TEXTO,
        "xtick.color": TEXTO_2,
        "ytick.color": TEXTO_2,
        "text.color": TEXTO,
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": REJILLA,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "legend.frameon": False,
        "font.size": 10,
    }
)
MILES = FuncFormatter(lambda v, _: f"{v:,.0f}")


def _guardar(fig, cfg: dict, nombre: str, log) -> None:
    p = ruta(cfg, "figuras") / f"{nombre}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("  -> %s", p.name)


def f01_importe_histograma(df, cfg, log):
    """Numérica: histograma del importe con intervalos logarítmicos, por clase.

    La altura es la proporción de transacciones de cada clase que cae en el intervalo (no la
    densidad por USD, que con intervalos logarítmicos aplastaría visualmente los importes altos).
    Las dos clases se comparan en proporción porque tienen tamaños muy distintos.
    """
    fig, ax = plt.subplots(figsize=(8, 4.2))
    bordes = np.logspace(np.log10(0.25), np.log10(32000), 60)
    for clase in ("legítima", "fraude"):
        x = df.loc[df["clase"] == clase, "TransactionAmt"]
        ax.hist(
            x,
            bins=bordes,
            weights=np.full(len(x), 1 / len(x)),
            histtype="step",
            linewidth=2,
            color=COLOR_CLASE[clase],
            linestyle=LINEA_CLASE[clase],
            label=f"{clase} (n = {len(x):,}; mediana {x.median():,.2f} USD)",
        )
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}")
    )
    ax.set_xlabel("Importe de la transacción (USD, escala logarítmica)")
    ax.set_ylabel("Proporción de transacciones de la clase")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_title(
        "El importe es muy asimétrico; el del fraude se reparte más en el tramo medio-alto"
    )
    ax.legend(loc="upper left")
    _guardar(fig, cfg, "f01_importe_histograma", log)


def f02_importe_por_producto(df, cfg, log):
    """Numérica por grupos: boxplots del importe por producto, ordenados por mediana."""
    orden = (
        df.groupby("ProductCD")["TransactionAmt"].median().sort_values().index.tolist()
    )
    datos = [df.loc[df["ProductCD"] == p, "TransactionAmt"] for p in orden]
    tasas = df.groupby("ProductCD")["isFraud"].mean()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.boxplot(
        datos,
        tick_labels=[f"{p}\n(fraude {100 * tasas[p]:.1f} %)" for p in orden],
        showfliers=False,
        widths=0.5,
        medianprops={"color": NARANJA, "linewidth": 2},
        boxprops={"color": AZUL},
        whiskerprops={"color": AZUL},
        capprops={"color": AZUL},
    )
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(MILES)
    ax.set_xlabel(
        "Producto (ProductCD), ordenado por mediana del importe; tasa de fraude entre paréntesis"
    )
    ax.set_ylabel("Importe (USD, escala logarítmica)")
    ax.set_title("El producto con más fraude (C) es el de importes más bajos")
    ax.text(
        0.99,
        0.02,
        "Cajas: cuartiles; bigotes: 1.5 IQR; sin puntos atípicos dibujados",
        transform=ax.transAxes,
        ha="right",
        fontsize=8,
        color=TEXTO_2,
    )
    _guardar(fig, cfg, "f02_importe_por_producto", log)


def f03_tasa_por_categoria(df, cfg, log):
    """Categórica vs objetivo: tasa de fraude por categoría, barras ordenadas, con n."""
    paneles = [
        ("ProductCD", "Producto"),
        ("card6", "Tipo de tarjeta"),
        ("tiene_identidad", "Registro de identidad"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=False)
    global_ = df["isFraud"].mean()
    for ax, (var, titulo) in zip(axes, paneles):
        v = df[var].astype("object").where(df[var].notna(), "(nulo)")
        if var == "tiene_identidad":
            v = v.map({True: "con identidad", False: "sin identidad"})
        t = df.assign(_c=v).groupby("_c")["isFraud"].agg(["mean", "size"])
        minimo = min(
            cfg["eda"]["min_filas_categoria"], int(0.01 * len(df))
        )  # 1,000 con los datos reales
        t = t[t["size"] >= minimo].sort_values("mean")
        ax.barh(t.index, 100 * t["mean"], color=AZUL, height=0.6)
        for i, (m, n) in enumerate(zip(t["mean"], t["size"])):
            ax.text(
                100 * m + 0.2,
                i,
                f"{100 * m:.1f} %  (n = {n:,})",
                va="center",
                fontsize=8,
                color=TEXTO,
            )
        ax.axvline(100 * global_, color=TEXTO_2, linestyle=":", linewidth=1.2)
        ax.set_xlim(0, 100 * t["mean"].max() * 1.9)
        ax.set_title(titulo, fontsize=11)
        ax.set_xlabel("Tasa de fraude (% de transacciones)")
        ax.grid(axis="y", visible=False)
    fig.suptitle(
        "La tasa de fraude cambia mucho entre categorías",
        fontweight="bold",
        fontsize=12,
    )
    fig.text(
        0.5,
        0.005,
        f"Línea punteada: tasa global ({100 * global_:.1f} %). Se omiten categorías con menos de "
        f"{minimo:,} transacciones.",
        ha="center",
        fontsize=8,
        color=TEXTO_2,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _guardar(fig, cfg, "f03_tasa_por_categoria", log)


def f04_pareto_correo(df, cfg, log):
    """Categórica con concentración: Pareto de P_emaildomain (un solo eje, en % de filas)."""
    v = (
        df["P_emaildomain"]
        .astype("object")
        .where(df["P_emaildomain"].notna(), "(nulo)")
    )
    part = v.value_counts(normalize=True)
    top = part.head(12)
    serie = pd.concat(
        [top, pd.Series({f"Otros ({len(part) - 12} categorías)": part.iloc[12:].sum()})]
    )
    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = np.arange(len(serie))
    ax.bar(
        x,
        100 * serie.values,
        color=AZUL,
        width=0.6,
        label="Participación de cada dominio",
    )
    ax.plot(
        x,
        100 * serie.cumsum().values,
        color=NARANJA,
        marker="o",
        markersize=5,
        linewidth=2,
        linestyle="--",
        label="Participación acumulada",
    )
    for xi, c in zip(x, serie.cumsum().values):
        if xi in (0, 1, 2, 5, len(serie) - 1):
            ax.text(
                xi,
                100 * c + 2.5,
                f"{100 * c:.0f} %",
                ha="center",
                fontsize=8,
                color=TEXTO,
            )
    ax.set_xticks(x, serie.index, rotation=40, ha="right")
    ax.set_ylim(0, 110)
    ax.yaxis.set_major_formatter(PercentFormatter())
    ax.set_ylabel("Transacciones (% del total)")
    ax.set_xlabel("Dominio de correo del comprador (P_emaildomain)")
    n4 = 100 * serie.iloc[:4].sum()
    ax.set_title(
        f"Las cuatro categorías más frecuentes reúnen el {n4:.0f} % de las transacciones"
    )
    ax.legend(loc="center right")
    _guardar(fig, cfg, "f04_pareto_correo", log)


def f05_serie_diaria(diaria, cfg, log):
    """Serie temporal: volumen y tasa de fraude diarios, en dos paneles (no dos ejes)."""
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True)
    a1.plot(diaria["dia_relativo"], diaria["transacciones"], color=AZUL, linewidth=1.6)
    a2.plot(
        diaria["dia_relativo"],
        100 * diaria["tasa_fraude"],
        color=NARANJA,
        linewidth=1.6,
    )
    d = cfg["eda"]["periodo_dias"]
    for ax in (a1, a2):
        for b in range(d, d * cfg["eda"]["periodos"], d):
            ax.axvline(b + 0.5, color=TEXTO_2, linestyle=":", linewidth=1)
    for k in range(cfg["eda"]["periodos"]):
        a1.text(
            d * k + d / 2,
            a1.get_ylim()[1] * 0.97,
            f"periodo {k + 1}",
            ha="center",
            va="top",
            fontsize=8,
            color=TEXTO_2,
        )
    a1.set_ylim(0, diaria["transacciones"].max() * 1.12)
    a1.yaxis.set_major_formatter(MILES)
    a1.set_ylabel("Transacciones por día")
    a2.set_ylim(0, 100 * diaria["tasa_fraude"].max() * 1.12)
    a2.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    a2.set_ylabel("Tasa de fraude diaria")
    a2.set_xlabel("Día relativo (1 a 182; TransactionDT entre 86,400)")
    a1.set_title("El primer periodo tiene más volumen y menos fraude que el resto")
    fig.tight_layout()
    _guardar(fig, cfg, "f05_serie_diaria", log)


def f06_lorenz(lor, gin, cfg, log):
    """Concentración: curvas de Lorenz de G1 (importe) y G2 (card1), con su Gini."""
    g = gin.set_index(["variable", "valor"])["gini"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax in (a1, a2):
        ax.plot(
            [0, 1],
            [0, 1],
            color=TEXTO_2,
            linewidth=1,
            linestyle=":",
            label="igualdad perfecta (G = 0)",
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0))
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.set_aspect("equal")
    for clase, color, ls in (("legítima", AZUL, "-"), ("fraude", NARANJA, "--")):
        c = lor[lor["curva"] == f"G1 importe: {clase}"]
        a1.plot(
            c["prop_unidades"],
            c["prop_total"],
            color=color,
            linestyle=ls,
            linewidth=2,
            label=f"{clase}: G = {g[('TransactionAmt', clase)]:.3f}",
        )
    a1.set_title("G1: importe por transacción")
    a1.set_xlabel("Transacciones (acumulado, de menor a mayor importe)")
    a1.set_ylabel("Monto (acumulado)")
    for var, color, ls, etq in (
        ("transacciones", AZUL, "-", "transacciones"),
        ("fraudes", NARANJA, "--", "fraudes"),
    ):
        c = lor[lor["curva"] == f"G2 {var} por card1"]
        a2.plot(
            c["prop_unidades"],
            c["prop_total"],
            color=color,
            linestyle=ls,
            linewidth=2,
            label=f"{etq}: G = {g[(f'{var} por card1', 'todos')]:.3f}",
        )
    a2.set_title("G2: actividad y fraude por valor de card1")
    a2.set_xlabel("Valores de card1 (acumulado, de menor a mayor)")
    a2.set_ylabel("Total (acumulado)")
    a1.legend(loc="upper left", fontsize=8)
    a2.legend(loc="upper left", fontsize=8)
    fig.suptitle(
        "El fraude se concentra más que la actividad: en card1, el 10 % de los valores reúne el 98 %",
        fontweight="bold",
        fontsize=12,
    )
    fig.tight_layout()
    _guardar(fig, cfg, "f06_lorenz", log)


def f07_entropia(ent, cfg, log):
    """Heterogeneidad: entropía normalizada por clase (barras) y de ProductCD por periodo (línea)."""
    fig, (a1, a2) = plt.subplots(
        1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.4, 1]}
    )
    vars_ = ["ProductCD", "card6", "P_emaildomain (60 categorías)"]
    etiquetas = [
        "Producto\n(K = 5)",
        "Tipo de tarjeta\n(K = 5)",
        "Dominio de correo\n(K = 60)",
    ]
    x = np.arange(len(vars_))
    for k, (clase, color, trama) in enumerate(
        (("legítima", AZUL, ""), ("fraude", NARANJA, "//"))
    ):
        vals = [
            ent[(ent["variable"] == v) & (ent["valor"] == clase)][
                "entropia_norm_sobre_K"
            ].iloc[0]
            for v in vars_
        ]
        b = a1.bar(
            x + (k - 0.5) * 0.36,
            vals,
            width=0.34,
            color=color,
            hatch=trama,
            edgecolor=FONDO,
            label=clase,
        )
        a1.bar_label(b, fmt="%.2f", fontsize=8, padding=2)
    a1.set_xticks(x, etiquetas)
    a1.set_ylim(0, 1.25)
    a1.set_yticks(np.arange(0, 1.01, 0.2))
    a1.set_ylabel("Entropía normalizada (0 = una categoría; 1 = uniforme)")
    a1.set_title("Por clase", pad=10)
    a1.legend(loc="upper center", ncol=2)
    p = ent[(ent["variable"] == "ProductCD") & (ent["grupo"] == "periodo")]
    a2.plot(
        p["valor"].astype(int),
        p["entropia_norm_sobre_K"],
        color=AZUL,
        marker="o",
        markersize=6,
        linewidth=2,
    )
    a2.set_ylim(0, 1)
    a2.set_xticks(range(1, cfg["eda"]["periodos"] + 1))
    a2.set_xlabel("Periodo de 30 días")
    a2.set_ylabel("Entropía normalizada de ProductCD")
    a2.set_title("Producto, por periodo", pad=10)
    fig.suptitle(
        "El fraude se reparte más entre productos; la mezcla de productos cambia tras el periodo 1",
        fontweight="bold",
        fontsize=12,
    )
    fig.tight_layout()
    _guardar(fig, cfg, "f07_entropia", log)


def f08_faltantes(cal, cfg, log):
    """Calidad: porcentaje de faltantes de cada columna, en total y entre transacciones con identidad."""
    c = cal[cal["tabla_origen"] != "derivada"].reset_index(drop=True)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 4.6), sharex=True)
    a1.bar(c.index, c["pct_nulos"], color=AZUL, width=1.0)
    a2.bar(c.index, c["pct_nulos_con_identidad"], color=NARANJA, width=1.0)
    a1.set_ylabel("% de faltantes\n(todas)")
    a2.set_ylabel("% de faltantes\n(con identidad)")
    for ax in (a1, a2):
        ax.set_ylim(0, 100)
        ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax.grid(axis="x", visible=False)
    ini = c.groupby("grupo", sort=False).apply(
        lambda g: (g.index.min(), g.index.max()), include_groups=False
    )
    for grupo, (i0, i1) in ini.items():
        if i1 - i0 >= 8:
            a2.text((i0 + i1) / 2, -32, grupo, ha="center", fontsize=8, color=TEXTO_2)
        a1.axvline(i0 - 0.5, color=TEXTO_2, linewidth=0.6, linestyle=":")
        a2.axvline(i0 - 0.5, color=TEXTO_2, linewidth=0.6, linestyle=":")
    a2.set_xticks([])
    a2.set_xlabel(
        "Las 434 columnas de la fuente, en su orden original, por familia", labelpad=22
    )
    a1.set_title(
        "Los faltantes llegan en bloques de columnas, y algunos bloques faltan siempre que hay identidad"
    )
    fig.tight_layout()
    _guardar(fig, cfg, "f08_faltantes", log)


def f09_mezcla_producto(df, cfg, log):
    """Categórica vs categórica: barras apiladas al 100 % de ProductCD por periodo y por identidad."""
    productos = ["W", "C", "R", "H", "S"]
    fig, (a1, a2) = plt.subplots(
        1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.6, 1]}
    )
    for ax, var, etq in (
        (a1, "periodo", "Periodo de 30 días"),
        (a2, "tiene_identidad", "Registro de identidad"),
    ):
        t = pd.crosstab(df[var], df["ProductCD"], normalize="index")[productos]
        if var == "tiene_identidad":
            t.index = t.index.map({False: "sin identidad", True: "con identidad"})
        base = np.zeros(len(t))
        for p, color in zip(productos, SERIES):
            ax.bar(
                range(len(t)),
                100 * t[p],
                bottom=100 * base,
                color=color,
                edgecolor=FONDO,
                linewidth=1.5,
                width=0.65,
                label=p,
            )
            for i, (b, h) in enumerate(zip(base, t[p])):
                if h >= 0.06:
                    ax.text(
                        i,
                        100 * (b + h / 2),
                        f"{p} {100 * h:.0f} %",
                        ha="center",
                        va="center",
                        fontsize=7.5,
                        color=TEXTO,
                    )
            base += t[p].to_numpy()
        ax.set_xticks(range(len(t)), t.index)
        ax.set_xlabel(etq)
        ax.set_ylim(0, 100)
        ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax.grid(axis="x", visible=False)
    a1.set_ylabel("Transacciones (% del grupo)")
    a2.legend(title="ProductCD", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.suptitle(
        "La mezcla de productos cambia tras el periodo 1, y W nunca trae registro de identidad",
        fontweight="bold",
        fontsize=12,
    )
    fig.tight_layout()
    _guardar(fig, cfg, "f09_mezcla_producto", log)


def cruces(df, cfg, log):
    """Tablas cruzadas que sustentan f09 y la verificación de P3 (identidad dentro de cada producto)."""
    filas = []
    for var in ("periodo", "tiene_identidad"):
        t = (
            df.groupby([var, "ProductCD"])["isFraud"]
            .agg(transacciones="size", fraudes="sum")
            .reset_index()
        )
        t["prop_en_grupo"] = t["transacciones"] / t.groupby(var)[
            "transacciones"
        ].transform("sum")
        t["tasa_fraude"] = t["fraudes"] / t["transacciones"]
        t.insert(0, "cruce", f"{var} x ProductCD")
        filas.append(
            t.rename(columns={var: "grupo"}).assign(
                grupo=lambda d: d["grupo"].astype(str)
            )
        )
    guardar_tabla(pd.concat(filas), cfg, "cruces_producto", log)


def figuras(df, cfg, log):
    tablas = ruta(cfg, "tablas")
    diaria = pd.read_csv(tablas / "serie_diaria.csv")
    gin = pd.read_csv(tablas / "concentracion_gini.csv")
    lor = pd.read_csv(tablas / "concentracion_lorenz.csv")
    ent = pd.read_csv(tablas / "entropia.csv")
    cal = pd.read_csv(ruta(cfg, "tablas").parent / "calidad_columnas.csv")
    assert (
        abs(
            gini(df["TransactionAmt"])
            - gin.query("grupo == 'global' and variable == 'TransactionAmt'")[
                "gini"
            ].iloc[0]
        )
        < 1e-6
    ), (
        "Las tablas de concentración no corresponden al extracto actual: correr antes «concentracion»"
    )

    cruces(df, cfg, log)
    f01_importe_histograma(df, cfg, log)
    f02_importe_por_producto(df, cfg, log)
    f03_tasa_por_categoria(df, cfg, log)
    f04_pareto_correo(df, cfg, log)
    f05_serie_diaria(diaria, cfg, log)
    f06_lorenz(lor, gin, cfg, log)
    f07_entropia(ent, cfg, log)
    f08_faltantes(cal, cfg, log)
    f09_mezcla_producto(df, cfg, log)
