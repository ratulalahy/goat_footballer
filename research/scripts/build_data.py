"""Build site/data/data.js (window.FG) from the research files.

Inputs (research/):
  h2h_metrics.json        Ronaldo v Messi, computed from messivsronaldo.app match histories (compute_h2h.py)
  mvr/*.json              messivsronaldo.app page data (FIFA-ranking and UEFA-ranking splits, honours)
  career_seasons.json     Wikipedia career tables for every player (extract_career_stats.py)
  honours.json            Wikipedia honours, Champions League totals (extract_honours.py)
  leaderboards.json       verified all-time leaderboards (recent_and_leaderboards.md)
Usage: python3 build_data.py <research_dir> <out_js>
"""
import csv, json, os, re, sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
import peer_metrics  # noqa: E402

AS_OF_LABEL = "29 October 2026"

PLAYERS = [  # id, full name, short, nation, role
    ("ronaldo", "Cristiano Ronaldo", "Ronaldo", "Portugal", "cr"),
    ("messi", "Lionel Messi", "Messi", "Argentina", "pe"),
    ("pele", "Pelé", "Pelé", "Brazil", "pe"),
    ("maradona", "Diego Maradona", "Maradona", "Argentina", "pe"),
    ("distefano", "Alfredo Di Stéfano", "Di Stéfano", "Argentina / Spain", "pe"),
    ("puskas", "Ferenc Puskás", "Puskás", "Hungary / Spain", "pe"),
    ("eusebio", "Eusébio", "Eusébio", "Portugal", "pe"),
    ("muller", "Gerd Müller", "G. Müller", "West Germany", "pe"),
    ("cruyff", "Johan Cruyff", "Cruyff", "Netherlands", "pe"),
    ("romario", "Romário", "Romário", "Brazil", "pe"),
    ("ronaldo_nazario", "Ronaldo Nazário", "R. Nazário", "Brazil", "pe"),
    ("zidane", "Zinedine Zidane", "Zidane", "France", "pe"),
    ("henry", "Thierry Henry", "Henry", "France", "pe"),
    ("ibrahimovic", "Zlatan Ibrahimović", "Ibrahimović", "Sweden", "pe"),
    ("lewandowski", "Robert Lewandowski", "Lewandowski", "Poland", "pe"),
    ("suarez", "Luis Suárez", "Suárez", "Uruguay", "pe"),
    ("benzema", "Karim Benzema", "Benzema", "France", "pe"),
    ("neymar", "Neymar", "Neymar", "Brazil", "pe"),
    ("kane", "Harry Kane", "Kane", "England", "pe"),
    ("mbappe", "Kylian Mbappé", "Mbappé", "France", "pe"),
    ("haaland", "Erling Haaland", "Haaland", "Norway", "pe"),
]

FAMILIES = [
    {"id": "volume", "label": "Goals", "short": "Goals"},
    {"id": "stage", "label": "Big stage", "short": "Big stage"},
    {"id": "intl", "label": "International", "short": "Intl"},
    {"id": "longevity", "label": "Longevity", "short": "Longevity"},
    {"id": "range", "label": "Range", "short": "Range"},
]


def load(path):
    with open(path) as fh:
        return json.load(fh)


def mvr_rows(research, page, key):
    d = load(os.path.join(research, "mvr", page))["result"]["data"][key]["edges"]
    return {e["node"]["competition"]: e["node"] for e in d}


