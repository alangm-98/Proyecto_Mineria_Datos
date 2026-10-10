-- =====================================================================
-- Pagos Lumen · E1 · Capa DW
-- DDL del esquema estrella en BigQuery
-- Proyecto: pagos-lumen-dw      Dataset: lumen_dw      Ubicación: US
--
-- Dos tablas de hechos y cinco dimensiones. Las tablas se crean vacías;
-- poblarlas corresponde a la etapa de preparación de datos.
--
-- Orden de ejecución: primero las dimensiones y después los hechos,
-- porque las llaves foráneas apuntan a tablas que ya deben existir.
--
-- Las llaves primarias y foráneas llevan NOT ENFORCED: BigQuery las
-- registra como documentación del diseño, pero no las hace cumplir.
--
-- P1 a P4 son las cuatro preguntas analíticas de E0 (preguntas.qmd),
-- numeradas en su orden original.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. dim_fecha · compartida por los dos hechos · SCD tipo 1
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.dim_fecha` (
  fecha_key         INT64 NOT NULL OPTIONS (description = 'Llave sustituta con forma AAAAMMDD, por ejemplo 20180101'),
  fecha             DATE  NOT NULL OPTIONS (description = 'Día de calendario'),
  anio              INT64  OPTIONS (description = 'Año'),
  trimestre         INT64  OPTIONS (description = 'Trimestre del año, de 1 a 4'),
  mes               INT64  OPTIONS (description = 'Mes del año, de 1 a 12'),
  nombre_mes        STRING OPTIONS (description = 'Nombre del mes en español'),
  dia_mes           INT64  OPTIONS (description = 'Día del mes, de 1 a 31'),
  dia_relativo_ieee INT64  OPTIONS (description = 'Día relativo de IEEE-CIS (1 a 182) asignado a esta fecha bajo el supuesto; vacío fuera de esa ventana'),
  PRIMARY KEY (fecha_key) NOT ENFORCED
)
OPTIONS (
  description = 'Dimensión de fecha: una fila por día de calendario, del 1 de enero de 2015 al 31 de marzo de 2026. Compartida por hechos_transaccion y hechos_pagos_trimestre. SCD tipo 1. Supuesto: las fechas de IEEE-CIS se calculan tomando el 1 de diciembre de 2017 como referencia de TransactionDT; puede estar corrida un día, por eso no hay día de la semana. Responde: P1, P2.'
);


-- ---------------------------------------------------------------------
-- 2. dim_tipo_tarjeta · compartida por los dos hechos · SCD tipo 1
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.dim_tipo_tarjeta` (
  tipo_tarjeta_key INT64 NOT NULL OPTIONS (description = 'Llave sustituta; 0 es Desconocido'),
  tipo_tarjeta     STRING OPTIONS (description = 'Tipo de tarjeta en español: Débito, Crédito, Débito o crédito, Tarjeta de cargo, Desconocido'),
  codigo_ieee      STRING OPTIONS (description = 'Valor original de card6 en IEEE-CIS'),
  etiqueta_banxico STRING OPTIONS (description = 'Etiqueta del cuadro CF621 de Banxico (Crédito o Débito); vacía si Banxico no reporta ese tipo'),
  PRIMARY KEY (tipo_tarjeta_key) NOT ENFORCED
)
OPTIONS (
  description = 'Dimensión conformada de tipo de tarjeta: une card6 de IEEE-CIS con la separación de crédito y débito de Banxico. Compartida por hechos_transaccion y hechos_pagos_trimestre. SCD tipo 1. Responde: P1, P2.'
);


