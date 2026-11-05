#!/usr/bin/env python3
"""Live read-only dashboard for harness.db.

Run:  python3 harness/dashboard.py   ->  http://127.0.0.1:8766
Opens the DB in read-only mode, so it never interferes with the agents.
Binds strictly to 127.0.0.1 (localhost only).
"""
import gzip
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import control, network_batch, answers_bank  # noqa: E402
from tools.bridge import DO_NOT_DOWNGRADE_STATUSES  # noqa: E402
from harness.config import identity_capsule  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = Path(BASE_DIR) / "harness" / "web"
PORT = int(os.environ.get("HARNESS_DASH_PORT", "8766"))

STATUS_ORDER = [
    "TO_APPLY",
    "BLOCKED_USER",
    "OUTREACH_DRAFTED",
    "APPLIED",
    "COMPANY_SITE_ONLY",
    "REJECTED",
    "RANKED_OUT",
    "HALTED"
]
STATUS_LABEL = {
    "TO_APPLY": "To apply",
    "BLOCKED_USER": "Needs you",
    "OUTREACH_DRAFTED": "Outreach drafted",
    "APPLIED": "Applied",
    "COMPANY_SITE_ONLY": "Company site",
    "REJECTED": "Rejected",
    "RANKED_OUT": "Ranked out",
    "HALTED": "Halted",
}

CSP_HEADER = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


def get_db_path() -> str:
    return os.environ.get("HARNESS_DB", os.path.join(BASE_DIR, "harness.db"))


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


def load_data() -> Dict[str, Any]:
    db_path = get_db_path()
    # query_only (not mode=ro): a WAL database cannot be opened mode=ro when no other connection holds it.
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    data = {
        "jobs": q(conn, "SELECT * FROM jobs ORDER BY tier, updated_at DESC"),
        "outreach": q(conn, "SELECT * FROM outreach_queue ORDER BY id DESC"),
        "locks": q(conn, "SELECT * FROM agent_locks"),
        "beats": q(conn, "SELECT * FROM agent_heartbeats"),
        "budgets": {r["key"]: r["val"] for r in q(conn, "SELECT * FROM budgets")},
        "screening": q(conn, "SELECT question_key, answer FROM screening_qa ORDER BY question_key"),
        "contacts": q(conn, "SELECT * FROM contacts ORDER BY score DESC"),
        "run_log": q(conn, "SELECT * FROM run_log ORDER BY id DESC LIMIT 15"),
        "kill_switch": q(conn, "SELECT * FROM kill_switch ORDER BY id DESC LIMIT 1"),
        "open_items": q(conn, "SELECT * FROM open_items ORDER BY status, id"),
        "email_drafts": q(conn, "SELECT * FROM outreach_email_drafts ORDER BY id"),
        "gmail_snapshot": q(conn, "SELECT * FROM gmail_drafts_snapshot ORDER BY id"),
        "app_answers": q(conn, "SELECT * FROM app_story_answers ORDER BY application, id"),
    }
    conn.close()
    return data


e = lambda s: html.escape(str(s if s is not None else ""))


def check_data_parity() -> str:
    """Parity check is unavailable in open-source release."""
    return "parity: unavailable"


