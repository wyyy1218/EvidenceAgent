"""S26 Chinese tech-doc catalog: project→split isolation, licenses, pinned versions."""
from __future__ import annotations

from typing import Any

# Unified freeze cutoff (ISO date). Commits below are intended pins; when live
# fetch fails, local authored excerpts still cite these tags/paths.
CUTOFF_DATE = "2026-10-25"

CATEGORIES = (
    "direct_fact",
    "multi_source",
    "version_conflict",
    "insufficient_evidence",
)

# Per §14.3 — train/dev/test never share projects.
PROJECTS: dict[str, dict[str, Any]] = {
    "fastapi": {
        "split": "train",
        "repo": "fastapi/fastapi",
        "license": "MIT",
        "redistribute": "ok_with_notice",
        "versions": ["0.100.1", "0.115.0"],
        "docs_root": "docs/en/docs",
    },
    "pydantic": {
        "split": "train",
        "repo": "pydantic/pydantic",
        "license": "MIT",
        "redistribute": "ok_with_notice",
        "versions": ["2.5.0", "2.9.0"],
        "docs_root": "docs",
    },
    "httpx": {
        "split": "train",
        "repo": "encode/httpx",
        "license": "BSD-3-Clause",
        "redistribute": "ok_with_notice",
        "versions": ["0.25.0", "0.27.0"],
        "docs_root": "docs",
    },
    "streamlit": {
        "split": "train",
        "repo": "streamlit/streamlit",
        "license": "Apache-2.0",
        "redistribute": "ok_with_notice",
        "versions": ["1.28.0", "1.39.0"],
        "docs_root": "docs",
    },
    "qdrant": {
        "split": "train",
        "repo": "qdrant/qdrant",
        "license": "Apache-2.0",
        "redistribute": "ok_with_notice",
        "versions": ["v1.7.0", "v1.11.0"],
        "docs_root": "docs",
    },
    "langgraph": {
        "split": "train",
        "repo": "langchain-ai/langgraph",
        "license": "MIT",
        "redistribute": "ok_with_notice",
        "versions": ["0.2.0", "0.2.28"],
        "docs_root": "docs",
    },
    "gradio": {
        "split": "dev",
        "repo": "gradio-app/gradio",
        "license": "Apache-2.0",
        "redistribute": "ok_with_notice",
        "versions": ["4.0.0", "4.44.0"],
        "docs_root": "guides",
    },
    "typer": {
        "split": "dev",
        "repo": "fastapi/typer",
        "license": "MIT",
        "redistribute": "ok_with_notice",
        "versions": ["0.9.0", "0.12.0"],
        "docs_root": "docs",
    },
    "starlette": {
        "split": "test",
        "repo": "encode/starlette",
        "license": "BSD-3-Clause",
        "redistribute": "ok_with_notice",
        "versions": ["0.27.0", "0.38.0"],
        "docs_root": "docs",
    },
    "click": {
        "split": "test",
        "repo": "pallets/click",
        "license": "BSD-3-Clause",
        "redistribute": "ok_with_notice",
        "versions": ["8.1.3", "8.1.7"],
        "docs_root": "docs",
    },
}

# Replay quota (S27 / §15.4)
REPLAY_QUOTA = {
    "train": {"direct_fact": 30, "multi_source": 30, "version_conflict": 30, "insufficient_evidence": 30},
    "dev": {"direct_fact": 8, "multi_source": 7, "version_conflict": 8, "insufficient_evidence": 7},
    "test": {"direct_fact": 13, "multi_source": 12, "version_conflict": 13, "insufficient_evidence": 12},
}

SPLIT_TARGETS = {"train": 240, "dev": 60, "test": 100}
PER_CATEGORY = {"train": 60, "dev": 15, "test": 25}

DATASET_ID = "zh_tech_s27_v1"
SOURCES_MANIFEST_ID = "mf_chinese_sources_s26_0001"
TASKS_MANIFEST_ID = "mf_chinese_tasks_s27_0001"
COLLECTION_ID = "traj_teacher_s29_0001"


def projects_for_split(split: str) -> list[str]:
    return [k for k, v in PROJECTS.items() if v["split"] == split]
