#!/bin/bash
# Starts the LitDigest server and opens it in the browser.
# Called by LitDigest.app; also fine to run on its own.
set -u
cd "$(dirname "$0")"

# --detach: start the server in the background and return, so the window that
# ran this can close. Without it the server runs in the foreground and closing
# that window stops it.
DETACH=0
[ "${1:-}" = "--detach" ] && DETACH=1

# Finder launches an app with only /usr/bin:/bin:/usr/sbin:/sbin, which has
# neither Homebrew's pdftotext nor a conda python.
export PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:$PATH"

PORT=8000
URL="http://127.0.0.1:$PORT"
# A double-clicked app gets a bare PATH, so the interpreter that has the packages
# is recorded in .python-path at setup time rather than looked up.
PY="${LITDIGEST_PYTHON:-}"
[ -z "$PY" ] && [ -s .python-path ] && PY="$(cat .python-path)"
[ -x "$PY" ] || PY="$(command -v python3)"

say(){ osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"LitDigest\"" >/dev/null 2>&1; }

if ! command -v pdftotext >/dev/null 2>&1; then
  say "LitDigest needs pdftotext to read PDFs.\n\nInstall it with:\n    brew install poppler"
  exit 1
fi

if [ -z "$PY" ] || ! "$PY" -c "import fastapi, uvicorn, pandas, openpyxl, fitz" 2>/dev/null; then
  say "LitDigest can't find its Python packages.\n\nOpen Terminal in this folder and run:\n    pip install -r requirements.txt\n\nIf you use conda, set LITDIGEST_PYTHON to that python first."
  exit 1
fi

if ! grep -qE '^XAI_API_KEY=.+' .env 2>/dev/null; then
  say "No API key found.\n\nPut your xAI key in the .env file in this folder:\n    XAI_API_KEY=xai-..."
  exit 1
fi

# /api/health is liveness only. /api/papers re-reads the spreadsheet and can run
# model calls, so it is far too expensive to poll -- but a server started before
# health existed does not answer it, so the already-running test falls back to it.
alive(){ curl -fsS -m 3 "$URL/api/health" >/dev/null 2>&1; }

mkdir -p cache

# A server started before /api/health existed answers the page but not the routes
# the page now needs -- it serves index.html off disk while having no /vendor mount,
# so every equation turns into its own LaTeX source. Clicking the icon used to hand
# over to it forever, because "something is listening" looked like success. Stop it
# and start again instead.
if ! alive && curl -fsS -m 20 "$URL/api/papers" >/dev/null 2>&1; then
  echo "stopping a server from an older version of LitDigest" >> cache/launch.log
  curl -fsS -m 5 -X POST "$URL/api/quit" >/dev/null 2>&1
  for _ in $(seq 1 20); do
    curl -fsS -m 2 "$URL/api/papers" >/dev/null 2>&1 || break
    sleep 0.5
  done
fi

# already running, and current? just bring it up
if alive; then
  open "$URL"; exit 0
fi

if [ "$DETACH" = "1" ]; then
  nohup "$PY" -m uvicorn server:app --host 127.0.0.1 --port "$PORT" >> cache/server.log 2>&1 &
  SERVER=$!
  disown $SERVER 2>/dev/null || true
else
  "$PY" -m uvicorn server:app --host 127.0.0.1 --port "$PORT" >> cache/server.log 2>&1 &
  SERVER=$!
  trap 'kill $SERVER 2>/dev/null' EXIT INT TERM
fi

for _ in $(seq 1 60); do
  alive && break
  kill -0 $SERVER 2>/dev/null || { say "The server failed to start.\n\nLast lines of cache/server.log:\n\n$(tail -6 cache/server.log)"; exit 1; }
  sleep 0.5
done

open "$URL"
[ "$DETACH" = "1" ] && exit 0
wait $SERVER
