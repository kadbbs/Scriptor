class ScriptorError(Exception):
    """An actionable workflow error safe to show to the user."""


class NotFound(ScriptorError):
    pass


class Conflict(ScriptorError):
    pass


class ModelError(ScriptorError):
    pass


class TransientModelError(ModelError):
    """A temporary transport failure eligible for bounded background retry."""

    def __init__(self, message, *, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class ReviewRejected(ScriptorError):
    pass


class StopRequested(ScriptorError):
    pass


class EvidenceError(ReviewRejected):
    """Review bookkeeping is invalid; repair the review, not the manuscript."""


class StructuredOutputError(ModelError):
    """A completed model response did not satisfy its output contract."""


class LiteraryError(ReviewRejected):
    """The prose needs a substantive narrative revision, not another evidence audit."""
