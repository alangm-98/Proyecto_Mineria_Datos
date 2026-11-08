-- =====================================================================
-- Pagos Lumen · E2 · Paso «carga» (4 de 4): tablas de hechos
--
-- Vacía y vuelve a llenar los dos hechos con los datos preparados.
-- Las llaves se buscan en las dimensiones ya cargadas, con el dato ausente
-- emparejado con el miembro 0. Si un valor no tiene miembro en su
-- dimensión, la llave queda vacía y BigQuery rechaza la inserción por la
-- restricción NOT NULL: nada se asigna a «Desconocido» en silencio.
-- =====================================================================

-- hechos_transaccion: una fila por transacción (grano de E1), desde analitico_limpio
TRUNCATE TABLE `${proyecto}.${dw}.hechos_transaccion`;
INSERT INTO `${proyecto}.${dw}.hechos_transaccion`
  (transaccion_id, fecha_key, tipo_tarjeta_key, producto_key, dispositivo_key,
   dominio_correo_key, segundo_relativo, monto_usd, es_fraude, monto_fraude_usd)
SELECT
  a.TransactionID,
  CAST(FORMAT_DATE('%Y%m%d', a.fecha) AS INT64),
  t.tipo_tarjeta_key,
  p.producto_key,
  d.dispositivo_key,
  c.dominio_correo_key,
  a.TransactionDT,
  CAST(a.TransactionAmt AS NUMERIC),
  a.isFraud,
  CAST(a.TransactionAmt AS NUMERIC) * a.isFraud
FROM `${proyecto}.${prep}.${p_analitico_limpio}` AS a
LEFT JOIN `${proyecto}.${dw}.dim_tipo_tarjeta` AS t
  ON IFNULL(t.codigo_ieee, '') = IFNULL(a.card6, '')
LEFT JOIN `${proyecto}.${dw}.dim_producto` AS p
  ON IFNULL(p.producto_cd, '') = IFNULL(a.ProductCD, '')
LEFT JOIN `${proyecto}.${dw}.dim_dispositivo` AS d
  ON d.tiene_identidad = a.tiene_identidad
 AND IFNULL(d.codigo_ieee, '') = IFNULL(a.DeviceType, '')
LEFT JOIN `${proyecto}.${dw}.dim_dominio_correo` AS c
  ON IFNULL(c.dominio, '') = IFNULL(a.P_emaildomain, '')
 AND c.es_actual;

-- hechos_pagos_trimestre: una fila por trimestre y tipo de tarjeta (crédito y débito)
TRUNCATE TABLE `${proyecto}.${dw}.hechos_pagos_trimestre`;
INSERT INTO `${proyecto}.${dw}.hechos_pagos_trimestre`
  (fecha_key, tipo_tarjeta_key, num_autorizaciones, monto_autorizado_mdp,
   pct_aceptacion_num, pct_aceptacion_monto, pct_contracargo_num, pct_contracargo_monto)
SELECT
  CAST(FORMAT_DATE('%Y%m%d', b.fecha_inicio_trimestre) AS INT64),
  t.tipo_tarjeta_key,
  x.num,
  x.mdp,
  x.acept_num,
  x.acept_monto,
  x.contracargo_num,
  x.contracargo_monto
FROM `${proyecto}.${prep}.${p_banxico_trimestres}` AS b
CROSS JOIN UNNEST([
  STRUCT('Crédito' AS etiqueta, b.aut_num_credito AS num, b.aut_mdp_credito AS mdp,
         b.pct_acept_num_credito AS acept_num, b.pct_acept_monto_credito AS acept_monto,
         b.pct_contracargo_num_credito AS contracargo_num,
         b.pct_contracargo_monto_credito AS contracargo_monto),
  STRUCT('Débito', b.aut_num_debito, b.aut_mdp_debito,
         b.pct_acept_num_debito, b.pct_acept_monto_debito,
         b.pct_contracargo_num_debito, b.pct_contracargo_monto_debito)
]) AS x
JOIN `${proyecto}.${dw}.dim_tipo_tarjeta` AS t ON t.etiqueta_banxico = x.etiqueta;
