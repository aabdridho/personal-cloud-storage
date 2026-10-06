from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from metrics import register_storage_collector
from routers import files, folders, login, users

app = FastAPI(title="Personal Cloud Storage", version="0.9.0")

app.include_router(login.router)
app.include_router(users.router)
app.include_router(folders.router)
app.include_router(files.router)


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}


# /metrics is scraped by Prometheus inside the Docker network only;
# Nginx refuses it from the outside.
Instrumentator(excluded_handlers=["/health", "/metrics"]).instrument(app).expose(
    app, include_in_schema=False
)
register_storage_collector()
