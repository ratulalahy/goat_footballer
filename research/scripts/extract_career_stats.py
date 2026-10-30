#!/usr/bin/env python3
"""Extract footballers' career statistics from English Wikipedia raw wikitext.

Regenerates /home/user/football-greatest/research/career_seasons.json.

Usage:
    python3 extract_career_stats.py              # fetch (or reuse today's raw files) + extract
    python3 extract_career_stats.py --offline    # never fetch; parse files already in research/raw
    python3 extract_career_stats.py --only pele muller   # restrict to some player ids (debugging)

Data access: https://en.wikipedia.org/wiki/<Title>?action=raw (the MediaWiki/REST APIs return
HTTP 429 from our network). Every fetched page is saved to research/raw/<Title>.wikitext with a
sidecar <Title>.meta.json (URL, fetch time, HTTP Last-Modified). A raw file whose mtime is from
today (UTC) is reused instead of re-fetched. The SHA-1 of the exact wikitext parsed is recorded.

Rules (see CONVENTIONS below): numbers are only ever copied from the tables, never estimated.
"—"/"–" in a competition column = did not play (0). A blank cell, or a dash in a Total column,
= no figure in the table (null). Totals are validated against the sum of the season rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests
import wikitextparser as wtp

RESEARCH = Path(__file__).resolve().parent.parent
RAW = RESEARCH / "raw"
OUT = RESEARCH / "career_seasons.json"
UA = "FootballGreatestResearch/1.0 (data-journalism research)"
MIN_INTERVAL = 2.0          # seconds between requests
BACKOFF = (10, 30, 60)      # seconds to wait after successive HTTP 429s

# (id, display name, requested Wikipedia title, article actually used if different)
PLAYERS = [
    ("ronaldo", "Cristiano Ronaldo", "Cristiano_Ronaldo", None),
    ("messi", "Lionel Messi", "Lionel_Messi", None),
    ("pele", "Pelé", "Pelé", None),
    ("muller", "Gerd Müller", "Gerd_Müller", None),
    ("puskas", "Ferenc Puskás", "Ferenc_Puskás", None),
    ("lewandowski", "Robert Lewandowski", "Robert_Lewandowski", None),
    ("ibrahimovic", "Zlatan Ibrahimović", "Zlatan_Ibrahimović", None),
    # "Luis_Suárez" is a disambiguation page; the prolific striker is the Uruguayan (born 1987).
    ("suarez", "Luis Suárez", "Luis_Suárez", "Luis_Suárez_(Uruguayan_footballer)"),
    ("benzema", "Karim Benzema", "Karim_Benzema", None),
    ("kane", "Harry Kane", "Harry_Kane", None),
    ("mbappe", "Kylian Mbappé", "Kylian_Mbappé", None),
    ("haaland", "Erling Haaland", "Erling_Haaland", None),
    ("neymar", "Neymar", "Neymar", None),
    ("henry", "Thierry Henry", "Thierry_Henry", None),
    ("ronaldo_nazario", "Ronaldo Nazário", "Ronaldo_(Brazilian_footballer)", None),
    ("romario", "Romário", "Romário", None),
    ("eusebio", "Eusébio", "Eusébio", None),
    # added on coordinator request (appended; ids fixed by the coordinator)
    ("maradona", "Diego Maradona", "Diego_Maradona", None),
    ("distefano", "Alfredo Di Stéfano", "Alfredo_Di_Stéfano", None),
    ("cruyff", "Johan Cruyff", "Johan_Cruyff", None),
    ("zidane", "Zinedine Zidane", "Zinedine_Zidane", None),
]

# Rows from leagues whose official status is disputed are FLAGGED (row field 'disputed_league' plus a
# row note), never dropped. Rules are applied to the displayed league / its link target / season year.
DISPUTED_LEAGUE_RULES = [
    {"code": "El Dorado",
     "match": lambda league, link, year, club: bool(re.search(r"campeonato profesional|categor[ií]a primera a|colombia",
                                                              f"{league} {link}", re.I)) and year is not None and 1949 <= year <= 1954,
     "note": ("Flag (disputed official status): Colombian professional league in the El Dorado era (1949–1954), "
              "when the league had broken away from the FIFA-affiliated federation; the official status of these "
              "matches is disputed. Kept, not dropped.")},
    {"code": "NASL",
     "match": lambda league, link, year, club: (league in ("NASL", "North American Soccer League")
                                                or link.startswith("North American Soccer League (1968"))
                                               and (year is None or year <= 1984),
     "note": ("Flag (disputed official status): North American Soccer League (1968–84), played under "
              "non-standard rules (e.g. shoot-outs for drawn matches); NASL matches are treated separately in some "
              "'official goals' tallies. Kept, not dropped.")},
    {"code": "indoor",
     "match": lambda league, link, year, club: bool(re.search(r"\bindoor\b", f"{club} {league} {link}", re.I))
                                               or league in ("MISL", "Major Indoor Soccer League"),
     "note": ("Flag (disputed official status): indoor football (Major Indoor Soccer League), not 11-a-side "
              "association football. Kept, not dropped.")},
]

# Gerd Müller's main-article international table is split into competition blocks
# ("UEFA Euro 1968 qual.", "Friendlies – 1969", ...) and qualifiers straddle calendar years, so
# per-year values cannot be read from it. Its {{further}} link leads to the goals list whose
# "Statistics" section has a Year/Apps/Goals table; that table is used for intl_years.
INTL_OVERRIDES = {
    "muller": {
        "article": "List_of_international_goals_scored_by_Gerd_Müller",
        "section": r"Statistics",
        "team": "West Germany",
        "note": ("intl_years come from the Statistics table of 'List of international goals scored by "
                 "Gerd Müller' (linked via {{further}} from the International section), because the main "
                 "article's table is organised by competition blocks (e.g. 'UEFA Euro 1968 qual.', "
                 "'Friendlies – 1969'), not calendar years, and qualifier blocks span two years. That list "
                 "labels the team 'Germany national team' (link to Germany national football team); the main "
                 "article labels it 'West Germany', which is used here."),
    },
}

CONVENTIONS = {
    "dash_in_competition_column": "'—'/'–' in a competition (non-Total) column = did not play -> 0",
    "blank_cell": "blank cell = no figure in the table -> null (e.g. Pelé's silver 'competition not held' cells)",
    "dash_in_total_column": ("'—' in a Total column (rows where every cell is '—', e.g. a year without caps) = did "
                             "not play -> 0, flagged in row notes; the tables' stated totals confirm this reading"),
    "disputed_league": ("rows from leagues of disputed official status (El Dorado-era Colombia 1949–54, NASL "
                        "1968–84, indoor/MISL) carry disputed_league=<code> and a row note; they are kept and "
                        "counted in all sums exactly as the source tables count them"),
    "row_order": "rows are in source-table order (chronological by club stint, loans where the table puts them)",
    "season": "season label copied exactly as displayed (link text), including hyphen/en-dash variants",
    "club": "displayed club name; a trailing ' (loan)' is removed and recorded as loan=true",
    "reserve_team": "reserve_team=true when the displayed club name ends in ' B', ' C', ' II' or ' 2' or contains ' II ' (label-based)",
    "league": "the table's Division cell; null where the table has no League column",
    "apps_goals": "the table's 'Total' Apps/Goals columns (all competitions the table covers)",
    "breakdown": "other competition columns exactly as labelled in that table's header",
    "excluded_rows": "per-club 'Total' rows and 'Career total' rows are excluded from season rows and used for validation",
    "intl": "senior national team rows only; youth (U15-U23/Olympic) and non-national (regional) rows excluded",
    "stated_totals": "copied from 'Career total'/'Total' rows; 'basis' says which row(s); a sum of stated rows is labelled as such",
    "summed_totals": "sum of the extracted rows, null cells counted as 0 (null cells are listed in validation_issues/notes)",
}

# ---------------------------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------------------------
_last_request = [0.0]
FETCH_LOG: list[str] = []


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fname(title: str) -> str:
    return title.replace(" ", "_").replace("/", "%2F")


def raw_path(title: str) -> Path:
    return RAW / f"{_fname(title)}.wikitext"


def meta_path(title: str) -> Path:
    return RAW / f"{_fname(title)}.meta.json"


def _is_today(p: Path) -> bool:
    mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).date()
    return mtime == dt.datetime.now(dt.timezone.utc).date()


def _http_get(url: str) -> requests.Response:
    r = None
    for attempt in range(len(BACKOFF) + 1):
        wait = MIN_INTERVAL - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.time()
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        if r.status_code == 429 and attempt < len(BACKOFF):
            FETCH_LOG.append(f"429 on {url}; backing off {BACKOFF[attempt]}s")
            time.sleep(BACKOFF[attempt])
            continue
        return r
    return r


def fetch_wikitext(title: str, offline: bool = False, _depth: int = 0) -> tuple[str, dict]:
    """Return (wikitext, meta). Reuses today's local copy. Follows #REDIRECT pages."""
    title = title.replace(" ", "_")
    p, mp = raw_path(title), meta_path(title)
    if p.exists() and (offline or _is_today(p)):
        text = p.read_text(encoding="utf-8")
        meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        meta.setdefault("title", title)
        meta.setdefault("url", f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title, safe='_()')}?action=raw")
        meta.setdefault("fetched_at", dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
                        .replace(microsecond=0).isoformat().replace("+00:00", "Z"))
        meta["reused_local_file"] = True
    else:
        if offline:
            raise FileNotFoundError(f"{p} missing and --offline given")
        url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title, safe='_()')}?action=raw"
        r = _http_get(url)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        r.encoding = "utf-8"
        text = r.text
        meta = {"title": title, "url": url, "fetched_at": utc_now(), "http_status": r.status_code,
                "last_modified": r.headers.get("last-modified"), "bytes": len(r.content)}
        RAW.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        FETCH_LOG.append(f"fetched {title} ({len(r.content)} bytes)")
    meta["sha1"] = hashlib.sha1(text.encode("utf-8")).hexdigest()
    m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", text, re.I)
    if m and _depth < 3:
        target = m.group(1).strip().replace(" ", "_")
        text2, meta2 = fetch_wikitext(target, offline, _depth + 1)
        meta2["redirected_from"] = title
        return text2, meta2
    return text, meta


