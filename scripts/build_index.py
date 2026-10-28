"""CLI: build versioned BM25+FAISS index for a project (S12)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence_agent.retrieval.dense import HashEmbedder, SentenceTransformerEmbedder
from evidence_agent.retrieval.index_store import build_project_index
from evidence_agent.storage.db import connect, work_root
from evidence_agent.storage.migrate import ensure_db


def resolve_embedder(root: Path, *, fake: bool):
    if fake:
        return HashEmbedder()
    emb_root = root / "models" / "embedding"
    if not emb_root.is_dir():
        raise SystemExit(f"embedding model dir missing: {emb_root}")
    revs = sorted([p for p in emb_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not revs:
        raise SystemExit("no embedding revision under models/embedding")
    return SentenceTransformerEmbedder(revs[0], device="cpu", threads=8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--fake-embedder", action="store_true", help="HashEmbedder for tests/CI without weights")
    args = ap.parse_args()

    root = work_root()
    ensure_db(root)
    embedder = resolve_embedder(root, fake=args.fake_embedder)
    conn = connect(root)
    try:
        result = build_project_index(conn, root=root, project_id=args.project_id, embedder=embedder)
        conn.commit()
    finally:
        conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
