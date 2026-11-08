-- =====================================================================
-- Pagos Lumen · E2 · Paso «reduccion»: vista con las columnas conservadas
--
-- La lista de columnas la genera src/reduccion.py a partir de la tabla de
-- decisión (lumen_prep.reduccion_decision). Es una vista: no copia datos y
-- siempre refleja la última versión de analitico_limpio.
-- =====================================================================

CREATE OR REPLACE VIEW `${proyecto}.${prep}.${p_analitico_reducido}`
OPTIONS (
  description = 'Columnas de ${p_analitico_limpio} que conserva el paso reduccion (ver ${p_reduccion_decision}). Creada por el pipeline.'
)
AS
SELECT
  ${columnas}
FROM `${proyecto}.${prep}.${p_analitico_limpio}`;
