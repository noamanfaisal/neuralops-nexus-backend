# NeuralOps data pod — DuckDB over MinIO, spoken as MCP (see server.py).
FROM python:3.12-slim

WORKDIR /pod
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .

# DuckDB's httpfs extension is fetched on first use; bake it so the pod
# works without outbound internet at run time.
RUN python -c "import duckdb; con = duckdb.connect(); con.execute('INSTALL httpfs')"

EXPOSE 8900
CMD ["python", "server.py"]
