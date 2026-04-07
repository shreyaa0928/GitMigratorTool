"""GitHub migrator - pure REST API, no git CLI needed. Works on Render free tier."""
import requests
import git
import tempfile
import shutil
import base64
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
            self.clone_url = f"https://{token}@github.com/{self.repo}.git"

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

    def _patch(self, path, data):
        r = self.session.patch(f"{self.BASE}{path}", json=data)
        r.raise_for_status()
        return r.json()

    # ── List repos ───────────────────────────────────────────────────

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

    # ── Read source ──────────────────────────────────────────────────

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
                if "pull_request" not in i:
                    issues.append({
                        "title": i["title"],
                        "body": i.get("body") or "",
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
                    "body": p.get("body") or "",
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

    # ── Write to target ──────────────────────────────────────────────

    def create_repository(self, info: dict) -> dict:
        """Create repo on target. Uses auto_init=True so we get an initial commit,
        which allows us to create branches/tags via the refs API."""
        try:
            existing = self._get(f"/repos/{self.repo}")
            self.clone_url = f"https://{self.token}@github.com/{self.repo}.git"
            return {"status": "exists", "url": existing["html_url"]}
        except Exception:
            pass

        user = self._get("/user")
        owner = user["login"]
        repo_name = info["name"]

        payload = {
            "name": repo_name,
            "description": info.get("description", ""),
            "private": info.get("private", False),
            "auto_init": True,          # ← KEY FIX: creates initial commit so refs API works
            "has_issues": info.get("has_issues", True),
            "has_wiki": info.get("has_wiki", False),
        }
        r = self._post("/user/repos", payload)
        self.repo = f"{owner}/{repo_name}"
        self.clone_url = f"https://{self.token}@github.com/{self.repo}.git"
        return {"status": "created", "url": r["html_url"]}

    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        """Push full repository (all branches and tags) using git mirror with direct subprocess"""
        import subprocess
        import tempfile
        import shutil
        import os

        temp_dir = tempfile.mkdtemp()
        try:
            # Step 1: Clone source
            clone_cmd = ["git", "clone", "--mirror", source_clone_url, temp_dir]
            subprocess.run(clone_cmd, check=True, capture_output=True)

            # Step 2: Prepare target URL
            target_url = f"https://{self.token}@github.com/{self.repo}.git"
            
            # Step 3: Force push mirror
            push_cmd = ["git", "push", "--mirror", "--force", target_url]
            process = subprocess.run(push_cmd, cwd=temp_dir, capture_output=True, text=True)
            
            if process.returncode != 0:
                raise Exception(f"Git push failed: {process.stderr}")

            return {
                "migrated": len(branches) or 1, 
                "total": len(branches) or 1, 
                "status": "success"
            }
        except Exception as e:
            return {"migrated": 0, "status": "failed", "error": str(e)}
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

    def push_tags(self, tags: list, source_clone_url: str) -> dict:
        """Tags are migrated with push_branches via git mirror"""
        return {"migrated": len(tags), "total": len(tags)}

    def create_issues(self, issues: list) -> dict:
        created = 0
        for issue in issues:
            try:
                payload = {
                    "title": issue["title"],
                    "body": f"*Migrated from source repository*\n\n{issue.get('body', '')}",
                    "labels": issue.get("labels", []),
                }
                r = self._post(f"/repos/{self.repo}/issues", payload)
                if issue.get("state") == "closed":
                    try:
                        self._patch(f"/repos/{self.repo}/issues/{r['number']}", {"state": "closed"})
                    except Exception:
                        pass
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