# ---------------------------------------------------------------------------------------------
# Cell cleaning
# ---------------------------------------------------------------------------------------------
DROP_TEMPLATES = {
    "efn", "efn-ua", "efn-lr", "efn-lg", "efn-la", "refn", "sfn", "sfnp", "sfnm", "harvnb", "r", "rp",
    "cn", "citation needed", "ref label", "note label", "noteref", "notetag", "update after",
    "dagger", "double-dagger", "*", "†", "updated", "flagicon", "flag icon", "fbaicon", "efn-n",
    "webarchive", "soccerbase", "soccerway", "nft", "nft player", "clarify", "dubious",
    "failed verification", "vague", "sic", "anchor", "ref", "tooltip-note", "bdfutbol",
}
FIRST_PARAM_TEMPLATES = {"nowrap", "nobr", "nobold", "small", "big", "center", "lang", "nbsp", "abbr",
                         "tooltip", "hover title", "resize", "smaller", "larger", "noitalic",
                         "background color", "transl", "tl", "fb", "fbw", "fbu"}
SORT_TEMPLATES = {"sort", "sortname", "sort date", "dts"}
DASH_TEMPLATES = {"dash", "mdash", "ndash", "–", "—", "em dash", "en dash"}
EMPTY_TEMPLATES = {"hs", "hidden sort", "sortkey"}
UNKNOWN_TEMPLATES: set[str] = set()


def _tname(t: "wtp.Template") -> str:
    return t.name.strip().lower().replace("_", " ")


def _template_text(t: "wtp.Template") -> str:
    name = _tname(t)
    pos = [a.value for a in t.arguments if a.positional]
    if name in DROP_TEMPLATES or name.startswith("efn") or name.startswith("cite "):
        return ""
    if name in SORT_TEMPLATES:
        if name == "sort":
            return pos[1] if len(pos) > 1 else (pos[0] if pos else "")
        return " ".join(pos)
    if name in DASH_TEMPLATES:
        return "—"
    if name in EMPTY_TEMPLATES:
        return ""
    if name in FIRST_PARAM_TEMPLATES:
        return pos[0] if pos else ""
    UNKNOWN_TEMPLATES.add(name)
    return pos[0] if pos else ""


def clean(cell: str | None) -> str:
    """Wikitext cell -> displayed plain text (refs/footnotes removed, link text kept)."""
    s = cell or ""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s, flags=re.I)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S | re.I)
    for _ in range(12):                       # replace innermost templates until none are left
        tpls = wtp.parse(s).templates
        if not tpls:
            break
        inner = [t for t in tpls if not t.templates]
        for t in sorted(inner, key=lambda t: t.span[0], reverse=True):
            a, b = t.span
            s = s[:a] + _template_text(t) + s[b:]
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)    # [[A|B]] -> B, [[A]] -> A
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)        # [url text] -> text
    s = re.sub(r"'{2,}", "", s)                                  # bold / italic
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)                      # remaining html tags
    s = (s.replace("&nbsp;", " ").replace(" ", " ").replace("&ndash;", "–")
          .replace("&mdash;", "—"))
    return re.sub(r"\s+", " ", s).strip()


