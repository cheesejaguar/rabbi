"""Vercel serverless function entry point."""

import sys
import os

# Add the project root to the path so we can import backend.app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangum import Mangum
from backend.app.main import app

# Wrap FastAPI app with Mangum for Lambda/Vercel compatibility
handler = Mangum(app, lifespan="off")
