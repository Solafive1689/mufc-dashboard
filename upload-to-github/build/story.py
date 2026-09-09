#!/usr/bin/env python3
"""story.py — the narrative layer, counted from the ledger and checked against it.

Everything here is either
  (a) arithmetic over ledger rows — eras, streaks, rolling form, cumulative pace,
      where a 26/27 match sits in the 25/26 distribution — or
  (b) an authored note (build/notes/eras.json, turning-points.json,
      availability-26-27.json) that carries an `assert` the build verifies before
      it is allowed onto a page.

A ledger row is normalised to: round, opp, venue, result, gf, ga, pts, xg, oxg,
plus whatever else the caller left on it. Both seasons' ledgers pass through
`norm()` so one set of functions serves both.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
NOTES = os.path.join(HERE, 'notes')


def _load(name):
    p = os.path.join(NOTES, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def norm(rows):
    """Both ledgers, one shape. 25/26 rows use gw/ven/res; 26/27 use round/venue/result."""
    out = []
    for r in rows:
        n = dict(r)
        n['round'] = r.get('round', r.get('gw'))
        n['venue'] = r.get('venue', r.get('ven'))
        n['result'] = r.get('result', r.get('res'))
        n['pts'] = r.get('pts', 3 if n['result'] == 'W' else (1 if n['result'] == 'D' else 0))
        out.append(n)
    out.sort(key=lambda x: x['round'])
    return out


def _rec(rows):
    n = len(rows)
    w = sum(1 for r in rows if r['result'] == 'W')
    d = sum(1 for r in rows if r['result'] == 'D')
    l = sum(1 for r in rows if r['result'] == 'L')
    pts = sum(r['pts'] for r in rows)
    gf = sum(r['gf'] for r in rows); ga = sum(r['ga'] for r in rows)
    xg = [r['xg'] for r in rows if r.get('xg') is not None]
    oxg = [r['oxg'] for r in rows if r.get('oxg') is not None]
    return {'n': n, 'w': w, 'd': d, 'l': l, 'pts': pts, 'ppg': round(pts / n, 2) if n else None,
            'gf': gf, 'ga': ga, 'gd': gf - ga,
            'xg': round(sum(xg) / len(xg), 2) if xg else None, 'n_xg': len(xg),
            'xga': round(sum(oxg) / len(oxg), 2) if oxg else None,
            'xgd': round((sum(xg) - sum(oxg)) / len(xg), 2) if xg and len(xg) == len(oxg) else None}


# ----------------------------------------------------------------------------- eras
def eras(season, rows, fail):
    """Manager eras with the record inside each. Refuses if the authored rounds
    overlap or leave a gap — an era table that does not tile the season would
    quietly drop matches from every split built on it."""
    notes = (_load('eras.json') or {}).get('seasons', {}).get(season)
    if not notes:
        return []
    rows = norm(rows)
    covered = []
    for e in notes:
        a, b = e['from_round'], e['to_round']
        if a > b:
            fail(f"eras.json {season}: {e['id']} runs from round {a} to {b}")
        covered.extend(range(a, b + 1))
    if sorted(covered) != list(range(min(covered), max(covered) + 1)) or len(covered) != len(set(covered)):
        fail(f"eras.json {season}: eras overlap or leave a gap ({sorted(set(covered))[:5]}…)")
    if min(covered) != 1:
        fail(f"eras.json {season}: first era starts at round {min(covered)}, not 1")
    out = []
    for e in notes:
        inside = [r for r in rows if e['from_round'] <= r['round'] <= e['to_round']]
        rec = _rec(inside)
        out.append({'id': e['id'], 'name': e['name'], 'role': e['role'],
                    'from_round': e['from_round'], 'to_round': e['to_round'],
                    'from': e.get('from'), 'to': e.get('to'), 'note': e.get('note'),
                    'source': e.get('source'), 'played': rec['n'], **rec})
    return out


# ----------------------------------------------------------------------------- streaks
def _runs(rows, keep):
    """Longest run of consecutive rows satisfying keep(row): (length, from, to)."""
    best, cur, start = (0, None, None), 0, None
    for r in rows:
        if keep(r):
            if cur == 0:
                start = r['round']
            cur += 1
            if cur > best[0]:
                best = (cur, start, r['round'])
        else:
            cur = 0
    return {'len': best[0], 'from': best[1], 'to': best[2]}


def streaks(rows):
    rows = norm(rows)
    # the current run, read backwards from the last match
    cur_kind, cur_len = None, 0
    for r in reversed(rows):
        k = r['result']
        if cur_kind is None:
            cur_kind = k
        if k == cur_kind:
            cur_len += 1
        else:
            break
    return {
        'win': _runs(rows, lambda r: r['result'] == 'W'),
        'unbeaten': _runs(rows, lambda r: r['result'] in ('W', 'D')),
        'winless': _runs(rows, lambda r: r['result'] in ('D', 'L')),
        'losing': _runs(rows, lambda r: r['result'] == 'L'),
        'scoring': _runs(rows, lambda r: r['gf'] > 0),
        'clean_sheets': _runs(rows, lambda r: r['ga'] == 0),
        'conceding': _runs(rows, lambda r: r['ga'] > 0),
        'current': {'kind': cur_kind, 'len': cur_len},
    }


# ----------------------------------------------------------------------------- form + pace
def cumulative(rows):
    """Per round: cumulative points, goals for/against, xG difference (null once any xG is missing)."""
    rows = norm(rows)
    pts = gf = ga = 0; xgd = 0.0; xg_ok = True
    out = []
    for r in rows:
        pts += r['pts']; gf += r['gf']; ga += r['ga']
        if r.get('xg') is None or r.get('oxg') is None:
            xg_ok = False
        else:
            xgd += r['xg'] - r['oxg']
        out.append({'round': r['round'], 'pts': pts, 'gf': gf, 'ga': ga, 'gd': gf - ga,
                    'xgd': round(xgd, 2) if xg_ok else None, 'result': r['result'],
                    'opp': r['opp'], 'venue': r['venue'], 'score': f"{r['gf']}-{r['ga']}"})
    return out


def rolling(rows, k=5):
    """Rolling points per game over the last k matches, from the k-th match on."""
    rows = norm(rows)
    out = []
    for i in range(len(rows)):
        if i + 1 < k:
            out.append({'round': rows[i]['round'], 'ppg': None})
            continue
        win = rows[i + 1 - k:i + 1]
        out.append({'round': rows[i]['round'], 'ppg': round(sum(r['pts'] for r in win) / k, 2)})
    return out


def pace(rows_now, rows_base):
    """26/27 against 25/26 at the same matchweek: cumulative points and xG difference."""
    now = {c['round']: c for c in cumulative(rows_now)}
    base = {c['round']: c for c in cumulative(rows_base)}
    out = []
    for rnd in sorted(base):
        b = base[rnd]; n = now.get(rnd)
        out.append({'round': rnd, 'base_pts': b['pts'], 'base_xgd': b['xgd'], 'base_gd': b['gd'],
                    'pts': n['pts'] if n else None, 'xgd': n['xgd'] if n else None,
                    'gd': n['gd'] if n else None})
    played = [o for o in out if o['pts'] is not None]
    at = played[-1] if played else None
    return {'rows': out, 'at': {'round': at['round'], 'pts': at['pts'], 'base_pts': at['base_pts'],
                                'delta': at['pts'] - at['base_pts'],
                                'xgd': at['xgd'], 'base_xgd': at['base_xgd']} if at else None}


# ----------------------------------------------------------------------------- distribution
def percentile_of(values, v):
    """Share of the reference values at or below v, 0–100."""
    vals = [x for x in values if x is not None]
    if not vals or v is None:
        return None
    return round(100 * sum(1 for x in vals if x <= v) / len(vals))


def against_baseline(rows_now, rows_base, keys):
    """Where each 26/27 match sits in the 25/26 distribution of each metric.

    keys: {metric_key: (ledger_field, label, direction)}. A metric absent from
    the 25/26 ledger yields no row rather than a guessed one."""
    base = norm(rows_base)
    now = norm(rows_now)
    out = []
    for key, (field, label, direction) in keys.items():
        ref = [r.get(field) for r in base if r.get(field) is not None]
        if len(ref) < 10:
            continue
        s = sorted(ref)
        med = s[len(s) // 2] if len(s) % 2 else round((s[len(s) // 2 - 1] + s[len(s) // 2]) / 2, 2)
        out.append({'key': key, 'label': label, 'direction': direction, 'n_base': len(ref),
                    'min': s[0], 'q1': s[len(s) // 4], 'median': med, 'q3': s[(3 * len(s)) // 4], 'max': s[-1],
                    'matches': [{'round': r['round'], 'opp': r['opp'], 'value': r.get(field),
                                 'pct': percentile_of(ref, r.get(field))} for r in now]})
    return out


# ----------------------------------------------------------------------------- turning points
def turning_points(season, rows, fail, ctx=None):
    """Authored points, each verified against the ledger before it is published."""
    ctx = ctx or {}
    notes = (_load('turning-points.json') or {}).get('seasons', {}).get(season) or []
    by_round = {r['round']: r for r in norm(rows)}
    out = []
    for tp in notes:
        a = tp.get('assert')
        ev = {}
        if a:
            if 'round' in a:
                r = by_round.get(a['round'])
                if r is None:
                    fail(f"turning point '{tp['id']}' asserts round {a['round']}, which has not been played")
                if a.get('result') and r['result'] != a['result']:
                    fail(f"turning point '{tp['id']}': asserts {a['result']}, ledger has {r['result']}")
                if a.get('score') and f"{r['gf']}-{r['ga']}" != a['score']:
                    fail(f"turning point '{tp['id']}': asserts {a['score']}, ledger has {r['gf']}-{r['ga']}")
                if a.get('opp') and r['opp'] != a['opp']:
                    fail(f"turning point '{tp['id']}': asserts opponent {a['opp']}, ledger has {r['opp']}")
                ev = {'round': r['round'], 'opp': r['opp'], 'venue': r['venue'], 'result': r['result'],
                      'score': f"{r['gf']}-{r['ga']}", 'xg': r.get('xg'), 'oxg': r.get('oxg'), 'match': r.get('match')}
            if a.get('goal'):
                goals = (ctx.get('goals') or {}).get(a['round'], [])
                hit = [g for g in goals if g['min'] == a['goal']['min'] and g['team'] == a['goal']['team']]
                if not hit:
                    fail(f"turning point '{tp['id']}': no {a['goal']['team']} goal at {a['goal']['min']}′ in round {a['round']}")
                ev['goal'] = hit[0]
            if a.get('player_goals'):
                strip = ctx.get('player_goals') or {}
                for pid, g in a['player_goals'].items():
                    got = strip.get((a['round'], pid))
                    if got != g:
                        fail(f"turning point '{tp['id']}': asserts {pid} scored {g} in round {a['round']}, counted {got}")
                ev['player_goals'] = a['player_goals']
            if a.get('availability'):
                av = ctx.get('availability') or {}
                if a['availability'] not in av:
                    fail(f"turning point '{tp['id']}': {a['availability']} is not in availability-26-27.json")
                ev['availability'] = av[a['availability']]
        out.append({'id': tp['id'], 'round': tp.get('round'), 'kind': tp['kind'], 'title': tp['title'],
                    'body': tp['body'], 'source': tp.get('source'), 'evidence': ev})
    return out


# ----------------------------------------------------------------------------- availability
def availability(matches, strip_ids, fail):
    """The current unavailable list, plus the record in the matches each player missed.

    matches: played 26/27 match payloads. A player 'missed' a match when he is
    neither in its players list nor in its unused list."""
    notes = _load('availability-26-27.json')
    if not notes:
        return None
    out = []
    for p in notes['players']:
        if p.get('returned'):
            continue
        missed = []
        for m in matches:
            names_on = {pl['player_id'] for pl in m['players']}
            unused = set(m.get('unused') or [])
            # unused is a list of names, not ids; match on name too
            if p['player_id'] in names_on or p['name'] in unused:
                continue
            meta = m['meta']
            missed.append({'round': meta['round'], 'opp': meta['opp'], 'venue': meta['venue'],
                           'result': meta['result'], 'score': meta['score'], 'match': meta['match_id']})
        rec = _rec([{'round': x['round'], 'result': x['result'], 'gf': int(x['score'].split('-')[0]),
                     'ga': int(x['score'].split('-')[1]), 'pts': 3 if x['result'] == 'W' else (1 if x['result'] == 'D' else 0)}
                    for x in missed]) if missed else None
        out.append({**{k: v for k, v in p.items()}, 'missed': missed, 'record_without': rec})
    return {'checked': notes['checked'], 'source': notes['source'], 'players': out,
            'out': sum(1 for p in out if p['status'] == 'out'),
            'doubt': sum(1 for p in out if p['status'] == 'doubt')}


def with_without(rows, cells_by_player, ids):
    """25/26 record with and without each of the given players, from the availability
    grid (S started, N came on, B unused, O not in squad).

    'Without' means not in the matchday squad at all — the nearest thing the grid
    holds to unavailable. An unused substitute was available and left out, which
    is a selection, so those matches count on neither side. Four matches a side
    is the floor: two results are a coincidence with a label."""
    rows = norm(rows)
    out = []
    for pid, nm in ids:
        cells = cells_by_player.get(pid)
        if not cells:
            continue
        w = [r for r in rows if cells[r['round'] - 1] in ('S', 'N')]
        wo = [r for r in rows if cells[r['round'] - 1] == 'O']
        if len(wo) < 4 or len(w) < 4:
            continue
        out.append({'player_id': pid, 'name': nm, 'with': _rec(w), 'without': _rec(wo),
                    'bench': sum(1 for r in rows if cells[r['round'] - 1] == 'B')})
    out.sort(key=lambda x: -(x['with']['ppg'] - x['without']['ppg']))
    return out


# ----------------------------------------------------------------------------- leads
def lead_windows(leads):
    """What happened after United went ahead, from the v2 LEADS windows.

    A window opens at a goal (og = 'scored' when United scored it) and closes at
    the next goal or full time (eb). Interventions (iv) are substitutions and
    shape changes inside the window with the minutes elapsed since it opened —
    the nearest thing the data holds to a decision on the bench. Only windows
    United opened are counted as 'leads'; the rest are the opponent's."""
    ours = [l for l in leads if l['og'] == 'scored']
    held = [l for l in ours if l['eb'] == 'full time']
    lost = [l for l in ours if l['eb'] == 'we conceded']
    extended = [l for l in ours if l['eb'] == 'we scored']
    first_sub = [min(i['el'] for i in l['iv'] if i['kind'] == 'sub') for l in ours if any(i['kind'] == 'sub' for i in l['iv'])]
    first_sub.sort()
    med = first_sub[len(first_sub) // 2] if first_sub else None
    def rec(rows):
        d = [r['d'] for r in rows]
        return {'n': len(rows), 'minutes': sum(d), 'median_len': sorted(d)[len(d) // 2] if d else None}
    by_change = {'with_sub': [l for l in ours if any(i['kind'] == 'sub' for i in l['iv'])],
                 'no_sub': [l for l in ours if not any(i['kind'] == 'sub' for i in l['iv'])]}
    shape = [l for l in ours if any(i['kind'] == 'shape' for i in l['iv'])]
    return {
        'windows': len(leads), 'leads': len(ours), 'held': rec(held), 'lost': rec(lost), 'extended': rec(extended),
        'median_minutes_to_first_sub': med, 'subs_in_leads': sum(1 for l in ours for i in l['iv'] if i['kind'] == 'sub'),
        'shape_changes_in_leads': len(shape),
        'lost_share_with_sub': round(sum(1 for l in by_change['with_sub'] if l['eb'] == 'we conceded') / len(by_change['with_sub']), 2) if by_change['with_sub'] else None,
        'lost_share_no_sub': round(sum(1 for l in by_change['no_sub'] if l['eb'] == 'we conceded') / len(by_change['no_sub']), 2) if by_change['no_sub'] else None,
        'n_with_sub': len(by_change['with_sub']), 'n_no_sub': len(by_change['no_sub']),
        'rows': sorted([{'round': l['gw'], 'opp': l['o'], 'venue': l['v'], 'from': l['s'], 'to': l['e'], 'len': l['d'], 'ended': l['eb'],
                         'subs': sum(1 for i in l['iv'] if i['kind'] == 'sub'), 'shape': sum(1 for i in l['iv'] if i['kind'] == 'shape'),
                         'first_sub_after': min((i['el'] for i in l['iv'] if i['kind'] == 'sub'), default=None)} for l in ours],
                       key=lambda r: (r['round'], r['from'])),
    }
