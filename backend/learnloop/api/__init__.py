"""Public application factory (keeps learnloop.api.create_app stable)."""

from .app import create_app

__all__ = ["create_app"]
