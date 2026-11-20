"""Evaluation use-case errors with stable meanings for API frontends."""


class InvalidBearerTokenError(ValueError):
    """A split bearer token does not identify a session split."""


class TaskNotFoundError(ValueError):
    """A task is missing or is not owned by the supplied split token."""


class TaskAlreadyCompleteError(ValueError):
    """A task has already been completed."""
