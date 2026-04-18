#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/backends/python/api/main"
TS_CONFIG="$ROOT_DIR/frontend/tsconfig.json"
TSC_BIN="$ROOT_DIR/frontend/node_modules/.bin/tsc"
MIGRATION_FILE="$ROOT_DIR/backends/python/api/main/migrations/0011_timesheetitem_hourly_rate_snapshot.py"

FAILED=0

pass() {
  echo "[PASS] $1"
}

fail() {
  echo "[FAIL] $1"
  FAILED=1
}

echo "== Release Readiness Check =="
echo "Root: $ROOT_DIR"
echo ""

echo "1) Python syntax check (py_compile)"
if [ ! -d "$API_DIR" ]; then
  fail "API directory not found: $API_DIR"
else
  PY_FILES=()
  while IFS= read -r -d '' py_file; do
    PY_FILES+=("$py_file")
  done < <(find "$API_DIR" -type f -name "*.py" -print0)

  if [ "${#PY_FILES[@]}" -eq 0 ]; then
    fail "No Python files found in $API_DIR"
  elif python3 - "${PY_FILES[@]}" <<'PY'
import os
import py_compile
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="pycompile-check-") as tmp:
    for idx, path in enumerate(sys.argv[1:], start=1):
        cfile = os.path.join(tmp, f"check_{idx}.pyc")
        py_compile.compile(path, cfile=cfile, doraise=True)
PY
  then
    pass "Python files compiled (${#PY_FILES[@]} files)"
  else
    fail "py_compile failed"
  fi
fi

echo ""
echo "2) Frontend TypeScript check (tsc --noEmit)"
if [ ! -f "$TS_CONFIG" ]; then
  fail "tsconfig not found: $TS_CONFIG"
elif [ ! -x "$TSC_BIN" ]; then
  fail "tsc binary not found: $TSC_BIN (run npm install in frontend)"
elif "$TSC_BIN" -p "$TS_CONFIG" --noEmit --pretty false; then
  pass "TypeScript check passed"
else
  fail "TypeScript check failed"
fi

echo ""
echo "3) Migration presence check"
if [ -f "$MIGRATION_FILE" ]; then
  pass "Migration file exists: 0011_timesheetitem_hourly_rate_snapshot.py"
else
  fail "Migration file missing: $MIGRATION_FILE"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "Result: READY (local technical gate)"
  exit 0
fi

echo "Result: NOT READY (see [FAIL] lines above)"
exit 1
