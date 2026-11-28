"""Turn an llm-eval-kit report into the nightly drift verdict and a Markdown summary.

Used by .github/workflows/drift.yml. Drift means any of:
  - a critical case failed (no tolerance),
  - the regression gate against the committed baseline failed (quality dropped beyond tolerance,
    or a critical baseline case is missing from the run),
  - the run stopped early on a limit such as --max-cost.

Usage: python drift_report.py REPORT_JSON SUMMARY_MD
Writes the Markdown to SUMMARY_MD and `status=clean|drift|error` to $GITHUB_OUTPUT when set.
A missing or unreadable report is `error`: the run broke (outage, bad key), which is not drift.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def verdict(report: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    critical = sorted(r["id"] for r in report.get("results", []) if r.get("critical") and not r.get("passed"))
    if critical:
        reasons.append(f"critical cases failed: {', '.join(critical)}")
    reg = report.get("regression")
    if reg is None:
        reasons.append("no regression result: the run did not compare against a baseline")
    elif not reg.get("passed"):
        reasons += [r for r in reg.get("reasons", []) if not r.startswith("critical cases failed")]
        if not reasons:
            reasons.append("regression gate failed")
    if report.get("stopped_reason"):
        reasons.append(f"run stopped early: {report['stopped_reason']}")
    return ("drift" if reasons else "clean"), reasons


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render(report: dict, status: str, reasons: list[str], run_url: str) -> str:
    usage = report.get("usage") or {}
    cost = usage.get("live_cost_usd")
    reg = report.get("regression") or {}
    critical = sorted(r["id"] for r in report.get("results", []) if r.get("critical") and not r.get("passed"))
    lines = [
        f"## LLM summary drift check: {'clean' if status == 'clean' else 'DRIFT DETECTED'}",
        "",
        f"Suite `{report.get('suite_name')}`, model `{report.get('provider')}/{report.get('model')}`.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Pass rate | {report.get('passed')}/{report.get('total')} ({_pct(report.get('pass_rate'))}) |",
        f"| Critical failures | {len(critical)}{' (' + ', '.join(critical) + ')' if critical else ''} |",
        f"| Non-critical pass rate vs baseline | {_pct(reg.get('pass_rate_baseline'))} -> "
        f"{_pct(reg.get('pass_rate_current'))} |",
        f"| Non-critical mean score vs baseline | {_num(reg.get('mean_score_baseline'))} -> "
        f"{_num(reg.get('mean_score_current'))} |",
        f"| Regression gate | {'passed' if reg.get('passed') else 'failed'} |",
        f"| Live calls | {usage.get('live_calls', 0)} |",
        f"| Estimated cost | {'unknown' if cost is None else f'${cost:.6f}'} |",
    ]
    if reasons:
        lines += ["", "Reasons:", *[f"- {r}" for r in reasons]]
    if reg.get("newly_failing"):
        lines += ["", f"Newly failing non-critical cases: {', '.join(reg['newly_failing'])}"]
    failed = [r for r in report.get("results", []) if not r.get("passed")]
    if failed:
        lines += ["", "Failed cases:"]
        for r in failed:
            # model and judge text goes into an issue, so break any @mention it might carry
            detail = " ".join(str(r.get("detail", "")).split())[:300].replace("@", "@​")
            lines.append(f"- `{r.get('id')}`{' (critical)' if r.get('critical') else ''}: {detail}")
    for w in report.get("warnings", []):
        lines += ["", f"Note: {w}"]
    if run_url:
        lines += ["", f"Run: {run_url}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    report_path, summary_path = Path(argv[1]), Path(argv[2])
    run_url = os.environ.get("RUN_URL", "")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        status, reasons = verdict(report)
        text = render(report, status, reasons, run_url)
    except (OSError, ValueError, KeyError, TypeError) as e:
        status = "error"
        text = (
            "## LLM summary drift check: run error\n\n"
            f"No usable report at `{report_path}` ({type(e).__name__}). The live run broke before it could be "
            "scored, for example a provider outage or a bad key. This is not counted as drift; see the logs.\n"
        )
        if run_url:
            text += f"\nRun: {run_url}\n"
    summary_path.write_text(text, encoding="utf-8")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
