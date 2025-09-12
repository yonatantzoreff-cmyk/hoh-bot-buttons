import os, json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import webhook, followups

app = FastAPI(title="HOH Buttons MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(followups.router)

@app.get("/health")
def health():
    return {"ok": True}
