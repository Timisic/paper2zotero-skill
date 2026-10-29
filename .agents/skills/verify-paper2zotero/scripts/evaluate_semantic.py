#!/usr/bin/env python3
"""Offline diagnostic of Zotero MCP's installed default embedding provider."""
import argparse
import cProfile
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--model-cache", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parent / "semantic-fixture.json")
parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()
root = Path(__file__).resolve().parent
output = args.output.resolve()
cache = args.model_cache.resolve()
required = ["model.onnx", "tokenizer.json", "config.json", "vocab.txt", "tokenizer_config.json", "special_tokens_map.json"]
for name in required:
    if not (cache / "onnx" / name).is_file():
        parser.error(f"missing cached model file {name}; no download is permitted")
if not args.worker:
    output.mkdir(parents=True, exist_ok=False)
    profile_home = output / "profile"
    profile_home.mkdir()
    environment = {
        "HOME": str(profile_home), "XDG_CONFIG_HOME": str(profile_home / ".config"),
        "XDG_CACHE_HOME": str(profile_home / ".cache"), "PATH": "/usr/bin:/bin",
        "TMPDIR": str(output), "TOKENIZERS_PARALLELISM": "false",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False", "PYTHONNOUSERSITE": "1",
    }
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", "--model-cache", str(cache), "--output", str(output), "--fixture", str(args.fixture.resolve())],
        env=environment, cwd=output, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
    )
    (output / "stdout.log").write_text(completed.stdout)
    (output / "stderr.log").write_text(completed.stderr)
    print(completed.stdout, end="")
    if completed.returncode:
        print(completed.stderr, file=sys.stderr)
    raise SystemExit(completed.returncode)

network_attempts = []
def deny_network(event, values):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}:
        network_attempts.append(event)
        raise RuntimeError("network prohibited in offline semantic evaluation")
sys.addaudithook(deny_network)

import onnxruntime
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
from zotero_mcp.chroma_client import ChromaClient

ONNXMiniLM_L6_V2.DOWNLOAD_PATH = cache
def deny_download(*unused_args, **unused_kwargs):
    raise RuntimeError("model download prohibited; populate an explicit public model cache first")
ONNXMiniLM_L6_V2._download = deny_download

fixture_bytes = args.fixture.read_bytes()
fixture = json.loads(fixture_bytes)
documents = fixture["documents"]
queries = fixture["queries"]
ids = [doc["id"] for doc in documents]
assert len(ids) == len(set(ids)) == 6
assert len(queries) >= 6 and all(query["expected"] in ids for query in queries)
texts = [doc["title"] + "\n" + doc["description"] for doc in documents]
(output / "fixture.json").write_bytes(fixture_bytes)
model_path = cache / "onnx" / "model.onnx"
model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
claim = "Compare diagnostic retrieval hit rates on six fixed public-paper descriptions. Latency is descriptive only, not a speed comparison or a full MCP benchmark."
(output / "design.json").write_text(json.dumps({
    "claim": claim, "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
    "rounds": 5, "query_modes": ["semantic_en", "semantic_zh", "keyword_en"],
    "keyword_baseline": "Case-insensitive English alphabetic token-set overlap on the same title and description; fixed stop words removed; zero-overlap documents excluded; ties broken by document ID.",
    "latency_scope": "Each semantic search calls installed ChromaClient.search, including query embedding, any per-call model-session setup, and collection retrieval; excludes imports, initial index creation and warmup. Keyword times include tokenization, scoring and sorting.",
}, ensure_ascii=False, indent=2))

start = time.perf_counter()
db = output / "chroma"
client = ChromaClient(collection_name="public_paper_diagnostic", persist_directory=str(db), embedding_model="default")
client.add_documents(documents=texts, metadatas=[{"source": doc["source"], "public_fixture": True} for doc in documents], ids=ids)
initialization_ms = (time.perf_counter() - start) * 1000
assert client.collection.count() == 6
stored = client.collection.get(include=["embeddings", "documents"])
assert set(stored["ids"]) == set(ids)
assert stored["embeddings"].shape == (6, 384)
assert (db / "chroma.sqlite3").is_file()
assert not any(name in sys.modules for name in ["zotero_mcp.client", "zotero_mcp.semantic_search"])

stopwords = set("a an and are as at be before by can do find for from how in is it of on or paper study that the this to which with without work".split())
def keywords(text):
    return set(re.findall(r"[a-z]+", text.lower())) - stopwords

def retrieve(mode, query):
    if mode == "keyword_en":
        query_words = keywords(query["en"])
        scores = [(len(query_words & keywords(text)), doc_id) for doc_id, text in zip(ids, texts)]
        ranked = sorted(scores, key=lambda row: (-row[0], row[1]))
        ranked = [row for row in ranked if row[0] > 0]
        return [row[1] for row in ranked], [row[0] for row in ranked]
    language = "zh" if mode == "semantic_zh" else "en"
    result = client.search([query[language]], n_results=6)
    return result["ids"][0], result["distances"][0]

