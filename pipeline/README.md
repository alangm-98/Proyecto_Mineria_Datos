# Pipeline de E2 · Pagos Lumen

Pipeline reproducible de la entrega E2 (EDA y preparación de los datos). Lleva los datos crudos de
`lumen_staging` al esquema estrella de `lumen_dw`, pasando por una capa de preparación
(`lumen_prep`), y deja ejecutables las vistas de `lumen_mart`.

> **Estado: borrador de la fase 0.** Hoy el pipeline solo hace la verificación previa
> (credenciales y staging). Los pasos se agregan fase por fase y este README se completa al final,
> con el tiempo de ejecución medido.

## Datos reales y muestra

**Todo el análisis y el DW usan los datos reales completos, que viven en BigQuery.** El
repositorio no contiene datos de IEEE-CIS: las reglas de la competencia prohíben redistribuirlos.

La carpeta `data/sample/` solo sirve para ver el esquema y probar el código. Contiene:

| Archivo                          | Fuente                          | Contenido                                                                                                 |
| :------------------------------- | :------------------------------ | :-------------------------------------------------------------------------------------------------------- |
| `banxico_cf621_series.csv`       | B · Banco de México, CF621      | Cuadro completo, tal como se exportó del SIE el 9 de octubre de 2026 (ISO-8859-1, 18 líneas de metadatos) |
| `free_email_domains_1.13.0.json` | D · `free-email-domains` 1.13.0 | Lista completa (licencia MIT)                                                                             |
| (pendiente, fase A1)             | C · ULB                         | Muestra de filas (ODbL / DbCL)                                                                            |
| (pendiente, fase A1)             | A · IEEE-CIS                    | **Datos sintéticos** con el mismo esquema, generados con semilla fija. No son transacciones reales        |

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

```bash
cd pipeline
uv sync --frozen        # crea .venv con Python 3.13.18 y las versiones exactas de uv.lock
```

## Autenticación

El pipeline usa las credenciales de aplicación por defecto (ADC) de la cuenta de Google de quien
lo ejecuta. **No se usa ninguna llave de cuenta de servicio** y no se guarda ninguna credencial en
el repositorio.

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project pagos-lumen-dw
```

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
Cada corrida deja un registro en `logs/` (no se sube al repositorio).

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
   uv run python bootstrap/cargar_staging.py --tablas ieee ulb --simular   # revisar
   uv run python bootstrap/cargar_staging.py --tablas ieee ulb
   ```

   (Pendiente: carga de Banco de México y de la lista de dominios desde `data/sample/`.)

El script no sobrescribe una tabla que ya existe, salvo con `--reemplazar`.

## Estructura

```
pipeline/
├── run_pipeline.py        punto de entrada único
├── config.yaml            parámetros
├── pyproject.toml         dependencias directas (versiones exactas)
├── uv.lock                todas las dependencias, fijadas
├── requirements.txt       las mismas versiones, para pip
├── .python-version        3.13.18
├── src/                   módulos del pipeline
├── esquemas/              esquema explícito de las tablas de IEEE-CIS en staging
├── bootstrap/             carga de staging (no forma parte del pipeline)
└── data/sample/           muestra pequeña (ver «Datos reales y muestra»)
```

Las consultas SQL que ejecuta el pipeline están en `sql/`, en la raíz del repositorio.
