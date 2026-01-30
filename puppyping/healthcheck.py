from __future__ import annotations

from .db import ensure_schema, get_connection


def main() -> None:
    with get_connection() as conn:
        ensure_schema(conn)
    print("OK")


if __name__ == "__main__":
    main()
