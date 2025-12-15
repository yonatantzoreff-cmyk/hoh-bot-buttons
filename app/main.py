from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import webhook, followups
from app.routers import ui
from app.routers import calendar_import

app = FastAPI(title="HOH Buttons MVP v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(followups.router)
app.include_router(ui.router)
app.include_router(calendar_import.router)

@app.get("/health")
def health():
    return {"ok": True}
