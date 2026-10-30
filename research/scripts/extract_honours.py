#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_honours.py -- build research/honours.json from raw English-Wikipedia wikitext.

Inputs
------
research/raw/<Title>.wikitext  (+ <Title>.meta.json sidecars with fetch time / Last-Modified)
fetched with   curl -A "FootballGreatestResearch/1.0 (data-journalism research)" \
                    "https://en.wikipedia.org/wiki/<Title>?action=raw"
(see fetch_wikitext.py; pages written by the other research agent are reused as-is).

Method
------
1. PLAYER PAGES (primary source). The level-2 "Honours" section is cut out. Footnote/citation
   templates ({{efn}}, {{efn-ua}}, {{refn}}, {{sfn}}, <ref>...) are removed FIRST, so years that
   appear only inside footnotes (e.g. Messi's 2005 Supercopa note) are never counted.
2. The section is walked line by line with a small state machine: '''Bold''' lines, ===Sub===
   headings and ";Term" lines open a block (club, national team, "Individual"). Blocks for
   Manager/Coach, Orders, Decorations and Records are skipped until the next === heading
   (Puskás, Di Stéfano, Cruyff, Zidane, Henry list managerial trophies in the same section).
3. Every bullet is split at its first top-level colon into LABEL (competition/award) and VALUE.
   Years/seasons are read from the VALUE only (link labels and plain text). Qualifiers inside the
   value ("; runner-up:", "third place:", "nominated:", "silver award:") change the outcome for
   the years that follow; qualifiers in the label ("FIFA World Cup runner-up") set the initial
   outcome. Only outcome == winner is counted as a title/award win.
4. Bullets are classified with the explicit, ordered rule tables TEAM_RULES / individual rules
   below. Unmatched team bullets are kept under team_honours.unclassified for review.
5. LIST ARTICLES give independent cross-checks: Ballon d'Or podiums (Ballon_d'Or winners table,
   used as the podium source), European Golden Shoe winners, UCL all-time scorers (goals/apps,
   qualifiers excluded by that table) and season top scorers, UCL most-titles table, FIFA World
   Player / FIFA Ballon d'Or / The Best wins-by-player tables, FIFA World Cup awards.
6. Players below the UCL list's 25-goal cut-off use documented secondary sources (UCL_FALLBACK).

Nothing is estimated: when a value is not available from a source the field is null and the
reason is recorded in notes.

Run:  python3 extract_honours.py            (writes research/honours.json)
      python3 extract_honours.py --review   (also prints every classified bullet for audit)
"""
import json
import os
import re
import sys
import unicodedata
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

import wikitextparser as wtp

BASE = "/home/user/football-greatest/research"
RAW = os.path.join(BASE, "raw")
OUT = os.path.join(BASE, "honours.json")
REVIEW = "--review" in sys.argv

# ----------------------------------------------------------------------------------------------
# Players: (id, display name, Wikipedia title actually parsed)
# ----------------------------------------------------------------------------------------------
PLAYERS = [
    ("cristiano-ronaldo", "Cristiano Ronaldo", "Cristiano_Ronaldo"),
    ("lionel-messi", "Lionel Messi", "Lionel_Messi"),
    ("pele", "Pelé", "Pelé"),
    ("gerd-muller", "Gerd Müller", "Gerd_Müller"),
    ("ferenc-puskas", "Ferenc Puskás", "Ferenc_Puskás"),
    ("alfredo-di-stefano", "Alfredo Di Stéfano", "Alfredo_Di_Stéfano"),
    ("eusebio", "Eusébio", "Eusébio"),
    ("diego-maradona", "Diego Maradona", "Diego_Maradona"),
    ("johan-cruyff", "Johan Cruyff", "Johan_Cruyff"),
    ("zinedine-zidane", "Zinedine Zidane", "Zinedine_Zidane"),
    ("robert-lewandowski", "Robert Lewandowski", "Robert_Lewandowski"),
    ("zlatan-ibrahimovic", "Zlatan Ibrahimović", "Zlatan_Ibrahimović"),
    # "Luis_Suárez" is a disambiguation page; the Uruguayan striker (b. 1987) is the player meant.
    ("luis-suarez", "Luis Suárez", "Luis_Suárez_(Uruguayan_footballer)"),
    ("karim-benzema", "Karim Benzema", "Karim_Benzema"),
    ("harry-kane", "Harry Kane", "Harry_Kane"),
    ("kylian-mbappe", "Kylian Mbappé", "Kylian_Mbappé"),
    ("erling-haaland", "Erling Haaland", "Erling_Haaland"),
    ("neymar", "Neymar", "Neymar"),
    ("thierry-henry", "Thierry Henry", "Thierry_Henry"),
    ("ronaldo-nazario", "Ronaldo Nazário", "Ronaldo_(Brazilian_footballer)"),
    ("romario", "Romário", "Romário"),
]

LIST_PAGES = {
    "ucl_scorers": "List_of_UEFA_Champions_League_top_scorers",   # redirect target of List_of_European_Cup_and_UEFA_Champions_League_top_scorers
    "ucl_records": "European_Cup_and_UEFA_Champions_League_records_and_statistics",  # redirect target of UEFA_Champions_League_records_and_statistics
    "golden_shoe": "European_Golden_Shoe",
    "ballon_dor": "Ballon_d'Or",
    "fifa_wpoty": "FIFA_World_Player_of_the_Year",
    "fifa_ballon_dor": "FIFA_Ballon_d'Or",
    "the_best": "The_Best_FIFA_Men's_Player",
    "wc_awards": "FIFA_World_Cup_awards",
    "copa_awards": "Copa_América_awards",
    "euro_awards": "UEFA_European_Championship_awards",
    "super_cup": "UEFA_Super_Cup",                                    # status of the 1972 edition
    "goals_500": "List_of_footballers_with_500_or_more_goals",       # fetched for cross-check only (not used for honours)
}

# ----------------------------------------------------------------------------------------------
# Generic helpers
# ----------------------------------------------------------------------------------------------
DASH = "–"


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s):
    """lower-case, accent-free, typographic apostrophes/dashes unified, whitespace collapsed"""
    s = strip_accents(s).lower()
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"[–—−‐]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_target(t):
    t = t.split("#")[0].replace("_", " ").strip()
    return norm(t)


def load_page(title):
    path = os.path.join(RAW, title + ".wikitext")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    meta = {}
    mpath = os.path.join(RAW, title + ".meta.json")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fh:
            meta = json.load(fh)
    if not meta.get("fetched_at"):
        meta["fetched_at"] = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta["fetched_at_note"] = "no sidecar; file mtime used"
    return text, meta


# ---- brace / bracket aware scanning ---------------------------------------------------------
def _match_close(text, i, open_tok, close_tok):
    """text[i:] starts with open_tok; return index just after the matching close_tok (or len)."""
    depth, j, n = 0, i, len(text)
    while j < n:
        if text.startswith(open_tok, j):
            depth += 1
            j += len(open_tok)
            continue
        if text.startswith(close_tok, j):
            depth -= 1
            j += len(close_tok)
            if depth == 0:
                return j
            continue
        j += 1
    return n


def split_params(inner):
    parts, cur, db, dl, i = [], [], 0, 0, 0
    while i < len(inner):
        two = inner[i:i + 2]
        if two == "{{":
            db += 1; cur.append(two); i += 2; continue
        if two == "}}":
            db -= 1; cur.append(two); i += 2; continue
        if two == "[[":
            dl += 1; cur.append(two); i += 2; continue
        if two == "]]":
            dl -= 1; cur.append(two); i += 2; continue
        if inner[i] == "|" and db == 0 and dl == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(inner[i])
        i += 1
    parts.append("".join(cur))
    return parts


NOTE_TEMPLATES = {"efn", "efn-ua", "efn-lr", "efn-la", "efn-ur", "efn-lg", "refn", "sfn", "sfnp", "sfnm",
                  "harvnb", "harvp", "cn", "citation needed", "fact", "r", "rp", "notetag", "ref label",
                  "note label", "dubious", "clarify", "better source needed", "failed verification",
                  "when", "by whom", "which", "who", "update needed", "update", "#tag:ref", "ref", "nbsp",
                  "citation needed span", "verification needed", "according to whom", "unreliable source?"}
REMOVE_TEMPLATES = {"columns-list", "div col", "div col end", "col-begin", "col-2", "col-3", "col-end",
                    "col-break", "refbegin", "refend", "clear", "multicol", "multicol-break", "multicol-end",
                    "colbegin", "colend", "for", "main", "see also", "further", "flagicon", "fbaicon", "fbicon",
                    "flag icon", "dagger", "double-dagger", "updated", "#expr", "decimals", "sort dash",
                    "short description", "pp-semi-indef", "use dmy dates", "anchor", "ayd", "sticky-header",
                    "tooltip", "efn-ua", "notelist", "reflist"}
UNWRAP_TEMPLATES = {"small", "nowrap", "nobr", "big", "sup", "sub", "resize", "bold", "italic", "nowrap begin"}


def expand_templates(text):
    """Remove footnote/layout templates, unwrap formatting ones, expand ill/sortname/sort/nts/'."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("{{", i):
            j = _match_close(text, i, "{{", "}}")
            inner = text[i + 2:j - 2]
            params = split_params(inner)
            name = params[0].strip()
            lname = name.lower()
            pos = [p for p in params[1:] if not re.match(r"^\s*[\w-]+\s*=", p)]
            named = {}
            for p in params[1:]:
                m = re.match(r"^\s*([\w-]+)\s*=(.*)$", p, flags=re.S)
                if m:
                    named[m.group(1).strip()] = m.group(2).strip()
            rep = None
            if lname in NOTE_TEMPLATES or lname.startswith("efn") or lname in REMOVE_TEMPLATES:
                rep = ""
            elif lname == "'":
                rep = "'"
            elif lname == "!":
                rep = "|"
            elif lname in UNWRAP_TEMPLATES:
                rep = expand_templates(pos[0]) if pos else ""
            elif lname == "abbr":
                rep = expand_templates(pos[0]) if pos else ""
            elif lname == "ill":
                target = pos[0].strip() if pos else ""
                label = named.get("lt", target)
                rep = f"[[{target}|{label}]]"
            elif lname == "sortname":
                first = pos[0].strip() if len(pos) > 0 else ""
                last = pos[1].strip() if len(pos) > 1 else ""
                link = pos[2].strip() if len(pos) > 2 else ""
                disp = f"{first} {last}".strip()
                if named.get("nolink"):
                    rep = disp
                else:
                    target = link or (f"{disp} ({named['dab']})" if named.get("dab") else disp)
                    rep = f"[[{target}|{disp}]]"
            elif lname == "sort":
                rep = expand_templates(pos[1]) if len(pos) > 1 else ""
            elif lname == "nts":
                rep = pos[0].strip() if pos else ""
            else:
                rep = text[i:j]  # keep unknown templates verbatim (stripped later for plain text)
            out.append(rep)
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def remove_file_links(text):
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("[[", i):
            j = _match_close(text, i, "[[", "]]")
            inner = text[i + 2:j - 2]
            if re.match(r"^\s*(file|image|category)\s*:", inner, flags=re.I):
                i = j
                continue
            out.append(text[i:j])
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def clean_wikitext(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/\s*>", "", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref\s*>", "", text, flags=re.S | re.I)
    text = expand_templates(text)
    text = remove_file_links(text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"</?(sup|sub|small|span|nowiki|big|center|div|abbr)[^>]*>", "", text, flags=re.I)
    return text


LINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")


def links_of(s):
    return [(m.group(1).strip(), (m.group(2) if m.group(2) is not None else m.group(1)).strip())
            for m in LINK_RE.finditer(s)]


def plain(s):
    s = LINK_RE.sub(lambda m: (m.group(2) if m.group(2) is not None else m.group(1)), s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = s.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def split_top_colon(s):
    db = dl = 0
    i = 0
    while i < len(s):
        two = s[i:i + 2]
        if two == "[[":
            dl += 1; i += 2; continue
        if two == "]]":
            dl -= 1; i += 2; continue
        if two == "{{":
            db += 1; i += 2; continue
        if two == "}}":
            db -= 1; i += 2; continue
        if s[i] == ":" and db == 0 and dl == 0:
            return s[:i], s[i + 1:]
        i += 1
    return s, None


# ----------------------------------------------------------------------------------------------
# Value tokenising: years / seasons, qualifiers, parenthetical notes
# ----------------------------------------------------------------------------------------------
YEAR_PAT = (r"(?<!\d)(?P<y1>1[89]\d{2}|20\d{2})(?:\s*[–—−‐-]\s*(?P<y2>\d{4}|\d{2}))?"
            r"(?:\s+(?P<sfx>Metropolitano|Nacional|Apertura|Clausura))?(?!\d)")
QUAL_PAT = (r"\b(?P<q>runners?[\s\-–]?ups?|second[\s\-]place|third[\s\-]place|fourth[\s\-]place|"
            r"[234](?:nd|rd|th)[\s\-]place|nominated|nominations?|silver award|bronze award|finalists?)\b")
PAREN_PAT = r"(?P<paren>\((?:[^()]|\([^()]*\))*\))"
SCAN_RE = re.compile(PAREN_PAT + r"|(?P<ph>\x00(?P<phn>\d+)\x00)|" + QUAL_PAT + "|" + YEAR_PAT, re.I)
QUAL_ONLY_RE = re.compile(QUAL_PAT, re.I)


def qual_to_outcome(q):
    q = q.lower()
    if q.startswith("nominat"):
        return "nominated"
    if q.startswith("runner") or q.startswith("second") or q.startswith("2nd") or q.startswith("silver") or q.startswith("finalist"):
        return "runner_up"
    if q.startswith("third") or q.startswith("3rd") or q.startswith("bronze"):
        return "third_place"
    if q.startswith("fourth") or q.startswith("4th"):
        return "fourth_place"
    return "other"


def season_str(y1, y2, sfx):
    s = y1
    if y2:
        if len(y2) == 4:
            y2 = y2[2:] if y2[:2] == y1[:2] else y2
        s = f"{y1}{DASH}{y2}"
    if sfx:
        s += " " + sfx
    return s


def parse_value(value, initial_outcome):
    """Return list of entries {season, outcome, link, note, shared} from a bullet's value part."""
    links = []

    def _ph(m):
        links.append((m.group(1).strip(), (m.group(2) if m.group(2) is not None else m.group(1)).strip()))
        return f" \x00{len(links) - 1}\x00 "

    s = LINK_RE.sub(_ph, value)
    s = s.replace("'''", " ").replace("''", " ")
    s = re.sub(r"\{\{[^{}]*\}\}", " ", s)
    entries, outcome = [], initial_outcome

    def resolve(txt):
        return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))][1], txt)

    for m in SCAN_RE.finditer(s):
        if m.group("paren"):
            note = re.sub(r"\s+", " ", resolve(m.group("paren"))).strip()
            if entries:
                e = entries[-1]
                e["note"] = (e.get("note", "") + " " + note).strip()
                if re.search(r"shared|joint|tied", note, re.I):
                    e["shared"] = True
            continue
        if m.group("ph"):
            target, label = links[int(m.group("phn"))]
            found = False
            for ym in re.finditer(YEAR_PAT, label):
                entries.append({"season": season_str(ym.group("y1"), ym.group("y2"), ym.group("sfx")),
                                "outcome": outcome, "link": target})
                found = True
            if not found:
                qm = QUAL_ONLY_RE.search(label)
                if qm:
                    outcome = qual_to_outcome(qm.group("q"))
            continue
        if m.group("q"):
            outcome = qual_to_outcome(m.group("q"))
            continue
        if m.group("y1"):
            entries.append({"season": season_str(m.group("y1"), m.group("y2"), m.group("sfx")),
                            "outcome": outcome, "link": None})
    return entries


# ----------------------------------------------------------------------------------------------
# Honours-section walker
# ----------------------------------------------------------------------------------------------
NATIONAL_TEAMS = {"portugal", "argentina", "brazil", "west germany", "germany", "hungary", "netherlands",
                  "france", "england", "spain", "uruguay", "poland", "sweden", "norway", "italy"}
SKIP_HEADER_RE = re.compile(r"manager|coach|managerial|orders|records|decorations|further honours|honorific|overall", re.I)


def block_kind(name):
    n = norm(name)
    if re.search(r"\bu-?\d{2}\b|youth|under-\d{2}|olympic", n):
        return "national_youth"
    if n in NATIONAL_TEAMS:
        return "national"
    if "state team" in n:
        return "state_selection"
    return "club"


def honours_section(text):
    m = re.search(r"^==\s*Honou?rs\s*==\s*$", text, flags=re.M)
    if not m:
        return None, None
    rest = text[m.end():]
    n = re.search(r"^==[^=].*?==\s*$", rest, flags=re.M)
    start_line = text[:m.start()].count("\n") + 1
    return (rest[:n.start()] if n else rest), start_line


def walk_honours(section):
    """Yield dicts: {block, kind, mode, line} for every bullet in player/individual blocks."""
    mode, block, kind = "player", None, None
    skip_until_h3 = False
    out = []
    for raw_line in section.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        h = re.match(r"^(={3,6})\s*(.*?)\s*\1\s*$", line)
        if h:
            level, title = len(h.group(1)), h.group(2)
            t = norm(plain(title))
            if level == 3:
                skip_until_h3 = False
            if skip_until_h3:
                continue
            if SKIP_HEADER_RE.search(t):
                skip_until_h3 = True
                continue
            if t.startswith("individual"):
                mode, block, kind = "individual", "Individual", "individual"
            elif t in ("player", "club", "clubs", "international", "national team", "as a player"):
                mode, block, kind = "player", None, None
            else:
                mode, block, kind = "player", plain(title), block_kind(plain(title))
            continue
        if skip_until_h3:
            continue
        b = re.match(r"^'''(.+?)'''\s*(.*)$", line) or (re.match(r"^;\s*(.+?)()$", line) if line.startswith(";") else None)
        if b and not line.startswith("*"):
            name = plain(b.group(1)).strip(" :")
            n = norm(name)
            if SKIP_HEADER_RE.search(n):
                skip_until_h3 = True
                continue
            if n.startswith("individual"):
                mode, block, kind = "individual", "Individual", "individual"
            elif n == "player":
                pass  # Cruyff: ===Individual=== / '''Player''' keeps individual mode
            else:
                mode, block, kind = "player", name, block_kind(name)
            continue
        if line.startswith("*"):
            if line.startswith("**"):
                continue  # sub-bullets (no titles in any of the 21 pages)
            out.append({"block": block, "kind": kind, "mode": mode, "line": line.lstrip("*").strip()})
    return out


