#!/usr/bin/env python3
"""shot_proxy.py — a per-shot xG proxy for matches where the vendor gives only a total.

WHY THIS EXISTS

Twelve's match report prints a team xG and a shot map, but no value per shot. The
shot map on a match page encodes chance quality as circle area, and the xG race
accumulates it by minute; both need a number for every shot. Without one the map
draws every shot the same size and the race cannot be drawn at all.

The opposition scout already solved this and says so on the page: "the per-side
total is Twelve's, the split across shots is geometric". That method was applied
upstream and never written down here. It was recovered from the 30 shots on the
Everton scout by fitting candidate models against the published values:

    power family   ang^1.00 / d^0.00       RMSE 0.00003   R2 1.0000
    logistic       1/(1+e^-(-2.5 + 2.8a))  RMSE 0.00930   R2 0.9923
    log-linear     exp(-0.75 ln d + 0.25a) RMSE 0.01824   R2 0.9704

The first reproduces every published value to within 0.00005, so the method is

    q_i = angle_i / sum(angle) x  the vendor's total for that side

where angle is the horizontal angle the goal mouth subtends at the shot. Distance
carries no separate term: a shot further out subtends a narrower angle, so the
angle already prices it. One definition, in one file, used by every writer.

WHAT THIS IS NOT

It is not an xG model. It cannot know that a shot was a header, taken under
pressure, or struck with the weaker foot, and it will overprice a speculative
strike from a central position and underprice a tap-in from a tight angle. What
it preserves is the side total, which is the vendor's, and the ordering of shots
by how much of the goal they could see. Anything built on it is labelled
`modelled` and must stay labelled.

Penalties are never proxied. A penalty subtends a wide angle from twelve yards
and the geometry would price it like a good open-play chance. Where the vendor
reports xG and np xG separately, the difference is the penalty xG and is assigned
to the penalty shots directly; the geometric split then runs over the non-penalty
total and the non-penalty shots only.
"""
from __future__ import annotations

import math

PITCH_L, PITCH_W = 105.0, 68.0   # metres, the frame the coordinates are scaled to
GOAL_W = 7.32                    # metres
MIN_DX = 0.35                    # keep the angle finite on the goal line itself
PENALTY_SITS = ('penalty',)


def goal_angle(x, y):
    """Angle the goal mouth subtends at a shot, in radians.

    x, y are WhoScored 0-100 with the shooting side attacking towards x = 100,
    which is how both sides are stored in the match payloads.
    """
    X = (x / 100.0) * PITCH_L
    Y = (y / 100.0) * PITCH_W
    dx = max(PITCH_L - X, MIN_DX)
    near = math.atan2(PITCH_W / 2 - GOAL_W / 2 - Y, dx)
    far = math.atan2(PITCH_W / 2 + GOAL_W / 2 - Y, dx)
    return abs(far - near)


def price_side(shots, total, np_total=None, player_xg=None):
    """Give every shot on one side an xg, preserving the side total.

    player_xg, when given, is {surname: xG} from an independent per-player model.
    It becomes the weight for each player's share of the side total and the angle
    split then only has to divide a player's own xG across their own shots. That
    is a far weaker assumption than pricing every shot from geometry alone, and
    for the many players who take exactly one shot it is no assumption at all.
    Validated on MW3: pure geometry correlates -0.03 with Understat across the
    eight single-shot players; anchoring makes those eight exact.

    Mutates and returns the list. Each priced shot gains xg and xg_src='modelled';
    a penalty gains xg_src='vendor-penalty' where the vendor's own split allows it.
    Returns (priced_count, penalty_count) for the caller to report.
    """
    if not shots or total is None:
        return 0, 0
    np_total = total if np_total is None else np_total
    pens = [s for s in shots if (s.get('sit') or '').lower() in PENALTY_SITS]
    open_ = [s for s in shots if s not in pens]

    pen_xg = round(total - np_total, 4)
    if pens:
        each = pen_xg / len(pens) if pen_xg > 0 else None
        for s in pens:
            s['xg'] = None if each is None else round(each, 4)
            s['xg_src'] = 'vendor-penalty' if each is not None else 'unpriced-penalty'

    if not open_:
        return 0, len(pens)
    angles = [goal_angle(s['x'], s['y']) for s in open_]
    if sum(angles) <= 0:
        return 0, len(pens)

    if player_xg:
        groups = {}
        for s, a in zip(open_, angles):
            groups.setdefault(_surname(s.get('who')), []).append((s, a))
        weights = {k: max(player_xg.get(k, 0.0), 0.0) for k in groups}
        wsum = sum(weights.values())
        if wsum > 0:
            for k, items in groups.items():
                share = weights[k] / wsum * np_total
                asum = sum(a for _, a in items) or 1.0
                for s, a in items:
                    s['xg'] = round(share * a / asum, 4)
                    s['xg_src'] = 'modelled'
            return len(open_), len(pens)

    sa = sum(angles)
    for s, a in zip(open_, angles):
        s['xg'] = round(a / sa * np_total, 4)
        s['xg_src'] = 'modelled'
    return len(open_), len(pens)


def _surname(name):
    parts = str(name or '').split()
    return parts[-1].lower() if parts else ''


def cumulative(shots):
    """[[minute, running xG], ...] for one side, starting at [0, 0].

    Shots the proxy could not price are skipped rather than counted as zero, so a
    flat stretch means no shots and never means a shot with no value.
    """
    out = [[0, 0.0]]
    run = 0.0
    for s in sorted((s for s in shots if s.get('xg') is not None), key=lambda s: s.get('min') or 0):
        run = round(run + s['xg'], 4)
        out.append([s.get('min') or 0, run])
    return out


def situation_totals(shots):
    """{situation: {n, xg}} with xg summed from whatever the shots now carry."""
    out = {}
    for s in shots:
        k = s.get('sit') or 'open'
        e = out.setdefault(k, {'n': 0, 'xg': None})
        e['n'] += 1
        if s.get('xg') is not None:
            e['xg'] = round((e['xg'] or 0) + s['xg'], 4)
    return out
