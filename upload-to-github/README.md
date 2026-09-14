# MUFC · Performance — dashboard v3

A static site: `index.html` + `styles.css` + `src/` + one JSON payload per route under `data/`.
No build step is needed to serve it — GitHub Pages serves the folder as-is.

## Routes (the URL is the state)

    #/26-27/season                    running season · filter row · ledger · pace v 25/26 · turning points · availability
    #/26-27/season?venue=A&tier=top   the same page, only away matches against last season's top six
    #/26-27/season?with=<player_id>   only matches that player was on the pitch for (without=… for the inverse)
    #/26-27/matches                   calendar, 46 fixtures
    #/26-27/matches/mw02-ips          one match · story · tape · xG race · shots · territory · players
    #/26-27/opponents/eve             the scout for the next fixture (+ "did it hold?" after)
    #/26-27/squad                     season-to-date strip · per-90 baseline · G+A · availability
    #/26-27/players/mufc_fernandes_bruno
    #/league                          25/26 table rebuilt from 380 results (26/27 unlocks at round 10)
    #/25-26/season                    the finished season: by matchweek with the coach eras, trap, xG every match, with & without

Filters and comparisons live in the query string (`?shots=setpiece&outcome=sot`, `?metric=passes`,
`?m=mw02-ips`) so any view can be sent to someone.

## Adding a matchweek

1. Run the pipeline as usual (WhoScored capture, Twelve backfill).
2. `python build/ingest_whoscored.py --mcd logs/mcd_<...>.json --gw N --roster <roster.csv> --master <master.csv> --apply`
   — writes `build/matches/gwN.json` with the counted blocks AND WhoScored's published ones
   (lineup slots, goals/subs/cards, ratings, cards). A cup tie or European matchday takes
   `--comp EFL` / `--comp UCL` and lands as `build/matches/efl3.json` / `ucl1.json`.
3. Drop `build/twelve/gwN.json` and `build/understat/gwN-players.json` in when they arrive.
4. Update the authored notes if the week earned it: `build/notes/season-26-27.json` (headline),
   `build/notes/turning-points.json` (a point, with an `assert` the build checks),
   `build/notes/availability-26-27.json` (who is out, checked date, source),
   `build/fixtures/cups.json` (a newly drawn tie).
5. `python3 build/build_payloads.py` — dry run. It refuses on a failed gate.
6. `python3 build/build_payloads.py --apply` — writes `data/`. The season, squad, pace,
   turning points and availability panels rebuild themselves from what is there.
7. Upload the folder to the `mufc-dashboard` repo (or `git push` once the folder is a checkout).

MW1 and MW2 came through the v2 export, which never carried lineups, events or ratings.
Re-running the ingest for `--gw 1` and `--gw 2` against their `logs/mcd_*.json` grafts
those blocks onto the published payloads without touching anything the v2 source says;
the build refuses the graft if the scoreline or the players differ.

## The narrative layer

`build/story.py` counts eras, streaks, cumulative pace and rolling form from the ledger
and checks every authored note against it. A turning point whose `assert` (score, result,
opponent, goal minute, scorer) no longer matches the data fails the build. Eras must tile
the season. The season pages read `story.*`; nothing narrative is typed into the view.

`build_payloads.py` currently reads `build/v2_source.json` (the v2 `mufc.js` objects). To point it at
the pipeline's CSVs, replace `load_source()`; every projection reads from that one dict.

## Provenance rule

Sample badges (n, pending, below floor, caveat) sit on KPI tiles. The source class is written in
words in each panel footer and shown on hover. A per-figure source badge appears only when it is a
warning (modelled / proxy / inferred). Hover any number for its source.

## Previews and the private export

    python3 build/bundle.py            → preview.html   (everything inlined; public content only)
    python3 build/bundle.py --staff    → staff-preview.html (adds private/eve-staff.json: coaching calls
                                          and the "show sources" per-figure badges)

`private/` is never part of the public folder. Do not upload it.

## Payload shapes

See the docstring at the top of `build/build_payloads.py`. Every 26/27 payload carries
`meta.sample`; per-90 values are `null` under 450 minutes; NaN stays `null` and renders as an em dash.