# ----------------------------------------------------------------------------------------------
# Team-honour classification (ordered; first match wins). Patterns run on the normalised
# label text + label link targets.  (pattern, category, competition, country)
# ----------------------------------------------------------------------------------------------
TEAM_RULES = [
    (r"olympic.*(silver|bronze)|(silver|bronze) medal", "excluded_olympic_non_gold", "Olympic Games (non-gold medal)", None),
    (r"olympic", "olympic_gold", "Olympic Games football tournament", None),
    (r"world youth championship|u-?20 world cup|under-1[79]|u-?1[679]\b|u-?20\b|youth|toulon tournament|syrenka|south american u-20|meridian",
     "youth", "Youth competition", None),
    (r"fifa club world cup", "fifa_club_world_cup", "FIFA Club World Cup", None),
    (r"fifa intercontinental cup", "fifa_intercontinental_cup", "FIFA Intercontinental Cup (2024–)", None),
    (r"intercontinental (champions' )?supercup", "other_international_club", "Intercontinental Champions' Supercup", None),
    (r"small club world cup", "other_international_club", "Small Club World Cup (unofficial)", None),
    (r"intercontinental cup|european/south american cup", "intercontinental_cup", "Intercontinental Cup (1960–2004)", None),
    (r"confederations cup", "confederations_cup", "FIFA Confederations Cup", None),
    (r"fifa world cup", "fifa_world_cup", "FIFA World Cup", None),
    (r"finalissima|artemio franchi", "finalissima", "CONMEBOL–UEFA Cup of Champions (Finalissima / Artemio Franchi Cup)", None),
    (r"nations league", "uefa_nations_league", "UEFA Nations League", None),
    (r"uefa european championship|uefa euro\b", "continental_nt", "UEFA European Championship", None),
    (r"south american championship of champions", "other_international_club", "South American Championship of Champions", None),
    (r"copa america|south american championship", "continental_nt", "Copa América / South American Championship", None),
    (r"cup winners'? cup", "cup_winners_cup", "European Cup Winners' Cup", None),
    (r"intertoto", "other_continental_club", "UEFA Intertoto Cup", None),
    (r"uefa super cup|european super cup", "uefa_super_cup", "UEFA Super Cup", None),
    (r"uefa cup|uefa europa league|inter-cities fairs cup", "uefa_cup_europa_league", "UEFA Cup / UEFA Europa League", None),
    (r"uefa champions league|european cup", "european_cup", "European Cup / UEFA Champions League", None),
    (r"supercopa libertadores", "other_continental_club", "Supercopa Libertadores", None),
    (r"copa libertadores", "copa_libertadores", "Copa Libertadores", None),
    (r"recopa sudamericana", "recopa_sudamericana", "Recopa Sudamericana", None),
    (r"copa mercosur", "other_continental_club", "Copa Mercosur (CONMEBOL)", None),
    (r"arab club champions cup", "other_international_club", "Arab Club Champions Cup (UAFA)", None),
    (r"latin cup", "other_international_club", "Latin Cup", None),
    (r"copa aldao", "other_international_club", "Copa Aldao (Argentina–Uruguay champions)", None),
    (r"leagues cup", "other_international_club", "Leagues Cup (MLS–Liga MX)", None),
    (r"campeones cup", "other_international_club", "Campeones Cup (MLS–Liga MX)", None),
    # league cups whose names contain a league name must precede the league rules
    (r"copa de la liga", "league_cup", "Copa de la Liga", "Spain"),
    (r"coupe de la ligue", "league_cup", "Coupe de la Ligue", "France"),
    # leagues ------------------------------------------------------------------------------------
    (r"supporters' shield", "league_regular_season", "MLS Supporters' Shield (regular season)", "United States"),
    (r"eastern conference|atlantic conference", "excluded_conference", "Conference title (MLS/NASL)", "United States"),
    (r"mls cup", "league", "Major League Soccer (MLS Cup)", "United States"),
    (r"north american soccer league|\bnasl\b", "league", "North American Soccer League (Soccer Bowl)", "United States"),
    (r"regionalliga|\bii+ liga\b|segunda division|serie a2|second division|usl first division", "lower_tier_league", "Lower-tier league", None),
    (r"campeonato paulista", "state_league", "Campeonato Paulista (São Paulo state)", "Brazil"),
    (r"campeonato carioca", "state_league", "Campeonato Carioca (Rio de Janeiro state)", "Brazil"),
    (r"campeonato mineiro", "state_league", "Campeonato Mineiro (Minas Gerais state)", "Brazil"),
    (r"campeonato gaucho", "state_league", "Campeonato Gaúcho (Rio Grande do Sul state)", "Brazil"),
    (r"campeonato provincial|mocambola", "state_league", "Campeonato Provincial de Moçambique (colonial-era provincial championship)", "Mozambique"),
    (r"recopa gaucha", "other_domestic", "Recopa Gaúcha (state super cup)", "Brazil"),
    (r"selecoes estaduais", "other_domestic", "Campeonato Brasileiro de Seleções Estaduais (state teams)", "Brazil"),
    (r"campeonato brasileiro serie a", "league", "Campeonato Brasileiro Série A", "Brazil"),
    (r"premier league", "league", "Premier League", "England"),
    (r"la liga", "league", "La Liga", "Spain"),
    (r"serie a", "league", "Serie A", "Italy"),
    (r"austrian (football )?bundesliga", "league", "Austrian Bundesliga", "Austria"),
    (r"bundesliga", "league", "Bundesliga", "Germany"),
    (r"ligue 1|division 1", "league", "Ligue 1 / French Division 1", "France"),
    (r"eredivisie", "league", "Eredivisie", "Netherlands"),
    (r"primeira liga|primeira divisao", "league", "Primeira Liga / Primeira Divisão", "Portugal"),
    (r"saudi pro league", "league", "Saudi Pro League", "Saudi Arabia"),
    (r"ekstraklasa", "league", "Ekstraklasa", "Poland"),
    (r"nemzeti bajnoksag", "league", "Nemzeti Bajnokság I", "Hungary"),
    (r"uruguayan primera division", "league", "Uruguayan Primera División", "Uruguay"),
    (r"argentine primera division|^primera division", "league", "Argentine Primera División", "Argentina"),
    (r"campeonato profesional|categoria primera a", "league", "Categoría Primera A (Campeonato Profesional)", "Colombia"),
    # domestic cups -----------------------------------------------------------------------------
    (r"community shield", "super_cup", "FA Community Shield", "England"),
    (r"supertaca", "super_cup", "Supertaça Cândido de Oliveira", "Portugal"),
    (r"supercopa de espana", "super_cup", "Supercopa de España", "Spain"),
    (r"supercoppa italiana", "super_cup", "Supercoppa Italiana", "Italy"),
    (r"trophee des champions", "super_cup", "Trophée des Champions", "France"),
    (r"dfl-supercup|franz beckenbauer supercup", "super_cup", "DFL-Supercup / Franz Beckenbauer Supercup", "Germany"),
    (r"johan cru(?:ij|y)ff shield|dutch super ?cup", "super_cup", "Johan Cruyff Shield (Dutch Super Cup)", "Netherlands"),
    (r"polish super cup", "super_cup", "Polish Super Cup", "Poland"),
    (r"saudi super cup", "super_cup", "Saudi Super Cup", "Saudi Arabia"),
    (r"efl cup|football league cup", "league_cup", "EFL Cup / Football League Cup", "England"),
    (r"fa cup", "national_cup", "FA Cup", "England"),
    (r"copa del rey|copa del generalisimo", "national_cup", "Copa del Rey / Copa del Generalísimo", "Spain"),
    (r"coppa italia", "national_cup", "Coppa Italia", "Italy"),
    (r"dfb-pokal", "national_cup", "DFB-Pokal", "Germany"),
    (r"coupe de france", "national_cup", "Coupe de France", "France"),
    (r"knvb cup", "national_cup", "KNVB Cup", "Netherlands"),
    (r"taca de portugal", "national_cup", "Taça de Portugal", "Portugal"),
    (r"copa do brasil", "national_cup", "Copa do Brasil", "Brazil"),
    (r"king's cup", "national_cup", "King's Cup (Saudi Arabia)", "Saudi Arabia"),
    (r"austrian cup", "national_cup", "Austrian Cup", "Austria"),
    (r"polish cup", "national_cup", "Polish Cup", "Poland"),
    (r"copa colombia", "national_cup", "Copa Colombia", "Colombia"),
    (r"copa argentina", "national_cup", "Copa Argentina", "Argentina"),
    (r"qatar crown prince cup", "other_domestic", "Qatar Crown Prince Cup", "Qatar"),
    (r"taca ribeiro dos reis", "other_domestic", "Taça Ribeiro dos Reis", "Portugal"),
    (r"taca de honra", "other_domestic", "Taça de Honra de Lisboa (regional)", "Portugal"),
    (r"torneio rio-sao paulo", "other_domestic", "Torneio Rio–São Paulo (inter-state)", "Brazil"),
    (r"tournoi de paris", "other_friendly", "Tournoi de Paris (invitational)", None),
    # national-team minor / regional --------------------------------------------------------------
    (r"roca cup|oswaldo cruz|bernardo o'higgins|taca do atlantico|independence cup", "other_national_team", "Minor/bilateral national-team cup", None),
    (r"central european international cup", "other_national_team", "Central European International Cup (regional, 1927–60)", None),
    (r"balkan cup", "other_national_team", "Balkan Cup (regional)", None),
]
COUNTED_TEAM_CATS = {"league", "national_cup", "league_cup", "super_cup", "european_cup", "copa_libertadores",
                     "cup_winners_cup", "uefa_cup_europa_league", "uefa_super_cup", "recopa_sudamericana",
                     "intercontinental_cup", "fifa_club_world_cup", "fifa_intercontinental_cup", "fifa_world_cup",
                     "continental_nt", "uefa_nations_league", "confederations_cup", "finalissima", "olympic_gold"}


def classify_team(label_plain, label_links):
    key = norm(label_plain + " || " + " | ".join(t for t, _ in label_links))
    for pat, cat, comp, country in TEAM_RULES:
        if re.search(pat, key):
            # specific competition names for continental national-team titles
            if cat == "continental_nt":
                comp = "UEFA European Championship" if re.search(r"uefa european championship|uefa euro", key) else "Copa América / South American Championship"
            return cat, comp, country
    return None, None, None


# ----------------------------------------------------------------------------------------------
# Individual-award classification
# ----------------------------------------------------------------------------------------------
LEAGUE_TOP_SCORER_RULES = [
    # (pattern on normalised label+links, league, country)
    (r"pichichi|spanish league top scorer", "La Liga", "Spain"),
    (r"premier league golden boot", "Premier League", "England"),
    (r"capocannoniere", "Serie A", "Italy"),
    (r"torjagerkanone|bundesliga top (goal)?scorer|list of bundesliga top scorers", "Bundesliga", "Germany"),
    (r"ligue 1 top (goal)?scorer|list of ligue 1 top scorers", "Ligue 1", "France"),
    (r"eredivisie (top scorer|golden boot)|list of eredivisie top scorers|eredivisie top scorer", "Eredivisie", "Netherlands"),
    (r"bola de prata \(portugal\)", "Primeira Liga / Primeira Divisão", "Portugal"),
    (r"saudi pro league (golden boot|top (goal)?scorer)", "Saudi Pro League", "Saudi Arabia"),
    (r"ekstraklasa top (goal)?scorer", "Ekstraklasa", "Poland"),
    (r"hungarian top scorer", "Nemzeti Bajnokság I", "Hungary"),
    (r"argentine primera division top scorer", "Argentine Primera División", "Argentina"),
    (r"campeonato profesional top scorer", "Categoría Primera A (Campeonato Profesional)", "Colombia"),
    (r"campeonato brasileiro serie a top scorer", "Campeonato Brasileiro Série A", "Brazil"),
    (r"mls golden boot", "Major League Soccer", "United States"),
]
# top-scorer style awards that are NOT top-flight league awards (recorded, never counted)
OTHER_TOP_SCORER_RE = re.compile(r"top (goal)?scorer|golden boot|golden shoe|topscorer|rei do gol", re.I)
# European-calendar leagues: a bare year on a player page ("Bundesliga top scorer: 1967") is the
# season-ending year and is normalised to "1966–67" (original kept in as_listed).
EUROPEAN_SEASON_LEAGUES = {"Bundesliga", "Primeira Liga / Primeira Divisão", "La Liga", "Serie A", "Premier League",
                           "Ligue 1", "Eredivisie", "Ekstraklasa", "Saudi Pro League"}
