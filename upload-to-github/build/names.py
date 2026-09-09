#!/usr/bin/env python3
"""One definition of a player_id, shared by every writer in the pipeline.

There were two. build_payloads.py replaced six accented characters by hand and
mapped everything else to a hyphen; ingest_whoscored.py folded with NFKD and
stripped to [a-z]. They agree on the current squad and diverge on names the
Premier League produces every season — the match page linked to the id the
ingest wrote into the payload while the player file on disk was named with the
id build_payloads generated, so the first Højlund or Zaniolo in a squad would
have 404'd into the "Could not load this page" panel.

Neither script imports the other; both import this.
"""
from __future__ import annotations

import re
import unicodedata

# NFKD decomposes an accented letter into a base letter plus a combining mark.
# It does not touch a letter that is its own codepoint rather than a base plus a
# mark, and several of those are common in Premier League squads. Without this
# table Højlund folds to "hjlund", Bayındır to "baydr" and Sørloth to "srloth".
_LETTERS = {
    'ø': 'o', 'æ': 'ae', 'œ': 'oe', 'ð': 'd', 'þ': 'th', 'ł': 'l', 'ı': 'i',
    'ß': 'ss', 'đ': 'd', 'ħ': 'h', 'ŋ': 'n', 'ơ': 'o', 'ư': 'u', 'ŧ': 't',
}


def fold(s: str) -> str:
    """A name part reduced to the [a-z0-9] a URL segment can carry."""
    s = (s or '').lower()
    s = ''.join(_LETTERS.get(c, c) for c in s)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', s)


# Surname particles. A three-token name whose middle token is one of these is a
# two-part surname — "de Ligt", "van de Beek", "da Silva" — and the roster
# registry (mufc_player_registry on the iMac) mints it as one word:
# mufc_deligt_matthijs. Without this the ingest wrote mufc_ligt_matthijs for the
# same man, so his 26/27 page would have had no 25/26 baseline and the id gate
# would have failed the first time he played with --roster passed.
PARTICLES = {'de', 'da', 'di', 'do', 'dos', 'das', 'del', 'della', 'der', 'den', 'van', 'von',
             'le', 'la', 'el', 'al', 'bin', 'ben', 'mac', 'mc', 'st', 'saint', 'ter', 'ten', 'af', 'av',
             'du', 'des', 'y', 'e'}


def player_id(name: str) -> str:
    """mufc_<surname>_<first name>, folded.

    Two tokens: surname is the last, first name the first — what every existing
    payload and URL is built on, unchanged. Three or more tokens: if every middle
    token is a particle the surname is the particles and the last token joined
    ("Matthijs de Ligt" → mufc_deligt_matthijs, matching the roster); otherwise the
    last token alone, as before ("Ayden Heaven" is two, but a "Kobbie John Mainoo"
    would still be mufc_mainoo_kobbie). A one-part name drops the trailing
    underscore rather than repeating itself.
    """
    parts = (name or '').split()
    if not parts:
        raise ValueError('player_id() needs a name')
    if len(parts) == 1:
        return f'mufc_{fold(parts[0])}'
    middle = [p.lower() for p in parts[1:-1]]
    if middle and all(m in PARTICLES for m in middle):
        surname = ''.join(fold(p) for p in parts[1:])
    else:
        surname = fold(parts[-1])
    return f'mufc_{surname}_{fold(parts[0])}'


if __name__ == '__main__':
    CASES = {'Bruno Fernandes': 'mufc_fernandes_bruno', 'Matthijs de Ligt': 'mufc_deligt_matthijs',
             'Donny van de Beek': 'mufc_vandebeek_donny', 'Rasmus Højlund': 'mufc_hojlund_rasmus',
             'Casemiro': 'mufc_casemiro', 'Lisandro Martínez': 'mufc_martinez_lisandro',
             'Kobbie John Mainoo': 'mufc_mainoo_kobbie', 'Altay Bayındır': 'mufc_bayindir_altay'}
    for n, want in CASES.items():
        got = player_id(n)
        assert got == want, (n, got, want)
    print(f'names.player_id: {len(CASES)} cases pass')
