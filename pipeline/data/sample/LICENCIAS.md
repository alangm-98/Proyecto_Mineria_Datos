# Licencias de los archivos de esta carpeta

Esta carpeta contiene copias completas de dos fuentes cuya licencia permite redistribuirlas (B y
D), una muestra de una tercera (C) y un archivo sintético con el esquema de la cuarta (A). No
contiene datos reales de IEEE-CIS (fuente A): sus reglas prohíben redistribuirlos.

## IEEE-CIS sintético (`ieee_sintetico_train_transaction.csv`, `ieee_sintetico_train_identity.csv`)

**No son datos de la fuente.** Tienen las mismas columnas y tipos que `train_transaction.csv` y
`train_identity.csv` de la competencia IEEE-CIS Fraud Detection, pero todos los valores los
genera `pipeline/bootstrap/generar_muestras.py --sintetico` con números aleatorios y semilla
fija. Sirven para ver el esquema y probar código. Los datos reales se descargan de Kaggle
aceptando las reglas de la competencia (ver `pipeline/README.md`).

## ULB Credit Card Fraud (`ulb_muestra.csv`)

Muestra aleatoria simple de 1,000 filas, con semilla fija, de la tabla pública
`bigquery-public-data.ml_datasets.ulb_fraud_detection` (Machine Learning Group, Université Libre
de Bruxelles, y Worldline). La genera `pipeline/bootstrap/generar_muestras.py --ulb`. Licencia:
Open Database License 1.0 para la base y Database Contents License 1.0 para los contenidos; esta
muestra se redistribuye bajo las mismas licencias. Se pide citar a Dal Pozzolo, Caelen, Johnson y
Bontempi (CIDM, IEEE, 2015).

## Banco de México · cuadro CF621 (`banxico_cf621_series.csv`)

Fuente: Banco de México, Sistema de Información Económica (SIE), cuadro CF621 «Operaciones en TPV
de Comercio Electrónico», <https://www.banxico.org.mx/SieInternet/>. Exportado el 9 de octubre de 2026. Banco de México autoriza reproducir o utilizar su información citando la fuente y la
dirección del sitio («Salvedad al uso de esta página»,
<https://www.banxico.org.mx/footer-es/salvedad-politicas-uso-banco-.html>). El archivo se
conserva tal como se exportó: codificación ISO-8859-1, fin de línea CRLF y 18 líneas de metadatos.

## free-email-domains 1.13.0 (`free_email_domains_1.13.0.json`)

Fuente: <https://github.com/Kikobeats/free-email-domains>, archivo `domains.json`, versión
1.13.0, descargado el 9 de octubre de 2026. Se redistribuye bajo la licencia MIT, cuyo texto
íntegro se reproduce a continuación como exige la propia licencia.

```text
The MIT License (MIT)

Copyright © 2017 Kiko Beats <josefrancisco.verdu@gmail.com> (kikobeats.com)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```
