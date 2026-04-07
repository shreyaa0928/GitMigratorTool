"""Base class for all VCS migrators."""
from abc import ABC, abstractmethod


class BaseMigrator(ABC):
    def __init__(self, token: str, repo: str):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Clean repository path (strip browser URLs)
        clean_repo = repo.strip()
        if "://" in clean_repo:
            clean_repo = clean_repo.split("://")[-1]
        
        # Strip common domain prefixes
        for domain in ["github.com/", "gitlab.com/", "bitbucket.org/"]:
            if domain in clean_repo:
                clean_repo = clean_repo.split(domain)[-1]
        
        if clean_repo.endswith(".git"): clean_repo = clean_repo[:-4]
        self.repo = clean_repo
        self.token = token
        self.clone_url = ""

    @abstractmethod
    def list_repositories(self) -> list: pass

    @abstractmethod
    def get_repository_info(self) -> dict: pass

    @abstractmethod
    def get_branches(self) -> list: pass

    def get_specific_branches(self, names: list) -> list:
        return [b for b in self.get_branches() if b["name"] in names]

    @abstractmethod
    def get_tags(self) -> list: pass

    @abstractmethod
    def get_issues(self) -> list: pass

    @abstractmethod
    def get_pull_requests(self) -> list: pass

    @abstractmethod
    def get_collaborators(self) -> list: pass

    @abstractmethod
    def create_repository(self, info: dict) -> dict: pass

    @abstractmethod
    def push_branches(self, branches: list, source_clone_url: str) -> dict: pass

    @abstractmethod
    def push_tags(self, tags: list, source_clone_url: str) -> dict: pass

    @abstractmethod
    def create_issues(self, issues: list) -> dict: pass

    @abstractmethod
    def create_pull_requests(self, prs: list) -> dict: pass

    @abstractmethod
    def add_collaborators(self, users: list) -> dict: pass
