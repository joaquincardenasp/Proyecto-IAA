FROM python:3.11-slim

WORKDIR /app

# ── Dependencias Python ───────────────────────────────────────────────────────
# Copiar solo requirements primero → aprovechar caché de Docker cuando el
# código cambia pero las dependencias no.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código de la aplicación ───────────────────────────────────────────────────
COPY app/ ./app/

# ── Directorios de datos ──────────────────────────────────────────────────────
# inputs/ → archivos Excel que se suben en runtime (vía /api/upload)
# outputs/ → Excel generado por el solver
RUN mkdir -p inputs outputs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
