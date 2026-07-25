from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class PaginatedResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: PaginatedData[T]


def ok(data: T | None = None, message: str = "success") -> APIResponse[T]:
    return APIResponse(code=0, message=message, data=data)


def error(code: int, message: str) -> APIResponse:
    return APIResponse(code=code, message=message, data=None)


def paginated_ok(
    items: list,
    total: int,
    page: int = 1,
    page_size: int = 20,
    message: str = "success",
) -> PaginatedResponse:
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    paginated_data = PaginatedData(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
    return PaginatedResponse(code=0, message=message, data=paginated_data)
