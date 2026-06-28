
from fastapi import FastAPI

app = FastAPI(title="API Gateway")

@app.get("/")
def gateway():
    return {"gateway":"running"}
