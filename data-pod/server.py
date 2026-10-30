"""
NeuralOps DATA POD — DuckDB over MinIO, spoken as MCP (owner's ask,
2026-10-30: "we will make one runpod with duckdb + minio to handle large
csv").

WHAT IT IS: one small box (RunPod, or any docker host) that holds a team's
BIG files — CSVs too large to ride chat or the project folder — in MinIO
(S3-compatible object store), and answers questions about them with DuckDB,
which reads s3:// natively and only pulls the bytes a query touches. NeuralOps
attaches it like any external MCP server (transport http, a bearer token as
the client_secret); personas then query gigabyte CSVs without one byte of the
file entering the chat, the engine, or the model — only RESULTS travel, capped.

THE TOOLS (read/write split matters — NeuralOps's approval gate reads the
readOnlyHint: reads run silently, writes pause on a card):
  read  : list_files · describe_file · run_sql (SELECT-shaped only)
  write : upload_url (a presigned PUT for the person's browser/curl)
          · export_result (COPY a query's result to a new file in the bucket)

AUTH: every request needs  Authorization: Bearer $DATAPOD_TOKEN  — exactly
what NeuralOps sends for a static-secrets MCP server (the token goes in the
server dialog's client_secret). No token configured = the pod refuses to
start rather than run open.

ENV (docker-compose.yaml sets the in-pod ones):
  DATAPOD_TOKEN        the bearer token (required)
  S3_ENDPOINT          internal MinIO address   (default http://minio:9000)
  S3_PUBLIC_ENDPOINT   MinIO as the OUTSIDE world reaches it — presigned
                       upload/download URLs are signed against THIS host, so
                       it must be the pod's public address for MinIO's port
                       (required for upload_url/download links to work)
  S3_KEY / S3_SECRET   MinIO credentials        (default minioadmin/…)
  S3_BUCKET            the one bucket           (default datapod)
  PORT                 the MCP port             (default 8900, path /mcp)
"""
from __future__ import annotations

import json
import os
import re

import boto3
import duckdb
from botocore.client import Config as BotoConfig
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

# ── config ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DATAPOD_TOKEN", "")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://minio:9000")
S3_PUBLIC_ENDPOINT = os.environ.get("S3_PUBLIC_ENDPOINT", "")
S3_KEY = os.environ.get("S3_KEY", "minioadmin")
S3_SECRET = os.environ.get("S3_SECRET", "minioadmin")
BUCKET = os.environ.get("S3_BUCKET", "datapod")
PORT = int(os.environ.get("PORT", "8900"))

MAX_ROWS = 500          # run_sql hands back at most this many rows
MAX_CELL_CHARS = 400    # one cell's text cap
MAX_OUTPUT_CHARS = 60_000  # the whole result's cap — a model context is finite
URL_TTL_SECONDS = 3600  # presigned links live one hour

if not TOKEN:
    raise SystemExit("DATAPOD_TOKEN is not set — refusing to run an open data pod.")


def _s3(public: bool = False):
    """Two clients on purpose: presigned URLs must be SIGNED against the host
    the outside world will actually dial (S3_PUBLIC_ENDPOINT); everything the
    pod does itself goes over the internal address."""
    endpoint = (S3_PUBLIC_ENDPOINT if public else "") or S3_ENDPOINT
    return boto3.client(
        "s3", endpoint_url=endpoint,
        aws_access_key_id=S3_KEY, aws_secret_access_key=S3_SECRET,
        config=BotoConfig(signature_version="s3v4"), region_name="us-east-1",
    )


def _duck() -> duckdb.DuckDBPyConnection:
    """A FRESH in-memory DuckDB per call (no state bleeds between questions),
    with httpfs pointed at MinIO so s3://bucket/file.csv just works."""
    from urllib.parse import urlsplit
    parts = urlsplit(S3_ENDPOINT)
    con = duckdb.connect(":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_endpoint='{parts.netloc}';")
    con.execute(f"SET s3_use_ssl={'true' if parts.scheme == 'https' else 'false'};")
    con.execute("SET s3_url_style='path';")  # MinIO speaks path-style
    con.execute(f"SET s3_access_key_id='{S3_KEY}';")
    con.execute(f"SET s3_secret_access_key='{S3_SECRET}';")
    return con


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\- ]{0,200}$")


def _check_name(name: str) -> str | None:
    if not _SAFE_NAME.match(name or "") or ".." in name:
        return "That file name is not allowed (letters, digits, . _ / - and spaces; no leading dot, no ..)."
    return None


# run_sql is READ-ONLY by shape: only question-shaped statements pass, so the
# gate may run it silently. Writing has its own two tools, which pause.
_READ_SQL = re.compile(r"^\s*(select|with|describe|show|summarize|explain|from|pivot|unpivot)\b", re.I)
_FORBIDDEN_SQL = re.compile(r"\b(copy|export|install|load|attach|detach|create|insert|update|delete|drop|alter|set|pragma|call)\b", re.I)


