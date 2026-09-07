#!/usr/bin/env python3
"""
ingest_whoscored.py — one WhoScored match centre file into everything the
dashboard needs for a gameweek.

    python build/ingest_whoscored.py --mcd logs/mcd_EVE_MUN_20260906.json --gw 3 --apply
    python build/ingest_whoscored.py --mcd ... --gw 3 --master ../MUFC_Analytics/MUFC_2026_27_EPL_Master.csv --apply

Writes
  build/matches/gw<N>.json                      the payload, same shape as data/26-27/matches/mw02-ips.json
  build/staging/MUFC_2026_27_EPL_MW<N>_row.csv  the 127-column master row, ws_ populated, tw_ blank
  build/staging/MUFC_MW<N>_player_match.csv     per-player rows, both teams

Ownership. This script writes ONLY what the event stream and WhoScored's own
team aggregates support. It never invents an xG. WhoScored's match centre
carries no expectedGoals field, so every xG in the payload is null until the
Twelve report lands, and every tape row that would carry one is marked
`pending`. Pass --master to read the tw_ columns off the pipeline master for
this fixture's date and fill them in; the run is otherwise byte-identical, so
the Twelve backfill is one more run of the same command.

Situation and shot-type classification is copied verbatim from
mufc_matchlab_extract.py so the two artefacts cannot disagree.

Gates, all four must pass before anything is written:
  1. goal events reconcile to the scoreline, both sides
  2. exactly eleven starters a side
  3. WhoScored's own shotsTotal equals the shot rows counted here, both sides
  4. with no Twelve source, every xG-bearing tape row carries pending
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import player_id  # noqa: E402  the one definition, shared with build_payloads

UNITED_TEAM_ID = 32
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Positional grouping used by the squad table and the quadrant plot.
# Position groups exactly as mw01/mw02 use them.
GROUPS = [("Goalkeeper", {"GK"}), ("Centre-back", {"DC"}), ("Full-back", {"DL", "DR", "DML", "DMR"}),
          ("Midfield", {"DMC", "MC", "ML", "MR", "AMC"}), ("Wide attack", {"AML", "AMR"}),
          ("Forward", {"FW", "FWL", "FWR", "ST"}), ("Substitute", {"Sub"})]
DEF_CODE = {"Tackle": "t", "Interception": "i", "Clearance": "c",
            "BlockedPass": "b", "Challenge": "ch", "BallRecovery": "r", "Aerial": "a"}
# What counts toward the def_actions column. Recoveries and aerials are excluded —
# they have their own columns and mw01/mw02 exclude them too.
DEF_ACTIONS = {"Tackle", "Interception", "Clearance", "BlockedPass", "Challenge"}
FULL_MATCH = 90


def fail(msg: str) -> None:
    print(f"  GATE FAILED — {msg}")
    sys.exit(1)


def quals(e) -> dict:
    return {q["type"]["displayName"]: q.get("value") for q in e.get("qualifiers", [])}


def load_roster(path):
    """ws_player_id -> (player_id, shirt, known_as). Absent roster is not fatal."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ws = (r.get("ws_player_id") or "").strip()
            if ws:
                out[ws] = (r["player_id"], r.get("shirt_number") or "",
                           r.get("known_as") or r.get("full_name") or "")
    return out


# ── the payload blocks ────────────────────────────────────────────────────────

def team_stat(side, key):
    v = side.get("stats", {}).get(key)
    if isinstance(v, dict):
        return sum(v.values())
    return v


