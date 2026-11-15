#!/usr/bin/env python3
"""Sync merged PR to Confluence pages' 'Historique des changements' section.

Lit l'event GitHub depuis GITHUB_EVENT_PATH, extrait les pages cibles via :
1. Labels PR (ex: 'confluence:meanrev' -> page_id via .github/confluence-pages.json)
2. Section 'Confluence-Pages: <id1>,<id2>' dans le PR body (override direct)

Pour chaque page cible, ajoute une entree dans la section 'Historique des
changements' (ou la cree si absente). Idempotent : si la meme PR est deja
listee (via son numero dans le href), skip.

Variables d'environnement requises :
- GITHUB_EVENT_PATH : path vers l'event JSON (fourni par GitHub Actions)
- CONFLUENCE_EMAIL : email Atlassian du compte owner du token
- CONFLUENCE_API_TOKEN : API token Atlassian
- CONFLUENCE_BASE_URL : ex https://coudercxavier.atlassian.net/wiki
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        print(f"[ERR] env {name} manquante ou vide", file=sys.stderr)
        sys.exit(1)
    return v


def _load_event() -> dict:
    path = _env("GITHUB_EVENT_PATH")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_mapping() -> dict:
    root = Path(__file__).resolve().parent.parent
    with open(root / "confluence-pages.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _targets_from_pr(pr: dict, mapping: dict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    for label in pr.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else str(label)
        pid = mapping["labels"].get(name)
        if pid and pid not in seen:
            ids.append(pid)
            seen.add(pid)

    body = pr.get("body") or ""
    m = re.search(r"^Confluence-Pages:\s*([0-9,\s]+)", body, re.MULTILINE | re.IGNORECASE)
    if m:
        for raw in m.group(1).split(","):
            pid = raw.strip()
            if pid.isdigit() and pid not in seen:
                ids.append(pid)
                seen.add(pid)

    return ids


def _auth_header() -> str:
    email = _env("CONFLUENCE_EMAIL")
    token = _env("CONFLUENCE_API_TOKEN")
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _confluence_get(base_url: str, path: str) -> dict:
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, headers={
        "Authorization": _auth_header(),
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _confluence_put(base_url: str, path: str, payload: dict) -> dict:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": _auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_page(base_url: str, page_id: str) -> dict:
    return _confluence_get(
        base_url,
        f"/api/v2/pages/{page_id}?body-format=storage",
    )


def _build_entry_html(pr: dict, today: str) -> str:
    number = pr.get("number")
    title = (pr.get("title") or "").strip()
    url = pr.get("html_url") or ""
    user = (pr.get("user") or {}).get("login") or "?"
    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    safe_user = user.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<li><strong>{today}</strong> — '
        f'<a href="{url}">PR #{number}</a> {safe_title} '
        f'<em>(@{safe_user})</em></li>'
    )


def _already_logged(body_html: str, pr_number: int) -> bool:
    needle = f"pull/{pr_number}"
    needle_alt = f"PR #{pr_number}"
    return needle in body_html or needle_alt in body_html


def _ensure_history_section(body_html: str) -> tuple[str, str]:
    """Return (updated_body, marker_used). Appends section if missing."""
    marker = "Historique des changements"
    if marker in body_html:
        return body_html, marker
    appended = (
        body_html.rstrip()
        + f'<h2>{marker}</h2><ul></ul>'
    )
    return appended, marker


def _inject_entry(body_html: str, entry_html: str) -> str:
    """Insert entry_html as the first <li> under the first <ul> following the
    'Historique des changements' heading. Returns updated html.
    """
    marker = "Historique des changements"
    idx_heading = body_html.find(marker)
    if idx_heading < 0:
        return body_html
    search_from = idx_heading
    idx_ul = body_html.find("<ul", search_from)
    if idx_ul < 0:
        tail_insert = body_html.find("</h2>", idx_heading)
        if tail_insert < 0:
            return body_html + f"<ul>{entry_html}</ul>"
        insert_at = tail_insert + len("</h2>")
        return body_html[:insert_at] + f"<ul>{entry_html}</ul>" + body_html[insert_at:]
    idx_gt = body_html.find(">", idx_ul)
    if idx_gt < 0:
        return body_html
    insert_at = idx_gt + 1
    return body_html[:insert_at] + entry_html + body_html[insert_at:]


def _update_page(base_url: str, page_id: str, pr: dict, today: str) -> str:
    page = _fetch_page(base_url, page_id)
    title = page.get("title") or f"page {page_id}"
    version_num = (page.get("version") or {}).get("number") or 1
    body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""

    pr_number = pr.get("number")
    if pr_number and _already_logged(body, int(pr_number)):
        return f"[SKIP] page {page_id} \"{title}\" : PR #{pr_number} deja dans l'historique"

    body_prepared, _ = _ensure_history_section(body)
    entry = _build_entry_html(pr, today)
    new_body = _inject_entry(body_prepared, entry)

    payload = {
        "id": page_id,
        "status": "current",
        "title": title,
        "body": {
            "representation": "storage",
            "value": new_body,
        },
        "version": {"number": version_num + 1},
    }
    _confluence_put(base_url, f"/api/v2/pages/{page_id}", payload)
    return f"[OK]   page {page_id} \"{title}\" : PR #{pr_number} ajoutee (v{version_num + 1})"


def main() -> int:
    event = _load_event()
    pr = event.get("pull_request") or {}
    if not pr:
        print("[WARN] event sans pull_request, nothing to do")
        return 0
    if not pr.get("merged"):
        print(f"[INFO] PR #{pr.get('number')} pas mergee, skip")
        return 0

    mapping = _load_mapping()
    targets = _targets_from_pr(pr, mapping)
    if not targets:
        print(f"[INFO] PR #{pr.get('number')} sans label confluence: ni section Confluence-Pages, skip")
        return 0

    base_url = _env("CONFLUENCE_BASE_URL")
    today = date.today().isoformat()
    print(f"[INFO] Sync PR #{pr.get('number')} vers {len(targets)} page(s) Confluence")

    any_error = False
    for page_id in targets:
        try:
            msg = _update_page(base_url, page_id, pr, today)
            print(msg)
        except urllib.error.HTTPError as e:
            any_error = True
            print(f"[ERR]  page {page_id} : HTTP {e.code} {e.reason}", file=sys.stderr)
            try:
                detail = e.read().decode("utf-8")[:500]
                print(f"       detail: {detail}", file=sys.stderr)
            except Exception:
                pass
        except Exception as e:
            any_error = True
            print(f"[ERR]  page {page_id} : {type(e).__name__} {e}", file=sys.stderr)

    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