DASHES = {"—", "–", "-", "−", "‒", "―"}


def to_int(s: str):
    """-> (value, kind); kind in ok | dash | blank | unparsed."""
    v = (s or "").strip()
    if v == "":
        return None, "blank"
    if v in DASHES:
        return 0, "dash"
    v2 = v.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\d+", v2):
        return int(v2), "ok"
    return None, "unparsed"


def parse_stat(raw: str, is_total: bool):
    """Parse a stat cell. -> (value, kind, markers). Handles Pelé-style '38*' and '14+15*'."""
    s = (raw or "").strip()
    markers = []
    if s.endswith("*"):
        s = s[:-1].strip()
        markers.append("*")
    if re.fullmatch(r"\d+(?:\s*\+\s*\d+)+", s):
        markers.append(f"sum of parts '{s}'")
        return sum(int(x) for x in re.findall(r"\d+", s)), "ok", markers
    v, kind = to_int(s)
    if kind == "dash" and is_total:
        return 0, "dash_total", markers      # did not play (same dash convention), flagged by callers
    return v, kind, markers


def link_target(cell) -> str | None:
    if cell is None:
        return None
    wl = cell.wikilinks
    return wl[0].title.strip() if wl else None


# ---------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------
HEADING_RE = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.M)


def get_section(text: str, name_regex: str, start: int = 0, end: int | None = None):
    """First section (after `start`) whose heading text matches name_regex. -> (start, end) or None."""
    end = len(text) if end is None else end
    for m in HEADING_RE.finditer(text, start, end):
        if re.fullmatch(name_regex, m.group(2).strip(), re.I):
            lvl = len(m.group(1))
            for m2 in HEADING_RE.finditer(text, m.end(), end):
                if len(m2.group(1)) <= lvl:
                    return m.start(), m2.start()
            return m.start(), end
    return None


def as_of_markers(section_text: str) -> list[str]:
    out = []
    for t in wtp.parse(section_text).templates:
        if _tname(t) in ("updated", "as of", "update", "last updated"):
            pos = [a.value for a in t.arguments if a.positional]
            if pos:
                out.append(clean(pos[0]))
    return out


# ---------------------------------------------------------------------------------------------
# Generic table analysis
# ---------------------------------------------------------------------------------------------
SEASON_RE = re.compile(r"^\d{4}(?:\s*[–\-/]\s*\d{2,4})?(?:\s*,\s*\d{4}(?:\s*[–\-/]\s*\d{2,4})?)*$")


def is_total_label(v: str) -> bool:
    return re.fullmatch(r"(?:sub-?)?totals?", (v or "").strip(), re.I) is not None


def is_career_total(v: str) -> bool:
    return re.fullmatch(r"(?:career|overall|grand)\s+totals?", (v or "").strip(), re.I) is not None


def analyse_table(tb):
    """-> dict(cells, nh, ncols, roles, stats{comp: {'apps': j, 'goals': j}}, comp_links)."""
    cells = tb.cells(span=True)
    # Leading header rows. wikitextparser marks cells that follow '||' on a '!' line as non-header,
    # although MediaWiki renders them as <th>; so a row also counts as a header row when its first
    # own (non-spanned) cell is a header cell and none of its cells is numeric.
    nh = 0
    for ri, r in enumerate(cells):
        if not r:
            break
        own = [c for j, c in enumerate(r) if c is not None and
               (ri == 0 or j >= len(cells[ri - 1]) or cells[ri - 1][j] is not c)]
        numeric = any(re.fullmatch(r"[\d,]+\*?", clean(c.value)) for c in r if c is not None)
        if all(c is None or c.is_header for c in r) or (own and own[0].is_header and not numeric):
            nh += 1
        else:
            break
    ncols = max(len(r) for r in cells) if cells else 0
    roles, stats, comp_links = [], {}, {}
    for j in range(ncols):
        labels, links = [], []
        for r in cells[:nh]:
            c = r[j] if j < len(r) else None
            if c is None:
                continue
            lab = clean(c.value)
            if not labels or labels[-1] != lab:
                labels.append(lab)
                links.append(link_target(c))
        low = [x.lower() for x in labels]
        if not labels or all(x == "" for x in labels):
            roles.append(("spacer",))
        elif low[-1] in ("apps", "goals"):
            comp = labels[-2] if len(labels) >= 2 else ""
            stats.setdefault(comp, {})[low[-1]] = j
            if len(labels) >= 2:
                comp_links[comp] = links[-2]
            roles.append(("stat", comp, low[-1]))
        elif low[-1] == "division":
            roles.append(("division",))
        elif low[-1] in ("club", "team", "national team"):
            roles.append(("club",))
        elif low[-1] == "season":
            roles.append(("season",))
        elif low[-1] == "year":
            roles.append(("year",))
        else:
            roles.append(("other", labels[-1]))
    return {"cells": cells, "nh": nh, "ncols": ncols, "roles": roles, "stats": stats, "comp_links": comp_links}


FOOTNOTE_SKIP = re.compile(r"^((one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+appearances?|"
                           r"appearances?|appearance\(s\)|includes|all appearances)\b", re.I)


def cell_footnotes(cell) -> list[str]:
    """Substantive {{efn}}/{{refn}} texts in a cell (competition-coverage notes are skipped)."""
    out = []
    if cell is None:
        return out
    for t in wtp.parse(cell.value).templates:
        n = _tname(t)
        if n.startswith("efn") or n == "refn":
            pos = [a.value for a in t.arguments if a.positional]
            txt = clean(pos[0]) if pos else ""
            if txt and not FOOTNOTE_SKIP.match(txt):
                out.append(txt)
    return out


def col_label(info, j) -> str:
    r = info["roles"][j]
    if r[0] == "stat":
        return f"{r[1] or 'Apps/Goals'} {r[2]}".strip()
    return {"division": "Division", "season": "Season", "club": "Club", "year": "Year"}.get(r[0], r[-1] if len(r) > 1 else r[0])


def own_cells(cells, ri):
    """(j, cell) pairs that start in row ri (not carried down by a rowspan)."""
    r = cells[ri]
    prev = cells[ri - 1] if ri > 0 else []
    return [(j, c) for j, c in enumerate(r) if c is not None and not (j < len(prev) and prev[j] is c)]


def role_col(info, name):
    idx = [j for j, r in enumerate(info["roles"]) if r[0] == name]
    return idx[0] if idx else None


def row_values(info, r):
    vals = [clean(c.value) if c is not None else "" for c in r]
    return vals + [""] * (info["ncols"] - len(vals))


