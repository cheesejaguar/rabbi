"""WorkOS SSO Authentication module."""

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from workos import WorkOSClient
from typing import Optional
import secrets

from .config import get_settings

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()

# Lazy-initialized WorkOS client
_workos_client: Optional[WorkOSClient] = None


def get_workos_client() -> WorkOSClient:
    """Get or create the WorkOS client (lazy initialization for testing)."""
    global _workos_client
    if _workos_client is None:
        _workos_client = WorkOSClient(
            api_key=settings.workos_api_key,
            client_id=settings.workos_client_id,
        )
    return _workos_client


# Session serializer
_serializer: Optional[URLSafeTimedSerializer] = None


def get_serializer() -> URLSafeTimedSerializer:
    """Get or create the session serializer."""
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(settings.session_secret_key)
    return _serializer


def create_session_token(user_data: dict) -> str:
    """Create a signed session token."""
    serializer = get_serializer()
    return serializer.dumps(user_data)


def verify_session_token(token: str, max_age: int = 86400) -> Optional[dict]:
    """Verify and decode a session token. Default max_age is 24 hours."""
    serializer = get_serializer()
    try:
        return serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[dict]:
    """Get the current user from session cookie."""
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_session_token(token)


def require_auth(request: Request) -> dict:
    """Dependency that requires authentication."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/login")
async def login(request: Request):
    """Initiate SSO login flow."""
    if not settings.workos_api_key or not settings.workos_client_id:
        raise HTTPException(
            status_code=500,
            detail="WorkOS not configured. Please set WORKOS_API_KEY and WORKOS_CLIENT_ID."
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Get authorization URL from WorkOS User Management (AuthKit)
    authorization_url = get_workos_client().user_management.get_authorization_url(
        redirect_uri=settings.workos_redirect_uri,
        state=state,
        provider="authkit",  # Use AuthKit for universal login
    )

    # Set state in cookie for verification
    response = RedirectResponse(url=authorization_url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=600,  # 10 minutes
    )
    return response


@router.get("/callback")
async def callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle SSO callback from WorkOS."""
    if error:
        raise HTTPException(status_code=400, detail=f"Authentication error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")

    # Verify state for CSRF protection
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    try:
        # Exchange code for user info using User Management API
        auth_response = get_workos_client().user_management.authenticate_with_code(
            code=code,
        )
        user = auth_response.user

        # Create session data including authentication_token for logout
        user_data = {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "access_token": auth_response.access_token,
            "refresh_token": getattr(auth_response, 'refresh_token', None),
        }

        # Create session token
        session_token = create_session_token(user_data)

        # Redirect to app with session cookie
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="session",
            value=session_token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=86400,  # 24 hours
            path="/",  # Explicit path for consistent cookie handling
        )
        # Clear the oauth state cookie
        response.delete_cookie("oauth_state")
        return response

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")


@router.get("/logout")
async def logout():
    """Log out the current user."""
    response = RedirectResponse(url="/auth/logged-out", status_code=302)
    response.delete_cookie("session", path="/")
    return response


@router.get("/logged-out")
async def logged_out():
    """Show login page."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>rebbe.dev - Login</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body {
                font-family: 'Inter', -apple-system, sans-serif;
                background: #1a1a1a;
                color: #e8e8e8;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
            }
            .container {
                text-align: center;
                padding: 40px;
            }
            .icon { font-size: 3rem; margin-bottom: 16px; color: #d4a853; }
            h1 { color: #e8e8e8; margin-bottom: 8px; font-size: 1.75rem; }
            p { color: #a0a0a0; margin-bottom: 32px; font-size: 0.95rem; }
            a {
                display: inline-block;
                background: #d4a853;
                color: white;
                padding: 14px 32px;
                border-radius: 12px;
                text-decoration: none;
                font-weight: 500;
                font-size: 1rem;
                transition: all 0.15s ease;
            }
            a:hover { background: #e4bc6a; transform: translateY(-2px); }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">&#x2721;</div>
            <h1>rebbe.dev</h1>
            <p>Sign in to continue</p>
            <a href="/auth/login">Sign In</a>
        </div>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@router.get("/me")
async def get_me(user: dict = Depends(require_auth)):
    """Get current user info."""
    return JSONResponse(content=user)


@router.get("/check")
async def check_auth(request: Request):
    """Check if user is authenticated (for frontend)."""
    user = get_current_user(request)
    if user:
        return JSONResponse(content={"authenticated": True, "user": user})
    return JSONResponse(content={"authenticated": False}, status_code=401)