def _rows_to_text(cursor) -> str:
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(MAX_ROWS)
    more = bool(cursor.fetchone())
    def cell(v):
        s = "" if v is None else str(v)
        return s if len(s) <= MAX_CELL_CHARS else s[: MAX_CELL_CHARS - 1] + "…"
    out = {"columns": columns,
           "rows": [[cell(v) for v in row] for row in rows],
           "row_count_shown": len(rows),
           "truncated": more}
    text = json.dumps(out, ensure_ascii=False, default=str)
    if len(text) > MAX_OUTPUT_CHARS:
        # drop rows until it fits — a bounded answer beats a broken one
        while out["rows"] and len(text) > MAX_OUTPUT_CHARS:
            out["rows"] = out["rows"][: max(1, len(out["rows"]) // 2)]
            out["truncated"] = True
            out["row_count_shown"] = len(out["rows"])
            text = json.dumps(out, ensure_ascii=False, default=str)
    return text


mcp = FastMCP("NeuralOps Data Pod", host="0.0.0.0", port=PORT)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_files(prefix: str = "") -> str:
    """The files in the pod's bucket — name, size, last modified. Big CSVs
    live HERE, not in chat; query them with run_sql."""
    s3 = _s3()
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix or "", MaxKeys=500)
    except Exception as exc:  # noqa: BLE001
        return f"list_files failed: {type(exc).__name__}: {exc}"
    rows = [{"name": o["Key"], "size": o["Size"], "modified": o["LastModified"].isoformat()}
            for o in resp.get("Contents", [])]
    return json.dumps({"files": rows, "truncated": bool(resp.get("IsTruncated"))},
                      ensure_ascii=False)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def describe_file(name: str) -> str:
    """A file's columns and types (DuckDB's sniff) plus its row count — read
    this before writing SQL against it. Works for .csv, .parquet and .json."""
    problem = _check_name(name)
    if problem:
        return problem
    con = _duck()
    try:
        source = f"s3://{BUCKET}/{name}"
        cursor = con.execute(f"DESCRIBE SELECT * FROM '{source}'")
        schema = [{"column": r[0], "type": r[1]} for r in cursor.fetchall()]
        count = con.execute(f"SELECT count(*) FROM '{source}'").fetchone()[0]
        return json.dumps({"file": name, "rows": count, "schema": schema}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return f"describe_file failed: {type(exc).__name__}: {exc}"
    finally:
        con.close()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def run_sql(sql: str) -> str:
    """Query the bucket's files with DuckDB SQL — reference a file as
    's3://<bucket>/<name>' (e.g. SELECT … FROM 's3://datapod/sales.csv').
    READ-ONLY by design: only SELECT-shaped statements run (writes go through
    export_result, which asks first). At most 500 rows come back — aggregate
    rather than page."""
    if not _READ_SQL.match(sql or "") or _FORBIDDEN_SQL.search(sql or ""):
        return ("run_sql is read-only: start with SELECT/WITH/DESCRIBE/SHOW/"
                "SUMMARIZE, and use export_result to write a result file.")
    con = _duck()
    try:
        return _rows_to_text(con.execute(sql))
    except Exception as exc:  # noqa: BLE001
        return f"run_sql failed: {type(exc).__name__}: {exc}"
    finally:
        con.close()


@mcp.tool()
def upload_url(name: str) -> str:
    """A one-hour presigned PUT link for adding a file to the pod — hand it to
    the person: `curl -T <local file> '<url>'` (or any HTTP client). The file
    never travels through chat or the AI; it goes straight to the pod."""
    problem = _check_name(name)
    if problem:
        return problem
    if not S3_PUBLIC_ENDPOINT:
        return ("upload_url needs S3_PUBLIC_ENDPOINT set on the pod (the "
                "outside address of MinIO) — ask the admin to configure it.")
    try:
        url = _s3(public=True).generate_presigned_url(
            "put_object", Params={"Bucket": BUCKET, "Key": name}, ExpiresIn=URL_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        return f"upload_url failed: {type(exc).__name__}: {exc}"
    return json.dumps({"name": name, "method": "PUT", "url": url,
                       "expires_in": URL_TTL_SECONDS,
                       "how": f"curl -T your-file.csv '{url}'"}, ensure_ascii=False)


@mcp.tool()
def export_result(sql: str, name: str) -> str:
    """Run a SELECT and save its FULL result as a new file in the bucket
    (.csv or .parquet by extension) — the road for derived datasets; the
    download link comes back. The query itself must still be SELECT-shaped."""
    problem = _check_name(name)
    if problem:
        return problem
    if not name.lower().endswith((".csv", ".parquet")):
        return "Name the export .csv or .parquet."
    if not _READ_SQL.match(sql or "") or _FORBIDDEN_SQL.search(sql or ""):
        return "The query half must be SELECT-shaped."
    fmt = "(FORMAT PARQUET)" if name.lower().endswith(".parquet") else "(FORMAT CSV, HEADER)"
    con = _duck()
    try:
        con.execute(f"COPY ({sql}) TO 's3://{BUCKET}/{name}' {fmt}")
    except Exception as exc:  # noqa: BLE001
        return f"export_result failed: {type(exc).__name__}: {exc}"
    finally:
        con.close()
    link = ""
    if S3_PUBLIC_ENDPOINT:
        try:
            link = _s3(public=True).generate_presigned_url(
                "get_object", Params={"Bucket": BUCKET, "Key": name}, ExpiresIn=URL_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            link = ""
    return json.dumps({"saved": name, "download_url": link or None,
                       "expires_in": URL_TTL_SECONDS if link else None}, ensure_ascii=False)


# ── bearer wall + boot ───────────────────────────────────────────────────────
app = mcp.streamable_http_app()


class BearerWall:
    """Every request shows the pod's token — exactly the Authorization header
    NeuralOps sends for a static-secrets MCP server."""

    def __init__(self, inner):
        self._inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization", "") != f"Bearer {TOKEN}":
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self._inner(scope, receive, send)


def _ensure_bucket() -> None:
    s3 = _s3()
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:  # noqa: BLE001 — first boot: make it
        s3.create_bucket(Bucket=BUCKET)


if __name__ == "__main__":
    import uvicorn
    _ensure_bucket()
    uvicorn.run(BearerWall(app), host="0.0.0.0", port=PORT)
