# Supplementary Dockerfile for EvidenceAgent (S48).
# AutoDL production path is process-based (venv + scripts/serve.py).
# Do NOT assume Docker-in-Docker on the rental host.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORK_ROOT=/work/evidence-agent \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /work/evidence-agent/repo

# App-layer deps only; GPU/vLLM belong on the host infer env.
COPY locks/app.txt /tmp/locks/app.txt
RUN pip install --no-cache-dir -r /tmp/locks/app.txt && rm -rf /tmp/locks

COPY . /work/evidence-agent/repo

EXPOSE 6006 6008
# vLLM stays on 127.0.0.1:8001 of the host; not published from this image.

CMD ["python", "-m", "evidence_agent.cli", "serve", "start", "--no-vllm"]
