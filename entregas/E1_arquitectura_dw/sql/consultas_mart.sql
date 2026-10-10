-- =====================================================================
-- Pagos Lumen · E1 · Capa DataMart
-- Consultas que responden las preguntas de E0 a partir del esquema estrella
-- Proyecto: pagos-lumen-dw      Dataset: lumen_mart      Ubicación: US
--
-- Cada consulta se guarda como vista en lumen_mart y lee solo de lumen_dw.
-- Las tablas del DW están vacías en esta entrega: las vistas son válidas,
-- pero todavía no devuelven filas.
--
-- P1 a P4 son las cuatro preguntas analíticas de E0 (preguntas.qmd).
--   P1  p1_tasa_por_segmento    GROUP BY CUBE y GROUPING
--   P2  p2_tramo_diario         funciones de ventana y GROUP BY ROLLUP
--   P2  p2_referencia_mexico    GROUP BY ROLLUP
--   P3  p3_identidad            GROUP BY ROLLUP
--   P4  sin consulta: ninguna fuente trae las operaciones rechazadas ni
--       su desenlace, y el esquema no tiene un hecho que las represente.
-- =====================================================================


-- ---------------------------------------------------------------------
-- P1. ¿Qué combinación de atributos separa mejor el fraude?
-- Tasa de fraude de cada combinación de producto, tipo de tarjeta,
-- dispositivo y correo gratuito, comparada con la tasa global.
-- CUBE calcula todas las combinaciones: cada atributo solo, por pares,
-- por tríos, los cuatro juntos y el total.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `pagos-lumen-dw.lumen_mart.p1_tasa_por_segmento`
OPTIONS (
  description = 'Tasa de fraude por combinación de producto, tipo de tarjeta, dispositivo y correo gratuito, y cuántas veces supera a la tasa global. Todos marca un subtotal. Responde: P1.'
) AS
WITH tasa_global AS (
  SELECT SAFE_DIVIDE(SUM(es_fraude), COUNT(*)) AS tasa
  FROM `pagos-lumen-dw.lumen_dw.hechos_transaccion`
)
SELECT
  IF(GROUPING(p.producto_cd) = 1, 'Todos', p.producto_cd) AS producto,
  IF(GROUPING(t.tipo_tarjeta) = 1, 'Todos', t.tipo_tarjeta) AS tipo_tarjeta,
  IF(GROUPING(d.tipo_dispositivo) = 1, 'Todos', d.tipo_dispositivo) AS dispositivo,
  CASE
    WHEN GROUPING(c.es_gratuito) = 1 THEN 'Todos'
    WHEN c.es_gratuito IS NULL THEN 'Sin dato'
    WHEN c.es_gratuito THEN 'Gratuito'
    ELSE 'No gratuito'
  END AS correo,
  COUNT(*) AS transacciones,
  SUM(h.es_fraude) AS fraudes,
  SAFE_DIVIDE(SUM(h.es_fraude), COUNT(*)) AS tasa_fraude,
  SAFE_DIVIDE(SAFE_DIVIDE(SUM(h.es_fraude), COUNT(*)), ANY_VALUE(g.tasa)) AS veces_tasa_global
FROM `pagos-lumen-dw.lumen_dw.hechos_transaccion` AS h
JOIN `pagos-lumen-dw.lumen_dw.dim_producto` AS p ON p.producto_key = h.producto_key
JOIN `pagos-lumen-dw.lumen_dw.dim_tipo_tarjeta` AS t ON t.tipo_tarjeta_key = h.tipo_tarjeta_key
JOIN `pagos-lumen-dw.lumen_dw.dim_dispositivo` AS d ON d.dispositivo_key = h.dispositivo_key
JOIN `pagos-lumen-dw.lumen_dw.dim_dominio_correo` AS c ON c.dominio_correo_key = h.dominio_correo_key
CROSS JOIN tasa_global AS g
GROUP BY CUBE (p.producto_cd, t.tipo_tarjeta, d.tipo_dispositivo, c.es_gratuito);


-- ---------------------------------------------------------------------
-- P2. ¿Qué fracción del monto defraudado cae en el 0.75 % de cada día?
-- Ordena las transacciones de cada día con una regla simple (la de mayor
-- importe primero), marca el 0.75 % superior y mide cuánto fraude contiene.
-- La regla es un marcador de posición: cuando exista el modelo, el ORDER BY
-- de la ventana se cambia por su puntaje y el resto queda igual.
-- La fila con fecha vacía es el total del periodo.
-- También sirve a P1: es la línea base de reglas simples.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `pagos-lumen-dw.lumen_mart.p2_tramo_diario`
OPTIONS (
  description = 'Por día: fraude y monto defraudado contenidos en el 0.75 % de transacciones mejor ordenadas con una regla simple (mayor importe primero), frente a lo esperado con un orden al azar. La fila sin fecha es el total. Responde: P1, P2.'
) AS
WITH ordenadas AS (
  SELECT
    fecha_key,
    es_fraude,
    monto_fraude_usd,
    ROW_NUMBER() OVER (PARTITION BY fecha_key ORDER BY monto_usd DESC, transaccion_id) AS posicion,
    COUNT(*) OVER (PARTITION BY fecha_key) AS transacciones_dia
  FROM `pagos-lumen-dw.lumen_dw.hechos_transaccion`
),
marcadas AS (
  SELECT
    fecha_key,
    es_fraude,
    monto_fraude_usd,
    posicion <= CEIL(0.0075 * transacciones_dia) AS en_tramo
  FROM ordenadas
)
SELECT
  f.fecha,
  COUNT(*) AS transacciones,
  COUNTIF(m.en_tramo) AS transacciones_en_tramo,
  SUM(m.es_fraude) AS fraudes,
  SUM(IF(m.en_tramo, m.es_fraude, 0)) AS fraudes_en_tramo,
  SUM(m.monto_fraude_usd) AS monto_fraude_usd,
  SUM(IF(m.en_tramo, m.monto_fraude_usd, 0)) AS monto_fraude_en_tramo_usd,
  SAFE_DIVIDE(SUM(IF(m.en_tramo, m.monto_fraude_usd, 0)), SUM(m.monto_fraude_usd)) AS fraccion_monto_en_tramo,
  SAFE_DIVIDE(COUNTIF(m.en_tramo), COUNT(*)) AS fraccion_esperada_al_azar
