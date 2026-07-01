#!/usr/bin/env python3
"""
Fetches current point-transfer bonuses from Frequent Miler and writes
transfer-bonuses.json. Designed to run in GitHub Actions on a schedule.
No third-party deps (urllib + re only) so it runs on a bare python image.
Source: https://frequentmiler.com/current-point-transfer-bonuses/
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
    s = re.sub(r"<p style='display: ?none;'>.*?</p>", "", s, flags=re.S)  # kill hidden sort key
    s = re.sub(r"<[^>]+>", "", s)                                         # strip tags
    return htmllib.unescape(s).strip()

def parse_table_after(marker, html):
    idx = html.lower().find(marker.lower())
    if idx == -1: return []
    m = re.search(r"<table.*?</table>", html[idx:], re.S)
    if not m: return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S)
    out = []
    for r in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        if len(cells) < 4: continue
        src = clean(cells[0])
        if src.lower() == "transfer from": continue  # header
        link = re.search(r"href=['\"]([^'\"]+)['\"]", cells[1])
        details = clean(cells[1])
        start = re.search(r"(\d{2}/\d{2}/\d{2})", clean(cells[2]))
        end   = re.search(r"(\d{2}/\d{2}/\d{2})", clean(cells[3]))
        # pull the headline % if present
        pct = re.search(r"(\d+%|Up to \d+%)", details)
        out.append({
            "from": src,
            "details": details,
            "pct": pct.group(1) if pct else "",
            "url": link.group(1) if link else "",
            "start": start.group(1) if start else "",
            "end": end.group(1) if end else "",
        })
    return out

def main():
    html = fetch(URL)
    current = parse_table_after("Current and Upcoming Transfer Bonuses", html)
    if not current:
        print("ERROR: parsed 0 rows — page structure may have changed", file=sys.stderr)
        sys.exit(1)
    data = {
        "source": URL,
        "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "count": len(current),
        "bonuses": current,
    }
    with open("transfer-bonuses.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(current)} transfer bonuses.")

if __name__ == "__main__":
    main()
