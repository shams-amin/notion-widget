#!/usr/bin/env python3
"""
Fetches current point-transfer bonuses from Frequent Miler and writes
transfer-bonuses.json. Designed to run in GitHub Actions on a schedule.
No third-party deps (urllib + re only) so it runs on a bare python image.
Source: https://frequentmiler.com/current-point-transfer-bonuses/

v2 (2026-10-08): Frequent Miler split their table into
  From | To | Details | Start | End   (it used to be From | Details | Start | End).
Columns are now mapped by HEADER NAME, with a positional fallback for both
layouts, and the run FAILS LOUDLY (non-zero exit -> no commit, GitHub emails
you) if the parsed rows look wrong (no end dates, no percentages, or nothing
still live). That way a future layout change can never publish bad data again.
"""
import urllib.request, re, json, html as htmllib, datetime, sys

URL = "https://frequentmiler.com/current-point-transfer-bonuses/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")

def clean(s):
    # kill hidden sort keys like <p style="display:none">46266</p> / <span ...>
    s = re.sub(r"<(p|span|div)[^>]*display:\s*none[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")

def find_date(text):
    """Return the LAST mm/dd/yy in the text, zero-padded (FM may prefix a numeric sort key)."""
    hits = DATE_RE.findall(text or "")
    if not hits:
        return ""
    m, d, y = hits[-1]
    y = y[-2:]
    return f"{int(m):02d}/{int(d):02d}/{y}"

def to_date(s):
    try:
        m, d, y = s.split("/")
        return datetime.date(2000 + int(y), int(m), int(d))
    except Exception:
        return None

def header_map(texts):
    """Map column roles from a header row; return None if it doesn't look like a header."""
    low = [t.lower().strip() for t in texts]
    has_from = any(x in ("transfer from", "from") or x.startswith("transfer from") for x in low)
    has_end  = any(x in ("end", "end date", "ends", "expires", "expiration") for x in low)
    if not (has_from and has_end):
        return None
    cm = {}
    for i, x in enumerate(low):
        if "from" in x and "from" not in cm:          cm["from"] = i
        elif x.startswith("transfer to") or x == "to": cm["to"] = i
        elif "detail" in x or "bonus" in x:           cm["details"] = i
        elif "start" in x or "begin" in x:            cm["start"] = i
        elif x.startswith("end") or "expir" in x:     cm["end"] = i
    return cm if {"from", "end"} <= set(cm) else None

def positional_map(n):
    if n >= 5: return {"from": 0, "to": 1, "details": 2, "start": 3, "end": 4}
    if n == 4: return {"from": 0, "details": 1, "start": 2, "end": 3}
    return None

def parse_table_after(marker, html):
    idx = html.lower().find(marker.lower())
    if idx == -1:
        return []
    m = re.search(r"<table.*?</table>", html[idx:], re.S)
    if not m:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S)
    colmap, out = None, []
    for r in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        if len(cells) < 4:
            continue
        texts = [clean(c) for c in cells]
        hm = header_map(texts)
        if hm:                       # header row -> learn the layout, skip it
            colmap = hm
            continue
        cm = colmap or positional_map(len(cells))
        if not cm:
            continue
        def cell(role):
            i = cm.get(role)
            return cells[i] if i is not None and i < len(cells) else ""
        def text(role):
            return clean(cell(role))
        src     = text("from")
        details = text("details") if "details" in cm else ""
        to      = text("to") if "to" in cm else ""
        link = re.search(r"href=['\"]([^'\"]+)['\"]", cell("details") or cell("to") or "")
        pct  = re.search(r"(?i)(up to \d+%|\d+%)", details) or re.search(r"(?i)(up to \d+%|\d+%)", to)
        start = find_date(text("start")) if "start" in cm else ""
        end   = find_date(text("end"))
        if not end:                  # header-ish or malformed row
            continue
        if not to:
            mt = re.search(r"(?i)\bto\s+(.+?)$", details)
            to = mt.group(1).strip() if mt else ""
        if not details:
            details = f"{pct.group(1) if pct else 'Transfer bonus'} transfer bonus from {src} to {to}".strip()
        out.append({
            "from": src,
            "to": to,
            "details": details,
            "pct": pct.group(1) if pct else "",
            "url": link.group(1) if link else "",
            "start": start,
            "end": end,
        })
    return out

def main():
    # Offline test hook: FM_HTML_FILE=/path/to/saved.html python fetch_transfer_bonuses.py
    import os
    local = os.environ.get("FM_HTML_FILE")
    html = open(local, encoding="utf-8", errors="replace").read() if local else fetch(URL)
    current = parse_table_after("Current and Upcoming Transfer Bonuses", html)
    if not current:
        print("ERROR: parsed 0 rows - page structure may have changed", file=sys.stderr)
        sys.exit(1)
    # --- sanity checks: refuse to publish data that looks mis-parsed ---
    today = datetime.datetime.now(datetime.timezone.utc).date()
    with_pct = sum(1 for b in current if b["pct"])
    live = [b for b in current if (to_date(b["end"]) or datetime.date.min) >= today]
    problems = []
    if with_pct < max(1, len(current) // 2):
        problems.append(f"only {with_pct}/{len(current)} rows have a % - column mapping is probably wrong")
    if not live:
        problems.append("every row's end date is in the past - probably reading the wrong column")
    if problems:
        for p in problems:
            print("ERROR: " + p, file=sys.stderr)
        print(json.dumps(current[:3], indent=2), file=sys.stderr)
        sys.exit(1)
    data = {
        "source": URL,
        "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "count": len(current),
        "live": len(live),
        "bonuses": current,
    }
    with open("transfer-bonuses.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(current)} transfer bonuses ({len(live)} live as of {today}).")

if __name__ == "__main__":
    main()
