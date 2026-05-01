"""Offline AI Assistant — backend package.
 
This file makes the `app/` directory a Python package, which is what allows
imports like `from app import database` and `from .config import settings`
to work. It is intentionally minimal: Python only requires it to *exist*.
 
Anything we put here is loaded once when any module inside `app/` is
first imported, so we keep it tiny — just the public version string.
"""
 
__version__ = "1.1.0"
 