#!/usr/bin/env python3
"""Local install analytics for Darvish D Bot.

This module keeps a small JSON file and generates an SVG line chart that can be
shown in README.md. It is intentionally dependency-free and works on a fresh VPS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DATA_FILE = DOCS_DIR / "install_stats.json"
CHART_FILE = DOCS_DIR / "install_chart.svg"
DOWNLOAD_CHART_FILE = DOCS_DIR / "download_chart.svg"
DEFAULT_START_DATE = os.environ.get("PROJECT_GITHUB_ADDED_DATE", "2026-06-21")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def today_utc() -> date:
    return utc_now().date()


def parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        return fallback


def load_stats() -> dict[str, Any]:
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("project_added_date", DEFAULT_START_DATE)
                data.setdefault("total_installs", 0)
                data.setdefault("daily", {})
                data.setdefault("events", [])
                return data
        except Exception:
            pass
    return {
        "project_added_date": DEFAULT_START_DATE,
        "total_installs": 0,
        "daily": {},
        "events": [],
        "last_updated_utc": utc_now().isoformat(),
    }


def save_stats(data: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    data["last_updated_utc"] = utc_now().isoformat()
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def machine_id() -> str:
    raw = ""
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8", errors="ignore").strip()
                break
        except Exception:
            pass
    if not raw:
        raw = socket.gethostname()
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def git_info() -> dict[str, str]:
    def run(cmd: list[str]) -> str:
        try:
            return subprocess.check_output(cmd, cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
        except Exception:
            return ""
    return {
        "commit": run(["git", "rev-parse", "--short", "HEAD"]),
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "remote": run(["git", "config", "--get", "remote.origin.url"]),
    }


def record_install(source: str) -> None:
    data = load_stats()
    day = today_utc().isoformat()
    data["daily"][day] = int(data.get("daily", {}).get(day, 0)) + 1
    data["total_installs"] = int(data.get("total_installs", 0)) + 1
    events = data.setdefault("events", [])
    events.append({
        "time_utc": utc_now().isoformat(),
        "source": source,
        "machine": machine_id(),
        **git_info(),
    })
    # Keep the file compact for repositories.
    if len(events) > 5000:
        data["events"] = events[-5000:]
    save_stats(data)
    generate_chart()


def date_range(start: date, end: date) -> list[date]:
    if end < start:
        return [end]
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def cumulative_points(data: dict[str, Any]) -> list[tuple[date, int]]:
    start = parse_date(str(data.get("project_added_date") or DEFAULT_START_DATE), today_utc())
    end = today_utc()
    daily = data.get("daily", {}) or {}
    total = 0
    points: list[tuple[date, int]] = []
    for d in date_range(start, end):
        total += int(daily.get(d.isoformat(), 0))
        points.append((d, total))
    return points or [(end, int(data.get("total_installs", 0)))]


def nice_label(d: date) -> str:
    return d.strftime("%b %d")


def svg_escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_chart() -> None:
    data = load_stats()
    points = cumulative_points(data)
    width, height = 920, 420
    left, right, top, bottom = 70, 36, 78, 70
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_y = max(1, max(v for _, v in points))
    min_y = 0

    def x_at(idx: int) -> float:
        if len(points) == 1:
            return left + plot_w
        return left + (plot_w * idx / (len(points) - 1))

    def y_at(v: int) -> float:
        return top + plot_h - ((v - min_y) / max(1, max_y - min_y)) * plot_h

    coords = [(x_at(i), y_at(v)) for i, (_, v) in enumerate(points)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"{left},{top+plot_h} " + polyline + f" {left+plot_w},{top+plot_h}"

    grid_lines = []
    y_labels = []
    steps = 4
    for i in range(steps + 1):
        value = round(max_y * i / steps)
        y = y_at(value)
        grid_lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#274762" stroke-width="1" opacity="0.55"/>')
        y_labels.append(f'<text x="{left-14}" y="{y+5:.1f}" text-anchor="end" fill="#9fc9ea" font-size="13">{value}</text>')

    ticks = []
    max_ticks = 6
    if len(points) <= max_ticks:
        idxs = list(range(len(points)))
    else:
        idxs = sorted(set(round(i * (len(points) - 1) / (max_ticks - 1)) for i in range(max_ticks)))
    for i in idxs:
        d, _ = points[i]
        x = x_at(i)
        ticks.append(f'<text x="{x:.1f}" y="{height-32}" text-anchor="middle" fill="#9fc9ea" font-size="13">{svg_escape(nice_label(d))}</text>')

    current_total = points[-1][1]
    start_label = points[0][0].isoformat()
    end_label = points[-1][0].isoformat()
    last_updated = str(data.get("last_updated_utc", utc_now().isoformat())).replace("+00:00", "Z")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Darvish D Bot install chart">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#071626"/><stop offset="1" stop-color="#0b2f55"/></linearGradient>
    <linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#37c8ff" stop-opacity="0.45"/><stop offset="1" stop-color="#37c8ff" stop-opacity="0.03"/></linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="3.2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect width="{width}" height="{height}" rx="24" fill="url(#bg)"/>
  <rect x="18" y="18" width="{width-36}" height="{height-36}" rx="20" fill="none" stroke="#35b8ff" stroke-width="2" opacity="0.75"/>
  <text x="{left}" y="44" fill="#ffffff" font-size="24" font-family="Inter,Segoe UI,Arial,sans-serif" font-weight="700">Installation growth</text>
  <text x="{left}" y="67" fill="#9fc9ea" font-size="14" font-family="Inter,Segoe UI,Arial,sans-serif">Cumulative installs from {svg_escape(start_label)} to {svg_escape(end_label)}</text>
  <text x="{width-right}" y="50" text-anchor="end" fill="#ffffff" font-size="30" font-family="Inter,Segoe UI,Arial,sans-serif" font-weight="800">{current_total}</text>
  <text x="{width-right}" y="70" text-anchor="end" fill="#9fc9ea" font-size="13" font-family="Inter,Segoe UI,Arial,sans-serif">total installs</text>
  {''.join(grid_lines)}
  {''.join(y_labels)}
  <polygon points="{area}" fill="url(#area)"/>
  <polyline points="{polyline}" fill="none" stroke="#39c8ff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>
  <circle cx="{coords[-1][0]:.1f}" cy="{coords[-1][1]:.1f}" r="6" fill="#ffffff" stroke="#39c8ff" stroke-width="4"/>
  {''.join(ticks)}
  <text x="{left}" y="{height-14}" fill="#7daed4" font-size="12" font-family="Inter,Segoe UI,Arial,sans-serif">Last updated: {svg_escape(last_updated)}</text>
  <text x="{width-right}" y="{height-14}" text-anchor="end" fill="#7daed4" font-size="12" font-family="Inter,Segoe UI,Arial,sans-serif">Generated by scripts/install_analytics.py</text>
</svg>
'''
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    CHART_FILE.write_text(svg, encoding="utf-8")
    download_svg = svg.replace("Installation growth", "Download growth").replace("Cumulative installs", "Cumulative downloads").replace("total installs", "total downloads").replace("Generated by scripts/install_analytics.py", "Generated by scripts/install_analytics.py")
    download_svg = download_svg.replace("install chart", "download chart")
    DOWNLOAD_CHART_FILE.write_text(download_svg, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Track and render installation analytics.")
    sub = parser.add_subparsers(dest="command")
    record = sub.add_parser("record", help="Record one install event and regenerate the chart")
    record.add_argument("--source", default=os.environ.get("INSTALL_SOURCE", "install.sh"))
    sub.add_parser("generate", help="Regenerate chart without recording a new install")
    sub.add_parser("show", help="Print current stats JSON")
    args = parser.parse_args()

    if args.command == "record":
        record_install(args.source)
    elif args.command == "generate":
        generate_chart()
    elif args.command == "show":
        print(json.dumps(load_stats(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
