"""GitHub migrator - pure REST API, no git CLI needed. Works on Render free tier."""
import requests
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

    def _get_all_commits_for_branch(self, source_repo: str, branch_sha: str) -> list:
        """Fetch commits for a branch from source repo (up to 100)."""
        try:
            data = self._get(f"/repos/{source_repo}/commits",
                             params={"sha": branch_sha, "per_page": 100})
            return data
        except Exception:
            return []

    def _copy_tree(self, source_repo: str, tree_sha: str) -> str:
        """Copy a git tree from source repo to target repo recursively."""
        # Get the tree from source
        source_session = requests.Session()
        source_session.headers.update(self.session.headers)
        
        r = source_session.get(f"{self.BASE}/repos/{source_repo}/git/trees/{tree_sha}",
                               params={"recursive": "1"})
        if not r.ok:
            return None
        tree_data = r.json()
        
        new_tree = []
        for item in tree_data.get("tree", []):
            if item["type"] == "blob":
                # Get blob content from source
                blob_r = source_session.get(f"{self.BASE}/repos/{source_repo}/git/blobs/{item['sha']}")
                if blob_r.ok:
                    blob_data = blob_r.json()
                    # Create blob on target
                    try:
                        new_blob = self._post(f"/repos/{self.repo}/git/blobs", {
                            "content": blob_data["content"],
                            "encoding": blob_data["encoding"],
                        })
                        new_tree.append({
                            "path": item["path"],
                            "mode": item["mode"],
                            "type": "blob",
                            "sha": new_blob["sha"],
                        })
                    except Exception:
                        pass

        if not new_tree:
            return None

        # Create tree on target
        try:
            new_tree_r = self._post(f"/repos/{self.repo}/git/trees", {"tree": new_tree})
            return new_tree_r["sha"]
        except Exception:
            return None

    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        """
        Migrate branches using pure GitHub API.
        
        Strategy:
        1. Get commits from source branch
        2. Copy tree (files) from source to target
        3. Create commit on target pointing to copied tree
        4. Create/update branch ref pointing to new commit
        
        This works even for cross-account GitHub→GitHub migration.
        """
        if not branches:
            return {"migrated": 0}

        # Extract source repo from clone URL: https://token@github.com/owner/repo.git
        try:
            source_repo = source_clone_url.split("github.com/")[-1].replace(".git", "")
        except Exception:
            return {"migrated": 0, "error": "Could not parse source repo from clone URL"}

        migrated = 0
        errors = []

        for branch in branches:
            try:
                sha = branch["sha"]
                name = branch["name"]

                # Get the commit from source
                try:
                    commit_data = self._get(f"/repos/{source_repo}/git/commits/{sha}")
                except Exception:
                    # Try via commits API
                    commits = self._get(f"/repos/{source_repo}/commits",
                                        params={"sha": sha, "per_page": 1})
                    if not commits:
                        raise Exception(f"Cannot fetch commit {sha}")
                    commit_data = self._get(f"/repos/{source_repo}/git/commits/{commits[0]['sha']}")

                tree_sha = commit_data["tree"]["sha"]

                # Copy the tree from source to target
                new_tree_sha = self._copy_tree(source_repo, tree_sha)

                if new_tree_sha:
                    # Create a new commit on target with the copied tree
                    new_commit = self._post(f"/repos/{self.repo}/git/commits", {
                        "message": f"Migrated from {source_repo} branch {name}",
                        "tree": new_tree_sha,
                        "author": commit_data.get("author", {"name": "Migration", "email": "migration@example.com"}),
                    })
                    new_sha = new_commit["sha"]
                else:
                    # Fallback: try direct SHA reference (works if same GitHub account)
                    new_sha = sha

                # Create or update branch ref on target
                try:
                    self._get(f"/repos/{self.repo}/git/ref/heads/{name}")
                    # Exists - update
                    self.session.patch(
                        f"{self.BASE}/repos/{self.repo}/git/refs/heads/{name}",
                        json={"sha": new_sha, "force": True}
                    )
                except Exception:
                    # Create new
                    self._post(f"/repos/{self.repo}/git/refs", {
                        "ref": f"refs/heads/{name}",
                        "sha": new_sha,
                    })

                migrated += 1

            except Exception as e:
                errors.append(f"{branch['name']}: {str(e)[:150]}")

        result = {"migrated": migrated, "total": len(branches)}
        if errors:
            result["errors"] = errors
        return result

    def push_tags(self, tags: list, source_clone_url: str) -> dict:
        """Migrate tags via GitHub API."""
        if not tags:
            return {"migrated": 0}

        try:
            source_repo = source_clone_url.split("github.com/")[-1].replace(".git", "")
        except Exception:
            return {"migrated": 0, "error": "Could not parse source repo"}

        migrated = 0
        errors = []

        for tag in tags:
            try:
                sha = tag["sha"]
                name = tag["name"]

                # Try to create tag ref on target
                try:
                    self._get(f"/repos/{self.repo}/git/ref/tags/{name}")
                    # Exists - update
                    self.session.patch(
                        f"{self.BASE}/repos/{self.repo}/git/refs/tags/{name}",
                        json={"sha": sha, "force": True}
                    )
                except Exception:
                    self._post(f"/repos/{self.repo}/git/refs", {
                        "ref": f"refs/tags/{name}",
                        "sha": sha,
                    })
                migrated += 1

            except Exception as e:
                errors.append(f"{tag['name']}: {str(e)[:150]}")

        result = {"migrated": migrated, "total": len(tags)}
        if errors:
            result["errors"] = errors
        return result

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