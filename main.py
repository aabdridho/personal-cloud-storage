from fastapi import FastAPI

from routers import files, folders, login, users

app = FastAPI(title="Personal Cloud Storage", version="0.6.0")

app.include_router(login.router)
app.include_router(users.router)
app.include_router(folders.router)
app.include_router(files.router)


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}