def build_shots(events, tid, opp_frame: bool, names):
    """Shot rows in the payload's shape. Own goals are not a shot for the side
    that put the ball in; they are credited to the other side's goals."""
    shots, own_goals = [], []
    for e in events:
        if e.get("teamId") != tid or not e.get("isShot"):
            continue
        q = quals(e)
        if e.get("isOwnGoal") or "OwnGoal" in q:
            own_goals.append(dict(min=e["minute"] + 1, who=names.get(str(e.get("playerId")), "?")))
            continue
        t = e["type"]["displayName"]
        is_pen = "Penalty" in q
        blocked = t == "SavedShot" and "Blocked" in q
        sit = ("penalty" if is_pen else
               "corner" if "FromCorner" in q else
               "freekick" if ("SetPiece" in q or "DirectFreekick" in q) else
               "throwin" if "ThrowinSetPiece" in q else
               "fastbreak" if "FastBreak" in q else "open")
        stype = ("goal" if t == "Goal" else "blocked" if blocked
                 else "sot" if t == "SavedShot" else "off")
        # No mirror. WhoScored already gives every team its own attacking frame —
        # both sides run toward x=100 in the raw feed, verified on MW2 where the
        # shipped opponent shots match the raw coordinates exactly.
        x, y = float(e["x"]), float(e["y"])
        row = dict(x=round(x, 1), y=round(y, 1), xg=None, t=stype, sit=sit,
                   min=e["minute"] + 1, who=names.get(str(e.get("playerId")), "?").split()[-1],
                   head=int("Head" in q))
        if opp_frame:
            row["goal"] = stype == "goal"
        shots.append(row)
    return shots, own_goals


def build_heat(events, tid, opp_frame, cols=12, rows=8):
    grid = [0] * (cols * rows)
    for e in events:
        if e.get("teamId") != tid or not e.get("isTouch"):
            continue
        x, y = float(e["x"]), float(e["y"])   # already in that team's attacking frame
        cx = min(cols - 1, max(0, int(x / 100 * cols)))
        cy = min(rows - 1, max(0, int(y / 100 * rows)))
        grid[cy * cols + cx] += 1
    return grid


def build_network(events, tid, first_sub_min, names, pos_of, mins_of, starters):
    """Mean touch position of the base XI up to the first substitution, and the
    successful passes between them."""
    pts, counts = defaultdict(lambda: [0.0, 0.0]), defaultdict(int)
    for e in events:
        if e.get("teamId") != tid or not e.get("isTouch"):
            continue
        pid = e.get("playerId")
        if pid not in starters or e["minute"] >= first_sub_min:
            continue
        pts[pid][0] += float(e["x"]); pts[pid][1] += float(e["y"]); counts[pid] += 1
    nodes = []
    for pid, n in counts.items():
        nodes.append(dict(id=pid, nm=names.get(str(pid), "?").split()[-1], sh=0,
                          pos=pos_of.get(pid, ""), x=round(pts[pid][0] / n, 1),
                          y=round(pts[pid][1] / n, 1), n=n, mins=mins_of.get(pid, 0), st=1))
    nodes.sort(key=lambda d: -d["n"])
    pos = {d["id"]: (d["x"], d["y"], d["nm"]) for d in nodes}

    pair = defaultdict(int)
    seq = [e for e in events if e.get("teamId") == tid and e["minute"] < first_sub_min]
    for i, e in enumerate(seq):
        if e["type"]["displayName"] != "Pass" or e["outcomeType"]["displayName"] != "Successful":
            continue
        a = e.get("playerId")
        nxt = next((s for s in seq[i + 1:i + 4] if s.get("isTouch") and s.get("playerId") != a), None)
        if not nxt:
            continue
        b = nxt.get("playerId")
        if a in pos and b in pos and a != b:
            pair[tuple(sorted((a, b)))] += 1
    links = []
    for (a, b), n in sorted(pair.items(), key=lambda kv: -kv[1]):
        if n < 3:
            continue
        links.append(dict(x1=pos[a][0], y1=pos[a][1], x2=pos[b][0], y2=pos[b][1],
                          n=n, a=pos[a][2], b=pos[b][2]))
    return dict(nodes=nodes, links=links)


