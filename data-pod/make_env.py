"""Create data-pod/.env with strong random secrets — values are never printed.

    python make_env.py            # on the box, or:
    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/w python:3.12-slim python /w/make_env.py /w

Refuses to touch an existing .env (secrets are created once, never
regenerated). Ports bind to 127.0.0.1 — the pod is reached over NeuralOps'
own docker network (docker-compose.neuralops.yaml); presigned upload links
stay off until S3_PUBLIC_ENDPOINT is set by hand.

Read the token back for the MCP dialog with:  grep DATAPOD_TOKEN .env
"""
import os
import secrets
import sys

folder = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, ".env")
if os.path.exists(path):
    sys.exit(f"{path} already exists — refusing to overwrite secrets.")

lines = [
    "# Created by make_env.py — keep it private; never commit it.",
    f"DATAPOD_TOKEN={secrets.token_urlsafe(48)}",
    "S3_KEY=datapod-admin",
    f"S3_SECRET={secrets.token_urlsafe(32)}",
    "S3_PUBLIC_ENDPOINT=",
    "DATAPOD_PORT=127.0.0.1:8900",
    "MINIO_PORT=127.0.0.1:9000",
]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"wrote {path} (values not shown)")
