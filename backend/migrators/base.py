"""Base class for all VCS migrators."""
from abc import ABC, abstractmethod


class BaseMigrator(ABC):
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo[:-4] if repo and repo.endswith(".git") else repo
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
