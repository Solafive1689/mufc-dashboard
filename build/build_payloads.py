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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data')
FLOOR = 450            # minutes before a per-90 is shown
LOCKS = {'dominance': 10, 'gamestate': 10, 'adjusted': 15, 'league': 10}

# ----------------------------------------------------------------------------- helpers
def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def player_id(name):
    parts = name.replace('í', 'i').replace('é', 'e').replace('á', 'a').replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n').split()
    return 'mufc_' + slug(parts[-1]) + '_' + slug(parts[0]) if len(parts) > 1 else 'mufc_' + slug(parts[0])

def per90(total, mins):
    if mins is None or mins < FLOOR:
        return None
    return round(total / mins * 90, 2)

def match_slug(gw, code):
    return f"mw{gw:02d}-{code.lower()}"

def fail(msg):
    print('GATE FAILED:', msg, file=sys.stderr)
    sys.exit(2)

# ----------------------------------------------------------------------------- source
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
def build_index(src):
    D = src['D']
    fixtures = []
    played = {1: 'gw1', 2: 'gw2'}
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
        if f['comp'] == 'PL' and gw == 3:
            fx['scout'] = 'eve'
        fixtures.append(fx)
    teams = {}
    for r in D['lg']['table']:
        teams[r['team']] = {'name': r['team'], 'tier_25_26': r['tier'], 'pos_25_26': r['pos']}
    return {
        'seasons': [{'id': '26-27', 'label': '2026/27', 'status': 'running', 'baseline': '25-26'},
                    {'id': '25-26', 'label': '2025/26', 'status': 'complete', 'baseline': None}],
        'fixtures': fixtures,
        'teams': teams,
        'registry': registry(src),
        'thresholds': dict(LOCKS, floor_minutes=FLOOR),
        'tier_names': D['tierName'],
        'generated_from': 'mufc.js (v2 payload) via build_payloads.py',
    }

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

# ----------------------------------------------------------------------------- opponent
def build_opponent(src):
    I, I2 = src['IPS'], src['IPS2']
    meta = I2['meta']
    subject = meta['subject']
    tiles = [{'label': t['k'], 'value': t['v'], 'ver': t['ver'], 'opp': bool(t['opp'])} for t in I2['tiles']]
    return {
        'meta': {'subject': subject, 'name': meta['teams'][subject]['name'], 'foes': meta['foes'],
                 'teams': meta['teams'], 'fixture_id': 'PL-03-EVE', 'built_from': [
                     {'label': 'Everton 2–0 Crystal Palace', 'date': '2026-08-22', 'ws': '1983549'},
                     {'label': 'Bournemouth 1–1 Everton', 'date': '2026-08-29', 'ws': '1983556'}],
                 'sample': {'matches': 2, 'event_streams_bound': len(meta['foes'])}, 'xg': meta['xg'],
                 'notes_source': 'opponents/everton_2026_27/notes.yaml'},
        'claim': {'headline': ['Everton do not want', 'the ball.'],
                  'lead': 'Under 42% possession in both league matches, four points from two, and ten big chances conceded to four created. Their goals come from set pieces, their threat from turnovers high up, and their block drops by 11–21 m between the 60th and 75th minute in both games.'},
        'kpis': [{'label': 'Possession', 'value': '41.5', 'unit': '%', 'note': '41.9 home, 41.1 away · Twelve, mirror-verified', 'src': 'twelve'},
                 {'label': 'Big chances conceded', 'value': '10', 'unit': '', 'note': 'v 4 created · 1 goal conceded · Pickford 8 saves', 'src': 'whoscored'},
                 {'label': 'Shots from set pieces', 'value': '31', 'unit': '%', 'note': '9 of 29 · 2 of their 3 goals', 'src': 'counted'},
                 {'label': 'Block height, 60–75′', 'value': '27.8', 'unit': 'm', 'note': 'v Palace · 29.6 m v Bournemouth · lowest of both matches', 'src': 'counted'}],
        'block_height': {'blocks': ['0–15', '15–30', '30–45', '45–60', '60–75', '75–90'],
                         'v_palace': [40.3, 42.0, 46.1, 49.0, 27.8, 41.1], 'v_bournemouth': [42.3, 57.3, 35.4, 40.6, 29.6, 40.0]},
        'losses': {'total': 205, 'zones': [['Attacking left', 38], ['Defensive centre', 28], ['Attacking right', 24], ['Midfield right', 23], ['Defensive left', 23]]},
        'channels': [{'ch': 'Left wing', 'entries': 23, 'shots': 8}, {'ch': 'Left half-space', 'entries': 3, 'shots': 4},
                     {'ch': 'Centre', 'entries': 12, 'shots': 11}, {'ch': 'Right half-space', 'entries': 3, 'shots': 3},
                     {'ch': 'Right wing', 'entries': 17, 'shots': 3}],
        'tiles': tiles, 'notes': I2['notes'], 'metrics': I2['metRows'], 'census': I2['cen'],
        'shots': I2['shots'], 'zones': I['zones'], 'transitions': I['trans'], 'chan_points': I['chan'], 'chan_shots': I['chanShots'],
        'network': {'nodes': I['nodes'], 'links': I['links']}, 'players': I2['players'],
    }

