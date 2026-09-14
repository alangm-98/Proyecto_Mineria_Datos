# Proyecto Integrador de Minería de Datos

**Sitio publicado:** https://alangm-98.github.io/Proyecto_Mineria_Datos/

Detección y priorización de fraude transaccional en una institución de fondos de pago electrónico.

---

## Integrantes

| Nombre completo                | Número de cuenta |
| :----------------------------- | :--------------- |
| Flores Juárez Luis Enrique     | 322278316        |
| García Morales Carlos Alan     | 315169724        |
| Rangel Salcedo Melanie Valeria | 322056958        |

---

## Datos del curso

|                             |                                 |
| :-------------------------- | :------------------------------ |
| **Asignatura**              | Almacenes y Minería de Datos    |
| **Institución**             | Facultad de Ciencias, UNAM      |
| **Profesora**               | Jessica Santizo Galicia         |
| **Ayudante de Teoría**      | Diego Antonio Villalba González |
| **Ayudante de Laboratorio** | Emma Alicia Jiménez Sánchez     |

---

## Descripción del proyecto

Una institución de fondos de pago electrónico pierde alrededor de 8.2 millones de pesos mensuales
por fraude en comercio electrónico. Su motor de reglas genera cerca de 900 alertas diarias, pero el
equipo de revisión manual solo alcanza a atender 300; las restantes se autorizan de forma
automática al cierre del día por falta de capacidad.

El problema no es detectar fraude, ya que el sistema detecta más de lo que la organización puede
atender, sino decidir qué revisar. Este proyecto construye un ordenamiento por riesgo para que las
revisiones diarias sean las que más pérdida evitan, sin aumentar los bloqueos a clientes legítimos
ni la carga del equipo.

El desarrollo sigue la metodología **CRISP-DM** y se construye de forma incremental a lo largo del
semestre.

| #   | Fase CRISP-DM            | Estado                        |
| :-- | :----------------------- | :---------------------------- |
| 1   | Comprensión del negocio  | Entrega E0, completada        |
| 2   | Comprensión de los datos | Pendiente                     |
| 3   | Preparación de los datos | Pendiente                     |
| 4   | Modelado                 | Pendiente                     |
| 5   | Evaluación               | Pendiente                     |
| 6   | Despliegue               | Integrada en el reporte final |

---

## Entrega E0: Comprensión del negocio

| Entregable                                   | Archivo                  |
| :------------------------------------------- | :----------------------- |
| Bitácora de la reunión con el stakeholder    | `bitacora.qmd`           |
| Business Understanding Canvas                | `canvas.qmd`             |
| Preguntas de investigación priorizadas       | `preguntas.qmd`          |
| Criterio de éxito                            | `criterio_exito.qmd`     |
| Supuestos y riesgos                          | `riesgos_supuestos.qmd`  |
| Uso de herramientas de IA                    | `uso_ia.qmd`             |
| Expediente de fuentes (material de respaldo) | `fuentes/expediente.qmd` |

Todos ubicados en `entregas/E0_comprension_negocio/`.

---

## Estructura del repositorio

```
.
├── index.qmd                        Portada del sitio
├── _quarto.yml                      Configuración de Quarto
├── styles.css                       Hoja de estilos
├── .nojekyll                        Requerido por GitHub Pages
├── docs/                            Sitio compilado, publicado por Pages
└── entregas/
    └── E0_comprension_negocio/
        ├── bitacora.qmd
        ├── canvas.qmd
        ├── preguntas.qmd
        ├── criterio_exito.qmd
        ├── riesgos_supuestos.qmd
        ├── uso_ia.qmd
        └── fuentes/
            └── expediente.qmd
```

---

## Compilación local

Requiere [Quarto](https://quarto.org/docs/get-started/) instalado.

```bash
quarto preview     # previsualización en vivo
quarto render      # compila el sitio hacia docs/
```

La publicación se realiza mediante GitHub Pages desde la rama `main`, carpeta `/docs`
(Settings → Pages).

---

## Nota sobre el caso

El stakeholder de este proyecto es **simulado**. La institución descrita no es real: es un caso
construido por el equipo a partir de fuentes públicas verificables sobre el fraude financiero en
México, el sector de tecnología financiera y su marco regulatorio.

Las fuentes se documentan en el expediente, donde cada ficha indica institución emisora, enlace y
fecha de consulta, y se distingue de forma explícita entre datos con sustento documental y
parámetros asumidos por el equipo. El uso de herramientas de IA se declara en la página
correspondiente del sitio.