def n(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def build_h2h(research):
    hm = load(os.path.join(research, "h2h_metrics.json"))["players"]
    R, M = hm["ronaldo"], hm["messi"]
    keep = ["birth_date", "first_match", "last_match", "career", "club", "intl", "intl_competitive", "intl_friendly",
            "from_age_30", "from_age_35", "from_age_40", "by_age"]
    comps = ["World Cup", "UEFA European Championships", "Copa America", "Champions League"]
    slim = {}
    for who, P in (("ronaldo", R), ("messi", M)):
        s = {k: P[k] for k in keep}
        s["by_competition"] = {c: P["by_competition"][c] for c in comps if c in P["by_competition"]}
        slim[who] = s

    # Longevity, like for like
    def goals_between(who, lo, hi_excl):
        return sum(v["goals"] for a, v in hm[who]["by_age"].items() if lo <= int(a) < hi_excl)
    m_last = date.fromisoformat(M["last_match"])
    m_birth = date.fromisoformat(M["birth_date"])
    r_birth = date.fromisoformat(R["birth_date"])
    m_age_days = (m_last - m_birth).days
    r_rows = list(csv.DictReader(open(os.path.join(research, "mvr", "ronaldo_matches.csv"))))
    r_at = sum(n(r["goals"]) for r in r_rows if (date.fromisoformat(r["iso_date"]) - r_birth).days <= m_age_days)
    yrs = m_last.year - m_birth.year - ((m_last.month, m_last.day) < (m_birth.month, m_birth.day))
    months = (m_last.month - m_birth.month - (m_last.day < m_birth.day)) % 12
    longevity = {
        "messiNow": M["career"]["goals"], "ronaldoAtMessiAge": r_at,
        "messiAgeLabel": f"{yrs} years and {months} months",
        "r30to38": goals_between("ronaldo", 30, 39), "m30to38": goals_between("messi", 30, 39),
        "rFrom40": R["from_age_40"]["goals"],
    }

    # Champions League
    honours = {e["node"]["honour"]: e["node"] for e in load(os.path.join(research, "mvr", "honours-and-achievements.json"))["result"]["data"]["allSheetHonours"]["edges"]}
    uefa = {who: mvr_rows(research, "all-time-stats_uefa-club-rankings.json", key) for who, key in (("r", "allSheetRonaldoUefaTopXStats"), ("m", "allSheetMessiUefaTopXStats"))}
    ucl = {}
    for k, P, hk in (("r", R, "rcount"), ("m", M, "mcount")):
        ucl[k] = {
            "rounds": {rd: {"goals": P["ucl_by_round"][rd]["goals"], "apps": P["ucl_by_round"][rd]["apps"]} for rd in ("Group", "R16", "QF", "SF", "F")},
            "qfsf": {"goals": P["ucl_qf_sf_f"]["goals"], "apps": P["ucl_qf_sf_f"]["apps"]},
            "knockout": {"goals": P["ucl_knockout"]["goals"], "apps": P["ucl_knockout"]["apps"]},
            "total": {"goals": P["ucl"]["goals"], "apps": P["ucl"]["apps"]},
            "titles": n(honours["Champions League"][hk]),
            "topScorer": n(honours["Champions League Top Scorer"][hk]),
            "vsTop10": {"goals": n(uefa[k]["vs Top 10"]["goals"]), "apps": n(uefa[k]["vs Top 10"]["apps"])},
        }

    # International: competitive goals by opponent FIFA ranking band
    fifa = {who: mvr_rows(research, "international-stats_fifa-rankings.json", key) for who, key in (("r", "allSheetRonaldoIntTopXStats"), ("m", "allSheetMessiIntTopXStats"))}

    def cum(k, label):
        row = fifa[k].get(label, {})
        return n(row.get("goals")), n(row.get("apps"))

    def band_vals(k):
        t10, t20, t50 = cum(k, "vs Top 10 Competitive"), cum(k, "vs Top 20 Competitive"), cum(k, "vs Top 50 Competitive")
        b5175, b76100 = cum(k, "vs 51-75 Competitive"), cum(k, "vs 76-100 Competitive")
        rest = [cum(k, f"vs {x} Competitive") for x in ("101-150", "151-200", "201-250")]
        return [t10, (t20[0] - t10[0], t20[1] - t10[1]), (t50[0] - t20[0], t50[1] - t20[1]),
                (b5175[0] + b76100[0], b5175[1] + b76100[1]), (sum(x[0] for x in rest), sum(x[1] for x in rest))]
    rb, mb = band_vals("r"), band_vals("m")
    labels = ["Top 10", "11–20", "21–50", "51–100", "101 and below"]
    bands = [{"label": l, "r": rb[i][0], "rApps": rb[i][1], "m": mb[i][0], "mApps": mb[i][1]} for i, l in enumerate(labels)]
    assert sum(b["r"] for b in bands) == R["intl_competitive"]["goals"], "Ronaldo FIFA bands do not sum to competitive goals"
    assert sum(b["m"] for b in bands) == M["intl_competitive"]["goals"], "Messi FIFA bands do not sum to competitive goals"

    # Tournaments
    RESULTS = {
        ("r", "UEFA European Championships", 2004): "Runners-up", ("r", "World Cup", 2006): "Fourth place",
        ("r", "UEFA European Championships", 2008): "Quarter-finals", ("r", "World Cup", 2010): "Round of 16",
        ("r", "UEFA European Championships", 2012): "Semi-finals", ("r", "World Cup", 2014): "Group stage",
        ("r", "UEFA European Championships", 2016): "Winners", ("r", "World Cup", 2018): "Round of 16",
        ("r", "UEFA European Championships", 2021): "Round of 16", ("r", "World Cup", 2022): "Quarter-finals",
        ("r", "UEFA European Championships", 2024): "Quarter-finals", ("r", "World Cup", 2026): "Round of 16 (lost 1–0 to Spain)",
        ("m", "World Cup", 2006): "Quarter-finals", ("m", "Copa America", 2007): "Runners-up", ("m", "World Cup", 2010): "Quarter-finals",
        ("m", "Copa America", 2011): "Quarter-finals", ("m", "World Cup", 2014): "Runners-up", ("m", "Copa America", 2015): "Runners-up",
        ("m", "Copa America", 2016): "Runners-up", ("m", "World Cup", 2018): "Round of 16", ("m", "Copa America", 2019): "Third place",
        ("m", "Copa America", 2021): "Winners", ("m", "World Cup", 2022): "Winners", ("m", "Copa America", 2024): "Winners",
        ("m", "World Cup", 2026): "Runners-up (lost 1–0 to Spain after extra time)",
    }
    tourn = {}
    for k, P in (("r", R), ("m", M)):
        out = []
        for t in P["tournaments"]:
            if t["comp"] not in ("World Cup", "UEFA European Championships", "Copa America"):
                continue
            nm = {"World Cup": "World Cup", "UEFA European Championships": "Euro", "Copa America": "Copa América"}[t["comp"]]
            label_year = 2020 if (nm == "Euro" and t["year"] == 2021) else t["year"]
            out.append({"name": f"{nm} {label_year}" + (" (played 2021)" if label_year != t["year"] else ""), "year": t["year"],
                        "type": "wc" if t["comp"] == "World Cup" else "cont", "goals": t["goals"], "apps": t["apps"],
                        "result": RESULTS.get((k, t["comp"], t["year"]))})
        tourn[k] = out
    wc_scored = {k: sum(1 for t in tourn[k] if t["type"] == "wc" and t["goals"] > 0) for k in tourn}
    comp10 = {k: cum(k, "vs Top 10 Competitive") for k in ("r", "m")}
    intl = {"r": {"compTop10": comp10["r"][0], "compTop10Apps": comp10["r"][1], "wcScored": wc_scored["r"]},
            "m": {"compTop10": comp10["m"][0], "compTop10Apps": comp10["m"][1], "wcScored": wc_scored["m"]},
            "bands": bands}

    # Goal types
    def gt(P, strong, weak):
        c = P["career"]
        return {"strong": c[strong], "weak": c[weak], "head": c["head"], "other": c["other"], "total": c["goals"],
                "pens": c["pens"], "fk": c["freeKicks"], "nonDominantShare": round((c[weak] + c["head"]) / c["goals"], 4)}
    goal_types = {"r": gt(R, "right", "left"), "m": gt(M, "left", "right")}
    for k, P in (("r", R), ("m", M)):
        g = goal_types[k]
        assert g["strong"] + g["weak"] + g["head"] + g["other"] == g["total"], f"goal types do not sum for {k}"
    pens = {}
    for k, P in (("r", R), ("m", M)):
        sc, ms = P["career"]["pens"], P["career"]["pensMissed"]
        pens[k] = {"scored": sc, "taken": sc + ms, "rate": round(sc / (sc + ms), 4)}

    YEARS = {"Sporting CP": "2002–03", "Manchester United": "2003–09, 2021–22", "Real Madrid": "2009–18", "Juventus": "2018–21",
             "Al Nassr": "2023–", "Barcelona": "2004–21", "Paris Saint-Germain": "2021–23", "Inter Miami": "2023–"}
    clubs = []
    for who, P, order in (("ronaldo", R, ["Sporting CP", "Manchester United", "Real Madrid", "Juventus", "Al Nassr"]),
                          ("messi", M, ["Barcelona", "Paris Saint-Germain", "Inter Miami"])):
        for c in order:
            clubs.append({"player": who, "club": c, "years": YEARS[c], "goals": P["clubs"][c]["goals"], "apps": P["clubs"][c]["apps"]})

    h2h = {"ronaldo": slim["ronaldo"], "messi": slim["messi"], "longevity": longevity, "ucl": ucl,
           "decisive": {"r": R["decisive"], "m": M["decisive"]}, "intl": intl, "tournaments": tourn,
           "goalTypes": goal_types, "perfectHatTricks": {"r": R["perfect_hat_tricks"], "m": M["perfect_hat_tricks"]},
           "pens": pens, "clubs": clubs,
           "range": {"opponents": {"r": R["distinct_opponents_scored_against"], "m": M["distinct_opponents_scored_against"]},
                     "competitions": {"r": R["distinct_competitions_scored_in"], "m": M["distinct_competitions_scored_in"]}},
           "europeOnly": {"r": R["career"]["goals"] - R["clubs"]["Al Nassr"]["goals"], "m": M["career"]["goals"] - M["clubs"]["Inter Miami"]["goals"]},
           "honoursMvr": {k: {"r": n(v["rcount"]), "m": n(v["mcount"])} for k, v in honours.items() if v.get("rcount") not in (None, "", "-") or v.get("mcount") not in (None, "", "-")}}
    return h2h, hm



METRICS = [
    # id, label, short, family, desc, better, dec, defaultW
    ("goals", "Official goals", "Official goals", "volume", "Senior first-team club goals plus full international goals", "high", 0, 1),
    ("gpg", "Goals per game", "Goals/game", "volume", "Official goals divided by official matches", "high", 2, 0),
    ("uclGoals", "European Cup and Champions League goals", "UCL goals", "stage", "Europe's top club competition since 1955, qualifiers excluded", "high", 0, 1),
    ("uclTitles", "European Cup and Champions League titles", "UCL titles", "stage", "Wins of Europe's top club competition", "high", 0, 1),
    ("uclFinalGoals", "Goals in European Cup and Champions League finals", "Final goals", "stage", "Every final since 1956", "high", 0, 0),
    ("intlGoals", "International goals", "Intl goals", "intl", "Goals in full senior internationals", "high", 0, 1),
    ("caps", "International caps", "Caps", "intl", "Full senior international appearances", "high", 0, 0),
    ("wcScored", "World Cups with a goal", "World Cups scored", "intl", "Different World Cup tournaments in which he scored", "high", 0, 1),
    ("goals30", "Goals from age 30", "Goals 30+", "longevity", "Ronaldo and Messi exact to the day; others from season totals", "high", 0, 1),
    ("goals35", "Goals from age 35", "Goals 35+", "longevity", "Ronaldo and Messi exact to the day; others from season totals", "high", 0, 0),
    ("seasons30", "Club seasons with 30+ goals", "30-goal seasons", "longevity", "Club seasons with at least 30 official goals", "high", 0, 1),
    ("apps", "Official matches", "Matches", "longevity", "Senior first-team club and full international matches", "high", 0, 0),
    ("leaguesTop", "Leagues where he was top scorer", "Leagues topped", "range", "Different top-flight national leagues in which he won the scoring title", "high", 0, 1),
    ("clubs100", "Clubs with 100+ goals", "100-goal clubs", "range", "Clubs for which he scored at least 100 official goals", "high", 0, 1),
    ("countriesTitle", "Countries with a league title", "Title countries", "range", "Different countries in which he won the top-flight league", "high", 0, 0),
    ("leaguesScored", "Countries whose top league he scored in", "Leagues scored in", "range", "Top-flight national leagues with at least one league goal", "high", 0, 0),
]

PRESETS = [  # the core case, one preset per criterion family, and everything
    ("core", "Core criteria", None),
    ("stage", "Big stage", {"uclGoals": 1, "uclTitles": 1, "uclFinalGoals": 1}),
    ("intl", "International", {"intlGoals": 1, "caps": 1, "wcScored": 1}),
    ("longevity", "Longevity", {"goals30": 1, "goals35": 1, "seasons30": 1, "apps": 1}),
    ("range", "Range", {"leaguesTop": 1, "clubs100": 1, "countriesTitle": 1, "leaguesScored": 1}),
    ("all", "Everything", "all"),
]

# World Cup tournaments in which each player scored (FIFA tournament records; 2026 from FIFA match reports and player articles)
WC_SCORED = {
    "ronaldo": [2006, 2010, 2014, 2018, 2022, 2026], "messi": [2006, 2014, 2018, 2022, 2026],
    "pele": [1958, 1962, 1966, 1970], "neymar": [2014, 2018, 2022, 2026],
    "maradona": [1982, 1986, 1994], "ronaldo_nazario": [1998, 2002, 2006], "suarez": [2010, 2014, 2018],
    "mbappe": [2018, 2022, 2026], "kane": [2018, 2022, 2026],
    "muller": [1970, 1974], "zidane": [1998, 2006], "henry": [1998, 2006],
    "puskas": [1954], "eusebio": [1966], "cruyff": [1974], "romario": [1994], "benzema": [2014],
    "lewandowski": [2022], "haaland": [2026], "ibrahimovic": [], "distefano": [],
}
WC_NOTES = {"ibrahimovic": "Played the 2002 and 2006 World Cups without scoring", "distefano": "Never played at a World Cup",
            "lewandowski": "Poland lost the 2026 play-off final to Sweden", "romario": "Also played in 1990 without scoring"}

# Goals in European Cup / Champions League finals (Wikipedia records article; final match reports)
UCL_FINAL_GOALS = {
    "distefano": (7, "Scored in five finals, 1956–1960, three of them in 1960"), "puskas": (7, "Four in 1960, three in 1962"),
    "ronaldo": (4, "2008, 2014 and two in 2017; the record for the Champions League era"), "eusebio": (3, "Two in 1962, one in 1963"),
    "muller": (3, "Two in the 1974 replay, one in 1975"), "messi": (2, "2009 and 2011"), "cruyff": (2, "Both goals in the 1972 final"),
    "zidane": (1, "2002"), "benzema": (1, "2018"), "suarez": (1, "2015"), "neymar": (1, "2015"),
    "henry": (0, "Played the 2006 final"), "lewandowski": (0, "Played the 2013 and 2020 finals"), "kane": (0, "Played the 2019 final"),
    "mbappe": (0, "Played the 2020 final"), "haaland": (0, "Played the 2023 final"), "romario": (0, "Played the 1994 final"),
    "ibrahimovic": (0, "Never reached a final"), "ronaldo_nazario": (0, "Never reached a final"), "maradona": (0, "Never reached a final"),
    "pele": (None, "Never played in the competition"),
}

# Top-flight national leagues, by the name used in the career tables -> country
TOP_FLIGHT = {
    "A-League": "Australia", "Allsvenskan": "Sweden", "Argentine Primera División": "Argentina", "Austrian Bundesliga": "Austria",
    "Bundesliga": "Germany", "Campeonato Profesional": "Colombia", "Division 1": "France", "Ekstraklasa": "Poland", "Eliteserien": "Norway",
    "Eredivisie": "Netherlands", "La Liga": "Spain", "Ligue 1": "France", "MLS": "United States", "Major League Soccer": "United States",
    "Mexican Primera División": "Mexico", "NASL": "United States", "North American Soccer League": "United States",
    "Nemzeti Bajnokság I": "Hungary", "Premier League": "England", "Primeira Divisão": "Portugal", "Primeira Liga": "Portugal",
    "Saudi Pro League": "Saudi Arabia", "Serie A": "Italy", "Série A": "Brazil", "Campeonato Brasileiro Série A": "Brazil",
    "Uruguayan Primera División": "Uruguay",
}
NOT_TOP_FLIGHT = {"2. Amateurliga Schwaben", "ASL", "Bezirksliga Schwaben", "Championship", "II liga", "III liga", "IV liga", "League One",
                  "Moçambola", "Regionalliga Süd", "Segunda División", "Segunda Divisão", "Superettan", "USL 1st"}


def leagues_scored(player):
    countries = set()
    for s in peer_metrics.first_team_rows(player):
        names = []
        if s.get("league") and (s.get("league_goals") or 0) > 0:
            names.append(s["league"])
        for comp, d in (s.get("breakdown") or {}).items():  # tables without a League column (Pelé's Santos)
            if comp in TOP_FLIGHT and (d.get("goals") or 0) > 0:
                names.append(comp)
        for nm in names:
            if nm in TOP_FLIGHT:
                countries.add(TOP_FLIGHT[nm])
            elif nm not in NOT_TOP_FLIGHT:
                raise KeyError(f"unclassified league {nm!r} for {player['id']}")
    return sorted(countries)


def build_values(research, hm):
    cs = load(os.path.join(research, "career_seasons.json"))
    by_id = {p["id"]: p for p in cs["players"]}
    values, notes, curves, derived = {}, {}, {}, {}
    for pid, *_ in PLAYERS:
        c = peer_metrics.compute(by_id[pid])
        derived[pid] = c
        lsc = leagues_scored(by_id[pid])
        wc = WC_SCORED[pid]
        fg, fnote = UCL_FINAL_GOALS[pid]
        v = {"goals": c["goals"], "gpg": round(c["gpg"], 2), "intlGoals": c["intl_goals"], "caps": c["intl_apps"], "apps": c["apps"],
             "wcScored": len(wc), "uclFinalGoals": fg,
             "goals30": c["from30"], "goals35": c["from35"], "goals40": c["from40"], "seasons30": len(c["club_seasons30"]),
             "clubs100": len(c["clubs100"]), "leaguesScored": len(lsc)}
        nt = {"goals": f"{c['club_goals']} club + {c['intl_goals']} international, in {c['apps']} matches",
              "clubs100": ", ".join(c["clubs100"]) or "None", "seasons30": ", ".join(c["club_seasons30"]) or "None",
              "wcScored": (", ".join(str(y) for y in wc) if wc else "None") + (f". {WC_NOTES[pid]}" if pid in WC_NOTES else ""),
              "uclFinalGoals": fnote, "leaguesScored": ", ".join(lsc), "caps": f"{c['intl_goals']} goals in {c['intl_apps']} internationals",
              "apps": f"{c['club_apps']} club + {c['intl_apps']} international"}
        if pid in ("ronaldo", "messi"):
            P = hm[pid]
            v["goals30"], v["goals35"], v["goals40"] = P["from_age_30"]["goals"], P["from_age_35"]["goals"], P["from_age_40"]["goals"]
            nt["goals30"] = "Exact: goals on or after his 30th birthday"
            nt["goals35"] = "Exact: goals on or after his 35th birthday"
            curves[pid] = P["age_curve_monthly"]
            assert c["goals"] == P["career"]["goals"], f"{pid}: Wikipedia ({c['goals']}) and match records ({P['career']['goals']}) disagree"
        else:
            nt["goals30"] = nt["goals35"] = nt["goals40"] = "Estimated from season totals placed at each season's end"
            curves[pid] = c["age_curve"]
        age_now = (date(2026, 10, 30) - date.fromisoformat(by_id[pid]["birth_date"])).days / 365.2425
        for t in (30, 35, 40):
            if age_now < t:
                nt[f"goals{t}"] = f"Has not turned {t} yet"
        for mid, text in TABLE_NOTES.get(pid, {}).items():
            nt[mid] = text
        if c["dropped_rows"]:
            nt["goals"] += ". Excludes " + ", ".join(f"{club} {season}" for club, season, _a, _g in c["dropped_rows"])
        values[pid], notes[pid] = v, nt
    return values, notes, curves, derived, cs


TABLE_NOTES = {  # where Wikipedia's stated totals and its own season rows differ (see career_seasons.json validation_issues)
    "pele": {"goals": "710 club (Santos and New York Cosmos) + 77 for Brazil, from the season rows; the tables' stated club total is 709. Excludes friendlies and exhibition games, which take some counts above 1,200",
             "leaguesTop": "Counts the Taça Brasil, later merged into Brazil's national championship by the CBF; state championships excluded"},
    "puskas": {"intlGoals": "Year rows sum to 83; the table's stated Hungary total is 84"},
    "distefano": {"goals": "Includes Millonarios 1949–52, when Colombia's league played outside FIFA"},
}


def apply_honours(hon, values, notes):
    H = hon_by_id(hon)
    for pid, p in H.items():
        th, ih, u = p["team_honours"], p["individual_honours"], p.get("ucl") or {}
        v, nt = values[pid], notes[pid]
        played_ucl = bool(u.get("apps"))
        v["uclGoals"] = u.get("goals") if played_ucl else None
        v["uclTitles"] = th["european_cup_ucl"]["count"] if played_ucl else None
        if played_ucl:
            nt["uclGoals"] = f"{u['goals']} goals in {u['apps']} games"
            seasons = th["european_cup_ucl"].get("seasons") or []
            nt["uclTitles"] = ", ".join(seasons) if seasons else "No titles"
        else:
            nt["uclGoals"] = nt["uclTitles"] = "Never played in the European Cup or Champions League"
        v["leaguesTop"] = p["distinct_leagues_top_scorer"]
        by_league = ih.get("league_top_scorer_by_league") or {}
        nt.setdefault("leaguesTop", "; ".join(f"{lg} ×{d['count']}" for lg, d in by_league.items()) or "Never a league's top scorer")
        v["countriesTitle"] = p["distinct_countries_league_title"]
        nt["countriesTitle"] = ", ".join(th["league_titles"]["by_country"].keys()) or "None"


def build(research):
    h2h, hm = build_h2h(research)
    values, notes, curves, derived, cs = build_values(research, hm)
    apply_honours(load(os.path.join(research, "honours.json")), values, notes)
    lb = load(os.path.join(research, "leaderboards.json"))
    leaderboards = build_leaderboards(lb)
    hon = load(os.path.join(research, "honours.json"))
    metrics = [{"id": m[0], "label": m[1], "short": m[2], "family": m[3], "desc": m[4], "better": m[5], "dec": m[6], "defaultW": m[7]} for m in METRICS]
    for m in metrics:  # the page's premise: no criterion on which another player's career leads Ronaldo's by design is hidden; record who leads each
        vals = [(pid, values[pid].get(m["id"])) for pid in values if values[pid].get(m["id"]) is not None]
        best = max(v for _, v in vals)
        m["leaders"] = [pid for pid, v in vals if v == best]
    presets = []
    for pid, label, w in PRESETS:
        if w is None:
            w = {m[0]: m[7] for m in METRICS if m[7]}
        elif w == "all":
            w = {m[0]: 1 for m in METRICS}
        presets.append({"id": pid, "label": label, "weights": w})
    FG = {
        "meta": {"asOfLabel": AS_OF_LABEL, "generated": date.today().isoformat(),
                 "matrixSource": "Sources: Wikipedia career-statistics tables and honours sections (fetched 30 October 2026); FIFA tournament records; match-by-match records for Ronaldo and Messi. Goals from age 30 and 35 are exact for Ronaldo and Messi and estimated from season totals for everyone else.",
                 "ageSource": "Sources: match-by-match records for Ronaldo and Messi (exact age on match day); Wikipedia season tables for everyone else (season totals placed at each season's end). Active players are shown to 30 October 2026.",
                 "leaguesSource": "Source: Wikipedia honours sections (fetched 30 October 2026). Shared awards count. Brazilian state championships and the colonial Mozambique league are excluded.",
                 "uclSource": "Source: Wikipedia, list of European Cup and Champions League top scorers (updated 21 October 2026).",
                 "intlSource": f"Source: Wikipedia, list of men's footballers with 50 or more international goals (as of {leaderboards['intlAsOf']}).",
                 "wcSource": "Sources: FIFA World Cup records and 2026 match reports; Wikipedia player articles. Uwe Seeler, Miroslav Klose and Ivan Perišić, outside this comparison, also scored at four World Cups."},
        "players": [{"id": p[0], "name": p[1], "short": p[2], "nation": p[3], "role": p[4], "active": is_active(p[0], cs),
                     "born": next(x["birth_date"] for x in cs["players"] if x["id"] == p[0]), "debut": debut_year(p[0], cs)} for p in PLAYERS],
        "families": FAMILIES, "metrics": metrics, "presets": presets,
        "values": values, "valueNotes": notes, "ageCurves": curves,
        "profile": build_profile(h2h, hm), "leaderboards": leaderboards, "leagueTopScorer": build_league_matrix(hon),
    }
    FG["headline"] = headline(h2h)
    FG["records"] = RECORDS
    FG["references"] = REFERENCES
    FG.update(copy_blocks(hm))
    return FG


def debut_year(pid, cs):
    """Calendar year in which the player's first senior first-team season began."""
    p = next(x for x in cs["players"] if x["id"] == pid)
    first = peer_metrics.first_team_rows(p)[0]["season"]
    return int(re.search(r"(1[89]\d\d|20\d\d)", first).group(1))


def is_active(pid, cs):
    """Active = the player's latest club season is the 2026 or 2026–27 season."""
    p = next((x for x in cs["players"] if x["id"] == pid), None)
    if not p or not p["club_seasons"]:
        return False
    return p["club_seasons"][-1]["season"].startswith("2026")


def build_profile(h2h, hm):
    """Ronaldo-only detail from his match-by-match record."""
    R = hm["ronaldo"]
    U = h2h["ucl"]["r"]
    return {
        "career": R["career"], "intl": R["intl"], "intlCompetitive": R["intl_competitive"], "firstMatch": R["first_match"],
        "uclRounds": U["rounds"], "uclTotal": U["total"], "uclKnockout": U["knockout"], "uclTitles": U["titles"], "uclTopScorer": U["topScorer"],
        "tournaments": h2h["tournaments"]["r"], "goalTypes": h2h["goalTypes"]["r"], "perfectHatTricks": h2h["perfectHatTricks"]["r"],
        "pens": h2h["pens"]["r"], "clubs": [c for c in h2h["clubs"] if c["player"] == "ronaldo"],
        "opponents": R["distinct_opponents_scored_against"], "competitions": R["distinct_competitions_scored_in"],
        "decisive": R["decisive"], "from30": R["from_age_30"]["goals"], "from35": R["from_age_35"]["goals"], "from40": R["from_age_40"]["goals"],
        "euroGoals": R["by_competition"]["UEFA European Championships"]["goals"], "wcGoals": R["by_competition"]["World Cup"]["goals"],
    }


HON_IDS = {"cristiano-ronaldo": "ronaldo", "lionel-messi": "messi", "pele": "pele", "gerd-muller": "muller", "ferenc-puskas": "puskas",
           "alfredo-di-stefano": "distefano", "eusebio": "eusebio", "diego-maradona": "maradona", "johan-cruyff": "cruyff",
           "zinedine-zidane": "zidane", "robert-lewandowski": "lewandowski", "zlatan-ibrahimovic": "ibrahimovic", "luis-suarez": "suarez",
           "karim-benzema": "benzema", "harry-kane": "kane", "kylian-mbappe": "mbappe", "erling-haaland": "haaland", "neymar": "neymar",
           "thierry-henry": "henry", "ronaldo-nazario": "ronaldo_nazario", "romario": "romario"}
BALLON_INELIGIBLE = {"pele": "Not eligible: the award was open only to Europeans until 1995",
                     "maradona": "Not eligible: the award was open only to Europeans until 1995",
                     "romario": "Not eligible at his peak: non-Europeans were admitted from 1995"}


def hon_by_id(hon):
    out = {}
    for p in hon["players"]:
        pid = HON_IDS.get(p["id"])
        if pid is None:
            raise KeyError(f"unmapped honours id {p['id']}")
        out[pid] = p
    return out


def _role(name):
    return "cr" if name == "Cristiano Ronaldo" else "pe"


def _num(v):
    if isinstance(v, (int, float)):
        return v, False
    t = str(v).strip()
    return int(t.rstrip("+")), t.endswith("+")


def build_leaderboards(lb):
    meta = lb["_meta"]["leaderboards"]
    intl = [{"player": r["player"], "country": r["country"], "goals": r["value"], "caps": r["secondary"], "role": _role(r["player"]),
             "status": r.get("status")} for r in lb["5a_mens_international_goals_top15"]]
    ucl = [{"player": r["player"], "goals": r["value"], "apps": r["secondary"], "role": _role(r["player"])} for r in lb["5c_ucl_all_time_scorers_top15"]]
    career = []
    for key, label, short in (("5g_career_goals_iffhs_method_top10", "IFFHS method", "Top-level official matches: league, cup, continental and international"),
                              ("5g_career_goals_rsssf_official_top_level_top10", "RSSSF, top level", "Official matches at top level"),
                              ("5g_career_goals_rsssf_official_all_levels_top10", "RSSSF, all levels", "Official matches at every level, including reserve and regional selections")):
        rows = []
        for r in lb[key][:8]:
            v, plus = _num(r["value"])
            rows.append({"player": r["player"], "goals": v, "plus": plus, "role": _role(r["player"])})
        m = meta.get(key, {})
        career.append({"id": key, "label": label, "desc": short, "asOf": m.get("as_of") or lb[key][0].get("as_of"),
                       "source": m.get("source_url") or lb[key][0].get("source_url"), "rows": rows})
    g = lb["5g_career_goals_guinness"][0]
    return {"intl": intl, "ucl": ucl, "career": career,
            "guinness": {"player": g["player"], "goals": g["value"], "apps": g["secondary"], "source": g["source_url"]},
            "intlAsOf": meta["5a_mens_international_goals_top15"]["as_of"], "intlSource": meta["5a_mens_international_goals_top15"]["source_url"],
            "uclAsOf": meta["5c_ucl_all_time_scorers_top15"]["as_of"], "uclSource": meta["5c_ucl_all_time_scorers_top15"]["source_url"]}


LEAGUE_SHORT = [  # display order: Europe's big five first, then by first appearance
    ("Premier League", "Premier League"), ("La Liga", "La Liga"), ("Serie A", "Serie A"), ("Bundesliga", "Bundesliga"),
    ("Ligue 1", "Ligue 1"), ("Eredivisie", "Eredivisie"), ("Primeira Liga / Primeira Divisão", "Primeira Liga"),
    ("Saudi Pro League", "Saudi Pro League"), ("Major League Soccer", "MLS"), ("Campeonato Brasileiro Série A", "Brazil Série A"),
    ("Argentine Primera División", "Argentina Primera"), ("Categoría Primera A (Campeonato Profesional)", "Colombia Primera A"),
    ("Nemzeti Bajnokság I", "Hungary NB I"), ("Ekstraklasa", "Ekstraklasa"),
]


def build_league_matrix(hon):
    H = hon_by_id(hon)
    known = dict(LEAGUE_SHORT)
    present = set()
    rows = []
    for pid, p in H.items():
        by_league = p["individual_honours"].get("league_top_scorer_by_league") or {}
        for lg in by_league:
            if lg not in known:
                raise KeyError(f"league {lg!r} ({pid}) missing from LEAGUE_SHORT")
            present.add(lg)
        rows.append({"id": pid, "counts": {known[lg]: d["count"] for lg, d in by_league.items()},
                     "seasons": {known[lg]: d["seasons"] for lg, d in by_league.items()}})
    order = [pid for pid, *_ in PLAYERS]
    rows.sort(key=lambda r: (-len(r["counts"]), -sum(r["counts"].values()), order.index(r["id"])))
    leagues = [{"id": short, "label": short} for lg, short in LEAGUE_SHORT if lg in present]
    return {"leagues": leagues, "rows": rows}


def headline(h2h):
    R = h2h["ronaldo"]
    return [
        {"value": f"{R['career']['goals']:,}", "label": "Official goals", "note": "Most ever, on IFFHS and RSSSF counts"},
        {"value": f"{R['intl']['goals']}", "label": "International goals", "note": "Men's all-time record"},
        {"value": f"{h2h['ucl']['r']['total']['goals']}", "label": "Champions League goals", "note": "All-time record"},
        {"value": f"{h2h['intl']['r']['wcScored']}", "label": "World Cups with a goal", "note": "The only player to score at six"},
    ]


W_INTL = "https://en.wikipedia.org/wiki/List_of_men%27s_footballers_with_50_or_more_international_goals"
W_CAPS = "https://en.wikipedia.org/wiki/List_of_men%27s_footballers_with_100_or_more_international_caps"
W_500 = "https://en.wikipedia.org/wiki/List_of_footballers_with_500_or_more_goals"
W_UCL = "https://en.wikipedia.org/wiki/European_Cup_and_UEFA_Champions_League_records_and_statistics"
W_EURO = "https://en.wikipedia.org/wiki/UEFA_European_Championship_top_goalscorers"
FIFA_WC = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/cristiano-ronaldo-portugal-goal-record"

RECORDS = [  # group, record, Ronaldo's figure, next best (where the source gives it), source label, source URL
    ("Career", "Most official goals", "985", "Lionel Messi, 936", "IFFHS method via Wikipedia (29 Oct 2026); RSSSF", W_500),
    ("International", "Most international goals, men", "146", "Lionel Messi, 126", "Wikipedia list (7 Oct 2026)", W_INTL),
    ("International", "Most international caps, men", "234", "Lionel Messi, 208", "Wikipedia list (6 Oct 2026)", W_CAPS),
    ("International", "Most World Cups with a goal", "6", "Lionel Messi, 5", "FIFA (23 Jun 2026)", FIFA_WC),
    ("International", "Most European Championships with a goal", "5", "Robert Lewandowski and Luka Modrić, 4", "Wikipedia", W_EURO),
    ("International", "Most European Championship goals", "14", "Michel Platini, 9", "Wikipedia", W_EURO),
    ("Champions League", "Most goals", "140", "Lionel Messi, 129", "Wikipedia records (21 Oct 2026)", W_UCL),
    ("Champions League", "Most matches won", "115", "Thomas Müller, 111", "Wikipedia records", W_UCL),
    ("Champions League", "Most seasons as top scorer", "7", "Lionel Messi, 6", "Wikipedia records", W_UCL),
    ("Champions League", "Most goals in the knockout rounds", "67", "Lionel Messi, 49", "Wikipedia records", W_UCL),
    ("Champions League", "Most quarter-final goals", "25", None, "Wikipedia records", W_UCL),
    ("Champions League", "Most semi-final goals", "13", None, "Wikipedia records", W_UCL),
    ("Champions League", "Most goals in finals since 1992", "4", None, "Wikipedia records", W_UCL),
    ("Champions League", "Most away goals", "63", None, "Wikipedia records", W_UCL),
    ("Champions League", "Most direct free-kick goals", "12", None, "Wikipedia records", W_UCL),
    ("Champions League", "Most consecutive matches with a goal", "11", None, "Wikipedia records (2017–18)", W_UCL),
    ("Champions League", "Most goals against one opponent", "10", None, "Wikipedia records (against Juventus)", W_UCL),
]
RECORDS = [{"group": g, "record": r, "value": v, "next": nx, "source": s, "href": u} for g, r, v, nx, s, u in RECORDS]


def copy_blocks(hm):
    R = hm["ronaldo"]
    method = [
        {"title": "Data", "paras": [
            "Official goals are goals in senior competitive club matches (league, domestic cups and super cups, continental club competitions, Club World Cup) and full internationals, friendlies included. Club friendlies, youth, Olympic and reserve-team matches, indoor football and penalty-shootout kicks are excluded.",
            f"Career totals for all 21 players come from the career-statistics tables on English Wikipedia, fetched 30 October 2026. Ronaldo and Messi are also counted match by match from independent match records; both sources give identical totals ({R['career']['goals']} for Ronaldo, 936 for Messi). Honours come from each player's Wikipedia honours section; all-time lists from Wikipedia, RSSSF and FIFA.",
        ]},
        {"title": "Normalisation and aggregation", "cites": ["OECD/JRC 2008"], "paras": [
            "Each criterion is normalised across the players in the selected group with one of four methods described in the OECD/JRC Handbook on Constructing Composite Indicators: distance to a reference (share of the best value), min–max rescaling, standardisation (z-scores) and ranking. The overall score is the weighted arithmetic mean of the normalised scores (linear aggregation).",
        ], "formula": "score(p) = Σ wᵢ · nᵢ(p) ÷ Σ wᵢ     share of best: nᵢ = 100·xᵢ/max · min–max: nᵢ = 100·(xᵢ−min)/(max−min) · z-score: nᵢ = (xᵢ−mean)/sd · rank: nᵢ = 100·(N−rankᵢ)/(N−1)"},
        {"title": "Missing data", "cites": ["OECD/JRC 2008"], "paras": [
            "Values are never imputed. A player without data for a selected criterion is scored on the criteria he has, with the weights rescaled to sum to one, and is marked † in the ranking. This applies to Pelé, who never played in the European Cup or Champions League.",
        ]},
        {"title": "Uncertainty analysis", "cites": ["Saisana et al. 2005", "Rubin 1981"], "paras": [
            "Rank stability is tested by Monte Carlo simulation, following the uncertainty-analysis approach of Saisana, Saltelli and Tarantola. Each of 5,000 runs draws a weight vector uniformly from the simplex over the selected criteria (a flat Dirichlet distribution, as in Rubin's Bayesian bootstrap) and one of the four normalisation methods with equal probability, then ranks the players. The panel reports each player's median rank, the 5th–95th percentile range and the share of runs in which he ranks first. The random-number generator is seeded, so results are reproducible.",
        ]},
        {"title": "Age-based measures", "cites": ["Dendir 2016"], "paras": [
            "Goals from age 30 and 35 measure output after the typical peak: a study of players in Europe's top leagues found average peak performance between ages 25 and 27, with forwards near 25. Ronaldo's and Messi's ages are exact to the match day. For the other players, each season's goals are placed at the end of that season and each year's international goals at mid-year, so their figures are estimates accurate to about one season and are labelled as such.",
        ]},
        {"title": "Charts and colour", "cites": ["Cleveland & McGill 1984", "Machado et al. 2009"], "paras": [
            "Quantities are drawn as lengths or positions on a common scale, the encodings readers judge most accurately. The highlight colour and the neutral series colour were checked for separation under protanopia and deuteranopia using the Machado, Oliveira and Fernandes simulation, in both light and dark themes.",
        ]},
        {"title": "Scope and known disputes", "paras": [
            "The criteria cover goals, the Champions League, international football, longevity and range. Creative play (assists, dribbling) and awards decided by votes (the Ballon d'Or) are not scored.",
            "Ronaldo's goal against Al-Faisaly on 23 October 2026 is credited to him by the referee's report and the Saudi Pro League but recorded as an own goal by Opta, Sofascore and FotMob; this page follows the league (985; 984 on the Opta count). The totals include every senior division, so a few players score higher here than on IFFHS's top-level-only count (Gerd Müller: 724 here, 634 there). Guinness lists Pelé with 1,279 goals, a count that includes friendlies and tour matches.",
        ]},
        {"title": "Data sources", "list": SOURCES},
        {"title": "References", "refs": True},
    ]
    footer = [
        "Greatest of All Time. Match data to 29 October 2026; other players from Wikipedia as of 30 October 2026. Built and checked by scripts that can be re-run.",
        "Independent analysis of public data. Not affiliated with any player, club, league or federation.",
    ]
    return {"method": method, "footer": footer}


SOURCES = [
    {"text": "English Wikipedia", "href": W_500, "after": "— career-statistics tables and honours sections for all 21 players (raw wikitext, 30 October 2026); all-time goal, international and Champions League lists and records."},
    {"text": "Match-by-match records", "href": "https://www.messivsronaldo.app/", "after": "— one row per official match for Ronaldo (1,343) and Messi (1,183): dates, rounds, goal types. Totals cross-checked with Wikipedia and RonaldoStats."},
    {"text": "RSSSF", "href": "https://www.rsssf.org/players/prolific.html", "after": "— most prolific goalscorers in official matches (updated 19 July 2026)."},
    {"text": "FIFA", "href": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/fifa-world-cup-all-time-leading-scorers", "after": "— World Cup records, 2026 match reports and awards."},
    {"text": "Guinness World Records", "href": "https://www.guinnessworldrecords.com/world-records/most-career-goals-(football)", "after": "— most career goals, all matches."},
    {"text": "Reuters, AP, ESPN and the Saudi Pro League", "after": "— 2025–26 results and titles, and the disputed 23 October 2026 goal (links in the research notes)."},
]


REFERENCES = [  # methods actually used on the page
    {"key": "OECD/JRC 2008", "text": "OECD & European Commission Joint Research Centre (2008). Handbook on Constructing Composite Indicators: Methodology and User Guide. OECD Publishing. ISBN 978-92-64-04345-9.",
     "href": "https://knowledge4policy.ec.europa.eu/sites/default/files/jrc47008_handbook_final.pdf", "use": "Normalisation options, linear weighted aggregation, missing-data treatment"},
    {"key": "Saisana et al. 2005", "text": "Saisana, M., Saltelli, A. & Tarantola, S. (2005). Uncertainty and sensitivity analysis techniques as tools for the quality assessment of composite indicators. Journal of the Royal Statistical Society: Series A, 168(2), 307–323. doi:10.1111/j.1467-985X.2005.00350.x",
     "href": "https://doi.org/10.1111/j.1467-985X.2005.00350.x", "use": "Monte Carlo uncertainty analysis of the ranking"},
    {"key": "Rubin 1981", "text": "Rubin, D. B. (1981). The Bayesian bootstrap. The Annals of Statistics, 9(1), 130–134.",
     "href": "https://doi.org/10.1214/aos/1176345338", "use": "Random weights drawn uniformly over the simplex (flat Dirichlet)"},
    {"key": "Dendir 2016", "text": "Dendir, S. (2016). When do soccer players peak? A note. Journal of Sports Analytics, 2(2).",
     "href": "https://www.radford.edu/content/radfordcore/home/news/releases/2016/october/at-what-age-do-soccer-players-peak--ask-an-economist.html", "use": "Typical peak age (25–27) behind the age-30 and age-35 thresholds"},
    {"key": "Cleveland & McGill 1984", "text": "Cleveland, W. S. & McGill, R. (1984). Graphical perception: theory, experimentation, and application to the development of graphical methods. Journal of the American Statistical Association, 79(387), 531–554.",
     "href": "https://doi.org/10.1080/01621459.1984.10478080", "use": "Values shown as lengths on a common scale"},
    {"key": "Machado et al. 2009", "text": "Machado, G. M., Oliveira, M. M. & Fernandes, L. A. F. (2009). A physiologically-based model for simulation of color vision deficiency. IEEE Transactions on Visualization and Computer Graphics, 15(6), 1291–1298. doi:10.1109/TVCG.2009.113",
     "href": "https://doi.org/10.1109/TVCG.2009.113", "use": "Colour palette checked for colour-vision deficiency"},
]

RESEARCH_DIR = None

if __name__ == "__main__":
    RESEARCH_DIR = sys.argv[1]
    FG = build(RESEARCH_DIR)
    os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True)
    with open(sys.argv[2], "w") as fh:
        fh.write("window.FG = " + json.dumps(FG, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("wrote", sys.argv[2], os.path.getsize(sys.argv[2]), "bytes; players", len(FG["players"]), "; criteria", len(FG["metrics"]), "; records", len(FG["records"]))
    for m in FG["metrics"]:
        print(f"  {m['id']:15s} leader(s): {', '.join(m['leaders'])}")
