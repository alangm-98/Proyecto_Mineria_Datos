-- =====================================================================
-- Pagos Lumen · E2 · Paso «carga» (3 de 4): dim_dominio_correo, SCD tipo 2
--
-- La dimensión NO se vacía: conserva la historia de cada dominio.
--   1. Se clasifica cada dominio observado con la versión actual de la lista
--      de correo gratuito (es_gratuito).
--   2. Si la versión vigente de un dominio tiene otra clasificación, se cierra:
--      valido_hasta = día anterior a la carga de la lista nueva, es_actual = falso.
--   3. Todo dominio sin versión vigente (nuevo o recién cerrado) recibe una
--      versión nueva con llave propia, vigente desde la fecha de carga de la lista.
-- Si nada cambió, no se escribe nada: correrlo dos veces da el mismo resultado.
--
-- Parámetros que fija src/carga.py: ${dim} (la dimensión), ${lista} (tabla de
-- la lista con una columna «dominio») y ${fecha_lista} (fecha de carga de esa
-- versión). La prueba de SCD 2 usa este mismo archivo con una lista simulada.
-- =====================================================================

CREATE TEMP TABLE entrada AS
SELECT
  o.dominio,
  ARRAY_REVERSE(SPLIT(o.dominio, '.'))[SAFE_OFFSET(0)] AS terminacion,
  l.dominio IS NOT NULL AS es_gratuito
FROM (
  SELECT DISTINCT P_emaildomain AS dominio
  FROM `${proyecto}.${prep}.${p_analitico_limpio}`
  WHERE P_emaildomain IS NOT NULL
) AS o
LEFT JOIN (SELECT DISTINCT dominio FROM `${lista}`) AS l USING (dominio);

-- Miembro 0 (sin dato), solo la primera vez
INSERT INTO `${dim}`
  (dominio_correo_key, dominio, terminacion, es_gratuito, valido_desde, valido_hasta, es_actual)
SELECT 0, CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS BOOL),
       DATE '${fecha_lista}', DATE '9999-12-31', TRUE
FROM (SELECT 1)
WHERE NOT EXISTS (SELECT 1 FROM `${dim}` WHERE dominio_correo_key = 0);

-- Cerrar versiones vigentes cuya clasificación cambió con la lista nueva
UPDATE `${dim}` AS d
SET valido_hasta = DATE_SUB(DATE '${fecha_lista}', INTERVAL 1 DAY),
    es_actual = FALSE
FROM entrada AS e
WHERE d.dominio = e.dominio
  AND d.es_actual
  AND d.es_gratuito IS DISTINCT FROM e.es_gratuito
  AND d.valido_desde < DATE '${fecha_lista}';

-- Versión nueva para cada dominio sin versión vigente
INSERT INTO `${dim}`
  (dominio_correo_key, dominio, terminacion, es_gratuito, valido_desde, valido_hasta, es_actual)
SELECT
  (SELECT IFNULL(MAX(dominio_correo_key), 0) FROM `${dim}`) + ROW_NUMBER() OVER (ORDER BY e.dominio),
  e.dominio,
  e.terminacion,
  e.es_gratuito,
  DATE '${fecha_lista}',
  DATE '9999-12-31',
  TRUE
FROM entrada AS e
WHERE NOT EXISTS (
  SELECT 1 FROM `${dim}` AS d WHERE d.dominio = e.dominio AND d.es_actual
);