# ----------------------------------------------------------------------------- seasons
def build_season_running(src):
    D = src['D']
    played = [('gw1', 1), ('gw2', 2)]
    rows = []
    for key, gw in played:
        g = D[key]; gf, ga = [int(x) for x in g['score'].split('-')]
        fx = next(f for f in D['fix'] if f['comp'] == 'PL' and f['rd'] == gw)
        pos = next(s for s in g['summary'] if s['lab'] == 'Possession %')
        rows.append({'round': gw, 'opp': g['opp'], 'code': fx['code'], 'venue': g['ven'], 'date': g['date'], 'gf': gf, 'ga': ga,
                     'result': 'W' if gf > ga else ('D' if gf == ga else 'L'), 'pts': 3 if gf > ga else (1 if gf == ga else 0),
                     'xg': g['xg'], 'oxg': g['oxg'], 'possession': pos['u'], 'field_tilt': float(g['story']['hero'][0]['v']),
                     'match': match_slug(gw, fx['code'])})
    n = len(rows)
    ppg = sum(r['pts'] for r in rows) / n
    pairs = {p['lab']: p for p in D['season']['pairs']}
    def mean(k): return round(sum(r[k] for r in rows) / n, 2)
    kpis = [
        {'key': 'points', 'value': f"{ppg:.2f}", 'baseline': 1.87, 'note': f"n = {n} · 25/26 finished on 1.87"},
        {'key': 'xg_diff', 'value': f"{mean('xg') - mean('oxg'):+.2f}", 'baseline': 0.55, 'note': f"n = {n} · 25/26 +0.55 per match"},
        {'key': 'possession_pct', 'value': f"{mean('possession'):.1f}", 'baseline': 51.8, 'note': f"n = {n} · 25/26 51.8 · WhoScored"},
        {'key': 'field_tilt', 'value': f"{mean('field_tilt'):.0f}", 'baseline': 51, 'note': f"n = {n} · 25/26 average 51"},
        {'key': 'np_xg_per_shot', 'value': None, 'baseline': 0.12, 'note': 'GW2 Twelve report pending', 'pending': True},
    ]
    svs = [{'key': 'points', 'now': round(ppg, 2), 'base': 1.87}, {'key': 'goals_for', 'now': mean('gf'), 'base': 1.82},
           {'key': 'goals_against', 'now': mean('ga'), 'base': 1.32}, {'key': 'xg', 'now': mean('xg'), 'base': 1.90},
           {'key': 'xga', 'now': mean('oxg'), 'base': 1.30}, {'key': 'possession_pct', 'now': mean('possession'), 'base': 51.8},
           {'key': 'shots', 'now': 27.0, 'base': 15.7}, {'key': 'pass_accuracy', 'now': 88.7, 'base': 82.3}, {'key': 'clearances', 'now': 12.5, 'base': 25.0}]
    return {
        'meta': {'season': '26-27', 'sample': {'matches': n, 'of': 38}, 'baseline': '25-26'},
        'claim': {'eyebrow': 'Season 2026/27 · Premier League', 'headline': D['gw2']['story']['h1a'] and ['Level at half time.', 'Four goals in twenty-six minutes.'],
                  'lead': 'United have had 66% of the ball across two matches and converted it once. Last season the same pattern produced 3.00 points per game under 45% possession and 1.40 above 55%.'},
        'kpis': kpis, 'ledger': rows, 'season_v_season': svs,
        'locks': {'dominance': {'at': LOCKS['dominance'], 'played': n}, 'gamestate': {'at': LOCKS['gamestate'], 'played': n},
                  'adjusted': {'at': LOCKS['adjusted'], 'played': n}},
        'held_back': [{'label': 'Field tilt %', 'base': 51.34, 'gw1': 84}, {'label': 'np xG per shot', 'base': 0.12, 'gw1': 0.10},
                      {'label': 'xT created', 'base': 1.57, 'gw1': 2.98}, {'label': 'Box touches', 'base': 21.29, 'gw1': 32},
                      {'label': 'PPDA (higher = less press)', 'base': 6.05, 'gw1': 4.13}],
    }

def build_season_complete(src):
    D = src['D']
    return {
        'meta': {'season': '25-26', 'sample': {'matches': 38, 'of': 38}, 'validated': D['lg']['validated']},
        'claim': {'eyebrow': 'Season 2025/26 · Premier League · final', 'headline': ['Dominated the ball,', 'dropped the points.'],
                  'lead': 'United took 3.00 points per game in the ten matches they held under 45% of the ball, and 1.40 in the fifteen they held over 55% — while creating their best chances in the second group. Split on ws_possession_pct.'},
        'ledger': D['season']['matches'], 'timelines': D['season']['tl'], 'trap': D['season']['trap'], 'dists': D['season']['dists'],
        'pairs': D['season']['pairs'], 'corr': D['season']['corr'], 'buckets': D['season']['buckets'],
        'gamestate': D['gs'], 'leads': src['LEADS'], 'phase': D['phase'], 'adjusted': D['resid'],
    }