# Editions listed as won on a player page but not recognised by the organising body.
UNOFFICIAL_EDITIONS = {
    ("uefa_super_cup", "1972"): "1972 European Super Cup (Ajax v Rangers) 'is considered unofficial by UEFA' "
                                "(https://en.wikipedia.org/wiki/UEFA_Super_Cup); listed, not counted.",
}


def classify_individual(label_plain, label_links, full_line):
    lp = norm(label_plain)
    key = norm(label_plain + " || " + " | ".join(t for t, _ in label_links))
    fl = norm(plain(full_line))
    first_link = norm_target(label_links[0][0]) if label_links else ""
    if re.search(r"assist", key):
        return {"cat": "ignore"}
    if re.search(r"gerd muller trophy|striker of the year|kopa trophy|dream team", key):
        return {"cat": "ignore"}
    # ---- Ballon d'Or family --------------------------------------------------------------------
    if "super ballon d'or" in key:
        return {"cat": "super_ballon_dor"}
    if re.search(r"nouveau palmares", fl):
        return {"cat": "ballon_dor_retrospective"}
    if re.search(r"prix d'honneur|for services to football", fl):
        return {"cat": "ballon_dor_honorary"}
    if re.search(r"special award", key):
        return {"cat": "ignore"}
    if first_link in ("fifa world player of the year", "the best fifa men's player") or lp.startswith("fifa world player of the year") or lp.startswith("the best fifa men's player"):
        return {"cat": "fifa_award"}
    # the label itself must BE the Ballon d'Or (e.g. not Pelé's "Football Player of the Century,
    # elected by France Football's Ballon d'Or winners")
    if re.match(r"^(fifa )?ballon d'or", lp):
        return {"cat": "ballon_dor"}
    # ---- Golden Shoe / UCL top scorer ----------------------------------------------------------
    if "european golden shoe" in key:
        return {"cat": "european_golden_shoe"}
    if re.search(r"(champions league|european cup)[^|]*top (goal)?scorer", key) and "nations" not in key:
        return {"cat": "ucl_top_scorer"}
    # ---- World Cup -----------------------------------------------------------------------------
    m = re.match(r"^(\d{4}) fifa world cup$", lp)
    if m and re.search(r"golden ball", fl):
        return {"cat": "wc_golden_ball", "year_from_label": m.group(1)}
    if "world cup" in lp and "club world cup" not in lp and "youth" not in lp and "u-20" not in lp:
        if re.search(r"golden ball", lp):
            return {"cat": "wc_golden_ball"}
        if re.search(r"golden (boot|shoe)", lp):
            return {"cat": "wc_golden_boot"}
        if re.search(r"(silver|bronze) (ball|boot|shoe)", lp):
            return {"cat": "wc_other_award"}
    # ---- continental national-team top scorer ---------------------------------------------------
    if re.search(r"nations league[^|]*(top scorer|golden boot)", key) and not re.search(r"bronze|silver", lp):
        return {"cat": "nations_league_top_scorer"}
    if re.search(r"(european championship|uefa euro)[^|]*(golden boot|top (goal)?scorer)", key) and "qualif" not in key and not re.search(r"bronze|silver", lp):
        return {"cat": "continental_top_scorer", "competition": "UEFA European Championship"}
    if re.search(r"(copa america|south american championship)[^|]*(golden boot|top scorer)", key) and not re.search(r"u-20|youth|bronze|silver", key):
        return {"cat": "continental_top_scorer", "competition": "Copa América / South American Championship"}
    # ---- league top scorer ----------------------------------------------------------------------
    if "landmark" not in key:
        for pat, league, country in LEAGUE_TOP_SCORER_RULES:
            if re.search(pat, key):
                return {"cat": "league_top_scorer", "league": league, "country": country}
    if OTHER_TOP_SCORER_RE.search(lp) and not re.search(r"galaxy|placar|cbf|landmark", key):
        return {"cat": "other_top_scorer"}
    return {"cat": None}


# ----------------------------------------------------------------------------------------------
# Season helpers
# ----------------------------------------------------------------------------------------------
def year_to_season(tok):
    """'1968' -> '1967–68' (season-ending year notation used on some pages); seasons unchanged."""
    if re.fullmatch(r"\d{4}", tok):
        y = int(tok)
        return f"{y - 1}{DASH}{str(y)[2:]}"
    return tok


def season_end_year(tok):
    m = re.match(r"(\d{4})(?:–(\d{2,4}))?", tok)
    if not m:
        return None
    if m.group(2):
        e = m.group(2)
        return int(e) if len(e) == 4 else int(m.group(1)[:2] + e)
    return int(m.group(1))


def first_year(tok):
    m = re.match(r"(\d{4})", tok)
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------------------------------
# List-article parsers (cross-checks)
# ----------------------------------------------------------------------------------------------
def section_of(text, start_heading_regex, end_heading_regex=None):
    m = re.search(start_heading_regex, text, flags=re.M)
    if not m:
        return ""
    rest = text[m.end():]
    if end_heading_regex:
        n = re.search(end_heading_regex, rest, flags=re.M)
        return rest[:n.start()] if n else rest
    return rest


def table_rows(table_wikitext):
    t = wtp.parse(table_wikitext).tables[0]
    return t.data(span=True)


def cell_targets(cell):
    cell = cell or ""
    return [norm_target(t) for t, _ in links_of(clean_wikitext(cell))
            if not re.match(r"(file|image)\s*:", t, re.I)]


def cell_plain(cell):
    return plain(clean_wikitext(cell or "")).replace("'''", "").strip()


def parse_ballon_dor_table(text):
    sec = section_of(text, r"^== Winners ==", r"^=== Wins by player ===")
    sec = clean_wikitext(re.sub(r"<!--.*?-->", "", sec, flags=re.S))
    p = wtp.parse(sec)
    table = [t for t in p.tables if "Ballon d'Or winners" in t.string[:400]][0]
    res = defaultdict(list)
    for row in table.data(span=True):
        if len(row) < 3:
            continue
        year = cell_plain(row[0])
        if not re.fullmatch(r"\d{4}", year):
            continue
        rank = cell_plain(row[1])
        for t in cell_targets(row[2])[:1]:
            res[t].append((int(year), rank))
    return res


def parse_golden_shoe(text):
    sec = section_of(text, r"^== Winners ==", r"^=== Multiple winners ===")
    sec = clean_wikitext(re.sub(r"<!--.*?-->", "", sec, flags=re.S))
    p = wtp.parse(sec)
    table = [t for t in p.tables if "European Golden Shoe winners" in t.string[:300]][0]
    res = defaultdict(list)
    for row in table.data(span=True):
        if len(row) < 3:
            continue
        season = cell_plain(row[0])
        if not re.match(r"^\d{4}", season):
            continue
        pairs = [(norm_target(t), lbl) for t, lbl in links_of(clean_wikitext(row[1] or ""))
                 if not re.match(r"(file|image)\s*:", t, re.I)][:1]
        for t, lbl in pairs:
            res[t].append(season.replace("-", DASH))
            GOLDEN_SHOE_WINNERS[season.replace("-", DASH)].append(t)
            DISPLAY.setdefault(t, lbl)
    return res


GOLDEN_SHOE_WINNERS = defaultdict(list)  # season -> winners (2 entries = shared award)


def parse_ucl_alltime(text):
    sec = section_of(text, r"^== All-time top scorers ==", r"^==Top scorers by season==")
    sec = clean_wikitext(sec)
    rows = re.split(r"\n\|-", sec)
    res = {}
    for r in rows:
        if 'scope="row"' not in r:
            continue
        lines = [l for l in r.split("\n") if l.strip()]
        tgt = cell_targets(r)
        if not tgt:
            continue
        cells = [re.sub(r'^[|!]\s*(?:[^|\[\]]*\|(?!\|))?', "", l).strip() for l in lines]
        nums = [c for c in cells if re.fullmatch(r"\d+", c)]
        # rows start with rank (may be absent for tied rows) -> take the last two integers before ratio
        years = next((c for c in cells if re.fullmatch(r"\d{4}–(\d{4})?", plain(c))), None)
        if len(nums) >= 2:
            goals, apps = int(nums[-2]), int(nums[-1])
            clubs = plain(re.sub(r'^\|\s*(?:[^|\[\]]*\|(?!\|))?', "", lines[-1]))
            res[tgt[0]] = {"goals": goals, "apps": apps, "years": plain(years) if years else None, "clubs": clubs}
    return res


def parse_ucl_season_top_scorers(text):
    sec = section_of(text, r"^==Top scorers by season==", r"^===By player===")
    sec = clean_wikitext(sec)
    data = wtp.parse(sec).tables[0].data(span=True)
    by_season = defaultdict(list)
    for row in data[1:]:
        season = cell_plain(row[0])
        for t in cell_targets(row[1])[:1]:
            by_season[season].append(t)
    res = defaultdict(list)
    for season, ps in by_season.items():
        for t in ps:
            res[t].append({"season": season, "shared": len(ps) > 1})
    return res


def parse_ucl_most_wins(text):
    sec = section_of(text, r"^==== Most wins ====", r"^==== Match wins ====")
    sec = clean_wikitext(sec)
    data = wtp.parse(sec).tables[0].data(span=True)
    res = {}
    for row in data[1:]:
        if len(row) < 2:
            continue
        n = cell_plain(row[0])
        tg = cell_targets(row[1])
        if re.fullmatch(r"\d+", n) and tg:
            res[tg[0]] = int(n)
    return res


