-- =====================================================================
-- Pagos Lumen · E2 · Paso «limpieza»: dataset analítico limpio de la fuente A
--
-- Mismas filas que analitico_crudo: no se elimina ninguna transacción.
--
--   Faltantes: no se imputa; el NULL se conserva. Si un método necesita
--     imputar, se ajusta con la partición de entrenamiento en «reduccion».
--   Duplicados: se conservan y se marcan en posible_duplicado.
--   Atípicos del importe: se marcan en importe_atipico con la regla del IQR
--     sobre ln(importe), con cuartiles de entrenamiento. El importe no cambia.
--   Negativos en las columnas D: se conservan (src/limpieza.py los cuenta).
--   Categorías: dominios de correo en minúsculas, sin espacios y con la tabla
--     de equivalencias de config.yaml; columnas T/F a BOOL.
--   Llaves de la unión transacción-identidad: las valida src/limpieza.py.
--
-- Los fragmentos entre signo de pesos y llaves que no son nombres (listas de
-- columnas, expresiones) los genera src/limpieza.py a partir del esquema de
-- analitico_crudo y de config.yaml; el SQL completo se guarda en
-- pipeline/logs/04_limpieza_analitico_generado.sql.
--
-- Idempotente: CREATE OR REPLACE TABLE. Costo: ~1 GB por corrida.
-- =====================================================================

CREATE OR REPLACE TABLE `${proyecto}.${prep}.${p_analitico_limpio}`
OPTIONS (
  description = 'Fuente A tras la limpieza de E2: mismas filas que ${p_analitico_crudo}; correo normalizado, columnas T/F como BOOL; marcas posible_duplicado e importe_atipico; log_importe; particion temporal. Creada por el paso limpieza del pipeline.'
)
AS
WITH
base AS (
  SELECT
    c.* REPLACE (
${reemplazos}
    ),
    ${expr_particion}                                                     AS particion,
    LN(c.TransactionAmt)                                                  AS log_importe,
    -- Huellas de la fila cruda, para encontrar registros repetidos (las mismas del paso calidad)
    FARM_FINGERPRINT(TO_JSON_STRING(STRUCT(${columnas_sin_id})))          AS _huella_sin_id,
    FARM_FINGERPRINT(TO_JSON_STRING(STRUCT(${columnas_sin_id_ni_tiempo}))) AS _huella_sin_tiempo
  FROM `${proyecto}.${prep}.${p_analitico_crudo}` AS c
),

-- Cuartiles de ln(importe) calculados solo con entrenamiento (sin fuga)
cuartiles AS (
  SELECT DISTINCT
    PERCENTILE_CONT(log_importe, 0.25) OVER () AS q1,
    PERCENTILE_CONT(log_importe, 0.75) OVER () AS q3
  FROM base
  WHERE particion = 'entrenamiento'
),

grupos AS (
  SELECT
    *,
    COUNT(*) OVER (PARTITION BY _huella_sin_id)     AS _n_sin_id,
    COUNT(*) OVER (PARTITION BY _huella_sin_tiempo) AS _n_sin_tiempo
  FROM base
)

SELECT
  g.* EXCEPT (_huella_sin_id, _huella_sin_tiempo, _n_sin_id, _n_sin_tiempo),
  -- Todas las filas de cada grupo repetido quedan marcadas (también la «primera»)
  CASE
    WHEN g._n_sin_id > 1     THEN 'exacto'      -- igual a otra salvo TransactionID
    WHEN g._n_sin_tiempo > 1 THEN 'sin_tiempo'  -- igual a otra salvo TransactionID y el tiempo
  END AS posible_duplicado,
  CASE
    WHEN g.log_importe < q.q1 - ${iqr_k} * (q.q3 - q.q1) THEN 'bajo'
    WHEN g.log_importe > q.q3 + ${iqr_k} * (q.q3 - q.q1) THEN 'alto'
  END AS importe_atipico
FROM grupos AS g
CROSS JOIN cuartiles AS q;
