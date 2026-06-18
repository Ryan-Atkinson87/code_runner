class GitError(Exception):
    def __init__(self, message: str, exit_code: int = 1, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class MergeConflictError(GitError):
    pass


class PathBoundaryError(Exception):
    pass
