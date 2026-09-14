#!/usr/bin/env python3
"""build_payloads.py — project the pipeline's data into one JSON payload per route.

House convention: dry-run by default, --apply to write, refuse on a failed gate.

Source for this first cut is the v2 dashboard's data object (mufc.js: D, LEADS, IPS, IPS2),
which already carries every grain the pipeline produces. Swap `load_source()` for the CSV
readers when the pipeline emits them directly; every projection below reads from the
`src` dict only, so nothing else changes.

Routes emitted (data/):
  index.json                       seasons · fixtures · teams · metric registry · thresholds
  crests.json                      crest data-URIs, loaded lazily
  26-27/season.json                running season: ledger, KPI row, season v baseline, locks
  25-26/season.json                finished season: ledger, game state, leads, trap, phase, adjusted
  26-27/matches/<slug>.json        one per played match: story, tape, timeline, shots, heat, network, players
  26-27/opponents/<code>.json      one per scouted fixture
  26-27/squad.json                 season-to-date strip, per-90 baseline, goals & assists, availability
  26-27/players/<player_id>.json   match log + touch plots + season summary
  league/25-26.json                table, ranks, tiers, dropped points, best wins, validation
"""
import argparse, json, math, os, re, sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import player_id  # noqa: E402  the one definition, shared with the ingest
import shot_proxy  # noqa: E402  the geometric per-shot split, shared with the scout
import story  # noqa: E402  eras, streaks, pace, turning points — counted, then checked

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data')
FLOOR = 450            # minutes before a per-90 is shown
LOCKS = {'dominance': 10, 'gamestate': 10, 'adjusted': 15, 'league': 10}
COMP_NAMES = {'PL': 'Premier League', 'UCL': 'Champions League', 'EFL': 'Carabao Cup', 'FAC': 'FA Cup'}
ROUND_PREFIX = {'PL': 'MW', 'UCL': 'MD', 'EFL': 'R', 'FAC': 'R'}

# ----------------------------------------------------------------------------- helpers
def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def per90(total, mins):
    if mins is None or mins < FLOOR:
        return None
    return round(total / mins * 90, 2)

def match_slug(gw, code):
    return f"mw{gw:02d}-{code.lower()}"


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def built_matches(files):
    """Every played 26/27 match payload written so far this run, in round order.

    The season and squad projections read from here rather than from a list of
    gameweek names, so a matchweek that reaches data/26-27/matches/ reaches the
    season page in the same run. Nothing downstream needs to know whether the
    payload came from the v2 source or from ingest_whoscored.py."""
    return sorted((p for name, p in files.items()
                   if name.startswith('26-27/matches/') and name.endswith('.json')
                   and p['meta'].get('comp', 'PL') == 'PL'),   # the season ledger is the league
                  key=lambda p: p['meta']['round'])


def built_cup_matches(files):
    return sorted((p for name, p in files.items()
                   if name.startswith('26-27/matches/') and p['meta'].get('comp', 'PL') != 'PL'),
                  key=lambda p: p['meta']['date'])


def tape_value(payload, key, side='united'):
    """One side of a tape row, or None when the row is still pending.

    A pending row carries a null and must stay null: averaging over it would
    quietly change the denominator without changing the label."""
    row = next((r for r in payload['tape'] if r['key'] == key), None)
    if row is None or row.get('pending'):
        return None
    return row.get(side)


def kpi_value(payload, key):
    k = next((k for k in payload['kpis'] if k['key'] == key), None)
    if k is None or k.get('value') in (None, ''):
        return None
    try:
        return float(k['value'])
    except (TypeError, ValueError):
        return None


def ledger_row(m):
    """One played match projected into the shape the season ledger uses."""
    meta = m['meta']
    ft = kpi_value(m, 'field_tilt')
    return {'round': meta['round'], 'opp': meta['opp'], 'code': meta['code'], 'venue': meta['venue'],
            'date': meta['date'], 'gf': meta['gf'], 'ga': meta['ga'], 'result': meta['result'],
            'pts': 3 if meta['result'] == 'W' else (1 if meta['result'] == 'D' else 0),
            'xg': meta.get('xg'), 'oxg': meta.get('oxg'),
            'possession': tape_value(m, 'possession_pct'), 'field_tilt': ft,
            'chance_quality': kpi_value(m, 'np_xg_per_shot'),
            'shots': tape_value(m, 'shots'), 'pass_accuracy': tape_value(m, 'pass_accuracy'),
            'clearances': tape_value(m, 'clearances'),
            'story_headline': (m.get('story') or {}).get('headline'),
            'match': meta['match_id'],
            # who was on the pitch, so the season page can be filtered "with X" /
            # "without X" without loading every match payload
            'xi': [p['player_id'] for p in m.get('players', []) if p.get('started')],
            'used': [p['player_id'] for p in m.get('players', []) if p.get('mins')],
            'formation': meta.get('formation'), 'opp_formation': meta.get('opp_formation')}


def avg(rows, key, d=2):
    """Mean over the rows that carry the column, with the count it was taken over.

    Returns (value, n). A metric whose supplier has not reported yet has a
    smaller n than the season, and the caller is expected to say so rather than
    average a null as a zero."""
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None, 0
    return round(sum(vals) / len(vals), d), len(vals)

def fail(msg):
    print('GATE FAILED:', msg, file=sys.stderr)
    sys.exit(2)

# ----------------------------------------------------------------------------- source
INGEST_DIR = os.path.join(HERE, 'matches')


def load_ingested():
    """Gameweeks produced by ingest_whoscored.py, keyed by round.

    These arrive already in the output payload shape, so they are written through
    rather than passed to build_match. Anything the v2 source does not know about
    (a gameweek captured after the v2 export) comes in this way."""
    out = {}
    if not os.path.isdir(INGEST_DIR):
        return out
    for fn in sorted(os.listdir(INGEST_DIR)):
        m = re.fullmatch(r'gw(\d+)\.json', fn)
        if m:
            out[int(m.group(1))] = json.load(open(os.path.join(INGEST_DIR, fn), encoding='utf-8'))
    return out


def load_ingested_cups():
    """Champions League matchdays and cup rounds, keyed by fixture_id (UCL-01-SAB).
    They get a match payload and a player-log row; the league ledger stays league."""
    out = {}
    if not os.path.isdir(INGEST_DIR):
        return out
    for fn in sorted(os.listdir(INGEST_DIR)):
        m = re.fullmatch(r'(ucl|efl|fac)(\d+)\.json', fn)
        if m:
            p = json.load(open(os.path.join(INGEST_DIR, fn), encoding='utf-8'))
            out[f"{m.group(1).upper()}-{int(m.group(2)):02d}-{p['meta']['code']}"] = p
    return out


def as_source_gw(payload):
    """Adapt an ingested payload to the handful of D.gw<N> fields build_players
    reads, so player pages pick up the gameweek without a second code path."""
    meta = payload['meta']
    roster = []
    for pl in payload['players']:
        att, cmp_ = pl['passes_att'], pl['passes_cmp']
        da, dc = (pl['dribbles'].split('/') + ['0', '0'])[:2]
        # The ingest publishes def_actions as one number; the per-event codes in the
        # player's defensive plot (t i c b ch r a, with outcome) let the log carry
        # the same tackles / interceptions / clearances columns the v2 weeks have.
        d = (payload.get('plots', {}).get(pl['player_id']) or {}).get('d') or []
        cnt = lambda code, ok=None: sum(1 for x in d if x[2] == code and (ok is None or bool(x[3]) == ok))
        v = {'minutes': pl['mins'], 'goals': pl['goals'], 'assists': pl['assists'],
             'shots': pl['shots'], 'shots_on_target': pl['sot'],
             'key_passes': pl['key_passes'], 'passes_attempted': att,
             'passes_completed': cmp_, 'pass_accuracy_pct': pl['pass_acc'],
             'final_third_passes': pl['final_third_passes'],
             'passes_into_box': pl['passes_into_box'], 'touches': pl['touches'],
             'box_touches': pl['box_touches'], 'def_actions': pl['def_actions'],
             'recoveries': pl['recoveries'], 'dispossessed': pl['dispossessed'],
             'aerials_won': pl['aerials_won'], 'aerials_lost': pl['aerials_lost'],
             'dribbles_completed': int(dc) if str(dc).isdigit() else 0,
             'dribbles_attempted': int(da) if str(da).isdigit() else 0,
             'tackles': cnt('t'), 'tackles_won': cnt('t', True), 'interceptions': cnt('i'),
             'clearances': cnt('c'), 'blocks': cnt('b')}
        # published-by-WhoScored fields the extended ingest emits; absent on older captures
        for k in ('rating', 'motm', 'yellow', 'red', 'on', 'off', 'captain'):
            if pl.get(k) is not None:
                v[k] = pl[k]
        roster.append({'nm': pl['name'], 'sh': pl['shirt'], 'pos': pl['pos'], 'grp': pl['group'],
                       'st': int(pl['started']), 'mins': pl['mins'], 'role': pl['pos'], 'v': v})
    plots = {pl['name']: payload['plots'].get(pl['player_id'], {}) for pl in payload['players']}
    return {'opp': meta['opp'], 'ven': meta['venue'], 'score': meta['score'],
            'roster': roster, 'plots': plots}


def load_source():
    js = open(os.path.join(HERE, 'v2_source.json')).read()
    return json.loads(js)

