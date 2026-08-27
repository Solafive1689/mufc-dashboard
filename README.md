# MUFC Performance Dashboard

Manchester United, Premier League. One page, six sections, two seasons of match data.

**Live:** https://solafive1689.github.io/mufc-dashboard/

---

## What it does

United took **3.00 points per game** in the ten matches of 2025/26 they held under 45% of the ball, and **1.40** in the fifteen they held over 55%. The season finished on **1.87 PPG**. That gap is what the dashboard exists to interrogate.

2025/26 is complete — **38 matches**. 2026/27 is live and updated matchweek by matchweek.

Matchweek 1 was Hull City away. **71.7% possession, 21 shots to 8, xG 1.81 v 1.59, xT 2.98 v 0.88.** Lost 0–2. The same match again.

## Sections

- **Match** — every matchweek from one to thirty-eight. Pick any played fixture and load it: minute-by-minute timeline, shot map, territory and passing shape, a pass network with an adjustable minimum-pass threshold, and heatmaps for United, the opponent, or the difference between them.
- **Squad** — squad table, sortable by touches, passes, key passes, box touches, defensive actions or minutes.
- **Player**, **Season**, **League** — the same data cut by player, by season, and against the rest of the division.
- **Method** — how each metric is defined and where it came from. Read it before arguing with a number.

## Data

- **Twelve Football** — xG, xT.
- **WhoScored** — possession, shots, event-level match stats.
- **Derived** — metrics computed from the above.

Every figure in the dashboard carries its source tag. Nothing is unattributed.

## Running it locally

Static site, no build step. Serve the folder over http — opening `index.html` straight from the filesystem will not work, because it imports `mufc.js` as an ES module and browsers block module imports over `file://`.

```bash
git clone https://github.com/Solafive1689/mufc-dashboard.git
cd mufc-dashboard
python3 -m http.server 8000
```

Then open http://localhost:8000.

## Updating the data

`mufc.js` holds every gameweek as a keyed object — `gw1`, `gw2`, and so on. Add the new gameweek, bump the cache token in `index.html` (`mufc.js?v=N`), commit, push. Pages rebuilds in under a minute.

## Build notes

Five files, roughly **550 KB**, nothing fetched from a third party at runtime.

| File | What it is |
| --- | --- |
| `index.html` | The dashboard |
| `mufc.js` | Match data, one object per gameweek |
| `support.js` | The runtime that boots the page |
| `react.production.min.js` | React 18.3.1, vendored |
| `react-dom.production.min.js` | ReactDOM 18.3.1, vendored |

React was originally pulled from a CDN at runtime. When that CDN was unreachable the page rendered nothing at all — not a degraded version, a blank screen. Both files now live in the repo, so the site depends on nothing but GitHub.

---

Built by **Reece Howell** — MSc Sport Performance Analysis, Twelve Football ambassador.
