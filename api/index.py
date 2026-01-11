"""Vercel serverless function entry point."""

from http.server import BaseHTTPRequestHandler
import json


class handler(BaseHTTPRequestHandler):
    """Simple HTTP handler for Vercel."""

    def do_GET(self):
        """Handle GET requests."""
        # Lazy import to avoid detection issues
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        try:
            from mangum import Mangum
            from backend.app.main import app as fastapi_app

            # Create Mangum handler
            mangum_handler = Mangum(fastapi_app, lifespan="off")

            # Build the event for Mangum
            event = {
                "httpMethod": "GET",
                "path": self.path,
                "headers": dict(self.headers),
                "queryStringParameters": {},
                "body": None,
                "isBase64Encoded": False,
            }

            # Get response from Mangum
            response = mangum_handler(event, None)

            # Send response
            self.send_response(response.get("statusCode", 200))
            for key, value in response.get("headers", {}).items():
                self.send_header(key, value)
            self.end_headers()

            body = response.get("body", "")
            if response.get("isBase64Encoded"):
                import base64
                body = base64.b64decode(body)
            elif isinstance(body, str):
                body = body.encode()

            self.wfile.write(body)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            error_response = json.dumps({"error": str(e), "type": type(e).__name__})
            self.wfile.write(error_response.encode())

    def do_POST(self):
        """Handle POST requests."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        try:
            from mangum import Mangum
            from backend.app.main import app as fastapi_app

            # Read body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b""

            # Create Mangum handler
            mangum_handler = Mangum(fastapi_app, lifespan="off")

            # Build the event for Mangum
            event = {
                "httpMethod": "POST",
                "path": self.path,
                "headers": dict(self.headers),
                "queryStringParameters": {},
                "body": body.decode() if body else None,
                "isBase64Encoded": False,
            }

            # Get response from Mangum
            response = mangum_handler(event, None)

            # Send response
            self.send_response(response.get("statusCode", 200))
            for key, value in response.get("headers", {}).items():
                self.send_header(key, value)
            self.end_headers()

            resp_body = response.get("body", "")
            if response.get("isBase64Encoded"):
                import base64
                resp_body = base64.b64decode(resp_body)
            elif isinstance(resp_body, str):
                resp_body = resp_body.encode()

            self.wfile.write(resp_body)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            error_response = json.dumps({"error": str(e), "type": type(e).__name__})
            self.wfile.write(error_response.encode())
