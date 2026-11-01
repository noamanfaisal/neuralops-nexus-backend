# CodeGraphContext as an HTTP tool server (owner's ask 2026-10-31).
#
# CodeGraphContext (github.com/CodeGraphContext/CodeGraphContext, MIT) indexes
# source code into an EMBEDDED graph database (no Neo4j, no DB server) and
# serves it over MCP — but only as a local command (stdio). NeuralOps dials
# tool servers over HTTP only for launch, so mcp-proxy wraps that one fixed
# command as an HTTP endpoint. No user-typed commands run here.
#
# One container per project: CodeGraphContext has no access control of its
# own and will index any path it can see, so isolation comes from mounting
# ONLY that project's code, READ-ONLY, at /code.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir codegraphcontext mcp-proxy

# The graph lives in a named volume at ~/.codegraphcontext; creating the
# folder here (owned by cgc) makes a fresh volume inherit that owner —
# otherwise docker creates it as root and the server can't write its graph.
RUN useradd --create-home cgc \
 && mkdir -p /home/cgc/.codegraphcontext \
 && chown -R cgc:cgc /home/cgc/.codegraphcontext
USER cgc
WORKDIR /home/cgc

EXPOSE 8811
CMD ["mcp-proxy", "--host", "0.0.0.0", "--port", "8811", "--pass-environment", "--", "codegraphcontext", "mcp", "start"]