def add(a, b):
    return (a or 0) + (b or 0)


# ---------------------------------------------------------------------------------------------
# Club tables
# ---------------------------------------------------------------------------------------------
LOAN_RE = re.compile(r"\s*\(\s*loan\s*\)\s*$", re.I)
RESERVE_RE = re.compile(r"(?:\s(?:B|C|II|2)$)|(?:\sII\s)")


def parse_club_tables(tables, issues: list, notes: list):
    seasons, subtotals, career_rows, comps_seen = [], [], [], []
    for ti, tb in enumerate(tables):
        info = analyse_table(tb)
        cells, nh, stats = info["cells"], info["nh"], info["stats"]
        club_col, season_col, div_col = role_col(info, "club"), role_col(info, "season"), role_col(info, "division")
        cap = clean(tb.caption) if tb.caption else f"table {ti + 1}"
        if club_col is None or season_col is None:
            issues.append(f"Club table '{cap}': no Club/Season column found; skipped")
            continue
        if "Total" not in stats:
            issues.append(f"Club table '{cap}': no 'Total' Apps/Goals columns; apps/goals left null")
        for c in stats:
            if c not in comps_seen:
                comps_seen.append(c)
        # header sanity: which column really holds the season labels?
        data = [row_values(info, r) for r in cells[nh:]]
        body = [v for v in data if not any(is_total_label(x) or is_career_total(x) for x in v[:3])]
        n_season = sum(bool(SEASON_RE.match(v[season_col])) for v in body)
        n_club = sum(bool(SEASON_RE.match(v[club_col])) for v in body)
        if n_club > n_season:
            notes.append(f"Club table '{cap}': header labels 'Club' and 'Season' are swapped relative to the "
                         f"data (season labels sit under the 'Club' heading); columns assigned by content.")
            club_col, season_col = season_col, club_col
        league_from_header = None
        if div_col is None and "League" in stats:
            lk = info["comp_links"].get("League")
            if lk:
                league_from_header = re.sub(r"\s*\([^)]*\)\s*$", "", lk)
                notes.append(f"Club table '{cap}' has no Division column; league name taken from the 'League' "
                             f"header link ({lk}).")
        if "League" not in stats:
            notes.append(f"Club table '{cap}' has no 'League' column (competitions: "
                         f"{', '.join(c for c in stats if c != 'Total')}); league/league_apps/league_goals are null "
                         f"and the per-competition values are kept in 'breakdown'.")
        block_start = len(seasons)      # season rows after the previous subtotal row (any club)
        last_sub_by_club: dict = {}      # club -> index into seasons after that club's last subtotal row
        for ri, r in enumerate(cells[nh:], start=nh):
            vals = row_values(info, r)
            if all(v == "" for v in vals):
                continue                 # empty row (e.g. a doubled '|-')
            if len(r) != info["ncols"]:
                issues.append(f"Club table '{cap}' row {ri}: {len(r)} cells, expected {info['ncols']}")
            label_cells = vals[:max(club_col, season_col) + 2]
            parsed = {}
            markers = {}
            kinds = {}
            for comp, d in stats.items():
                for k in ("apps", "goals"):
                    if k in d:
                        v, kind, mk = parse_stat(vals[d[k]], is_total=(comp == "Total"))
                        parsed[(comp, k)] = v
                        kinds[(comp, k)] = (kind, vals[d[k]])
                        if mk:
                            markers[(comp, k)] = mk
            fnotes = [f"footnote on {col_label(info, j)}: {fn}" for j, c in own_cells(cells, ri)
                      for fn in cell_footnotes(c)]
            if any(is_career_total(x) for x in label_cells):
                career_rows.append({"table": ti, "caption": cap, "vals": parsed, "kinds": kinds})
                notes.extend(f"Career total row, {fn}" for fn in fnotes)
                continue
            if is_total_label(vals[season_col]) or is_total_label(vals[club_col]):
                club_label = vals[club_col]
                if is_total_label(club_label):
                    block = seasons[block_start:]
                    block = [s for s in block if s["_table"] == ti]
                    club_name = block[-1]["club"] if block else None
                else:
                    # all rows of this club since its previous subtotal row (handles loans in between
                    # and repeat stints, e.g. Manchester United 2003–09 and 2021–22)
                    club_name = LOAN_RE.sub("", club_label)
                    start = last_sub_by_club.get(club_name, 0)
                    block = [s for s in seasons[start:] if s["club"] == club_name and s["_table"] == ti]
                subtotals.append({"club": club_name, "table": ti, "rows": block, "vals": parsed,
                                  "kinds": kinds, "markers": markers})
                notes.extend(f"{club_name} 'Total' row, {fn}" for fn in fnotes)
                star = [f"{c} {k}" for (c, k), mk in markers.items() if "*" in mk]
                if star:
                    notes.append(f"{club_name} 'Total' row: values marked '*' in source on: " + ", ".join(star))
                block_start = len(seasons)
                if club_name:
                    last_sub_by_club[club_name] = len(seasons)
                continue
            stat_cells = [vals[d[k]] for d in stats.values() for k in d]
            if not any(re.search(r"\d", x) or x in DASHES for x in stat_cells):
                notes.append(f"Club table '{cap}' row {ri} skipped (no statistics): {' | '.join(vals)[:120]}")
                continue
            club_raw, season = vals[club_col], vals[season_col]
            loan = bool(LOAN_RE.search(club_raw))
            club = LOAN_RE.sub("", club_raw)
            if not SEASON_RE.match(season):
                issues.append(f"Season label '{season}' ({club}) does not look like a season/year")
            row = {"club": club, "season": season,
                   "league": (vals[div_col] or None) if div_col is not None else league_from_header,
                   "league_apps": parsed.get(("League", "apps")), "league_goals": parsed.get(("League", "goals")),
                   "apps": parsed.get(("Total", "apps")), "goals": parsed.get(("Total", "goals"))}
            if loan:
                row["loan"] = True
            if RESERVE_RE.search(club):
                row["reserve_team"] = True
            lg_link = (link_target(r[div_col]) if div_col is not None and div_col < len(r) else
                       info["comp_links"].get("League")) or ""
            ym = re.match(r"\d{4}", season)
            for rule in DISPUTED_LEAGUE_RULES:
                if rule["match"](row["league"] or "", lg_link, int(ym.group()) if ym else None, club):
                    row["disputed_league"] = rule["code"]
                    fnotes.append(rule["note"])
                    break
            bd = {}
            for comp in stats:
                if comp in ("League", "Total"):
                    continue
                bd[comp] = {k: parsed.get((comp, k)) for k in ("apps", "goals") if k in stats[comp]}
            if bd:
                row["breakdown"] = bd
            rnotes = list(fnotes)
            star = [f"{'Total' if c == 'Total' else c} {k}" for (c, k), mk in markers.items() if "*" in mk]
            if star:
                rnotes.append("marked '*' in source (see notes) on: " + ", ".join(star))
            for (c, k), mk in markers.items():
                for m in mk:
                    if m.startswith("sum of parts"):
                        rnotes.append(f"{c} {k} cell reads '{kinds[(c, k)][1]}'; value is the {m}")
            for (c, k), (kind, raw) in kinds.items():
                if kind == "dash_total":
                    rnotes.append(f"{c} {k} cell is '{raw}' (did not play, per the table's dash convention) -> 0")
                    if any((v or 0) > 0 for (c2, k2), v in parsed.items() if k2 == k and c2 != c):
                        issues.append(f"{club} {season}: {c} {k} is '{raw}' but other columns have {k}")
                elif kind == "unparsed":
                    rnotes.append(f"{c} {k} cell '{raw}' is not a number -> null")
                    issues.append(f"{club} {season}: {c} {k} cell '{raw}' not a number -> null")
                elif kind == "blank" and c in ("Total", "League"):
                    rnotes.append(f"{c} {k} cell blank -> null")
            if rnotes:
                row["notes"] = rnotes
            row["_table"], row["_parsed"] = ti, parsed
            seasons.append(row)
    return seasons, subtotals, career_rows, comps_seen


