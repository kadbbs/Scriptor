from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .errors import Conflict, ModelError, NotFound, ReviewRejected, ScriptorError
from .llm import create_model
from .models import (
    AutoRequest,
    CreateBook,
    EditRequest,
    IdeaInput,
    PlanRequest,
    StageRequest,
    WriteRequest,
)
from .repository import Repository
from .runner import AutoRunner
from .service import StoryService


def create_app(settings: Settings | None = None, model_factory=None):
    settings = settings or Settings.from_env()
    model_factory = model_factory or (lambda: create_model(settings))

    @asynccontextmanager
    async def lifespan(app):
        app.state.repo = Repository(settings.database)
        app.state.runner = AutoRunner(app.state.repo, model_factory, settings)
        try:
            yield
        finally:
            app.state.runner.close()

    app = FastAPI(title="Scriptor", version=__version__, lifespan=lifespan)
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def editor():
        return FileResponse(static_dir / "index.html")

    def service(request: Request):
        model = model_factory()
        try:
            yield StoryService(request.app.state.repo, model, settings)
        finally:
            close = getattr(model, "close", None)
            if close:
                close()

    @app.exception_handler(ScriptorError)
    async def domain_error(request, exc):
        status = (
            404
            if isinstance(exc, NotFound)
            else 409
            if isinstance(exc, Conflict)
            else 422
            if isinstance(exc, ReviewRejected)
            else 502
            if isinstance(exc, ModelError)
            else 400
        )
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "provider": settings.provider,
            "api_format": "messages" if settings.provider == "anthropic" else "responses",
        }

    @app.get("/api/books")
    def books(svc: StoryService = Depends(service)):
        return svc.repo.list()

    @app.post("/api/books", status_code=201)
    def create(payload: IdeaInput | CreateBook, svc: StoryService = Depends(service)):
        return svc.repo.create(payload)

    @app.post("/api/books/{book_id}/step")
    def step(book_id: str, svc: StoryService = Depends(service)):
        return svc.step(book_id)

    @app.post("/api/books/{book_id}/conceive")
    def conceive(book_id: str, svc: StoryService = Depends(service)):
        return svc.conceive(book_id)

    @app.post("/api/books/{book_id}/direct")
    def direct(book_id: str, svc: StoryService = Depends(service)):
        return svc.direct(book_id)

    @app.post("/api/books/{book_id}/auto", status_code=202)
    def auto(book_id: str, payload: AutoRequest, request: Request):
        return request.app.state.runner.start(book_id, payload.chapters)

    @app.get("/api/books/{book_id}/auto")
    def auto_status(book_id: str, request: Request):
        request.app.state.repo.get(book_id)
        return request.app.state.repo.jobs(book_id)

    @app.post("/api/books/{book_id}/auto/{job_id}/pause")
    def pause(book_id: str, job_id: str, request: Request):
        return request.app.state.repo.pause_job(book_id, job_id)

    @app.get("/api/books/{book_id}")
    def inspect(book_id: str, svc: StoryService = Depends(service)):
        return svc.inspect(book_id)

    @app.post("/api/books/{book_id}/bible")
    def bible(book_id: str, svc: StoryService = Depends(service)):
        return svc.bible(book_id)

    @app.post("/api/books/{book_id}/plans")
    def plan(book_id: str, payload: PlanRequest, svc: StoryService = Depends(service)):
        return svc.plan(book_id, payload)

    @app.post("/api/books/{book_id}/chapters/{number}/generate")
    def write(
        book_id: str, number: int, payload: WriteRequest, svc: StoryService = Depends(service)
    ):
        return svc.write(
            book_id,
            number,
            rewrite=payload.rewrite,
            content=payload.content,
            expected_revision=payload.expected_revision,
        )

    @app.put("/api/books/{book_id}/chapters/{number}")
    def edit(book_id: str, number: int, payload: EditRequest, svc: StoryService = Depends(service)):
        return svc.write(
            book_id,
            number,
            rewrite=True,
            content=payload.content,
            expected_revision=payload.expected_revision,
        )

    @app.get("/api/books/{book_id}/chapters/{number}/history")
    def history(book_id: str, number: int, svc: StoryService = Depends(service)):
        svc.repo.get(book_id)
        return svc.repo.history(book_id, number)

    @app.post("/api/books/{book_id}/stages")
    def advance(book_id: str, payload: StageRequest, svc: StoryService = Depends(service)):
        return svc.advance(book_id, payload.stage, payload.confirm)

    @app.get("/api/books/{book_id}/runs")
    def runs(book_id: str, svc: StoryService = Depends(service)):
        svc.repo.get(book_id)
        return svc.repo.runs(book_id)

    @app.get("/api/books/{book_id}/export", response_class=PlainTextResponse)
    def export(book_id: str, svc: StoryService = Depends(service)):
        return PlainTextResponse(
            svc.export(book_id),
            headers={"Content-Disposition": f'attachment; filename="{book_id}.md"'},
        )

    return app
