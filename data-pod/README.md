# NeuralOps Data Pod — large CSVs, DuckDB + MinIO

One box that holds a team's BIG files (CSVs/parquet too large for chat or
the project folder) and answers SQL about them. NeuralOps attaches it like
any external MCP server; personas then query gigabyte files and only capped
RESULTS ever travel — never the file.

```
 person ──presigned PUT──►  MinIO (S3)  ◄──s3:// reads──  DuckDB
                                 ▲                           ▲
                                 └──────── data pod (MCP, bearer) ◄── NeuralOps
```

## Deploy (RunPod or any docker host)

```bash
cd data-pod
cp .env.example .env        # set DATAPOD_TOKEN + S3_SECRET (+ S3_PUBLIC_ENDPOINT)
docker compose up -d --build
```

On RunPod: expose ports 8900 (the MCP server) and 9000 (MinIO, only if you
want presigned upload/download links; put its public proxy URL in
`S3_PUBLIC_ENDPOINT`). 9001 is MinIO's web console for dragging files in by
hand — expose at your own taste.

## Attach to NeuralOps

Intelligence → MCP tab → **Add server**:
- transport **http**, URL `http://<pod address>:8900/mcp`
- auth **static secrets**, client_secret = your `DATAPOD_TOKEN`
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
  file goes straight to the pod, never through the AI.
- Or the MinIO console (port 9001) — drag and drop.
- Or any S3 client against port 9000 with the pod's key/secret.

## Honest limits

- `run_sql` refuses non-SELECT statements; deriving data goes through
  `export_result` (which asks first). Results are capped at 500 rows /
  ~60k characters — aggregate, don't page.
- One bucket, one token: anyone holding the token sees all of it. Make a
  second pod for data that needs a different audience.
- Presigned links live one hour and carry full access to that one file.
