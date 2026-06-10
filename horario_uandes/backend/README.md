# Backend — Generador de Horarios UANDES

Documentación técnica del backend, basada en el **código actual** (no en el PRD/CONTEXT).
Describe cómo se procesan los datos, qué restricciones duras están realmente activas en
CP-SAT, qué restricciones blandas evalúa el GA, y las limitaciones conocidas.

Pipeline general:

```
parser.py  →  solver_cpsat.py  →  solver_ga.py  →  exporter.py / reporter.py
(datos)       (factibilidad)      (optimización)    (Excel / reporte)
```

---

## 1. Flujo de datos (`parser.py`)

### 1.1 Archivos de entrada

| Archivo | Hojas usadas |
|---------|--------------|
| `Maestro_XXXXXX.xlsx` | `MAESTRO`, `PROFESORES`, `RESPUESTAS`, `DisponibilidadesFueraForms` |
| `SALAS_ESPECIALES_ING.xlsx` | `BBDD`, `SALAS ESPECIALES` |

El Maestro se localiza con `glob("[Mm]aestro*.xlsx")` y se usa el primero en orden
alfabético. Las columnas se mapean **por nombre** (no por posición), con normalización
sin acentos/mayúsculas (`_mapear_columnas`), de modo que el parser tolera reordenamientos
o cambios de capitalización de columnas.

### 1.2 Hoja MAESTRO → secciones

Solo se procesan las filas con **`CURSO MANDANTE` = "SI"**. Por cada fila:

| Dato | Columna(s) del Maestro | Transformación |
|------|------------------------|----------------|
| Código de curso | `CODIGO` | string |
| Sección | `SECCIONES` | `1.0` → `"1"`, letras tal cual |
| Plan de estudio | `PLAN DE ESTUDIO` | usado para acumular semestres |
| Semestre malla | `Plan Común`, o `ICI/IOC/ICE/ICC/ICA` | si `Plan Común` tiene valor se usa **solo** esa; si no, las de carrera. Se preservan sufijos de mención ("9a") |
| Horas a programar | `Clases A PROGRAMAR`, `Ayudantías PROGRAMAR`, `Laboratorios o Talleres PROGRAMAR` | enteros (se usan estas, **no** las regulares) |
| Distribución | `2+1 o 3?` | `"3"/"3-juntas"` → 1 bloque; resto → `ceil(horas/2)` |
| Profesor cátedra | `RUT PROFESOR 1` | normalizado (sin puntos/espacios) |
| Profesor lab | `RUT PROFESOR LABT` | si existe |

**Creación de secciones** (una `Seccion` por componente con horas > 0):

- **CLAS** si `Clases A PROGRAMAR > 0` → profesor = `RUT PROFESOR 1`, `afecta_disponibilidad=True` (si hay RUT).
- **AYUD** si `Ayudantías PROGRAMAR > 0` → profesor nominal = `RUT PROFESOR 1` (solo display), `afecta_disponibilidad=False` (la dicta un TA).
- **LABT** si `Laboratorios o Talleres PROGRAMAR > 0`:
  - Si hay `RUT PROFESOR LABT` → ese profesor, `afecta_disponibilidad=True`.
  - Si **no** hay profesor de lab → profesor = `RUT PROFESOR 1` solo como referencia, `afecta_disponibilidad=False` (se asume TA).

**Cálculo de bloques necesarios:** `ceil(horas/2)` (bloques de 2h), o `1` para distribución
"3"/"3-juntas". Un mismo curso en varias filas (distintos planes) **acumula semestres**
(unión de sets); las secciones se crean una sola vez por `(codigo, seccion, componente)`.

### 1.3 Tipo de profesor y disponibilidad

> **Las columnas LUNES-VIERNES del Maestro NO se usan** (no son confiables: no coinciden
> con el formulario real). La disponibilidad se lee de tres fuentes:

| Fuente | Tipo | Disponibilidad resultante |
|--------|------|---------------------------|
| Hoja `PROFESORES` (41 filas) | **JORNADA** | **Total** (`disponibilidad = set()` → sin restricción) |
| Hoja `RESPUESTAS` (formulario) | HONORARIO | Bloques declarados |
| Hoja `DisponibilidadesFueraForms` | HONORARIO sin formulario | Bloques cargados a mano |
| (sin datos en ninguna) | HONORARIO | Total + aviso |

- Un RUT que aparece en `PROFESORES` ⇒ JORNADA; el resto ⇒ HONORARIO.
- `RESPUESTAS`: una fila por `(profe, día, franja de 50 min)`. Día en español
  ("Lunes"…"Viernes", con acento) → `L/M/X/J/V`. Franja `"8:30-9:20"` → minuto de inicio.
- Conversión franja → bloque (`_subblocks_a_bloques`): un bloque está disponible
  **solo si el profesor declaró TODOS sus sub-bloques** de 50 min (debe estar libre el
  bloque completo).

### 1.4 Hoja de salas

