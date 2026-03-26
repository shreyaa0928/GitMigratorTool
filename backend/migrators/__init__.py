"""Base class for all VCS migrators."""
from abc import ABC, abstractmethod


class BaseMigrator(ABC):
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo  # format: "owner/repo" or full URL
        self.clone_url = ""

    @abstractmethod
    def list_repositories(self) -> list:
        """Return list of {'name', 'full_name', 'clone_url', 'description', 'private'}"""
        pass

    @abstractmethod
    def get_repository_info(self) -> dict:
        pass

    @abstractmethod
    def get_branches(self) -> list:
        pass

    def get_specific_branches(self, names: list) -> list:
        all_branches = self.get_branches()
        return [b for b in all_branches if b["name"] in names]

    @abstractmethod
    def get_tags(self) -> list:
        pass

    @abstractmethod
    def get_issues(self) -> list:
        pass

    @abstractmethod
    def get_pull_requests(self) -> list:
        pass

    @abstractmethod
    def get_collaborators(self) -> list:
        pass

    @abstractmethod
    def create_repository(self, info: dict) -> dict:
        pass

    @abstractmethod
    def push_branches(self, branches: list, source_clone_url: str) -> dict:
        pass

    @abstractmethod
    def push_tags(self, tags: list, source_clone_url: str) -> dict:
        pass

    @abstractmethod
    def create_issues(self, issues: list) -> dict:
        pass

    @abstractmethod
    def create_pull_requests(self, prs: list) -> dict:
        pass

    @abstractmethod
    def add_collaborators(self, users: list) -> dict:
        pass
