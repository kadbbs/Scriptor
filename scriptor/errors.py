class ScriptorError(Exception):
    """An actionable workflow error safe to show to the user."""


class NotFound(ScriptorError):
    pass


class Conflict(ScriptorError):
    pass


class ModelError(ScriptorError):
    pass


class ReviewRejected(ScriptorError):
    pass


class StopRequested(ScriptorError):
    pass


class EvidenceError(ReviewRejected):
    """Review bookkeeping is invalid; repair the review, not the manuscript."""


class StructuredOutputError(ModelError):
    """A completed model response did not satisfy its output contract."""
