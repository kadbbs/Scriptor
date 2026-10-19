from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import Settings
from .errors import Conflict, ModelError, NotFound, ReviewRejected, ScriptorError
from .llm import ResponsesModel
from .models import CreateBook, EditRequest, PlanRequest, StageRequest, WriteRequest
from .repository import Repository
from .service import StoryService


def create_app(settings: Settings | None = None, model_factory=None):
    settings = settings or Settings.from_env()
    model_factory = model_factory or (lambda: ResponsesModel(settings))

    @asynccontextmanager
    async def lifespan(app):
        app.state.repo = Repository(settings.database)
        yield

    app = FastAPI(title="Scriptor", version="0.3.0", lifespan=lifespan)

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
        return {"status": "ok", "api_format": "responses"}

    @app.get("/api/books")
    def books(svc: StoryService = Depends(service)):
        return svc.repo.list()

    @app.post("/api/books", status_code=201)
    def create(payload: CreateBook, svc: StoryService = Depends(service)):
        return svc.repo.create(payload)

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
        return svc.write(book_id, number, rewrite=payload.rewrite, content=payload.content)

    @app.put("/api/books/{book_id}/chapters/{number}")
    def edit(book_id: str, number: int, payload: EditRequest, svc: StoryService = Depends(service)):
        return svc.write(book_id, number, rewrite=True, content=payload.content)

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