- `BBDD`: `CODIGO` → `SALA ESPECIAL` (formato `"NOMBRE EN HORARIO DE CONTEXTO"`).
  Se descartan los contextos `PRUEBA` y `AYUDANTIA`. El nombre se **canonicaliza**
  (`_canon_sala`: `"LABORATORIO DE COMPUTACION"` → `"LABT COMPUTACION"`) para que calce
  con la hoja de inventario.
- `SALAS ESPECIALES`: cuenta cuántas salas físicas hay de cada `TIPO`
  (`capacidad_por_sala`, ej. `LABT COMPUTACION → 4`).

### 1.5 Estructura de salida (`models.py`)

```
DatosProblema
├── cursos:     {codigo: Curso}
├── secciones:  [Seccion]
├── profesores: {rut: Profesor}
└── capacidad_por_sala: {nombre_sala: n_salas_físicas}

Curso(codigo, titulo, semestres_por_carrera {carrera: {sem}}, planes,
      clases_horas, ayudantias_horas, laboratorios_horas, sala_especial)

Seccion(id="{codigo}-{seccion}-{componente}", codigo_curso, seccion, componente,
        rut_profesor, afecta_disponibilidad, cantidad_bloques_necesarios)

Profesor(rut, nombre, tipo {JORNADA|HONORARIO}, disponibilidad: set[bloque_idx])
```

### 1.6 Catálogo de bloques (`blocks.py`)

95 bloques = **19 tipos × 5 días**. Cada bloque tiene `sub_bloques` (slots de 50 min).
Dos bloques **se solapan** si son del mismo día y comparten ≥1 sub-bloque
(`MATRIZ_SOLAPAMIENTO`), **no** por igualdad de índice.

- **7 tipos estándar** (`es_estandar=True`): 5 de 2h (8:30, 10:30, 13:30, 15:30, 17:30)
  + 2 de 3h (10:30-13:20, 12:30-15:20). Es la grilla institucional preferida.
- **12 tipos "helper"** (`es_estandar=False`): rellenan los huecos (inicios 9:30, 11:30,
  12:30, 14:30, 16:30 y 3h de mañana/tarde/noche) para que cualquier disponibilidad sea
  representable. Se usan **solo como último recurso** (ver objetivo del solver).

---

## 2. Restricciones DURAS — activas en `solver_cpsat.py`

El modelo es **a nivel de sección**: cada sección tiene su(s) variable(s) de bloque, con
dominio = sus bloques disponibles. El solver **decide el paralelismo por sí mismo**: para
que todos los ramos de un semestre quepan sin topes, pone en paralelo las secciones de un
mismo curso donde la disponibilidad lo permite. No hay agrupación previa.

| ID | Qué verifica | Estado / detalle |
|----|--------------|------------------|
| **RD2 — Disponibilidad de profesor** | Cada sección solo puede ir en bloques donde su profesor está disponible. | **Activa y dura.** Implementada como el **dominio** de cada variable (`disponibilidad_seccion`). JORNADA = todos los bloques estándar; HONORARIO = sus bloques declarados. **Se respeta por completo**: si no hay bloque válido, el modelo es INFEASIBLE. |
| **Intra-sección** | Los bloques de una misma sección no se solapan entre sí. | Activa. |
| **NRC — Componentes de la misma sección** | CLAS-k, AYUD-k y LABT-k de la **misma sección** (mismo NRC) no se solapan (el alumno asiste a los tres). | Activa. Se agrupa por `(codigo, seccion)`. |
| **RD1 — Sin topes de malla** | Secciones de **cursos distintos** del mismo `(carrera, semestre)` no se solapan. | Activa y dura. Secciones del **mismo** curso quedan exentas (pueden ir paralelas). |
| **RD3 — Unicidad de profesor** | Un profesor con `afecta_disponibilidad=True` no dicta dos secciones a la vez, **en cualquier rol** y curso. | Activa. Incluye: dos LABT del mismo curso con la misma profesora; un profesor que dicta LABT de un curso y CLAS de otro. **El profesor de laboratorio se trata como persona distinta** del de cátedra (cada sección usa su profesor real). AYUD no entra (la dicta un TA). |
| **RD4 — Capacidad de salas especiales** | En cada instante (sub-bloque), la cantidad de secciones que usan un mismo tipo de sala no supera las salas físicas disponibles. | Activa. **Capacidad = 1** → ningún par puede solaparse (incluye mismo curso). **Capacidad > 1** → suma por sub-bloque ≤ capacidad (ej. LABT COMPUTACION: hasta 4 en paralelo). Se cuenta por **sub-bloque**, así que bloques distintos que se solapan (ej. 10:30-13:20 y 12:30-15:20) también compiten por la sala. AYUD excluida. |
| **RD7 — Ayudantías desde 12:30** | Los bloques de AYUD inician a las 12:30 o después. | Activa, implementada en el **dominio** de las secciones AYUD. |

**Objetivo de optimización del CP-SAT:** minimizar el uso de bloques **helper**
(no estándar). Las secciones sin datos de disponibilidad quedan restringidas a la grilla
estándar; las que sí tienen disponibilidad pueden usar helpers, pero solo cuando su
disponibilidad lo obliga.

