# Pipeline de E2 · Pagos Lumen

Pipeline reproducible de la entrega E2 (EDA y preparación de los datos). Lleva los datos crudos de
`lumen_staging` al esquema estrella de `lumen_dw`, pasando por una capa de preparación
(`lumen_prep`), y deja ejecutables las vistas de `lumen_mart`.

> **Sin muestreo.** El pipeline trabaja con las 590,540 transacciones completas. El paso
> `muestreo` evalúa los criterios (volumen, clase desbalanceada, registros redundantes) y registra
> la decisión: el volumen cabe en la capacidad de cómputo y en la cuota gratuita de BigQuery, y
> solo 910 filas (0.15 %) tienen un posible duplicado. Balancear las clases (3.50 % de fraude) es
> una decisión del modelado y se haría solo dentro de la partición de entrenamiento.

## Datos reales y muestra

**Todo el análisis y el DW usan los datos reales completos, que viven en BigQuery.** El
repositorio no contiene datos de IEEE-CIS: las reglas de la competencia prohíben redistribuirlos.

La carpeta `data/sample/` solo sirve para ver el esquema y probar el código. Contiene:

| Archivo                                                                     | Fuente                          | Contenido                                                                                                       |
| :-------------------------------------------------------------------------- | :------------------------------ | :-------------------------------------------------------------------------------------------------------------- |
| `banxico_cf621_series.csv`                                                  | B · Banco de México, CF621      | Cuadro completo, tal como se exportó del SIE el 9 de octubre de 2026 (ISO-8859-1, 18 líneas de metadatos)       |
| `free_email_domains_1.13.0.json`                                            | D · `free-email-domains` 1.13.0 | Lista completa (licencia MIT)                                                                                   |
| `ulb_muestra.csv`                                                           | C · ULB                         | Muestra aleatoria simple de 1,000 filas con semilla fija (ODbL / DbCL)                                          |
| `ieee_sintetico_train_transaction.csv`, `ieee_sintetico_train_identity.csv` | A · IEEE-CIS                    | **Datos sintéticos**: mismas columnas y tipos, valores inventados con semilla fija. No son transacciones reales |

Los archivos de ULB y de IEEE-CIS sintético los genera `bootstrap/generar_muestras.py`
(`--ulb` lee staging en BigQuery; `--sintetico` no necesita Google Cloud). Con la misma semilla y
las versiones de `uv.lock` se obtienen los mismos archivos, byte por byte.

Las licencias y la forma de citar cada fuente están en `data/sample/LICENCIAS.md`.

## Requisitos

- [`uv`](https://docs.astral.sh/uv/) (en Arch Linux: `sudo pacman -S uv`). `uv` instala por su
  cuenta la versión exacta de Python del proyecto (**3.13.18**, fijada en `.python-version`), sin
  depender del Python del sistema.
- Google Cloud CLI (`gcloud`), para autenticarse (en Arch Linux, paquete `google-cloud-cli` de AUR).
- Acceso a un proyecto de Google Cloud con BigQuery.

Las versiones de todas las bibliotecas están fijadas en `uv.lock`. `requirements.txt` tiene las
mismas versiones, para quien prefiera `pip`.

## Instalación

Desde un clon limpio del repositorio:

```bash
git clone https://github.com/alangm-98/Proyecto_Mineria_Datos.git
cd Proyecto_Mineria_Datos/pipeline
uv sync --frozen        # crea .venv con Python 3.13.18 y las versiones exactas de uv.lock
```

Todos los comandos de este README se ejecutan desde la carpeta `pipeline/`.

## Autenticación

El pipeline usa las credenciales de aplicación por defecto (ADC) de la cuenta de Google de quien
lo ejecuta. **No se usa ninguna llave de cuenta de servicio** y no se guarda ninguna credencial en
el repositorio.

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project pagos-lumen-dw
```

El primer comando abre el navegador. En la pantalla de consentimiento basta con aceptar el
permiso de Google Cloud; los demás que ofrezca (por ejemplo, Cloud SQL) no hacen falta. Las
credenciales quedan en `~/.config/gcloud/`, fuera del repositorio. Para retirarlas al terminar:
`gcloud auth application-default revoke`.

### Permisos necesarios en el proyecto

| Rol                                                                | Para qué                                                                                     |
| :----------------------------------------------------------------- | :------------------------------------------------------------------------------------------- |
| BigQuery Job User (`roles/bigquery.jobUser`)                       | Ejecutar consultas                                                                           |
| BigQuery Data Editor (`roles/bigquery.dataEditor`)                 | Leer staging y crear o reemplazar tablas y vistas en `lumen_prep`, `lumen_dw` y `lumen_mart` |
| Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`) | Usar el proyecto como proyecto de cuota de las credenciales ADC                              |
| Storage Object Viewer (`roles/storage.objectViewer`)               | Solo para cargar staging desde Cloud Storage (bootstrap)                                     |

