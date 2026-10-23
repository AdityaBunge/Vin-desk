import csv
import io
from typing import Annotated

from fastapi import Query
from fastapi.responses import Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

PageNum = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


def paginate(db: Session, stmt: Select, page: int, page_size: int, unique: bool = False) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    result = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size))
    items = result.unique().all() if unique else result.all()
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}


def like(term: str) -> str:
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def csv_response(filename: str, columns: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        # Prefix formula-like cells so spreadsheets do not execute them (CSV injection).
        writer.writerow(
            [f"'{c}" if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in row]
        )
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