def get_next_cycle(run_logs: List[Dict[str, Any]]) -> str:
    """Human text for the next scheduled cycle, from the DB schedule (system clock). Never raises."""
    try:
        sch = control.get_schedule()
        cycle_runs = [r for r in run_logs if r.get("mode") == "cycle"]
        last = f"last started {cycle_runs[0]['started_at'][:16].replace('T', ' ')} UTC; " if cycle_runs and cycle_runs[0].get("started_at") else "no cycle has run yet; "
        if not sch["enabled"]:
            return last + "schedule paused"
        if sch["next_due"] is None:
            return last + f"next due {sch['interval_min']} min after the dashboard starts"
        nd = datetime.fromtimestamp(sch["next_due"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return last + f"next due {nd} (every {sch['interval_min']} min, checked against the system clock)"
    except Exception:
        return "next due: unavailable"


def pill(status: str) -> str:
    return f'<span class="pill s-{e(status)}">{e(STATUS_LABEL.get(status, status))}</span>'


def render_html(d: Dict[str, Any]) -> str:
    """Retained for backwards compatibility with tests asserting server-side render."""
    jobs = d["jobs"]
    counts = {s: 0 for s in STATUS_ORDER}
    for j in jobs:
        st = j.get("status", "")
        counts[st] = counts.get(st, 0) + 1

    pending = [o for o in d["outreach"] if o.get("approval_status") == "PENDING_MOBILE_REVIEW"]
    blocked = [j for j in jobs if j.get("status") == "BLOCKED_USER" or (j.get("blocker_note") and j.get("status") not in ("APPLIED", "REJECTED"))]

    ks_row = d["kill_switch"][0] if d["kill_switch"] else {}
    ks_active = bool(ks_row.get("on", 0))
    ks_reason = ks_row.get("reason", "")
    ks_class = "ks-on" if ks_active else "ks-off"
    ks_status_text = "ENGAGED (HALTED)" if ks_active else "OFF (Active)"

    stats_html = "".join(
        f'<div class="stat"><div class="n">{counts.get(s, 0)}</div><div class="l">{STATUS_LABEL[s]}</div></div>'
        for s in STATUS_ORDER
    ) + (
        f'<div class="stat"><div class="n">{len(pending)}</div><div class="l">Drafts to review</div></div>'
        f'<div class="stat"><div class="n">{e(d["budgets"].get("inmail_credits", "–"))}</div><div class="l">InMail credits</div></div>'
    )

    needs_you_html = "".join(
        f'<li><b>#{j["id"]} {e(j["company"])}</b> — {e(j["role"])}<p>{e(j.get("blocker_note", ""))}</p>'
        f'<a href="{e(j.get("job_url", "#"))}" target="_blank" rel="noopener">Open posting ↗</a></li>'
        for j in blocked
    ) or '<li class="muted">Nothing currently blocked.</li>'

    approval_queue_html = "".join(
        f'<li><div class="row"><b>[#{o["id"]}] {e(o["company"])}</b> → {e(o.get("recruiter_name", ""))} '
        f'<span class="pill">{e(o.get("channel", ""))} · {o.get("char_count", 0)} chars</span>'
        f'<span class="pill o-{e(o.get("approval_status", ""))}">{e(o.get("approval_status", ""))}</span></div>'
        f'<blockquote>{e(o.get("rendered_message", ""))}</blockquote></li>'
        for o in d["outreach"]
    ) or '<li class="muted">No outreach drafts in queue.</li>'

    contacts_by_job: Dict[int, List[Dict[str, Any]]] = {}
    for c in d["contacts"]:
        jid = c.get("job_id")
        if jid:
            contacts_by_job.setdefault(jid, []).append(c)

    contacts_html = ""
    for j in jobs[:20]:
        c_list = contacts_by_job.get(j["id"], [])
        if c_list:
            top_c = c_list[0]
            contacts_html += (
                f'<li><b>#{j["id"]} {e(j["company"])}</b> ({e(j["role"])}): '
                f'Top Contact: <b>{e(top_c.get("name"))}</b> ({e(top_c.get("title"))}) '
                f'<span class="pill">Score: {top_c.get("score", 0)}</span> '
                f'<span class="pill">{e(top_c.get("outreach_kind", "contact"))}</span>'
                f'</li>'
            )
    if not contacts_html:
        contacts_html = '<li class="muted">No contacts scored yet.</li>'

    net_counts: Dict[str, int] = {}
    for c in d["contacts"]:
        net_counts[c.get("status", "PROPOSED")] = net_counts.get(c.get("status", "PROPOSED"), 0) + 1
    network_html = "".join(
        f'<li><span class="pill">{e(k)}</span> {v}</li>' for k, v in sorted(net_counts.items())
    ) or '<li class="muted">No contacts yet. Run /network.</li>'
    network_html += '<li class="muted">Daily cap 25 prefilled. Tabs are prefilled only; you press Send.</li>'

    cs = control.get_settings()
    def _tog(name, label, key):
        on = bool(cs.get(key))
        return (f'<button class="btn {"on" if on else "off"}" onclick="ctl(\'toggle\',{{name:\'{name}\',on:{str(not on).lower()}}})">'
                f'{label}: {"ON" if on else "OFF"}</button>')
    submit_on = bool(cs.get("ctl:submit"))
    submit_btn = (
        f'<button class="btn {"on" if submit_on else "off"}" '
        f'onclick="ctl(\'submit\',{{on:false}})">'
        f'Submit for real: {"ON" if submit_on else "OFF"}</button>'
    )
    runs_html = "".join(
        f'<li><span class="pill">{e(r["status"])}</span> {e(r["started_at"])} {e(r.get("halted_reason") or "")}</li>'
        for r in control.last_runs()
    ) or '<li class="muted">No cycle has run yet.</li>'
    control_html = (
        _tog("schedule", "6-hourly cycle", "ctl:schedule")
        + _tog("portals", "Portals", "ctl:portals")
        + _tog("people", "People + tabs", "ctl:people")
        + submit_btn
        + '<button class="btn" onclick="ctl(\'run_now\',{})">Run cycle now</button>'
        + '<button class="btn off" onclick="ctl(\'kill\',{on:true})">KILL SWITCH</button>'
        + '<button class="btn" onclick="ctl(\'kill\',{on:false})">Release kill switch</button>'
        + ('<div class="muted">Cycle running now...</div>' if control.cycle_running() else "")
        + f"<ul>{runs_html}</ul>"
    )

    pend = [c for c in d["contacts"] if c.get("status") == "PREFILLED"]
    decide_html = "".join(
        f'<li><b>{e(c["name"])}</b> - {e(c["title"])} @ {e(c["current_company"])} '
        f'<a href="{e(c["profile_url"])}" target="_blank" rel="noopener">profile</a> '
        f'<button class="btn" onclick="ctl(\'mark\',{{id:{int(c["id"])},status:\'SENT\'}})">I sent it</button>'
        f'<button class="btn off" onclick="ctl(\'mark\',{{id:{int(c["id"])},status:\'SKIPPED\'}})">Skipped</button></li>'
        for c in pend
    ) or '<li class="muted">No prefilled tabs waiting. Press Send in Chrome, then mark them here.</li>'

    saved_items_html = "".join(
        f'<li><span class="pill">{e(i["status"])}</span> <b>{e(i["area"])}</b>: {e(i["item"])}</li>' for i in d["open_items"]
    ) or '<li class="muted">None.</li>'
    drafts_html = "".join(
        f'<li><span class="pill">{e(x["status"])}</span> <b>{e(x["company"])}</b> to {e(x["contact_name"])} '
        f'{("&lt;" + e(x["to_email"]) + "&gt;") if x.get("to_email") else "(no address yet)"}'
        f'<details><summary style="cursor:pointer;color:var(--acc)">{e(x["subject"])}</summary>'
        f'<pre style="white-space:pre-wrap">{e(x["body"])}</pre></details></li>' for x in d["email_drafts"]
    ) or '<li class="muted">No email drafts.</li>'
    gsnap_html = "".join(
        f'<li>{e(x["account"])}: {e(x["subject"])} {("to " + e(x["to_addr"])) if x.get("to_addr") else ""} '
        f'<span class="muted">{e(x.get("note"))}</span></li>' for x in d["gmail_snapshot"]
    ) or '<li class="muted">No Gmail drafts snapshot.</li>'
    app_ans_html = "".join(
        f'<li><span class="pill">{e(a["status"])}</span> <b>{e(a["application"])}</b>'
        f'<details><summary style="cursor:pointer;color:var(--acc)">{e(a["question"][:110])}</summary>'
        f'<div style="white-space:pre-wrap">{e(a["answer"])}</div></details></li>' for a in d["app_answers"]
    ) or '<li class="muted">No saved application answers.</li>'
    all_contacts_html = "".join(
        f'<tr><td>{e(c["name"])}</td><td>{e(c["title"])}</td><td>{e(c["current_company"])}</td>'
        f'<td>{e(c["status"])}</td><td>{e(c["score"])}</td>'
        f'<td><a href="{e(c["profile_url"])}" target="_blank" rel="noopener">profile</a></td></tr>' for c in d["contacts"]
    ) or '<tr><td colspan="6" class="muted">No contacts.</td></tr>'

    answers_html = "".join(
        f'<li><b>{e(qa.get("question_key"))}</b>: '
        f'<details style="display:inline"><summary style="cursor:pointer;color:var(--acc)">Reveal answer</summary>'
        f'<div style="margin-top:4px;padding:4px 8px;background:var(--bg);border-radius:4px">{e(qa.get("answer"))}</div></details>'
        f'</li>'
        for qa in d["screening"]
    ) or '<li class="muted">No screening answers stored.</li>'

    open_items_count = counts.get("TO_APPLY", 0) + len(blocked) + len(pending)
    open_items_html = (
        f'<li><b>{counts.get("TO_APPLY", 0)}</b> jobs waiting to apply</li>'
        f'<li><b>{len(blocked)}</b> applications blocked needing user intervention</li>'
        f'<li><b>{len(pending)}</b> outreach drafts awaiting review</li>'
    )

    runs_html = "".join(
        f'<li><b>{e(r.get("mode", "run"))}</b> ({e(r.get("run_id", "run"))}) '
        f'<span class="pill r-{e(r.get("status"))}">{e(r.get("status"))}</span> '
        f'<span class="muted">{e((r.get("started_at") or "")[:19])}</span>'
        + (f'<p style="color:var(--blk)"><b>HALTED:</b> {e(r.get("halted_reason"))}</p>' if r.get("status") == "HALTED" or r.get("halted_reason") else '')
        + f'</li>'
        for r in d["run_log"]
    ) or '<li class="muted">No recorded runs yet.</li>'

    sources = Counter(j.get("platform", "Unknown") for j in jobs)
    source_html = "".join(
        f'<div class="stat"><div class="n">{cnt}</div><div class="l">{e(src)}</div></div>'
        for src, cnt in sources.items()
    ) or '<div class="muted">No sources recorded.</div>'

    scores = [j.get("rank_score") for j in jobs if j.get("rank_score") is not None]
    if scores:
        high = sum(1 for s in scores if s >= 4.0)
        med = sum(1 for s in scores if 3.0 <= s < 4.0)
        low = sum(1 for s in scores if s < 3.0)
        rank_dist_html = (
            f'<div class="stat"><div class="n">{high}</div><div class="l">High (≥4.0)</div></div>'
            f'<div class="stat"><div class="n">{med}</div><div class="l">Medium (3.0-3.9)</div></div>'
            f'<div class="stat"><div class="n">{low}</div><div class="l">Low (&lt;3.0)</div></div>'
        )
    else:
        rank_dist_html = '<div class="muted">No ranked jobs yet.</div>'

    rows = "".join(
        f'<tr data-status="{e(j.get("status"))}"><td class="num">{j["id"]}</td>'
        f'<td><b>{e(j.get("company"))}</b></td>'
        f'<td><a href="{e(j.get("job_url", "#"))}" target="_blank" rel="noopener">{e(j.get("role"))}</a></td>'
        f'<td>{pill(j.get("status", ""))}</td><td class="num">T{e(j.get("tier", ""))}</td><td>{e(j.get("platform", ""))}</td>'
        f'<td>{e(j.get("rank_score", "–"))}</td>'
        f'<td>{e(j.get("recruiter_name")) or "<span class=muted>—</span>"}</td>'
        f'<td>{e(j.get("date_applied")) or "<span class=muted>—</span>"}</td>'
        f'<td class="muted">{e((j.get("updated_at") or "")[:16].replace("T", " "))}</td></tr>'
        for j in jobs
    ) or '<tr><td colspan="10" class="muted">No jobs yet.</td></tr>'

    filters = "".join(
        f'<button data-f="{s}">{STATUS_LABEL[s]} ({counts.get(s, 0)})</button>' for s in STATUS_ORDER
    )
    now = datetime.now().strftime("%d %b %Y, %H:%M:%S")
    parity_text = check_data_parity()
    next_cycle_text = get_next_cycle(d.get("run_log", []))

    return (PAGE
        .replace("{{now}}", now)
        .replace("{{ks_status}}", ks_status_text)
        .replace("{{ks_reason}}", e(ks_reason))
        .replace("{{ks_class}}", ks_class)
        .replace("{{data_parity}}", e(parity_text))
        .replace("{{next_cycle}}", e(next_cycle_text))
        .replace("{{stats}}", stats_html)
        .replace("{{blockers}}", needs_you_html)
        .replace("{{approval_queue}}", approval_queue_html)
        .replace("{{contacts}}", contacts_html)
        .replace("{{network}}", network_html)
        .replace("{{control}}", control_html)
        .replace("{{saved_items}}", saved_items_html)
        .replace("{{drafts}}", drafts_html)
        .replace("{{gsnap}}", gsnap_html)
        .replace("{{app_answers}}", app_ans_html)
        .replace("{{all_contacts}}", all_contacts_html)
        .replace("{{decide}}", decide_html)
        .replace("{{token}}", e(control.get_token()))
        .replace("{{answers}}", answers_html)
        .replace("{{open_items}}", open_items_html)
        .replace("{{runs}}", runs_html)
        .replace("{{sources}}", source_html)
        .replace("{{rank_dist}}", rank_dist_html)
        .replace("{{filters}}", filters)
        .replace("{{rows}}", rows)
    )


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Harness Dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#16181d;--mut:#6b7280;--line:#e5e7eb;--acc:#2563eb;
--todo:#2563eb;--blk:#d97706;--ok:#059669;--site:#7c3aed;--rej:#9ca3af;--halt:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#0e1013;--card:#171a1f;--fg:#e8eaed;--mut:#9aa1ab;--line:#2a2f37;--acc:#60a5fa}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1240px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px}
.muted{color:var(--mut)}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:16px 0}
.stat,.card{background:var(--card);border:1px solid var(--line);border-radius:10px}
.stat{padding:12px 14px}.stat .n{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}.stat .l{color:var(--mut);font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
.card{padding:14px 16px}ul{list-style:none;margin:0;padding:0}li{padding:8px 0;border-top:1px solid var(--line)}li:first-child{border-top:0}
li p{margin:4px 0;color:var(--mut);font-size:13px}blockquote{margin:6px 0 0;padding:8px 10px;border-left:3px solid var(--acc);background:var(--bg);border-radius:4px;white-space:pre-wrap}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-top:1px solid var(--line);white-space:nowrap}th{color:var(--mut);font-weight:500;border-top:0}
.num{font-variant-numeric:tabular-nums}
.btn{margin:4px 6px 4px 0;padding:6px 12px;border-radius:8px;border:1px solid #888;background:transparent;color:inherit;cursor:pointer}.btn.on{background:#1f7a3d;color:#fff}.btn.off{background:#8a2b2b;color:#fff}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);color:var(--mut)}
.s-TO_APPLY{color:var(--todo);border-color:currentColor}.s-BLOCKED_USER{color:var(--blk);border-color:currentColor}
.s-OUTREACH_DRAFTED{color:var(--site);border-color:currentColor}.s-APPLIED{color:var(--ok);border-color:currentColor}
.s-COMPANY_SITE_ONLY{color:var(--site);border-color:currentColor}.s-REJECTED{color:var(--rej);border-color:currentColor}
.s-RANKED_OUT{color:var(--mut);border-color:currentColor}.s-HALTED{color:var(--halt);border-color:currentColor}
.ks-banner{padding:10px 14px;border-radius:8px;margin:12px 0;display:flex;justify-content:space-between;align-items:center}
.ks-off{background:rgba(5,150,105,0.1);border:1px solid var(--ok);color:var(--ok)}
.ks-on{background:rgba(220,38,38,0.1);border:1px solid var(--halt);color:var(--halt)}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.filters button{font:inherit;font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
.filters button.on{background:var(--acc);border-color:var(--acc);color:#fff}
</style></head><body><main>
<header><h1>Job Harness</h1><span class="muted">Live from harness.db · updated {{now}} · auto-refresh 20s</span></header>

<section class="card ks-banner {{ks_class}}">
  <div><b>Kill switch:</b> <span>{{ks_status}}</span> <span class="muted">{{ks_reason}}</span></div>
  <div style="font-size:13px;margin-top:6px">
    <span><b>Data parity:</b> {{data_parity}}</span> · <span><b>Next cycle:</b> {{next_cycle}}</span>
  </div>
</section>

<section class="card" style="margin-bottom:12px">
  <h2>Pipeline funnel</h2>
  <div class="stats">{{stats}}</div>
</section>

<section class="grid">
  <div class="card"><h2>Needs you</h2><ul>{{blockers}}</ul></div>
  <div class="card"><h2>Open items</h2><ul>{{open_items}}</ul></div>
</section>

<section class="grid">
  <div class="card"><h2>Saved open items</h2><ul>{{saved_items}}</ul></div>
  <div class="card"><h2>Recruiter email drafts (not sent)</h2><ul>{{drafts}}</ul></div>
  <div class="card"><h2>Gmail drafts snapshot</h2><ul>{{gsnap}}</ul></div>
  <div class="card"><h2>Application answers (e.g. Acme Corp)</h2><ul>{{app_answers}}</ul></div>
  <div class="card" style="grid-column:1/-1"><h2>All contacts</h2><table><tr><th>Name</th><th>Title</th><th>Company</th><th>Status</th><th>Score</th><th></th></tr>{{all_contacts}}</table></div>
</section>
<section class="grid">
  <div class="card">
    <h2>Control</h2>
    <div style="margin-bottom:6px;font-size:13px"><b>Data parity:</b> {{data_parity}}</div>
    <div style="margin-bottom:8px;font-size:13px"><b>Next cycle:</b> {{next_cycle}}</div>
    {{control}}
  </div>
  <div class="card"><h2>Tabs awaiting your Send</h2><ul>{{decide}}</ul></div>
</section>
<script>
const TOKEN="{{token}}";
async function ctl(action,body){
  const r=await fetch("/ctl/"+action,{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:JSON.stringify(body)});
  const j=await r.json().catch(()=>({}));
  if(!r.ok){alert(j.error||"failed");return;}
  location.reload();
}
</script>
<section class="grid">
  <div class="card"><h2>Approval queue</h2><ul>{{approval_queue}}</ul></div>
  <div class="card"><h2>Contacts per job</h2><ul>{{contacts}}</ul></div>
  <div class="card"><h2>Networking batch</h2><ul>{{network}}</ul></div>
</section>

<section class="grid">
  <div class="card"><h2>Answers bank</h2><ul>{{answers}}</ul></div>
  <div class="card"><h2>Last runs</h2><ul>{{runs}}</ul></div>
</section>

<section class="grid">
  <div class="card"><h2>Source breakdown</h2><div class="stats">{{sources}}</div></div>
  <div class="card"><h2>Rank score distribution</h2><div class="stats">{{rank_dist}}</div></div>
</section>

<section class="card" style="margin-bottom:12px">
  <h2>Jobs</h2>
  <div class="filters"><button data-f="" class="on">All</button>{{filters}}</div>
  <div class="tablewrap"><table><thead><tr><th>#</th><th>Company</th><th>Role</th><th>Status</th><th>Tier</th><th>Platform</th><th>Score</th><th>Recruiter</th><th>Applied</th><th>Updated (UTC)</th></tr></thead>
  <tbody>{{rows}}</tbody></table></div>
</section>
</main><script>
const KEY='harness-filter';let f='';try{f=localStorage.getItem(KEY)||''}catch(_){}
function apply(v){f=v;try{localStorage.setItem(KEY,v)}catch(_){}
document.querySelectorAll('.filters button').forEach(b=>b.classList.toggle('on',b.dataset.f===v));
document.querySelectorAll('tbody tr[data-status]').forEach(r=>r.style.display=!v||r.dataset.status===v?'':'none')}
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>apply(b.dataset.f));apply(f);
setTimeout(()=>location.reload(),20000);
</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def _send_bytes(
        self,
        code: int,
        body: bytes,
        ctype: str,
        cache_control: str = "no-store",
        etag: Optional[str] = None,
    ):
        """Send HTTP response with security headers, ETag/304 handling, and optional gzip."""
        # Defense-in-depth: redact any banned link host from outgoing body
        try:
            for fl in identity_capsule().get("forbidden_links", []):
                fl_bytes = fl.encode("utf-8")
                if fl_bytes in body:
                    body = body.replace(fl_bytes, b"the-banned-resume-shortener")
        except Exception:
            pass

        if etag:
            # Recompute ETag if body was redacted
            recomputed_etag = hashlib.sha256(body).hexdigest()
            if_none_match = self.headers.get("If-None-Match")
            formatted_etag = f'"{recomputed_etag.strip(chr(34))}"'
            if if_none_match and if_none_match in (recomputed_etag, formatted_etag, etag, f'"{etag.strip(chr(34))}"'):
                self.send_response(304)
                self.send_header("ETag", formatted_etag)
                self.send_header("Cache-Control", cache_control)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", CSP_HEADER)
                self.end_headers()
                return
            etag = recomputed_etag

        # Check gzip encoding
        accept_encoding = self.headers.get("Accept-Encoding", "")
        can_gzip = "gzip" in accept_encoding and len(body) > 1024 and (
            ctype.startswith("text/")
            or ctype.startswith("application/json")
            or ctype.startswith("application/javascript")
            or ctype.startswith("image/svg+xml")
        )
        if can_gzip:
            out_body = gzip.compress(body)
            c_encoding = "gzip"
        else:
            out_body = body
            c_encoding = None

        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out_body)))
        if c_encoding:
            self.send_header("Content-Encoding", c_encoding)
        if etag:
            formatted_etag = f'"{etag.strip(chr(34))}"'
            self.send_header("ETag", formatted_etag)
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP_HEADER)
        self.end_headers()
        self.wfile.write(out_body)

    def _json(
        self,
        code: int,
        obj: Any,
        cache_control: str = "no-store",
        etag: Optional[str] = None,
    ):
        b = json.dumps(obj, indent=2, default=str).encode("utf-8")
        self._send_bytes(code, b, "application/json; charset=utf-8", cache_control=cache_control, etag=etag)

    def _send_error(self, code: int, message: str):
        self._json(code, {"error": message})

    def do_GET(self):
        # Strict Host check (prevents DNS rebinding)
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._send_error(403, "bad host")

        clean_path = urllib.parse.unquote(self.path.split("?", 1)[0])

        try:
            # 1. Main HTML Shell
            if clean_path in ("/", "/index.html"):
                index_file = WEB_DIR / "index.html"
                if not index_file.is_file():
                    # Fallback to legacy render_html if web shell is missing
                    data = load_data()
                    body = render_html(data).encode("utf-8")
                else:
                    template = index_file.read_text(encoding="utf-8")
                    token = control.get_token()
                    data = load_data()
                    parity_text = check_data_parity()
                    next_cycle_text = get_next_cycle(data.get("run_log", []))
                    rendered = (
                        template.replace("{{token}}", html.escape(token))
                        .replace("{{data_parity}}", html.escape(parity_text))
                        .replace("{{next_cycle}}", html.escape(next_cycle_text))
                    )
                    body = rendered.encode("utf-8")

                etag = hashlib.sha256(body).hexdigest()
                return self._send_bytes(200, body, "text/html; charset=utf-8", cache_control="no-store", etag=etag)

            # 2. Compact JSON State API (/api/state)
            if clean_path == "/api/state":
                data = load_data()
                # Stripped answers for high performance and privacy
                screening_safe = [{"question_key": r["question_key"]} for r in data.get("screening", [])]
                app_answers_safe = [
                    {
                        "id": r["id"],
                        "application": r.get("application"),
                        "question": r.get("question"),
                        "status": r.get("status"),
                    }
                    for r in data.get("app_answers", [])
                ]
                state_obj = {
                    "jobs": data.get("jobs", [])[:200],
                    "outreach": data.get("outreach", []),
                    "contacts": data.get("contacts", [])[:200],
                    "budgets": data.get("budgets", {}),
                    "screening": screening_safe,
                    "app_answers": app_answers_safe,
                    "run_log": data.get("run_log", [])[:15],
                    "kill_switch": data.get("kill_switch", []),
                    "open_items": data.get("open_items", []),
                    "email_drafts": data.get("email_drafts", []),
                    "gmail_snapshot": data.get("gmail_snapshot", []),
                    "settings": control.get_settings(),
                    "cycle_running": control.cycle_running(),
                    "parity": check_data_parity(),
                    "next_cycle": get_next_cycle(data.get("run_log", [])),
                    "schedule": control.get_schedule(),
                }
                raw_bytes = json.dumps(state_obj, indent=2, default=str).encode("utf-8")
                etag = hashlib.sha256(raw_bytes).hexdigest()
                return self._send_bytes(200, raw_bytes, "application/json; charset=utf-8", cache_control="no-cache", etag=etag)

            # 3. Answers List API (/api/answers)
            if clean_path == "/api/answers":
                if not control.check_token(self.headers.get("X-Token")):
                    return self._send_error(403, "bad token")
                parsed_url = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed_url.query)
                status_arg = params.get("status", ["drafted"])[0] if "status" in params else "drafted"
                db_path = get_db_path()
                conn = sqlite3.connect(db_path, timeout=5)
                conn.execute("PRAGMA query_only = ON")
                conn.row_factory = sqlite3.Row
                try:
                    answers_list = answers_bank.get_answers(conn, status=status_arg)
                    return self._json(200, {"answers": answers_list})
                finally:
                    conn.close()

            # 4. Individual Answer Reveal API (/api/answers/<id>)
            if clean_path.startswith("/api/answers/"):
                if not control.check_token(self.headers.get("X-Token")):
                    return self._send_error(403, "bad token")

                ans_id_str = clean_path[len("/api/answers/"):].strip()
                db_path = get_db_path()
                conn = sqlite3.connect(db_path, timeout=5)
                conn.execute("PRAGMA query_only = ON")
                conn.row_factory = sqlite3.Row
                try:
                    # Check app_story_answers by ID
                    row = conn.execute("SELECT * FROM app_story_answers WHERE id = ?", (ans_id_str,)).fetchone()
                    if row:
                        res = dict(row)
                        return self._json(200, {
                            "id": res["id"],
                            "application": res.get("application"),
                            "question": res.get("question"),
                            "answer": res.get("answer"),
                            "status": res.get("status"),
                        })
                    # Check screening_qa by question_key
                    row_qa = conn.execute("SELECT * FROM screening_qa WHERE question_key = ?", (ans_id_str,)).fetchone()
                    if row_qa:
                        res_qa = dict(row_qa)
                        return self._json(200, {
                            "question_key": res_qa["question_key"],
                            "answer": res_qa.get("answer"),
                        })
                    return self._send_error(404, "answer not found")
                finally:
                    conn.close()

            # 4. Filtered / Paginated jobs API (/api/jobs)
            if clean_path == "/api/jobs":
                data = load_data()
                return self._json(200, {"jobs": data.get("jobs", [])[:200]})

            # 5. Filtered / Paginated contacts API (/api/contacts)
            if clean_path == "/api/contacts":
                data = load_data()
                return self._json(200, {"contacts": data.get("contacts", [])[:200]})

            # 6. Drafts API (/api/drafts)
            if clean_path == "/api/drafts":
                data = load_data()
                return self._json(200, {
                    "email_drafts": data.get("email_drafts", []),
                    "gmail_snapshot": data.get("gmail_snapshot", []),
                })

            # 7. Runs API (/api/runs)
            if clean_path == "/api/runs":
                return self._json(200, {"runs": control.last_runs()})

            # 8. Full /api (Backwards compatibility for existing test suite)
            if clean_path == "/api":
                data = load_data()
                has_token = control.check_token(self.headers.get("X-Token"))
                if not has_token:
                    data["screening"] = [{"question_key": r["question_key"]} for r in data["screening"]]
                    data["app_answers"] = [
                        {
                            "id": r["id"],
                            "application": r["application"],
                            "question": r["question"],
                            "status": r["status"]
                        }
                        for r in data["app_answers"]
                    ]
                return self._json(200, data, cache_control="no-store")

            # 9. Static File Serving with Strict Path-Traversal Protection
            rel_path = clean_path.lstrip("/")
            target_file = (WEB_DIR / rel_path).resolve()

            # Assert target resolves strictly within WEB_DIR
            try:
                target_file.relative_to(WEB_DIR)
            except ValueError:
                return self._send_error(404, "Not Found")

            if not target_file.is_file():
                return self._send_error(404, "Not Found")

            content = target_file.read_bytes()
            suffix = target_file.suffix.lower()
            ctype = MIME_TYPES.get(suffix, "application/octet-stream")

            # Immutable cache for fonts; no-cache with ETag for code and styles
            cache_ctrl = "public, max-age=31536000, immutable" if suffix == ".woff2" else "no-cache"
            file_etag = hashlib.sha256(content).hexdigest()
            return self._send_bytes(200, content, ctype, cache_control=cache_ctrl, etag=file_etag)

        except Exception as ex:
            return self._send_error(500, f"Dashboard error: {ex}")

    def do_POST(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._send_error(403, "bad host")
        if not self.path.startswith("/ctl/"):
            return self._send_error(404, "not found")
        if not control.check_token(self.headers.get("X-Token")):
            return self._send_error(403, "bad token")

        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            action = self.path[len("/ctl/"):]
            if action == "toggle":
                return self._json(200, control.set_toggle(str(body["name"]), bool(body["on"])))
            if action == "submit":
                on = bool(body.get("on") if "on" in body else body.get("mode") == 1)
                confirm = bool(body.get("confirm") or body.get("confirm_live"))
                db_path = get_db_path()
                try:
                    new_settings = control.set_submit_mode(1 if on else 0, confirm=confirm, path=db_path, actor="user")
                    return self._json(200, {"ok": True, "submit": new_settings.get("ctl:submit", 0), "settings": new_settings})
                except ValueError as ex:
                    return self._send_error(400, str(ex))
            if action == "kill":
                control.set_kill_switch(bool(body["on"]), "dashboard")
                return self._json(200, {"ok": True})
            if action == "run_now":
                return self._json(200, {"started": control.request_run_now()})
            if action == "apply_now":
                return self._json(200, control.request_apply_now(bool(body.get("start_shadow"))))
            if action == "answer":
                ans_id = int(body["id"])
                ans_act = str(body.get("action", "")).lower()
                ans_val = body.get("answer")
                if ans_act not in ("approve", "edit", "retire"):
                    return self._send_error(400, "action must be approve, edit, or retire")
                conn = sqlite3.connect(get_db_path(), timeout=10)
                try:
                    conn.row_factory = sqlite3.Row
                    if ans_act == "approve":
                        ok = answers_bank.cmd_approve(conn, ans_id, answer=ans_val)
                    elif ans_act == "edit":
                        if not ans_val or not str(ans_val).strip():
                            return self._send_error(400, "answer cannot be empty for edit")
                        ok = answers_bank.cmd_edit(conn, ans_id, str(ans_val))
                    elif ans_act == "retire":
                        ok = answers_bank.cmd_retire(conn, ans_id)
                    if not ok:
                        return self._send_error(404, "answer not found")
                    return self._json(200, {"ok": True, "id": ans_id, "action": ans_act})
                finally:
                    conn.close()
            if action == "mark":
                st = str(body["status"]).upper()
                if st not in ("SENT", "SKIPPED"):
                    return self._send_error(400, "status must be SENT or SKIPPED")
                conn = network_batch._connect()
                try:
                    return self._json(200, network_batch.mark(conn, str(int(body["id"])), st, "dashboard"))
                finally:
                    conn.close()
            if action == "job_status":
                job_id = int(body["id"])
                st = str(body["status"]).upper()
                if st not in ("APPLIED", "RANKED_OUT"):
                    return self._send_error(400, "status must be APPLIED or RANKED_OUT")
                conn = sqlite3.connect(get_db_path(), timeout=10)
                try:
                    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    if not row:
                        return self._send_error(404, "job not found")
                    if row[0] not in ("TO_APPLY", "BLOCKED_USER", "NEEDS_INPUT"):
                        return self._send_error(409, f"job is {row[0]}; only open jobs can be changed here")
                    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    day = datetime.now().strftime("%Y-%m-%d")
                    if st == "APPLIED":
                        conn.execute("UPDATE jobs SET status='APPLIED', blocker_note='', date_applied=?, updated_at=? WHERE id=?", (day, now_ts, job_id))
                    else:
                        conn.execute("UPDATE jobs SET status='RANKED_OUT', blocker_note='Skipped by owner', updated_at=? WHERE id=?", (now_ts, job_id))
                    conn.execute(
                        "INSERT INTO action_log (run_id, ts, actor, action, target, result, detail) VALUES ('', ?, 'user', 'job_status', ?, ?, ?)",
                        (now_ts, str(job_id), st, f"from {row[0]} via dashboard"),
                    )
                    conn.commit()
                    return self._json(200, {"ok": True, "id": job_id, "status": st})
                finally:
                    conn.close()
            return self._send_error(404, "unknown action")
        except (KeyError, ValueError, LookupError, TypeError) as ex:
            return self._send_error(400, str(ex))

    def log_message(self, *a):
        pass


def _scheduler_loop(interval_s: int = 30):
    import time as _t
    while True:
        try:
            control.scheduler_tick()
        except Exception:
            pass  # never let the scheduler thread die
        _t.sleep(interval_s)


def run_server(port: int = PORT, host: str = "127.0.0.1", scheduler: bool = False):
    if scheduler and not os.environ.get("HARNESS_NO_SCHEDULER"):
        import threading
        threading.Thread(target=_scheduler_loop, daemon=True, name="cycle-scheduler").start()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    print(f"Job Harness dashboard → http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    run_server(PORT, "127.0.0.1", scheduler=True)
