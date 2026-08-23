#!/bin/bash
# Set up and run the yente MCP server by hand -- what mcp/yente-mcp.service
# runs as a unit, laid out as a script so it can be exercised (or run on a
# box with no systemd, e.g. a laptop) without installing the unit first.
#
#   mcp/run.sh setup     create mcp/.venv and install mcp/requirements.txt
#   mcp/run.sh start     run yente-mcp in the foreground, Ctrl-C to stop
#
# Reads YENTE_BASE_URL from the environment if already set (so a caller can
# point this at a different yente for a moment); otherwise defaults to the
# same address deploy/vinzor.service's VINZOR_SCREENING_URL names --
# 127.0.0.1:8090, where deploy/screening/docker-compose.yml binds yente's
# port. See mcp/README.md for why that is a value kept in step by hand
# rather than a shared setting, same as the two files above already do.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

case "${1:-}" in
    setup)
        python3.11 -m venv "$VENV" 2>/dev/null || python3 -m venv "$VENV"
        "$VENV/bin/pip" install -r "$HERE/requirements.txt"
        echo "installed into $VENV -- vinzor's own environment is untouched"
        ;;
    start)
        if [ ! -x "$VENV/bin/yente-mcp" ]; then
            echo "no venv at $VENV yet -- run: mcp/run.sh setup" >&2
            exit 1
        fi
        export YENTE_BASE_URL="${YENTE_BASE_URL:-http://127.0.0.1:8090}"
        export YENTE_MCP_TRANSPORT="${YENTE_MCP_TRANSPORT:-http}"
        export YENTE_MCP_HOST="${YENTE_MCP_HOST:-127.0.0.1}"
        export YENTE_MCP_PORT="${YENTE_MCP_PORT:-8091}"
        export YENTE_MCP_NAME="${YENTE_MCP_NAME:-vinzor-yente}"
        # See mcp/yente-mcp.service's own comment: a real defect, hit on
        # Windows during development, in how the package reads its bundled
        # model file. Harmless to set unconditionally.
        export PYTHONUTF8=1
        echo "starting yente-mcp on http://$YENTE_MCP_HOST:$YENTE_MCP_PORT, forwarding to $YENTE_BASE_URL"
        exec "$VENV/bin/yente-mcp"
        ;;
    *)
        echo "usage: mcp/run.sh {setup|start}" >&2
        exit 2
        ;;
esac