## Ejecución

```bash
uv run python run_pipeline.py --solo-verificar   # credenciales, datasets y tablas de staging
uv run python run_pipeline.py                    # pipeline completo
```

Los parámetros (proyecto, datasets, tablas, supuestos, semilla, umbrales) están en `config.yaml`.
Cada corrida deja un registro en `logs/` (no se sube al repositorio). Con `--desde` y `--hasta` se
ejecuta solo un tramo, por ejemplo `--desde calidad --hasta calidad`.

### Pasos

| Paso                | Qué hace                                                                                                                                                                                                                                                                                        | Escribe                                                                                                   | Duración y datos procesados (corridas del 7 y 8 nov 2026)                    |
| :------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------- |
| Verificación previa | Credenciales, ubicación de staging y filas de cada tabla contra la fuente                                                                                                                                                                                                                       | Nada                                                                                                      | ~3 s; solo metadatos                                                         |
| `ingesta`           | Une y tipa A, B y D sin limpiar (SQL de `sql/01` a `sql/03`); valida filas, llaves y fechas                                                                                                                                                                                                     | `lumen_prep.analitico_crudo`, `banxico_trimestres`, `dominios_lista`                                      | ~25 s; ~1.1 GB                                                               |
| `calidad`           | Diagnóstico sin corregir: faltantes, ceros, distintos y rango por columna; duplicados; valores de categóricas; dominios sin pareja; consistencia de Banxico                                                                                                                                     | `lumen_prep.calidad_*` y `salidas/calidad_*.csv`                                                          | ~3 min; ~2.3 GB                                                              |
| `limpieza`          | Mismas filas: correo normalizado, T/F a BOOL, marcas de posibles duplicados y de importes atípicos, `log_importe` y partición temporal; registro de cada tratamiento con su conteo                                                                                                              | `lumen_prep.analitico_limpio`, `registro_limpieza` y su CSV                                               | ~1.5 min; ~3.6 GB                                                            |
| `reduccion`         | Con la partición de entrenamiento: faltantes, valor dominante, χ² con V de Cramér, Spearman y PCA del bloque V; una decisión por columna                                                                                                                                                        | `lumen_prep.reduccion_decision`, vista `analitico_reducido`, `salidas/reduccion_*.csv`, figuras f12 y f13 | ~2.5 min; ~1.1 GB la primera vez (después usa el extracto local de `cache/`) |
| `muestreo`          | Mide los tres criterios del muestreo sobre `analitico_limpio` y registra la decisión; falla si un criterio lo justificara                                                                                                                                                                       | `lumen_prep.muestreo_decision` y su CSV                                                                   | ~5 s; ~5 MB                                                                  |
| `antes_despues`     | Mismas medidas clave sobre `analitico_crudo` y `analitico_reducido`; falla si cambia alguna que debía quedar igual                                                                                                                                                                              | `lumen_prep.antes_despues`, su CSV y figuras f14 y f15                                                    | ~20 s; ~1.9 GB                                                               |
| `carga`             | Crea el esquema estrella de E1 si no existe (`sql/06`) y comprueba que sea idéntico; llena las dimensiones de tipo 1 (`sql/07`), actualiza `dim_dominio_correo` con historia SCD 2 (`sql/08`) y llena los hechos (`sql/09`); 35 validaciones (grano, llaves huérfanas, totales, miembros de E1) | Las 7 tablas de `lumen_dw`; `lumen_prep.carga_validaciones` y su CSV                                      | ~65 s; ~0.1 GB                                                               |
| `datamart`          | Crea las vistas de E1 si no existen (`sql/10`), las consulta y cruza sus totales con el DW y el EDA                                                                                                                                                                                             | `salidas/mart_*.csv`                                                                                      | ~15 s; ~0.1 GB                                                               |

