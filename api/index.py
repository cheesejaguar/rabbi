"""Vercel serverless function entry point."""

import sys
import os

# Add the project root to the path so we can import backend.app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.main import app

# Vercel expects the app to be named 'app' or 'handler'
handler = app
