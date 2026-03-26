"""GitLab migrator using GitLab REST API v4."""
import requests
import subprocess
import tempfile
from urllib.parse import quote
from .base import BaseMigrator


class GitLabMigrator(BaseMigrator):
    BASE = "https://gitlab.com/api/v4"

    def __init__(self, token: str, repo: str):
        super().__init__(token, repo)
        self.session = requests.Session()
        self.session.headers.update({
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        })
        if repo:
            self.encoded = quote(repo, safe="")
            self.clone_url = f"https://oauth2:{token}@gitlab.com/{repo}.git"

    def _get(self, path, params=None):
        r = self.session.get(f"{self.BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path, data):
        r = self.session.post(f"{self.BASE}{path}", json=data)
        r.raise_for_status()
        return r.json()

    def list_repositories(self) -> list:
        results = []
        page = 1
        while True:
            data = self._get("/projects", params={"membership": True, "per_page": 100, "page": page, "order_by": "last_activity_at"})
            if not data:
                break
            for p in data:
                results.append({
                    "name": p["name"],
                    "full_name": p["path_with_namespace"],
                    "clone_url": p["http_url_to_repo"],
                    "description": p.get("description", ""),
                    "private": p["visibility"] == "private",
                    "default_branch": p.get("default_branch", "main"),
                })
            page += 1
            if len(data) < 100:
                break
        return results

    def get_repository_info(self) -> dict:
        p = self._get(f"/projects/{self.encoded}")
        self.clone_url = f"https://oauth2:{self.token}@gitlab.com/{self.repo}.git"
        return {
            "name": p["name"],
            "description": p.get("description", ""),
            "private": p["visibility"] == "private",
            "default_branch": p.get("default_branch", "main"),
            "homepage": p.get("web_url", ""),
            "topics": p.get("tag_list", []),
            "has_issues": p.get("issues_enabled", True),
            "has_wiki": p.get("wiki_enabled", False),
        }

    def get_branches(self) -> list:
        data = self._get(f"/projects/{self.encoded}/repository/branches", params={"per_page": 100})
        return [{"name": b["name"], "sha": b["commit"]["id"]} for b in data]

    def get_tags(self) -> list:
        data = self._get(f"/projects/{self.encoded}/repository/tags", params={"per_page": 100})
        return [{"name": t["name"], "sha": t["commit"]["id"]} for t in data]

    def get_issues(self) -> list:
        data = self._get(f"/projects/{self.encoded}/issues", params={"per_page": 100, "state": "all"})
        return [{
            "title": i["title"],
            "body": i.get("description", ""),
            "state": i["state"],
            "labels": i.get("labels", []),
            "assignees": [a["username"] for a in i.get("assignees", [])],
        } for i in data]

    def get_pull_requests(self) -> list:
        data = self._get(f"/projects/{self.encoded}/merge_requests", params={"per_page": 100, "state": "all"})
        return [{
            "title": mr["title"],
            "body": mr.get("description", ""),
            "state": mr["state"],
            "head": mr["source_branch"],
            "base": mr["target_branch"],
        } for mr in data]

    def get_collaborators(self) -> list:
        data = self._get(f"/projects/{self.encoded}/members")
        perm_map = {10: "guest", 20: "reporter", 30: "developer", 40: "maintainer", 50: "owner"}
        return [{"login": m["username"], "permission": perm_map.get(m["access_level"], "pull")} for m in data]

    def create_repository(self, info: dict) -> dict:
        data = self._post("/projects", {
            "name": info["name"],
            "description": info.get("description", ""),
            "visibility": "private" if info.get("private") else "public",
            "initialize_with_readme": False,
            "issues_enabled": info.get("has_issues", True),
        })
        self.repo = data["path_with_namespace"]
        self.encoded = quote(self.repo, safe="")
        self.clone_url = f"https://oauth2:{self.token}@gitlab.com/{self.repo}.git"
        return {"status": "created", "url": data["web_url"]}

    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        if not branches:
            return {"migrated": 0}
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "clone", "--mirror", source_clone_url, tmpdir], check=True, capture_output=True)
            subprocess.run(["git", "remote", "set-url", "origin", self.clone_url], cwd=tmpdir, check=True, capture_output=True)
            refs = [f"refs/heads/{b['name']}:refs/heads/{b['name']}" for b in branches]
            subprocess.run(["git", "push", "origin", "--force"] + refs, cwd=tmpdir, check=True, capture_output=True)
        return {"migrated": len(branches), "branches": [b["name"] for b in branches]}

    def push_tags(self, tags: list, source_clone_url: str) -> dict:
        if not tags:
            return {"migrated": 0}
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "clone", "--mirror", source_clone_url, tmpdir], check=True, capture_output=True)
            subprocess.run(["git", "remote", "set-url", "origin", self.clone_url], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "--tags", "--force"], cwd=tmpdir, check=True, capture_output=True)
        return {"migrated": len(tags)}

    def create_issues(self, issues: list) -> dict:
        created = 0
        for issue in issues:
            try:
                self._post(f"/projects/{self.encoded}/issues", {
                    "title": issue["title"],
                    "description": f"*Migrated*\n\n{issue.get('body', '')}",
                    "labels": ",".join(issue.get("labels", [])),
                })
                created += 1
            except Exception:
                pass
        return {"migrated": created, "total": len(issues)}

    def create_pull_requests(self, prs: list) -> dict:
        created = 0
        for pr in prs:
            try:
                self._post(f"/projects/{self.encoded}/merge_requests", {
                    "title": pr["title"],
                    "description": f"*Migrated PR*\n\n{pr.get('body', '')}",
                    "source_branch": pr["head"],
                    "target_branch": pr["base"],
                })
                created += 1
            except Exception:
                pass
        return {"migrated": created, "total": len(prs)}

    def add_collaborators(self, users: list) -> dict:
        added = 0
        for user in users:
            try:
                user_data = self._get(f"/users?username={user['login']}")
                if user_data:
                    self._post(f"/projects/{self.encoded}/members", {
                        "user_id": user_data[0]["id"],
                        "access_level": 30,
                    })
                    added += 1
            except Exception:
                pass
        return {"migrated": added, "total": len(users)}
