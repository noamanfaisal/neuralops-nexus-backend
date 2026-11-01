# NeuralOps Data Pod — large CSVs, DuckDB + S3 storage

One box that holds a team's BIG files (CSVs/parquet too large for chat or
the project folder) and answers SQL about them. NeuralOps attaches it like
any external MCP server; personas then query gigabyte files and only capped
RESULTS ever travel — never the file.

```
 person ──presigned PUT──►  SeaweedFS (S3)  ◄──s3:// reads──  DuckDB
                                 ▲                              ▲
                                 └────────── data pod (MCP, bearer) ◄── NeuralOps
```

Storage is **SeaweedFS** (Apache-2.0, S3-compatible). It replaced MinIO on
2026-11-01: MinIO retired its free edition and its images are no longer
published. The pod talks to it exactly as it did to MinIO.

Verified live on node3 (2026-11-01): a 1,000,000-row / 34 MB CSV is
described in ~1 s and a GROUP BY over all of it answers in ~0.6 s; requests
without the bearer token get 401.

## Deploy on the NeuralOps box itself (nothing public)

```bash
cd data-pod
python make_env.py            # .env with strong random secrets, never printed
docker compose -p datapod -f docker-compose.yaml -f docker-compose.neuralops.yaml up -d --build
```

The pod joins NeuralOps' docker network; its ports stay on 127.0.0.1.
In NeuralOps the URL is `http://datapod:8900/mcp`.

## Deploy on RunPod or any other docker host

```bash
cd data-pod
python make_env.py            # then edit .env: drop the 127.0.0.1: prefixes,
                              # set S3_PUBLIC_ENDPOINT if you want upload links
docker compose up -d --build
```

Expose port 8900 (the MCP server), and the S3 port (MINIO_PORT, default
9000) only if you want presigned upload/download links — put its public URL
in `S3_PUBLIC_ENDPOINT`.

## Attach to NeuralOps

`/add-mcp` → **Add server**:
- transport **HTTP**, URL `http://datapod:8900/mcp` (same box) or
  `http(s)://<pod address>:8900/mcp`
- auth **static secrets**, secret = your `DATAPOD_TOKEN`
  (read it on the box with `grep DATAPOD_TOKEN .env` — never paste it in chat)
- Refresh tools, attach to the personas that should see the data.

## The tools

| Tool | Kind | What |
|---|---|---|
| `list_files` | read | the bucket's files with sizes |
| `describe_file` | read | columns, types, row count of one file |
| `run_sql` | read | DuckDB SQL over `'s3://<bucket>/<file>'` — SELECT-shaped only, ≤500 rows back |
| `upload_url` | write | a 1-hour presigned PUT for adding a file (`curl -T file.csv '<url>'`) |
| `export_result` | write | save a query's FULL result as a new .csv/.parquet in the bucket |

Reads run silently under NeuralOps's approval gate; the two writes pause on
an approval card first — the same rule as every other tool.

## Getting big files IN

- `upload_url` from chat → the persona hands the person a curl line; the
  file goes straight to the pod, never through the AI (needs
  `S3_PUBLIC_ENDPOINT`).
- Or any S3 client against the S3 port with the pod's key/secret.

## Honest limits

- `run_sql` refuses non-SELECT statements; deriving data goes through
  `export_result` (which asks first). Results are capped at 500 rows /
  ~60k characters — aggregate, don't page.
- One bucket, one token: anyone holding the token sees all of it. Make a
  second pod for data that needs a different audience.
- Presigned links live one hour and carry full access to that one file.
