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


def player_id(name: str) -> str:
    """mufc_<surname>_<first name>, folded.

    Surname is the last whitespace-separated part and first name the first, which
    is what both previous implementations did and what the existing payloads and
    URLs are built on. A one-part name drops the trailing underscore rather than
    repeating itself.
    """
    parts = (name or '').split()
    if not parts:
        raise ValueError('player_id() needs a name')
    if len(parts) == 1:
        return f'mufc_{fold(parts[0])}'
    return f'mufc_{fold(parts[-1])}_{fold(parts[0])}'
