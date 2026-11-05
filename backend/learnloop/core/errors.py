"""Failures shared by core rules, service clients, and durable workflows."""


class ServiceError(Exception):
    def __init__(
        self, code: str, message: str, retryable: bool = True, details: dict | None = None
    ):
        self.code, self.message, self.retryable = code, message, retryable
        self.details = details
        super().__init__(message)
