"""The benchmark script runs, writes its report, and the vote path keeps the genre rerank."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from benchmarks import fairness
from tests.conftest import host_headers


def test_benchmark_writes_report(tmp_path):
    fairness.main(["--seeds", "0-1", "--plays", "10", "--repeats", "1", "--out", str(tmp_path)])
    data = json.loads((tmp_path / "fairness.json").read_text())
    assert set(data["overall"]) == set(fairness.STRATEGIES)
    assert "| current |" in (tmp_path / "fairness.md").read_text()


def _without_latency(result):
    return {mix: {s: {k: v for k, v in row.items() if k != "latency_ms_median"} for s, row in rows.items()}
            for mix, rows in result["per_mix"].items()}


def test_same_seed_same_metrics(tmp_path):
    a = fairness.run([3], plays=10, repeats=1)
    b = fairness.run([3], plays=10, repeats=1)
    assert _without_latency(a) == _without_latency(b)


def test_vote_keeps_the_genre_rerank(client: TestClient, party_code: str):
    for name, genre in [("A", "pop"), ("B", "pop"), ("C", "pop"), ("D", "jazz")]:
        client.post(f"/party/{party_code}/join", json={"display_name": name, "genre": genre})
    queue = client.post(f"/party/{party_code}/generate-queue", headers=host_headers(party_code)).json()["queue"]
    tracks = [fairness.Track(id=q["track_id"], name=q["name"], artist=q["artist"], genres=q["genres"]) for q in queue]
    before = fairness.longest_shared_genre_run(tracks[:20])
    voted = client.post(f"/party/{party_code}/vote", json={"track_id": queue[5]["track_id"], "value": 1},
                        headers=host_headers(party_code)).json()["queue"]
    after = fairness.longest_shared_genre_run(
        [fairness.Track(id=q["track_id"], name=q["name"], artist=q["artist"], genres=q["genres"]) for q in voted][:20])
    assert after <= max(before, 2)
