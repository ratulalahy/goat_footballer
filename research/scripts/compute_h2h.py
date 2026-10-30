"""Compute Ronaldo vs Messi metrics from match-level data (messivsronaldo.app match histories).

Every number is derived from one row per official senior match, so totals can be audited.
Usage: python3 compute_h2h.py <mvr_dir> <out_json>
"""
import csv, json, sys, os
from datetime import date
from collections import defaultdict

BIRTH = {"ronaldo": date(1985, 2, 5), "messi": date(1987, 6, 24)}
INTL_TOURN = {"World Cup", "UEFA European Championships", "Copa America", "Confederations Cup", "Finalissima"}
INTL_COMP = {"World Cup Qualifier", "Euros Qualifier", "UEFA Nations League"} | INTL_TOURN
LEAGUES = {"Premier League", "La Liga", "Serie A", "Saudi Pro League", "Primeira Liga", "Ligue 1", "MLS"}
KO_ROUNDS = {"R96", "R64", "R32", "R16", "QF", "SF", "F", "3rd Place Play-off", "Play-off"}

def i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0

def age_on(b, d):
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))

def won(r):
    st, so = i(r["scoreTeam"]), i(r["scoreOpponent"])
    if st != so:
        return st > so
    ps = (r.get("penScore") or "").strip()
    if ps and "-" in ps:
        a, b = ps.split("-")[:2]
        return i(a) > i(b)
    return None  # drawn, no shootout

def pts(a, b):
    return 3 if a > b else (1 if a == b else 0)

def decisive(r):
    """True when removing the player's goals would change the match result (shootouts ignored)."""
    st, so, g = i(r["scoreTeam"]), i(r["scoreOpponent"]), i(r["goals"])
    return g > 0 and pts(st, so) > pts(st - g, so)

def summarize(rows):
    s = defaultdict(int)
    for r in rows:
        s["apps"] += 1
        for k in ("goals", "assists", "minsPlayed", "pens", "pensMissed", "hatTricks", "freeKicks",
                  "insideBox", "outsideBox", "left", "right", "head", "other"):
            s[k] += i(r[k])
    s["npg"] = s["goals"] - s["pens"]
    return dict(s)