**Verificación independiente** (`verificar_topes`, `verificar_rd3`, `verificar_rd4`,
`verificar_intra`): re-chequean la solución. En la corrida completa (299 secciones,
7 carreras) el resultado es `topes=0, RD3=0, RD4=0, intra=0`.

### Resumen de las preguntas concretas

- **¿Se respeta por completo la disponibilidad de los profesores?**
  Sí, es restricción **dura** (RD2). JORNADA = disponibilidad total; HONORARIO = su
  formulario. Si los datos hacen el problema imposible, el solver devuelve INFEASIBLE
  (no relaja la disponibilidad).
- **¿Se verifica que los LABT no topen por espacio físico?**
  Sí (RD4), por capacidad de salas y **por sub-bloque**. Con 1 sala física no pueden
  coincidir; con N salas, hasta N en paralelo.
- **¿El profesor de laboratorio se considera distinto al de cátedra?**
  Sí. Cada sección guarda su profesor real (`RUT PROFESOR LABT` para LABT, `RUT PROFESOR 1`
  para CLAS), y RD3 los trata por separado. Si el LABT no tiene profesor propio, se asume
  TA y no genera restricción de disponibilidad.

---

## 3. Restricciones BLANDAS — `solver_ga.py`

El GA parte de la solución factible de CP-SAT y optimiza el siguiente fitness
(penalización, **menor es mejor**). Mantiene todas las restricciones duras: el grafo de
conflictos codifica RD1/RD3/RD4/NRC y cada mutación verifica factibilidad; el dominio de
cada sección respeta RD2.

| ID | Peso | Qué penaliza |
|----|------|--------------|
| **RB1** | 100 | Labs de Programación (`ING1103`-LABT) cuyos bloques no son del mismo día y consecutivos. |
| **RB2** | 80 | Profesor JORNADA asignado a un bloque extremo (inicio 8:30 ó 17:30). Solo cuenta si la sección `afecta_disponibilidad` (no penaliza secciones de TA). |
| **RB3** | 50 | Componentes distintos del mismo curso (CLAS/AYUD/LABT) que comparten día. |
| **RB4** | 50 | Más de un bloque del mismo componente/sección en el mismo día. |
| **RB5** | 60 | Bloques que difieren del histórico de semestres anteriores (`inputs/historico/`). |
| **Helper** | 40 (`PESO_BLOQUE_HELPER`) | Cada bloque helper (fuera de la grilla estándar) usado. |

Parámetros por defecto de `ejecutar_ga`: `n_generaciones=200`, `pop_size=40`, `cxpb=0.5`,
`mutpb=0.4`, `seed=42`.

---

## 4. Limitaciones conocidas (lo que NO se verifica)

1. **Distribución "2+1"**: se trata como 2h (`ceil(horas/2)`). No se modela el bloque
   adicional de 1h.

2. **Bloques de 3h no se fuerzan a slots de 3h (RD6 no implementada).** Un curso
   "3-juntas" necesita 1 bloque, pero ese bloque puede caer en cualquier slot del dominio
   (incluido uno de 2h). No hay restricción que lo obligue a un bloque tipo "3h"
   (10:30-13:20 / 12:30-15:20).

3. **Días distintos para secciones multi-bloque: no es restricción dura.** El intra-sección
   solo prohíbe **solapamiento**. Dos bloques de la misma sección en el mismo día pero sin
   solaparse (ej. 8:30 y 10:30) están permitidos por CP-SAT; el GA lo **desalienta** vía
   RB4 (blanda), pero no lo prohíbe.

4. **Honorarios sin datos de disponibilidad** (ni en RESPUESTAS ni en FueraForms) se asumen
   con **disponibilidad total**. Si en realidad tienen restricciones, no se respetan.

5. **Salas con nombre desconocido** (un nombre en BBDD que no calza con ningún TIPO del
   inventario, ni siquiera tras canonicalizar) se tratan como **capacidad 1** (conservador).

6. **RD4 en el GA es una aproximación binaria.** El CP-SAT modela la capacidad exacta por
   sub-bloque, pero el grafo de conflictos del GA solo conecta pares (para capacidad > 1
   conecta cursos distintos). La factibilidad de capacidad la garantiza el punto de partida
   de CP-SAT; un movimiento del GA podría, en teoría, exceder capacidad entre secciones del
   mismo curso (el `reporter` lo señalaría).

7. **Disponibilidad estricta a nivel de bloque completo.** Un bloque se considera disponible
   solo si el profesor declaró **todos** sus sub-bloques. Una declaración parcial no habilita
   el bloque.

8. **AYUD restringida a la grilla estándar desde 12:30**, sin considerar disponibilidad de
   profesor (se asume TA). El RUT del profesor 1 se guarda solo para mostrar en el Excel.

9. **Cursos sin semestre en malla** (ningún valor en Plan Común ni carreras) no participan
   de RD1 (no generan topes), pero sí del resto de restricciones.

10. **Selección del Maestro**: si hay varios `Maestro*.xlsx` en `inputs/`, se usa el primero
    alfabéticamente (con aviso). No se valida que sea el "correcto".