import os
import base64
import requests
from datetime import datetime
from typing import Optional

GITHUB_API = "https://api.github.com"


def _get_token():
    from dotenv import load_dotenv
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_path = os.path.join(backend_dir, ".env")
    load_dotenv(env_path, override=True)
    # GitHub Upload token ONLY - do NOT fall back to LLM tokens
    return os.getenv("REPO_UPLOAD_TOKEN", "") or os.getenv("GITHUB_UPLOAD_TOKEN", "")


def _headers(token: Optional[str] = None):
    t = token or _get_token()
    return {
        "Authorization": f"token {t}",
        "Accept": "application/vnd.github.v3+json",
    }


def get_repo_owner(token: Optional[str] = None):
    """Get the authenticated user's login (owner) from the GitHub API."""
    headers = _headers(token)
    resp = requests.get(f"{GITHUB_API}/user", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()["login"]


def check_repo_exists(owner: str, repo: str, token: Optional[str] = None) -> bool:
    """Check if a repository exists and is accessible."""
    headers = _headers(token)
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=headers, timeout=10)
    print(f"[GitHub Upload] Repo check: GET /repos/{owner}/{repo} -> {resp.status_code}")
    if resp.status_code != 200:
        print(f"[GitHub Upload] Repo check response: {resp.text[:500]}")
    return resp.status_code == 200


def get_file_sha(owner: str, repo: str, path: str, token: Optional[str] = None) -> Optional[str]:
    """Get the SHA of an existing file (needed for updates). Returns None if not found."""
    headers = _headers(token)
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None


def get_file_content(owner: str, repo: str, path: str, token: Optional[str] = None) -> Optional[str]:
    """Get the decoded content of an existing file. Returns None if not found."""
    headers = _headers(token)
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=headers, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        return base64.b64decode(data["content"]).decode("utf-8")
    return None


def backup_existing_file(
    owner: str,
    repo: str,
    file_path: str,
    branch: str = "main",
    token: Optional[str] = None,
) -> Optional[str]:
    """
    If a file exists at file_path, back it up to _backup/<filename>_<timestamp>.<ext>
    inside the same directory. Returns the backup path or None if file didn't exist.
    """
    sha = get_file_sha(owner, repo, file_path, token)
    if not sha:
        return None

    content = get_file_content(owner, repo, file_path, token)
    if content is None:
        return None

    # Build backup path: same directory + _backup/ + filename_timestamp.ext
    dir_part = ""
    if "/" in file_path:
        dir_part = "/".join(file_path.split("/")[:-1])

    base_name = file_path.split("/")[-1]
    name_part, ext_part = os.path.splitext(base_name)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{name_part}_{timestamp}{ext_part}"

    backup_path = f"{dir_part}/_backup/{backup_name}" if dir_part else f"_backup/{backup_name}"

    msg = f"Backup existing {base_name} before overwrite"
    headers = _headers(token)
    body = {
        "message": msg,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }

    resp = requests.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{backup_path}",
        headers=headers,
        json=body,
        timeout=30,
    )

    if resp.status_code in (200, 201):
        print(f"[GitHub Upload] Backed up {file_path} -> {backup_path}")
        return backup_path
    else:
        print(f"[GitHub Upload] Backup failed for {file_path}: {resp.status_code} {resp.text[:200]}")
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
    headers = _headers(token)

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


def _create_blob(owner: str, repo: str, content: str, token: Optional[str] = None) -> str:
    """Create a blob and return its SHA."""
    headers = _headers(token)
    body = {
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "encoding": "base64",
    }
    resp = requests.post(f"{GITHUB_API}/repos/{owner}/{repo}/git/blobs", headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()["sha"]


def _get_branch_head(owner: str, repo: str, branch: str, token: Optional[str] = None) -> dict:
    """Get the latest commit SHA and tree SHA on a branch."""
    headers = _headers(token)
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/git/refs/heads/{branch}", headers=headers, timeout=10)
    resp.raise_for_status()
    commit_sha = resp.json()["object"]["sha"]

    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/git/commits/{commit_sha}", headers=headers, timeout=10)
    resp.raise_for_status()
    return {
        "commit_sha": commit_sha,
        "tree_sha": resp.json()["tree"]["sha"],
    }


def _get_existing_tree_entries(owner: str, repo: str, head_sha: str, token: Optional[str] = None) -> list:
    """Get the full recursive tree of blobs for the current branch head."""
    headers = _headers(token)
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{head_sha}?recursive=1",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return [
        entry
        for entry in resp.json().get("tree", [])
        if entry.get("type") == "blob"
    ]