# ----------------------------------------------------------------------------- squad + players
def build_squad(src):
    D = src['D']
    s26 = sorted(D['squad']['s26'], key=lambda p: (-p['ga'], -p['g'], -p['mins']))
    matches = 2; available = matches * 90
    team_goals = 5; attributed = sum(p['g'] for p in s26)
    strip = []
    for p in s26:
        strip.append({'player_id': p['id'], 'name': p['nm'], 'pos': p['pos'], 'apps': p['apps'], 'starts': p['starts'], 'mins': round(p['mins']),
                      'g': p['g'], 'a': p['a'], 'ga': p['ga'], 'per90_running': round(p['ga'] / p['mins'] * 90, 2) if p['mins'] else 0,
                      'over_floor': p['mins'] >= FLOOR, 'involvements': p.get('ret', []), 'rating': p['rat']})
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
        'meta': {'season': '26-27', 'sample': {'matches': matches, 'minutes_available': available, 'players_used': len(s26)}, 'floor': FLOOR},
        'claim': {'eyebrow': 'Squad 2026/27 · season to date', 'headline': ['Bruno has four of the five.', 'Nobody else has two.'],
                  'lead': f"Five team goals in two matches: three and an assist for Bruno Fernandes, one for Mbeumo, an assist for Cunha, and one own goal that sits in the team total and in nobody's column. {len(s26)} players used; none has reached the {FLOOR}-minute floor, so there are no per-90 rates on this page yet."},
        'kpis': {'matches': matches, 'team_goals': team_goals, 'attributed': attributed, 'assists': sum(p['a'] for p in s26),
                 'players_used': len(s26), 'over_floor': sum(1 for p in s26 if p['mins'] >= FLOOR)},
        'season_to_date': strip, 'per90_baseline': per90_rows, 'goals_assists_25_26': D['ga'],
        'availability': {'gw_count': D['avail']['gwCount'], 'rows': D['avail']['rows']},
    }

def build_players(src, matches):
    D = src['D']
    out = {}
    s25 = {p['id']: p for p in D['squad']['s25']}; s26 = {p['id']: p for p in D['squad']['s26']}
    for key, gw, m in matches:
        g = D[key]
        for r in g['roster']:
            pid = player_id(r['nm'])
            entry = out.setdefault(pid, {'meta': {'player_id': pid, 'name': r['nm'], 'shirt': r['sh'], 'pos': r['pos'], 'group': r['grp']},
                                         'seasons': {}, 'match_log': [], 'plots': {}})
            v = r['v']
            entry['match_log'].append({'match': m['meta']['match_id'], 'round': gw, 'opp': g['opp'], 'venue': g['ven'], 'score': g['score'],
                                       'result': m['meta']['result'], 'started': bool(r['st']), **{k: v.get(k) for k in v}})
            if r['nm'] in g['plots']:
                entry['plots'][m['meta']['match_id']] = g['plots'][r['nm']]
    for pid, e in out.items():
        e['meta']['sample'] = {'matches': len(e['match_log']), 'minutes': sum((r.get('minutes') or 0) for r in e['match_log'])}
        for sid, table in (('25-26', s25), ('26-27', s26)):
            p = table.get(pid)
            if p:
                e['seasons'][sid] = {'apps': p['apps'], 'starts': p['starts'], 'mins': round(p['mins']), 'rating_wtd': p['rat'], 'mom': p['mom'],
                                     'g': p['g'], 'a': p['a'], 'ga': p['ga'], 'ga90': p.get('ga90'), 'over_floor': p['mins'] >= FLOOR,
                                     'per90': {k: per90(p['v'][k], p['mins']) for k in ['touches', 'passes', 'key', 'shots', 'tackles', 'int', 'clear', 'aerials', 'drib']},
                                     'pct': p['pct'], 'attempts': p['att'], 'totals': p['v']}
    return out

# ----------------------------------------------------------------------------- league
def build_league(src):
    D = src['D']; lg = D['lg']
    return {'meta': {'season': '25-26', 'sample': {'results': 380}, 'validated': lg['validated'], 'locks': {'league': LOCKS['league']}},
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
    if len(idx['fixtures']) != 46: fail(f"expected 46 fixtures, got {len(idx['fixtures'])}")
    return True

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--apply', action='store_true'); args = ap.parse_args()
    src = load_source()
    files = OrderedDict()
    files['index.json'] = build_index(src)
    files['crests.json'] = src['D']['crest']
    m1 = build_match(src, 'gw1', 1); m2 = build_match(src, 'gw2', 2)
    files[f"26-27/matches/{m1['meta']['match_id']}.json"] = m1
    files[f"26-27/matches/{m2['meta']['match_id']}.json"] = m2
    files['26-27/opponents/eve.json'] = build_opponent(src)
    files['26-27/season.json'] = build_season_running(src)
    files['25-26/season.json'] = build_season_complete(src)
    files['26-27/squad.json'] = build_squad(src)
    for pid, p in build_players(src, [('gw1', 1, m1), ('gw2', 2, m2)]).items():
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
