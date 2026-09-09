#!/usr/bin/env python3
"""The published blocks the ingest emits, exercised on a synthetic match centre.

No real matchCentreData is in the repo, so this is the shape contract: the
minute-key trap on ratings, own goals crediting the other side, a second yellow
counted as a red, the formation template read by slot rather than by list order,
and a substitution carrying who it replaced. Run:  python3 build/tests/test_ingest_published.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ingest_whoscored as ing  # noqa: E402


def ev(t, tid, pid, minute, quals=(), **kw):
    return dict(type={'displayName': t}, teamId=tid, playerId=pid, minute=minute, expandedMinute=minute,
                outcomeType={'displayName': 'Successful'}, x=50, y=50,
                qualifiers=[{'type': {'displayName': q}} for q in quals], **kw)


US, THEM = 32, 31
NAMES = {'1': 'Senne Lammens', '2': 'Bruno Fernandes', '3': 'Bryan Mbeumo', '9': 'James Tarkowski', '10': 'Iliman Ndiaye',
         '4': 'Benjamin Sesko'}
us = {'teamId': US, 'name': 'Manchester United',
      'players': [
          {'playerId': 1, 'name': 'Senne Lammens', 'shirtNo': 1, 'position': 'GK', 'isFirstEleven': True,
           'stats': {'ratings': {'45': 6.1, '100': 6.4, '96': 7.0}}},
          {'playerId': 2, 'name': 'Bruno Fernandes', 'shirtNo': 8, 'position': 'AMC', 'isFirstEleven': True,
           'isManOfTheMatch': True, 'stats': {'ratings': {'10': 6.0, '90': 8.3}}},
          {'playerId': 3, 'name': 'Bryan Mbeumo', 'shirtNo': 19, 'position': 'AMR', 'isFirstEleven': True,
           'subbedOutExpandedMinute': 70, 'stats': {'ratings': {'70': 7.2}}},
          {'playerId': 4, 'name': 'Benjamin Sesko', 'shirtNo': 9, 'position': 'Sub', 'isFirstEleven': False,
           'subbedInExpandedMinute': 70, 'stats': {'ratings': {'90': 6.5}}}],
      'formations': [{'formationName': '4231', 'captainPlayerId': 2,
                      'playerIds': [1, 2, 3, 4], 'formationSlots': [1, 10, 8, 0],
                      'formationPositions': [{'vertical': 0, 'horizontal': 5}] + [{'vertical': 3, 'horizontal': 5}] * 6
                      + [{'vertical': 7, 'horizontal': 8}, {'vertical': 7, 'horizontal': 5}, {'vertical': 8, 'horizontal': 5}, {'vertical': 9, 'horizontal': 5}],
                      'startMinuteExpanded': 0, 'endMinuteExpanded': 70}]}
them = {'teamId': THEM, 'name': 'Everton', 'players': [
    {'playerId': 9, 'name': 'James Tarkowski', 'shirtNo': 6, 'position': 'DC', 'isFirstEleven': True, 'stats': {'ratings': {'90': 6.9}}},
    {'playerId': 10, 'name': 'Iliman Ndiaye', 'shirtNo': 10, 'position': 'AMC', 'isFirstEleven': True, 'stats': {}}], 'formations': []}

events = [
    ev('Goal', US, 3, 46, isGoal=True, isShot=True),                       # Mbeumo 47'
    ev('Goal', THEM, 9, 60, ('OwnGoal',), isGoal=True, isOwnGoal=True),   # Tarkowski og → United goal
    ev('Card', US, 2, 55, ('Yellow',)),
    ev('Card', THEM, 10, 80, ('Yellow',)),
    ev('Card', THEM, 10, 88, ('SecondYellow',)),
    ev('SubstitutionOff', US, 3, 69),
    ev('SubstitutionOn', US, 4, 69, relatedPlayerId=3),
]

pub_us = ing.build_published(us, events, US)
pub_them = ing.build_published(them, events, THEM)
assert pub_us[1]['rating'] == 6.4, 'rating must be the highest MINUTE key (100), not the lexically last (96)'
assert pub_us[2]['rating'] == 8.3 and pub_us[2]['motm'] and pub_us[2]['captain']
assert pub_us[2]['yellow'] == 1 and pub_us[2]['red'] == 0
assert pub_them[10]['yellow'] == 1 and pub_them[10]['red'] == 1, 'a second yellow is a red'
assert pub_us[4]['on'] == 70 and pub_us[3]['off'] == 70
assert ing.match_rating(them['players'][1]) is None, 'no ratings block → None, never 0'

lineup = ing.build_lineup(us, NAMES, {}, pub_us, 'u')
assert len(lineup) == 1 and lineup[0]['formation'] == '4-2-3-1'
xi = lineup[0]['xi']
assert [p['slot'] for p in xi] == [1, 8, 10], 'substitutes (slot 0) are excluded and slots are sorted'
assert xi[0]['player_id'] == 'mufc_lammens_senne' and xi[0]['v'] == 0
assert xi[1]['player_id'] == 'mufc_mbeumo_bryan' and xi[1]['v'] == 7 and xi[1]['h'] == 8, 'position comes from the slot, not the list index'
assert xi[2]['rating'] == 8.3 and xi[2]['captain']
assert ing.build_lineup(them, NAMES, {}, pub_them, 'o') == [], 'no formation block → empty list, the page draws a list'

evs = ing.build_events(events, US, THEM, NAMES, pub_us, pub_them)
kinds = [(e['min'], e['kind'], e['team'], e['who']) for e in evs]
assert (47, 'goal', 'u', 'Mbeumo') in kinds
assert (61, 'goal', 'u', 'Tarkowski (og)') in kinds, 'an own goal is credited to the other side'
assert (70, 'sub', 'u', 'Sesko') in kinds and next(e for e in evs if e['kind'] == 'sub')['off'] == 'Mbeumo'
assert [e['card'] for e in evs if e['kind'] == 'card'] == ['yellow', 'yellow', 'red']
assert sum(1 for e in evs if e['kind'] == 'goal') == 2
print('ingest published blocks: 20 assertions pass')