def _sum_rows(rows, comp, k):
    vals = [r["_parsed"].get((comp, k)) for r in rows]
    if all(v is None for v in vals):
        return None, 0
    return sum(v or 0 for v in vals), sum(v is None for v in vals)


def validate_club(seasons, subtotals, career_rows, issues):
    # 1) per-row: competitions add up to the Total column
    for r in seasons:
        p = r["_parsed"]
        for k in ("apps", "goals"):
            tot = p.get(("Total", k))
            parts = [v for (c, kk), v in p.items() if kk == k and c != "Total"
                     and not re.search(r"sub-?total", c, re.I)]
            if tot is None or not parts:
                continue
            s = sum(v or 0 for v in parts)
            if s != tot:
                issues.append(f"Row {r['club']} {r['season']}: competition {k} add up to {s} but Total {k} is {tot}")
    # 2) per-club subtotal rows
    for st in subtotals:
        rows = st["rows"]
        span = f"{rows[0]['season']}–{rows[-1]['season']}" if rows else "no rows"
        if not rows:
            issues.append(f"Club subtotal row for {st['club']} matched no season rows")
        st["summed"] = {}
        for (comp, k), stated in st["vals"].items():
            summed, nulls = _sum_rows(rows, comp, k)
            st["summed"][(comp, k)] = summed
            if stated is None:
                continue
            if summed != stated:
                issues.append(f"Club subtotal {st['club']} ({span}) {comp} {k}: stated {stated}, "
                              f"sum of season rows {summed}" + (f" ({nulls} null cells)" if nulls else ""))
    # 3) career total row(s)
    for cr in career_rows:
        rows = [s for s in seasons if s["_table"] == cr["table"]] if len(career_rows) > 1 else seasons
        for (comp, k), stated in cr["vals"].items():
            summed, nulls = _sum_rows(rows, comp, k)
            if stated is not None and summed != stated:
                issues.append(f"Career total {comp} {k}: stated {stated}, sum of season rows {summed}"
                              + (f" ({nulls} null cells)" if nulls else ""))


# ---------------------------------------------------------------------------------------------
# International tables
# ---------------------------------------------------------------------------------------------
def classify_team(display: str, target: str | None) -> str:
    s = f"{display} {target or ''}"
    if re.search(r"under-?\s?\d+|\bU-?\d{2}\b|olympic|amateur|youth|\bB team\b", s, re.I):
        return "youth"
    if target and not re.search(r"national (?:football |soccer |association football )?team", target, re.I):
        return "non-national"
    return "senior"


def parse_intl_table(tb, issues: list, notes: list, team_override: str | None = None):
    info = analyse_table(tb)
    cells, nh, stats = info["cells"], info["nh"], info["stats"]
    team_col, year_col = role_col(info, "club"), role_col(info, "year")
    use = "Total" if "Total" in stats else (next(iter(stats)) if len(stats) == 1 else None)
    if year_col is None or use is None:
        issues.append("International table: could not identify Year / Apps / Goals columns")
        return None
    rows, team_totals, overall = [], [], None
    for ri, r in enumerate(cells[nh:], start=nh):
        vals = row_values(info, r)
        team = team_override if team_col is None else vals[team_col]
        target = None if team_col is None else link_target(r[team_col] if team_col < len(r) else None)
        year_raw = vals[year_col]
        parsed, kinds = {}, {}
        for comp, d in stats.items():
            for k in ("apps", "goals"):
                if k in d:
                    v, kind, mk = parse_stat(vals[d[k]], is_total=(comp == use))
                    parsed[(comp, k)], kinds[(comp, k)] = v, (kind, vals[d[k]])
        if is_career_total(team) or is_career_total(year_raw):
            overall = {"label": team if is_career_total(team) else year_raw, "vals": parsed}
            continue
        if is_total_label(year_raw) or (team_col is not None and is_total_label(team)):
            if team_col is not None and is_total_label(team):
                overall = {"label": "Total", "vals": parsed}
            else:
                team_totals.append({"team": team, "target": target, "vals": parsed})
            continue
        if len(set(vals)) == 1:   # e.g. a 'Source:' row spanning the table
            continue
        m = re.fullmatch(r"(\d{4})", year_raw)
        row = {"team": team, "year": int(m.group(1)) if m else None,
               "apps": parsed.get((use, "apps")), "goals": parsed.get((use, "goals"))}
        if not m:
            row["label"] = year_raw
        bd = {c: {k: parsed.get((c, k)) for k in ("apps", "goals")} for c in stats if c != use}
        if bd:
            row["breakdown"] = bd
        for (c, k), (kind, raw) in kinds.items():
            if kind == "dash_total":
                row.setdefault("notes", []).append(f"{c} {k} cell is '{raw}' (no appearances, per the table's "
                                                   f"dash convention) -> 0")
                if any((v or 0) > 0 for (c2, k2), v in parsed.items() if k2 == k and c2 != c):
                    issues.append(f"Intl {team} {year_raw}: {c} {k} is '{raw}' but other columns have {k}")
            elif kind == "unparsed" or (kind == "blank" and c == use):
                row.setdefault("notes", []).append(f"{c} {k} cell '{raw}' -> null")
                issues.append(f"Intl {team} {year_raw}: {c} {k} cell '{raw}' -> null")
        row["_class"] = classify_team(team, target)
        row["_target"] = target
        row["_parsed"] = parsed
        rows.append(row)
    return {"rows": rows, "team_totals": team_totals, "overall": overall, "use": use, "stats": stats}


