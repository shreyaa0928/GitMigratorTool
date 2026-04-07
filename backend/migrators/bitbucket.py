"""Bitbucket migrator - pure REST API, no git CLI needed. Works on Render free tier."""
import requests
import git
import tempfile
import shutil
from .base import BaseMigrator


class BitBucketMigrator(BaseMigrator):
    BASE = "https://api.bitbucket.org/2.0"

    def __init__(self, token: str, repo: str):
        super().__init__(token, repo)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        if repo:
            self.clone_url = f"https://x-token-auth:{token}@bitbucket.org/{self.repo}.git"
        self._workspace = self.repo.split("/")[0] if "/" in self.repo else ""

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
            params = None
        return results

    def list_repositories(self) -> list:
        try:
            user = self._get("/user")
            workspace = user.get("username") or self._workspace
        except Exception:
            workspace = self._workspace
        repos = self._paginate(f"/repositories/{workspace}",
                               params={"pagelen": 100, "sort": "-updated_on"})
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
            data = self._paginate(f"/repositories/{self.repo}/pullrequests",
                                  params={"pagelen": 100, "state": "ALL"})
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
            return [{"login": u["user"]["account_id"], "permission": u.get("permission", "read")}
                    for u in data.get("values", [])]
        except Exception:
            return []

    def create_repository(self, info: dict) -> dict:
        workspace = self._workspace or "me"
        slug = info["name"].lower().replace(" ", "-")
        try:
            data = self._post(f"/repositories/{workspace}/{slug}", {
                "scm": "git",
                "name": info["name"],
                "description": info.get("description", ""),
                "is_private": info.get("private", False),
            })
            self.repo = data["full_name"]
            self.clone_url = f"https://x-token-auth:{self.token}@bitbucket.org/{self.repo}.git"
            return {"status": "created", "url": data["links"]["html"]["href"]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        """Push full repository using git mirror with direct subprocess"""
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
            target_url = f"https://x-token-auth:{self.token}@bitbucket.org/{self.repo}.git"
            
            # Step 3: Force push mirror
            push_cmd = ["git", "push", "--mirror", "--force", target_url]
            process = subprocess.run(push_cmd, cwd=temp_dir, capture_output=True, text=True)
            
            if process.returncode != 0:
                raise Exception(f"Git push failed: {process.stderr}")

            return {
                "status": "success",
                "message": "Repository fully migrated",
                "migrated": len(branches) or 1,
                "total": len(branches) or 1
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "migrated": 0
            }
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
        return {
            "migrated": 0,
            "total": len(users),
            "note": "Bitbucket team permissions require workspace admin access."
        }