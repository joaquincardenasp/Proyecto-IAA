# Generador de Horarios — Optimización de la Programación Académica

Herramienta basada en Inteligencia Artificial para automatizar la construcción del horario
académico semestral de la **Facultad de Ingeniería y Ciencias Aplicadas de la Universidad de
los Andes**. Genera un horario factible que respeta las restricciones duras del proceso y lo
optimiza según restricciones blandas de calidad, reduciendo drásticamente el tiempo y el
esfuerzo manual, sin reemplazar la revisión final del equipo académico.

> **Ante cualquier duda, contactar a [jicardenas@miuandes.cl](mailto:jicardenas@miuandes.cl).**

---

## Índice

- [El problema](#el-problema)
- [La solución](#la-solución)
- [Arquitectura](#arquitectura)
- [Restricciones del modelo](#restricciones-del-modelo)
- [Archivos de entrada](#archivos-de-entrada)
- [Instalación](#instalación)
- [Ejecución](#ejecución)
- [Uso de la aplicación](#uso-de-la-aplicación)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Despliegue](#despliegue)
- [Resultados](#resultados)
- [Documentación adicional](#documentación-adicional)
- [Autores y contacto](#autores-y-contacto)

---

## El problema

La programación académica de la Facultad se realiza hoy de forma **manual**, a partir de
múltiples archivos Excel gestionados por una sola persona. Esto implica una alta carga
operativa (construir un horario sin infringir disponibilidad de profesores, capacidad de
salas o topes entre ramos toma decenas de horas), un proceso difícil de mantener y un
conocimiento concentrado en una única persona.

## La solución

El sistema automatiza la generación de un horario **factible** y lo **optimiza**, entregando
además herramientas para revisarlo, editarlo y diagnosticar conflictos:

- **Parser** que lee los archivos que el cliente ya usa y extrae cursos, profesores y mallas.
- **Horario base** que garantiza las restricciones duras mediante el solver **CP-SAT**
  (OR-Tools).
- **Optimización** de las restricciones blandas mediante un **algoritmo genético** (DEAP).
- **Exportación** del horario a Excel, listo para revisión.
- **Panel de decisiones** para resolver ambigüedades de duración/distribución de clases.
- **Panel de diagnóstico** que explica por qué una sección no pudo programarse y sugiere
  acciones concretas.
- **Edición manual** "click-para-mover" con revalidación en vivo, **métricas/KPIs** y
  **versionado** del trabajo entre sesiones.

> El paradigma es **asistente, no generador perfecto**: cuando no existe solución factible,
> el sistema **diagnostica la causa y guía al usuario**; **nunca relaja una restricción dura
> automáticamente**.

## Arquitectura

El proyecto se compone de dos aplicaciones desplegables de forma independiente:

| Componente | Tecnología | Rol |
|---|---|---|
| **Backend** | Python · FastAPI · OR-Tools (CP-SAT) · DEAP (GA) | API REST, motor de optimización, persistencia y autenticación. |
| **Frontend** | React · TypeScript · Vite · Tailwind CSS | Interfaz web (SPA). |
| **Base de datos** | SQLAlchemy → SQLite (local) / PostgreSQL (producción) | Persistencia de planificaciones y versiones. Agnóstica al motor vía `DATABASE_URL`. |
| **Autenticación** | Google Identity Services + sesión JWT propia | Login restringido a correos institucionales (`@uandes.cl`, `@miuandes.cl`). |

El flujo del motor: **CP-SAT** construye un horario base que respeta matemáticamente las
restricciones duras; sobre ese horario, un **algoritmo genético** optimiza las blandas
mediante una función de *fitness* que penaliza su incumplimiento.

## Restricciones del modelo

**Duras** (obligatorias, garantizadas por CP-SAT):

- Disponibilidad de profesor · unicidad de profesor (no dicta dos secciones a la vez).
- Sin solapamiento entre componentes de una misma sección.
- Sin topes de malla (secciones del mismo par carrera–semestre no se solapan).
- Capacidad de salas especiales (no se exceden las salas físicas por tipo).
- Ayudantías solo desde las 12:30.

**Blandas** (preferencias, optimizadas por el GA):

- Continuidad de los laboratorios de programación (mismo día, bloques contiguos).
- Evitar profesores de jornada en bloques extremos del día.
- Separar los componentes de un mismo curso en días distintos.
- No repetir un mismo componente más de una vez por día.
- Evitar ventanas (tiempos muertos) en la jornada del profesor.

## Archivos de entrada

El sistema recibe **únicamente los dos archivos que el cliente ya usa** en su proceso:

- **Archivo Maestro** (`Maestro_*.xlsx`, obligatorio): oferta de cursos, secciones,
  profesores, carreras y semestres. Hojas: `MAESTRO`, `PROFESORES`, `RESPUESTAS`,
  `DisponibilidadesFueraForms`. Solo se programan las filas con `CURSO MANDANTE = SI`.
- **Archivo de Salas Especiales** (`SALAS_ESPECIALES_ING.xlsx`, obligatorio): requerimiento
  de sala por curso e inventario físico. Hojas: `BBDD` y `SALAS ESPECIALES`.

> La disponibilidad de profesores se obtiene de las hojas `PROFESORES` / `RESPUESTAS` /
> `DisponibilidadesFueraForms`, **no** de columnas de días del Maestro. Un profesor sin datos
> se asume con disponibilidad total.

## Instalación

**Requisitos:** Python 3.11+ (probado en 3.12), Node.js 18+ y npm, Git. PostgreSQL solo en
producción (en local se usa SQLite, incluido en Python).

```bash
git clone <URL-del-repositorio>
cd "Prog Academica V2/horario_uandes"

# Backend
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

En local no se requiere configuración adicional: sin `DATABASE_URL` el backend crea una base
SQLite automáticamente, y sin `GOOGLE_CLIENT_ID` la autenticación queda desactivada (acceso
abierto, útil para desarrollo). Las variables de entorno están documentadas en
`backend/.env.example` y `frontend/.env.example`.

## Ejecución

Con dos terminales, una por servicio:

```bash
# Terminal 1 — Backend (desde backend/, con el venv activado)
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend (desde frontend/)
npm run dev
```

Frontend en `http://localhost:5173`, backend en `http://localhost:8000` (documentación
interactiva en `/docs`). Vite proxea las llamadas `/api` al backend, así que en local no hace
falta configurar `VITE_API_BASE_URL`.

## Uso de la aplicación

Al ingresar, la aplicación pide autenticarse con una cuenta de Google institucional. La
interfaz se organiza en pestañas que se habilitan progresivamente:

1. **Planificaciones** — punto de entrada. Crear una planificación (nombre + archivo Maestro
   + archivo de Salas), activarla, eliminarla o versionarla. Una planificación agrupa un
   proceso completo (archivos + horario + historial) y persiste entre sesiones.
2. **Generar horario** — con una planificación activa, ejecuta el solver. Pasa por cuatro
   etapas visibles: leer archivos → horario base (CP-SAT) → optimización (GA) → exportación.
3. **Horario** — grilla semanal (Lun–Vie, 08:30–19:20) con filtros por carrera, semestre,
   tipo y texto. Permite ver el detalle de cada sección y **mover bloques manualmente**: el
   sistema marca en verde los destinos sin conflicto y en rojo los que lo generan (con el
   motivo). Un panel superior lista los **conflictos activos**.
4. **Métricas** — KPIs y estadísticas de calidad: secciones, bloques, mejora del GA,
   distribución por día/tipo y detalle de violaciones.
5. **Diagnóstico** — cuando el horario es parcial o inviable, explica la causa por unidad
   (carrera–semestre) y sugiere **acciones concretas** para desbloquear.
6. **Decisiones** — define la distribución de clases de 3 h (`3-juntas` o `2+1`) o la
   duración de componentes de 1 h antes de generar.
7. **Versiones** — guarda y recupera versiones con nombre del horario.

Cuando existe un horario generado, el botón **Descargar Excel** exporta el horario completo.

## Estructura del proyecto

```
Prog Academica V2/
├── README.md                 # Este archivo
└── horario_uandes/
    ├── frontend/             # React + TypeScript + Tailwind (Vite)
    │   └── src/
    │       ├── api/client.ts        # Cliente HTTP (inyecta el token de sesión)
    │       ├── components/          # Vistas: Inicio, Workspace, paneles, Login
    │       ├── App.tsx              # Nivel superior y autenticación
    │       └── theme.ts             # Paleta y colores por tipo de bloque
    ├── backend/
    │   ├── app/
    │   │   ├── main.py              # App FastAPI, routers, init_db al iniciar
    │   │   ├── auth.py              # Login Google + sesión JWT + require_user
    │   │   ├── api/routes.py        # Endpoints (solve, edición, planificaciones)
    │   │   ├── db/                  # Motor SQLAlchemy + modelos
    │   │   ├── core/                # parser, models, solver_cpsat, solver_ga,
    │   │   │                        #   diagnostico, edicion, exporter
    │   │   └── schemas/             # Esquemas Pydantic de la API
    │   ├── tests/                   # Tests incrementales por paso (parser → API)
    │   └── requirements.txt
    └── docs/                  # PRD, contexto, informe y manuales (LaTeX)
```

## Despliegue

El sistema está pensado para desplegarse en **Render** con tres recursos: un **PostgreSQL**,
un **Web Service** para el backend (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`) y un
**Static Site** para el frontend (`npm ci && npm run build`, publicando `dist/`). El esquema
de base de datos se crea/actualiza automáticamente al iniciar la aplicación.

El backend, ejecutándose en el plan *Starter* de Render (0.5 vCPU, 512 MB RAM), opera de
forma estable. El procedimiento completo, las variables de entorno y la configuración de
Google Cloud (OAuth) están detallados en el **Manual de Instalación y Despliegue**
(`horario_uandes/docs/`).

## Resultados

- **Tasa de violaciones de restricciones duras (TVRD):** 0 % de forma consistente.
- **Reducción del tiempo de planificación (TRPH):** un horario sin violaciones duras se
  obtiene en menos de 5 minutos, frente a ~50 horas-hombre del proceso manual (> 95 % de
  reducción estimada).
- **Cumplimiento de restricciones blandas (TCRB):** ~13 % de bloques con alguna violación
  blanda en promedio (objetivo < 28 %).

## Documentación adicional

En `horario_uandes/docs/` se encuentran los documentos completos del proyecto:

- **Informe ejecutivo final** — contexto, solución, KPIs y conclusiones.
- **Manual de usuario** — guía detallada de la interfaz web.
- **Manual de instalación y despliegue** — instalación, variables de entorno y puesta en
  producción reproducible.

## Autores y contacto

**Grupo 17 — IA Aplicada, Universidad de los Andes**

- Joaquín Cárdenas
- Matías De la Sotta
- Pablo Moyano

Ante cualquier duda o consulta sobre el proyecto, contactar a
**[jicardenas@miuandes.cl](mailto:jicardenas@miuandes.cl)**.
