"""Convert messivsronaldo.app match-history page-data into clean CSVs.

Source: https://www.messivsronaldo.app/match-histories/{ronaldo,messi}-match-history/
(Gatsby page-data JSON). One row per official senior appearance (club friendlies excluded by the source).
Usage: python3 mvr_to_csv.py <mvr_dir>
"""
import csv, json, sys, os

def load(path, key):
    d = json.load(open(path))["result"]["data"][key]["edges"]
    return [e["node"] for e in d]

def num(v):
    if v in (None, "", "-"):
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except ValueError:
        return v

def main(mvr_dir):
    for who, key in (("ronaldo", "allSheetRonaldoMatchHistory"), ("messi", "allSheetMessiMatchHistory")):
        rows = load(os.path.join(mvr_dir, f"match-histories_{who}-match-history.json"), key)
        out = []
        for r in rows:
            dd, mm = r["date"].split("-")
            row = {k: num(v) if k not in ("date", "year", "season", "competition", "homeAway", "round", "team", "opponent", "notes", "ftScore", "penScore", "h2H") else v for k, v in r.items()}
            row["iso_date"] = f"{r['year']}-{int(mm):02d}-{int(dd):02d}"
            out.append(row)
        out.sort(key=lambda x: x["iso_date"])
        cols = ["iso_date"] + [k for k in rows[0].keys()]
        with open(os.path.join(mvr_dir, f"{who}_matches.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(out)
        print(who, len(out), "matches", out[0]["iso_date"], "->", out[-1]["iso_date"])

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
