import os
import base64
import requests
from typing import Optional

GITHUB_API = "https://api.github.com"


def _get_token():
    from dotenv import load_dotenv
    load_dotenv()
    return os.getenv("GITHUB_TOKEN", "")


def _headers():
    token = _get_token()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def get_repo_owner(token: Optional[str] = None):
    """Get the authenticated user's login (owner) from the GitHub API."""
    headers = _headers()
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.get(f"{GITHUB_API}/user", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()["login"]


def check_repo_exists(owner: str, repo: str, token: Optional[str] = None) -> bool:
    """Check if a repository exists and is accessible."""
    headers = _headers()
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=headers, timeout=10)
    return resp.status_code == 200


def get_file_sha(owner: str, repo: str, path: str, token: Optional[str] = None) -> Optional[str]:
    """Get the SHA of an existing file (needed for updates). Returns None if not found."""
    headers = _headers()
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None


def upload_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
    token: Optional[str] = None,
) -> dict:
    """
    Create or update a file in a GitHub repository.
    Returns the GitHub API response dict.
    """
    headers = _headers()
    if token:
        headers["Authorization"] = f"token {token}"

    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }

    # If file exists, we need its SHA to update it
    sha = get_file_sha(owner, repo, path, token)
    if sha:
        body["sha"] = sha

    resp = requests.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def upload_jmx_to_github(
    repo_name: str,
    jmx_content: str,
    jmx_filename: str = "generated_test_plan.jmx",
    csv_files: Optional[dict] = None,
    branch: str = "main",
    commit_message: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Upload JMX script and optional CSV data files to a GitHub repo.

    Args:
        repo_name: Repository name (e.g. "automated-ncs-api")
        jmx_content: The JMX XML string
        jmx_filename: Name for the JMX file
        csv_files: Optional dict of {filename: content_string} for data files
        branch: Branch to upload to
        commit_message: Custom commit message
        token: Optional override for GitHub token

    Returns:
        dict with upload results
    """
    owner = get_repo_owner(token)

    if not check_repo_exists(owner, repo_name, token):
        return {
            "success": False,
            "error": f"Repository '{owner}/{repo_name}' not found or not accessible.",
        }

    results = []
    errors = []

    # Upload JMX file
    jmx_path = jmx_filename
    msg = commit_message or f"Upload {jmx_filename} via AI Performance Script Generator"
    try:
        result = upload_file(owner, repo_name, jmx_path, jmx_content, msg, branch, token)
        results.append({"file": jmx_path, "url": result.get("content", {}).get("html_url", "")})
    except Exception as e:
        errors.append({"file": jmx_path, "error": str(e)})

    # Upload CSV files under data/ folder
    if csv_files:
        for filename, content in csv_files.items():
            data_path = f"data/{filename}"
            data_msg = f"Upload data file {filename} via AI Performance Script Generator"
            try:
                result = upload_file(owner, repo_name, data_path, content, data_msg, branch, token)
                results.append({"file": data_path, "url": result.get("content", {}).get("html_url", "")})
            except Exception as e:
                errors.append({"file": data_path, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "owner": owner,
        "repo": repo_name,
        "branch": branch,
        "uploaded": results,
        "errors": errors,
    }
