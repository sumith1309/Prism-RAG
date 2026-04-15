#!/usr/bin/env bash
# One-command setup for the HW1 Qdrant CLI.
# Creates venv, installs deps, downloads RFC 7519 PDF, starts Qdrant.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "==> [1/4] Python virtual environment"
# Find a Python >= 3.10 (sentence-transformers 3.x needs it).
PYBIN=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    v=$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    major=${v%%.*}; minor=${v##*.}
    if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
      PYBIN="$cand"
      break
    fi
  fi
done
if [[ -z "$PYBIN" ]]; then
  echo "ERROR: need Python >= 3.10. Install via 'brew install python@3.12' and retry." >&2
  exit 1
fi
echo "    Using $PYBIN ($($PYBIN --version))"
if [[ ! -d .venv ]]; then
  "$PYBIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "==> [2/4] Downloading RFC 7519 PDF (JSON Web Tokens)"
PDF_PATH="data/rfc7519_jwt.pdf"
if [[ -s "$PDF_PATH" ]]; then
  echo "    PDF already exists, skipping download."
else
  URLS=(
    "https://www.rfc-editor.org/rfc/pdfrfc/rfc7519.txt.pdf"
    "https://www.rfc-editor.org/rfc/rfc7519.pdf"
    "https://datatracker.ietf.org/doc/pdf/rfc7519"
  )
  ok=0
  for u in "${URLS[@]}"; do
    echo "    Trying $u"
    if curl -fSL --retry 2 --max-time 30 -o "$PDF_PATH" "$u"; then
      if [[ -s "$PDF_PATH" ]] && head -c 4 "$PDF_PATH" | grep -q "%PDF"; then
        ok=1
        echo "    Downloaded OK."
        break
      fi
    fi
    rm -f "$PDF_PATH"
  done
  if [[ "$ok" -ne 1 ]]; then
    echo "ERROR: Could not download RFC 7519 PDF from any source." >&2
    exit 1
  fi
fi

echo "==> [3/4] Starting Qdrant via docker-compose"
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker does not appear to be running. Start Docker Desktop and retry." >&2
  exit 1
fi
docker compose up -d

echo "    Waiting for Qdrant to be ready on http://localhost:6333 ..."
for _ in $(seq 1 30); do
  if curl -sf http://localhost:6333/readyz >/dev/null; then
    echo "    Qdrant ready."
    break
  fi
  sleep 1
done

echo "==> [4/4] Done."
echo
echo "Activate the venv and run the CLI:"
echo "    source .venv/bin/activate"
echo "    python rag_cli.py"
