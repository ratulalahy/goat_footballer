"""Derive comparable career metrics and age curves from career_seasons.json (Wikipedia tables).

Rules (see METHODOLOGY.md):
- Senior first-team official matches only: reserve/B-team rows and indoor-league rows are dropped.
- Official goals = first-team club goals (all competitions) + full international goals.
- Age curves place each club season's goals at the season's end (31 May for split seasons,
  30 Nov for calendar-year seasons) and each year's international goals at 1 July.
  Seasons still in progress are placed at the data cut-off date.
"""
import json, re, sys
from datetime import date
from collections import defaultdict

AS_OF = date(2026, 10, 30)
INDOOR = re.compile(r"Buffalo Stallions|MISL|indoor", re.I)

def season_end(label):
    s = label.replace("—", "–").replace("-", "–")
    years = [int(y) for y in re.findall(r"(1[89]\d\d|20\d\d)", s)]
    m = re.search(r"(\d{4})\s*–\s*(\d{2})(?!\d)", s)
    if m:  # e.g. 2002–03
        end_y = int(m.group(1)[:2] + m.group(2))
        if end_y < int(m.group(1)):
            end_y += 100
        d = date(max([end_y] + years), 5, 31)
    elif re.search(r"\d{4}\s*–\s*\d{4}", s):  # e.g. 1999–2000
        d = date(max(years), 5, 31)
    elif years:  # calendar-year season
        d = date(max(years), 11, 30)
    else:
        raise ValueError(f"unparseable season label: {label!r}")
    return min(d, AS_OF)

def age_at(birth, d):
    return (d - birth).days / 365.2425

def first_team_rows(p):
    return [s for s in p["club_seasons"] if not s.get("reserve_team") and not INDOOR.search(s.get("club", "") + " " + str(s.get("league", "")))]

def compute(player):
    b = date.fromisoformat(player["birth_date"])
    rows = first_team_rows(player)
    club_goals = sum(s.get("goals") or 0 for s in rows)
    club_apps = sum(s.get("apps") or 0 for s in rows)
    intl_goals = sum(y.get("goals") or 0 for y in player["intl_years"])
    intl_apps = sum(y.get("apps") or 0 for y in player["intl_years"])
    events = []
    for s in rows:
        events.append((season_end(s["season"]), s.get("goals") or 0))
    for y in player["intl_years"]:
        events.append((min(date(int(y["year"]), 7, 1), AS_OF), y.get("goals") or 0))
    events.sort()
    curve, cum = [], 0
    for d, g in events:
        cum += g
        a = round(age_at(b, d), 3)
        if curve and abs(curve[-1][0] - a) < 1e-6:
            curve[-1][1] = cum
        else:
            curve.append([a, cum])
    from30 = sum(g for d, g in events if age_at(b, d) >= 30)
    from35 = sum(g for d, g in events if age_at(b, d) >= 35)
    from40 = sum(g for d, g in events if age_at(b, d) >= 40)
    per_club = defaultdict(int)
    for s in rows:
        per_club[re.sub(r"\s*\(loan\)", "", s["club"]).strip()] += s.get("goals") or 0
    per_season = defaultdict(int)
    for s in rows:
        per_season[s["season"]] += s.get("goals") or 0
    seasons30 = sorted(k for k, v in per_season.items() if v >= 30)
    return {
        "club_goals": club_goals, "club_apps": club_apps, "intl_goals": intl_goals, "intl_apps": intl_apps,
        "goals": club_goals + intl_goals, "apps": club_apps + intl_apps,
        "gpg": round((club_goals + intl_goals) / (club_apps + intl_apps), 3),
        "from30": from30, "from35": from35, "from40": from40,
        "clubs100": sorted(c for c, g in per_club.items() if g >= 100),
        "per_club": dict(per_club),
        "club_seasons30": seasons30,
        "age_curve": curve,
        "dropped_rows": [(s["club"], s["season"], s.get("apps"), s.get("goals")) for s in player["club_seasons"] if s not in rows],
    }

if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    for p in d["players"]:
        c = compute(p)
        print(f"{p['id']:16s} goals {c['goals']:4d} in {c['apps']:4d} ({c['gpg']:.2f}) | 30+ {c['from30']:3d} | 35+ {c['from35']:3d} | clubs100 {c['clubs100']} | 30-goal club seasons {len(c['club_seasons30'])} | last age {c['age_curve'][-1][0]:.1f} | dropped {c['dropped_rows']}")
