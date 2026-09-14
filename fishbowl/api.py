"""JSON API - every route is a GET, nothing here can mutate anything."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .config import cost_for
from .status import classify


def handle_api(app, path: str, query: dict) -> tuple[int, dict]:
    """Route an /api/* request. Returns (http_status, json_dict)."""
    if path == "/api/health":
        return 200, _health(app)

    if path == "/api/projects":
        return 200, _projects(app)

    if path == "/api/sessions":
        return 200, {"sessions": _sessions(app)}

    if path == "/api/stats":
        return 200, _stats(app)

    # /api/sessions/{sid} and /api/sessions/{sid}/activities
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[:2] == ["api", "sessions"]:
        return _session_detail(app, parts[2])
    if len(parts) == 4 and parts[:2] == ["api", "sessions"] \
            and parts[3] == "activities":
        return _session_activities(app, parts[2], query)

    return 404, {"error": "not found"}


# --------------------------------------------------------------------

def _health(app) -> dict:
    st = app.scanner.last_stats
    return {
        "version": _version(),
        "mode": "demo" if app._replay else "live",
        "source_root": str(app.cfg.source_root),
        "files_watched": st.files_watched,
        "files_changed": st.files_changed,
        "lines_parsed": st.lines_parsed,
        "lines_skipped": st.lines_skipped,
        "parse_errors": st.parse_errors,
        "last_scan_ms": st.duration_ms,
        "indexing": not app.scanner.first_pass_done,
    }


def _version():
    from . import __version__
    return __version__


def _display_project(project_dir: str, cwd: str | None) -> str:
    """Prefer the session's real cwd; fall back to the encoded dir."""
    if cwd:
        return cwd
    # "C--Users-demo-x" style: readable enough as-is, no lossy decode
    return project_dir


def _sessions(app) -> list[dict]:
    now = time.time()
    out = []
    for s in list(app.store.sessions.values()):
        s.status = classify(s, app.cfg, now)
        d = s.to_dict()
        d["project"] = _display_project(s.project_dir, s.cwd)
        d["cost_usd"] = cost_for(app.cfg.prices,
                                 _primary_model(s), d["usage"])
        out.append(d)
    out.sort(key=lambda d: d.get("last_activity_at") or "", reverse=True)
    return out


def _primary_model(s) -> str | None:
    if s.usage.models:
        return s.usage.models.most_common(1)[0][0]
    return None


def _projects(app) -> list[dict]:
    groups: dict[str, dict] = {}
    for d in _sessions(app):
        g = groups.setdefault(d["project"], {
            "project": d["project"], "session_count": 0,
            "active": 0, "idle": 0, "stalled": 0})
        g["session_count"] += 1
        g[d["status"]] = g.get(d["status"], 0) + 1
    return sorted(groups.values(),
                  key=lambda g: g["project"].lower())


def _session_detail(app, sid: str) -> tuple[int, dict]:
    s = app.store.get(sid)
    if s is None:
        return 404, {"error": "unknown session"}
    now = time.time()
    s.status = classify(s, app.cfg, now)
    d = s.to_dict()
    d["project"] = _display_project(s.project_dir, s.cwd)
    d["cost_usd"] = cost_for(app.cfg.prices, _primary_model(s),
                             d["usage"])
    tail = app.store.activities(sid, limit=200)["items"]
    return 200, {"session": d, "activities": tail}


def _session_activities(app, sid: str, query: dict) -> tuple[int, dict]:
    if app.store.get(sid) is None:
        return 404, {"error": "unknown session"}
    before = (query.get("before") or [None])[0]
    try:
        limit = int((query.get("limit") or ["500"])[0])
    except ValueError:
        limit = 500
    return 200, app.store.activities(sid, before_key=before, limit=limit)


def _stats(app) -> dict:
    sessions = _sessions(app)
    by_model: dict[str, dict] = {}
    day_ago = time.time() - 86400
    recent = {"input_tokens": 0, "cache_read_tokens": 0,
              "cache_write_tokens": 0, "output_tokens": 0}

    def epoch(ts):
        try:
            return datetime.fromisoformat(
                ts.replace("Z", "+00:00")).timestamp() if ts else 0
        except ValueError:
            return 0

    for d in sessions:
        u = d["usage"]
        for model, turns in u["models"].items():
            bucket = by_model.setdefault(model, {
                "model": model, "turns": 0,
                "input_tokens": 0, "cache_read_tokens": 0,
                "cache_write_tokens": 0, "output_tokens": 0})
            bucket["turns"] += turns
        # attribute all of a session's usage to its primary model
        pm = _primary_model_from_dict(u)
        if pm and pm in by_model:
            b = by_model[pm]
            b["input_tokens"] += u["input_tokens"]
            b["cache_read_tokens"] += u["cache_read_tokens"]
            b["cache_write_tokens"] += u["cache_write_tokens"]
            b["output_tokens"] += u["output_tokens"]
        if epoch(d.get("last_activity_at")) >= day_ago:
            for k in recent:
                recent[k] += u.get(k, 0)

    for b in by_model.values():
        b["cost_usd"] = cost_for(app.cfg.prices, b["model"], b)

    top = sorted(
        ({"session_id": d["session_id"], "title": d["title"],
          "project": d["project"], "status": d["status"],
          "cost_usd": d["cost_usd"], "total_tokens":
          _total_tokens(d["usage"])}
         for d in sessions if d["cost_usd"] is not None),
        key=lambda x: x["cost_usd"], reverse=True)[:10]

    return {
        "session_count": len(sessions),
        "sessions_by_status": {
            st: sum(1 for d in sessions if d["status"] == st)
            for st in ("active", "idle", "stalled", "archived")},
        "by_model": sorted(by_model.values(),
                           key=lambda b: b["turns"], reverse=True),
        "last_24h": recent,
        "priciest_sessions": top,
    }


def _primary_model_from_dict(usage: dict) -> str | None:
    models = usage.get("models") or {}
    if not models:
        return None
    return max(models.items(), key=lambda kv: kv[1])[0]


def _total_tokens(u: dict) -> int:
    return (u.get("input_tokens", 0) + u.get("cache_read_tokens", 0)
            + u.get("cache_write_tokens", 0) + u.get("output_tokens", 0))