-- ---------------------------------------------------------------------
-- 3. dim_producto · SCD tipo 1
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.dim_producto` (
  producto_key INT64 NOT NULL OPTIONS (description = 'Llave sustituta; 0 es Desconocido'),
  producto_cd  STRING OPTIONS (description = 'Código original de ProductCD en IEEE-CIS: W, C, R, H o S'),
  descripcion  STRING OPTIONS (description = 'Descripción del código; la fuente lo publica enmascarado'),
  PRIMARY KEY (producto_key) NOT ENFORCED
)
OPTIONS (
  description = 'Dimensión de producto: una fila por código de producto de IEEE-CIS. Vesta enmascara el código y no publica su significado. SCD tipo 1. Responde: P1.'
);


-- ---------------------------------------------------------------------
-- 4. dim_dispositivo · SCD tipo 1
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.dim_dispositivo` (
  dispositivo_key  INT64 NOT NULL OPTIONS (description = 'Llave sustituta; 0 es Sin registro de identidad'),
  tipo_dispositivo STRING OPTIONS (description = 'Escritorio, Móvil, Tipo no informado o Sin registro de identidad'),
  codigo_ieee      STRING OPTIONS (description = 'Valor original de DeviceType en IEEE-CIS'),
  tiene_identidad  BOOL   OPTIONS (description = 'Verdadero si la transacción tiene fila en la tabla de identidad'),
  PRIMARY KEY (dispositivo_key) NOT ENFORCED
)
OPTIONS (
  description = 'Dimensión de dispositivo: separa la transacción sin registro de identidad de la que sí lo tiene pero no informa el tipo de dispositivo. SCD tipo 1. Responde: P1, P3.'
);


-- ---------------------------------------------------------------------
-- 5. dim_dominio_correo · SCD tipo 2
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.dim_dominio_correo` (
  dominio_correo_key INT64 NOT NULL OPTIONS (description = 'Llave sustituta; 0 es Sin dato. Cada versión de un dominio tiene su propia llave'),
  dominio            STRING OPTIONS (description = 'Dominio del correo del comprador, valor original de P_emaildomain'),
  terminacion        STRING OPTIONS (description = 'Último segmento del dominio, por ejemplo com, net o mx'),
  es_gratuito        BOOL   OPTIONS (description = 'Verdadero si el dominio está en la lista free-email-domains'),
  valido_desde       DATE   OPTIONS (description = 'Inicio de vigencia de esta versión'),
  valido_hasta       DATE   OPTIONS (description = 'Fin de vigencia; 9999-12-31 en la versión vigente'),
  es_actual          BOOL   OPTIONS (description = 'Verdadero en la versión vigente'),
  PRIMARY KEY (dominio_correo_key) NOT ENFORCED
)
OPTIONS (
  description = 'Dimensión de dominio de correo del comprador. Integra la lista free-email-domains en el atributo es_gratuito. SCD tipo 2: la lista se actualiza a diario y cada cambio crea una versión nueva sin borrar la anterior. Responde: P1.'
);


-- ---------------------------------------------------------------------
-- 6. hechos_transaccion · fuente: IEEE-CIS
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.hechos_transaccion` (
  transaccion_id     INT64 NOT NULL OPTIONS (description = 'Dimensión degenerada: TransactionID de IEEE-CIS'),
  fecha_key          INT64 NOT NULL OPTIONS (description = 'Llave a dim_fecha; se calcula de TransactionDT con el supuesto de fecha de referencia'),
  tipo_tarjeta_key   INT64 NOT NULL OPTIONS (description = 'Llave a dim_tipo_tarjeta; sale de card6'),
  producto_key       INT64 NOT NULL OPTIONS (description = 'Llave a dim_producto; sale de ProductCD'),
  dispositivo_key    INT64 NOT NULL OPTIONS (description = 'Llave a dim_dispositivo; sale de DeviceType y de la existencia de fila de identidad'),
  dominio_correo_key INT64 NOT NULL OPTIONS (description = 'Llave a dim_dominio_correo; sale de P_emaildomain'),
  segundo_relativo   INT64   OPTIONS (description = 'TransactionDT sin cambios: segundos desde una referencia que la fuente no publica. No aditiva'),
  monto_usd          NUMERIC OPTIONS (description = 'Importe de la transacción en dólares (TransactionAmt). Aditiva'),
  es_fraude          INT64   OPTIONS (description = 'Vale 1 si la transacción es fraude y 0 si no (isFraud). Aditiva: su suma es el número de fraudes'),
  monto_fraude_usd   NUMERIC OPTIONS (description = 'Importe defraudado: monto_usd por es_fraude. Aditiva'),
  PRIMARY KEY (transaccion_id) NOT ENFORCED,
  FOREIGN KEY (fecha_key)          REFERENCES `pagos-lumen-dw.lumen_dw.dim_fecha` (fecha_key) NOT ENFORCED,
  FOREIGN KEY (tipo_tarjeta_key)   REFERENCES `pagos-lumen-dw.lumen_dw.dim_tipo_tarjeta` (tipo_tarjeta_key) NOT ENFORCED,
  FOREIGN KEY (producto_key)       REFERENCES `pagos-lumen-dw.lumen_dw.dim_producto` (producto_key) NOT ENFORCED,
  FOREIGN KEY (dispositivo_key)    REFERENCES `pagos-lumen-dw.lumen_dw.dim_dispositivo` (dispositivo_key) NOT ENFORCED,
  FOREIGN KEY (dominio_correo_key) REFERENCES `pagos-lumen-dw.lumen_dw.dim_dominio_correo` (dominio_correo_key) NOT ENFORCED
)
OPTIONS (
  description = 'Grano: una fila por transacción con tarjeta en comercio electrónico. Fuente: IEEE-CIS Fraud Detection (Kaggle; datos de Vesta). Responde: P1, P2, P3.'
);


