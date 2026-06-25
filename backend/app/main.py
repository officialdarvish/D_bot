
from fastapi import FastAPI

app = FastAPI(title="DBOT Enterprise API")

@app.get("/")
def root():
    return {"status":"enterprise api running"}

@app.get("/health")
def health():
    return {"ok": True}
