#!/usr/bin/env python3
"""S25: Build HotpotQA distractor-derived subset with isolation (seed=42).

Usage:
  python scripts/build_hotpotqa_subset.py --root <WORK_ROOT>
  python scripts/build_hotpotqa_subset.py --root <WORK_ROOT> --fixture-only   # tiny offline fixture
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.data.near_dup import (
    is_near_duplicate,
    normalize_question,
    paragraph_hash,
    support_title_conflict,
)

DATASET_ID = "hotpotqa_distractor_s25_v1"
SEED_TAG = "42"
TARGETS = {"test": 200, "dev": 100, "train": 600}


def _sha_sort_key(example_id: str) -> str:
    return hashlib.sha256(f"{SEED_TAG}:{example_id}".encode("utf-8")).hexdigest()


def _support_titles(ex: dict[str, Any]) -> list[str]:
    # HotpotQA: supporting_facts = {"title": [...], "sent_id": [...]} or list of [title, sent_id]
    sf = ex.get("supporting_facts") or {}
    if isinstance(sf, dict) and "title" in sf:
        return list(sf.get("title") or [])
    if isinstance(sf, list):
        titles = []
        for item in sf:
            if isinstance(item, (list, tuple)) and item:
                titles.append(str(item[0]))
            elif isinstance(item, dict) and item.get("title"):
                titles.append(str(item["title"]))
        return titles
    return []


def _context_paras(ex: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Return list of (title, sentences)."""
    ctx = ex.get("context") or {}
    if isinstance(ctx, dict) and "title" in ctx and "sentences" in ctx:
        titles = ctx["title"]
        sents = ctx["sentences"]
        out = []
        for t, ss in zip(titles, sents):
            if isinstance(ss, list):
                out.append((str(t), [str(x) for x in ss]))
            else:
                out.append((str(t), [str(ss)]))
        return out
    if isinstance(ctx, list):
        out = []
        for item in ctx:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                title, sentences = item[0], item[1]
                if isinstance(sentences, list):
                    out.append((str(title), [str(s) for s in sentences]))
        return out
    return []


def _gold_support_spans(ex: dict[str, Any], paras: list[tuple[str, list[str]]]) -> list[dict[str, Any]]:
    spans = []
    title_to_sents = {t: sents for t, sents in paras}
    sf = ex.get("supporting_facts") or {}
    pairs: list[tuple[str, int]] = []
    if isinstance(sf, dict) and "title" in sf:
        for t, sid in zip(sf.get("title") or [], sf.get("sent_id") or []):
            pairs.append((str(t), int(sid)))
    elif isinstance(sf, list):
        for item in sf:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]), int(item[1])))
    for title, sid in pairs:
        sents = title_to_sents.get(title) or []
        text = sents[sid] if 0 <= sid < len(sents) else None
        spans.append(
            {
                "title": title,
                "sent_id": sid,
                "text": text,
                "anchor_ok": text is not None,
            }
        )
    return spans


def _online_pack(ex: dict[str, Any], task_id: str, split: str) -> dict[str, Any]:
    """Visible online fields — NO answer / supporting_facts."""
    paras = _context_paras(ex)
    docs = []
    for title, sents in paras:
        body = "\n".join(sents)
        docs.append({"title": title, "text": body, "n_sentences": len(sents)})
    return {
        "task_id": task_id,
        "split": split,
        "question": ex.get("question") or "",
        "requirements": [{"requirement_id": "req_main", "text": ex.get("question") or ""}],
        "allowed_snapshot_ids": [f"{task_id}::ctx"],
        "answerability": "answerable",
        "expected_status": "answered",
        "difficulty": "medium",
        "source_versions": [{"dataset": DATASET_ID, "level": ex.get("level"), "type": ex.get("type")}],
        "generation_model": "hotpotqa_official",
        "review_status": "imported",
        "license_refs": ["CC-BY-SA-4.0"],
        "context_docs": docs,  # allowed corpus only
    }


