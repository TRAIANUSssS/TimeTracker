"""Read-only request snapshots and commands to the existing tracker writer."""

import hashlib
import sqlite3
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from time_tracker import __version__
from time_tracker.api.commands import WriterUnavailable
from time_tracker.api.schemas import (
    ActivityFilters,
    AppFilters,
    Application,
    ApplicationPatch,
    ApplicationSegment,
    AppsResponse,
    ContextSwitches,
    DateCell,
    Filters,
    OtherSegment,
    SystemStats,
    TimelineFilters,
    WeekdayCell,
)
from time_tracker.runtime import SystemClock
from time_tracker.storage.stats import Statistics, application_json


def create_app(database, *, commands=None, clock=None) -> FastAPI:
    clock = clock if clock is not None else SystemClock()
    app = FastAPI(title="TimeTracker local API", version=__version__)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_request(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed"}, status_code=403
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, error):
        return JSONResponse({"detail": "Storage temporarily unavailable"}, status_code=503)

    def stats(filters, operation, **kwargs):
        now = clock.now_ms()
        with database.reader() as connection:
            reader = Statistics(connection, filters.selection(), now)
            return getattr(reader, operation)(**kwargs)

    @app.get("/stats/apps", response_model=AppsResponse)
    def apps(filters: Annotated[AppFilters, Query()]):
        return stats(filters, "apps", active_only=filters.active_only)

    @app.get("/stats/system", response_model=SystemStats)
    def system(filters: Annotated[Filters, Query()]):
        return stats(filters, "system")

    @app.get("/stats/context-switches", response_model=ContextSwitches)
    def switches(filters: Annotated[Filters, Query()]):
        return stats(filters, "context_switches")

    @app.get("/stats/timeline", response_model=list[ApplicationSegment | OtherSegment])
    def timeline(filters: Annotated[TimelineFilters, Query()]):
        return stats(filters, "timeline")

    @app.get("/stats/activity", response_model=list[DateCell] | list[WeekdayCell])
    def activity(filters: Annotated[ActivityFilters, Query()]):
        return stats(filters, "activity")

    @app.get("/applications", response_model=list[Application])
    def applications():
        with database.reader() as connection:
            return [
                application_json(row)
                for row in connection.execute(
                    "SELECT * FROM applications ORDER BY name COLLATE NOCASE,id"
                )
            ]

    @app.patch("/applications/{application_id}", response_model=Application)
    def patch(application_id: int, settings: ApplicationPatch):
        if commands is None:
            raise HTTPException(503, "Tracker writer is not available")
        try:
            return commands.change(application_id, settings.model_dump(exclude_unset=True))
        except LookupError as error:
            raise HTTPException(404, "Application does not exist") from error
        except WriterUnavailable as error:
            raise HTTPException(503, str(error)) from error

    @app.get(
        "/applications/{application_id}/icon",
        response_class=FileResponse,
        responses={200: {"content": {"image/png": {}}}, 404: {"description": "No cached icon"}},
    )
    def icon(application_id: int):
        with database.reader() as connection:
            rows = connection.execute(
                "SELECT path FROM executables WHERE application_id=? ORDER BY last_seen_at DESC,id",
                (application_id,),
            ).fetchall()
        for row in rows:
            key = hashlib.sha256(row["path"].encode("utf-8")).hexdigest()
            path = database.path.parent / "icons" / f"{key}.png"
            if path.is_file():
                return FileResponse(path, media_type="image/png")
        raise HTTPException(404, "No cached icon")

    return app
