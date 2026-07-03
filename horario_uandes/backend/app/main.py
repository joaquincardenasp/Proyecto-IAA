import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .auth import router as auth_router, require_user
from .db.database import init_db

app = FastAPI(title="Generador de Horarios UANDES")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    """Health check público (para el balanceador/Render)."""
    return {"status": "ok"}

# CORS_ORIGINS: lista de orígenes separados por coma.
# En desarrollo no hace falta setearla.
# En producción (Render): CORS_ORIGINS=https://tu-frontend.onrender.com
_extra = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_origins = ["http://localhost:5173", "http://localhost:3000"] + _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth (público). Las demás rutas quedan protegidas por require_user (que es no-op si el
# auth no está configurado, para desarrollo y tests).
app.include_router(auth_router, prefix="/api")
app.include_router(router, prefix="/api", dependencies=[Depends(require_user)])
