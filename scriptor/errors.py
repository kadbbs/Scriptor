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