def main(mvr_dir, out_path):
    out = {"source": "messivsronaldo.app match histories (official senior matches; club friendlies excluded)",
           "fetched_at": open(os.path.join(mvr_dir, "fetched_at.txt")).read().strip(), "players": {}}
    for who in ("ronaldo", "messi"):
        rows = list(csv.DictReader(open(os.path.join(mvr_dir, f"{who}_matches.csv"))))
        b = BIRTH[who]
        for r in rows:
            y, m, d = map(int, r["iso_date"].split("-"))
            r["_date"] = date(y, m, d)
            r["_age"] = age_on(b, r["_date"])
            r["_intl"] = r["team"] in ("Portugal", "Argentina")
        P = {"birth_date": b.isoformat(), "last_match": rows[-1]["iso_date"], "first_match": rows[0]["iso_date"]}
        P["career"] = summarize(rows)
        club = [r for r in rows if not r["_intl"]]
        intl = [r for r in rows if r["_intl"]]
        P["club"] = summarize(club)
        P["intl"] = summarize(intl)
        P["intl_competitive"] = summarize([r for r in intl if r["competition"] in INTL_COMP])
        P["intl_friendly"] = summarize([r for r in intl if r["competition"] == "International Friendly"])
        P["intl_tournaments"] = summarize([r for r in intl if r["competition"] in INTL_TOURN])
        P["intl_tournament_knockout"] = summarize([r for r in intl if r["competition"] in INTL_TOURN and r["round"] in KO_ROUNDS])
        P["by_competition"] = {c: summarize([r for r in rows if r["competition"] == c]) for c in sorted({r["competition"] for r in rows})}
        P["leagues"] = {c: summarize([r for r in rows if r["competition"] == c]) for c in sorted({r["competition"] for r in rows} & LEAGUES)}
        ucl = [r for r in rows if r["competition"] == "Champions League"]
        P["ucl"] = summarize(ucl)
        P["ucl_by_round"] = {rd: summarize([r for r in ucl if r["round"] == rd]) for rd in ("Group", "R16", "QF", "SF", "F")}
        P["ucl_knockout"] = summarize([r for r in ucl if r["round"] in KO_ROUNDS])
        P["ucl_qf_sf_f"] = summarize([r for r in ucl if r["round"] in ("QF", "SF", "F")])
        finals = [r for r in rows if r["round"] == "F"]
        P["finals"] = summarize(finals)
        P["finals"]["won"] = sum(1 for r in finals if won(r) is True)
        P["finals_list"] = [{"date": r["iso_date"], "comp": r["competition"], "team": r["team"], "opp": r["opponent"],
                             "score": f'{r["scoreTeam"]}-{r["scoreOpponent"]}', "pens": r.get("penScore") or "",
                             "goals": i(r["goals"]), "assists": i(r["assists"]), "won": won(r)} for r in finals]
        P["knockout_all"] = summarize([r for r in rows if r["round"] in KO_ROUNDS])
        # Age profile: exact age on match day
        ages = defaultdict(list)
        for r in rows:
            ages[r["_age"]].append(r)
        P["by_age"] = {a: summarize(ages[a]) for a in sorted(ages)}
        for t in (30, 33, 35, 38, 40):
            P[f"from_age_{t}"] = summarize([r for r in rows if r["_age"] >= t])
            P[f"before_age_{t}"] = summarize([r for r in rows if r["_age"] < t])
        P["by_year"] = {y: summarize([r for r in rows if r["_date"].year == y]) for y in sorted({r["_date"].year for r in rows})}
        P["by_season"] = {s: summarize([r for r in rows if r["season"] == s]) for s in sorted({r["season"] for r in rows})}
        P["hat_trick_matches"] = sum(1 for r in rows if i(r["goals"]) >= 3)
        P["perfect_hat_tricks"] = sum(1 for r in rows if i(r["left"]) >= 1 and i(r["right"]) >= 1 and i(r["head"]) >= 1)
        P["seasons_30plus"] = sorted(s for s, v in P["by_season"].items() if v["goals"] >= 30)
        P["years_40plus"] = sorted(y for y, v in P["by_year"].items() if v["goals"] >= 40)
        P["distinct_opponents_scored_against"] = len({r["opponent"] for r in rows if i(r["goals"]) > 0})
        P["distinct_competitions_scored_in"] = len({r["competition"] for r in rows if i(r["goals"]) > 0})
        P["clubs"] = {t: summarize([r for r in club if r["team"] == t]) for t in sorted({r["team"] for r in club})}
        dec = [r for r in rows if decisive(r)]
        P["decisive"] = {
            "matches": len(dec),
            "per100": round(len(dec) / len(rows) * 100, 1),
            "points_added": sum(pts(i(r["scoreTeam"]), i(r["scoreOpponent"])) - pts(i(r["scoreTeam"]) - i(r["goals"]), i(r["scoreOpponent"])) for r in dec),
            "knockout": sum(1 for r in dec if r["round"] in KO_ROUNDS),
            "ucl_knockout": sum(1 for r in dec if r["competition"] == "Champions League" and r["round"] in KO_ROUNDS),
        }
        # Cumulative goals by exact age, one point per calendar month with a match (age in years at month end)
        cum, curve, last_key = 0, [], None
        for r in rows:
            cum += i(r["goals"])
            key = (r["_date"].year, r["_date"].month)
            age = (r["_date"] - b).days / 365.2425
            if curve and key == last_key:
                curve[-1] = [round(age, 3), cum]
            else:
                curve.append([round(age, 3), cum])
            last_key = key
        P["age_curve_monthly"] = curve
        # International tournaments: goals per edition
        tour = defaultdict(lambda: {"apps": 0, "goals": 0, "assists": 0})
        for r in intl:
            if r["competition"] in INTL_TOURN:
                k = (r["competition"], r["_date"].year)
                tour[k]["apps"] += 1
                tour[k]["goals"] += i(r["goals"])
                tour[k]["assists"] += i(r["assists"])
        P["tournaments"] = [{"comp": c, "year": y, **v} for (c, y), v in sorted(tour.items(), key=lambda kv: kv[0][1])]
        out["players"][who] = P
    json.dump(out, open(out_path, "w"), indent=1, default=str)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
