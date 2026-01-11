"""Vercel serverless function entry point.

Vercel's @vercel/python runtime supports ASGI apps (FastAPI/Starlette) natively.
Just export the app and Vercel handles the rest.
"""

import sys
import os

# Add the project root to the path BEFORE any imports
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Import the FastAPI app
from backend.app.main import app