# ----------------------------------------------------------------------------- registry
SRC = {'ws': 'whoscored', 'tw': 'twelve', 'ev': 'counted', 'derived': 'derived'}
REGISTRY = OrderedDict([
    # key: (label, unit, fmt, source, direction, group)
    ('possession_pct',  ('Possession',            '%',  '1',  'whoscored', 'neutral', 'ball')),
    ('xg',              ('Expected goals',        '',   '2',  'twelve',    'higher',  'chances')),
    ('xt',              ('Expected threat',       '',   '2',  'twelve',    'higher',  'chances')),
    ('shots',           ('Shots',                 '',   '0',  'whoscored', 'higher',  'chances')),
    ('shots_on_target', ('On target',             '',   '0',  'whoscored', 'higher',  'chances')),
    ('box_touches',     ('Touches in opp box',    '',   '0',  'counted',   'higher',  'territory')),
    ('big_chances',     ('Big chances',           '',   '0',  'whoscored', 'higher',  'chances')),
    ('corners',         ('Corners',               '',   '0',  'whoscored', 'neutral', 'set-pieces')),
    ('passes',          ('Passes',                '',   '0',  'whoscored', 'neutral', 'ball')),
    ('pass_accuracy',   ('Pass accuracy',         '%',  '1',  'whoscored', 'higher',  'ball')),
    ('tackles',         ('Tackles',               '',   '0',  'whoscored', 'neutral', 'defence')),
    ('clearances',      ('Clearances',            '',   '0',  'whoscored', 'neutral', 'defence')),
    ('aerials_won',     ('Aerials won',           '',   '0',  'counted',   'higher',  'defence')),
    ('fouls',           ('Fouls',                 '',   '0',  'whoscored', 'lower',   'discipline')),
    ('field_tilt',      ('Field tilt',            '%',  '0',  'twelve',    'higher',  'territory')),
    ('np_xg_per_shot',  ('Chance quality',        '',   '2',  'twelve',    'higher',  'chances')),
    ('points',          ('Points per game',       '',   '2',  'derived',   'higher',  'results')),
    ('goals_for',       ('Goals scored',          '',   '2',  'derived',   'higher',  'results')),
    ('goals_against',   ('Goals conceded',        '',   '2',  'derived',   'lower',   'results')),
    ('xg_diff',         ('Expected-goal difference','', '2',  'derived',   'higher',  'chances')),
    ('xga',             ('Expected goals against','',   '2',  'twelve',    'lower',   'chances')),
])
TAPE_KEYS = {  # v2 summary label -> registry key
    'Possession %': 'possession_pct', 'xG (Twelve)': 'xg', 'xT (Twelve)': 'xt', 'Shots': 'shots',
    'On target': 'shots_on_target', 'Touches in opp box': 'box_touches', 'Big chances': 'big_chances',
    'Corners': 'corners', 'Passes': 'passes', 'Pass accuracy %': 'pass_accuracy', 'Tackles': 'tackles',
    'Clearances': 'clearances', 'Aerials won': 'aerials_won', 'Fouls': 'fouls'}

def registry(src):
    opp_share = {m['lab']: m['r2'] for m in src['D']['tierMetrics']}
    share_map = {'Points per game': 'Points', 'Expected-goal difference': 'xG difference', 'Possession': 'Possession %',
                 'Chance quality': 'Chance quality', 'Shots': 'Shots (open play)'}
    out = []
    for k, (lab, unit, fmt, source, direction, group) in REGISTRY.items():
        out.append({'key': k, 'label': lab, 'unit': unit, 'fmt': fmt, 'source': source, 'direction': direction,
                    'group': group, 'opp_share': opp_share.get(share_map.get(lab)),
                    'floor': FLOOR if group in ('per90',) else None,
                    'caveat': '2026_27-001' if k == 'xt' else None})
    return out

# ----------------------------------------------------------------------------- index
def build_index(src, ingested=None, cups_played=None):
    D = src['D']
    fixtures = []
    played = {1: 'gw1', 2: 'gw2'}
    ingested = ingested or {}
    cups_played = cups_played or {}
    for f in D['fix']:
        gw = f['rd'] if f['comp'] == 'PL' else None
        fx = {'fixture_id': f"{f['comp']}-{f['rd']:02d}-{f['code']}", 'comp': f['comp'], 'round': f['rd'], 'date': f['date'],
              'ko': f['ko'], 'opp': f['opp'], 'short': f['short'], 'code': f['code'], 'venue': f['ven'], 'tv': f['tv'],
              'rest_days': f['rest'], 'congested': f['cong'], 'status': 'scheduled', 'match': None, 'scout': None}
        if f['comp'] == 'PL' and gw in played:
            g = D[played[gw]]
            fx['status'] = 'played'; fx['score'] = g['score']; fx['xg'] = g['xg']; fx['oxg'] = g['oxg']
            gf, ga = [int(x) for x in g['score'].split('-')]
            fx['result'] = 'W' if gf > ga else ('D' if gf == ga else 'L')
            fx['match'] = match_slug(gw, f['code'])
        if f['comp'] == 'PL' and gw in ingested:
            im = ingested[gw]['meta']
            fx['status'] = 'played'; fx['score'] = im['score']; fx['xg'] = im['xg']; fx['oxg'] = im['oxg']
            fx['result'] = im['result']; fx['match'] = im['match_id']
        # A scout attaches itself to whatever fixture its authored file names, so
        # adding one is adding a file. This used to be `if gw == 3: 'eve'`.
        sc = SCOUTS.get(fx['fixture_id'])
        if sc:
            fx['scout'] = sc['code']   # stays reachable after the fixture is played
        fixtures.append(fx)
    # Domestic cups. The v2 fixture layer was 38 + 8 and the calendar said so in
    # its footer; the Carabao Cup tie drawn on 26 August had nowhere to go. They
    # are authored in build/fixtures/cups.json and merged here in date order, so
    # the calendar, the rest-days column and the competition filter all see them.
    for c in load_cups():
        fixtures.append({'fixture_id': f"{c['comp']}-{c['round']:02d}-{c['code']}", 'comp': c['comp'], 'round': c['round'],
                         'round_label': c.get('round_label'), 'date': c['date'], 'ko': c['ko'], 'opp': c['opp'],
                         'short': c['short'], 'code': c['code'], 'venue': c['venue'], 'tv': c.get('tv'),
                         'rest_days': None, 'congested': False, 'status': 'scheduled', 'match': None, 'scout': None,
                         'source': c.get('source')})
    for fx in fixtures:
        cp = cups_played.get(fx['fixture_id'])
        if cp:
            im = cp['meta']
            fx['status'] = 'played'; fx['score'] = im['score']; fx['xg'] = im.get('xg'); fx['oxg'] = im.get('oxg')
            fx['result'] = im['result']; fx['match'] = im['match_id']
    fixtures.sort(key=lambda f: (f['date'], f['ko'] or ''))
    # rest days are recomputed over the merged list — a cup tie three days before
    # a league match is exactly the congestion the column exists to show
    prev = None
    from datetime import date as _date
    for f in fixtures:
        d = _date.fromisoformat(f['date'])
        f['rest_days'] = (d - prev).days if prev else None
        f['congested'] = bool(f['rest_days'] is not None and f['rest_days'] <= 3)
        prev = d
    teams = {}
    for r in D['lg']['table']:
        teams[r['team']] = {'name': r['team'], 'tier_25_26': r['tier'], 'pos_25_26': r['pos']}
    counts = OrderedDict()
    for f in fixtures:
        counts[f['comp']] = counts.get(f['comp'], 0) + 1
    return {
        'seasons': [{'id': '26-27', 'label': '2026/27', 'status': 'running', 'baseline': '25-26'},
                    {'id': '25-26', 'label': '2025/26', 'status': 'complete', 'baseline': None}],
        'fixtures': fixtures,
        'fixture_counts': counts,
        'comp_names': COMP_NAMES,
        'round_prefix': ROUND_PREFIX,
        'teams': teams,
        'registry': registry(src),
        'thresholds': dict(LOCKS, floor_minutes=FLOOR),
        'tier_names': dict(D['tierName'], new='Not in the 25/26 Premier League'),
        'generated_from': 'mufc.js (v2 payload) via build_payloads.py',
    }