FROM marcadas AS m
JOIN `pagos-lumen-dw.lumen_dw.dim_fecha` AS f ON f.fecha_key = m.fecha_key
GROUP BY ROLLUP (f.fecha);


-- ---------------------------------------------------------------------
-- P2, referencia de México. ¿Cuánto pesan los contracargos por número y
-- por monto en el comercio electrónico mexicano?
-- Usa el segundo hecho y las dos dimensiones compartidas.
-- Los porcentajes no son aditivos: no se suman ni se promedian tal cual,
-- se ponderan por el número o el monto de autorizaciones.
-- ROLLUP agrega el subtotal de cada año y el total general.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `pagos-lumen-dw.lumen_mart.p2_referencia_mexico`
OPTIONS (
  description = 'Por año y tipo de tarjeta: autorizaciones, monto, compra promedio y porcentaje de contracargos por número y por monto en comercio electrónico en México (Banxico, CF621). Todos marca un subtotal. Responde: P2.'
) AS
SELECT
  IF(GROUPING(f.anio) = 1, 'Todos', CAST(f.anio AS STRING)) AS anio,
  IF(GROUPING(t.tipo_tarjeta) = 1, 'Todos', t.tipo_tarjeta) AS tipo_tarjeta,
  SUM(h.num_autorizaciones) AS num_autorizaciones,
  SUM(h.monto_autorizado_mdp) AS monto_autorizado_mdp,
  SAFE_DIVIDE(SUM(h.monto_autorizado_mdp) * 1000000, SUM(h.num_autorizaciones)) AS compra_promedio_mxn,
  SAFE_DIVIDE(SUM(h.pct_contracargo_num * h.num_autorizaciones), SUM(h.num_autorizaciones)) AS pct_contracargo_num,
  SAFE_DIVIDE(SUM(h.pct_contracargo_monto * h.monto_autorizado_mdp), SUM(h.monto_autorizado_mdp)) AS pct_contracargo_monto
FROM `pagos-lumen-dw.lumen_dw.hechos_pagos_trimestre` AS h
JOIN `pagos-lumen-dw.lumen_dw.dim_fecha` AS f ON f.fecha_key = h.fecha_key
JOIN `pagos-lumen-dw.lumen_dw.dim_tipo_tarjeta` AS t ON t.tipo_tarjeta_key = h.tipo_tarjeta_key
GROUP BY ROLLUP (f.anio, t.tipo_tarjeta);


-- ---------------------------------------------------------------------
-- P3. ¿La ausencia de identidad del dispositivo es una señal de riesgo?
-- Compara la tasa de fraude de las transacciones con y sin registro de
-- identidad, y dentro de las que lo tienen, por tipo de dispositivo.
-- ROLLUP agrega el subtotal de cada grupo y el total general.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `pagos-lumen-dw.lumen_mart.p3_identidad`
OPTIONS (
  description = 'Tasa de fraude, por número y por monto, de las transacciones con y sin registro de identidad, y por tipo de dispositivo. Todos y Todas marcan un subtotal. Responde: P3.'
) AS
SELECT
  IF(GROUPING(d.tiene_identidad) = 1, 'Todas', IF(d.tiene_identidad, 'Con identidad', 'Sin identidad')) AS registro_identidad,
  IF(GROUPING(d.tipo_dispositivo) = 1, 'Todos', d.tipo_dispositivo) AS dispositivo,
  COUNT(*) AS transacciones,
  SUM(h.es_fraude) AS fraudes,
  SAFE_DIVIDE(SUM(h.es_fraude), COUNT(*)) AS tasa_fraude,
  SUM(h.monto_fraude_usd) AS monto_fraude_usd,
  SAFE_DIVIDE(SUM(h.monto_fraude_usd), SUM(h.monto_usd)) AS tasa_fraude_monto
FROM `pagos-lumen-dw.lumen_dw.hechos_transaccion` AS h
JOIN `pagos-lumen-dw.lumen_dw.dim_dispositivo` AS d ON d.dispositivo_key = h.dispositivo_key
GROUP BY ROLLUP (d.tiene_identidad, d.tipo_dispositivo);