def commit_files_separate(
    owner: str,
    repo: str,
    files: list,
    branch: str,
    token: Optional[str] = None,
) -> dict:
    """
    Commit each file with its own commit via the contents API (with backup of existing files).
    files: list of dicts {path, content, message}
    """
    results = []
    errors = []
    backups = []

    for f in files:
        path = f["path"]
        content = f["content"]
        msg = f.get("message", f"Upload {path.split('/')[-1]} via AI Performance Script Generator")
        try:
            backup_path = backup_existing_file(owner, repo, path, branch, token)
            if backup_path:
                backups.append({"original": path, "backup": backup_path})
            result = upload_file(owner, repo, path, content, msg, branch, token)
            results.append({"file": path, "url": result.get("content", {}).get("html_url", "")})
        except Exception as e:
            errors.append({"file": path, "error": str(e)})

    return {"uploaded": results, "backups": backups, "errors": errors}


def commit_files_single(
    owner: str,
    repo: str,
    files: list,
    branch: str,
    token: Optional[str] = None,
    commit_message: str = "Upload JMX, data and config via AI Performance Script Generator",
) -> dict:
    """
    Commit all files (plus backups of any existing ones) in a single commit
    using the Git Data API. Preserves all untouched files already in the repo.
    files: list of dicts {path, content}
    """
    results = []
    backups = []
    errors = []

    try:
        head = _get_branch_head(owner, repo, branch, token)
        head_sha = head["commit_sha"]
        base_tree_sha = head["tree_sha"]
    except Exception as e:
        return {
            "uploaded": results,
            "backups": backups,
            "errors": [{"file": branch, "error": f"Could not read branch head: {e}"}],
        }

    # Fetch the existing tree so untouched files are preserved
    tree_entries = []
    existing_paths = set()
    try:
        for entry in _get_existing_tree_entries(owner, repo, base_tree_sha, token):
            existing_paths.add(entry["path"])
            tree_entries.append({
                "path": entry["path"],
                "mode": entry.get("mode", "100644"),
                "type": "blob",
                "sha": entry["sha"],
            })
    except Exception as e:
        errors.append({"file": "(root)", "error": f"Could not read existing tree: {e}"})
        return {
            "uploaded": results,
            "backups": backups,
            "errors": errors + [{"file": "(root)", "error": "Aborted - cannot build tree."}],
        }

    # Build blobs for new files and backups of existing files
    all_paths = {}
    try:
        for f in files:
            path = f["path"]
            all_paths[path] = _create_blob(owner, repo, f["content"], token)

            if path in existing_paths:
                old_content = get_file_content(owner, repo, path, token)
                if old_content is not None:
                    dir_part = "/".join(path.split("/")[:-1]) if "/" in path else ""
                    base_name = path.split("/")[-1]
                    name_part, ext_part = os.path.splitext(base_name)
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    backup_name = f"{name_part}_{timestamp}{ext_part}"
                    backup_path = f"{dir_part}/_backup/{backup_name}" if dir_part else f"_backup/{backup_name}"
                    all_paths[backup_path] = _create_blob(owner, repo, old_content, token)
                    backups.append({"original": path, "backup": backup_path})
    except Exception as e:
        errors.append({"file": "(blob)", "error": f"Blob creation failed: {e}"})
        return {"uploaded": results, "backups": backups, "errors": errors}

    # Override changed/new paths in the tree
    for path, blob_sha in all_paths.items():
        tree_entries = [e for e in tree_entries if e["path"] != path]
        tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})

    # Create new tree
    try:
        headers = _headers(token)
        resp = requests.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees",
            headers=headers,
            json={"base_tree": base_tree_sha, "tree": tree_entries},
            timeout=30,
        )
        resp.raise_for_status()
        new_tree_sha = resp.json()["sha"]
    except Exception as e:
        errors.append({"file": "(tree)", "error": f"Tree creation failed: {e}"})
        return {"uploaded": results, "backups": backups, "errors": errors}

    # Create commit
    try:
        resp = requests.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/commits",
            headers=headers,
            json={"message": commit_message, "tree": new_tree_sha, "parents": [head_sha]},
            timeout=30,
        )
        resp.raise_for_status()
        new_commit_sha = resp.json()["sha"]
    except Exception as e:
        errors.append({"file": "(commit)", "error": f"Commit creation failed: {e}"})
        return {"uploaded": results, "backups": backups, "errors": errors}

    # Update the branch ref
    try:
        resp = requests.patch(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/refs/heads/{branch}",
            headers=headers,
            json={"sha": new_commit_sha, "force": False},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        errors.append({"file": branch, "error": f"Branch ref update failed: {e}"})
        return {"uploaded": results, "backups": backups, "errors": errors}

    for f in files:
        results.append({
            "file": f["path"],
            "url": f"https://github.com/{owner}/{repo}/blob/{branch}/{f['path']}",
        })

    return {"uploaded": results, "backups": backups, "errors": errors}


def upload_jmx_to_github(
    repo_name: str,
    jmx_content: str,
    jmx_filename: str = "generated_test_plan.jmx",
    csv_files: Optional[dict] = None,
    branch: str = "main",
    commit_message: Optional[str] = None,
    token: Optional[str] = None,
    subfolder: str = "",
    owner_override: Optional[str] = None,
    single_commit: bool = True,
    extra_files: Optional[dict] = None,
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
        subfolder: Optional subfolder path within the repo (e.g. "automated-usecases")
        owner_override: Optional owner override (defaults to authenticated user)
        single_commit: If True (default), commit all files (JMX + CSVs + extra)
                       in a single commit. If False, each file gets its own commit.
        extra_files: Optional dict of {filename: content_string} for additional files
                     (e.g. config.yml) committed alongside the JMX.

    Returns:
        dict with upload results
    """
    print(f"[GitHub Upload] Resolving owner...")
    owner = owner_override or get_repo_owner(token)
    print(f"[GitHub Upload] Owner: {owner}")

    print(f"[GitHub Upload] Checking repo {owner}/{repo_name}...")
    if not check_repo_exists(owner, repo_name, token):
        print(f"[GitHub Upload] ERROR: Repo {owner}/{repo_name} not found")
        return {
            "success": False,
            "error": f"Repository '{owner}/{repo_name}' not found or token lacks access. Ensure: (1) repo exists, (2) token has 'repo' scope, (3) token owner is a member of '{owner}' org.",
            "uploaded": [],
            "errors": [],
        }
    print(f"[GitHub Upload] Repo exists. Uploading files...")

    # Build path with optional subfolder prefix
    prefix = f"{subfolder.strip('/')}/" if subfolder else ""

    # Assemble the full list of files to upload
    file_defs = []  # list of dicts {path, content, message}
    file_defs.append({
        "path": f"{prefix}{jmx_filename}",
        "content": jmx_content,
        "message": commit_message or f"Upload {jmx_filename} via AI Performance Script Generator",
    })

    if csv_files:
        for filename, content in csv_files.items():
            file_defs.append({
                "path": f"{prefix}data/{filename}",
                "content": content,
                "message": f"Upload data file {filename} via AI Performance Script Generator",
            })

    if extra_files:
        for filename, content in extra_files.items():
            file_defs.append({
                "path": f"{prefix}{filename}",
                "content": content,
                "message": f"Upload {filename} via AI Performance Script Generator",
            })

    if single_commit:
        print(f"[GitHub Upload] Single-commit mode: committing {len(file_defs)} files together...")
        commit_result = commit_files_single(
            owner=owner,
            repo=repo_name,
            files=file_defs,
            branch=branch,
            token=token,
            commit_message=commit_message or "Upload JMX, data and config via AI Performance Script Generator",
        )
        results = commit_result["uploaded"]
        backups = commit_result["backups"]
        errors = commit_result["errors"]
    else:
        print(f"[GitHub Upload] Separate-commit mode: committing {len(file_defs)} files individually...")
        commit_result = commit_files_separate(
            owner=owner,
            repo=repo_name,
            files=file_defs,
            branch=branch,
            token=token,
        )
        results = commit_result["uploaded"]
        backups = commit_result["backups"]
        errors = commit_result["errors"]

    return {
        "success": len(errors) == 0,
        "owner": owner,
        "repo": repo_name,
        "branch": branch,
        "commit_mode": "single" if single_commit else "separate",
        "uploaded": results,
        "backups": backups,
        "errors": errors,
    }


def auto_upload_generated_files(
    jmx_content: str,
    jmx_filename: str = "generated_test_plan.jmx",
    csv_files: Optional[dict] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Automatically upload generated files to the configured GitHub repository.
    Configuration comes from environment variables:
      - GITHUB_UPLOAD_REPO  (e.g. "dss-pe-jmeter")
      - GITHUB_UPLOAD_PATH  (e.g. "automated-usecases")
      - GITHUB_UPLOAD_BRANCH (default: "main")
      - GITHUB_UPLOAD_OWNER  (defaults to authenticated user)
    """
    from dotenv import load_dotenv

    # Resolve backend/.env path from this file's location
    # github_uploader.py -> services/ -> app/ -> backend/
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_path = os.path.join(backend_dir, ".env")

    print(f"[GitHub Auto-Upload] Loading .env from: {env_path}")
    print(f"[GitHub Auto-Upload] .env exists: {os.path.exists(env_path)}")

    load_dotenv(env_path, override=True)

    repo = os.getenv("GITHUB_UPLOAD_REPO", "")
    subfolder = os.getenv("GITHUB_UPLOAD_PATH", "automated-usecases")
    branch = os.getenv("GITHUB_UPLOAD_BRANCH", "main")
    owner = os.getenv("GITHUB_UPLOAD_OWNER", "") or None

    # Fallback: if dotenv didn't pick it up, parse .env manually
    if not repo and os.path.exists(env_path):
        print("[GitHub Auto-Upload] dotenv returned empty repo, trying manual parse...")
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip()
                    if key == "GITHUB_UPLOAD_REPO" and val:
                        repo = val
                        os.environ["GITHUB_UPLOAD_REPO"] = val
                    elif key == "GITHUB_UPLOAD_PATH" and val:
                        subfolder = val
                        os.environ["GITHUB_UPLOAD_PATH"] = val
                    elif key == "GITHUB_UPLOAD_BRANCH" and val:
                        branch = val
                        os.environ["GITHUB_UPLOAD_BRANCH"] = val
                    elif key == "GITHUB_UPLOAD_OWNER" and val:
                        owner = val
                        os.environ["GITHUB_UPLOAD_OWNER"] = val
                    elif key == "GITHUB_UPLOAD_TOKEN" and val:
                        os.environ["GITHUB_UPLOAD_TOKEN"] = val

        print(f"[GitHub Auto-Upload] After manual parse: repo={repo}, subfolder={subfolder}, branch={branch}, owner={owner}")

    print(f"[GitHub Auto-Upload] Config: repo={repo}, subfolder={subfolder}, branch={branch}, owner={owner}")

    if not repo:
        print("[GitHub Auto-Upload] ERROR: GITHUB_UPLOAD_REPO is not set")
        return {
            "success": False,
            "error": "GITHUB_UPLOAD_REPO is not configured. Add it to backend/.env",
            "uploaded": [],
            "errors": [],
        }

    effective_token = token or _get_token()
    if not effective_token:
        print("[GitHub Auto-Upload] ERROR: No GitHub token available")
        return {
            "success": False,
            "error": "GitHub token is not configured. Add GITHUB_UPLOAD_TOKEN or REPO_UPLOAD_TOKEN to backend/.env or GitHub Actions secrets.",
            "uploaded": [],
            "errors": [],
        }

    print(f"[GitHub Auto-Upload] Token present: {len(effective_token)} chars, uploading JMX ({len(jmx_content)} bytes)...")
    return upload_jmx_to_github(
        repo_name=repo,
        jmx_content=jmx_content,
        jmx_filename=jmx_filename,
        csv_files=csv_files,
        branch=branch,
        token=effective_token,
        subfolder=subfolder,
        owner_override=owner,
    )
