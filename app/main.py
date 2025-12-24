import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import webhook, followups
from app.routers import ui
from app.routers import calendar_import
from app.routers import shift_organizer
from app.routers import availability
from app.routers import events_api
from app.routers import notifications
from app.db_schema import SchemaMissingError, ensure_calendar_schema

logger = logging.getLogger(__name__)

try:
    ensure_calendar_schema()
except SchemaMissingError as exc:
    raise RuntimeError(str(exc)) from exc
except Exception as exc:
    raise RuntimeError(f"Failed to validate database schema: {exc}") from exc

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
app.include_router(shift_organizer.router)
app.include_router(availability.router)
app.include_router(events_api.router)
app.include_router(notifications.router)

@app.get("/health")
def health():
    return {"ok": True}
