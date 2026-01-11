"""Vercel serverless function entry point."""

import sys
import os

# Add the project root to the path so we can import backend.app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangum import Mangum
from backend.app.main import app as fastapi_app

# Wrap FastAPI app with Mangum for Lambda/Vercel compatibility
# The handler must be named 'handler' for Vercel
handler = Mangum(fastapi_app, lifespan="off")

# Also expose as 'app' for compatibility
app = handler
