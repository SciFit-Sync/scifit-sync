"""골드셋 라벨링 웹 UI.

브라우저에서 질의별 후보 논문을 보고 정답 PMID를 선택한다.

사용법:
    pip install flask requests deep-translator
    python mlops/scripts/label_server.py
    → http://localhost:5001 접속
"""

import json
import os
import threading
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template_string, request

CANDIDATES_PATH = Path("mlops/eval/candidates.jsonl")
LABELS_PATH = Path("mlops/eval/labels.jsonl")
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ABSTRACT_MAX_CHARS = 600
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_RATE_LIMIT = 0.11 if NCBI_API_KEY else 0.4  # API키 있으면 10/s, 없으면 2.5/s

app = Flask(__name__)
_abstract_cache: dict[str, str] = {}
_ncbi_lock = threading.Lock()  # NCBI 요청 직렬화


def load_candidates() -> list[dict]:
    items = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                items.append(json.loads(stripped))
    return items


def load_labels() -> dict[str, str | None]:
    labels: dict[str, str | None] = {}
    if not LABELS_PATH.exists():
        return labels
    with LABELS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                rec = json.loads(stripped)
                labels[rec["qid"]] = rec.get("pmid")
    return labels


def save_label(qid: str, pmid: str | None) -> None:
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    labels = load_labels()
    labels[qid] = pmid
    with LABELS_PATH.open("w", encoding="utf-8") as f:
        for q, p in labels.items():
            f.write(json.dumps({"qid": q, "pmid": p}, ensure_ascii=False) + "\n")


