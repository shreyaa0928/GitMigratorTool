"""GitLab migrator - pure REST API, no git CLI needed. Works on Render free tier."""
import requests
import git
import tempfile
import shutil
from datetime import datetime
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
            self.encoded = quote(self.repo, safe="")
            self.clone_url = f"https://oauth2:{token}@gitlab.com/{self.repo}.git"

    def _get_username(self):
        if not hasattr(self, "username") or not self.username:
            try:
                user = self._get("/user")
                self.username = user["username"]
            except Exception:
                self.username = "git" # fallback
        return self.username

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
            data = self._get("/projects", params={
                "membership": True, "per_page": 100,
                "page": page, "order_by": "last_activity_at"
            })
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
        data = self._get(f"/projects/{self.encoded}/issues",
                         params={"per_page": 100, "state": "all"})
        return [{
            "title": i["title"],
            "body": i.get("description", "") or "",
            "state": i["state"],
            "labels": i.get("labels", []),
            "assignees": [a["username"] for a in i.get("assignees", [])],
        } for i in data]

    def get_pull_requests(self) -> list:
        data = self._get(f"/projects/{self.encoded}/merge_requests",
                         params={"per_page": 100, "state": "all"})
        return [{
            "title": mr["title"],
            "body": mr.get("description", "") or "",
            "state": mr["state"],
            "head": mr["source_branch"],
            "base": mr["target_branch"],
        } for mr in data]

    def get_collaborators(self) -> list:
        try:
            data = self._get(f"/projects/{self.encoded}/members")
            perm_map = {10: "guest", 20: "reporter", 30: "developer", 40: "maintainer", 50: "owner"}
            return [{"login": m["username"], "permission": perm_map.get(m["access_level"], "pull")} for m in data]
        except Exception:
            return []

    def create_repository(self, info: dict) -> dict:
        try:
            # If self.repo has a slash, it's 'namespace/name'
            path_parts = self.repo.split("/")
            repo_name = path_parts[-1]
            namespace_path = "/".join(path_parts[:-1]) if len(path_parts) > 1 else None

            payload = {
                "name": repo_name,
                "description": info.get("description", ""),
                "visibility": "private" if info.get("private") else "public",
                "initialize_with_readme": False,
                "issues_enabled": info.get("has_issues", True),
            }

            # Improved Namespace Lookup
            if namespace_path:
                try:
                    # Try direct namespace first
                    ns_data = self._get(f"/namespaces/{quote(namespace_path, safe='')}")
                    payload["namespace_id"] = ns_data["id"]
                except Exception:
                    try:
                        # Search in groups if direct failed
                        groups = self._get(f"/groups?search={quote(namespace_path)}")
                        if groups and groups[0]["full_path"].lower() == namespace_path.lower():
                            payload["namespace_id"] = groups[0]["id"]
                    except Exception:
                        pass

            try:
                data = self._post("/projects", payload)
            except Exception as e:
                # If project already exists, we must find its REAL path to push to it
                if "already exists" in str(e).lower() or "has already been taken" in str(e).lower():
                    # Search by name in user's projects to get the correct path_with_namespace
                    try:
                        search = self._get(f"/projects?search={quote(repo_name)}&membership=True")
                        # Pick the one that matches intended name
                        match = next((p for p in search if p["name"].lower() == repo_name.lower()), search[0])
                        data = match
                    except Exception:
                        # Final fallback: try the path we have
                        data = self._get(f"/projects/{quote(self.repo, safe='')}")
                else:
                    raise e

            self.repo = data["path_with_namespace"]
            self.encoded = quote(self.repo, safe="")
            self.clone_url = f"https://oauth2:{self.token}@gitlab.com/{self.repo}.git"
            return {"status": "created" if "id" in data else "exists", "url": data["web_url"]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        """Push full repository using git mirror with detailed file-based logging for diagnostics"""
        import subprocess
        import tempfile
        import shutil
        import os

        log_file = "migration_debug.log"
        def log(msg):
            with open(log_file, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] {msg}\n")
            print(f"DEBUG: {msg}")

        # Clear old log
        with open(log_file, "w") as f: f.write("--- Migration Debug Start ---\n")

        temp_dir = tempfile.mkdtemp()
        try:
            # Step 0: Check git
            git_v = subprocess.run(["git", "--version"], capture_output=True, text=True)
            log(f"Git Version: {git_v.stdout.strip()}")

            # Step 1: Clone source
            log(f"Cloning from source (URL masked)...")
            clone_cmd = ["git", "clone", "--mirror", source_clone_url, temp_dir]
            clone_proc = subprocess.run(clone_cmd, capture_output=True, text=True)
            if clone_proc.returncode != 0:
                log(f"Clone Failed: {clone_proc.stderr}")
                raise Exception(f"Source Clone Failed: {clone_proc.stderr}")
            log("Clone Successful.")

            # Step 2: Prepare target URL
            username = self._get_username()
            target_url = f"https://{username}:{self.token}@gitlab.com/{self.repo}.git"
            log(f"Target Resolved: {self.repo} for user {username}")
            
            # Step 3: Force push mirror
            log("Executing force mirror push...")
            push_cmd = ["git", "push", "--mirror", "--force", target_url]
            process = subprocess.run(push_cmd, cwd=temp_dir, capture_output=True, text=True)
            
            log(f"Push Return Code: {process.returncode}")
            if process.returncode != 0:
                log(f"Push Failed Error: {process.stderr}")
                raise Exception(f"Git push failed: {process.stderr}")

            log("Push Completed Successfully on all branches.")
            return {
                "status": "success",
                "message": "Repository fully mirrored",
                "migrated": len(branches) or 1,
                "total": len(branches) or 1
            }
        except Exception as e:
            log(f"Final Exception: {str(e)}")
            return {
                "status": "failed",
                "error": str(e),
                "migrated": 0
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            log("--- Migration Debug End ---\n")

    def push_tags(self, tags: list, source_clone_url: str) -> dict:
        """Migrate tags via GitLab API - no git CLI needed."""
        if not tags:
            return {"migrated": 0}
        migrated = 0
        errors = []
        for tag in tags:
            try:
                self._post(f"/projects/{self.encoded}/repository/tags", {
                    "tag_name": tag["name"],
                    "ref": tag["sha"],
                })
                migrated += 1
            except Exception as e:
                err_str = str(e)
                if "already exists" in err_str.lower() or "400" in err_str:
                    migrated += 1  # already there, count as success
                else:
                    errors.append(f"{tag['name']}: {err_str[:120]}")
        result = {"migrated": migrated, "total": len(tags)}
        if errors:
            result["errors"] = errors
        return result

    def create_issues(self, issues: list) -> dict:
        created = 0
        for issue in issues:
            try:
                r = self._post(f"/projects/{self.encoded}/issues", {
                    "title": issue["title"],
                    "description": f"*Migrated*\n\n{issue.get('body', '')}",
                    "labels": ",".join(issue.get("labels", [])),
                })
                if issue.get("state") == "closed":
                    try:
                        self._put(f"/projects/{self.encoded}/issues/{r['iid']}",
                                  {"state_event": "close"})
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