def parse_wins_by_player(text, heading=r"^===\s*Wins by player\s*==="):
    sec = section_of(text, heading, r"^===\s*Wins by country\s*===")
    sec = clean_wikitext(sec)
    t = wtp.parse(sec).tables[0]
    res = {}
    for row in t.data(span=True)[1:]:
        # locate the player cell = first cell whose first link is not a year-article
        idx = None
        for i, c in enumerate(row):
            tg = cell_targets(c)
            if tg and not re.match(r"^\d{4} |the best fifa football awards", tg[0]):
                idx = i
                break
        if idx is None:
            continue
        player = cell_targets(row[idx])[0]
        cols = row[idx + 1:idx + 4]

        def yrs(c):
            return sorted({int(m.group(0)) for m in re.finditer(r"(?<!\d)(19|20)\d{2}(?!\d)", cell_plain(c))})
        res[player] = {"winner": yrs(cols[0]) if len(cols) > 0 else [],
                       "runner_up": yrs(cols[1]) if len(cols) > 1 else [],
                       "third": yrs(cols[2]) if len(cols) > 2 else []}
    return res


def parse_wc_golden_ball_official(text):
    sec = section_of(text, r"^===Official winners \(1982–present\)===", r"^===Unofficial winner")
    sec = clean_wikitext(sec)
    res = {}
    for row in wtp.parse(sec).tables[0].data(span=True)[1:]:
        y = re.match(r"\d{4}", cell_plain(row[0]))
        if y:
            res[int(y.group(0))] = [cell_targets(c)[0] if cell_targets(c) else None for c in row[1:4]]
    return res


def parse_wc_top_scorers(text):
    sec = section_of(text, r"^==Golden Boot==", r"^==Golden Glove==")
    sec = clean_wikitext(sec)
    res = {}
    for row in wtp.parse(sec).tables[0].data(span=True):
        if not row:
            continue
        y = re.match(r"\d{4}", cell_plain(row[0]))
        if y and len(row) > 1:
            res[int(y.group(0))] = cell_targets(row[1])
    return res


def parse_continental_top_scorers(text, start, end):
    """year -> list of sets (one per edition; two South American Championships were held in 1959)
    of player targets listed as that edition's top scorer(s)."""
    sec = clean_wikitext(section_of(text, start, end))
    res = defaultdict(list)
    for row in wtp.parse(sec).tables[0].data(span=True):
        if not row:
            continue
        y = re.match(r"\d{4}", cell_plain(row[0]))
        if not y:
            continue
        cols = []
        for c in row[1:]:
            pairs = [(norm_target(t), lbl) for t, lbl in links_of(clean_wikitext(c or ""))
                     if not re.match(r"^\d{4} |(file|image)\s*:", t, re.I)]
            cols.append(pairs)
        if cols:
            best = max(cols, key=len)
            DISPLAY.update(dict(best))
            res[int(y.group(0))].append({t for t, _ in best})
    return res


DISPLAY = {}  # normalised link target -> display name (for co-top-scorer lists)


def edition_with(lst, target):
    """the edition set (from parse_continental_top_scorers) that contains target, else empty set"""
    return next((s for s in lst if target in s), set())


def parse_career_stats_european_cup(text, efn_regex):
    """Sum apps/goals in career-statistics cells whose {{efn}} note names the European Cup / UCL.
    Returns (apps, goals, per_season list) or None."""
    s = re.search(r"^==+\s*Career statistics\s*==+", text, flags=re.M)
    if not s:
        return None
    sec = text[s.end():]
    e = re.search(r"^===?\s*International", sec, flags=re.M)
    sec = sec[:e.start()] if e else sec
    names = {}
    for m in re.finditer(r"\{\{efn\|name=([^|}]+)\|([^}]*)\}\}", sec):
        names[m.group(1).strip()] = m.group(2)
    wanted = {n for n, txt in names.items() if re.search(efn_regex, txt)}
    total_a = total_g = 0
    per = []
    season = None
    for line in sec.split("\n"):
        sm = re.match(r"^\|\s*\[\[[^\]|]*\|(\d{4}(?:–\d{2,4})?)\]\]", line.strip())
        if sm:
            season = sm.group(1)
        cells = re.split(r"\|\|", line)
        for i, c in enumerate(cells):
            m = re.search(r"(\d+)\s*\{\{efn\|name=([^|}]+)", c)
            if m and m.group(2).strip() in wanted and i + 1 < len(cells):
                g = re.match(r"\s*(\d+)", cells[i + 1])
                if g:
                    total_a += int(m.group(1)); total_g += int(g.group(1))
                    per.append({"season": season, "apps": int(m.group(1)), "goals": int(g.group(1))})
    return total_a, total_g, per


# ----------------------------------------------------------------------------------------------
# Secondary sources for players below the UCL list's 25-goal cut-off (documented, not estimated)
# ----------------------------------------------------------------------------------------------
UCL_FALLBACK = {
    "pele": {
        "goals": 0, "apps": 0, "apps_include_qualifiers": False,
        "source": "Wikipedia Pelé infobox: clubs Santos (1956–1974) and New York Cosmos (1975–1977) only; "
                  "never played for a European club, so no European Cup/UCL matches.",
    },
    "diego-maradona": {
        "goals": 2, "apps": 6, "apps_include_qualifiers": False,
        "source": "Wikipedia Diego_Maradona career-statistics table (cells annotated 'Appearances in European Cup'): "
                  "1987–88 2 apps/0 goals, 1990–91 4 apps/2 goals. Goals corroborated by match reports in "
                  "1987–88_European_Cup (Real Madrid 2–0, Napoli 1–1 Francini) and 1990–91_European_Cup "
                  "(Napoli 3–0 Újpesti Dózsa: Maradona 43', 77'; away 2–0 Incocciati, Alemão; Spartak 0–0, 0–0). "
                  "Pre-1992 knockout format, Napoli entered in the first round, so no qualifying matches.",
        "wiki_efn": r"European Cup(?! Winners)",
    },
    "johan-cruyff": {
        "goals": 19, "apps": 49, "apps_include_qualifiers": False,
        "source": "RSSSF 'Johan Cruijff - Goals in European Cups' (Marcel Haisma, last updated 31 Jul 2008), "
                  "https://rsssf.org/players/cruijff-in-ec.html: Champions Cup 49 matches/19 goals (1966–67 to 1982–83). "
                  "Matches the Wikipedia Johan_Cruyff career-statistics cells annotated 'Appearances in European Cup'.",
        "wiki_efn": r"European Cup(?! Winners)",
    },
    "zinedine-zidane": {
        "goals": 14, "apps": 80, "apps_include_qualifiers": False,
        "source": "RSSSF 'Zinédine Zidane - Matches in European Cups' (Emilio Pla Díaz, last updated 15 Jan 2010), "
                  "https://rsssf.org/players/zidane-in-ec.html: Champions League 82 matches/14 goals, which include the "
                  "2004–05 third qualifying round v Wisła Kraków (2 matches, 0 goals; round confirmed in "
                  "2004–05_UEFA_Champions_League). Excluding them: 80 matches/14 goals.",
    },
    "ronaldo-nazario": {
        "goals": 14, "apps": 40, "apps_include_qualifiers": False,
        "source": "RSSSF 'Ronaldo Luis Nazário de Lima - Goals in European Cups' (Emilio Pla Díaz, last updated 14 Feb 2008), "
                  "https://rsssf.org/players/ronaldo-in-ec.html: Champions League 42 matches/16 goals, which include the "
                  "2004–05 third qualifying round v Wisła Kraków (2 matches, 2 goals; round confirmed in "
                  "2004–05_UEFA_Champions_League). Excluding them: 40 matches/14 goals. The Wikipedia career-statistics "
                  "UCL cells sum to 42/16, i.e. they include those qualifiers.",
        "wiki_efn": r"UEFA Champions League",
    },
    "romario": {
        "goals": 20, "apps": 32, "apps_include_qualifiers": False,
        "source": "RSSSF '\"Romário\" de Souza Faria - Matches in European Cups' (Karel Stokkermans, last updated 7 Jan 2009), "
                  "https://rsssf.org/players/romario-in-ec.html: Champions Cup/Champions League 32 matches/20 goals "
                  "(PSV 1988–89 to 1992–93, Barcelona 1993–94 and 1994–95), none in a qualifying/preliminary round "
                  "(checked against the season articles).",
    },
}


