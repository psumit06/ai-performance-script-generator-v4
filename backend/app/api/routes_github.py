import os
import secrets
import time
import requests as req
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
from app.services.github_uploader import upload_jmx_to_github, get_repo_owner

router = APIRouter()

# In-memory store for OAuth tokens and pending states
_oauth_states = {}  # state -> {token, expires_at}
_oauth_tokens = {}  # session_id -> {token, user, expires_at}


def _load_env():
    from dotenv import load_dotenv
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(backend_dir, ".env"), override=True)


def _get_oauth_config():
    _load_env()
    client_id = os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")
    return client_id, client_secret


# ── OAuth: Step 1 – Generate auth URL ──────────────────────────────────────
@router.get("/github/auth")
def github_auth():
    """Redirect to GitHub OAuth authorization page."""
    client_id, _ = _get_oauth_config()
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="GITHUB_OAUTH_CLIENT_ID is not configured. Create a GitHub OAuth App and add it to backend/.env",
        )

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"created_at": time.time()}

    auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope=repo"
        f"&state={state}"
    )
    return RedirectResponse(url=auth_url)


# ── OAuth: Step 2 – GitHub redirects back with code ─────────────────────────
@router.get("/github/callback")
def github_callback(code: str = "", state: str = ""):
    """Handle GitHub OAuth callback, exchange code for token."""
    if not code or not state:
        return HTMLResponse("<h2>OAuth failed: missing code or state</h2>", status_code=400)

    if state not in _oauth_states:
        return HTMLResponse("<h2>OAuth failed: invalid or expired state</h2>", status_code=400)

    del _oauth_states[state]

    client_id, client_secret = _get_oauth_config()
    if not client_secret:
        return HTMLResponse("<h2>GITHUB_OAUTH_CLIENT_SECRET not configured</h2>", status_code=500)

    # Exchange code for access token
    resp = req.post(
        "https://github.com/login/oauth/access_token",
        json={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )

    data = resp.json()
    access_token = data.get("access_token", "")
    if not access_token:
        error = data.get("error_description", data.get("error", "Unknown error"))
        return HTMLResponse(f"<h2>OAuth token exchange failed</h2><p>{error}</p>", status_code=400)

    # Get user info
    user_resp = req.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {access_token}", "Accept": "application/json"},
        timeout=10,
    )
    user_login = user_resp.json().get("login", "unknown") if user_resp.status_code == 200 else "unknown"

    # Store token with a session ID
    session_id = secrets.token_urlsafe(16)
    _oauth_tokens[session_id] = {
        "token": access_token,
        "user": user_login,
        "expires_at": time.time() + 3600,  # 1 hour
    }

    # Return HTML that sends the session_id back to the opener window
    html = f"""<!DOCTYPE html>
<html><head><title>GitHub Auth</title></head>
<body style="background:#0a0813;color:#e0e0e0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
<div style="text-align:center;">
    <h2 style="color:#00f2fe;">GitHub Authorized</h2>
    <p>Logged in as <strong>{user_login}</strong></p>
    <p>You can close this window.</p>
</div>
<script>
try {{
    if (window.opener) {{
        window.opener.postMessage({{ type: 'github-auth-complete', session_id: '{session_id}' }}, '*');
    }}
}} catch(e) {{}}
setTimeout(function() {{ window.close(); }}, 1500);
</script>
</body></html>"""
    return HTMLResponse(content=html)


# ── OAuth: Step 3 – Frontend polls for token ────────────────────────────────
@router.get("/github/token/{session_id}")
def get_oauth_token(session_id: str):
    """Return the OAuth token for a completed session."""
    session = _oauth_tokens.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if time.time() > session["expires_at"]:
        del _oauth_tokens[session_id]
        raise HTTPException(status_code=410, detail="Session expired")
    return {"token": session["token"], "user": session["user"]}


# ── Upload endpoint (uses OAuth token or env token) ────────────────────────
class GitHubUploadRequest(BaseModel):
    repo_name: str
    branch: str = "main"
    jmx_content: str
    jmx_filename: str = "generated_test_plan.jmx"
    csv_files: Optional[dict] = None
    commit_message: Optional[str] = None
    subfolder: str = ""
    owner_override: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/github/upload")
def upload_to_github(request: GitHubUploadRequest):
    """Upload generated JMX and data files to a GitHub repository."""
    _load_env()

    # Resolve token: prefer OAuth session, fall back to env token
    token = None
    if request.session_id:
        session = _oauth_tokens.get(request.session_id)
        if session and time.time() <= session["expires_at"]:
            token = session["token"]

    if not token:
        token = os.getenv("GITHUB_UPLOAD_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")

    if not token:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "GITHUB_TOKEN_NOT_CONFIGURED",
                "message": "No GitHub token available. Sign in via OAuth or add GITHUB_UPLOAD_TOKEN to backend/.env",
            },
        )

    owner = request.owner_override or os.getenv("GITHUB_UPLOAD_OWNER", "") or None
    base_path = os.getenv("GITHUB_UPLOAD_PATH", "usecases")
    subfolder = f"{base_path}/{request.subfolder.strip('/')}" if request.subfolder else base_path

    try:
        result = upload_jmx_to_github(
            repo_name=request.repo_name,
            jmx_content=request.jmx_content,
            jmx_filename=request.jmx_filename,
            csv_files=request.csv_files,
            branch=request.branch,
            commit_message=request.commit_message,
            token=token,
            subfolder=subfolder,
            owner_override=owner,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/repos")
def list_repos():
    """List accessible repositories for the authenticated user."""
    _load_env()

    token = os.getenv("GITHUB_UPLOAD_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitHub token not configured.",
        )

    try:
        owner = get_repo_owner(token)
        resp = req.get(
            "https://api.github.com/user/repos",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
            params={"per_page": 100, "sort": "updated"},
            timeout=10,
        )
        resp.raise_for_status()
        repos = [{"name": r["name"], "full_name": r["full_name"], "private": r["private"]} for r in resp.json()]
        return {"owner": owner, "repos": repos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