-- ---------------------------------------------------------------------
-- 7. hechos_pagos_trimestre · fuente: Banco de México, cuadro CF621
-- ---------------------------------------------------------------------
CREATE TABLE `pagos-lumen-dw.lumen_dw.hechos_pagos_trimestre` (
  fecha_key             INT64 NOT NULL OPTIONS (description = 'Llave a dim_fecha: primer día del trimestre'),
  tipo_tarjeta_key      INT64 NOT NULL OPTIONS (description = 'Llave a dim_tipo_tarjeta: crédito o débito'),
  num_autorizaciones    INT64   OPTIONS (description = 'Número de autorizaciones (series SF273477 crédito, SF273479 débito). Aditiva'),
  monto_autorizado_mdp  INT64   OPTIONS (description = 'Monto autorizado en millones de pesos (SF273478 crédito, SF273480 débito). Aditiva'),
  pct_aceptacion_num    FLOAT64 OPTIONS (description = 'Porcentaje de aceptación por número (SF273483 crédito, SF273485 débito). No aditiva'),
  pct_aceptacion_monto  FLOAT64 OPTIONS (description = 'Porcentaje de aceptación por monto (SF273484 crédito, SF273486 débito). No aditiva'),
  pct_contracargo_num   FLOAT64 OPTIONS (description = 'Porcentaje de contracargos por número (SF273489 crédito, SF273491 débito). No aditiva'),
  pct_contracargo_monto FLOAT64 OPTIONS (description = 'Porcentaje de contracargos por monto (SF273490 crédito, SF273492 débito). No aditiva'),
  PRIMARY KEY (fecha_key, tipo_tarjeta_key) NOT ENFORCED,
  FOREIGN KEY (fecha_key)        REFERENCES `pagos-lumen-dw.lumen_dw.dim_fecha` (fecha_key) NOT ENFORCED,
  FOREIGN KEY (tipo_tarjeta_key) REFERENCES `pagos-lumen-dw.lumen_dw.dim_tipo_tarjeta` (tipo_tarjeta_key) NOT ENFORCED
)
OPTIONS (
  description = 'Grano: una fila por trimestre y tipo de tarjeta. Fuente: Banco de México, SIE, cuadro CF621, operaciones con tarjeta en comercio electrónico. Sirve de referencia de México para P2; los porcentajes de aceptación dan contexto a P4, que no se cubre. Responde: P2.'
);
