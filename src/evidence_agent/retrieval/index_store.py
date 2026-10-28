"""Versioned index build: chunks + BM25 + FAISS with atomic pointer swap."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from evidence_agent.ingestion.chunker import (
    Chunk,
    chunk_document,
    validate_chunks,
)
from evidence_agent.retrieval.bm25 import BM25Index
from evidence_agent.retrieval.dense import Embedder, FaissIPIndex, HashEmbedder
from evidence_agent.storage import repositories as repo
from evidence_agent.storage.ids import new_id


CHUNKER_VERSION = "ea_chunker_0.1.0"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_project_config(root: Path) -> dict[str, Any]:
    path = root / "repo" / "configs" / "project.yaml"
    if not path.is_file():
        # tests may only have WORK_ROOT without nested repo
        alt = Path(__file__).resolve().parents[3] / "configs" / "project.yaml"
        path = alt if alt.is_file() else path
    if path.is_file():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def config_hash(cfg: dict[str, Any]) -> str:
    blob = json.dumps(
        {
            "ingestion": cfg.get("ingestion"),
            "retrieval": cfg.get("retrieval"),
            "chunker": CHUNKER_VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def version_set_hash(version_ids: list[str]) -> str:
    joined = ",".join(sorted(version_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _load_clean_and_meta(root: Path, version: dict[str, Any]) -> tuple[str, dict[str, Any], list | None]:
    norm = version.get("normalized_path")
    if not norm:
        raise ValueError(f"version {version['id']} missing normalized_path")
    # deduped versions reuse another path
    clean_path = root / norm
    if not clean_path.is_file():
        raise FileNotFoundError(clean_path)
    clean = clean_path.read_text(encoding="utf-8")
    meta_path = clean_path.parent / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    pages = None
    mapping_path = version.get("mapping_path")
    if mapping_path:
        mp = root / mapping_path
        if mp.is_file():
            mapping = json.loads(mp.read_text(encoding="utf-8"))
            if mapping.get("coordinate_system") == "pdf_page_plus_char_offset":
                # rebuild page texts from content_raw if available
                raw_path = clean_path.parent / "content_raw.txt"
                # pages stored only as lengths — use clean split by form feed if present
                # For PDF, content_clean is page-joined with \n\n in parse_pdf
                pages = []
                # Prefer reading from mapping page lengths by reconstructing from clean
                # Fall back: treat whole doc as one unit via md splitter
                if meta.get("kind") == "pdf" and mapping.get("pages"):
                    # Re-parse not available; split clean by double newlines approximating pages
                    parts = clean.split("\n\n")
                    for i, pinfo in enumerate(mapping["pages"]):
                        text = parts[i] if i < len(parts) else ""
                        pages.append({"page": pinfo["page"], "text": text})
    return clean, meta, pages


def chunk_version(
    root: Path,
    version: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
) -> list[Chunk]:
    cfg = cfg or load_project_config(root)
    ing = cfg.get("ingestion") or {}
    clean, meta, pages = _load_clean_and_meta(root, version)
    kind = meta.get("kind") or ("pdf" if pages else "md")
    return chunk_document(
        source_version_id=version["id"],
        clean_text=clean,
        kind=kind,
        pages=pages if kind == "pdf" else None,
        max_qwen=int(ing.get("max_chunk_qwen_tokens", 384)),
        max_emb=int(ing.get("max_chunk_embedding_tokens", 512)),
        overlap_qwen=int(ing.get("overlap_qwen_tokens", 64)),
    )


def build_project_index(
    conn: sqlite3.Connection,
    *,
    root: Path,
    project_id: str,
    embedder: Embedder | None = None,
    version_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Chunk all versions, build BM25+FAISS, atomically publish pointer.

    Raises ValueError if would produce empty index.
    """
    cfg = load_project_config(root)
    ret = cfg.get("retrieval") or {}
    batch = int(ret.get("indexing_batch", 16))
    threads = int((cfg.get("runtime") or {}).get("cpu_model_threads", 8))

    if version_ids is None:
        version_ids = repo.list_project_version_ids(conn, project_id)
    # Prefer latest per document to avoid indexing every historical version for "current"
    # Spec: index binds source version set — use provided/current set as-is.
    if not version_ids:
        raise ValueError("empty_version_set")

    all_chunks: list[Chunk] = []
    for vid in version_ids:
        row = conn.execute("SELECT * FROM source_versions WHERE id = ?", (vid,)).fetchone()
        if not row:
            continue
        version = dict(row)
        if version.get("parse_status") not in ("parsed", "deduped"):
            continue
        # Resolve normalized path for deduped
        if version.get("dedup_of_version_id") and not version.get("normalized_path"):
            prior = conn.execute(
                "SELECT * FROM source_versions WHERE id = ?",
                (version["dedup_of_version_id"],),
            ).fetchone()
            if prior:
                version["normalized_path"] = prior["normalized_path"]
                version["mapping_path"] = prior["mapping_path"]
        chunks = chunk_version(root, version, cfg=cfg)
        all_chunks.extend(chunks)

    if not all_chunks:
        raise ValueError("empty_chunks")

    errs = validate_chunks(all_chunks)
    if errs:
        raise ValueError("chunk_limit_violations:" + ";".join(errs[:5]))

    embedder = embedder or HashEmbedder()
    index_id = new_id("idx")
    vhash = version_set_hash(version_ids)
    chash = config_hash(cfg)
    staging = root / "data" / "indexes" / f".staging_{index_id}"
    final_dir = root / "data" / "indexes" / index_id
    chunks_dir = root / "data" / "chunks" / index_id
    staging.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Persist chunk JSONL + SQLite rows
    conn.execute("DELETE FROM chunks WHERE source_version_id IN (%s)" % ",".join("?" * len(version_ids)), version_ids)
    meta_by_id: dict[str, dict[str, Any]] = {}
    with (chunks_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for c in all_chunks:
            row = {
                "chunk_id": c.chunk_id,
                "source_version_id": c.source_version_id,
                "text": c.text,
                "page": c.page,
                "section": c.section,
                "start": c.start,
                "end": c.end,
                "parent_id": c.parent_section_id,
                "title": c.title,
                "is_fragment": c.is_fragment,
                "fragment_note": c.fragment_note,
                "kind": c.kind,
                "qwen_tokens": c.qwen_tokens,
                "emb_tokens": c.emb_tokens,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            conn.execute(
                "INSERT INTO chunks(id, source_version_id, text, page, section, start, end, parent_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    c.chunk_id,
                    c.source_version_id,
                    c.text,
                    c.page,
                    c.section,
                    c.start,
                    c.end,
                    c.parent_section_id,
                ),
            )
            meta_by_id[c.chunk_id] = row

    # BM25
    bm25 = BM25Index()
    bm25.build([(c.chunk_id, c.text) for c in all_chunks])
    (staging / "bm25.json").write_text(
        json.dumps(bm25.to_state(), ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Dense + FAISS
    faiss_idx = FaissIPIndex(embedder.dim)
    texts = [c.text for c in all_chunks]
    ids = [c.chunk_id for c in all_chunks]
    for i in range(0, len(texts), batch):
        batch_texts = texts[i : i + batch]
        batch_ids = ids[i : i + batch]
        vecs = embedder.encode(batch_texts, batch_size=batch)
        # finite + normalized checks
        if not np.isfinite(vecs).all():
            raise ValueError("non_finite_embeddings")
        norms = np.linalg.norm(vecs, axis=1)
        if np.any(np.abs(norms - 1.0) > 1e-2):
            vecs = vecs / (norms[:, None] + 1e-12)
        faiss_idx.add(batch_ids, vecs.astype(np.float32))
    faiss_idx.save(staging / "faiss")

    manifest = {
        "index_id": index_id,
        "project_id": project_id,
        "version_ids": sorted(version_ids),
        "version_set_hash": vhash,
        "chunk_count": len(all_chunks),
        "embedding_revision": embedder.revision,
        "embedding_dim": embedder.dim,
        "chunker_version": CHUNKER_VERSION,
        "config_hash": chash,
        "created_at": _utc(),
        "cpu_threads": threads,
        "indexing_batch": batch,
        "status": "ready",
    }
    (staging / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (chunks_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Atomic replace: rename staging → final
    if final_dir.exists():
        shutil.rmtree(final_dir)
    staging.rename(final_dir)

    rel_path = f"data/indexes/{index_id}"
    idx_row_id = new_id("idxrow")
    conn.execute(
        "INSERT INTO indexes(id, project_id, version_set_hash, embedding_revision, index_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (idx_row_id, project_id, vhash, embedder.revision, rel_path, _utc()),
    )

    # Pointer file (atomic write via temp)
    pointer_dir = root / "data" / "indexes"
    pointer_dir.mkdir(parents=True, exist_ok=True)
    pointer = {
        "project_id": project_id,
        "index_id": index_id,
        "index_path": rel_path,
        "version_set_hash": vhash,
        "chunk_count": len(all_chunks),
        "updated_at": _utc(),
    }
    ptr_tmp = pointer_dir / f".current_{project_id}.tmp"
    ptr_final = pointer_dir / f"current_{project_id}.json"
    ptr_tmp.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ptr_tmp.replace(ptr_final)

    # data/manifests copy
    man_dir = root / "data" / "manifests"
    man_dir.mkdir(parents=True, exist_ok=True)
    (man_dir / f"mf_index_{index_id}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "index_id": index_id,
        "index_row_id": idx_row_id,
        "chunk_count": len(all_chunks),
        "version_set_hash": vhash,
        "path": rel_path,
        "embedding_revision": embedder.revision,
        "manifest": manifest,
    }


def load_index_bundle(root: Path, project_id: str) -> dict[str, Any] | None:
    ptr = root / "data" / "indexes" / f"current_{project_id}.json"
    if not ptr.is_file():
        return None
    pointer = json.loads(ptr.read_text(encoding="utf-8"))
    index_path = root / pointer["index_path"]
    if not index_path.is_dir():
        return None
    manifest = json.loads((index_path / "manifest.json").read_text(encoding="utf-8"))
    bm25 = BM25Index.from_state(
        json.loads((index_path / "bm25.json").read_text(encoding="utf-8"))
    )
    faiss_idx = FaissIPIndex.load(index_path / "faiss")
    chunks_path = root / "data" / "chunks" / pointer["index_id"] / "chunks.jsonl"
    chunks: dict[str, dict[str, Any]] = {}
    if chunks_path.is_file():
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            chunks[row["chunk_id"]] = row
    return {
        "pointer": pointer,
        "manifest": manifest,
        "bm25": bm25,
        "faiss": faiss_idx,
        "chunks": chunks,
    }
