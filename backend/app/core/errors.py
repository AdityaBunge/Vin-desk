from fastapi import HTTPException, status


class DomainError(HTTPException):
    """Business-rule violation surfaced to the client as a 4xx with a readable message."""

    def __init__(self, detail: str | dict, code: int = status.HTTP_409_CONFLICT):
        super().__init__(status_code=code, detail=detail)


def not_found(what: str = "Record") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)


def forbidden(detail: str = "You do not have permission to perform this action") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)
