# MUFC · Performance — dashboard v3

A static site: `index.html` + `styles.css` + `src/` + one JSON payload per route under `data/`.
No build step is needed to serve it — GitHub Pages serves the folder as-is.

## Routes (the URL is the state)

    #/26-27/season                    running season · ledger · season v baseline · locked panels
    #/26-27/matches                   calendar, 46 fixtures
    #/26-27/matches/mw02-ips          one match · story · tape · xG race · shots · territory · players
    #/26-27/opponents/eve             the scout for the next fixture (+ "did it hold?" after)
    #/26-27/squad                     season-to-date strip · per-90 baseline · G+A · availability
    #/26-27/players/mufc_fernandes_bruno
    #/league                          25/26 table rebuilt from 380 results (26/27 unlocks at round 10)
    #/25-26/season                    the finished season: dominance trap, ledger, game state

Filters and comparisons live in the query string (`?shots=setpiece&outcome=sot`, `?metric=passes`,
`?m=mw02-ips`) so any view can be sent to someone.

## Adding a matchweek

1. Run the pipeline as usual (WhoScored capture, Twelve backfill).
2. `python3 build/build_payloads.py` — dry run. It refuses on a failed gate
   (missing sample count, per-90 under the floor, a tape key with no registry entry).
3. `python3 build/build_payloads.py --apply` — writes `data/`.
4. Upload the folder to the `mufc-dashboard` repo (or `git push` once the folder is a checkout).

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
