#!/usr/bin/env bash
#
# publish.sh — build the dashboard payloads and deploy to Netlify.
#
# Route A: git is not in the hot path. No commit, no push, no PR, no keychain,
# no .git/*.lock. GitHub stays as the archive and is pushed on your own schedule.
#
#   ./publish.sh              gate only, deploy nothing   (default — safe)
#   ./publish.sh --deploy     gate, then deploy to production
#   ./publish.sh --draft      gate, then deploy a preview URL only
#
# First run: see SETUP at the bottom.

set -euo pipefail

# ─────────────────────────────────────────── config (edit these three)
DASH_REPO="${DASH_REPO:-$HOME/Desktop/mufc-dashboard-push}"
STAGE_DIR="${STAGE_DIR:-$HOME/Desktop/.mufc-publish-stage}"
NETLIFY_SITE="${NETLIFY_SITE:-}"   # site name or ID; blank uses the linked site
# The pipeline venv. Bare python3 on this machine is a package-less 3.14, so the
# build must run on the interpreter that has pandas et al. Override with PY=... if
# the venv moves.
PY="${PY:-$HOME/Desktop/MUFC_Analytics/.venv/bin/python}"
# The season tracker is a single self-contained HTML file in the pipeline repo
# (no relative asset paths — verified before this was added). It is served at
# /tracker/ on the same site, copied straight into the staged folder at deploy
# time; it never enters this repo, so the data/ reproducibility gate is untouched.
# Blank to leave the tracker off the site.
TRACKER="${TRACKER:-$HOME/Desktop/MUFC_Analytics/mufc_2026_27_tracker.html}"

# Everything that should be served. Anything not listed is never uploaded —
# this is the allowlist that keeps private/ off the public internet.
PUBLISH_PATHS=(
  index.html
  styles.css
  src
  data
  figures
)

MODE="gate"
case "${1:-}" in
  --deploy) MODE="prod" ;;
  --draft)  MODE="draft" ;;
  "")       ;;
  *) echo "usage: $0 [--deploy|--draft]" >&2; exit 2 ;;
esac

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

cd "$DASH_REPO" || die "dashboard repo not found at $DASH_REPO"
[ -x "$PY" ] || die "venv interpreter not found at $PY (set PY=...)"

# ─────────────────────────────────────────── 1. build
say "1/5  Building payloads (dry run)"
"$PY" build/build_payloads.py 2>&1 | tee /tmp/mufc_payload_dry.log
grep -qiE 'fail|error|refus' /tmp/mufc_payload_dry.log \
  && die "dry run reported a problem — read /tmp/mufc_payload_dry.log, fix, re-run"

say "2/5  Applying"
"$PY" build/build_payloads.py --apply

# ─────────────────────────────────────────── 2. gates
say "3/5  Gates"

# Reproducibility: a second apply must not change anything.
BEFORE=$(find data -type f -exec shasum {} \; | sort | shasum | cut -d' ' -f1)
"$PY" build/build_payloads.py --apply >/dev/null
AFTER=$(find data -type f -exec shasum {} \; | sort | shasum | cut -d' ' -f1)
[ "$BEFORE" = "$AFTER" ] || die "data/ is not reproducible — two identical runs differ"
echo "  ok  data/ reproducible"

for f in build/build_payloads.py build/ingest_whoscored.py; do
  "$PY" -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" \
    || die "$f does not parse"
done
echo "  ok  build scripts parse"

[ -d private ] && {
  printf '%s\n' "${PUBLISH_PATHS[@]}" | grep -qx private \
    && die "private/ is in PUBLISH_PATHS — remove it"
}
echo "  ok  private/ not in the publish allowlist"

# Availability note staleness (the Thursday check from the weekly design)
NOTES=build/notes/availability-26-27.json
if [ -f "$NOTES" ]; then
  CHECKED=$("$PY" -c "import json;print(json.load(open('$NOTES')).get('checked','?'))")
  echo "  --  availability last checked: $CHECKED"
fi

# ─────────────────────────────────────────── 3. stage
say "4/5  Staging publishable files"
rm -rf "$STAGE_DIR"; mkdir -p "$STAGE_DIR"
for p in "${PUBLISH_PATHS[@]}"; do
  [ -e "$p" ] && cp -R "$p" "$STAGE_DIR/" && echo "  + $p"
done
if [ -n "$TRACKER" ]; then
  [ -f "$TRACKER" ] || die "tracker not found at $TRACKER (set TRACKER= to skip)"
  # Refuse a tracker that references anything by relative path — the file is
  # served alone, so a relative src/href would 404 on the site.
  if grep -qE '(src|href)="(\./|\.\./|[A-Za-z0-9_-]+/)[^"]*\.(js|css|png|jpg|svg|json)"' "$TRACKER"; then
    die "tracker carries relative asset references — it would not render alone at /tracker/"
  fi
  mkdir -p "$STAGE_DIR/tracker" && cp "$TRACKER" "$STAGE_DIR/tracker/index.html" && echo "  + tracker/index.html  ($(du -h "$TRACKER" | cut -f1), from $(basename "$TRACKER"))"
fi
find "$STAGE_DIR" -name '.DS_Store' -delete
echo "  staged $(find "$STAGE_DIR" -type f | wc -l | tr -d ' ') files, $(du -sh "$STAGE_DIR" | cut -f1)"

# ─────────────────────────────────────────── 4. deploy
if [ "$MODE" = "gate" ]; then
  say "5/5  Gate-only run — nothing deployed"
  echo "  staged at $STAGE_DIR"
  echo "  re-run with --deploy to ship, or --draft for a preview URL"
  exit 0
fi

command -v netlify >/dev/null || die "netlify CLI not installed (npm i -g netlify-cli)"

SITE_ARG=()   # empty array: expanded with the [@]+ idiom below, which bash 3.2 + set -u needs
[ -n "$NETLIFY_SITE" ] && SITE_ARG=(--site "$NETLIFY_SITE")

if [ "$MODE" = "prod" ]; then
  say "5/5  Deploying to production"
  netlify deploy --prod --dir "$STAGE_DIR" ${SITE_ARG[@]+"${SITE_ARG[@]}"}
else
  say "5/5  Deploying draft"
  netlify deploy --dir "$STAGE_DIR" ${SITE_ARG[@]+"${SITE_ARG[@]}"}
fi

say "Done. GitHub is untouched — push the archive whenever you like:"
echo "  cd $DASH_REPO && git add -A && git commit -m 'gwN' && git push"

# ─────────────────────────────────────────── SETUP (once)
#
#   npm install -g netlify-cli
#   netlify login
#   cd ~/Desktop/mufc-dashboard-push && netlify link      # or: netlify sites:create
#   chmod +x publish.sh
#
# PUBLISH_PATHS was checked against the repo root on 13 Sep 2026: index.html
# loads styles.css, src/charts.js and src/app.js, so those are staged; there is
# no assets/ directory. Run once in gate mode and read the staged file list
# before the first --deploy.
#
# Two things this deliberately does NOT do:
#   - It does not scrape. WhoScored capture needs a real local Chrome via
#     undetected-chromedriver and stays a separate manual step before this runs.
#   - It does not touch git. That is the entire point of Route A.