# ----------------------------------------------------------------------------------------------
# Per-player curated notes: context that the parser cannot infer (each tied to a cited source)
# ----------------------------------------------------------------------------------------------
CURATED_NOTES = {
    "luis-suarez": ["Wikipedia 'Luis_Suárez' is a disambiguation page; this record is the Uruguayan striker (b. 1987), "
                    "Luis_Suárez_(Uruguayan_footballer). Not to be confused with Luis Suárez Miramontes (Spain), 1960 Ballon d'Or winner."],
    "lionel-messi": ["Wikipedia does not credit the 2005 Supercopa de España (footnote: Messi was not in the squad for either "
                     "leg), although FC Barcelona, FIFA and the RFEF credit it; nor the 2025 MLS Eastern Conference trophy."],
    "pele": ["Pelé's six 'Campeonato Brasileiro Série A' titles are the 1961–65 Taça Brasil and the 1968 Torneio Roberto "
             "Gomes Pedrosa, retroactively unified with the national championship by the CBF (2010); likewise his 1961, 1963 "
             "and 1964 'Série A top scorer' awards are Taça Brasil top-scorer awards. Excluding the unified titles, his only "
             "national-league title is the 1977 NASL (Soccer Bowl) with New York Cosmos and he has no national-league "
             "top-scorer award.",
             "His 10 Campeonato Paulista titles and 11 Paulista top-scorer awards are state-level and not counted as "
             "top-flight league honours here; the 'France Football Ballon d'Or' years listed on his page are the "
             "retrospective 'Le nouveau palmarès', not awards (he was ineligible: non-European)."],
    "cristiano-ronaldo": ["The 2023 Arab Club Champions Cup (UAFA, not a confederation competition) is listed under "
                          "other_international_club, not as a continental title; many trophy tallies include it.",
                          "distinct_leagues_top_scorer = 4 is corroborated by his article: 'the first footballer to finish as "
                          "top scorer in four different leagues: the English, Spanish, Italian and Saudi leagues'."],
    "zlatan-ibrahimovic": ["The two Serie A titles won with Juventus (2004–05, 2005–06) were revoked in the Calciopoli "
                           "scandal and are not listed (his page: 'Juventus were stripped of their last two Scudetti'; "
                           "'2 additional titles were revoked with Juventus'). Counting them would give 14 league titles."],
    "ronaldo-nazario": ["Credited with the 1994 World Cup although he did not play a match (page: 'went to the 1994 FIFA "
                        "World Cup ... aged 17, but did not play')."],
    "neymar": ["Credited with the 2023–24 Saudi Pro League title with Al-Hilal after 3 league appearances (career-statistics "
               "table; text: 'He played five games for his new club before rupturing his anterior cruciate ligament')."],
    "erling-haaland": ["Credited with the 2018–19 Austrian Bundesliga title after 2 league appearances for Red Bull Salzburg "
                       "(joined 1 January 2019; career-statistics table)."],
    "eusebio": ["The 1976 NASL title was won with Toronto Metros-Croatia, a Canadian club in the US-based North American "
                "Soccer League; counted under 'United States' as the league's country."],
    "alfredo-di-stefano": ["His Colombian league titles (1949, 1951, 1952) and top-scorer awards (1951, 1952) with Millonarios "
                           "date from Colombia's 'El Dorado' period (which began on 25 April 1949, per his page); they are "
                           "counted as top-flight (Categoría Primera A) honours, as on his Wikipedia page."],
    "diego-maradona": ["The 1993 Artemio Franchi Cup is counted as a Finalissima: the competition was 'created in 1985 as the "
                       "European/South American Nations Cup ... also referred to as the Artemio Franchi Cup' and re-established "
                       "as the Finalissima in 2022 (https://en.wikipedia.org/wiki/Finalissima)."],
    "kylian-mbappe": ["The 2024 FIFA Intercontinental Cup (Real Madrid) is FIFA's new annual club competition, distinct from "
                      "both the 1960–2004 Intercontinental Cup and the FIFA Club World Cup; recorded separately."],
}


