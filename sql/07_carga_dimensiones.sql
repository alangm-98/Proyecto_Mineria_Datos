-- =====================================================================
-- Pagos Lumen · E2 · Paso «carga» (2 de 4): dimensiones de tipo 1
--
-- Vacía y vuelve a llenar las cuatro dimensiones de SCD tipo 1, así que
-- correrlo dos veces da el mismo resultado. Los catálogos (llaves, nombres
-- y códigos) son los que define estrella.qmd de E1; el miembro 0 representa
-- el dato ausente en todas salvo dim_fecha.
-- =====================================================================

-- dim_fecha: un día por fila entre las fechas de config.yaml (sección dw).
-- dia_relativo_ieee es el único lugar donde vive el supuesto de fecha de E1.
TRUNCATE TABLE `${proyecto}.${dw}.dim_fecha`;
INSERT INTO `${proyecto}.${dw}.dim_fecha`
  (fecha_key, fecha, anio, trimestre, mes, nombre_mes, dia_mes, dia_relativo_ieee)
SELECT
  CAST(FORMAT_DATE('%Y%m%d', f) AS INT64),
  f,
  EXTRACT(YEAR FROM f),
  EXTRACT(QUARTER FROM f),
  EXTRACT(MONTH FROM f),
  ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
   'septiembre', 'octubre', 'noviembre', 'diciembre'][OFFSET(EXTRACT(MONTH FROM f) - 1)],
  EXTRACT(DAY FROM f),
  IF(DATE_DIFF(f, DATE '${fecha_referencia_ieee}', DAY) BETWEEN rango.desde AND rango.hasta,
     DATE_DIFF(f, DATE '${fecha_referencia_ieee}', DAY), NULL)
FROM UNNEST(GENERATE_DATE_ARRAY(DATE '${dw_fecha_inicio}', DATE '${dw_fecha_fin}')) AS f
CROSS JOIN (
  SELECT MIN(dia_relativo) AS desde, MAX(dia_relativo) AS hasta
  FROM `${proyecto}.${prep}.${p_analitico_limpio}`
) AS rango;

-- dim_tipo_tarjeta: une card6 de IEEE-CIS con la etiqueta de Banxico (E1)
TRUNCATE TABLE `${proyecto}.${dw}.dim_tipo_tarjeta`;
INSERT INTO `${proyecto}.${dw}.dim_tipo_tarjeta`
  (tipo_tarjeta_key, tipo_tarjeta, codigo_ieee, etiqueta_banxico)
VALUES
  (0, 'Desconocido', NULL, NULL),
  (1, 'Débito', 'debit', 'Débito'),
  (2, 'Crédito', 'credit', 'Crédito'),
  (3, 'Débito o crédito', 'debit or credit', NULL),
  (4, 'Tarjeta de cargo', 'charge card', NULL);

-- dim_producto: miembro 0 y un código por fila en orden alfabético
TRUNCATE TABLE `${proyecto}.${dw}.dim_producto`;
INSERT INTO `${proyecto}.${dw}.dim_producto` (producto_key, producto_cd, descripcion)
SELECT 0, CAST(NULL AS STRING), 'Desconocido'
UNION ALL
SELECT
  ROW_NUMBER() OVER (ORDER BY ProductCD),
  ProductCD,
  'Código enmascarado por Vesta; la fuente no publica su significado'
FROM (
  SELECT DISTINCT ProductCD
  FROM `${proyecto}.${prep}.${p_analitico_limpio}`
  WHERE ProductCD IS NOT NULL
);

-- dim_dispositivo: separa «sin registro de identidad» de «tipo no informado» (E1)
TRUNCATE TABLE `${proyecto}.${dw}.dim_dispositivo`;
INSERT INTO `${proyecto}.${dw}.dim_dispositivo`
  (dispositivo_key, tipo_dispositivo, codigo_ieee, tiene_identidad)
VALUES
  (0, 'Sin registro de identidad', NULL, FALSE),
  (1, 'Escritorio', 'desktop', TRUE),
  (2, 'Móvil', 'mobile', TRUE),
  (3, 'Tipo no informado', NULL, TRUE);