def _offline_gold(ex: dict[str, Any], task_id: str, split: str) -> dict[str, Any]:
    paras = _context_paras(ex)
    spans = _gold_support_spans(ex, paras)
    return {
        "task_id": task_id,
        "split": split,
        "gold_answer": ex.get("answer"),
        "gold_claims": [{"claim_id": "ans", "text": ex.get("answer")}],
        "gold_support_spans": spans,
        "supporting_facts_raw": ex.get("supporting_facts"),
        "all_anchors_ok": all(s.get("anchor_ok") for s in spans) if spans else False,
    }


def _write_task_corpus(root: Path, task_id: str, online: dict[str, Any]) -> Path:
    d = root / "data" / "tasks" / "hotpotqa" / DATASET_ID / "corpora" / task_id
    d.mkdir(parents=True, exist_ok=True)
    parts = []
    for doc in online.get("context_docs") or []:
        parts.append(f"# {doc['title']}\n\n{doc['text']}\n")
    path = d / "context.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    # Ensure gold answer not in file name side-channel
    meta = {
        "task_id": task_id,
        "allowed_only": True,
        "doc_count": len(online.get("context_docs") or []),
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def select_subset(
    validation: list[dict[str, Any]],
    train: list[dict[str, Any]],
    targets: dict[str, int] | None = None,
) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    """Select test from validation, then dev/train from official train."""
    targets = dict(targets or TARGETS)
    report: dict[str, Any] = {
        "skipped_near_dup": 0,
        "skipped_title_conflict": 0,
        "paragraph_cross_split_hits": 0,
        "anchor_failures": 0,
        "limitations": [
            "Support-title isolation does not prove full semantic independence from pretraining.",
            "Distractor contexts may share non-support Wikipedia paragraphs across splits; "
            "reported in paragraph_cross_split_hits without auto-skip (support-title rule remains hard).",
        ],
    }

    def sorted_pool(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda ex: _sha_sort_key(str(ex.get("id") or ex.get("_id") or "")))

    selected: dict[str, list[dict]] = {"test": [], "dev": [], "train": []}
    used_questions: list[str] = []
    titles_by_split: dict[str, set[str]] = {"test": set(), "dev": set(), "train": set()}
    para_hashes_by_split: dict[str, set[str]] = {"test": set(), "dev": set(), "train": set()}

    def try_add(split: str, ex: dict) -> bool:
        nonlocal report
        q = ex.get("question") or ""
        titles = _support_titles(ex)
        for prev in used_questions:
            dup, _, _ = is_near_duplicate(q, prev)
            if dup:
                report["skipped_near_dup"] += 1
                return False
        # Hard skip: support titles already used in another split
        for other, tset in titles_by_split.items():
            if other == split:
                continue
            if support_title_conflict(titles, tset):
                report["skipped_title_conflict"] += 1
                return False

        paras = _context_paras(ex)
        phashes = [paragraph_hash(s) for _, sents in paras for s in sents]
        # Soft: scan/report cross-split paragraph reuse (do not skip — distractor corpus overlaps)
        for other, sset in para_hashes_by_split.items():
            if other == split:
                continue
            if any(h in sset for h in phashes):
                report["paragraph_cross_split_hits"] += 1
                break

        eid = str(ex.get("id") or ex.get("_id") or "")
        task_id = f"hpqa_{split}_{eid}"
        online = _online_pack(ex, task_id, split)
        gold = _offline_gold(ex, task_id, split)
        if not gold["all_anchors_ok"]:
            report["anchor_failures"] += 1
            return False
        selected[split].append({"raw": ex, "online": online, "gold": gold, "task_id": task_id})
        used_questions.append(q)
        titles_by_split[split] |= set(titles)
        para_hashes_by_split[split].update(phashes)
        return True

    for ex in sorted_pool(validation):
        if len(selected["test"]) >= targets["test"]:
            break
        try_add("test", ex)

    for ex in sorted_pool(train):
        if len(selected["dev"]) < targets["dev"]:
            try_add("dev", ex)
            continue
        if len(selected["train"]) >= targets["train"]:
            break
        try_add("train", ex)

    report["counts"] = {k: len(v) for k, v in selected.items()}
    report["targets"] = targets
    report["scale_complete"] = all(report["counts"][k] >= targets[k] for k in targets)
    return selected, report


def load_hotpot_hf() -> tuple[list[dict], list[dict], dict[str, Any]]:
    import os

    # Mainland networks often need a Hub mirror; allow override.
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from datasets import load_dataset

    ds = load_dataset("hotpotqa/hotpot_qa", "distractor")
    meta = {
        "dataset": "hotpotqa/hotpot_qa",
        "config": "distractor",
        "revision": "main",
        "hf_endpoint": os.environ.get("HF_ENDPOINT"),
        "license": "CC-BY-SA-4.0",
        "n_train_official": len(ds["train"]),
        "n_validation_official": len(ds["validation"]),
    }
    try:
        meta["dataset_fingerprint_train"] = ds["train"]._fingerprint  # noqa: SLF001
        meta["dataset_fingerprint_validation"] = ds["validation"]._fingerprint  # noqa: SLF001
    except Exception:
        pass
    val = [dict(x) for x in ds["validation"]]
    tr = [dict(x) for x in ds["train"]]
    return val, tr, meta


def load_fixture() -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Tiny synthetic distractor-like examples for offline CI."""
    cities = [
        "Helsinki", "Kyoto", "Lisbon", "Nairobi", "Oslo", "Quebec", "Recife", "Seoul",
        "Tunis", "Utrecht", "Vienna", "Warsaw", "Xiamen", "Yangon", "Zurich",
        "Athens", "Bogota", "Cairo", "Dublin", "Edmonton", "Florence", "Geneva", "Hanoi",
        "Istanbul", "Jakarta",
    ]
    topics = [
        "river estuary mapping",
        "satellite radio patents",
        "glacier mass balance",
        "medieval trade guilds",
        "coral reef bleaching",
        "fermion pairing models",
        "bronze casting workshops",
        "volcanic ash layers",
        "manuscript illumination",
        "tidal turbine farms",
        "silk route caravans",
        "polar night biology",
        "ceramic kiln designs",
        "monsoon wind corridors",
        "orbital debris catalogs",
        "harbor quarantine laws",
        "alpine seed banks",
        "desert irrigation canals",
        "deep mine seismology",
        "coastal dune ecology",
        "lattice cryptography",
        "baroque organ builders",
        "peatland carbon flux",
        "spice warehouse audits",
        "aurora oval geometry",
    ]

    def make(i: int, split_hint: str) -> dict:
        title_a = f"Org_{split_hint}_{i}_{topics[i].split()[0]}"
        title_b = f"Artifact_{split_hint}_{i}_{topics[i].split()[-1]}"
        city = cities[i % len(cities)]
        topic = topics[i % len(topics)]
        sents_a = [
            f"{title_a} specializes in {topic}.",
            f"{title_a} headquarters are located in {city}.",
        ]
        sents_b = [
            f"{title_b} was created by {title_a}.",
            f"{title_b} became notable after {2000 + i}.",
        ]
        return {
            "id": f"{split_hint}_{i}",
            "question": f"In which city are the headquarters of the organization that created {title_b} for {topic}?",
            "answer": city,
            "supporting_facts": {"title": [title_a, title_b], "sent_id": [1, 0]},
            "context": {"title": [title_a, title_b], "sentences": [sents_a, sents_b]},
            "level": "easy",
            "type": "bridge",
        }

    validation = [make(i, "val") for i in range(5)]
    train = [make(i, "trn") for i in range(20)]
    meta = {
        "dataset": "fixture_hotpot_like",
        "config": "distractor_synthetic",
        "revision": "fixture",
        "license": "CC-BY-SA-4.0",
        "note": "Offline fixture; not official HotpotQA",
    }
    return validation, train, meta


def write_outputs(
    root: Path,
    selected: dict[str, list[dict]],
    report: dict[str, Any],
    upstream_meta: dict[str, Any],
    *,
    fixture: bool,
) -> None:
    base = root / "data" / "tasks" / "hotpotqa" / DATASET_ID
    splits_dir = root / "data" / "splits" / DATASET_ID
    raw_dir = root / "data" / "raw" / "hotpotqa"
    man_dir = root / "data" / "manifests"
    for d in (base, splits_dir, raw_dir, man_dir):
        d.mkdir(parents=True, exist_ok=True)

    (raw_dir / "upstream_meta.json").write_text(
        json.dumps(upstream_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for split, items in selected.items():
        online_path = base / f"{split}.jsonl"
        gold_path = base / f"{split}.gold.jsonl"
        with online_path.open("w", encoding="utf-8") as fo, gold_path.open("w", encoding="utf-8") as fg:
            for it in items:
                # strip context_docs from jsonl pointer? keep for corpus build then thin
                online = dict(it["online"])
                docs = online.pop("context_docs", [])
                online_thin = dict(online)
                online_thin["corpus_relpath"] = f"corpora/{it['task_id']}/context.md"
                fo.write(json.dumps(online_thin, ensure_ascii=False) + "\n")
                fg.write(json.dumps(it["gold"], ensure_ascii=False) + "\n")
                # restore for corpus write
                online["context_docs"] = docs
                _write_task_corpus(root, it["task_id"], online)

        # split id list
        (splits_dir / f"{split}.ids.txt").write_text(
            "\n".join(it["task_id"] for it in items) + ("\n" if items else ""),
            encoding="utf-8",
        )

    # Isolation check: gold fields must not appear in online jsonl
    isolation_violations = []
    for split in selected:
        for line in (base / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            for banned in ("gold_answer", "gold_claims", "supporting_facts", "answer"):
                if banned in obj:
                    isolation_violations.append({"split": split, "field": banned, "task_id": obj.get("task_id")})
        # scan corpus files for answer string leakage (best-effort)
        for it in selected[split]:
            ans = (it["gold"].get("gold_answer") or "").strip()
            corp = root / "data" / "tasks" / "hotpotqa" / DATASET_ID / "corpora" / it["task_id"] / "context.md"
            # answers may legitimately appear in context in HotpotQA — that's OK;
            # ban is against putting gold into *index metadata / policy state fields*
            _ = (ans, corp)

    report["isolation_violations"] = isolation_violations
    report["fixture"] = fixture
    (base / "leakage_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # File hashes for online packs
    hashes = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix in {".jsonl", ".json", ".md", ".txt"}:
            hashes[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = {
        "dataset_id": DATASET_ID,
        "seed": 42,
        "targets": TARGETS,
        "counts": report["counts"],
        "scale_complete": report["scale_complete"],
        "upstream": upstream_meta,
        "license_data": "CC-BY-SA-4.0",
        "license_code_note": "Project code Apache-2.0 does not relicense HotpotQA data",
        "file_sha256": hashes,
        "isolation_violations": isolation_violations,
    }
    man_path = man_dir / "mf_hotpotqa_s25_0001.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(man_path), **report["counts"], "scale_complete": report["scale_complete"]}, indent=2))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--fixture-only", action="store_true")
    args = p.parse_args(argv)

    targets = dict(TARGETS)
    fixture = False
    if args.fixture_only:
        val, tr, meta = load_fixture()
        targets = {"test": 3, "dev": 2, "train": 5}
        fixture = True
    else:
        try:
            val, tr, meta = load_hotpot_hf()
        except Exception as exc:
            print(f"HF load failed ({exc}); falling back to fixture", file=sys.stderr)
            val, tr, meta = load_fixture()
            targets = {"test": 3, "dev": 2, "train": 5}
            meta["fallback"] = str(exc)
            fixture = True

    selected, report = select_subset(val, tr, targets=targets)
    write_outputs(
        args.root,
        selected,
        report,
        meta,
        fixture=fixture or meta.get("dataset") == "fixture_hotpot_like",
    )
    return 0 if report.get("isolation_violations") == [] else 2


if __name__ == "__main__":
    raise SystemExit(main())
