import os

from fastapi import FastAPI

APP_VERSION = "0.1.0"

app = FastAPI(title="RDDH — Учёт расходов", version=APP_VERSION)


@app.get("/")
def root() -> dict:
    return {
        "service": "rddh-5jwf",
        "status": "ok",
        "version": APP_VERSION,
        "env": os.getenv("APP_ENV", "dev"),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