def fetch_abstract(pmid: str) -> str:
    """PubMed XML API로 초록 추출 — lock으로 직렬화해 rate limit 방지."""
    if pmid in _abstract_cache:
        return _abstract_cache[pmid]
    with _ncbi_lock:
        # lock 대기 중 다른 스레드가 채웠을 수 있음
        if pmid in _abstract_cache:
            return _abstract_cache[pmid]
        try:
            import xml.etree.ElementTree as ET

            params = {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"}
            if NCBI_API_KEY:
                params["api_key"] = NCBI_API_KEY
            resp = requests.get(PUBMED_FETCH_URL, params=params, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            parts = [el.text or "" for el in root.iter("AbstractText") if el.text]
            abstract = " ".join(parts).strip() or "(초록 없음)"
            result = abstract[:ABSTRACT_MAX_CHARS] + ("..." if len(abstract) > ABSTRACT_MAX_CHARS else "")
            time.sleep(NCBI_RATE_LIMIT)
        except Exception as e:
            result = f"(초록을 가져오지 못했습니다: {e})"
        _abstract_cache[pmid] = result
    return result


def translate_to_korean(text: str) -> str:
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source="en", target="ko").translate(text)
    except Exception:
        return text


HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>골드셋 라벨링</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #f5f6fa; color: #2d3436; }
  .header { background: #fff; border-bottom: 1px solid #e0e0e0; padding: 16px 32px;
            display: flex; align-items: center; gap: 16px; position: sticky; top: 0; z-index: 10; }
  .header h1 { font-size: 18px; font-weight: 600; }
  .progress-bar { flex: 1; background: #e0e0e0; border-radius: 4px; height: 8px; }
  .progress-fill { background: #6c5ce7; height: 8px; border-radius: 4px; transition: width 0.3s; }
  .progress-text { font-size: 13px; color: #636e72; white-space: nowrap; }
  .container { max-width: 860px; margin: 32px auto; padding: 0 16px; }
  .query-card { background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .query-label { font-size: 11px; font-weight: 700; text-transform: uppercase;
                 color: #6c5ce7; letter-spacing: 1px; margin-bottom: 8px; }
  .query-id { font-size: 12px; color: #b2bec3; margin-bottom: 4px; }
  .query-en { font-size: 15px; color: #636e72; margin-bottom: 6px; }
  .query-ko { font-size: 17px; font-weight: 600; }
  .candidates { display: flex; flex-direction: column; gap: 12px; }
  .candidate { background: #fff; border: 2px solid #e0e0e0; border-radius: 10px; padding: 18px 20px;
               cursor: pointer; transition: all 0.15s; position: relative; }
  .candidate:hover { border-color: #6c5ce7; box-shadow: 0 2px 12px rgba(108,92,231,0.12); }
  .candidate.selected { border-color: #6c5ce7; background: #f3f0ff; }
  .candidate.loading { opacity: 0.6; }
  .cand-header { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
  .cand-num { background: #e0e0e0; color: #636e72; border-radius: 50%; width: 28px; height: 28px;
              display: flex; align-items: center; justify-content: center;
              font-size: 13px; font-weight: 700; flex-shrink: 0; }
  .candidate.selected .cand-num { background: #6c5ce7; color: #fff; }
  .cand-title { font-size: 14px; font-weight: 600; line-height: 1.4; flex: 1; }
  .cand-score { font-size: 12px; color: #b2bec3; white-space: nowrap; flex-shrink: 0; }
  .cand-abstract { font-size: 13px; color: #636e72; line-height: 1.6; padding-left: 40px; }
  .cand-abstract.loading-text { color: #b2bec3; font-style: italic; }
  .cand-abstract-en { font-size: 12px; color: #b2bec3; line-height: 1.5; padding-left: 40px; margin-top: 4px; }
  .actions { display: flex; gap: 12px; margin-top: 24px; }
  .btn { padding: 12px 28px; border: none; border-radius: 8px; font-size: 15px;
         font-weight: 600; cursor: pointer; transition: all 0.15s; }
  .btn-primary { background: #6c5ce7; color: #fff; }
  .btn-primary:hover { background: #5a4bd1; }
  .btn-primary:disabled { background: #b2bec3; cursor: not-allowed; }
  .btn-skip { background: #f0f0f0; color: #636e72; }
  .btn-skip:hover { background: #e0e0e0; }
  .nav { display: flex; gap: 8px; margin-left: auto; }
  .btn-nav { background: #fff; border: 1px solid #e0e0e0; color: #636e72;
             padding: 8px 16px; font-size: 13px; }
  .btn-nav:hover { border-color: #6c5ce7; color: #6c5ce7; }
  .done-badge { background: #00b894; color: #fff; border-radius: 4px;
                padding: 2px 8px; font-size: 11px; font-weight: 700; }
  .selected-badge { position: absolute; right: 16px; top: 16px;
                    background: #6c5ce7; color: #fff; border-radius: 4px;
                    padding: 2px 8px; font-size: 11px; }
</style>
</head>
<body>
<div class="header">
  <h1>골드셋 라벨링</h1>
  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
  <div class="progress-text" id="progressText"></div>
</div>
<div class="container">
  <div class="query-card" id="queryCard"></div>
  <div class="candidates" id="candidateList"></div>
  <div class="actions">
    <button class="btn btn-primary" id="btnConfirm" onclick="confirm_()">확정</button>
    <button class="btn btn-skip" onclick="skip()">관련 논문 없음</button>
    <div class="nav">
      <button class="btn btn-nav" onclick="navigate(-1)">◀ 이전</button>
      <button class="btn btn-nav" onclick="navigate(1)">다음 ▶</button>
    </div>
  </div>
</div>

<script>
let allItems = [];
let labels = {};
let currentIdx = 0;
let selectedPmid = null;

async function init() {
  const r = await fetch('/api/data');
  const data = await r.json();
  allItems = data.items;
  labels = data.labels;
  currentIdx = allItems.findIndex(item => !(item.id in labels));
  if (currentIdx < 0) currentIdx = 0;
  render();
}

function updateProgress() {
  const done = Object.keys(labels).length;
  const total = allItems.length;
  document.getElementById('progressFill').style.width = (done / total * 100) + '%';
  document.getElementById('progressText').textContent = done + ' / ' + total;
}

async function render() {
  const item = allItems[currentIdx];
  selectedPmid = labels[item.id] !== undefined ? labels[item.id] : null;
  const isDone = item.id in labels;

  document.getElementById('queryCard').innerHTML = `
    <div class="query-label">${item.category} ${isDone ? '<span class="done-badge">완료</span>' : ''}</div>
    <div class="query-id">${item.id} (${currentIdx + 1}/${allItems.length})</div>
    <div class="query-en">${item.query}</div>
    <div class="query-ko">${item.query_ko || ''}</div>
  `;

  const list = document.getElementById('candidateList');
  list.innerHTML = '';
  document.getElementById('btnConfirm').disabled = (selectedPmid === null && !isDone);

  for (const [i, cand] of item.candidates.entries()) {
    const div = document.createElement('div');
    div.className = 'candidate' + (cand.pmid === selectedPmid ? ' selected' : '');
    div.dataset.pmid = cand.pmid;
    div.onclick = () => selectCandidate(cand.pmid);
    div.innerHTML = `
      ${cand.pmid === selectedPmid ? '<div class="selected-badge">선택됨</div>' : ''}
      <div class="cand-header">
        <div class="cand-num">${i + 1}</div>
        <div class="cand-title">${cand.title}</div>
        <div class="cand-score">score ${cand.score}</div>
      </div>
      <div class="cand-abstract loading-text" id="abs-ko-${cand.pmid}">초록 불러오는 중...</div>
      <div class="cand-abstract-en" id="abs-en-${cand.pmid}"></div>
    `;
    list.appendChild(div);
    fetchAbstract(cand.pmid);
  }

  updateProgress();
}

async function fetchAbstract(pmid) {
  const r = await fetch('/api/abstract/' + pmid);
  const data = await r.json();
  const ko = document.getElementById('abs-ko-' + pmid);
  const en = document.getElementById('abs-en-' + pmid);
  if (ko) {
    ko.textContent = data.abstract_ko;
    ko.classList.remove('loading-text');
  }
  if (en) {
    en.textContent = data.abstract_en !== data.abstract_ko ? data.abstract_en : '';
  }
}

function selectCandidate(pmid) {
  selectedPmid = pmid;
  document.querySelectorAll('.candidate').forEach(el => {
    const isSelected = el.dataset.pmid === pmid;
    el.classList.toggle('selected', isSelected);
    const badge = el.querySelector('.selected-badge');
    if (isSelected && !badge) {
      el.insertAdjacentHTML('afterbegin', '<div class="selected-badge">선택됨</div>');
    } else if (!isSelected && badge) {
      badge.remove();
    }
  });
  document.getElementById('btnConfirm').disabled = false;
}

async function confirm_() {
  if (selectedPmid === null) return;
  await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({qid: allItems[currentIdx].id, pmid: selectedPmid})
  });
  labels[allItems[currentIdx].id] = selectedPmid;
  updateProgress();
  navigate(1);
}

async function skip() {
  await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({qid: allItems[currentIdx].id, pmid: null})
  });
  labels[allItems[currentIdx].id] = null;
  updateProgress();
  navigate(1);
}

function navigate(dir) {
  const next = currentIdx + dir;
  if (next < 0 || next >= allItems.length) return;
  currentIdx = next;
  render();
}

init();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/data")
def api_data():
    candidates = load_candidates()
    labels = load_labels()
    return jsonify({"items": candidates, "labels": labels})


@app.route("/api/abstract/<pmid>")
def api_abstract(pmid: str):
    abstract_en = fetch_abstract(pmid)
    abstract_ko = translate_to_korean(abstract_en)
    return jsonify({"abstract_en": abstract_en, "abstract_ko": abstract_ko})


@app.route("/api/label", methods=["POST"])
def api_label():
    data = request.get_json()
    save_label(data["qid"], data.get("pmid"))
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("http://localhost:5001 에서 라벨링 시작")
    app.run(port=5001, debug=False, threaded=True)