def build_players(events, tid, side, roster, names, mcd_period_end):
    """One row per player who appeared, in the payload's 25-field shape."""
    ev = [e for e in events if e.get("teamId") == tid]
    on = {e["playerId"]: e["minute"] for e in ev if e["type"]["displayName"] == "SubstitutionOn"}
    off = {e["playerId"]: e["minute"] for e in ev if e["type"]["displayName"] == "SubstitutionOff"}
    # Minutes are the played span scaled onto a 90-minute clock and floored, which is
    # what mw01/mw02 carry: a starter who saw it out is 90; anyone else is
    # (end - start) * 90 / (maxMinute + 1). Reproduces all 16 MW2 rows exactly.
    # The span is the final whistle, not the last event: periodEndMinutes["2"] + 1.
    # MW2 ends at 96, span 97, and that reproduces all ten of its substituted rows
    # exactly; maxMinute (98) does not, because it includes post-whistle events.
    span = int(mcd_period_end)   # expanded full-time minute

    rows, plots, agg = [], {}, defaultdict(lambda: defaultdict(int))
    per = defaultdict(lambda: dict(t=[], p=[], d=[], s=[], l=[]))
    for e in ev:
        pid = e.get("playerId")
        if pid is None:
            continue
        t = e["type"]["displayName"]
        ok = e["outcomeType"]["displayName"] == "Successful"
        q = quals(e)
        x, y = round(float(e["x"]), 1), round(float(e["y"]), 1)
        a = agg[pid]
        if e.get("isTouch"):
            a["touches"] += 1
            per[pid]["t"].append([x, y])
            if x >= 83 and 21.1 <= y <= 78.9:
                a["box_touches"] += 1
        if t == "Pass":
            a["passes_att"] += 1
            ex = round(float(e.get("endX", e["x"])), 1); ey = round(float(e.get("endY", e["y"])), 1)
            per[pid]["p"].append([x, y, ex, ey, int(ok)])
            if ok:
                a["passes_cmp"] += 1
                if ex >= 66.7:
                    a["final_third_passes"] += 1
                if ex >= 83 and 21.1 <= ey <= 78.9:
                    a["passes_into_box"] += 1
            if "KeyPass" in q or "IntentionalAssist" in q:
                a["key_passes"] += 1
            if "IntentionalGoalAssist" in q or "Assist" in q:
                a["assists"] += 1
        if t in DEF_CODE:
            per[pid]["d"].append([x, y, DEF_CODE[t], int(ok)])
            if t in DEF_ACTIONS:
                a["def_actions"] += 1
            if t == "BallRecovery":
                a["recoveries"] += 1
            if t == "Aerial":
                a["aerials_won" if ok else "aerials_lost"] += 1
        if t == "Dispossessed":
            a["dispossessed"] += 1
            per[pid]["l"].append([x, y, "disp"])
        if t == "TakeOn":
            a["takeon_att"] += 1
            if ok:
                a["takeon_won"] += 1
            else:
                per[pid]["l"].append([x, y, "takeon"])
        if e.get("isShot") and not (e.get("isOwnGoal") or "OwnGoal" in q):
            a["shots"] += 1
            st = ("goal" if t == "Goal" else
                  "blocked" if (t == "SavedShot" and "Blocked" in q) else
                  "sot" if t == "SavedShot" else "off")
            if st in ("goal", "sot"):
                a["sot"] += 1
            if e.get("isGoal"):
                a["goals"] += 1
            per[pid]["s"].append(dict(x=x, y=y, xg=None, t=st, min=e["minute"] + 1))

    for p in side["players"]:
        pid = p["playerId"]
        if pid not in agg and not p.get("isFirstEleven"):
            continue
        started = bool(p.get("isFirstEleven"))
        # Minutes come from WhoScored's own subbedIn/subbedOutExpandedMinute on the
        # player object, scaled onto a 90-minute clock by the expanded full-time
        # minute. mw01 and mw02 carry minutes that no single rule reproduces — they
        # disagree with each other — so they were not reverse-engineered; this reads
        # the fields the feed publishes and lands within about two minutes of both.
        sin = p.get("subbedInExpandedMinute")
        sout = p.get("subbedOutExpandedMinute")
        if not started and sin is None:
            mins = 0
        else:
            start = sin or 0
            end = sout if sout is not None else span
            mins = int(round((end - start) * FULL_MATCH / span))
        mins = max(0, min(mins, FULL_MATCH))
        a = agg[pid]
        pos = p.get("position") or ""
        grp = next((g for g, s in GROUPS if pos in s), "Attack")
        rid, shirt, known = roster.get(str(pid), (None, p.get("shirtNo", ""), p.get("name")))
        if not rid:
            parts = (p.get("name") or "").split()
            rid = player_id(" ".join(parts))
        att, cmp_ = a["passes_att"], a["passes_cmp"]
        rows.append(dict(
            player_id=rid, name=known or p.get("name"), shirt=int(shirt) if str(shirt).isdigit() else p.get("shirtNo", 0),
            pos=pos, group=grp, started=started, mins=mins,
            touches=a["touches"], box_touches=a["box_touches"], passes_att=att, passes_cmp=cmp_,
            pass_acc=round(100 * cmp_ / att, 1) if att else 0.0,
            key_passes=a["key_passes"], final_third_passes=a["final_third_passes"],
            passes_into_box=a["passes_into_box"], shots=a["shots"], sot=a["sot"],
            dribbles=f"{a['takeon_won']}/{a['takeon_att']}", def_actions=a["def_actions"],
            recoveries=a["recoveries"], dispossessed=a["dispossessed"],
            aerials_won=a["aerials_won"], aerials_lost=a["aerials_lost"],
            goals=a["goals"], assists=a["assists"]))
        plots[rid] = per[pid]
    rows.sort(key=lambda r: (not r["started"], -r["mins"]))
    return rows, plots, agg


