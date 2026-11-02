# brain-core as a stdio MCP server, for registries that start the server and introspect it.
# A real install uses install.sh (Hindsight runs as a host service); this image has no
# Hindsight, so the agent runs on the vault, SQLite and the relations table only.
#
#   docker build -t brain-core .
#   docker run -i --rm brain-core            # speaks MCP on stdin/stdout
#   docker run -i --rm -v "$PWD/agent:/agent" brain-core   # persist the agent folder

FROM python:3.12-slim

WORKDIR /src
COPY pyproject.toml README.md LICENSE uv.lock ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /src

WORKDIR /
RUN brain init Atlas --path /agent --user you >/dev/null

ENTRYPOINT ["brain", "serve", "/agent"]