def validate_intl(parsed, issues, notes):
    rows, use = parsed["rows"], parsed["use"]
    teams = []
    for r in rows:
        if r["team"] not in teams:
            teams.append(r["team"])
    team_summaries = []
    for tt in parsed["team_totals"]:
        trs = [r for r in rows if r["team"] == tt["team"]]
        cls = trs[0]["_class"] if trs else classify_team(tt["team"], tt["target"])
        ent = {"team": tt["team"], "senior": cls == "senior",
               "stated": {"apps": tt["vals"].get((use, "apps")), "goals": tt["vals"].get((use, "goals"))},
               "summed": {"apps": sum(r["apps"] or 0 for r in trs), "goals": sum(r["goals"] or 0 for r in trs)}}
        team_summaries.append(ent)
        for k in ("apps", "goals"):
            if ent["stated"][k] is not None and ent["stated"][k] != ent["summed"][k]:
                issues.append(f"Intl subtotal {tt['team']}{'' if cls == 'senior' else ' (' + cls + ', excluded)'} "
                              f"{k}: stated {ent['stated'][k]}, sum of year rows {ent['summed'][k]}")
    if parsed["overall"]:
        for k in ("apps", "goals"):
            st = parsed["overall"]["vals"].get((use, k))
            sm = sum(r[k] or 0 for r in rows)
            if st is not None and st != sm:
                issues.append(f"Intl table '{parsed['overall']['label']}' {k}: stated {st}, "
                              f"sum of all rows in table {sm}")
    return teams, team_summaries


# ---------------------------------------------------------------------------------------------
# Infobox
# ---------------------------------------------------------------------------------------------
def infobox_dates(text: str, notes: list):
    p = wtp.parse(text[:80000])
    # the birth date may sit in an outer infobox (e.g. Infobox person / officeholder) that embeds
    # Infobox football biography as a module, so take the first infobox that has birth_date
    boxes = [t for t in p.templates if _tname(t).startswith("infobox") and t.get_arg("birth_date") is not None]
    if not boxes:
        return None
    box = boxes[0]
    arg = box.get_arg("birth_date")
    val = arg.value
    birth = None
    for t in wtp.parse(val).templates:
        if re.fullmatch(r"birth date(?: and age)?2?|bda|dob", _tname(t)):
            pos = [a.value.strip() for a in t.arguments if a.positional]
            if len(pos) >= 3 and all(x.isdigit() for x in pos[:3]):
                birth = f"{int(pos[0]):04d}-{int(pos[1]):02d}-{int(pos[2]):02d}"
            break
    # explanatory footnotes attached to the birth date (efn text, or non-citation refs)
    for t in wtp.parse(val).templates:
        if _tname(t).startswith("efn"):
            pos = [a.value for a in t.arguments if a.positional]
            if pos:
                notes.append("Infobox birth_date footnote: " + clean(pos[0]))
    for m in re.finditer(r"<ref[^>/]*>(.*?)</ref>", val, re.S):
        body = m.group(1).strip()
        if not re.match(r"\s*(\{\{|\[)", body) and len(clean(body)) > 40:   # skip plain citations
            notes.append("Infobox birth_date reference note: " + clean(body)[:300])
    darg = box.get_arg("death_date")
    if darg is not None and birth:
        for t in wtp.parse(darg.value).templates:
            if _tname(t).startswith("death date and age"):
                pos = [a.value.strip() for a in t.arguments if a.positional]
                if len(pos) >= 6 and all(x.isdigit() for x in pos[3:6]):
                    b2 = f"{int(pos[3]):04d}-{int(pos[4]):02d}-{int(pos[5]):02d}"
                    if b2 != birth:
                        notes.append(f"Infobox inconsistency: birth_date gives {birth} but the death_date "
                                     f"template's birth date is {b2}; birth_date field used.")
    return birth


# ---------------------------------------------------------------------------------------------
# Per-player extraction
# ---------------------------------------------------------------------------------------------
def source_entry(meta: dict, used_for: str) -> dict:
    ent = {"title": meta.get("title"), "url": meta.get("url"), "fetched_at": meta.get("fetched_at"),
           "http_last_modified": meta.get("last_modified"), "wikitext_sha1": meta.get("sha1"),
           "used_for": used_for}
    if meta.get("note"):                       # e.g. file fetched earlier today by another agent
        ent["fetch_note"] = meta["note"]
    return ent


def club_section_tables(text: str, sec):
    s0, s1 = sec
    cs = get_section(text, r"club(?: career)?(?: statistics)?", s0 + 1, s1)
    if cs is None:
        return None, []
    body = text[cs[0]:cs[1]]
    tabs = [tb for tb in wtp.parse(body).tables
            if re.search(r"season", tb.string[:3000], re.I) and re.search(r"apps", tb.string[:3000], re.I)]
    return cs, tabs


def intl_section_table(text: str, rng):
    s0, s1 = rng
    body = text[s0:s1]
    for tb in wtp.parse(body).tables:
        head = tb.string[:2500]
        if re.search(r"\byear\b", head, re.I) and re.search(r"apps", head, re.I) and re.search(r"goals", head, re.I):
            return tb
    return None