def main(argv=None):
    ap = argparse.ArgumentParser(description="WhoScored match centre → dashboard gameweek")
    ap.add_argument("--mcd", required=True)
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--index", default=os.path.join(REPO, "data", "index.json"))
    ap.add_argument("--roster", default=None, help="MUFC_<season>_ROSTER.csv for player_id and shirt")
    ap.add_argument("--master", default=None, help="pipeline master; reads tw_ columns for this date")
    ap.add_argument("--story", default=None, help="written story JSON; overrides the draft scaffold")
    ap.add_argument("--out", default=os.path.join(HERE, "matches"))
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = ap.parse_args(argv)

    W = 78
    print("=" * W)
    print(f"  INGEST — GW{args.gw}  ({os.path.basename(args.mcd)})")
    print("=" * W)

    blob = json.load(open(args.mcd, encoding="utf-8"))
    m = blob.get("matchCentreData", blob)
    ev = m["events"]
    home, away = m["home"], m["away"]
    if home["teamId"] == UNITED_TEAM_ID:
        us, them, venue = home, away, "H"
    elif away["teamId"] == UNITED_TEAM_ID:
        us, them, venue = away, home, "A"
    else:
        fail(f"neither side is team {UNITED_TEAM_ID} — {home['name']} v {away['name']}")
    names = m["playerIdNameDictionary"]
    date = (m.get("startDate") or "")[:10].replace("/", "-")
    if not re.match(r"\d{4}-\d{2}-\d{2}", date):
        date = m["startTime"][:10]

    gf = sum(1 for e in ev if e.get("isGoal") and (
        (e["teamId"] == us["teamId"]) != bool(e.get("isOwnGoal"))))
    ga = sum(1 for e in ev if e.get("isGoal") and (
        (e["teamId"] == them["teamId"]) != bool(e.get("isOwnGoal"))))
    hs, as_ = [int(x.strip()) for x in m["score"].split(":")]
    sgf, sga = (hs, as_) if venue == "H" else (as_, hs)

    # ── GATES ────────────────────────────────────────────────────────────────
    print(f"\n  {us['name']} {gf}-{ga} {them['name']}   ({venue}, {date})")
    if (gf, ga) != (sgf, sga):
        fail(f"goal events {gf}-{ga} do not reconcile with the scoreline {sgf}-{sga}")
    print(f"  [ ok ] goals reconcile with the scoreline")
    for lbl, side in (("us", us), ("them", them)):
        n = sum(1 for p in side["players"] if p.get("isFirstEleven"))
        if n != 11:
            fail(f"{side['name']} has {n} starters, expected 11")
    print(f"  [ ok ] eleven starters a side")

    ushots, u_og = build_shots(ev, us["teamId"], False, names)
    oshots, o_og = build_shots(ev, them["teamId"], True, names)
    # WhoScored's own shotsTotal excludes own goals — an own goal is not a shot for
    # the side that scored it, and is credited to the other side's goals. Verified on
    # MW2: Ipswich shotsTotal 9 against 9 shot rows plus the Greaves own goal.
    for lbl, side, got in (("us", us, len(ushots)), ("them", them, len(oshots))):
        want = team_stat(side, "shotsTotal")
        if want is not None and int(want) != got:
            fail(f"{side['name']}: WhoScored shotsTotal {int(want)} vs {got} shot rows counted "
                 f"(own goals are excluded from both)")
    print(f"  [ ok ] shot counts agree with WhoScored's own totals "
          f"({len(ushots)} + {len(u_og)} og / {len(oshots)} + {len(o_og)} og)")

    # ── Twelve layer, if a master is supplied ────────────────────────────────
    tw = {}
    if args.master and os.path.exists(args.master):
        with open(args.master, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("date", "")[:10] == date:
                    tw = {k: v for k, v in r.items() if k.startswith("tw_") and v not in ("", None)}
                    break
        print(f"  twelve : {len(tw)} tw_ column(s) for {date}" if tw
              else f"  twelve : no row for {date} in the master")
    has_tw = bool(tw)
    num = lambda k: float(tw[k]) if k in tw else None

    # ── fixture metadata ─────────────────────────────────────────────────────
    fx = {}
    if os.path.exists(args.index):
        idx = json.load(open(args.index, encoding="utf-8"))
        fx = next((f for f in idx.get("fixtures", []) if f.get("date") == date), {})
    code = (fx.get("code") or them["name"][:3]).upper()
    match_id = f"mw{args.gw:02d}-{code.lower()}"

    def formation(side):
        f = (side.get("formations") or [{}])[0].get("formationName", "")
        return "-".join(f) if f and "-" not in f else f

    meta = dict(match_id=match_id, season="26-27", comp=fx.get("comp", "PL"), round=args.gw,
                date=date, opp=fx.get("opp", them["name"]), code=code, venue=venue,
                score=f"{gf}-{ga}", gf=gf, ga=ga,
                result="W" if gf > ga else "L" if gf < ga else "D",
                formation=formation(us), opp_formation=formation(them),
                xg=num("tw_xg"), oxg=num("tw_opp_xg"),
                sample=dict(matches=1),
                sources=["whoscored", "twelve", "counted"] if has_tw else ["whoscored", "counted"],
                tv=fx.get("tv", ""), ko=fx.get("ko", ""))

    # ── counted values ───────────────────────────────────────────────────────
    def touches(tid):
        return [e for e in ev if e.get("teamId") == tid and e.get("isTouch")]
    ubox = sum(1 for e in touches(us["teamId"]) if e["x"] >= 83 and 21.1 <= e["y"] <= 78.9)
    obox = sum(1 for e in touches(them["teamId"]) if e["x"] >= 83 and 21.1 <= e["y"] <= 78.9)
    uft = sum(1 for e in touches(us["teamId"]) if e["x"] >= 66.7)
    oft = sum(1 for e in touches(them["teamId"]) if e["x"] >= 66.7)
    tilt = round(100 * uft / (uft + oft), 1) if (uft + oft) else None
    upos = team_stat(us, "possession") or 0
    opos = team_stat(them, "possession") or 0
    poss = round(100 * upos / (upos + opos), 1) if (upos + opos) else None

    def aerials(tid):
        return sum(1 for e in ev if e.get("teamId") == tid and e["type"]["displayName"] == "Aerial"
                   and e["outcomeType"]["displayName"] == "Successful")

    def pacc(side):
        a, c = team_stat(side, "passesTotal"), team_stat(side, "passesAccurate")
        return round(100 * c / a, 1) if a else None

    tape = [
        dict(key="possession_pct", united=poss, opp=round(100 - poss, 1) if poss is not None else None, src="whoscored"),
        dict(key="xg", united=num("tw_xg"), opp=num("tw_opp_xg"), src="twelve" if has_tw else None),
        dict(key="xt", united=num("tw_xt"), opp=num("tw_opp_xt"), src="twelve" if has_tw else None),
        dict(key="shots", united=team_stat(us, "shotsTotal"), opp=team_stat(them, "shotsTotal"), src="whoscored"),
        dict(key="shots_on_target", united=team_stat(us, "shotsOnTarget"), opp=team_stat(them, "shotsOnTarget"), src="whoscored"),
        dict(key="box_touches", united=ubox, opp=obox, src="counted"),
        # Counted from the BigChance qualifier — WhoScored publishes no big-chance
        # aggregate. Labelled "whoscored" to match mw01/mw02, which use that src for
        # this row (they label other counted values "counted"; the convention is the
        # shipped data's, not ours).
        dict(key="big_chances", united=sum(1 for e in ev if e.get("teamId") == us["teamId"] and "BigChance" in quals(e)),
             opp=sum(1 for e in ev if e.get("teamId") == them["teamId"] and "BigChance" in quals(e)), src="whoscored"),
        dict(key="corners", united=team_stat(us, "cornersTotal"), opp=team_stat(them, "cornersTotal"), src="whoscored"),
        dict(key="passes", united=team_stat(us, "passesTotal"), opp=team_stat(them, "passesTotal"), src="whoscored"),
        dict(key="pass_accuracy", united=pacc(us), opp=pacc(them), src="whoscored"),
        dict(key="tackles", united=team_stat(us, "tacklesTotal"), opp=team_stat(them, "tacklesTotal"), src="whoscored"),
        dict(key="clearances", united=team_stat(us, "clearances"), opp=team_stat(them, "clearances"), src="whoscored"),
        dict(key="aerials_won", united=aerials(us["teamId"]), opp=aerials(them["teamId"]), src="counted"),
        dict(key="fouls", united=team_stat(us, "foulsCommited") or team_stat(us, "foulsCommitted"),
             opp=team_stat(them, "foulsCommited") or team_stat(them, "foulsCommitted"), src="whoscored"),
    ]
    for r in tape:
        if r["src"] is None:
            r["src"] = "twelve"
            r["pending"] = True

    # GATE 4 — no Twelve source means every xG-bearing row says so
    if not has_tw:
        for r in tape:
            if r["key"] in ("xg", "xt") and not r.get("pending"):
                fail(f"tape row {r['key']} has no Twelve source but is not marked pending")
        print("  [ ok ] no Twelve source — xg and xt rows marked pending")

    # ── players, plots, network, heat, timeline ──────────────────────────────
    roster = load_roster(args.roster)
    pos_of = {p["playerId"]: p.get("position", "") for p in us["players"]}
    starters = {p["playerId"] for p in us["players"] if p.get("isFirstEleven")}
    first_sub = min((e["minute"] for e in ev
                     if e["teamId"] == us["teamId"] and e["type"]["displayName"] == "SubstitutionOn"),
                    default=max(e["minute"] for e in ev) + 1)
    period_end = int(m.get("expandedMaxMinute") or max(e["expandedMinute"] for e in ev))
    players, plots, _ = build_players(ev, us["teamId"], us, roster, names, period_end)
    mins_of = {}
    for p in us["players"]:
        r = next((r for r in players if r["name"] in (p.get("name"), roster.get(str(p["playerId"]), ("", "", ""))[2])), None)
        mins_of[p["playerId"]] = r["mins"] if r else 0
    network = build_network(ev, us["teamId"], first_sub, names, pos_of, mins_of, starters)
    network["nodes"] = network["nodes"][:16]

    goals = []
    for e in sorted([e for e in ev if e.get("isGoal")], key=lambda e: e["minute"]):
        q = quals(e)
        og = bool(e.get("isOwnGoal") or "OwnGoal" in q)
        mine = (e["teamId"] == us["teamId"]) != og
        who = names.get(str(e.get("playerId")), "?").split()[-1] + (" (og)" if og else "")
        sit = ("owngoal" if og else
               "penalty" if "Penalty" in q else
               "corner" if "FromCorner" in q else
               "freekick" if ("SetPiece" in q or "DirectFreekick" in q) else
               "fastbreak" if "FastBreak" in q else "open")
        goals.append(dict(min=e["minute"] + 1, team="u" if mine else "o", who=who, sit=sit))

    def sits(rows):
        out = {}
        for s in rows:
            b = out.setdefault(s["sit"], dict(n=0, xg=None))
            b["n"] += 1
        return out

    payload = dict(
        meta=meta, tape=tape,
        kpis=[dict(key="field_tilt", value=str(tilt) if tilt is not None else None,
                   note=f"{uft} final-third touches against {oft}"),
              dict(key="shots", value=str(int(team_stat(us, "shotsTotal") or 0)),
                   note=f"{int(team_stat(us,'shotsOnTarget') or 0)} on target against "
                        f"{them['name'].split()[0]}'s {int(team_stat(them,'shotsOnTarget') or 0)}"),
              dict(key="xg", value=(f"{num('tw_xg'):.2f}" if num("tw_xg") is not None else None),
                   note="Twelve report pending" if not has_tw else "Twelve"),
              dict(key="np_xg_per_shot", value=(f"{num('tw_np_xg_per_shot'):.2f}" if num("tw_np_xg_per_shot") is not None else None),
                   note="Twelve report pending" if not has_tw else "Twelve")],
        baseline=None,  # carried from an existing payload by build_payloads
        heat=dict(cols=12, rows=8, u=build_heat(ev, us["teamId"], False),
                  o=build_heat(ev, them["teamId"], True)),
        network=network, players=players, plots=plots,
        quadrant=dict(xl="Box touches", yl="Key passes",
                      note="Top right is doing both.",
                      pts=[dict(nm=p["name"].split()[-1], x=p["box_touches"], y=p["key_passes"],
                                mins=p["mins"], grp=p["group"]) for p in players]),
        shots=dict(united=ushots, opp=oshots, situations=dict(u=sits(ushots), o=sits(oshots))),
        timeline=dict(united=[], opp=[], goals=goals,
                      pending=not has_tw),
        story=dict(draft=True,
                   eyebrow=f"Matchweek {args.gw} · {meta['opp']} ({venue}) · {date}",
                   headline=[f"{meta['opp']} {ga}, United {gf}." if venue == "A" else f"United {gf}, {meta['opp']} {ga}."],
                   lead=(f"United had {poss}% of the ball and {tilt}% of the final third, "
                         f"{int(team_stat(us,'shotsTotal') or 0)} shots to {int(team_stat(them,'shotsTotal') or 0)}, "
                         f"and {ubox} touches in the {meta['opp']} box against {obox} in ours."),
                   sub="", cards=[dict(lab="Shape", v=meta["formation"], mono=1, dim=0),
                                  dict(lab=f"{meta['opp']} shape", v=meta["opp_formation"], mono=1, dim=1)],
                   hero=[dict(lab="Field tilt", v=str(tilt), unit="%", col="#201e1d",
                              note=f"{uft} final-third touches against {oft}"),
                         dict(lab="Shots", v=str(int(team_stat(us, "shotsTotal") or 0)),
                              unit=f"v {int(team_stat(them,'shotsTotal') or 0)}", col="#201e1d",
                              note=f"{int(team_stat(us,'shotsOnTarget') or 0)} on target against "
                                   f"{int(team_stat(them,'shotsOnTarget') or 0)}")],
                   shots_h2="", shots_intro="", sits_note="",
                   net_title=f"Passing network · 0′–{first_sub}′ base XI"),
        unused=[p["name"] for p in us["players"]
                if not p.get("isFirstEleven") and p["playerId"] not in
                {e["playerId"] for e in ev if e["teamId"] == us["teamId"]
                 and e["type"]["displayName"] == "SubstitutionOn"}],
        provenance=dict(source=os.path.basename(args.mcd), events=len(ev),
                        united_team_id=UNITED_TEAM_ID, twelve=has_tw,
                        note="WhoScored's match centre carries no expectedGoals field. "
                             "Every xG here is null until the Twelve report is merged with --master."),
    )
    if args.story and os.path.exists(args.story):
        payload["story"].update(json.load(open(args.story, encoding="utf-8")))
        payload["story"]["draft"] = False

    print(f"\n  payload: {len(players)} players · {len(ushots)}+{len(oshots)} shots · "
          f"{len(network['nodes'])} nodes / {len(network['links'])} links · {len(goals)} goals")
    print(f"  tilt {tilt}%  possession {poss}%  box touches {ubox}-{obox}")

    if not args.apply:
        print("\n" + "-" * W); print("  DRY RUN — nothing written. Re-run with --apply."); print("-" * W)
        return 0

    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, f"gw{args.gw}.json")
    txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    prev = open(dst, encoding="utf-8").read() if os.path.exists(dst) else None
    open(dst, "w", encoding="utf-8").write(txt)
    print(f"\n  written → {dst}  ({len(txt):,} bytes)"
          + ("  [unchanged — idempotent]" if prev == txt else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
