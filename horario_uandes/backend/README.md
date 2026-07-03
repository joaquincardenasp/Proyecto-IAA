# Backend — Generador de Horarios UANDES

Documentación técnica del backend, basada en el **código actual** (no en el PRD/CONTEXT).
Describe cómo se procesan los datos, qué restricciones duras están realmente activas en
CP-SAT, qué restricciones blandas evalúa el GA, y las limitaciones conocidas.

Pipeline general:

```
parser.py → solver_cpsat.py → solver_ga.py → exporter.py / reporter.py
(datos)     (factibilidad)     (optimización)  (Excel / reporte)
                  │
                  └─ si no hay horario completo:
                     resolver_por_partes → horario PARCIAL + diagnostico.py (causas + acciones)
```

> **Paradigma (asistente, no generador perfecto).** El sistema **nunca relaja restricciones
> duras automáticamente**. O entrega un horario factible, o entrega el mejor subconjunto
> factible (PARCIAL) junto con un **diagnóstico accionable** de lo que no cupo, y deja que el
> usuario resuelva (editando o ajustando datos) y revalide. Ver §5.

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
| Semestre malla | `Plan Común`, o `ICI/IOC/ICE/ICC/ICA` | si `Plan Común` tiene valor se usa esa. **Sem 1-4**: solo Plan Común. **Sem 5+**: además se expande a todas las especialidades del mismo número de semestre (los cursan todos los alumnos → RD1 contra todo ese semestre). Si no hay Plan Común, se usan las de carrera. Se preservan sufijos de mención ("9a") |
| Horas a programar | `Clases A PROGRAMAR`, `Ayudantías PROGRAMAR`, `Laboratorios o Talleres PROGRAMAR` | enteros (se usan estas, **no** las regulares) |
| Distribución | `2+1 o 3?` | `"3"/"3-juntas"` → 1 bloque de 3h; `"2+1"` → 1 bloque de 2h + 1 de 1h; resto → `ceil(horas/2)` bloques de 2h |
| Profesor cátedra | `RUT PROFESOR 1` | normalizado (sin puntos/espacios) |
| Profesor lab | `RUT PROFESOR LABT` | si existe |

**Secciones fuera de scope:** las filas cuya `SECCIONES` es una **letra** (B, C, …) en vez
de un número son cupos de desborde (cuando no entra todo el curso en una sala/lab). **No se
programan** (indicación de la encargada curricular); el resto de la fila —curso, profesor,
semestre— sí se registra.

**Creación de secciones** (una `Seccion` por componente con horas > 0, solo secciones numéricas):

- **CLAS** si `Clases A PROGRAMAR > 0` → profesor = `RUT PROFESOR 1`, `afecta_disponibilidad=True` (si hay RUT).
- **AYUD** si `Ayudantías PROGRAMAR > 0` → profesor nominal = `RUT PROFESOR 1` (solo display), `afecta_disponibilidad=False` (la dicta un TA).
- **LABT** si `Laboratorios o Talleres PROGRAMAR > 0`:
  - Si hay `RUT PROFESOR LABT` → ese profesor, `afecta_disponibilidad=True`.
  - Si **no** hay profesor de lab → profesor = `RUT PROFESOR 1` solo como referencia, `afecta_disponibilidad=False` (se asume TA).

**Cálculo de bloques necesarios:** `ceil(horas/2)` (bloques de 2h), o `1` para distribución
"3"/"3-juntas". Un mismo curso en varias filas (distintos planes) **acumula semestres**
(unión de sets); las secciones se crean una sola vez por `(codigo, seccion, componente)`.

**Duración de bloque por sección** (`duracion_bloque` / `tipos_bloques_necesarios`): `"3h"`
solo si la distribución es `"3"/"3-juntas"` y el componente tiene ≥3 horas; el resto es `"2h"`.
La distribución **`"2+1"`** está implementada: la sección lleva
`tipos_bloques_necesarios=["2h","1h"]` y el resolver filtra el dominio por tipo para cada
variable (una va a bloques de 2h, la otra a bloques de 1h; no se solapan). El solver solo
asigna a cada variable de la sección bloques de **su** tipo (ver RD6).

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
        rut_profesor, afecta_disponibilidad, cantidad_bloques_necesarios,
        tipos_bloques_necesarios=[], duracion_bloque="2h")

