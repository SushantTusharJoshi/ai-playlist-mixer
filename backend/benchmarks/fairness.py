"""
Fairness benchmark: simulated parties, three queue strategies, measured metrics.

    cd backend && python -m benchmarks.fairness --seeds 0-29 --plays 20

Writes benchmarks/results/fairness.json and benchmarks/results/fairness.md.
Every number in the report comes from this script; nothing is estimated.

Strategies
- popularity: all guests' candidate tracks sorted by popularity (no personalisation)
- round_robin: take turns by guest; each guest's next pick is their best unplayed track
- current: RankingAgent.rank then FairnessAgent.rerank (what Generate Queue does)
- current_no_rerank: RankingAgent.rank alone (ablation: what the rerank adds)
- current_after_vote: current, then one upvote handled the way the vote endpoint
  does it now (re-sort by score, then the same genre rerank)
- after_vote_sort_only: current, then one upvote handled the way the vote
  endpoint did it before this change (re-sort by score only)

A guest is "served" by a play when user_track_affinity >= 0.55, the same
threshold the app uses for matched_users.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import random
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.agents.fairness_agent import FairnessAgent, reorder_after_vote
from app.agents.ranking_agent import RankingAgent
from app.agents.voting_agent import vote_boost
from app.data import GENRE_DEFAULTS, tracks_for_genre
from app.ml.features import user_track_affinity
from app.models.schemas import QueueItem, Track, UserProfile

MATCH = 0.55
RESULTS = Path(__file__).resolve().parent / "results"

# Guest mixes: genre per guest (7 is the app's device cap).
MIXES: dict[str, list[str]] = {
    "balanced_7": ["pop", "hip hop", "rock", "edm", "latin", "jazz", "country"],
    "pop_majority": ["pop", "pop", "pop", "pop", "pop", "jazz", "country"],
    "two_camps": ["edm", "edm", "edm", "rock", "rock", "rock"],
    "one_outlier": ["hip hop", "hip hop", "hip hop", "hip hop", "hip hop", "hip hop", "jazz"],
    "small_3": ["k-pop", "indie", "r&b"],
}
STRATEGIES = ["popularity", "round_robin", "current", "current_no_rerank", "current_after_vote",
              "after_vote_sort_only"]

ranking_agent = RankingAgent()
fairness_agent = FairnessAgent()


# ── party simulation ───────────────────────────────

def make_guests(genres: list[str], rng: random.Random) -> list[UserProfile]:
    """Guests built like /join does, with seeded variation in taste and candidate tracks."""
    guests = []
    for i, genre in enumerate(genres):
        d = GENRE_DEFAULTS[genre]
        pool = tracks_for_genre(genre, 100)
        candidates = rng.sample(pool, min(12, len(pool)))
        guests.append(UserProfile(
            id=f"g{i}", display_name=f"guest{i}", genre=genre, top_genres=d["related"][:3],
            preferred_energy=min(1.0, max(0.0, d["energy"] + rng.uniform(-0.08, 0.08))),
            preferred_danceability=min(1.0, max(0.0, d["danceability"] + rng.uniform(-0.08, 0.08))),
            candidate_tracks=candidates,
        ))
    return guests


def strategy_queue(name: str, guests: list[UserProfile], rng: random.Random) -> list[Track]:
    if name == "popularity":
        pool = {t.id: t for g in guests for t in g.candidate_tracks}
        return sorted(pool.values(), key=lambda t: (-t.popularity, t.id))
    if name == "round_robin":
        prefs = [sorted(g.candidate_tracks, key=lambda t: (-user_track_affinity(t, g), t.id)) for g in guests]
        played, out = set(), []
        while any(prefs):
            for p in prefs:
                while p and p[0].id in played:
                    p.pop(0)
                if p:
                    t = p.pop(0)
                    played.add(t.id)
                    out.append(t)
        return out
    if name == "current_no_rerank":
        return [q.track for q in ranking_agent.rank(guests)]
    queue = fairness_agent.rerank(ranking_agent.rank(guests))
    if name == "current_after_vote":
        queue = reorder_after_vote(upvote_one(queue, rng))
    elif name == "after_vote_sort_only":
        queue = sorted(upvote_one(queue, rng), key=lambda x: x.score, reverse=True)
    return [q.track for q in queue]


def upvote_one(queue: list[QueueItem], rng: random.Random) -> list[QueueItem]:
    """Mirror of POST /vote: one random track gets +1 and the clamped boost."""
    queue = [q.model_copy() for q in queue]
    item = rng.choice(queue)
    old, item.votes = item.votes, item.votes + 1
    item.score = round(item.score - vote_boost(old) + vote_boost(item.votes), 4)
    return queue


# ── metrics ────────────────────────────────────────

def gini(values: list[float]) -> float:
    if not values or sum(values) == 0:
        return 0.0
    xs = sorted(values)
    n = len(xs)
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * sum(xs)) - (n + 1) / n


def longest_shared_genre_run(tracks: list[Track]) -> int:
    """Longest stretch of back-to-back tracks where each shares a genre tag with the one before."""
    best = run = 1 if tracks else 0
    for a, b in zip(tracks, tracks[1:], strict=False):
        shared = {g.lower() for g in a.genres} & {g.lower() for g in b.genres}
        run = run + 1 if shared else 1
        best = max(best, run)
    return best


def metrics(tracks: list[Track], guests: list[UserProfile], plays: int) -> dict:
    played = tracks[:plays]
    served = {g.id: 0 for g in guests}
    exposure = {g.id: 0.0 for g in guests}
    first = {g.id: None for g in guests}
    for pos, t in enumerate(played):
        for g in guests:
            if user_track_affinity(t, g) >= MATCH:
                served[g.id] += 1
                exposure[g.id] += 1 / math.log2(pos + 2)
                if first[g.id] is None:
                    first[g.id] = pos + 1
    counts = list(served.values())
    exp = list(exposure.values())
    waits = [w if w is not None else plays + 1 for w in first.values()]
    return {
        "plays_min": min(counts),
        "plays_max": max(counts),
        "plays_min_max_ratio": (min(counts) / max(counts)) if max(counts) else 0.0,
        "plays_gini": gini(counts),
        "guests_never_served": sum(1 for c in counts if c == 0),
        "worst_guest_wait": max(waits),
        "exposure_min_max_ratio": (min(exp) / max(exp)) if max(exp) else 0.0,
        "distinct_genres": len({g.lower() for t in played for g in t.genres}),
        "longest_same_genre_run": longest_shared_genre_run(played),
    }


def time_strategy(name: str, guests: list[UserProfile], seed: int, repeats: int) -> float:
    samples = []
    for r in range(repeats):
        rng = random.Random(seed * 1000 + r)
        start = time.perf_counter()
        strategy_queue(name, guests, rng)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def rerank_scaling(sizes: list[int], repeats: int, seed: int) -> list[dict]:
    """FairnessAgent.rerank alone on synthetic queues of growing size.

    mixed: two random genre tags per track, so the scan usually stops early.
    one_genre: every track shares a tag, so every step scans everything left (the O(n^2) case).
    """
    rng = random.Random(seed)
    genres = [g for d in GENRE_DEFAULTS.values() for g in d["related"]]

    def timed(queue):
        samples = []
        for _ in range(repeats):
            start = time.perf_counter()
            fairness_agent.rerank(queue)
            samples.append((time.perf_counter() - start) * 1000)
        return statistics.median(samples)

    rows = []
    for n in sizes:
        mixed = [QueueItem(track=Track(id=f"s{i}", name="t", artist="a", genres=rng.sample(genres, 2)),
                           score=rng.random()) for i in range(n)]
        mixed.sort(key=lambda q: q.score, reverse=True)
        same = [QueueItem(track=Track(id=f"o{i}", name="t", artist="a", genres=["pop"]), score=1 - i / n)
                for i in range(n)]
        rows.append({"queue_size": n, "mixed_ms_median": timed(mixed), "one_genre_ms_median": timed(same)})
    return rows


# ── report ─────────────────────────────────────────

def run(seeds: list[int], plays: int, repeats: int) -> dict:
    per_mix = {}
    for mix, genres in MIXES.items():
        rows = {s: [] for s in STRATEGIES}
        lat = {s: [] for s in STRATEGIES}
        for seed in seeds:
            guests = make_guests(genres, random.Random(seed))
            for s in STRATEGIES:
                rows[s].append(metrics(strategy_queue(s, guests, random.Random(seed)), guests, plays))
                lat[s].append(time_strategy(s, guests, seed, repeats))
        per_mix[mix] = {
            s: {**{k: statistics.mean(r[k] for r in rows[s]) for k in rows[s][0]},
                "latency_ms_median": statistics.median(lat[s])}
            for s in STRATEGIES
        }
    overall = {
        s: {k: statistics.mean(per_mix[m][s][k] for m in MIXES) for k in per_mix[next(iter(MIXES))][s]}
        for s in STRATEGIES
    }
    return {"per_mix": per_mix, "overall": overall}


def to_markdown(result: dict, meta: dict) -> str:
    cols = [("plays_min_max_ratio", "plays min/max", 2), ("plays_gini", "plays Gini", 3),
            ("guests_never_served", "guests never served", 2), ("worst_guest_wait", "worst guest wait", 1),
            ("exposure_min_max_ratio", "exposure min/max", 2), ("distinct_genres", "distinct genres", 1),
            ("longest_same_genre_run", "longest same-genre run", 1), ("latency_ms_median", "latency ms", 3)]

    def table(rows: dict) -> list[str]:
        out = ["| strategy | " + " | ".join(c[1] for c in cols) + " |",
               "|---|" + "---:|" * len(cols)]
        for s in STRATEGIES:
            out.append(f"| {s} | " + " | ".join(f"{rows[s][k]:.{d}f}" for k, _, d in cols) + " |")
        return out

    lines = [
        "# Fairness benchmark",
        "",
        f"Generated by `{meta['command']}` on {meta['generated_at']} "
        f"(Python {meta['python']}, {meta['platform']}). Seeds {meta['seeds']}, first {meta['plays']} plays.",
        "Every value is measured by `backend/benchmarks/fairness.py`; means over seeds, latency is the median.",
        "Latency depends on the machine; compare strategies with each other, not with other machines.",
        "",
        "Metrics: a guest is served by a play when their affinity for the track is at least 0.55 (the app's",
        "match threshold). plays min/max = least-served guest's plays / most-served guest's plays (1.0 is even).",
        "Gini over plays per guest (0 is even). Worst guest wait = position of the first play that serves the",
        "guest who waits longest (plays + 1 if never served). Exposure weights each play by 1/log2(position + 1).",
        "Longest same-genre run = back-to-back tracks that each share a genre tag with the previous one.",
        "",
        "## All mixes (mean of per-mix means)",
        "",
        *table(result["overall"]),
        "",
    ]
    for mix, rows in result["per_mix"].items():
        lines += [f"## {mix}: {', '.join(MIXES[mix])}", "", *table(rows), ""]
    lines += ["## FairnessAgent.rerank scaling", "",
              "Synthetic queues, median of repeats. mixed: two random genre tags per track. one_genre: every",
              "track shares one tag, so each step scans the whole remainder (the quadratic case).", "",
              "| queue size | mixed ms | one_genre ms |", "|---:|---:|---:|"]
    lines += [f"| {r['queue_size']} | {r['mixed_ms_median']:.3f} | {r['one_genre_ms_median']:.3f} |"
              for r in meta["rerank_scaling"]]
    return "\n".join(lines) + "\n"


def parse_seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",")]


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", default="0-29")
    ap.add_argument("--plays", type=int, default=20)
    ap.add_argument("--repeats", type=int, default=5, help="timing repeats per strategy and seed")
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args(argv)
    seeds = parse_seeds(args.seeds)

    result = run(seeds, args.plays, args.repeats)
    meta = {
        "command": f"python -m benchmarks.fairness --seeds {args.seeds} --plays {args.plays} --repeats {args.repeats}",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "seeds": args.seeds,
        "plays": args.plays,
        "mixes": MIXES,
        "rerank_scaling": rerank_scaling([25, 50, 100, 200, 400], repeats=args.repeats, seed=seeds[0]),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fairness.json").write_text(json.dumps({"meta": meta, **result}, indent=2) + "\n")
    (out / "fairness.md").write_text(to_markdown(result, meta))
    print(to_markdown(result, meta))
    return result


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
