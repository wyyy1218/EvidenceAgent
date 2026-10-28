#!/usr/bin/env python3
"""S07 doctor: run local core probes and write runs/probes/probe_s07_*."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import ensure_cache_env, work_root  # noqa: E402


def env_python(root: Path, name: str) -> Path:
    return root / "envs" / name / "bin" / "python"


def run_py(py: Path, code: str, timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run(
        [str(py), "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def latest_model(root: Path, role: str) -> Path | None:
    base = root / "models" / role
    if not base.is_dir():
        return None
    dirs = [p for p in base.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return sorted(dirs, key=lambda p: p.name)[-1]


def main() -> int:
    root = ensure_cache_env()
    probe_id = "probe_s07_core_a001"
    out_dir = root / "runs" / "probes" / probe_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail[:4000]})
        (out_dir / f"{name}.log").write_text(detail, encoding="utf-8")
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")

    # 1 CUDA
    train_py = env_python(root, "train")
    code, out = run_py(
        train_py,
        "import torch; x=torch.randn(512,512,device='cuda'); y=x@x; print('cuda',torch.cuda.get_device_name(0), float(y.mean()))",
    )
    record("cuda_matmul", code == 0, out)

    # 2 tokenizer + short generate (train env, no vLLM yet)
    base = latest_model(root, "base")
    if base is None:
        record("tokenizer_generate", False, "base model missing")
    else:
        tok_code = f"""
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
p={str(base)!r}
tok=AutoTokenizer.from_pretrained(p, trust_remote_code=True)
for s in ['你好', 'hello😀', '', '长'*2000]:
    ids=tok(s, return_tensors='pt')
    print('tok_ok', repr(s[:20]), ids['input_ids'].shape)
model=AutoModelForCausalLM.from_pretrained(p, torch_dtype=torch.bfloat16, device_map='cuda', trust_remote_code=True)
messages=[{{'role':'user','content':'用三个字回答：天是什么颜色？'}}]
text=tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs=tok(text, return_tensors='pt').to('cuda')
out=model.generate(**inputs, max_new_tokens=32)
print(tok.decode(out[0], skip_special_tokens=True))
print('GEN_OK')
"""
        code, out = run_py(train_py, tok_code, timeout=900)
        record("tokenizer_generate", code == 0 and "GEN_OK" in out, out)

    # 3 embedding / reranker CPU (app)
    app_py = env_python(root, "app")
    emb = latest_model(root, "embedding")
    rer = latest_model(root, "reranker")
    if emb is None or rer is None:
        record("embedding_reranker", False, f"emb={emb} rer={rer}")
    else:
        er_code = f"""
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder
emb=SentenceTransformer({str(emb)!r}, device='cpu')
v=emb.encode(['hello','你好'], normalize_embeddings=True)
print('emb_shape', v.shape, 'norm', float(np.linalg.norm(v[0])))
assert np.isfinite(v).all()
rer=CrossEncoder({str(rer)!r}, device='cpu')
scores=rer.predict([('query','doc relevant'), ('query',' unrelated xyz')])
print('rer_scores', scores)
print('ER_OK')
"""
        code, out = run_py(app_py, er_code, timeout=600)
        record("embedding_reranker", code == 0 and "ER_OK" in out, out)

    # 4 app import deepagents / langgraph compile
    imp_code = """
import deepagents, langgraph
from typing import TypedDict
from langgraph.graph import StateGraph, END

class S(TypedDict):
    text: str

def node(state: S) -> S:
    return {"text": state["text"] + "!"}

g = StateGraph(S)
g.add_node("node", node)
g.set_entry_point("node")
g.add_edge("node", END)
compiled = g.compile()
out = compiled.invoke({"text": "ok"})
print('deepagents', getattr(deepagents, '__version__', 'ok'))
print('langgraph_compiled', out)
print('APP_IMPORT_OK')
"""
    code, out = run_py(app_py, imp_code)
    record("app_import", code == 0 and "APP_IMPORT_OK" in out, out)

    # 5 external teacher / tavily — fallback if no keys
    private = root / "runs" / "system" / "private.env"
    env_map = {}
    if private.is_file():
        for line in private.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip()
    teacher_key = env_map.get("DASHSCOPE_API_KEY") or env_map.get("BAILIAN_API_KEY") or ""
    tavily_key = env_map.get("TAVILY_API_KEY") or ""
    ext = {
        "teacher": "SKIPPED_NO_KEY_FALLBACK_local_base" if not teacher_key else "KEY_PRESENT_PROBE_PENDING",
        "tavily": "SKIPPED_NO_KEY_FALLBACK_off" if not tavily_key else "KEY_PRESENT_PROBE_PENDING",
    }
    if teacher_key:
        # one cheap chat
        t_code = f"""
from openai import OpenAI
c=OpenAI(api_key={teacher_key!r}, base_url='https://dashscope.aliyuncs.com/compatible-mode/v1')
r=c.chat.completions.create(model='qwen3.8-max-0902', messages=[{{'role':'user','content':'ping'}}], max_tokens=8)
print(r.model, r.usage)
print('TEACHER_OK')
"""
        # openai may be in app env
        code, out = run_py(app_py, t_code, timeout=60)
        ext["teacher"] = "PASS" if code == 0 and "TEACHER_OK" in out else f"FAIL:{out[:500]}"
        (out_dir / "teacher.log").write_text(out, encoding="utf-8")
    if tavily_key:
        t_code = f"""
import httpx
r=httpx.post('https://api.tavily.com/search', json={{'api_key':{tavily_key!r},'query':'EvidenceAgent','search_depth':'basic','max_results':1}}, timeout=30)
print(r.status_code, r.text[:500])
print('TAVILY_OK' if r.status_code==200 else 'TAVILY_FAIL')
"""
        code, out = run_py(app_py, t_code, timeout=60)
        ext["tavily"] = "PASS" if "TAVILY_OK" in out else f"FAIL:{out[:500]}"
        (out_dir / "tavily.log").write_text(out, encoding="utf-8")
    record(
        "external_services",
        True,  # fallback allowed
        json.dumps(ext, ensure_ascii=False, indent=2),
    )

    summary = {
        "probe_id": probe_id,
        "when": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "core_pass": all(
            r["ok"]
            for r in results
            if r["name"] in {"cuda_matmul", "tokenizer_generate", "embedding_reranker", "app_import"}
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(
        "# " + probe_id + "\n\n"
        + "\n".join(f"- {'PASS' if r['ok'] else 'FAIL'}: `{r['name']}`" for r in results)
        + f"\n\ncore_pass={summary['core_pass']}\n",
        encoding="utf-8",
    )
    print("DOCTOR_CORE_DONE", summary["core_pass"])
    return 0 if summary["core_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