Profesor(rut, nombre, tipo {JORNADA|HONORARIO}, disponibilidad: set[bloque_idx])
```

### 1.6 Catálogo de bloques (`blocks.py`)

150 bloques = **30 tipos × 5 días**. Cada bloque tiene `sub_bloques` (slots de 50 min).
Dos bloques **se solapan** si son del mismo día y comparten ≥1 sub-bloque
(`MATRIZ_SOLAPAMIENTO`), **no** por igualdad de índice.

- **Tipos estándar** (`es_estandar=True`): 5 de 2h (8:30, 10:30, 13:30, 15:30, 17:30),
  2 de 3h (10:30-13:20, 12:30-15:20) y 11 de 1h (8:30-9:20 … 18:30-19:20). Es la grilla
  institucional preferida.
- **Tipos "helper"** (`es_estandar=False`): 5 de 2h + 7 de 3h que rellenan los huecos
  (inicios 9:30, 11:30, 12:30, 14:30, 16:30 y 3h de mañana/tarde/noche) para que cualquier
  disponibilidad sea representable. Se usan **solo como último recurso** (ver objetivo del
  solver). Los bloques de 1h se usan solo para el segundo componente de las secciones "2+1".

---

## 2. Restricciones DURAS — activas en `solver_cpsat.py`

El modelo es **a nivel de sección**: cada sección tiene su(s) variable(s) de bloque, con
dominio = sus bloques disponibles. El solver **decide el paralelismo por sí mismo**: para
que todos los ramos de un semestre quepan sin topes, pone en paralelo las secciones de un
mismo curso donde la disponibilidad lo permite. No hay agrupación previa.

| ID | Qué verifica | Estado / detalle |
|----|--------------|------------------|
| **RD2 — Disponibilidad de profesor** | Cada sección solo puede ir en bloques donde su(s) profesor(es) está(n) disponible(s). | **Activa y dura.** Implementada como el **dominio** de cada variable (`disponibilidad_seccion`). JORNADA = todos los bloques de su duración; HONORARIO = sus bloques declarados. Si la sección tiene **profesor 2** (co-dictante de CLAS), el dominio se intersecta también con su disponibilidad. **Se respeta por completo**: si no hay bloque válido, el modelo es INFEASIBLE. |
| **RD6 — Duración del bloque** | Una sección solo usa bloques cuyo tipo (2h/3h) coincide con su `duracion_bloque`. Una clase de 2h no puede caer en un bloque de 3h ni viceversa. | **Activa y dura.** Implementada en el **dominio** (`disponibilidad_seccion` filtra por `TODOS_BLOQUES[b].tipo == s.duracion_bloque`). Solo las clases "3-juntas"/de 3h usan bloques de 3h. |
| **Intra-sección** | Los bloques de una misma sección no se solapan entre sí. | Activa. |
| **NRC — Componentes de la misma sección** | CLAS-k, AYUD-k y LABT-k de la **misma sección** (mismo NRC) no se solapan (el alumno asiste a los tres). | Activa. Se agrupa por `(codigo, seccion)`. |
| **RD1 — Sin topes de malla** | Secciones de **cursos distintos** del mismo `(carrera, semestre)` no se solapan. | Activa y dura. Secciones del **mismo** curso quedan exentas (pueden ir paralelas). |
| **RD3 — Unicidad de profesor** | Un profesor con `afecta_disponibilidad=True` no dicta dos secciones a la vez, **en cualquier rol** y curso. | Activa. Incluye: dos LABT del mismo curso con la misma profesora; un profesor que dicta LABT de un curso y CLAS de otro. **El profesor de laboratorio se trata como persona distinta** del de cátedra (cada sección usa su profesor real). El **profesor 2** co-dictante también entra (no puede estar en dos secciones a la vez). AYUD no entra (la dicta un TA). |
| **RD4 — Capacidad de salas especiales** | En cada instante (sub-bloque), la cantidad de secciones que usan un mismo tipo de sala no supera las salas físicas disponibles. | Activa. **Capacidad = 1** → ningún par puede solaparse (incluye mismo curso). **Capacidad > 1** → suma por sub-bloque ≤ capacidad (ej. LABT COMPUTACION: hasta 4 en paralelo). Se cuenta por **sub-bloque**, así que bloques distintos que se solapan (ej. 10:30-13:20 y 12:30-15:20) también compiten por la sala. AYUD excluida. |
| **RD7 — Ayudantías desde 12:30** | Los bloques de AYUD inician a las 12:30 o después. | Activa, implementada en el **dominio** de las secciones AYUD. |
| **RD8 — Horarios protegidos de minors** | Los cursos de semestre **3, 4 o 5** no pueden ocupar los bloques que tocan las ventanas de minor: **Martes** 17:30-19:20, **Miércoles** 17:30-19:20, **Viernes** 10:30-12:20. | Activa, implementada en el **dominio** (`disponibilidad_seccion` excluye `BLOQUES_PROTEGIDOS_MINOR` para secciones de sem 3/4/5). Verificable con `verificar_minor`. |

**Objetivo de optimización del CP-SAT:** minimizar el uso de bloques **helper**
(no estándar). Las secciones sin datos de disponibilidad quedan restringidas a la grilla
estándar; las que sí tienen disponibilidad pueden usar helpers, pero solo cuando su
disponibilidad lo obliga.

**Verificación independiente** (`verificar_topes`, `verificar_rd3`, `verificar_rd4`,
`verificar_intra`): re-chequean la solución. Sobre el horario entregado —completo o
parcial— el resultado es `topes=0, RD3=0, RD4=0, intra=0`: el sistema nunca entrega un
horario que viole una restricción dura (lo que no cabe se reporta como diagnóstico, §5).

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
| **Helper** | 40 (`PESO_BLOQUE_HELPER`) | Cada bloque helper (fuera de la grilla estándar) usado. |

> Nota: la antigua RB5 (proximidad al histórico de semestres anteriores) fue **eliminada**
> — el cliente confirmó que no es relevante. El sistema ya no lee `inputs/historico/`.

Parámetros por defecto de `ejecutar_ga`: `n_generaciones=200`, `pop_size=40`, `cxpb=0.5`,
`mutpb=0.4`, `seed=42`.

---

## 4. Limitaciones conocidas (lo que NO se verifica)

1. **Días distintos para secciones multi-bloque: no es restricción dura.** El intra-sección
   solo prohíbe **solapamiento**. Dos bloques de la misma sección en el mismo día pero sin
   solaparse (ej. 8:30 y 10:30) están permitidos por CP-SAT; el GA lo **desalienta** vía
   RB4 (blanda), pero no lo prohíbe.

3. **Honorarios sin datos de disponibilidad** (ni en RESPUESTAS ni en FueraForms) se asumen
   con **disponibilidad total**. Si en realidad tienen restricciones, no se respetan.

4. **Salas con nombre desconocido** (un nombre en BBDD que no calza con ningún TIPO del
   inventario, ni siquiera tras canonicalizar) se tratan como **capacidad 1** (conservador).

5. **RD4 en el GA es una aproximación binaria.** El CP-SAT modela la capacidad exacta por
   sub-bloque, pero el grafo de conflictos del GA solo conecta pares (para capacidad > 1
   conecta cursos distintos). La factibilidad de capacidad la garantiza el punto de partida
   de CP-SAT; un movimiento del GA podría, en teoría, exceder capacidad entre secciones del
   mismo curso (el `reporter` lo señalaría).

6. **Disponibilidad estricta a nivel de bloque completo.** Un bloque se considera disponible
   solo si el profesor declaró **todos** sus sub-bloques. Una declaración parcial no habilita
   el bloque.

7. **AYUD** se dicta por un TA: no usa la disponibilidad de ningún profesor, solo se limita a
   bloques de 2h desde las 12:30 (RD7). El RUT del profesor 1 se guarda solo para mostrar en
   el Excel. La preferencia por la grilla estándar es blanda (objetivo / `PESO_BLOQUE_HELPER`).

8. **Cursos sin semestre en malla** (ningún valor en Plan Común ni carreras) no participan
   de RD1 (no generan topes), pero sí del resto de restricciones.

9. **Secciones con letra** (B, C, …) son cupos de desborde y **no se programan** (fuera de
   scope por decisión curricular).

10. **Selección del Maestro**: si hay varios `Maestro*.xlsx` en `inputs/`, se usa el primero
    alfabéticamente (con aviso). No se valida que sea el "correcto".

---

## 5. Asistente: horario parcial, diagnóstico y edición

El sistema **no relaja restricciones duras**. Cuando el modelo completo no es factible,
en vez de fallar (o inventar un horario relajado) entrega lo que sí cabe y explica el resto.

### 5.1 Resolución por partes (`solver_cpsat.resolver_por_partes`)

1. Intenta el modelo **completo**. Si es factible → `estado="FACTIBLE"` (horario total).
2. Si es INFEASIBLE, descompone en unidades **`(carrera, semestre)`** —la granularidad más
   fina que preserva RD1— y las resuelve **incrementalmente**: cada unidad respeta como
   **fijas** las secciones ya colocadas (RD1/RD3/RD4 contra ellas, vía los parámetros
   `secciones`/`fijadas` de `resolver`). Las que no entran se marcan **bloqueadas**.
   Resultado: `estado="PARCIAL"` con `asignaciones` (subconjunto que respeta TODAS las duras)
   + `bloqueadas: [UnidadBloqueada(carrera, semestre, secciones)]`. Si no entra nada →
   `"INFEASIBLE"`.

### 5.2 Diagnóstico (`diagnostico.py`)

Toma las unidades bloqueadas y produce, por unidad, la causa + **acciones concretas**:

- **Capa 1 — imposibilidad aislada** (sin solver): secciones imposibles por sí solas
  (sin bloques válidos; `2+1` cuyos únicos 2h y 1h se solapan; sesiones que no caben en
  horarios no solapados). Son los diagnósticos más precisos.
- **Capa 2 — restricción culpable** (con solver, en aislamiento): re-resuelve la unidad
  **sola**. Si es factible aislada → el bloqueo es **contención** con otros semestres
  (profesor/sala compartidos, que se identifican). Si es infactible aislada → prueba
  desactivar RD2/RD3/RD4 **solo para diagnosticar** (nunca se devuelve ese horario) y
  señala la restricción culpable.

Salida: `Diagnostico(unidades=[DiagnosticoUnidad(carrera, semestre, causa_principal,
sugerencias=[Sugerencia(causa, severidad, mensaje, acciones, secciones, profesores,
bloques)])])`.

### 5.3 Edición manual con revalidación (`edicion.py`)

Edición interactiva "click-para-mover": el usuario mueve un bloque de una sección y el
sistema valida contra **todas** las duras (chequeo focalizado en la sección movida, porque
el resto no cambia). No bloquea el movimiento: informa los conflictos y el usuario decide.

- `conflictos_de_seccion(datos, asig, sec_id)` → conflictos duros (RD1/RD2/RD3/RD4/RD6/RD7/
  intra/NRC) que involucran a `sec_id`.
- `bloques_validos(datos, asig, sec_id, indice)` → por cada bloque candidato del hueco,
  `estado="valido"` (verde) o `"conflicto"` (rojo, con `motivos`).
- `aplicar_movimiento(...)` → nueva asignación + conflictos resultantes.

### 5.4 Endpoints (`api/routes.py`)

| Método | Ruta | Qué hace |
|--------|------|----------|
| POST | `/upload` | Sube los Excel a `inputs/`. |
| POST | `/solve` | Lanza el pipeline en background. |
| GET | `/status` | Progreso (`idle/running/ready/error`). |
| GET | `/results` | Resultado: `estado`, `secciones`, `metricas`, `reporte`, `diagnostico`. |
| GET | `/diagnostico` | Solo el diagnóstico del último solve. |
| GET | `/report` | Solo el reporte de violaciones. |
| POST | `/editar/bloques-validos` | Candidatos verde/rojo para mover un bloque. |
| POST | `/editar/mover` | Aplica el movimiento, revalida y regenera reporte + Excel. |
| GET | `/export` | Descarga el `.xlsx` generado. |

> **Nota:** la re-subida del Excel editado (revalidación por archivo) está **diferida**;
> la edición se hace hoy con el flujo interactivo de §5.3.

---

## 6. Mejoras futuras

Ideas de evolución, ordenadas por valor/impacto. Ninguna es requisito para el funcionamiento
actual; se listan para no perder el contexto de decisiones ya analizadas.

### 6.1 Maximización de colocación (reemplazar el greedy de `resolver_por_partes`)

**Problema.** Hoy, cuando el modelo completo es INFEASIBLE, `resolver_por_partes` descompone
en unidades `(carrera, semestre)` y las resuelve **greedy incremental** (orden fijo, fijando
lo previo). Ese greedy no es óptimo: puede dejar bloqueadas unidades que en realidad **sí
caben** en una solución conjunta (falsos positivos), y el diagnóstico las reporta como
"contención" cuando no hay conflicto real. (Se observó al colocar los cursos de Plan Común
superior primero: encajonaban a especialidades que eran factibles.)

**Propuesta.** Modelar la colocación como **óptimo global maximizando secciones colocadas**:
cada sección lleva un booleano `colocada`; todas sus restricciones duras se aplican
**solo si `colocada`** (reificación con `OnlyEnforceIf`); el objetivo es `Maximize(Σ colocada)`.
El resultado coloca el **máximo real** y marca como bloqueadas **exactamente** las secciones
imposibles (sin artefactos de orden). El diagnóstico gana precisión quirúrgica (señala la
sección/dato exacto). Costo: modelo más grande y algo más lento; conviene medir tiempos.

### 6.2 Diagnóstico Capa 3 — núcleo conflictivo mínimo

Usar `model.AddAssumption()` + `solver.SufficientAssumptionsForInfeasibility()` de OR-Tools
para obtener el **subconjunto mínimo** de restricciones/secciones que se contradicen, en vez
de señalar la restricción a nivel de tipo (RD2/RD3/RD4) como hace la Capa 2. Da mensajes aún
más accionables ("estas 3 secciones + este profesor son el conflicto exacto").

### 6.3 Aviso de disponibilidad "huérfana" (lección del caso IOC3000)

Un profesor puede declarar una franja de 50 min que **ningún bloque del catálogo puede usar**
(p.ej. una franja suelta a las 18:30 cuando faltaba el bloque de 1h ahí). Hoy eso se descarta
en silencio y puede volver INFEASIBLE todo el modelo sin señal clara. **Propuesta:** en el
parser, avisar cuando un sub-bloque declarado por un profesor no cae en ningún bloque
agendable, para que los problemas de datos/catálogo salgan a la luz temprano.

### 6.4 Re-subida del Excel editado (Fase 5A, diferida)

Parser inverso del horario exportado + endpoint que revalida las asignaciones editadas a mano
y reporta qué duras se rompieron. Complementa la edición interactiva (§5.3) para quienes
prefieran editar en Excel. Fue diferida por ser frágil (el usuario puede romper el formato).

### 6.5 RD4 exacto en el GA

El GA aproxima la capacidad de salas (RD4 > 1) con un grafo de conflictos binario (ver §4, limitación 5).
Modelarla exactamente por sub-bloque evitaría que un movimiento del GA exceda capacidad entre
secciones del mismo curso (hoy solo lo garantiza el punto de partida de CP-SAT + el reporter).

### 6.6 "Días distintos" como restricción dura configurable

El intra-sección solo prohíbe **solape**; que dos bloques de una sección caigan el mismo día
sin solaparse lo desalienta RB4 (blanda). Si el cliente lo exige, podría volverse dura
(opcional por curso/componente).

### 6.7 Persistencia y deshacer de las ediciones manuales

Las ediciones "click-para-mover" viven en memoria (`_state`). Un despliegue real querría
persistirlas, soportar **deshacer/historial**, y recomputar métricas (fitness) tras cada
movimiento (hoy quedan algo desactualizadas respecto al horario editado).