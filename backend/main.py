
from fastapi import FastAPI

app = FastAPI(title="DBOT Enterprise Core")

@app.get("/health")
def health():
    return {"status":"healthy"}

@app.get("/")
def root():
    return {"service":"DBOT Enterprise SaaS"}