# ----------------------------------------------------------------------------------------------
# Main extraction per player
# ----------------------------------------------------------------------------------------------
def extract_player(pid, name, title, lists):
    text, meta = load_page(title)
    sec, start_line = honours_section(text)
    notes = list(CURATED_NOTES.get(pid, []))
    if sec is None:
        raise SystemExit(f"No Honours section for {title}")
    cleaned = clean_wikitext(sec)
    bullets = walk_honours(cleaned)
    src = f"https://en.wikipedia.org/wiki/{title}#Honours"

    team_items = []        # flat list of counted/uncounted team honours
    ind = defaultdict(list)
    review = []
    unclassified_team = []
    for b in bullets:
        label, value = split_top_colon(b["line"])
        label_plain, label_links = plain(label), links_of(label)
        qm = QUAL_ONLY_RE.search(label_plain)
        init_outcome = qual_to_outcome(qm.group("q")) if qm else "winner"
        if re.search(r"\bsilver award\b", label_plain, re.I):
            init_outcome = "runner_up"
        entries = parse_value(value, init_outcome) if value is not None else []
        declared = re.search(r"\((\d+)\)\s*$", label_plain)
        src_line = plain(b["line"])[:300]
        if b["mode"] == "player":
            cat, comp, country = classify_team(label_plain, label_links)
            review.append(("TEAM", b["block"], cat, comp, [(e["season"], e["outcome"]) for e in entries], src_line))
            if not entries:
                continue
            if cat is None:
                unclassified_team.append({"club_or_team": b["block"], "line": src_line})
                continue
            if b["kind"] == "national_youth" and cat not in ("olympic_gold", "excluded_olympic_non_gold"):
                cat = "youth"
            if declared and len([e for e in entries if e["outcome"] == "winner"]) != int(declared.group(1)):
                notes.append(f"Count check failed on '{src_line[:80]}': label says {declared.group(1)}, parsed "
                             f"{len([e for e in entries if e['outcome'] == 'winner'])} winning seasons.")
            # non-counted buckets keep the page's own wording so readers see what was excluded
            comp_name = comp if cat in COUNTED_TEAM_CATS or cat in ("league_regular_season", "state_league") \
                else re.sub(r"\s*\(\d+\)\s*$", "", label_plain).strip(" :'")
            for e in entries:
                c2, note = cat, e.get("note")
                if (cat, e["season"]) in UNOFFICIAL_EDITIONS and e["outcome"] == "winner":
                    c2, note = "unofficial_edition", UNOFFICIAL_EDITIONS[(cat, e["season"])]
                    notes.append(UNOFFICIAL_EDITIONS[(cat, e["season"])])
                team_items.append({"category": c2, "competition": comp_name, "country": country,
                                   "team": b["block"], "season": e["season"], "outcome": e["outcome"],
                                   "note": note, "source_line": src_line})
        elif b["mode"] == "individual":
            c = classify_individual(label_plain, label_links, b["line"])
            if c.get("year_from_label"):
                entries = [{"season": c["year_from_label"], "outcome": "winner", "link": None}]
            review.append(("IND", None, c.get("cat"), c.get("league") or c.get("competition"),
                           [(e["season"], e["outcome"]) for e in entries], src_line))
            if c["cat"] in (None, "ignore"):
                continue
            ind[c["cat"]].append({"entries": entries, "label": label_plain, "src": src_line, "meta": c,
                                  "declared": int(declared.group(1)) if declared else None})

    # ---------------------------------------------------------------- team honours assembly
    def items(cat, outcome="winner"):
        return [t for t in team_items if t["category"] == cat and t["outcome"] == outcome]

    def comp_block(cat):
        its = items(cat)
        return {"count": len(its), "seasons": [t["season"] for t in its],
                "teams": sorted({t["team"] for t in its if t["team"]}),
                "source": src if its else None}

    league_its = items("league")
    by_country = OrderedDict()
    for t in league_its:
        c = by_country.setdefault(t["country"], {"count": 0, "leagues": OrderedDict()})
        c["count"] += 1
        lg = c["leagues"].setdefault(t["competition"], {"count": 0, "seasons": [], "teams": []})
        lg["count"] += 1
        lg["seasons"].append(t["season"])
        if t["team"] not in lg["teams"]:
            lg["teams"].append(t["team"])

    def grouped(cat):
        out = OrderedDict()
        for t in items(cat):
            k = (t["competition"], t["country"])
            g = out.setdefault(k, {"competition": t["competition"], "country": t["country"], "count": 0,
                                   "seasons": [], "teams": []})
            g["count"] += 1
            g["seasons"].append(t["season"])
            if t["team"] not in g["teams"]:
                g["teams"].append(t["team"])
        lst = list(out.values())
        return {"total": sum(g["count"] for g in lst), "items": lst}

    cont_nt = grouped("continental_nt")
    team = OrderedDict()
    team["league_titles"] = {"total": len(league_its), "by_country": by_country, "source": src}
    team["domestic_cups"] = OrderedDict([("national_cup", grouped("national_cup")),
                                         ("league_cup", grouped("league_cup")),
                                         ("super_cup", grouped("super_cup"))])
    team["european_cup_ucl"] = comp_block("european_cup")
    team["other_continental_club"] = OrderedDict([
        ("copa_libertadores", comp_block("copa_libertadores")),
        ("cup_winners_cup", comp_block("cup_winners_cup")),
        ("uefa_cup_europa_league", comp_block("uefa_cup_europa_league")),
        ("uefa_super_cup", comp_block("uefa_super_cup")),
        ("recopa_sudamericana", comp_block("recopa_sudamericana")),
        ("other_not_counted", grouped("other_continental_club")["items"]),
    ])
    team["intercontinental_cup"] = comp_block("intercontinental_cup")
    team["fifa_club_world_cup"] = comp_block("fifa_club_world_cup")
    team["fifa_intercontinental_cup"] = comp_block("fifa_intercontinental_cup")
    team["fifa_world_cup"] = comp_block("fifa_world_cup")
    team["continental_national_team"] = cont_nt
    team["uefa_nations_league"] = comp_block("uefa_nations_league")
    team["confederations_cup"] = comp_block("confederations_cup")
    team["finalissima"] = comp_block("finalissima")
    team["olympic_gold"] = comp_block("olympic_gold")
    team["not_counted"] = OrderedDict([
        ("league_regular_season_titles", grouped("league_regular_season")["items"]),
        ("state_or_provincial_league_titles", grouped("state_league")["items"]),
        ("lower_tier_league_titles", grouped("lower_tier_league")["items"]),
        ("conference_titles", grouped("excluded_conference")["items"]),
        ("unofficial_editions", grouped("unofficial_edition")["items"]),
        ("other_domestic", grouped("other_domestic")["items"] + grouped("other_friendly")["items"]),
        ("other_international_club", grouped("other_international_club")["items"]),
        ("other_national_team", grouped("other_national_team")["items"]),
        ("youth", grouped("youth")["items"]),
    ])
    non_win = [t for t in team_items if t["outcome"] != "winner" and t["category"] in COUNTED_TEAM_CATS]
    team["non_winning_finishes"] = [{"competition": t["competition"], "season": t["season"], "outcome": t["outcome"],
                                     "team": t["team"]} for t in non_win]
    team["unclassified"] = unclassified_team

    # ---------------------------------------------------------------- individual assembly
    indiv = OrderedDict()

    def win_entries(cat):
        out = []
        for rec in ind.get(cat, []):
            for e in rec["entries"]:
                if e["outcome"] == "winner":
                    out.append((e, rec))
        return out

    # Ballon d'Or (wins from page; podiums from the Ballon d'Or article table)
    bd_page = sorted({first_year(e["season"]) for e, _ in win_entries("ballon_dor")})
    bd_page_runner = sorted({first_year(e["season"]) for rec in ind.get("ballon_dor", []) for e in rec["entries"] if e["outcome"] == "runner_up"})
    bd_page_third = sorted({first_year(e["season"]) for rec in ind.get("ballon_dor", []) for e in rec["entries"] if e["outcome"] == "third_place"})
    tgt = norm_target(title)
    table = lists["ballon_dor"].get(tgt, [])
    t1 = sorted(y for y, r in table if r.startswith("1"))
    t2 = sorted(y for y, r in table if r.startswith("2"))
    t3 = sorted(y for y, r in table if r.startswith("3"))
    indiv["ballon_dor"] = OrderedDict([
        ("wins", len(bd_page)), ("years", bd_page),
        ("podiums", OrderedDict([("first", t1), ("second", t2), ("third", t3), ("total", len(t1) + len(t2) + len(t3))])),
        ("includes_fifa_ballon_dor_2010_2015", sorted(y for y in bd_page if 2010 <= y <= 2015)),
        ("source", src),
        ("podium_source", "https://en.wikipedia.org/wiki/Ballon_d'Or#Winners (winners table, ranks 1st–3rd)"),
    ])
    if bd_page != t1:
        notes.append(f"Ballon d'Or wins differ: player page {bd_page} vs Ballon d'Or article {t1}.")
    for lbl, pg, tb in (("runner-up", bd_page_runner, t2), ("third place", bd_page_third, t3)):
        if pg and pg != tb:
            notes.append(f"Ballon d'Or {lbl} years differ: player page {pg} vs Ballon d'Or article {tb}.")
    other_bd = []
    for cat, kind in (("ballon_dor_retrospective", "retrospective 'Le nouveau palmarès' (France Football, 2015) — not an award"),
                      ("ballon_dor_honorary", "honorary award — not a Ballon d'Or win"),
                      ("super_ballon_dor", "Super Ballon d'Or (one-off 1989 award)")):
        for rec in ind.get(cat, []):
            other_bd.append({"award": rec["label"], "kind": kind,
                             "years": [e["season"] for e in rec["entries"]],
                             "outcomes": sorted({e["outcome"] for e in rec["entries"]})})
    indiv["ballon_dor_related_not_counted"] = other_bd

    # FIFA awards: split per sub-award by the year link (or by year range when unlinked)
    fifa = {"fifa_world_player_of_the_year": [], "fifa_ballon_dor": [], "the_best_fifa_mens_player": []}
    fifa_other = []
    for rec in ind.get("fifa_award", []):
        for e in rec["entries"]:
            y = first_year(e["season"])
            ln = norm(e.get("link") or "")
            if "fifa ballon d'or" in ln or (not ln and 2010 <= y <= 2015):
                k = "fifa_ballon_dor"
            elif "the best" in ln or (not ln and y >= 2016) or ("fifa world player" not in ln and y >= 2016):
                k = "the_best_fifa_mens_player"
            else:
                k = "fifa_world_player_of_the_year"
            if e["outcome"] == "winner":
                fifa[k].append(y)
            else:
                fifa_other.append({"award": k, "year": y, "outcome": e["outcome"]})
    # The FIFA Ballon d'Or years also appear in the Ballon d'Or line; when a page lists them only
    # there (Ronaldo), take them from the Ballon d'Or wins so the FIFA view is complete.
    for y in bd_page:
        if 2010 <= y <= 2015 and y not in fifa["fifa_ballon_dor"]:
            fifa["fifa_ballon_dor"].append(y)
    for k in fifa:
        fifa[k] = sorted(set(fifa[k]))
    indiv["fifa_world_player_of_the_year"] = {"wins": len(fifa["fifa_world_player_of_the_year"]), "years": fifa["fifa_world_player_of_the_year"]}
    indiv["fifa_ballon_dor_2010_2015"] = {"wins": len(fifa["fifa_ballon_dor"]), "years": fifa["fifa_ballon_dor"]}
    indiv["the_best_fifa_mens_player"] = {"wins": len(fifa["the_best_fifa_mens_player"]), "years": fifa["the_best_fifa_mens_player"]}
    indiv["fifa_best_player_award_total"] = {
        "wins": sum(len(v) for v in fifa.values()),
        "note": "FIFA World Player of the Year (1991–2009) + FIFA Ballon d'Or (2010–15, merged with the Ballon d'Or) + The Best FIFA Men's Player (2016–)."}
    indiv["fifa_award_podium_finishes"] = fifa_other
    for k, art in (("fifa_world_player_of_the_year", "fifa_wpoty"), ("fifa_ballon_dor", "fifa_ballon_dor"), ("the_best_fifa_mens_player", "the_best")):
        lst = lists[art].get(tgt)
        ref = lst["winner"] if lst else []
        if fifa[k] != ref:
            notes.append(f"{k}: player page {fifa[k]} vs list article {ref}.")

    # European Golden Shoe
    gs = []
    for e, rec in win_entries("european_golden_shoe"):
        season = year_to_season(e["season"])
        co = [DISPLAY.get(x, x) for x in GOLDEN_SHOE_WINNERS.get(season, []) if x != tgt]
        gs.append({"as_listed": e["season"], "season": season,
                   "shared": bool(e.get("shared")) or bool(co), "shared_with_per_list": co})
    gs_list = lists["golden_shoe"].get(tgt, [])
    indiv["european_golden_shoe"] = {"wins": len(gs), "seasons": [g["season"] for g in gs], "detail": gs, "source": src}
    if sorted(g["season"] for g in gs) != sorted(gs_list):
        notes.append(f"Golden Shoe seasons differ: player page {[g['season'] for g in gs]} vs European_Golden_Shoe list {gs_list}.")

    # League top scorer
    lts, lts_seen = [], set()
    for e, rec in win_entries("league_top_scorer"):
        m = rec["meta"]
        season = e["season"]
        if m["league"] in EUROPEAN_SEASON_LEAGUES and re.fullmatch(r"\d{4}", season):
            season = year_to_season(season)
        key = (m["league"], season)
        if key in lts_seen:
            continue
        lts_seen.add(key)
        lts.append(OrderedDict([("league", m["league"]), ("country", m["country"]), ("season", season),
                                ("as_listed", e["season"]),
                                ("award_as_listed", rec["label"]), ("shared", bool(e.get("shared")) or bool(re.search(r"joint|shared|tied", e.get("note") or "", re.I)))]))
    indiv["league_top_scorer"] = lts
    leagues = OrderedDict()
    for x in lts:
        leagues.setdefault(x["league"], {"country": x["country"], "count": 0, "seasons": []})
        leagues[x["league"]]["count"] += 1
        leagues[x["league"]]["seasons"].append(x["season"])
    indiv["league_top_scorer_by_league"] = leagues
    other_ts = []
    for rec in ind.get("other_top_scorer", []):
        other_ts.append({"award": rec["label"], "years": [e["season"] for e in rec["entries"] if e["outcome"] == "winner"]})
    indiv["other_top_scorer_awards_not_counted"] = other_ts

    # UCL top scorer
    uts = [year_to_season(e["season"]) for e, _ in win_entries("ucl_top_scorer")]
    uts_list = lists["ucl_season"].get(tgt, [])
    indiv["ucl_top_scorer"] = {"count": len(uts_list) if uts_list else len(uts),
                               "seasons": [x["season"] for x in uts_list] if uts_list else uts,
                               "shared_seasons": [x["season"] for x in uts_list if x["shared"]],
                               "source": "https://en.wikipedia.org/wiki/List_of_UEFA_Champions_League_top_scorers#Top_scorers_by_season (qualifying goals excluded)",
                               "player_page_lists": uts}
    if sorted(uts) != sorted(x["season"] for x in uts_list):
        notes.append(f"UCL top-scorer seasons differ: player page {uts} vs season list {[x['season'] for x in uts_list]}.")

    # World Cup awards
    wc_ball, wc_ball_retro = [], []
    for e, _ in win_entries("wc_golden_ball"):
        y = first_year(e["season"])
        (wc_ball if y >= 1982 else wc_ball_retro).append(y)
    gb_off = lists["wc_ball"]
    for y in wc_ball:
        if gb_off.get(y, [None])[0] != tgt:
            notes.append(f"World Cup Golden Ball {y} not confirmed by FIFA_World_Cup_awards official table.")
    wc_boot, wc_boot_pre = [], []
    for e, _ in win_entries("wc_golden_boot"):
        y = first_year(e["season"])
        (wc_boot if y >= 1982 else wc_boot_pre).append(y)
        if tgt not in lists["wc_scorers"].get(y, []):
            notes.append(f"World Cup Golden Boot/top scorer {y} not confirmed by FIFA_World_Cup_awards Golden Boot table.")
    other_wc = [{"award": rec["label"], "years": [e["season"] for e in rec["entries"]]} for rec in ind.get("wc_other_award", [])]
    indiv["world_cup_golden_ball"] = {"official_wins": len(wc_ball), "years": wc_ball,
                                      "retrospective_pre_1982": wc_ball_retro,
                                      "note": "Golden Ball officially awarded since 1982; earlier years are retrospective selections (not counted in official_wins)."}
    indiv["world_cup_golden_boot"] = {"wins": len(wc_boot) + len(wc_boot_pre), "years": sorted(wc_boot + wc_boot_pre),
                                      "pre_1982_top_scorer_years": wc_boot_pre,
                                      "note": "Award formally introduced in 1982; pre-1982 entries are tournament top-scorer recognitions."}
    indiv["world_cup_silver_bronze_awards"] = other_wc

    # Continental tournament top scorer
    cts = []
    tables = {"UEFA European Championship": ("euro_scorers", "https://en.wikipedia.org/wiki/UEFA_European_Championship_awards#Top_goalscorer"),
              "Copa América / South American Championship": ("copa_scorers", "https://en.wikipedia.org/wiki/Copa_Am%C3%A9rica_awards#Golden_Boot")}
    for e, rec in win_entries("continental_top_scorer"):
        comp = rec["meta"]["competition"]
        y = first_year(e["season"])
        listed = edition_with(lists[tables[comp][0]].get(y, []), tgt)
        cts.append(OrderedDict([("competition", comp), ("year", y),
                                ("shared", bool(e.get("shared")) or len(listed) > 1),
                                ("co_top_scorers_in_list", sorted(DISPLAY.get(x, x) for x in listed - {tgt})),
                                ("award_as_listed", rec["label"]), ("source", src)]))
        if tgt not in listed:
            notes.append(f"{comp} top scorer {y} (player page) not found in the awards list article.")
    for comp, (lk, url) in tables.items():
        for y, editions in sorted(lists[lk].items()):
            ps = edition_with(editions, tgt)
            if ps and not any(c["competition"] == comp and c["year"] == y for c in cts):
                co = sorted(DISPLAY.get(x, x) for x in ps - {tgt})
                cts.append(OrderedDict([("competition", comp), ("year", y), ("shared", len(ps) > 1),
                                        ("co_top_scorers_in_list", co),
                                        ("award_as_listed", None), ("source", url)]))
                notes.append(f"{comp} top scorer {y} comes from the awards list article ({url}); it is not in the "
                             f"player's Honours section" + (f" (shared with {', '.join(co)})." if co else "."))
    indiv["continental_tournament_top_scorer"] = cts
    nlts = [{"year": e["season"], "shared": bool(e.get("shared")), "award_as_listed": rec["label"]}
            for e, rec in win_entries("nations_league_top_scorer")]
    indiv["nations_league_top_scorer"] = nlts

    # ---------------------------------------------------------------- UCL career totals
    ucl_titles = team["european_cup_ucl"]["count"]
    al = lists["ucl_alltime"].get(tgt)
    if al:
        ucl = OrderedDict([("goals", al["goals"]), ("apps", al["apps"]), ("titles", ucl_titles),
                           ("apps_include_qualifiers", False),
                           ("source", "https://en.wikipedia.org/wiki/List_of_UEFA_Champions_League_top_scorers#All-time_top_scorers "
                                      "(table 'does not include goals scored in the qualification stage'; updated 21 October 2026)"),
                           ("years", al["years"]), ("clubs", al["clubs"])])
    elif pid in UCL_FALLBACK:
        fb = UCL_FALLBACK[pid]
        ucl = OrderedDict([("goals", fb["goals"]), ("apps", fb["apps"]), ("titles", ucl_titles),
                           ("apps_include_qualifiers", fb["apps_include_qualifiers"]), ("source", fb["source"])])
        if fb.get("wiki_efn"):
            r = parse_career_stats_european_cup(text, fb["wiki_efn"])
            if r:
                ucl["wikipedia_career_stats_crosscheck"] = {"apps": r[0], "goals": r[1], "per_season": r[2]}
    else:
        ucl = OrderedDict([("goals", None), ("apps", None), ("titles", ucl_titles), ("source", None)])
        notes.append("UCL goals/apps not found in any source consulted.")
    mw = lists["ucl_most_wins"].get(tgt)
    if mw is not None:
        ucl["titles_crosscheck_records_article"] = mw
        if mw != ucl_titles:
            notes.append(f"UCL titles: honours list gives {ucl_titles}, records article 'Most wins' table gives {mw}.")

    # ---------------------------------------------------------------- derived metrics & notes
    bare = []
    if any(re.fullmatch(r"\d{4}", g["as_listed"]) for g in gs):
        bare.append("European Golden Shoe")
    if any(re.fullmatch(r"\d{4}", e["season"]) for e, _ in win_entries("ucl_top_scorer")):
        bare.append("European Cup top scorer")
    if any(x["as_listed"] != x["season"] for x in lts):
        bare.append("league top scorer")
    if bare:
        notes.append("The player page gives season-ending years for: " + ", ".join(bare) + "; normalised to seasons "
                     "(e.g. 1970 -> 1969–70). Golden Shoe and European Cup top-scorer seasons so normalised match the list articles.")
    distinct_leagues = len(leagues)
    distinct_countries = len(by_country)
    nc = team["not_counted"]
    if nc["state_or_provincial_league_titles"]:
        notes.append("Not counted as top-flight league titles: " + "; ".join(
            f"{g['competition']} ×{g['count']} ({', '.join(g['seasons'])})" for g in nc["state_or_provincial_league_titles"]) + ".")
    if nc["league_regular_season_titles"]:
        incl = len(set(list(by_country.keys()) + ["United States"]))
        notes.append("MLS Supporters' Shield (best regular-season record: " + ", ".join(
            s for g in nc["league_regular_season_titles"] for s in g["seasons"]) + ") listed separately, not counted as a "
            "league title; the MLS Cup (playoff championship) is what counts as the US league title."
            + (f" If the Shield were counted, distinct_countries_league_title would be {incl}." if incl != len(by_country) else ""))
    if nc["lower_tier_league_titles"]:
        notes.append("Lower-tier league titles excluded: " + "; ".join(f"{g['competition']} ({', '.join(g['seasons'])})" for g in nc["lower_tier_league_titles"]) + ".")
    if nc["youth"]:
        notes.append("Youth titles excluded: " + "; ".join(f"{g['competition']} ({', '.join(g['teams'])}) {', '.join(g['seasons'])}" for g in nc["youth"]) + ".")
    if wc_ball_retro:
        notes.append(f"World Cup 'Golden Ball' {wc_ball_retro} listed on the player page predates the official award (1982); treated as retrospective.")
    if other_ts:
        pass
    if unclassified_team:
        notes.append(f"{len(unclassified_team)} team-honour line(s) left unclassified (see team_honours.unclassified).")

    player = OrderedDict([
        ("id", pid), ("name", name), ("wiki_title", title),
        ("source_url", f"https://en.wikipedia.org/wiki/{title}"),
        ("fetched_at", meta.get("fetched_at")),
        ("source_last_modified", meta.get("last_modified")),
        ("honours_section_line", start_line),
        ("team_honours", team),
        ("individual_honours", indiv),
        ("ucl", ucl),
        ("distinct_leagues_top_scorer", distinct_leagues),
        ("distinct_countries_league_title", distinct_countries),
        ("notes", notes),
    ])
    return player, review


