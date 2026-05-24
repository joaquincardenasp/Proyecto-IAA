import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router

app = FastAPI(title="Generador de Horarios UANDES")

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

app.include_router(router, prefix="/api")
