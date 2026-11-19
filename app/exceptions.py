class DocumentNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Document not found.")


class DocumentStateConflictError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class DocumentApprovalValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Document cannot be approved.")


class DocumentReviewPersistenceError(Exception):
    def __init__(self) -> None:
        super().__init__("Document review operation could not be completed.")