for query in queries:
    for mode in ["semantic_en", "semantic_zh", "keyword_en"]:
        retrieve(mode, query)

original_run = onnxruntime.InferenceSession.run
inference_calls = 0
inference_rows = 0
def counted_run(session, output_names, input_feed, run_options=None):
    global inference_calls, inference_rows
    result = original_run(session, output_names, input_feed, run_options)
    inference_calls += 1
    inference_rows += len(input_feed["input_ids"])
    return result
onnxruntime.InferenceSession.run = counted_run
rows = []
rounds = []
for round_index in range(5):
    modes = ["semantic_en", "semantic_zh", "keyword_en"]
    modes = modes[round_index % 3:] + modes[:round_index % 3]
    round_rows = []
    for query in queries:
        for mode in modes:
            calls_before = inference_calls
            start = time.perf_counter()
            ranking, scores = retrieve(mode, query)
            elapsed_ms = (time.perf_counter() - start) * 1000
            actual_calls = inference_calls - calls_before
            assert actual_calls == (0 if mode == "keyword_en" else 1)
            assert len(ranking) == len(set(ranking)) and set(ranking) <= set(ids)
            row = {"round": round_index + 1, "mode": mode, "query_id": query["id"], "query": query["zh" if mode == "semantic_zh" else "en"], "expected": query["expected"], "ranking": ranking, "scores": scores, "elapsed_ms": elapsed_ms, "onnx_calls": actual_calls, "top1": bool(ranking and ranking[0] == query["expected"]), "top3": query["expected"] in ranking[:3]}
            rows.append(row)
            round_rows.append(row)
    rounds.append({"round": round_index + 1, "mode_order_per_query": modes, "modes": {mode: {"elapsed_ms_total": sum(row["elapsed_ms"] for row in round_rows if row["mode"] == mode), "top1_count": sum(row["top1"] for row in round_rows if row["mode"] == mode), "top3_count": sum(row["top3"] for row in round_rows if row["mode"] == mode)} for mode in modes}})
onnxruntime.InferenceSession.run = original_run
profiler = cProfile.Profile()
profiler.enable()
for query in queries:
    retrieve("semantic_en", query)
profiler.disable()
profiler.dump_stats(str(output / "unreported-profile.pstats"))
summary = {}
for mode in ["semantic_en", "semantic_zh", "keyword_en"]:
    matching = [row for row in rows if row["mode"] == mode]
    totals = [entry["modes"][mode]["elapsed_ms_total"] for entry in rounds]
    summary[mode] = {"queries_per_round": len(queries), "rounds": 5, "top1_hits_per_round": [entry["modes"][mode]["top1_count"] for entry in rounds], "top3_hits_per_round": [entry["modes"][mode]["top3_count"] for entry in rounds], "round_ms_median": statistics.median(totals), "round_ms_range": [min(totals), max(totals)], "query_ms_median": statistics.median(row["elapsed_ms"] for row in matching)}
report = {
    "claim": claim, "summary": summary, "rounds": rounds, "results": rows,
    "evidence": {"database": str(db), "count": client.collection.count(), "embedding_shape": list(stored["embeddings"].shape), "embedding_function": type(client.embedding_function).__name__, "model_path": str(model_path), "model_sha256": model_sha256, "model_bytes": model_path.stat().st_size, "onnx_inference_calls_in_timed_queries": inference_calls, "onnx_input_rows_in_timed_queries": inference_rows, "network_attempts": network_attempts, "failed_queries": 0, "initialization_and_index_ms": initialization_ms, "cpu_count": os.cpu_count(), "load_average": list(os.getloadavg()), "packages": {name: importlib.metadata.version(name) for name in ["zotero-mcp-server", "chromadb", "onnxruntime", "tokenizers"]}, "environment_keys": sorted(os.environ), "isolated_home": str(Path.home()), "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(), "source_module": __import__("zotero_mcp.chroma_client", fromlist=["__file__"]).__file__},
    "limitations": ["Six hand-written descriptions are easy and do not represent full abstracts, full texts or the user's personal library.", "One exact expected document per query was assigned manually before running. Five repeated rounds measure reproducibility, not thirty independent relevance judgments.", "No full MCP server, Zotero API, automatic indexing, chunking, reranking or personal-library integration was exercised.", "The English keyword baseline is a simple token overlap reference, not Zotero's actual lexical search implementation.", "Manual English equivalents are supplied in the fixture. No translation service or automatic translation path was tested.", "Timings include low-overhead inference-call counting. Other work on the machine may affect them. No production performance or speedup claim is made.", "Python network audit and disabled model download block normal Python network paths. This is not an operating-system network sandbox."]
}
(output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"summary": summary, "evidence": report["evidence"]}, ensure_ascii=False, indent=2))
