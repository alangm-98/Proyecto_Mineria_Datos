-- =====================================================================
-- Pagos Lumen · E2 · Paso «ingesta» (1 de 3): dataset analítico de la fuente A
--
-- Une transacciones e identidad al grano declarado en E1: una fila por
-- transacción con tarjeta en comercio electrónico. No limpia ni imputa
-- nada: el EDA se hace sobre los datos crudos (PDF de E2, «Datos de
-- partida»). Solo agrega cuatro columnas para poder leer el tiempo.
--
-- LEFT JOIN: conserva las 446,307 transacciones sin registro de identidad.
-- Esa ausencia es el objeto de P3 y no puede perderse en la unión.
--
-- Se leen todas las columnas de staging (t.*, i.*) a propósito: el dataset
-- analítico debe contener las 434 variables de la fuente para que el EDA y
-- la reducción decidan sobre cada una. Costo: ~1 GB por corrida.
--
-- Idempotente: CREATE SCHEMA IF NOT EXISTS y CREATE OR REPLACE TABLE.
-- Los nombres entre signo de pesos y llaves vienen de config.yaml (src/bq.py).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS `${proyecto}.${prep}`
OPTIONS (
  location = '${ubicacion}',
  description = 'Capa de preparación de E2: dataset analítico, tablas intermedias y diagnóstico. La crea pipeline/run_pipeline.py.'
);

CREATE OR REPLACE TABLE `${proyecto}.${prep}.${p_analitico_crudo}`
OPTIONS (
  description = 'Fuente A unida al grano de E1 (una fila por transacción), sin limpiar. Entrada del EDA de E2. Columnas derivadas: dia_relativo, fecha (supuesto: referencia ${fecha_referencia_ieee}), hora, tiene_identidad. Creada por el paso ingesta del pipeline.'
)
AS
SELECT
  t.*,
  i.* EXCEPT (TransactionID),

  -- Columnas derivadas, solo para leer el tiempo y la unión
  i.TransactionID IS NOT NULL                                  AS tiene_identidad,
  DIV(t.TransactionDT, 86400)                                  AS dia_relativo,  -- 1 a 182
  DATE_ADD(DATE '${fecha_referencia_ieee}',
           INTERVAL DIV(t.TransactionDT, 86400) DAY)           AS fecha,         -- depende del supuesto
  MOD(DIV(t.TransactionDT, 3600), 24)                          AS hora           -- no depende del día de referencia elegido
FROM `${proyecto}.${staging}.${t_ieee_transaccion}` AS t
LEFT JOIN `${proyecto}.${staging}.${t_ieee_identidad}` AS i
  ON i.TransactionID = t.TransactionID;
