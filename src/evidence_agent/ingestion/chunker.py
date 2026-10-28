"""S12: dual-tokenizer chunking with section/page boundaries."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

TokenCounter = Callable[[str], int]

# Default limits from project.yaml / 项目说明 §9.2
DEFAULT_MAX_QWEN = 384
DEFAULT_MAX_EMB = 512
DEFAULT_OVERLAP_QWEN = 64


@dataclass
class Chunk:
    chunk_id: str
    source_version_id: str
    text: str
    start: int
    end: int
    page: int | None = None
    section: str | None = None
    parent_section_id: str | None = None
    title: str | None = None
    is_fragment: bool = False
    fragment_note: str | None = None
    kind: str = "paragraph"  # paragraph | code | table | heading
    qwen_tokens: int = 0
    emb_tokens: int = 0

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["parent_id"] = d.pop("parent_section_id")
        return d


def approx_qwen_tokens(text: str) -> int:
    """Fallback counter when Qwen tokenizer unavailable (tests / local)."""
    if not text:
        return 0
    # Rough: CJK ~1 tok/char; latin ~1 tok/4 chars
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf")
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def approx_emb_tokens(text: str) -> int:
    """bge-m3-ish fallback: slightly coarser than Qwen for latin."""
    if not text:
        return 0
    return max(1, (len(text) + 2) // 3)


def make_chunk_id(source_version_id: str, start: int, end: int, text: str) -> str:
    h = hashlib.sha256(f"{source_version_id}:{start}:{end}:{text[:64]}".encode("utf-8")).hexdigest()[:12]
    return f"chk_{h}"


_CODE_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_TABLE_LINE = re.compile(r"^\|.+\|$")


def _split_md_units(clean_text: str) -> list[dict[str, Any]]:
    """Split MD/TXT into structural units preserving offsets into clean_text."""
    lines = clean_text.split("\n")
    units: list[dict[str, Any]] = []
    pos = 0
    i = 0
    current_section = None
    parent_section_id = None
    section_stack: list[tuple[int, str]] = []

    while i < len(lines):
        line = lines[i]
        start = pos
        end = start + len(line)

        hm = _HEADING.match(line)
        if hm:
            level = len(hm.group(1))
            title = hm.group(2).strip()
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            parent = section_stack[-1][1] if section_stack else None
            sid = f"sec_{hashlib.sha256(f'{start}:{title}'.encode()).hexdigest()[:10]}"
            section_stack.append((level, sid))
            current_section = title
            parent_section_id = parent
            units.append(
                {
                    "text": line,
                    "start": start,
                    "end": end,
                    "kind": "heading",
                    "title": title,
                    "section": current_section,
                    "parent_section_id": parent_section_id,
                    "page": None,
                }
            )
            pos = end + 1 if i < len(lines) - 1 else end
            i += 1
            continue

        if _CODE_FENCE.match(line):
            block_lines = [line]
            block_end = end
            j = i + 1
            p = end + 1 if i < len(lines) - 1 else end
            while j < len(lines):
                block_lines.append(lines[j])
                block_end = p + len(lines[j])
                if _CODE_FENCE.match(lines[j]) and j > i:
                    break
                p = block_end + 1 if j < len(lines) - 1 else block_end
                j += 1
            else:
                j = i
                block_end = end
            text = "\n".join(block_lines)
            units.append(
                {
                    "text": text,
                    "start": start,
                    "end": block_end,
                    "kind": "code",
                    "title": current_section,
                    "section": current_section,
                    "parent_section_id": parent_section_id,
                    "page": None,
                }
            )
            i = j + 1
            pos = block_end + 1 if i < len(lines) else block_end
            continue

        if _TABLE_LINE.match(line.strip()):
            block_lines = [line]
            block_end = end
            j = i + 1
            p = end + 1 if i < len(lines) - 1 else end
            while j < len(lines) and _TABLE_LINE.match(lines[j].strip()):
                block_lines.append(lines[j])
                block_end = p + len(lines[j])
                p = block_end + 1 if j < len(lines) - 1 else block_end
                j += 1
            text = "\n".join(block_lines)
            units.append(
                {
                    "text": text,
                    "start": start,
                    "end": block_end,
                    "kind": "table",
                    "title": current_section,
                    "section": current_section,
                    "parent_section_id": parent_section_id,
                    "page": None,
                }
            )
            i = j
            pos = block_end + 1 if i < len(lines) else block_end
            continue

        # paragraph: gather non-empty consecutive lines until blank
        if line.strip() == "":
            pos = end + 1 if i < len(lines) - 1 else end
            i += 1
            continue

        para_lines = [line]
        block_end = end
        j = i + 1
        p = end + 1 if i < len(lines) - 1 else end
        while j < len(lines):
            if lines[j].strip() == "":
                break
            if _HEADING.match(lines[j]) or _CODE_FENCE.match(lines[j]) or _TABLE_LINE.match(lines[j].strip()):
                break
            para_lines.append(lines[j])
            block_end = p + len(lines[j])
            p = block_end + 1 if j < len(lines) - 1 else block_end
            j += 1
        text = "\n".join(para_lines)
        units.append(
            {
                "text": text,
                "start": start,
                "end": block_end,
                "kind": "paragraph",
                "title": current_section,
                "section": current_section,
                "parent_section_id": parent_section_id,
                "page": None,
            }
        )
        i = j
        pos = block_end + 1 if i < len(lines) else block_end

    return units


def _split_pdf_units(pages: list[dict[str, Any]], clean_text: str) -> list[dict[str, Any]]:
    """PDF: prefer page boundaries; offsets into concatenated clean_text if aligned."""
    units: list[dict[str, Any]] = []
    # Prefer using page texts with page-local offsets; also map into clean if possible
    cursor = 0
    for p in pages:
        page_no = int(p["page"])
        text = p.get("text") or ""
        if not text.strip():
            continue
        # Find in clean_text near cursor
        idx = clean_text.find(text, cursor)
        if idx < 0:
            idx = clean_text.find(text)
        if idx >= 0:
            start, end = idx, idx + len(text)
            cursor = end
        else:
            start, end = cursor, cursor + len(text)
            cursor = end
        # Split long pages by blank lines
        parts = re.split(r"\n\s*\n", text)
        offset = 0
        for part in parts:
            if not part.strip():
                offset += len(part) + 2
                continue
            # locate part within page text
            rel = text.find(part, offset)
            if rel < 0:
                rel = offset
            ps = start + rel if idx >= 0 else start + rel
            pe = ps + len(part)
            units.append(
                {
                    "text": part,
                    "start": ps,
                    "end": pe,
                    "kind": "paragraph",
                    "title": f"page_{page_no}",
                    "section": f"page_{page_no}",
                    "parent_section_id": None,
                    "page": page_no,
                    "page_char_start": rel,
                    "page_char_end": rel + len(part),
                }
            )
            offset = rel + len(part)
    return units


def _fits(text: str, qwen_count: TokenCounter, emb_count: TokenCounter, max_qwen: int, max_emb: int) -> bool:
    return qwen_count(text) <= max_qwen and emb_count(text) <= max_emb


def _hard_split(
    text: str,
    *,
    base_start: int,
    source_version_id: str,
    qwen_count: TokenCounter,
    emb_count: TokenCounter,
    max_qwen: int,
    max_emb: int,
    overlap_qwen: int,
    meta: dict[str, Any],
) -> list[Chunk]:
    """Binary-ish cut by characters until both token limits satisfied; carry overlap."""
    chunks: list[Chunk] = []
    n = len(text)
    if n == 0:
        return chunks
    pos = 0
    frag_i = 0
    while pos < n:
        lo, hi = pos + 1, n
        best = pos + 1
        while lo <= hi:
            mid = (lo + hi) // 2
            piece = text[pos:mid]
            if _fits(piece, qwen_count, emb_count, max_qwen, max_emb):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best <= pos:
            best = min(pos + 1, n)  # force progress on pathological tokenizers
        piece = text[pos:best]
        frag_i += 1
        is_frag = meta.get("kind") in ("code", "table") or (pos > 0 or best < n)
        note = None
        if is_frag:
            title = meta.get("title") or meta.get("section") or ""
            note = f"fragment of {meta.get('kind', 'block')}" + (f" ({title})" if title else "")
            if meta.get("kind") in ("code", "table"):
                note = f"{meta['kind']} fragment" + (f"; section={title}" if title else "")
        cid = make_chunk_id(source_version_id, base_start + pos, base_start + best, piece)
        chunks.append(
            Chunk(
                chunk_id=cid,
                source_version_id=source_version_id,
                text=piece,
                start=base_start + pos,
                end=base_start + best,
                page=meta.get("page"),
                section=meta.get("section"),
                parent_section_id=meta.get("parent_section_id"),
                title=meta.get("title"),
                is_fragment=is_frag,
                fragment_note=note,
                kind=meta.get("kind", "paragraph"),
                qwen_tokens=qwen_count(piece),
                emb_tokens=emb_count(piece),
            )
        )
        if best >= n:
            break
        # overlap: back up by ~overlap_qwen tokens (approx via chars)
        overlap_chars = max(0, min(best - pos - 1, overlap_qwen * 2))
        next_pos = best - overlap_chars
        if next_pos <= pos:
            next_pos = best
        pos = next_pos
    return chunks


def chunk_document(
    *,
    source_version_id: str,
    clean_text: str,
    kind: str = "md",
    pages: list[dict[str, Any]] | None = None,
    qwen_count: TokenCounter | None = None,
    emb_count: TokenCounter | None = None,
    max_qwen: int = DEFAULT_MAX_QWEN,
    max_emb: int = DEFAULT_MAX_EMB,
    overlap_qwen: int = DEFAULT_OVERLAP_QWEN,
) -> list[Chunk]:
    """Produce chunks respecting dual token limits and structural boundaries."""
    qwen_count = qwen_count or approx_qwen_tokens
    emb_count = emb_count or approx_emb_tokens

    if kind == "pdf" and pages:
        units = _split_pdf_units(pages, clean_text)
    else:
        units = _split_md_units(clean_text)

    out: list[Chunk] = []
    for u in units:
        text = u["text"]
        if not text.strip():
            continue
        meta = {
            "page": u.get("page"),
            "section": u.get("section"),
            "parent_section_id": u.get("parent_section_id"),
            "title": u.get("title"),
            "kind": u.get("kind", "paragraph"),
        }
        if _fits(text, qwen_count, emb_count, max_qwen, max_emb):
            cid = make_chunk_id(source_version_id, u["start"], u["end"], text)
            out.append(
                Chunk(
                    chunk_id=cid,
                    source_version_id=source_version_id,
                    text=text,
                    start=u["start"],
                    end=u["end"],
                    page=meta["page"],
                    section=meta["section"],
                    parent_section_id=meta["parent_section_id"],
                    title=meta["title"],
                    is_fragment=False,
                    kind=meta["kind"],
                    qwen_tokens=qwen_count(text),
                    emb_tokens=emb_count(text),
                )
            )
        else:
            # Must cut: preserve title/fragment note for code/table
            out.extend(
                _hard_split(
                    text,
                    base_start=u["start"],
                    source_version_id=source_version_id,
                    qwen_count=qwen_count,
                    emb_count=emb_count,
                    max_qwen=max_qwen,
                    max_emb=max_emb,
                    overlap_qwen=overlap_qwen,
                    meta=meta,
                )
            )
    return out


def validate_chunks(
    chunks: list[Chunk],
    *,
    qwen_count: TokenCounter | None = None,
    emb_count: TokenCounter | None = None,
    max_qwen: int = DEFAULT_MAX_QWEN,
    max_emb: int = DEFAULT_MAX_EMB,
) -> list[str]:
    """Return list of violation messages (empty = ok)."""
    qwen_count = qwen_count or approx_qwen_tokens
    emb_count = emb_count or approx_emb_tokens
    errs: list[str] = []
    for c in chunks:
        qt = qwen_count(c.text)
        et = emb_count(c.text)
        if qt > max_qwen:
            errs.append(f"{c.chunk_id}: qwen_tokens={qt}>{max_qwen}")
        if et > max_emb:
            errs.append(f"{c.chunk_id}: emb_tokens={et}>{max_emb}")
        if c.start < 0 or c.end < c.start:
            errs.append(f"{c.chunk_id}: bad span")
        if not c.text:
            errs.append(f"{c.chunk_id}: empty text")
    return errs
