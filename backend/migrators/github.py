"""GitHub migrator using GitHub REST API v3."""
import requests
import subprocess
import tempfile
import os
from .base import BaseMigrator
 
 
class GitHubMigrator(BaseMigrator):
    BASE = "https://api.github.com"
 
    def __init__(self, token: str, repo: str):
        super().__init__(token, repo)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if repo:
            self.clone_url = f"https://{token}@github.com/{repo}.git"
 
    def _get(self, path, params=None):
        r = self.session.get(f"{self.BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()
 
    def _post(self, path, data):
        r = self.session.post(f"{self.BASE}{path}", json=data)
        r.raise_for_status()
        return r.json()
 
    def _put(self, path, data=None):
        r = self.session.put(f"{self.BASE}{path}", json=data or {})
        r.raise_for_status()
        return r.json()
 
    def list_repositories(self) -> list:
        results = []
        page = 1
        while True:
            repos = self._get("/user/repos", params={"per_page": 100, "page": page, "sort": "updated"})
            if not repos:
                break
            for r in repos:
                results.append({
                    "name": r["name"],
                    "full_name": r["full_name"],
                    "clone_url": r["clone_url"],
                    "description": r.get("description", ""),
                    "private": r["private"],
                    "default_branch": r.get("default_branch", "main"),
                })
            page += 1
            if len(repos) < 100:
                break
        return results
 
    def get_repository_info(self) -> dict:
        r = self._get(f"/repos/{self.repo}")
        self.clone_url = f"https://{self.token}@github.com/{self.repo}.git"
        return {
            "name": r["name"],
            "description": r.get("description", ""),
            "private": r["private"],
            "default_branch": r.get("default_branch", "main"),
            "homepage": r.get("homepage", ""),
            "topics": r.get("topics", []),
            "has_issues": r.get("has_issues", True),
            "has_wiki": r.get("has_wiki", False),
        }
 
    def get_branches(self) -> list:
        branches = []
        page = 1
        while True:
            data = self._get(f"/repos/{self.repo}/branches", params={"per_page": 100, "page": page})
            if not data:
                break
            for b in data:
                branches.append({"name": b["name"], "sha": b["commit"]["sha"]})
            page += 1
            if len(data) < 100:
                break
        return branches
 
    def get_tags(self) -> list:
        tags = []
        page = 1
        while True:
            data = self._get(f"/repos/{self.repo}/tags", params={"per_page": 100, "page": page})
            if not data:
                break
            for t in data:
                tags.append({"name": t["name"], "sha": t["commit"]["sha"]})
            page += 1
            if len(data) < 100:
                break
        return tags
 
    def get_issues(self) -> list:
        issues = []
        page = 1
        while True:
            data = self._get(f"/repos/{self.repo}/issues",
                             params={"state": "all", "per_page": 100, "page": page})
            if not data:
                break
            for i in data:
                if "pull_request" not in i:  # exclude PRs
                    issues.append({
                        "title": i["title"],
                        "body": i.get("body", ""),
                        "state": i["state"],
                        "labels": [lb["name"] for lb in i.get("labels", [])],
                        "assignees": [a["login"] for a in i.get("assignees", [])],
                    })
            page += 1
            if len(data) < 100:
                break
        return issues
 
    def get_pull_requests(self) -> list:
        prs = []
        page = 1
        while True:
            data = self._get(f"/repos/{self.repo}/pulls",
                             params={"state": "all", "per_page": 100, "page": page})
            if not data:
                break
            for p in data:
                prs.append({
                    "title": p["title"],
                    "body": p.get("body", ""),
                    "state": p["state"],
                    "head": p["head"]["ref"],
                    "base": p["base"]["ref"],
                })
            page += 1
            if len(data) < 100:
                break
        return prs
 
    def get_collaborators(self) -> list:
        try:
            data = self._get(f"/repos/{self.repo}/collaborators", params={"per_page": 100})
            return [{"login": u["login"], "permission": u.get("role_name", "pull")} for u in data]
        except Exception:
            return []
 
    # --- Write methods ---
 
    def create_repository(self, info: dict) -> dict:
        # Check if already exists
        try:
            existing = self._get(f"/repos/{self.repo}")
            return {"status": "exists", "url": existing["html_url"]}
        except Exception:
            pass
        user = self._get("/user")
        owner = user["login"]
        payload = {
            "name": info["name"],
            "description": info.get("description", ""),
            "private": info.get("private", False),
            "auto_init": False,
            "has_issues": info.get("has_issues", True),
            "has_wiki": info.get("has_wiki", False),
        }
        r = self._post("/user/repos", payload)
        self.repo = f"{owner}/{info['name']}"
        self.clone_url = f"https://{self.token}@github.com/{self.repo}.git"
        return {"status": "created", "url": r["html_url"]}
 
    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        if not branches:
            return {"migrated": 0}
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(["git", "clone", "--mirror", source_clone_url, tmpdir],
                               check=True, capture_output=True, timeout=300)
                subprocess.run(["git", "remote", "set-url", "origin", self.clone_url],
                               cwd=tmpdir, check=True, capture_output=True)
                refs = [f"refs/heads/{b['name']}:refs/heads/{b['name']}" for b in branches]
                subprocess.run(["git", "push", "origin", "--force"] + refs,
                               cwd=tmpdir, check=True, capture_output=True, timeout=300)
            return {"migrated": len(branches), "branches": [b["name"] for b in branches]}
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode() if e.stderr else str(e)
            return {"migrated": 0, "error": f"Git error: {err[:200]}"}
        except Exception as e:
            return {"migrated": 0, "error": str(e)}
 
    def push_tags(self, tags: list, source_clone_url: str) -> dict:
        if not tags:
            return {"migrated": 0}
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(["git", "clone", "--mirror", source_clone_url, tmpdir],
                               check=True, capture_output=True, timeout=300)
                subprocess.run(["git", "remote", "set-url", "origin", self.clone_url],
                               cwd=tmpdir, check=True, capture_output=True)
                subprocess.run(["git", "push", "origin", "--tags", "--force"],
                               cwd=tmpdir, check=True, capture_output=True, timeout=300)
            return {"migrated": len(tags), "tags": [t["name"] for t in tags]}
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode() if e.stderr else str(e)
            return {"migrated": 0, "error": f"Git error: {err[:200]}"}
        except Exception as e:
            return {"migrated": 0, "error": str(e)}
 
    def create_issues(self, issues: list) -> dict:
        created = 0
        for issue in issues:
            try:
                self._post(f"/repos/{self.repo}/issues", {
                    "title": issue["title"],
                    "body": f"*Migrated from source*\n\n{issue.get('body', '')}",
                    "labels": issue.get("labels", []),
                })
                created += 1
            except Exception:
                pass
        return {"migrated": created, "total": len(issues)}
 
    def create_pull_requests(self, prs: list) -> dict:
        created = 0
        for pr in prs:
            try:
                self._post(f"/repos/{self.repo}/pulls", {
                    "title": pr["title"],
                    "body": f"*Migrated PR*\n\n{pr.get('body', '')}",
                    "head": pr["head"],
                    "base": pr["base"],
                })
                created += 1
            except Exception:
                pass
        return {"migrated": created, "total": len(prs)}
 
    def add_collaborators(self, users: list) -> dict:
        added = 0
        for user in users:
            try:
                self._put(f"/repos/{self.repo}/collaborators/{user['login']}",
                          {"permission": user.get("permission", "pull")})
                added += 1
            except Exception:
                pass
        return {"migrated": added, "total": len(users)}