**Tiempo aproximado de una corrida completa:** unos 9 minutos y 10 GB procesados en BigQuery
(suma de las corridas por paso; dentro de la cuota gratuita de 1 TB al mes). Las corridas
siguientes son más rápidas porque la reducción reutiliza su extracto local.

La historia de `dim_dominio_correo` se prueba aparte, en un dataset temporal que se borra al
terminar: `uv run python pruebas/prueba_scd2.py` (escribe `salidas/prueba_scd2.csv`).

## Proyecto propio: cargar staging desde cero

Para ejecutar el pipeline en otro proyecto de Google Cloud:

1. Cambiar `proyecto.id` y `bootstrap.bucket` en `config.yaml`.
2. Aceptar las reglas de la competencia en Kaggle y descargar `train_transaction.csv` y
   `train_identity.csv` de <https://www.kaggle.com/competitions/ieee-fraud-detection/data>.
3. Crear un bucket en la ubicación US y subir los dos archivos:

   ```bash
   gcloud storage buckets create gs://MI-BUCKET --location=US
   gcloud storage cp train_transaction.csv train_identity.csv gs://MI-BUCKET/ieee/
   ```

4. Cargar staging. El esquema de cada tabla es explícito y está en `esquemas/`:

   ```bash
   uv run python bootstrap/cargar_staging.py --tablas ieee ulb banxico dominios --simular   # revisar
   uv run python bootstrap/cargar_staging.py --tablas ieee ulb banxico dominios
   ```

   A (IEEE-CIS) se lee del bucket; C (ULB) se copia de la tabla pública de BigQuery; B (Banco de
   México) y D (dominios) se cargan desde `data/sample/` con las mismas opciones que en E1. Se
   comprobó que B y D quedan idénticas, fila por fila, a las tablas de staging de E1.

El script no sobrescribe una tabla que ya existe, salvo con `--reemplazar`. Con `--dataset NOMBRE`
carga en otro dataset, para probar sin tocar staging.

## Estructura

```
pipeline/
├── run_pipeline.py        punto de entrada único
├── config.yaml            parámetros
├── pyproject.toml         dependencias directas (versiones exactas)
├── uv.lock                todas las dependencias, fijadas
├── requirements.txt       las mismas versiones, para pip
├── .python-version        3.13.18
├── src/                   módulos del pipeline: un archivo por paso, más config, registro, bq y verificacion
├── esquemas/              esquema explícito de las tablas de staging (A, B y D)
├── bootstrap/             carga de staging y generación de muestras (no forman parte del pipeline)
├── pruebas/               prueba de la historia SCD 2 de dim_dominio_correo (no forma parte del pipeline)
├── eda/                   análisis exploratorio (no forma parte del pipeline)
├── salidas/               diagnóstico agregado que escribe el pipeline (conteos, sin filas de datos)
└── data/sample/           muestra pequeña (ver «Datos reales y muestra»)
```

Las consultas SQL que ejecuta el pipeline están en `sql/`, en la raíz del repositorio.