def extract_player(pid, name, requested, resolved, offline):
    notes, issues, sources = [], [], []
    title = resolved or requested
    if resolved and resolved != requested:
        req_text, req_meta = fetch_wikitext(requested, offline)
        disamb = bool(re.search(r"\{\{\s*(?:hndis|disambiguation|disambig|dab|human name disambiguation)",
                                req_text, re.I)) or "may refer to" in req_text
        listed = resolved.replace("_", " ") in req_text
        notes.append(f"Requested title '{requested}' is {'a disambiguation page' if disamb else 'NOT a disambiguation page (check!)'}"
                     f"; resolved to '{resolved}'{' (listed on that page)' if listed else ''}, the striker born 1987.")
        sources.append(source_entry(req_meta, "disambiguation check only"))
    text, meta = fetch_wikitext(title, offline)
    sources.append(source_entry(meta, "infobox birth date, club table" + ("" if pid in INTL_OVERRIDES else ", international table")))

    birth = infobox_dates(text, notes)
    sec = get_section(text, r"career statistics")
    if sec is None:
        raise RuntimeError(f"{title}: no 'Career statistics' section")

    # ---- club ----
    cs, ctabs = club_section_tables(text, sec)
    club_as_of = as_of_markers(text[cs[0]:cs[1]]) if cs else []
    legend = re.findall(r"^\*\s*''\s*\*\s*(Indicates[^\n]*?)''\s*$", text[cs[0]:cs[1]], re.M) if cs else []
    for lg in legend:
        notes.append("Source table legend: '*' " + clean(lg))
    seasons, subtotals, career_rows, comps = parse_club_tables(ctabs, issues, notes)
    validate_club(seasons, subtotals, career_rows, issues)
    if len(ctabs) > 1:
        notes.append(f"Club statistics are split over {len(ctabs)} tables: "
                     + "; ".join(clean(t.caption) if t.caption else "?" for t in ctabs))

    def pick(vals, comp, k):
        return vals.get((comp, k))

    if len(career_rows) == 1:
        cr = career_rows[0]["vals"]
        club_stated = {"apps": pick(cr, "Total", "apps"), "goals": pick(cr, "Total", "goals"),
                       "league_apps": pick(cr, "League", "apps"), "league_goals": pick(cr, "League", "goals"),
                       "basis": "table's 'Career total' row"}
    elif not career_rows and subtotals and all(any(s is r for st in subtotals for r in st["rows"]) for s in seasons):
        parts = [f"{st['club']} {pick(st['vals'], 'Total', 'apps')}/{pick(st['vals'], 'Total', 'goals')}" for st in subtotals]
        tot = lambda comp, k: (None if any(pick(st["vals"], comp, k) is None for st in subtotals)
                               else sum(pick(st["vals"], comp, k) for st in subtotals))
        club_stated = {"apps": tot("Total", "apps"), "goals": tot("Total", "goals"),
                       "league_apps": tot("League", "apps"), "league_goals": tot("League", "goals"),
                       "basis": "no 'Career total' row in the source; sum of the stated per-club 'Total' rows ("
                                + ", ".join(parts) + ")"}
    else:
        club_stated = {"apps": None, "goals": None, "league_apps": None, "league_goals": None,
                       "basis": f"{len(career_rows)} career-total rows found; not determinable"}
        issues.append("Club career total: could not determine a single stated total")
    club_summed = {}
    for key, (comp, k) in {"apps": ("Total", "apps"), "goals": ("Total", "goals"),
                           "league_apps": ("League", "apps"), "league_goals": ("League", "goals")}.items():
        v, nulls = _sum_rows(seasons, comp, k)
        absent = sum((comp, k) not in r["_parsed"] for r in seasons)
        if absent and v is not None:
            # the column does not exist in one of the tables: a career sum would be partial
            notes.append(f"club_total_summed.{key} is null: {absent} season row(s) come from a table without a "
                         f"'{comp}' column (sum over the other rows = {v})")
            v = None
        elif nulls and v is not None:
            notes.append(f"club_total_summed.{key}: {nulls} season row(s) have a null {comp} {k} (counted as 0)")
        club_summed[key] = v
    if not career_rows:
        for key in ("apps", "goals", "league_apps", "league_goals"):
            if club_stated.get(key) is not None and club_summed.get(key) != club_stated[key]:
                issues.append(f"Club total {key}: stated (sum of club Total rows) {club_stated[key]}, "
                              f"sum of season rows {club_summed[key]}")

    club_subtotals_out = []
    for st in subtotals:
        rows = st["rows"]
        club_subtotals_out.append({
            "club": st["club"],
            "seasons": f"{rows[0]['season']} to {rows[-1]['season']}" if rows else None,
            "stated": {"apps": pick(st["vals"], "Total", "apps"), "goals": pick(st["vals"], "Total", "goals"),
                       "league_apps": pick(st["vals"], "League", "apps"), "league_goals": pick(st["vals"], "League", "goals")},
            "summed": {"apps": st["summed"].get(("Total", "apps")), "goals": st["summed"].get(("Total", "goals")),
                       "league_apps": st["summed"].get(("League", "apps")), "league_goals": st["summed"].get(("League", "goals"))},
        })

    # ---- international ----
    isec = get_section(text, r"international(?: career)?(?: statistics)?", sec[0] + 1, sec[1])
    intl_as_of = as_of_markers(text[isec[0]:isec[1]]) if isec else []
    intl_title = title
    team_override = None
    main_intl_tb = intl_section_table(text, isec) if isec else None
    if pid in INTL_OVERRIDES:
        ov = INTL_OVERRIDES[pid]
        ltext, lmeta = fetch_wikitext(ov["article"], offline)
        sources.append(source_entry(lmeta, "international table (by calendar year)"))
        lsec = get_section(ltext, ov["section"])
        itb = intl_section_table(ltext, lsec) if lsec else None
        intl_title = ov["article"]
        team_override = ov["team"]
        notes.append(ov["note"])
        intl_as_of = intl_as_of + (as_of_markers(ltext[lsec[0]:lsec[1]]) if lsec else [])
        # cross-check against the main-article table (competition blocks)
        if main_intl_tb is not None:
            sub_issues = []
            mp = parse_intl_table(main_intl_tb, sub_issues, [])
            if mp:
                validate_intl(mp, sub_issues, [])
                tot = mp["overall"]["vals"] if mp["overall"] else {}
                ma, mg = tot.get((mp["use"], "apps")), tot.get((mp["use"], "goals"))
                sa, sg = sum(r["apps"] or 0 for r in mp["rows"]), sum(r["goals"] or 0 for r in mp["rows"])
                notes.append(f"Cross-check: main-article international table ({len(mp['rows'])} competition-block rows) "
                             f"states {ma} apps / {mg} goals; its rows sum to {sa}/{sg}.")
                issues.extend("Main-article intl table: " + x for x in sub_issues)
    else:
        itb = main_intl_tb
    intl_rows, intl_team_totals, intl_stated, intl_summed = [], [], None, None
    if itb is None:
        issues.append("No international appearances table found")
    else:
        ip = parse_intl_table(itb, issues, notes, team_override)
        if ip:
            teams, team_summaries = validate_intl(ip, issues, notes)
            intl_team_totals = team_summaries
            senior = [t for t in teams if any(r["team"] == t and r["_class"] == "senior" for r in ip["rows"])]
            excluded = [t for t in teams if t not in senior]
            if excluded:
                desc = ", ".join(f"{t} ({next(r['_class'] for r in ip['rows'] if r['team'] == t)})" for t in excluded)
                notes.append(f"International table also lists {desc}; excluded from intl_years "
                             f"(senior national team rows only).")
            intl_rows = [r for r in ip["rows"] if r["team"] in senior]
            use = ip["use"]
            tt = {t["team"]: t for t in ip["team_totals"]}
            ov_vals = ip["overall"]["vals"] if ip["overall"] else None
            if len(senior) == 1 and senior[0] in tt:
                v = tt[senior[0]]["vals"]
                intl_stated = {"apps": v.get((use, "apps")), "goals": v.get((use, "goals")),
                               "basis": f"'Total' row for {senior[0]}"}
                if ov_vals and excluded:
                    intl_stated["basis"] += (f"; the table's '{ip['overall']['label']}' row "
                                             f"({ov_vals.get((use, 'apps'))}/{ov_vals.get((use, 'goals'))}) also "
                                             f"counts {', '.join(excluded)}")
            elif ov_vals and not excluded:
                intl_stated = {"apps": ov_vals.get((use, "apps")), "goals": ov_vals.get((use, "goals")),
                               "basis": f"table's '{ip['overall']['label']}' row"}
            elif all(t in tt for t in senior) and senior:
                intl_stated = {"apps": sum(tt[t]["vals"].get((use, "apps")) or 0 for t in senior),
                               "goals": sum(tt[t]["vals"].get((use, "goals")) or 0 for t in senior),
                               "basis": "no single stated total for the senior teams; sum of the stated 'Total' rows for "
                                        + " + ".join(f"{t} ({tt[t]['vals'].get((use, 'apps'))}/{tt[t]['vals'].get((use, 'goals'))})" for t in senior)}
                if ov_vals:
                    intl_stated["basis"] += (f"; the table's '{ip['overall']['label']}' row "
                                             f"({ov_vals.get((use, 'apps'))}/{ov_vals.get((use, 'goals'))}) also "
                                             f"counts {', '.join(excluded)}")
            else:
                intl_stated = {"apps": None, "goals": None, "basis": "no stated total found"}
                issues.append("International: no stated total found for the senior team(s)")
            intl_summed = {"apps": sum(r["apps"] or 0 for r in intl_rows), "goals": sum(r["goals"] or 0 for r in intl_rows)}
            if intl_stated and len(senior) > 1 or (intl_stated and len(senior) == 1 and senior[0] not in tt):
                for k in ("apps", "goals"):
                    if intl_stated.get(k) is not None and intl_stated[k] != intl_summed[k]:
                        issues.append(f"Intl total {k}: stated {intl_stated[k]}, sum of senior year rows {intl_summed[k]}")
            if any(r["year"] is None for r in intl_rows):
                issues.append("Some international rows have no single calendar year (see 'label')")

    def strip(rows):
        out = []
        for r in rows:
            out.append({k: v for k, v in r.items() if not k.startswith("_")})
        return out

    as_of_parts = []
    if club_as_of:
        as_of_parts.append("club: " + "; ".join(club_as_of))
    if intl_as_of:
        as_of_parts.append("international: " + "; ".join(intl_as_of))
    if not as_of_parts:
        notes.append("No 'as of'/{{updated}} marker in the statistics tables (career finished).")

    fetched = next((s["fetched_at"] for s in sources if s["title"] == title), meta.get("fetched_at"))
    return {
        "id": pid, "name": name, "wiki_title": title, "requested_title": requested,
        "stats_article": title, "intl_stats_article": intl_title,
        "fetched_at": fetched,
        "birth_date": birth,
        "club_seasons": strip(seasons),
        "club_total_stated": club_stated,
        "club_total_summed": club_summed,
        "club_subtotals": club_subtotals_out,
        "intl_years": strip(intl_rows),
        "intl_total_stated": intl_stated,
        "intl_total_summed": intl_summed,
        "intl_team_totals": intl_team_totals,
        "stats_as_of": " | ".join(as_of_parts) if as_of_parts else None,
        "stats_as_of_detail": {"club": club_as_of or None, "intl": intl_as_of or None},
        "validation_issues": issues,
        "notes": notes,
        "sources": sources,
    }


