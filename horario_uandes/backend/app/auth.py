"""
auth.py — Autenticación con Google (OAuth) restringida por dominio institucional.

Flujo:
  1. El frontend obtiene un ID token de Google (Google Identity Services).
  2. POST /auth/google verifica ese token contra Google, valida que el email pertenezca a
     un dominio permitido (uandes.cl / miuandes.cl) y emite una **sesión JWT propia**.
  3. Las peticiones siguientes envían `Authorization: Bearer <jwt>`; `require_user` la valida.

Configuración por variables de entorno:
  GOOGLE_CLIENT_ID   — client id de OAuth (de Google Cloud Console). Si NO está seteado,
                       el auth queda DESACTIVADO (dev/tests: acceso abierto).
  AUTH_SECRET        — secreto para firmar las sesiones JWT (obligatorio en prod).
  ALLOWED_DOMAINS    — dominios permitidos, separados por coma (default: uandes.cl,miuandes.cl).
  SESSION_DAYS       — duración de la sesión en días (default: 7).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
AUTH_SECRET = os.getenv("AUTH_SECRET", "dev-secret-no-usar-en-prod")
ALLOWED_DOMAINS = {
    d.strip().lower()
    for d in os.getenv("ALLOWED_DOMAINS", "uandes.cl,miuandes.cl").split(",")
    if d.strip()
}
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))

# El auth se activa solo si hay un client id configurado. Sin él → acceso abierto
# (útil en desarrollo local y para los tests).
AUTH_ENABLED = bool(GOOGLE_CLIENT_ID)

router = APIRouter()


# ---------------------------------------------------------------------------
# Verificación del token de Google + sesión propia
# ---------------------------------------------------------------------------

def _verificar_google(credential: str) -> dict:
    """Verifica el ID token de Google y valida el dominio. Retorna {email, name, picture}."""
    info = google_id_token.verify_oauth2_token(
        credential, google_requests.Request(), GOOGLE_CLIENT_ID,
    )
    if not info.get("email_verified"):
        raise ValueError("El correo no está verificado por Google.")
    email = (info.get("email") or "").lower()
    dominio = email.rsplit("@", 1)[-1] if "@" in email else ""
    if dominio not in ALLOWED_DOMAINS:
        raise ValueError(
            f"Solo se permiten correos institucionales ({', '.join(sorted(ALLOWED_DOMAINS))}). "
            f"El correo '{email}' no está autorizado."
        )
    return {"email": email, "name": info.get("name", ""), "picture": info.get("picture", "")}


def _crear_sesion(user: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    return jwt.encode({**user, "exp": exp}, AUTH_SECRET, algorithm="HS256")


def _leer_sesion(token: str) -> dict:
    return jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])


def require_user(authorization: str = Header(default="")) -> dict:
    """
    Dependencia para proteger endpoints. Si el auth está desactivado (sin GOOGLE_CLIENT_ID),
    devuelve un usuario anónimo (acceso abierto). Si está activo, exige una sesión válida.
    """
    if not AUTH_ENABLED:
        return {"email": "dev@local", "name": "Desarrollo", "picture": ""}
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado.")
    try:
        return _leer_sesion(authorization[7:])
    except Exception:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class GoogleLoginRequest(BaseModel):
    credential: str


@router.post("/auth/google")
def login_google(req: GoogleLoginRequest):
    """Inicia sesión con un ID token de Google. Valida dominio y emite una sesión JWT."""
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="El login no está configurado en el servidor.")
    try:
        user = _verificar_google(req.credential)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception:
        raise HTTPException(status_code=401, detail="Token de Google inválido.")
    return {"token": _crear_sesion(user), "user": user}


@router.get("/auth/config")
def config():
    """
    Config pública de auth para el frontend (en runtime, no en build). Devuelve si el auth
    está activo y el client id público de Google. NO expone el AUTH_SECRET.
    """
    return {"auth_enabled": AUTH_ENABLED, "google_client_id": GOOGLE_CLIENT_ID}


@router.get("/auth/me")
def me(user: dict = Depends(require_user)):
    """Devuelve el usuario de la sesión actual (o anónimo si el auth está desactivado)."""
    return {"user": user, "auth_enabled": AUTH_ENABLED}
