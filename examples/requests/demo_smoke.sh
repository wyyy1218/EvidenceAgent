#!/usr/bin/env bash
# EvidenceAgent API smoke (no secrets in this file).
# Usage: export EVIDENCE_AGENT_API_TOKEN=... ; bash examples/requests/demo_smoke.sh
set -euo pipefail
API="${EVIDENCE_AGENT_API_URL:-http://127.0.0.1:6008}"
TOKEN="${EVIDENCE_AGENT_API_TOKEN:?set EVIDENCE_AGENT_API_TOKEN}"

echo "== healthz =="
curl -sS "$API/healthz"
echo

echo "== ask (short) =="
curl -sS -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"用一句话说明什么是可追溯证据。"}' \
  "$API/v1/ask"
echo

echo "== meta schema =="
curl -sS -H "Authorization: Bearer $TOKEN" "$API/v1/meta/schema" | head -c 400
echo
