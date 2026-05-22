from fastapi import FastAPI

app = FastAPI(title="Generador de Horarios UANDES")


@app.get("/api/health")
def health():
    return {"status": "ok"}
