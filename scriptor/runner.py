"""Durable automatic runs; each chapter uses the same workflow as manual stepping."""

import threading

from .errors import ScriptorError, StopRequested
from .service import StoryService


class AutoRunner:
    def __init__(self, repo, model_factory, settings):
        self.repo, self.model_factory, self.settings = repo, model_factory, settings
        self._threads = {}
        self._lock = threading.Lock()
        self._closing = False

    def start(self, book_id, chapters):
        with self._lock:
            if self._closing:
                raise ScriptorError("服务正在关闭，请稍后重试")
            job = self.repo.create_job(book_id, chapters)
            thread = threading.Thread(target=self._run, args=(job,), daemon=True)
            self._threads[job["id"]] = thread
            thread.start()
            return job

    def _run(self, job):
        stopped = threading.Event()
        model = None
        completed = 0

        def heartbeat():
            while not stopped.wait(5):
                try:
                    self.repo.heartbeat(job["id"])
                except Exception:
                    # A temporary DB error may recover on the next tick; lease expiry is fail-closed.
                    continue

        keeper = threading.Thread(target=heartbeat, daemon=True)
        keeper.start()
        try:
            model = self.model_factory()
            service = StoryService(self.repo, model, self.settings, job_id=job["id"])
            finished = False
            while completed < job["target"]:
                if self.repo.job(job["book_id"], job["id"])["status"] != "running":
                    break
                result = service.step(job["book_id"])
                finished = result["finished"]
                if finished:
                    break
                completed += 1
                self.repo.job_completed(job["id"], completed)
            self.repo.finish_job(
                job["id"],
                "completed" if finished or completed >= job["target"] else "paused",
                completed,
            )
        except StopRequested:
            self.repo.finish_job(job["id"], "paused", completed)
        except Exception as exc:
            error = (
                str(exc)
                if isinstance(exc, ScriptorError)
                else f"{type(exc).__name__}：自动运行失败"
            )
            self.repo.finish_job(job["id"], "failed", completed, error)
        finally:
            stopped.set()
            keeper.join(timeout=1)
            close = getattr(model, "close", None)
            if close:
                close()
            with self._lock:
                self._threads.pop(job["id"], None)

    def close(self):
        with self._lock:
            self._closing = True
            threads = list(self._threads.items())
        for job_id, _ in threads:
            with self.repo.connect() as conn:
                conn.execute(
                    "UPDATE jobs SET status='stopping' WHERE id=? AND status='running'", (job_id,)
                )
        # In-flight model calls finish atomically; hard process exits recover through lease expiry.
        for _, thread in threads:
            thread.join(timeout=1)
