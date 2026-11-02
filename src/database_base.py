"""Shared ORM metadata for product models and focused coordination tables."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Application schema metadata."""