def build_lists():
    L = {}
    t, _ = load_page(LIST_PAGES["ballon_dor"]); L["ballon_dor"] = parse_ballon_dor_table(t)
    t, _ = load_page(LIST_PAGES["golden_shoe"]); L["golden_shoe"] = parse_golden_shoe(t)
    t, _ = load_page(LIST_PAGES["ucl_scorers"]); L["ucl_alltime"] = parse_ucl_alltime(t); L["ucl_season"] = parse_ucl_season_top_scorers(t)
    t, _ = load_page(LIST_PAGES["ucl_records"]); L["ucl_most_wins"] = parse_ucl_most_wins(t)
    t, _ = load_page(LIST_PAGES["fifa_wpoty"]); L["fifa_wpoty"] = parse_wins_by_player(t)
    t, _ = load_page(LIST_PAGES["fifa_ballon_dor"]); L["fifa_ballon_dor"] = parse_wins_by_player(t)
    t, _ = load_page(LIST_PAGES["the_best"]); L["the_best"] = parse_wins_by_player(t)
    t, _ = load_page(LIST_PAGES["wc_awards"]); L["wc_ball"] = parse_wc_golden_ball_official(t); L["wc_scorers"] = parse_wc_top_scorers(t)
    t, _ = load_page(LIST_PAGES["copa_awards"]); L["copa_scorers"] = parse_continental_top_scorers(t, r"^==Golden Boot==", r"^==Golden Glove==")
    t, _ = load_page(LIST_PAGES["euro_awards"]); L["euro_scorers"] = parse_continental_top_scorers(t, r"^==Top goalscorer==", r"^===Statistics")
    return L


def main():
    lists = build_lists()
    players, all_review = [], []
    for pid, name, title in PLAYERS:
        p, review = extract_player(pid, name, title, lists)
        players.append(p)
        all_review.append((name, review))
    sources = OrderedDict()
    for k, title in LIST_PAGES.items():
        _, meta = load_page(title)
        sources[title] = {"url": f"https://en.wikipedia.org/wiki/{title}", "fetched_at": meta.get("fetched_at"),
                          "last_modified": meta.get("last_modified")}
    doc = OrderedDict([
        ("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("description", "Honours and records of 21 footballers, parsed from English Wikipedia 'Honours' sections "
                        "(raw wikitext) and cross-checked against Wikipedia list articles and RSSSF. Only titles/awards "
                        "listed as won are counted; runner-up/third-place finishes, youth, state, lower-tier, managerial "
                        "and retrospective/honorary items are listed separately and not counted."),
        ("definitions", OrderedDict([
            ("league_titles", "Top-flight national league championships. MLS Cup and NASL Soccer Bowl count as the US league title; "
                              "the MLS Supporters' Shield, Brazilian state championships (Paulista, Carioca, Mineiro, Gaúcho), "
                              "the colonial Mozambique provincial championship and lower divisions are not counted."),
            ("distinct_countries_league_title", "Number of different countries in league_titles.by_country."),
            ("distinct_leagues_top_scorer", "Number of different top-flight leagues in which the player was the league's "
                                            "top scorer (Pichichi, Premier League Golden Boot, Capocannoniere, Torjägerkanone, etc.); "
                                            "state championships, cups and second tiers excluded."),
            ("ballon_dor", "France Football Ballon d'Or incl. the 2010–15 FIFA Ballon d'Or; podiums from the Ballon d'Or article winners table."),
            ("ucl", "European Cup/UEFA Champions League proper (qualifying rounds excluded); titles from the player's honours list."),
        ])),
        ("caveats", [
            "Everything reflects English Wikipedia as fetched on the dates in fetched_at (2026-10-30). Recent items "
            "(2025–26 season titles, 2026 FIFA World Cup awards, 2026 Ballon d'Or) were cross-checked only against other "
            "Wikipedia articles fetched the same day (see each player's notes) and a small number of web searches "
            "recorded in the agent report; re-verify before publication.",
            "Counts include every competition in each category without judging which trophies are 'major'; minor, "
            "regional, unofficial, youth and state-level items are listed under team_honours.not_counted.",
        ]),
        ("sources", sources),
        ("players", players),
    ])
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"wrote {OUT} ({len(players)} players)")
    if REVIEW:
        for name, review in all_review:
            print("=" * 100)
            print(name)
            for kind, block, cat, comp, ents, line in review:
                if kind == "IND" and cat in (None, "ignore"):
                    continue
                print(f"  {kind:4} {str(block)[:22]:22} {str(cat):26} {str(comp)[:34]:34} {ents}")


if __name__ == "__main__":
    main()
