import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.github_uploader import upload_jmx_to_github, get_repo_owner

router = APIRouter()


class GitHubUploadRequest(BaseModel):
    repo_name: str
    branch: str = "main"
    jmx_content: str
    jmx_filename: str = "generated_test_plan.jmx"
    csv_files: Optional[dict] = None
    commit_message: Optional[str] = None
    subfolder: str = ""
    owner_override: Optional[str] = None


@router.post("/github/upload")
def upload_to_github(request: GitHubUploadRequest):
    """Upload generated JMX and data files to a GitHub repository."""
    from dotenv import load_dotenv
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(backend_dir, ".env"))

    token = os.getenv("GITHUB_UPLOAD_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "GITHUB_TOKEN_NOT_CONFIGURED",
                "message": "GitHub token is not configured. Add GITHUB_UPLOAD_TOKEN to backend/.env",
            },
        )

    try:
        result = upload_jmx_to_github(
            repo_name=request.repo_name,
            jmx_content=request.jmx_content,
            jmx_filename=request.jmx_filename,
            csv_files=request.csv_files,
            branch=request.branch,
            commit_message=request.commit_message,
            token=token,
            subfolder=request.subfolder,
            owner_override=request.owner_override,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/repos")
def list_repos():
    """List accessible repositories for the authenticated user."""
    from dotenv import load_dotenv
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(backend_dir, ".env"))

    token = os.getenv("GITHUB_UPLOAD_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitHub token not configured.",
        )

    try:
        owner = get_repo_owner(token)
        import requests as req
        resp = req.get(
            f"https://api.github.com/user/repos",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
            params={"per_page": 100, "sort": "updated"},
            timeout=10,
        )
        resp.raise_for_status()
        repos = [{"name": r["name"], "full_name": r["full_name"], "private": r["private"]} for r in resp.json()]
        return {"owner": owner, "repos": repos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