def load_cups():
    path = os.path.join(HERE, 'fixtures', 'cups.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        cups = json.load(fh).get('fixtures', [])
    for c in cups:
        for k in ('comp', 'round', 'date', 'opp', 'code', 'venue'):
            if c.get(k) in (None, ''):
                fail(f"fixtures/cups.json: a fixture is missing '{k}'")
        if c['comp'] not in COMP_NAMES:
            fail(f"fixtures/cups.json: competition '{c['comp']}' has no name in COMP_NAMES")
    return cups

# ----------------------------------------------------------------------------- match
def build_match(src, key, gw):
    D = src['D']; g = D[key]
    fx = next(f for f in D['fix'] if f['comp'] == 'PL' and f['rd'] == gw)
    gf, ga = [int(x) for x in g['score'].split('-')]
    tape = []
    for s in g['summary']:
        k = TAPE_KEYS.get(s['lab'])
        if k is None:
            fail(f"tape label '{s['lab']}' has no registry key")
        tape.append({'key': k, 'united': s['u'], 'opp': s['o'], 'src': SRC[s['src']]})
    baseline = {}
    for d in D['season']['dists']:
        m = {'ws_possession_pct': 'possession_pct', 'tw_xg': 'xg', 'ws_shots': 'shots', 'tw_field_tilt_pct': 'field_tilt'}.get(d['col'])
        if m: baseline[m] = {'median': d['med'], 'q1': d['q1'], 'q3': d['q3'], 'n': 38}
    players = []
    for p in g['players']:
        players.append({'player_id': player_id(p['nm']), 'name': p['nm'], 'shirt': p['sh'], 'pos': p['pos'], 'group': p['grp'],
                        'started': bool(p['st']), 'mins': p['mins'], 'touches': p['tch'], 'box_touches': p['box'],
                        'passes_att': p['pa'], 'passes_cmp': p['pc'], 'pass_acc': p['acc'], 'key_passes': p['kp'],
                        'final_third_passes': p['f3'], 'passes_into_box': p['pib'], 'shots': p['sh_'], 'sot': p['sot'],
                        'dribbles': p['drb'], 'def_actions': p['def'], 'recoveries': p['rec'], 'dispossessed': p['dis'],
                        'aerials_won': p['aw'], 'aerials_lost': p['al'], 'goals': p['g'], 'assists': p['a']})
    story = g['story']
    return {
        'meta': {'match_id': match_slug(gw, fx['code']), 'season': '26-27', 'comp': 'PL', 'round': gw, 'date': g['date'],
                 'opp': g['opp'], 'code': fx['code'], 'venue': g['ven'], 'score': g['score'], 'gf': gf, 'ga': ga,
                 'result': 'W' if gf > ga else ('D' if gf == ga else 'L'), 'formation': g['form'], 'opp_formation': g['oform'],
                 'xg': g['xg'], 'oxg': g['oxg'], 'sample': {'matches': 1}, 'sources': ['whoscored', 'twelve', 'counted'],
                 'tv': fx['tv'], 'ko': fx['ko']},
        'story': {'eyebrow': story['meta'], 'headline': [story['h1a'], story['h1b']], 'lead': story['lead'], 'sub': story['sub'],
                  'cards': story['cards'], 'hero': story['hero'], 'shots_h2': story['shotsH2'], 'shots_intro': story['shotsIntro'],
                  'sits_note': story['sitsNote'], 'net_title': story['netTitle']},
        'kpis': [{'key': 'field_tilt', 'value': story['hero'][0]['v'], 'note': story['hero'][0]['note']},
                 {'key': 'shots', 'value': story['hero'][1]['v'], 'note': story['hero'][1]['note']},
                 {'key': 'xg', 'value': story['hero'][2]['v'], 'note': story['hero'][2]['note']},
                 {'key': 'np_xg_per_shot', 'value': story['hero'][3]['v'], 'note': story['hero'][3]['note']}],
        'tape': tape, 'baseline': baseline,
        'timeline': {'united': g['tl']['u'], 'opp': g['tl']['o'], 'goals': g['tl']['goals']},
        'shots': {'united': g['shots'], 'opp': g['oshots'], 'situations': g['sits']},
        'heat': g['heat'], 'network': {'nodes': g['nodes'], 'links': g['links']},
        'players': players, 'unused': g['unused'], 'quadrant': g['quad'],
        'plots': {player_id(k): v for k, v in g['plots'].items()},
    }

PUBLISHED_FIELDS = ('rating', 'motm', 'yellow', 'red', 'on', 'off', 'captain')


def graft_published(base, ing):
    """Copy the extended ingest's published blocks onto a v2-built match payload.

    Additive only: nothing the v2 payload already says is touched. Refuses if the
    two disagree on the scoreline or on who played — a graft from the wrong
    capture would put one match's ratings on another match's page."""
    if ing['meta'].get('score') != base['meta'].get('score'):
        fail(f"gw{base['meta']['round']}: re-ingest says {ing['meta'].get('score')}, the published payload says {base['meta'].get('score')}")
    by_id = {p['player_id']: p for p in ing.get('players', [])}
    missing = [p['name'] for p in base['players'] if p['player_id'] not in by_id]
    if missing:
        fail(f"gw{base['meta']['round']}: re-ingest has no rows for {missing} — is it the right capture?")
    for p in base['players']:
        src_p = by_id[p['player_id']]
        for k in PUBLISHED_FIELDS:
            if src_p.get(k) is not None and p.get(k) is None:
                p[k] = src_p[k]
    for k in ('lineup', 'events', 'published'):
        if ing.get(k) and not base.get(k):
            base[k] = ing[k]
    if ing.get('events'):
        n_goals = sum(1 for e in ing['events'] if e['kind'] == 'goal')
        if n_goals != base['meta']['gf'] + base['meta']['ga']:
            fail(f"gw{base['meta']['round']}: grafted events carry {n_goals} goals against {base['meta']['score']}")
    return base


# ----------------------------------------------------------------------------- opponent
def build_opponent(src, scout):
    """One opposition scout: authored judgement from build/opponents/<code>.json,
    event-derived structure from the opponent ingest.

    The seam is deliberate and visible. Everything a human decided — the claim, the
    four KPI tiles, the block heights, the loss zones, the channel counts, every
    panel intro — comes from the file. Everything counted from an event stream
    still comes from the ingest, which for now is the v2 source's IPS/IPS2 objects
    and is still Everton's. Generalising THAT means running the opponent capture
    for a new club; this half no longer needs a code change.
    """
    I, I2 = src['IPS'], src['IPS2']
    meta = I2['meta']
    subject = meta['subject']
    tiles = [{'label': t['k'], 'value': t['v'], 'ver': t['ver'], 'opp': bool(t['opp'])} for t in I2['tiles']]
    built = list(scout.get('built_from', []))
    return {
        'meta': {'subject': subject, 'name': meta['teams'][subject]['name'], 'foes': meta['foes'],
                 'teams': meta['teams'], 'fixture_id': scout['fixture_id'], 'code': scout['code'],
                 'built_from': built,
                 'vendor_report': scout.get('vendor_report'),
                 'sample': {'matches': len(built) or meta.get('sample', {}).get('matches', 0),
                            'event_streams_bound': len(meta['foes'])},
                 'xg': meta['xg'],
                 'notes_source': scout.get('_source', {}).get('authored_from')},
        'claim': scout['claim'],
        'kpis': scout['kpis'],
        'teaser': scout.get('teaser', []),
        'panels': scout.get('panels', {}),
        'block_height': scout['block_height'],
        'losses': scout['losses'],
        'channels': scout['channels'],
        'tiles': tiles, 'notes': I2['notes'], 'metrics': I2['metRows'], 'census': I2['cen'],
        'shots': I2['shots'], 'zones': I['zones'], 'transitions': I['trans'], 'chan_points': I['chan'], 'chan_shots': I['chanShots'],
        'network': {'nodes': I['nodes'], 'links': I['links']}, 'players': I2['players'],
    }


# ----------------------------------------------------------------------------- seasons
def baseline_ledger(src):
    """The 25/26 ledger with per-match possession and opponent tier attached.

    Possession per match lives in the dominance-trap scatter (x = ws_possession_pct);
    the ledger rows themselves only carry the result and both xG figures. Joined on
    round so the running season can be compared like for like — same venue, same
    tier — rather than against one season-long mean."""
    D = src['D']
    poss = {p['gw']: p['x'] for p in D['season']['trap']['pts']}
    tier = {r['team']: r['tier'] for r in D['lg']['table']}
    short = {'Wolves': 'Wolverhampton Wanderers', 'Man City': 'Manchester City', 'Newcastle': 'Newcastle United',
             'Spurs': 'Tottenham Hotspur', 'West Ham': 'West Ham United', "Nott'm Forest": 'Nottingham Forest',
             'Forest': 'Nottingham Forest', 'Palace': 'Crystal Palace', 'Leeds': 'Leeds United'}
    rows = []
    for m in D['season']['matches']:
        full = short.get(m['opp'], m['opp'])
        rows.append({**m, 'round': m['gw'], 'venue': m['ven'], 'result': m['res'],
                     'possession': poss.get(m['gw']), 'tier': tier.get(full), 'opp_full': full})
    return rows


def baseline_means(base_rows):
    """Season means of the 25/26 ledger — the figures the running season is held
    against. Computed, not typed: the xG-difference baseline was a literal 0.55
    while the same payload's own distribution table said +0.60."""
    b = story.norm(base_rows)
    n = len(b)
    xg = sum(r['xg'] for r in b) / n; oxg = sum(r['oxg'] for r in b) / n
    poss = [r['possession'] for r in b if r.get('possession') is not None]
    return {'points': round(sum(r['pts'] for r in b) / n, 2),
            'goals_for': round(sum(r['gf'] for r in b) / n, 2),
            'goals_against': round(sum(r['ga'] for r in b) / n, 2),
            'xg': round(xg, 2), 'xga': round(oxg, 2), 'xg_diff': round(xg - oxg, 2),
            'possession_pct': round(sum(poss) / len(poss), 1) if poss else None, 'n': n}


def build_season_running(src, files):
    D = src['D']
    matches = built_matches(files)
    rows = [ledger_row(m) for m in matches]
    if not rows:
        fail('no played match payloads to project a running season from')
    teams = {r['team']: r for r in D['lg']['table']}
    for r in rows:
        # a side that was not in the 25/26 Premier League has no finishing tier;
        # it is 'new', which the index names, rather than a null the filter drops
        r['tier'] = (teams.get(r['opp']) or {}).get('tier') or 'new'
    n = len(rows)
    ppg = sum(r['pts'] for r in rows) / n

    xg, n_xg = avg(rows, 'xg')
    oxg, _ = avg(rows, 'oxg')
    poss, n_poss = avg(rows, 'possession', 1)
    tilt, n_tilt = avg(rows, 'field_tilt', 1)
    cq, n_cq = avg(rows, 'chance_quality')

    def sample(k):
        return f"n = {k}" if k == n else f"n = {k} of {n}"

    base_rows = baseline_ledger(src)
    B = baseline_means(base_rows)
    dist = {d['lab']: d for d in D['season']['dists']}
    b_tilt = dist['Field tilt %']['mean']; b_cq = dist['np xG per shot']['mean']
    xg_diff = None if xg is None or oxg is None else round(xg - oxg, 2)
    kpis = [
        {'key': 'points', 'value': f"{ppg:.2f}", 'baseline': B['points'], 'n': n,
         'note': f"{sample(n)} · 25/26 finished on {B['points']:.2f}"},
        {'key': 'xg_diff', 'value': None if xg_diff is None else f"{xg_diff:+.2f}", 'baseline': B['xg_diff'],
         'n': n_xg, 'pending': xg_diff is None,
         'note': f"{sample(n_xg)} · 25/26 {B['xg_diff']:+.2f} per match"
                 + ('' if n_xg == n else ' · Twelve report pending')},
        {'key': 'possession_pct', 'value': None if poss is None else f"{poss:.1f}", 'baseline': B['possession_pct'],
         'n': n_poss, 'note': f"{sample(n_poss)} · 25/26 {B['possession_pct']} · WhoScored"},
        {'key': 'field_tilt', 'value': None if tilt is None else f"{tilt:.0f}", 'baseline': round(b_tilt),
         'n': n_tilt, 'note': f"{sample(n_tilt)} · 25/26 average {b_tilt:.0f}"},
        {'key': 'np_xg_per_shot', 'value': None if cq is None else f"{cq:.2f}", 'baseline': b_cq,
         'n': n_cq, 'pending': cq is None,
         'note': (f"{sample(n_cq)} · 25/26 {b_cq:.2f} · Twelve"
                  if cq is not None else 'Twelve report pending')},
    ]

    # Every row is the mean of the column it names, over the matches that carry
    # it. Where a supplier has not reported, the row says how many matches it
    # actually averaged rather than borrowing the season's n. The 25/26 side is
    # computed from the same ledger where it can be; shots, pass accuracy and
    # clearances are not per match in the 25/26 payload, so those three come from
    # the season distribution table and say so with `base_src`.
    BASE = {'points': B['points'], 'goals_for': B['goals_for'], 'goals_against': B['goals_against'],
            'xg': B['xg'], 'xga': B['xga'], 'possession_pct': B['possession_pct'],
            'shots': dist['Shots']['mean'], 'pass_accuracy': dist['Pass accuracy %']['mean'],
            'clearances': dist['Clearances']['mean']}
    PER_MATCH = {'points', 'goals_for', 'goals_against', 'xg', 'xga', 'possession_pct'}
    COLS = [('points', None, 2), ('goals_for', 'gf', 2), ('goals_against', 'ga', 2),
            ('xg', 'xg', 2), ('xga', 'oxg', 2), ('possession_pct', 'possession', 1),
            ('shots', 'shots', 1), ('pass_accuracy', 'pass_accuracy', 1),
            ('clearances', 'clearances', 1)]
    svs = []
    for key, col, d in COLS:
        if key == 'points':
            now, k = round(ppg, 2), n
        else:
            now, k = avg(rows, col, d)
        svs.append({'key': key, 'col': col or 'pts', 'now': now, 'base': round(BASE[key], d), 'n': k,
                    'pending': now is None, 'base_src': 'ledger' if key in PER_MATCH else 'season-mean',
                    'filterable': key in PER_MATCH})

    # ---- the narrative layer ------------------------------------------------
    goals_by_round = {m['meta']['round']: (m.get('timeline') or {}).get('goals', []) for m in matches}
    player_goals = {(m['meta']['round'], p['player_id']): p.get('goals', 0) for m in matches for p in m['players']}
    strip_ids = {p['player_id'] for m in matches for p in m['players']}
    avail = story.availability(matches, strip_ids, fail)
    tps = story.turning_points('26-27', rows, fail, ctx={
        'goals': goals_by_round, 'player_goals': player_goals,
        'availability': {p['player_id']: p for p in (avail or {}).get('players', [])}})
    KEYS = OrderedDict([('possession_pct', ('possession', 'Possession %', 'neutral')),
                        ('xg', ('xg', 'xG for', 'higher')), ('xga', ('oxg', 'xG against', 'lower')),
                        ('goals_for', ('gf', 'Goals for', 'higher')), ('goals_against', ('ga', 'Goals against', 'lower'))])
    narrative = {
        'eras': story.eras('26-27', rows, fail),
        'streaks': story.streaks(rows),
        'cumulative': story.cumulative(rows),
        'rolling': story.rolling(rows, 5),
        'pace': story.pace(rows, base_rows),
        'against_baseline': story.against_baseline(rows, base_rows, KEYS),
        'turning_points': tps,
        'availability': avail,
    }

    return {
        'meta': {'season': '26-27', 'sample': {'matches': n, 'of': 38}, 'baseline': '25-26',
                 'baseline_means': B},
        'claim': season_claim(rows, poss, n_poss),
        'kpis': kpis, 'ledger': rows, 'season_v_season': svs,
        # the 25/26 ledger travels with the running season so the same venue /
        # tier / player filter can be applied to both sides of every comparison
        'baseline_ledger': [{'round': r['round'], 'opp': r['opp_full'], 'venue': r['venue'], 'result': r['result'],
                             'gf': r['gf'], 'ga': r['ga'], 'pts': r['pts'], 'xg': r['xg'], 'oxg': r['oxg'],
                             'possession': r['possession'], 'tier': r['tier']} for r in base_rows],
        'story': narrative,
        'locks': {name: {'at': at, 'played': n}
                  for name, at in (('dominance', LOCKS['dominance']),
                                   ('gamestate', LOCKS['gamestate']),
                                   ('adjusted', LOCKS['adjusted']))},
    }


def load_opponents():
    """Every authored opposition scout, keyed by the fixture it is built for.

    build_opponent() used to return Everton's claim, KPIs, block heights, loss
    zones and channel counts as literals, and build_index() attached the scout with
    `if gw == 3`. A second opponent meant editing two functions. It is now a file."""
    out = {}
    d = os.path.join(HERE, 'opponents')
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.json'):
            continue
        with open(os.path.join(d, fn), encoding='utf-8') as fh:
            o = json.load(fh)
        if not o.get('fixture_id'):
            fail(f"build/opponents/{fn} names no fixture_id")
        o.setdefault('code', fn[:-5])
        out[o['fixture_id']] = o
    return out


SCOUTS = {}


def load_twelve(rnd):
    """The Twelve match report for a round, transcribed into build/twelve/gw<N>.json.

    The ingest never invents an xG: WhoScored's match centre carries no expectedGoals
    field, so it writes nulls and marks the rows pending. This is the other half of
    that contract — when the vendor report lands, its figures are transcribed once,
    with the page they were printed on, and applied here. Nothing is read off a chart
    and nothing is derived; a value absent from the report stays pending."""
    path = os.path.join(HERE, 'twelve', f'gw{rnd}.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def load_rosters(rnd):
    """Understat player rosters for a round, if they have been captured.

    A second, independent xG model. On MW3 it disagrees with Twelve by 34% on
    Everton's total, so the two are never summed or averaged. Twelve's total is
    what the tape and the KPI tiles publish; these values are written to
    us_xg / us_xa, labelled understat, and used to shape how that total is split
    across shots."""
    path = os.path.join(HERE, 'understat', f'gw{rnd}-players.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def apply_twelve(payload):
    """Fill a match payload's vendor-modelled figures from its Twelve report."""
    rnd = payload['meta']['round']
    tw = load_twelve(rnd)
    if not tw:
        return payload
    if tw.get('match_id') != payload['meta']['match_id']:
        fail(f"twelve/gw{rnd}.json is for {tw.get('match_id')}, not {payload['meta']['match_id']}")
    t = tw['team']

    payload['meta']['xg'] = t['xg']['united']
    payload['meta']['oxg'] = t['xg']['opp']
    payload['meta'].setdefault('sources', [])
    if 'twelve' not in payload['meta']['sources']:
        payload['meta']['sources'].append('twelve')

    TAPE = {'xg': 'xg', 'xt': 'xt'}
    for key, field in TAPE.items():
        row = next((r for r in payload['tape'] if r['key'] == key), None)
        if row is None or field not in t:
            continue
        row['united'] = t[field]['united']
        row['opp'] = t[field]['opp']
        row['src'] = 'twelve'
        row.pop('pending', None)

    KPI = {'xg': ('xg', 2), 'np_xg_per_shot': ('np_xg_per_shot', 2), 'field_tilt': ('field_tilt', 0)}
    for key, (field, dp) in KPI.items():
        k = next((k for k in payload['kpis'] if k['key'] == key), None)
        if k is None or field not in t:
            continue
        # field tilt was being counted here as final-third touch share and published
        # under the registry's "Twelve, vendor model" label. Twelve prints its own
        # figure; keep ours in the note rather than silently replacing the number.
        if key == 'field_tilt' and k.get('value') not in (None, ''):
            k['note'] = f"Twelve prints {t[field]['united']}; final-third touch share here was {k['value']}"
        k['value'] = f"{t[field]['united']:.{dp}f}"
        k['src'] = 'twelve'
        k.pop('pending', None)
        if 'pending' in (k.get('note') or '').lower():
            k['note'] = f"Twelve report · {tw['_source']['generated']}"
    for k in payload['kpis']:
        if k['key'] == 'shots' and 'src' not in k:
            k['src'] = 'counted'

    payload['twelve'] = {'source': tw['_source'], 'team': t,
                         'not_in_the_report': tw.get('not_in_the_report', [])}
    payload.setdefault('provenance', {})['twelve_applied'] = True
    apply_shot_proxy(payload, t)
    return payload


def understat_weights(payload, side):
    """{surname: xG} for one side, from the Understat rosters, if captured."""
    rs = load_rosters(payload['meta']['round'])
    if not rs:
        return None
    key = 'united' if side == 'united' else 'opp'
    out = {}
    for p in rs['teams'][key]:
        parts = str(p.get('player') or '').split()
        if parts:
            out[parts[-1].lower()] = p.get('xG') or 0.0
    return out or None


def apply_shot_proxy(payload, t):
    """Price the shots geometrically when the report gives a total but no per-shot value.

    Only runs where every shot on a side is unpriced. A side the vendor HAS priced
    is never touched, so a later per-shot feed silently supersedes the proxy."""
    sides = [('united', 'united'), ('opp', 'opp')]
    priced = {}
    for key, side in sides:
        shots = payload['shots'][key]
        if not shots or any(s.get('xg') is not None for s in shots):
            continue
        total = t['xg'][side]
        np_total = (t.get('np_xg') or {}).get(side, total)
        pw = understat_weights(payload, side)
        n, npen = shot_proxy.price_side(shots, total, np_total, player_xg=pw)
        if n:
            priced[key] = {'shots': n, 'penalties': npen, 'total': total,
                           'np_total': np_total, 'anchored': bool(pw)}
    if not priced:
        return payload

    # Everything downstream of a shot's xg can now be drawn, and every one of them
    # inherits `modelled` from the split — the map, the race and the situation list.
    payload['timeline']['united'] = shot_proxy.cumulative(payload['shots']['united'])
    payload['timeline']['opp'] = shot_proxy.cumulative(payload['shots']['opp'])
    payload['timeline'].pop('pending', None)
    payload['timeline']['src'] = 'modelled'
    payload['shots']['situations'] = {'u': shot_proxy.situation_totals(payload['shots']['united']),
                                      'o': shot_proxy.situation_totals(payload['shots']['opp'])}
    anchored = all(v.get('anchored') for v in priced.values())
    payload['shots']['priced'] = {
        'method': 'understat-anchored' if anchored else 'geometric',
        'src': 'modelled',
        'note': ("circle area is a proxy: the side total is Twelve's, each player's share of it "
                 "is Understat's, and a player's own shots are split by the goal mouth each saw"
                 if anchored else
                 "circle area is a proxy: the side total is Twelve's, the split across shots is "
                 "the share of the goal mouth each one could see"),
        'sides': priced}
    for side, info in priced.items():
        got = round(sum(s['xg'] for s in payload['shots'][side] if s.get('xg') is not None), 2)
        want = round(info['total'], 2)
        if abs(got - want) > 0.01:
            fail(f"shot proxy for {payload['meta']['match_id']} {side} sums to {got}, "
                 f"Twelve's total is {want}")
    return payload


def apply_rosters(payload):
    """Attach WhoScored per-player xG and xA, in their own fields."""
    rnd = payload['meta']['round']
    rs = load_rosters(rnd)
    if not rs:
        return payload
    by_name = {p['player']: p for p in rs['teams']['united']}
    matched = 0
    for pl in payload['players']:
        r = by_name.get(pl['name'])
        if r is None:
            continue
        pl['us_xg'] = r['xG']
        pl['us_xa'] = r['xA']
        matched += 1
    if matched < len([p for p in payload['players'] if p['mins']]):
        missing = [p['name'] for p in payload['players'] if 'us_xg' not in p]
        fail(f"Understat xG missing for {missing} in gw{rnd} — names must match the payload exactly")
    payload['understat'] = {'source': rs['_source']}
    return payload


def load_notes(name):
    """An authored notes file, or None. Absent is not an error — the caller falls
    back to something derived and says that it did."""
    path = os.path.join(HERE, 'notes', name)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def season_headline(rows):
    """The authored headline while it still describes the season, else the most
    recent match's own headline.

    The season claim was a copy of MW2's match headline, typed once. After MW3 it
    sat above a three-match season that had drawn 2-2, still announcing four goals
    in twenty-six minutes. A headline is editorial and should not be computed —
    but a stale one is worse than a plain one, so an authored line that has been
    overtaken is replaced by copy that is at least current, loudly."""
    notes = (load_notes('season-26-27.json') or {}).get('claim') or {}
    latest = rows[-1]['round'] if rows else 0
    written_for = notes.get('written_for_round')
    headline = notes.get('headline')
    if headline and written_for == latest:
        return headline
    if headline:
        print(f"  [warn] season headline was written for MW{written_for}, "
              f"MW{latest} has been played — falling back to the MW{latest} headline. "
              f"Update build/notes/season-26-27.json.")
    fallback = (rows[-1].get('story_headline') if rows else None) or ['The season so far.']
    return fallback


def season_claim(rows, poss, n_poss):
    """The lead sentence counts what the ledger holds rather than restating a
    figure that was true when it was typed."""
    n = len(rows)
    wins = sum(1 for r in rows if r['result'] == 'W')
    word = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six',
            7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten'}
    matches = f"{word.get(n, n)} match{'es' if n != 1 else ''}"
    ball = '' if poss is None else f"United have had {poss:.0f}% of the ball across {matches}"
    won = ('and won none of them' if wins == 0
           else f"and won {word.get(wins, wins)} of them")
    return {'eyebrow': 'Season 2026/27 · Premier League',
            'headline': season_headline(rows),
            'lead': f"{ball} {won}. Last season the same pattern produced 3.00 points per game "
                    f"under 45% possession and 1.40 above 55%."}


def build_season_complete(src):
    D = src['D']
    rows = baseline_ledger(src)
    B = baseline_means(rows)
    mu = next(r for r in D['lg']['table'] if r['team'] == 'Manchester United')
    ranks = {r['lab']: r for r in D['lg']['ranks']}
    dist = {d['lab']: d for d in D['season']['dists']}
    # Every figure on the tile row is counted from the ledger or the rebuilt table
    # in this same run; the League page used to type '3rd', 69, 50, 8 and 17 by hand.
    kpis = [
        {'label': 'Finished', 'value': ordinal(mu['pos']),
         'note': f"{mu['pts']} points, {B['points']:.2f} per game · {mu['w']}W {mu['d']}D {mu['l']}L · home {mu['hpts']}, away {mu['apts']}", 'src': 'derived'},
        {'label': 'Goals', 'value': f"{mu['gf']}:{mu['ga']}", 'note': f"GD {mu['gd']:+d} · {ordinal(ranks['Goals scored']['rank'])} for scored, {ordinal(ranks['Goals conceded']['rank'])} for conceded", 'src': 'derived'},
        {'key': 'xg_diff', 'value': f"{B['xg_diff']:+.2f}", 'note': f"xG {B['xg']:.2f} for, {B['xga']:.2f} against, per match · Twelve", 'src': 'twelve'},
        {'key': 'possession_pct', 'value': f"{B['possession_pct']:.1f}", 'note': f"median {dist['Possession % (WhoScored)']['med']} · WhoScored", 'src': 'whoscored'},
        {'label': 'Clean sheets', 'value': mu['cs'], 'note': f"{ordinal(ranks['Clean sheets']['rank'])} of 20 · {ranks['Clean sheets']['bestTeam']} {ranks['Clean sheets']['best']}", 'src': 'derived'},
    ]
    avail_rows = D['avail']['rows']
    cells = {r['id']: r['cells'] for r in avail_rows}
    regulars = [(r['id'], r['nm']) for r in avail_rows if r['mins'] >= FLOOR]
    narrative = {
        'eras': story.eras('25-26', rows, fail),
        'streaks': story.streaks(rows),
        'cumulative': story.cumulative(rows),
        'rolling': story.rolling(rows, 5),
        'turning_points': story.turning_points('25-26', rows, fail),
        'with_without': story.with_without(rows, cells, regulars),
        'leads': story.lead_windows(src['LEADS']),
    }
    ledger = [{'gw': r['gw'], 'opp': r['opp'], 'ven': r['ven'], 'res': r['res'], 'gf': r['gf'], 'ga': r['ga'],
               'pts': r['pts'], 'xg': r['xg'], 'oxg': r['oxg'], 'possession': r['possession'], 'tier': r['tier']}
              for r in rows]
    return {
        'meta': {'season': '25-26', 'sample': {'matches': 38, 'of': 38}, 'validated': D['lg']['validated'],
                 'means': B},
        'claim': {'eyebrow': 'Season 2025/26 · Premier League · final', 'headline': ['Dominated the ball,', 'dropped the points.'],
                  'lead': 'United took 3.00 points per game in the ten matches they held under 45% of the ball, and 1.40 in the fifteen they held over 55% — while creating their best chances in the second group. Split on ws_possession_pct.'},
        'kpis': kpis,
        'ledger': ledger, 'timelines': D['season']['tl'], 'trap': D['season']['trap'], 'dists': D['season']['dists'],
        'pairs': D['season']['pairs'], 'corr': D['season']['corr'], 'buckets': D['season']['buckets'],
        'gamestate': D['gs'], 'leads': src['LEADS'], 'phase': D['phase'], 'adjusted': D['resid'],
        'story': narrative,
        # the availability grid, keyed by player, so "with X / without X" can be
        # applied to the ledger on the page without loading squad.json
        'lineups': {r['id']: {'name': r['nm'], 'cells': r['cells']} for r in avail_rows},
    }

# ----------------------------------------------------------------------------- squad + players
def season_to_date(matches):
    """Per-player 26/27 totals aggregated from the played match payloads.

    The v2 source object carries a squad.s26 table that was correct for the two
    matches it was exported from and does not grow. These are counted from the
    same player rows the match pages render, so the squad strip and the player
    pages can no longer disagree about how many appearances someone has."""
    agg = OrderedDict()
    for m in matches:
        meta = m['meta']
        for p in m['players']:
            a = agg.setdefault(p['player_id'], {
                'player_id': p['player_id'], 'name': p['name'], 'pos': p['pos'],
                'apps': 0, 'starts': 0, 'mins': 0.0, 'g': 0, 'a': 0, 'involvements': []})
            a['apps'] += 1
            a['starts'] += 1 if p.get('started') else 0
            a['mins'] += p.get('mins') or 0
            a['g'] += p.get('goals') or 0
            a['a'] += p.get('assists') or 0
            if p.get('goals') or p.get('assists'):
                a['involvements'].append({'g': p['goals'], 'a': p['assists'], 'opp': meta['opp'],
                                          'ven': meta['venue'], 'mw': meta['round']})
    rows = []
    for a in agg.values():
        a['mins'] = round(a['mins'])
        a['ga'] = a['g'] + a['a']
        a['per90_running'] = round(a['ga'] / a['mins'] * 90, 2) if a['mins'] else 0
        a['over_floor'] = a['mins'] >= FLOOR
        rows.append(a)
    rows.sort(key=lambda p: (-p['ga'], -p['g'], -p['mins']))
    return rows


def squad_claim(rows, matches, team_goals, attributed, floor):
    """Headline and lead counted from the strip, not typed against one export."""
    scorers = [r for r in rows if r['ga']]
    if scorers:
        top = scorers[0]
        runner = scorers[1] if len(scorers) > 1 else None
        surname = top['name'].split()[-1]
        head = [f"{surname} has {top['ga']} of the {team_goals}.",
                'Nobody else has two.' if not runner or runner['ga'] < 2
                else f"{runner['name'].split()[-1]} has {runner['ga']}."]
    else:
        head = ['No goal involvements yet.', f"{matches} matches in."]

    own = team_goals - attributed
    own_clause = ''
    if own > 0:
        own_clause = (f" {own} own goal{'s' if own != 1 else ''} sits in the team total "
                      f"and in nobody's column.")

    over = sum(1 for r in rows if r['over_floor'])
    floor_clause = (f"none has reached the {floor}-minute floor, so there are no per-90 rates "
                    f"on this page yet" if over == 0 else
                    f"{over} of them {'is' if over == 1 else 'are'} past the {floor}-minute floor")

    return {'eyebrow': 'Squad 2026/27 · season to date',
            'headline': head,
            'lead': f"{team_goals} team goals in {matches} matches.{own_clause} "
                    f"{len(rows)} players used; {floor_clause}."}


def build_squad(src, files):
    D = src['D']
    matches = built_matches(files)
    n = len(matches)
    available = n * 90
    strip = season_to_date(matches)
    team_goals = sum(m['meta']['gf'] for m in matches)
    attributed = sum(p['g'] for p in strip)
    assists = sum(p['a'] for p in strip)
    over_floor = sum(1 for p in strip if p['over_floor'])

    per90_rows = []
    for p in D['squad']['s25']:
        row = {'player_id': p['id'], 'name': p['nm'], 'pos': p['pos'], 'apps': p['apps'], 'mins': round(p['mins']), 'over_floor': p['over'],
               'rating_wtd': p['rat'], 'mom': p['mom']}
        for k in ['touches', 'passes', 'key', 'shots', 'tackles', 'int', 'clear', 'aerials', 'drib']:
            row[k] = per90(p['v'][k], p['mins'])
        row['pct'] = p['pct']; row['attempts'] = p['att']
        per90_rows.append(row)
    for row in per90_rows:
        if not row['over_floor'] and any(row[k] is not None for k in ['touches']):
            fail(f"per-90 emitted under the floor for {row['name']}")
    return {
        'meta': {'season': '26-27', 'sample': {'matches': n, 'minutes_available': available, 'players_used': len(strip)}, 'floor': FLOOR},
        'claim': squad_claim(strip, n, team_goals, attributed, FLOOR),
        'kpis': {'matches': n, 'team_goals': team_goals, 'attributed': attributed, 'assists': assists,
                 'players_used': len(strip), 'over_floor': over_floor,
                 # these two were typed into the view layer as "2 different scorers"
                 # and "3 players have an involvement" — true at MW2, wrong at MW3
                 'scorers': sum(1 for p in strip if p['g']),
                 'involved': sum(1 for p in strip if p['ga']),
                 # WhoScored's minutes-weighted rating over the played matches, where
                 # the ingest has emitted one; absent on payloads built from the v2 source
                 'rated_matches': sum(1 for m in matches if any(p.get('rating') is not None for p in m['players']))},
        'season_to_date': strip, 'per90_baseline': per90_rows, 'goals_assists_25_26': D['ga'],
        'availability': {'gw_count': D['avail']['gwCount'], 'rows': D['avail']['rows']},
    }


def build_players(src, matches):
    D = src['D']
    out = {}
    s25 = {p['id']: p for p in D['squad']['s25']}   # squad.s26 is no longer read — see season_from_log
    for key, gw, m in matches:
        g = D[key]
        for r in g['roster']:
            pid = player_id(r['nm'])
            entry = out.setdefault(pid, {'meta': {'player_id': pid, 'name': r['nm'], 'shirt': r['sh'], 'pos': r['pos'], 'group': r['grp']},
                                         'seasons': {}, 'match_log': [], 'plots': {}})
            v = r['v']
            entry['match_log'].append({'match': m['meta']['match_id'], 'round': gw, 'comp': m['meta'].get('comp', 'PL'),
                                       'date': m['meta'].get('date'), 'opp': g['opp'], 'venue': g['ven'], 'score': g['score'],
                                       'result': m['meta']['result'], 'started': bool(r['st']), **{k: v.get(k) for k in v}})
            if r['nm'] in g['plots']:
                entry['plots'][m['meta']['match_id']] = g['plots'][r['nm']]
    for pid, e in out.items():
        log = e['match_log']
        e['meta']['sample'] = {'matches': len(log), 'minutes': sum((r.get('minutes') or 0) for r in log)}
        p = s25.get(pid)
        if p:
            e['seasons']['25-26'] = {'apps': p['apps'], 'starts': p['starts'], 'mins': round(p['mins']), 'rating_wtd': p['rat'], 'mom': p['mom'],
                                     'g': p['g'], 'a': p['a'], 'ga': p['ga'], 'ga90': p.get('ga90'), 'over_floor': p['mins'] >= FLOOR,
                                     'per90': {k: per90(p['v'][k], p['mins']) for k in ['touches', 'passes', 'key', 'shots', 'tackles', 'int', 'clear', 'aerials', 'drib']},
                                     'pct': p['pct'], 'attempts': p['att'], 'totals': p['v']}
        # The 26/27 block used to come from the v2 source's squad.s26 table, which
        # was exported after MW2 and never grew: every player page said 2 apps and
        # 180′ for the season while its own match log listed three matches. It is
        # now the sum of the match log — the same rows the page renders — and the
        # gate below holds the two to each other.
        e['seasons']['26-27'] = season_from_log(log)
    return out


def season_from_log(log):
    mins = sum((r.get('minutes') or 0) for r in log)
    tot = lambda k: sum((r.get(k) or 0) for r in log)
    g, a = tot('goals'), tot('assists')
    # WhoScored's published match rating, minutes-weighted over the matches that
    # carry one. The ingest emits it from MW3 on; MW1 and MW2 came through the v2
    # source without it, so the count of rated matches travels with the figure.
    rated = [r for r in log if r.get('rating') is not None and r.get('minutes')]
    rating = (round(sum(r['rating'] * r['minutes'] for r in rated) / sum(r['minutes'] for r in rated), 2)
              if rated else None)
    att = {'pass': tot('passes_attempted'), 'tackle': tot('tackles'), 'aerial': tot('aerials_won') + tot('aerials_lost'),
           'drib': tot('dribbles_attempted')}
    pct = {'pass': round(100 * tot('passes_completed') / att['pass'], 1) if att['pass'] else None,
           'tackle': round(100 * tot('tackles_won') / att['tackle'], 1) if att['tackle'] and any(r.get('tackles_won') is not None for r in log) else None,
           'aerial': round(100 * tot('aerials_won') / att['aerial'], 1) if att['aerial'] else None,
           'drib': round(100 * tot('dribbles_completed') / att['drib'], 1) if att['drib'] else None}
    totals = {'touches': tot('touches'), 'passes': tot('passes_attempted'), 'key': tot('key_passes'), 'shots': tot('shots'),
              'tackles': tot('tackles'), 'int': tot('interceptions'), 'clear': tot('clearances'),
              'aerials': tot('aerials_won'), 'drib': tot('dribbles_completed')}
    return {'apps': len(log), 'starts': sum(1 for r in log if r.get('started')), 'mins': round(mins),
            'rating_wtd': rating, 'rated_matches': len(rated),
            'mom': sum(1 for r in log if r.get('motm')),
            'g': g, 'a': a, 'ga': g + a, 'ga90': round((g + a) / mins * 90, 3) if mins else None,
            'over_floor': mins >= FLOOR,
            'per90': {k: per90(v, mins) for k, v in totals.items()},
            'pct': pct, 'attempts': att, 'totals': totals, 'src': 'counted from the match log'}

# ----------------------------------------------------------------------------- league
def build_league(src):
    D = src['D']; lg = D['lg']
    mu = next(r for r in lg['table'] if r['team'] == 'Manchester United')
    ranks = {r['lab']: r for r in lg['ranks']}
    def tile(label, lab, value, note_extra=''):
        r = ranks[lab]
        return {'label': label, 'value': value, 'src': 'derived',
                'note': f"{ordinal(r['rank'])} of 20 · {r['bestTeam']} {r['best']} · median {r['med']}{note_extra}"}
    # The five tiles were literals ('3rd', 69, 50, 8, 17) that happened to agree
    # with the table beneath them. They are read from it now.
    kpis = [{'label': 'Finished', 'value': ordinal(mu['pos']), 'src': 'derived',
             'note': f"{mu['pts']} points · {mu['w']}W {mu['d']}D {mu['l']}L · {ranks['Points']['bestTeam']} {ranks['Points']['best']}"},
            tile('Goals scored', 'Goals scored', mu['gf']), tile('Goals conceded', 'Goals conceded', mu['ga']),
            tile('Clean sheets', 'Clean sheets', mu['cs']), tile('Points v top six', 'Points v top six', mu['topPts'])]
    return {'meta': {'season': '25-26', 'sample': {'results': 380}, 'validated': lg['validated'], 'locks': {'league': LOCKS['league']}},
            'kpis': kpis,
            'claim': {'eyebrow': 'Premier League 2025/26 · final · 38 of 38', 'headline': ['Third in almost everything.', 'Fifteenth in clean sheets.'],
                      'lead': "Third in points, goals, goal difference, home points and away points — and fifteenth in clean sheets, with 8 in 38 against Arsenal's 19. United finished third by outscoring the league, not by shutting games down. The table is recomputed from all 380 results and matches two independent published tables on every column."},
            'table': lg['table'], 'ranks': lg['ranks'], 'tier_record': D['tierRec'], 'tier_metrics': D['tierMetrics'], 'tier_counts': D['counts'],
            'dropped': {'rows': lg['dropped'], 'by_tier': lg['dropByTier'], 'total': lg['totalDropped'], 'cheap_count': lg['cheapCount'], 'cheap_pts': lg['cheapPts']},
            'best_wins': lg['bestWins'], 'league_avg_ppg': lg['leagueAvgPPG']}

# ----------------------------------------------------------------------------- gates + write
def gate(files):
    idx = files['index.json']
    keys = {r['key'] for r in idx['registry']}
    for name, payload in files.items():
        if name.startswith('26-27/') and 'meta' in payload and 'sample' not in payload['meta']:
            fail(f"{name}: 26/27 payload without meta.sample")
        for k in payload.get('kpis', []) if isinstance(payload.get('kpis'), list) else []:
            if 'key' in k and k['key'] not in keys:
                fail(f"{name}: kpi key {k['key']} not in registry")
        for t in payload.get('tape', []):
            if t['key'] not in keys: fail(f"{name}: tape key {t['key']} not in registry")
    want = 46 + len(load_cups())
    if len(idx['fixtures']) != want: fail(f"expected {want} fixtures (38 + 8 + cups), got {len(idx['fixtures'])}")
    if len({f['fixture_id'] for f in idx['fixtures']}) != len(idx['fixtures']): fail('duplicate fixture_id in the index')
    dates = [f['date'] for f in idx['fixtures']]
    if dates != sorted(dates): fail('index fixtures are not in date order')

    # ---- the index is the identity layer; nothing may disagree with it -------
    # Every gate below exists because something published disagreed with it once.
    played = [f for f in idx['fixtures'] if f['comp'] == 'PL' and f['status'] == 'played']

    for f in played:
        m = files.get(f"26-27/matches/{f.get('match')}.json")
        if m:
            for k in ('xg', 'oxg', 'score', 'result'):
                if f.get(k) != m['meta'].get(k):
                    fail(f"index fixture {f['fixture_id']} has {k}={f.get(k)!r}, "
                         f"its match payload has {m['meta'].get(k)!r}")
        if not f.get('match'):
            fail(f"fixture {f['fixture_id']} is played but names no match payload")
        if f"26-27/matches/{f['match']}.json" not in files:
            fail(f"fixture {f['fixture_id']} names match '{f['match']}' with no payload written")

    season = files.get('26-27/season.json')
    squad = files.get('26-27/squad.json')

    if season is not None:
        n_ledger = len(season['ledger'])
        if n_ledger != len(played):
            fail(f"season ledger holds {n_ledger} rows against {len(played)} played fixtures "
                 f"— rounds {[r['round'] for r in season['ledger']]} "
                 f"vs {[f['round'] for f in played]}")
        if season['meta']['sample']['matches'] != n_ledger:
            fail(f"season meta.sample.matches {season['meta']['sample']['matches']} "
                 f"disagrees with its own ledger ({n_ledger} rows)")
        by_round = {f['round']: f for f in played}
        for r in season['ledger']:
            f = by_round.get(r['round'])
            if f is None:
                fail(f"season ledger carries round {r['round']}, which the index has not played")
            if f"{r['gf']}-{r['ga']}" != f['score'] or r['result'] != f['result']:
                fail(f"season ledger round {r['round']} reads {r['result']} {r['gf']}-{r['ga']}, "
                     f"index reads {f['result']} {f['score']}")
        # A row with no value must say so. Averaging a null as a zero, or letting a
        # frozen literal sit beside a computed mean, is the failure this catches.
        notes = (load_notes('season-26-27.json') or {}).get('claim') or {}
        if notes.get('headline') and notes.get('written_for_round') == season['ledger'][-1]['round'] \
                and season['claim']['headline'] != notes['headline']:
            fail('season claim headline does not match the current authored note')
        for row in season['season_v_season']:
            if row.get('now') is None and not row.get('pending'):
                fail(f"season_v_season row '{row['key']}' has no value and is not marked pending")
            if 'n' not in row:
                fail(f"season_v_season row '{row['key']}' does not say how many matches it averaged")

    if squad is not None and season is not None:
        if squad['meta']['sample']['matches'] != season['meta']['sample']['matches']:
            fail(f"squad says {squad['meta']['sample']['matches']} matches, "
                 f"season says {season['meta']['sample']['matches']}")
        if squad['meta']['sample']['minutes_available'] != squad['meta']['sample']['matches'] * 90:
            fail("squad minutes_available is not matches * 90")
        k = squad['kpis']; strip = squad['season_to_date']
        if k['scorers'] != sum(1 for p in strip if p['g']) or k['involved'] != sum(1 for p in strip if p['ga']):
            fail('squad kpi scorers/involved disagree with the season-to-date strip')

    # ---- the narrative layer must agree with the ledger it narrates ---------
    if season is not None:
        st = season['story']
        n = season['meta']['sample']['matches']
        if len(st['cumulative']) != n or (st['pace']['at'] or {}).get('round') != season['ledger'][-1]['round']:
            fail('season story cumulative/pace do not cover the ledger')
        if st['cumulative'][-1]['pts'] != sum(r['pts'] for r in season['ledger']):
            fail('cumulative points disagree with the ledger')
        if any(e['played'] > n for e in st['eras']):
            fail('an era claims more matches than have been played')
        for tp in st['turning_points']:
            if tp['round'] is not None and not tp['evidence']:
                fail(f"turning point '{tp['id']}' names a round but carries no evidence")
        av = st.get('availability')
        if av:
            # a name here has to be someone the pipeline knows: the 25/26 grid, or a
            # player who has appeared in a 26/27 match payload
            known = set(((files.get('25-26/season.json') or {}).get('lineups') or {}).keys())
            for mname, m in files.items():
                if mname.startswith('26-27/matches/'):
                    known |= {p['player_id'] for p in m.get('players', [])}
            for p in av['players']:
                p['known'] = p['player_id'] in known
                if not p['known']:
                    # a summer signing who has not yet played has no page to link to;
                    # that is allowed, but said, so a typo in an id cannot hide as one
                    print(f"  [warn] availability: {p['player_id']} ({p['name']}) has no 25/26 grid row and no 26/27 "
                          f"appearance yet — listed without a link")
            if av['checked'] < season['ledger'][-1]['date']:
                print(f"  [warn] availability list was checked on {av['checked']}, before MW{season['ledger'][-1]['round']} was played — update build/notes/availability-26-27.json")
        b = st['against_baseline']
        for row in b:
            if len(row['matches']) != n:
                fail(f"against_baseline '{row['key']}' covers {len(row['matches'])} matches, season has {n}")

    base = files.get('25-26/season.json')
    if base is not None:
        if len(base['ledger']) != 38 or base['story']['cumulative'][-1]['pts'] != sum(r['pts'] for r in base['ledger']):
            fail('25/26 ledger or cumulative points are wrong')
        lg = files.get('league/25-26.json')
        mu = next(r for r in lg['table'] if r['team'] == 'Manchester United')
        if base['story']['cumulative'][-1]['pts'] != mu['pts'] or base['story']['cumulative'][-1]['gf'] != mu['gf']:
            fail('25/26 season ledger disagrees with the rebuilt league table on points or goals')
        if not base['story']['eras'] or base['story']['eras'][-1]['to_round'] != 38:
            fail('25/26 eras do not reach round 38')

    # ---- a player page's season block is the sum of its own match log --------
    for name, payload in files.items():
        if not name.startswith('26-27/players/'):
            continue
        s = payload['seasons'].get('26-27') or {}
        log = payload['match_log']
        if s.get('apps') != len(log) or s.get('mins') != round(sum((r.get('minutes') or 0) for r in log)):
            fail(f"{name}: seasons['26-27'] says {s.get('apps')} apps / {s.get('mins')}′, "
                 f"the match log has {len(log)} / {round(sum((r.get('minutes') or 0) for r in log))}′")
        if s.get('rating_wtd') is not None and s.get('rated_matches', 0) == 0:
            fail(f"{name}: carries a season rating with no rated matches")

    # ---- a vendor figure must have the vendor behind it ---------------------
    for name, payload in files.items():
        if not name.startswith('26-27/matches/'):
            continue
        rnd = payload['meta']['round']
        tw = load_twelve(rnd)
        for k in payload.get('kpis', []):
            if k.get('pending') and k.get('value') not in (None, ''):
                fail(f"{name}: kpi {k['key']} is marked pending and carries {k['value']}")
            if k.get('src') == 'twelve' and k.get('value') in (None, '') and not k.get('pending'):
                fail(f"{name}: kpi {k['key']} is sourced twelve, has no value, and is not pending")
            if 'pending' in (k.get('note') or '').lower() and k.get('value') not in (None, ''):
                fail(f"{name}: kpi {k['key']} carries {k['value']} under a note that still says pending")
        for r in payload.get('tape', []):
            if r.get('pending') and r.get('united') is not None:
                fail(f"{name}: tape row {r['key']} is marked pending and carries {r['united']}")
        if tw:
            t = tw['team']
            if payload['meta'].get('xg') != t['xg']['united'] or payload['meta'].get('oxg') != t['xg']['opp']:
                fail(f"{name}: meta xG {payload['meta'].get('xg')}:{payload['meta'].get('oxg')} "
                     f"does not match twelve/gw{rnd}.json ({t['xg']['united']}:{t['xg']['opp']})")

    # ---- a scout must attach to a fixture that exists ------------------------
    fids = {f['fixture_id'] for f in idx['fixtures']}
    for name, payload in files.items():
        if not name.startswith('26-27/opponents/'):
            continue
        fid = payload['meta']['fixture_id']
        if fid not in fids:
            fail(f"{name}: scout is built for fixture {fid}, which is not in the index")
        fx = next(f for f in idx['fixtures'] if f['fixture_id'] == fid)
        if fx.get('scout') != payload['meta']['code']:
            fail(f"{name}: fixture {fid} points at scout {fx.get('scout')!r}, "
                 f"this payload is {payload['meta']['code']!r}")
        for k in ('claim', 'kpis', 'block_height', 'losses', 'channels'):
            if not payload.get(k):
                fail(f"{name}: authored block '{k}' is missing or empty")

    # ---- a modelled figure must declare itself -----------------------------
    for name, payload in files.items():
        if not name.startswith('26-27/matches/'):
            continue
        mod = [s for side in ('united', 'opp') for s in payload['shots'][side]
               if s.get('xg_src') == 'modelled']
        pr = payload['shots'].get('priced')
        if mod and not pr:
            fail(f"{name}: {len(mod)} shots are modelled but shots.priced is absent, "
                 f"so the page has no way to label them")
        if pr and payload.get('timeline', {}).get('src') != 'modelled':
            fail(f"{name}: shots are modelled but the timeline does not say so")
        if pr:
            for side, info in pr['sides'].items():
                got = round(sum(s['xg'] for s in payload['shots'][side] if s.get('xg') is not None), 2)
                if abs(got - round(info['total'], 2)) > 0.01:
                    fail(f"{name}: modelled {side} shots sum to {got}, vendor total {info['total']}")

    # ---- an anchored split must actually have its anchor ---------------------
    for name, payload in files.items():
        if not name.startswith('26-27/matches/'):
            continue
        pr = payload['shots'].get('priced')
        if pr and pr['method'] == 'understat-anchored' and 'understat' not in payload:
            fail(f"{name}: shots claim an Understat-anchored split with no Understat source")
        if 'understat' in payload:
            miss = [p['name'] for p in payload['players'] if p.get('mins') and 'us_xg' not in p]
            if miss:
                fail(f"{name}: Understat attached but {miss} carry no us_xg")

    # ---- every player a match page links to must have a page ----------------
    # The two player_id implementations agreed on the squad of the day and would
    # have diverged on the next Højlund. build/names.py is now the only one; this
    # is the gate that keeps it that way.
    written = {name[len('26-27/players/'):-len('.json')]
               for name in files if name.startswith('26-27/players/')}
    for name, payload in files.items():
        if not name.startswith('26-27/matches/'):
            continue
        for p in payload.get('players', []):
            pid = p['player_id']
            if pid != player_id(p['name']):
                fail(f"{name}: player_id '{pid}' for {p['name']} is not what names.player_id() "
                     f"produces ('{player_id(p['name'])}')")
            if pid not in written:
                fail(f"{name}: links to player '{pid}' ({p['name']}) with no player payload")

    return True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--apply', action='store_true'); args = ap.parse_args()
    src = load_source()
    ingested = load_ingested()
    # A gameweek the v2 source already carries is built from it; anything else comes
    # from build/matches/gw<N>.json. gw1 and gw2 exist in the v2 source — that
    # payload wins for everything it holds (Twelve's per-shot xG, the written
    # story), so a re-ingest cannot quietly change what is published. What a
    # re-ingest CAN add is the published blocks the v2 export never carried —
    # lineup, events, ratings, cards — and those are grafted on, gated on the
    # two agreeing about the score and the players.
    early = {gw: p for gw, p in ingested.items() if gw in (1, 2)}
    ingested = {gw: p for gw, p in ingested.items() if gw not in (1, 2)}
    if ingested:
        print(f"ingested gameweeks: {sorted(ingested)}")
    global SCOUTS
    SCOUTS = load_opponents()
    if SCOUTS:
        print(f"opposition scouts: {sorted(v['code'] for v in SCOUTS.values())}")
    files = OrderedDict()
    m1 = build_match(src, 'gw1', 1); m2 = build_match(src, 'gw2', 2)
    for gw, m in ((1, m1), (2, m2)):
        if gw in early:
            graft_published(m, early[gw])
            print(f"gw{gw}: published blocks (lineup, events, ratings) grafted from build/matches/gw{gw}.json")
    # Enrich the ingested weeks BEFORE the index is built. index.json is the identity
    # layer every other payload is held to, and it carries each fixture's xG — built
    # first, it recorded MW3 as null while the match payload already had Twelve's 0.86.
    for gw, p in sorted(ingested.items()):
        # The 25/26 baseline is season-level and identical on every match payload;
        # the ingest cannot know it, so it is carried across here.
        if not p.get('baseline'):
            p['baseline'] = m2['baseline']
        ingested[gw] = apply_twelve(apply_rosters(p))
    cups = load_ingested_cups()
    for fid, p in cups.items():
        if not p.get('baseline'):
            p['baseline'] = m2['baseline']
    if cups:
        print(f"cup / European matches: {sorted(cups)}")
    files['index.json'] = build_index(src, ingested, cups)
    files['crests.json'] = src['D']['crest']
    files[f"26-27/matches/{m1['meta']['match_id']}.json"] = m1
    files[f"26-27/matches/{m2['meta']['match_id']}.json"] = m2
    for gw, p in sorted(ingested.items()):
        files[f"26-27/matches/{p['meta']['match_id']}.json"] = p
    for fid, p in sorted(cups.items()):
        files[f"26-27/matches/{p['meta']['match_id']}.json"] = p
    for fid, scout in sorted(SCOUTS.items()):
        files[f"26-27/opponents/{scout['code']}.json"] = build_opponent(src, scout)
    files['26-27/season.json'] = build_season_running(src, files)
    files['25-26/season.json'] = build_season_complete(src)
    files['26-27/squad.json'] = build_squad(src, files)
    for gw, p in sorted(ingested.items()):
        src['D'][f'gw{gw}'] = as_source_gw(p)
    mlist = [('gw1', 1, m1), ('gw2', 2, m2)] + [(f'gw{gw}', gw, p) for gw, p in sorted(ingested.items())]
    for fid, p in sorted(cups.items(), key=lambda kv: kv[1]['meta']['date']):
        src['D'][f'cup_{fid}'] = as_source_gw(p)
        mlist.append((f'cup_{fid}', p['meta']['round'], p))
    for pid, p in build_players(src, mlist).items():
        files[f"26-27/players/{pid}.json"] = p
    files['league/25-26.json'] = build_league(src)
    gate(files)
    total = 0
    for name, payload in files.items():
        s = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        total += len(s)
        print(f"{name:48s} {len(s)/1024:7.1f} KB")
        if args.apply:
            path = os.path.join(OUT, name); os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'w', encoding='utf-8').write(s)
    print(f"{'total':48s} {total/1024:7.1f} KB  {'written' if args.apply else 'dry run — add --apply to write'}")

if __name__ == '__main__':
    main()
