-- =====================================================================
-- Pagos Lumen · E2 · Paso «ingesta» (2 de 3): fuente B, Banco de México CF621
--
-- Lo mínimo para poder leer la tabla, sin cambiar ningún valor:
--   1. La fecha llega como texto día/mes/año. Se convierte con un formato
--      explícito (PARSE_DATE '%d/%m/%Y'), porque la detección automática de
--      BigQuery la lee como mes/día/año sin marcar error (hallazgo de E1).
--      Si alguna fecha no tuviera ese formato, la consulta falla en lugar de
--      producir una fecha equivocada.
--   2. Las series se renombran: de su identificador SF... a un nombre legible.
--      El identificador queda en la descripción de cada columna (abajo).
--   3. Se excluye la fila vacía del final del archivo exportado. El paso
--      registra cuántas filas se excluyeron.
--
-- Una fila por trimestre (45). El paso a una fila por trimestre y tipo de
-- tarjeta, que es el grano de hechos_pagos_trimestre, se hace en la carga.
--
-- Diccionario de series (encabezados del CSV del SIE):
--   SF273475 / SF273476  autorizaciones totales: número / monto (mdp)
--   SF273477 / SF273478  autorizaciones con crédito: número / monto (mdp)
--   SF273479 / SF273480  autorizaciones con débito: número / monto (mdp)
--   SF273481 a SF273486  % de aceptación (número, monto): total, crédito, débito
--   SF273487 a SF273492  % de contracargos (número, monto): total, crédito, débito
--   SF273493 a SF273498  % de devoluciones (número, monto): total, crédito, débito
-- =====================================================================

CREATE OR REPLACE TABLE `${proyecto}.${prep}.${p_banxico_trimestres}`
OPTIONS (
  description = 'Fuente B: Banco de México, cuadro CF621, una fila por trimestre (ene-mar 2015 a ene-mar 2026). Fecha convertida con formato explícito día/mes/año; series renombradas; sin la fila vacía final. Montos en millones de pesos; porcentajes ya calculados por Banxico (no aditivos). Creada por el paso ingesta del pipeline.'
)
AS
SELECT
  PARSE_DATE('%d/%m/%Y', TRIM(Fecha))   AS fecha_inicio_trimestre,

  SF273475 AS aut_num_total,
  SF273476 AS aut_mdp_total,
  SF273477 AS aut_num_credito,
  SF273478 AS aut_mdp_credito,
  SF273479 AS aut_num_debito,
  SF273480 AS aut_mdp_debito,

  SF273481 AS pct_acept_num_total,
  SF273482 AS pct_acept_monto_total,
  SF273483 AS pct_acept_num_credito,
  SF273484 AS pct_acept_monto_credito,
  SF273485 AS pct_acept_num_debito,
  SF273486 AS pct_acept_monto_debito,

  SF273487 AS pct_contracargo_num_total,
  SF273488 AS pct_contracargo_monto_total,
  SF273489 AS pct_contracargo_num_credito,
  SF273490 AS pct_contracargo_monto_credito,
  SF273491 AS pct_contracargo_num_debito,
  SF273492 AS pct_contracargo_monto_debito,

  SF273493 AS pct_devol_num_total,
  SF273494 AS pct_devol_monto_total,
  SF273495 AS pct_devol_num_credito,
  SF273496 AS pct_devol_monto_credito,
  SF273497 AS pct_devol_num_debito,
  SF273498 AS pct_devol_monto_debito
FROM `${proyecto}.${staging}.${t_banxico}`
WHERE Fecha IS NOT NULL AND TRIM(Fecha) != '';