# Notes that need a human reading of the article text (kept here so a re-run reproduces them).
EDITORIAL_NOTES = {
    "pele": [
        "Article text: the FIFA-reported 1,281 goals in 1,363 games include friendlies, tours, armed-forces and "
        "São Paulo state-team games; the Santos table covers official club competitions only, while the New York "
        "Cosmos table is described as 'all matches and goals' (its 'Other' column carries {{citation needed}}).",
        "Cosmos table footnote: RSSSF counts as league goals those in NASL, the NASL post-season, the Campeonato "
        "Paulista and the original Campeonato Brasileiro (1971–1974); no single 'League' column exists for Santos.",
    ],
    "puskas": [
        "Season '1943–44, 1944' is one table row covering two league seasons; '1944-45' (hyphen) is copied as "
        "written and links to the 1945 Nemzeti Bajnokság I season.",
    ],
    "eusebio": [
        "Buffalo Stallions (1979–80) row is indoor football (MISL); it is included in the table's career total.",
        "New Jersey Americans 1979: every cell of the row, including Total, is '—' (no appearances); recorded "
        "as 0 under the dash convention, which the club's 'Total' row (9/2 = the 1978 row alone) confirms.",
    ],
    "romario": [
        "America-RJ 2009 row lists Carioca Série B (state second tier) as the division; its league cells are '—'.",
    ],
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="never fetch; use files in research/raw")
    ap.add_argument("--only", nargs="*", help="player ids to process")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    players = []
    for pid, name, req, res in PLAYERS:
        if a.only and pid not in a.only:
            continue
        rec = extract_player(pid, name, req, res, a.offline)
        rec["notes"].extend(EDITORIAL_NOTES.get(pid, []))
        players.append(rec)
        print(f"{pid:16s} birth={rec['birth_date']} club stated={rec['club_total_stated']['apps']}/"
              f"{rec['club_total_stated']['goals']} summed={rec['club_total_summed']['apps']}/"
              f"{rec['club_total_summed']['goals']} intl stated="
              f"{(rec['intl_total_stated'] or {}).get('apps')}/{(rec['intl_total_stated'] or {}).get('goals')} "
              f"summed={(rec['intl_total_summed'] or {}).get('apps')}/{(rec['intl_total_summed'] or {}).get('goals')} "
              f"issues={len(rec['validation_issues'])}", file=sys.stderr)
    doc = {
        "generated_at": utc_now(),
        "source": "English Wikipedia, raw wikitext via ?action=raw",
        "script": "research/scripts/extract_career_stats.py",
        "conventions": CONVENTIONS,
        "players": players,
    }
    if UNKNOWN_TEMPLATES:
        print("Unknown templates seen in cells (first positional param kept):", sorted(UNKNOWN_TEMPLATES), file=sys.stderr)
    for line in FETCH_LOG:
        print(line, file=sys.stderr)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
