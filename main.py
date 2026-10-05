from fastapi import FastAPI

app = FastAPI(title="Personal Cloud Storage")


@app.get("/health")
def health_check():
    return {"status": "ok"}
