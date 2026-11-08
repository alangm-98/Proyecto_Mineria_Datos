-- =====================================================================
-- Pagos Lumen · E2 · Paso «ingesta» (3 de 3): fuente D, free-email-domains
--
-- En staging, cada fila es una línea cruda del archivo domains.json:
--   [               <- apertura del arreglo
--     "0-mail.com", <- un dominio entre comillas, con coma
--     ...
--     "zzz...com"   <- el último, sin coma
--   ]               <- cierre del arreglo
--
-- Lo mínimo para leerla: extraer el texto entre comillas. Las dos líneas
-- de corchetes no tienen dominio y quedan fuera; el paso verifica que sean
-- exactamente esas dos. No se cambia ningún dominio (ni mayúsculas ni
-- espacios): normalizar es una decisión de la fase B.
--
-- Nota: en las expresiones regulares, el signo de pesos de fin de línea va
-- doble porque el pipeline usa ese signo para sus parámetros; la plantilla
-- lo convierte en uno solo antes de enviar la consulta.
-- =====================================================================

CREATE OR REPLACE TABLE `${proyecto}.${prep}.${p_dominios_lista}`
OPTIONS (
  description = 'Fuente D: free-email-domains versión ${dominios_version}, cargada el ${dominios_fecha_carga}. Una fila por dominio, extraído de la línea cruda de staging. Creada por el paso ingesta del pipeline.'
)
AS
SELECT
  REGEXP_EXTRACT(linea, r'^\s*"([^"]+)"\s*,?\s*$$') AS dominio,
  '${dominios_version}'                            AS version_lista,
  DATE '${dominios_fecha_carga}'                   AS fecha_carga
FROM `${proyecto}.${staging}.${t_dominios}`
WHERE REGEXP_CONTAINS(linea, r'^\s*"[^"]+"\s*,?\s*$$');
