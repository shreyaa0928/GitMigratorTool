"""Bitbucket migrator using Bitbucket Cloud REST API 2.0."""
import requests
import subprocess
import tempfile
from .base import BaseMigrator


class BitBucketMigrator(BaseMigrator):
    BASE = "https://api.bitbucket.org/2.0"

    def __init__(self, token: str, repo: str):
        super().__init__(token, repo)
        self.session = requests.Session()
        # Bitbucket uses App Password or OAuth token
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        if repo:
            self.clone_url = f"https://x-token-auth:{token}@bitbucket.org/{repo}.git"
        self._workspace = repo.split("/")[0] if "/" in repo else ""

    def _get(self, path, params=None):
        r = self.session.get(f"{self.BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path, data):
        r = self.session.post(f"{self.BASE}{path}", json=data)
        r.raise_for_status()
        return r.json()

    def _paginate(self, path, params=None):
        results = []
        url = f"{self.BASE}{path}"
        while url:
            r = self.session.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("values", []))
            url = data.get("next")
            params = None  # Only use params for first request
        return results

    def list_repositories(self) -> list:
        try:
            user = self._get("/user")
            workspace = user.get("account_id", "")
        except Exception:
            workspace = self._workspace
        repos = self._paginate(f"/repositories/{workspace}", params={"pagelen": 100, "sort": "-updated_on"})
        return [{
            "name": r["name"],
            "full_name": r["full_name"],
            "clone_url": next((l["href"] for l in r["links"]["clone"] if l["name"] == "https"), ""),
            "description": r.get("description", ""),
            "private": r["is_private"],
            "default_branch": r["mainbranch"]["name"] if r.get("mainbranch") else "main",
        } for r in repos]

    def get_repository_info(self) -> dict:
        r = self._get(f"/repositories/{self.repo}")
        self.clone_url = f"https://x-token-auth:{self.token}@bitbucket.org/{self.repo}.git"
        return {
            "name": r["name"],
            "description": r.get("description", ""),
            "private": r["is_private"],
            "default_branch": r["mainbranch"]["name"] if r.get("mainbranch") else "main",
            "homepage": r["links"]["html"]["href"],
            "topics": [],
            "has_issues": True,
            "has_wiki": False,
        }

    def get_branches(self) -> list:
        data = self._paginate(f"/repositories/{self.repo}/refs/branches", params={"pagelen": 100})
        return [{"name": b["name"], "sha": b["target"]["hash"]} for b in data]

    def get_tags(self) -> list:
        data = self._paginate(f"/repositories/{self.repo}/refs/tags", params={"pagelen": 100})
        return [{"name": t["name"], "sha": t["target"]["hash"]} for t in data]

    def get_issues(self) -> list:
        try:
            data = self._paginate(f"/repositories/{self.repo}/issues", params={"pagelen": 100})
            return [{
                "title": i["title"],
                "body": i.get("content", {}).get("raw", ""),
                "state": "open" if i["status"] in ("new", "open") else "closed",
                "labels": [i.get("component", {}).get("name", "")] if i.get("component") else [],
                "assignees": [],
            } for i in data]
        except Exception:
            return []

    def get_pull_requests(self) -> list:
        try:
            data = self._paginate(f"/repositories/{self.repo}/pullrequests", params={"pagelen": 100, "state": "ALL"})
            return [{
                "title": pr["title"],
                "body": pr.get("description", ""),
                "state": pr["state"].lower(),
                "head": pr["source"]["branch"]["name"],
                "base": pr["destination"]["branch"]["name"],
            } for pr in data]
        except Exception:
            return []

    def get_collaborators(self) -> list:
        try:
            data = self._get(f"/repositories/{self.repo}/permissions-config/users")
            return [{"login": u["user"]["account_id"], "permission": u.get("permission", "read")} for u in data.get("values", [])]
        except Exception:
            return []

    def create_repository(self, info: dict) -> dict:
        workspace = self._workspace or "me"
        slug = info["name"].lower().replace(" ", "-")
        data = self._post(f"/repositories/{workspace}/{slug}", {
            "scm": "git",
            "name": info["name"],
            "description": info.get("description", ""),
            "is_private": info.get("private", False),
        })
        self.repo = data["full_name"]
        self.clone_url = f"https://x-token-auth:{self.token}@bitbucket.org/{self.repo}.git"
        return {"status": "created", "url": data["links"]["html"]["href"]}

    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        if not branches:
            return {"migrated": 0}
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "clone", "--mirror", source_clone_url, tmpdir], check=True, capture_output=True)
            subprocess.run(["git", "remote", "set-url", "origin", self.clone_url], cwd=tmpdir, check=True, capture_output=True)
            refs = [f"refs/heads/{b['name']}:refs/heads/{b['name']}" for b in branches]
            subprocess.run(["git", "push", "origin", "--force"] + refs, cwd=tmpdir, check=True, capture_output=True)
        return {"migrated": len(branches)}

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
                self._post(f"/repositories/{self.repo}/issues", {
                    "title": issue["title"],
                    "content": {"raw": f"*Migrated*\n\n{issue.get('body', '')}"},
                })
                created += 1
            except Exception:
                pass
        return {"migrated": created, "total": len(issues)}

    def create_pull_requests(self, prs: list) -> dict:
        created = 0
        for pr in prs:
            try:
                self._post(f"/repositories/{self.repo}/pullrequests", {
                    "title": pr["title"],
                    "description": f"*Migrated*\n\n{pr.get('body', '')}",
                    "source": {"branch": {"name": pr["head"]}},
                    "destination": {"branch": {"name": pr["base"]}},
                })
                created += 1
            except Exception:
                pass
        return {"migrated": created, "total": len(prs)}

    def add_collaborators(self, users: list) -> dict:
        return {"migrated": 0, "total": len(users), "note": "Bitbucket team permissions require workspace admin"}
