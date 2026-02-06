from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from puppyping.db import ensure_schema, get_connection

APP_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 40
MAX_LIMIT = 200


def _ensure_app_schema(conn) -> None:
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dog_swipes (
                id BIGSERIAL PRIMARY KEY,
                dog_id INTEGER NOT NULL,
                swipe TEXT NOT NULL CHECK (swipe IN ('left', 'right')),
                source TEXT,
                created_at_utc TIMESTAMPTZ NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_created_at
            ON dog_swipes (created_at_utc DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_dog_id
            ON dog_swipes (dog_id);
            """
        )
    conn.commit()


def _coerce_json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _jsonify(obj):
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    return _coerce_json(obj)


def _fetch_puppies(limit: int) -> list[dict]:
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (dog_id)
                        dog_id,
                        url,
                        name,
                        breed,
                        gender,
                        age_raw,
                        age_months,
                        weight_lbs,
                        location,
                        status,
                        ratings,
                        description,
                        media,
                        scraped_at_utc
                    FROM dog_profiles
                    ORDER BY dog_id, scraped_at_utc DESC
                ) latest
                ORDER BY scraped_at_utc DESC
                LIMIT %s;
                """,
                (limit,),
            )
            rows = cur.fetchall()
            columns = [col.name for col in cur.description]

    puppies: list[dict] = []
    for row in rows:
        record = dict(zip(columns, row))
        record = _jsonify(record)
        media = record.get("media") or {}
        images = media.get("images") or []
        record["primary_image"] = images[0] if images else None
        puppies.append(record)
    return puppies


def _store_swipe(dog_id: int, swipe: str, source: str | None = None) -> None:
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dog_swipes (dog_id, swipe, source, created_at_utc)
                VALUES (%s, %s, %s, %s);
                """,
                (dog_id, swipe, source, datetime.now(timezone.utc)),
            )
        conn.commit()


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/puppies":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", [DEFAULT_LIMIT])[0])
            except ValueError:
                return self._send_json(400, {"error": "limit must be an integer"})
            limit = max(1, min(MAX_LIMIT, limit))
            try:
                puppies = _fetch_puppies(limit)
            except Exception as exc:
                return self._send_json(
                    500,
                    {"error": "failed to load puppies", "detail": str(exc)},
                )
            return self._send_json(
                200, {"items": puppies, "count": len(puppies)}
            )

        if parsed.path == "/api/health":
            try:
                _fetch_puppies(1)
                return self._send_json(200, {"ok": True})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "detail": str(exc)})

        if parsed.path == "/" or "." not in parsed.path:
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/swipes":
            self.send_error(404, "Not Found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "invalid json"})

        try:
            dog_id = int(payload.get("dog_id"))
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "dog_id is required"})

        swipe = payload.get("swipe")
        if swipe not in ("left", "right"):
            return self._send_json(400, {"error": "swipe must be left or right"})

        source = payload.get("source")
        try:
            _store_swipe(dog_id, swipe, source)
        except Exception as exc:
            return self._send_json(500, {"error": "failed to store swipe", "detail": str(exc)})

        return self._send_json(201, {"ok": True})

    def log_message(self, fmt, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve PupSwipe web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"PupSwipe running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
