/* app.js — MUFC Performance v3. Hash router, route payloads, components, six pages.
   URL is state: #/26-27/matches/mw02-ips?shots=setpiece · #/26-27/opponents/eve · #/league
   Data: data/<route>.json, or window.__DATA__[path] when bundled as a single file. */
window.MUFC = window.MUFC || {};
(function (M) {
  const C = M.charts;
  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
  const num = (v, d = 0) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
  const SRC_WORDS = { whoscored: 'WhoScored, published', twelve: 'Twelve, vendor model', counted: 'counted from the event stream', derived: 'derived', inferred: 'inferred', mixed: 'mixed sources', understat: 'Understat, published', modelled: 'modelled from the vendor total' };
  const SRC_BADGE = { whoscored: 'pub', twelve: 'ven', counted: 'cnt', derived: 'derived', inferred: 'mod', modelled: 'mod' };

  // ------------------------------------------------------------------ data
  const cache = {};
  async function load(path) {
    if (cache[path]) return cache[path];
    if (window.__DATA__ && window.__DATA__[path]) return (cache[path] = window.__DATA__[path]);
    const r = await fetch(`data/${path}`);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return (cache[path] = await r.json());
  }
  let IDX = null, REG = {};

  // ------------------------------------------------------------------ state + router
  const state = { season: '26-27', comp: 'PL', fixture: null, baseline: true, staff: false };
  function parse() {
    const h = location.hash.replace(/^#\/?/, '');
    const [pathPart, q] = h.split('?');
    const parts = pathPart.split('/').filter(Boolean);
    const query = Object.fromEntries(new URLSearchParams(q || ''));
    let season = '26-27', page = 'season', id = null;
    if (parts[0] === 'league') { page = 'league'; }
    else if (parts[0] === '26-27' || parts[0] === '25-26') { season = parts[0]; page = parts[1] || 'season'; id = parts[2] || null; }
    else if (parts.length) { page = parts[0]; id = parts[1] || null; }
    return { season, page, id, query };
  }
  function href(page, id, query) { const s = page === 'league' ? '#/league' : `#/${state.season}/${page}${id ? '/' + id : ''}`; return query ? `${s}?${new URLSearchParams(query)}` : s; }
  function go(page, id, query) { location.hash = href(page, id, query).slice(1); }
  function setQuery(patch) { const r = parse(); const q = { ...r.query, ...patch }; Object.keys(q).forEach(k => (q[k] === null || q[k] === '' || q[k] === 'all') && delete q[k]); location.hash = href(r.page, r.id, Object.keys(q).length ? q : null).slice(1); }

  // ------------------------------------------------------------------ components
  // What each panel is made of, so Export writes the data and not the pixels.
  const EXPORTS = {};
  function badge(kind, text) { return `<span class="badge badge--${kind}">${esc(text)}</span>`; }
  // The source string, in the DOM, for anything that reads the page rather than
  // looks at it. Costs one hidden span and needs no ARIA plumbing.
  function srSource(text) { return `<span class="sr"> · Source: ${esc(text)}</span>`; }
  function sampleBadge(n, word = 'match') { return badge('sample', `n = ${n} ${word}${n === 1 ? '' : 'es'}`); }
  function srcWords(k) { return SRC_WORDS[k] || k; }
  function reg(k) { return REG[k] || { label: k, unit: '', fmt: '1', source: 'derived' }; }

  function contextBar(route) {
    const fx = IDX.fixtures;
    const nextFx = fx.find(f => f.comp === 'PL' && f.status !== 'played') || fx.at(-1);
    const cur = state.fixture ? fx.find(f => f.fixture_id === state.fixture) : nextFx;
    const chip = (on, label, attrs = '') => `<button class="chip ${on ? 'on' : ''}" ${attrs}>${label}</button>`;
    return `<header class="ctx"><div class="ctx__in">
      <span class="ctx__brand">MUFC · Performance</span>
      <span class="ctx__lab">Season</span>${chip(state.season === '26-27', '26/27', 'data-act="season" data-v="26-27"')}${chip(state.season === '25-26', '25/26', 'data-act="season" data-v="25-26"')}
      <span class="ctx__lab">Competition</span>${chip(state.comp === 'PL', 'PL', 'data-act="comp" data-v="PL"')}${chip(state.comp === 'UCL', 'UCL', 'data-act="comp" data-v="UCL" disabled title="No Champions League data in the pipeline yet"')}${chip(state.comp === 'ALL', 'All', 'data-act="comp" data-v="ALL"')}
      <span class="ctx__lab">Fixture</span>${chip(true, `${cur.comp === 'PL' ? 'MW' + cur.round : 'MD' + cur.round} ${esc(cur.short)} (${cur.venue}) · ${cur.status === 'played' ? cur.score.replace('-', '–') : esc(cur.date.slice(5))}`, `data-act="fixture" data-v="${cur.fixture_id}"`)}
      <span class="ctx__lab">Baseline</span>${chip(state.baseline, `25/26 ${state.baseline ? '✓' : ''}`, 'data-act="baseline"')}
      <span class="ctx__flex"></span>
      ${state.staff ? badge('staff', 'Staff · private export') : ''}
      <span class="ctx__find">Hover any number for its source</span>
    </div></header>`;
  }
  const NAV = [['season', 'Season'], ['matches', 'Matches'], ['opponents', 'Opponents'], ['squad', 'Squad'], ['league', 'League']];
  function nav(route, lineage) {
    const active = route.page === 'players' ? 'squad' : route.page;
    return `<nav class="nav"><div class="nav__in">
      ${NAV.map(([k, l]) => `<a class="nav__item ${active === k ? 'on' : ''}" href="${href(k)}">${l}</a>`).join('')}
      <span class="nav__flex"></span><span class="nav__lineage">${lineage}</span>
    </div></nav>`;
  }
  function rail(items) {
    return `<aside class="rail" aria-label="On this page">${items.map(([id, label, locked], i) => `<a href="#${id}" data-rail="${id}" class="${i === 0 ? 'on' : ''} ${locked ? 'locked' : ''}">${esc(label)}</a>`).join('')}</aside>`;
  }
  function claim(c, opts = {}) {
    const [a, b] = c.headline;
    return `<section class="claim ${opts.opp ? 'opp' : ''}" id="claim">
      <div class="claim__eye"><span class="t-eyebrow">${esc(c.eyebrow)}</span>${opts.badge || ''}</div>
      <h1 class="t-claim">${esc(a)} <em>${esc(b)}</em></h1>
      <p class="t-body">${esc(c.lead)}</p>
    </section>`;
  }
  function kpi(o) {
    const r = o.key ? reg(o.key) : {};
    const label = o.label || r.label; const unit = o.unit ?? r.unit ?? '';
    const pending = o.pending || o.value === null || o.value === undefined;
    const floor = o.floor;
    const badges = [];
    if (o.n !== undefined) badges.push(sampleBadge(o.n));
    if (pending) badges.push(badge('pending', 'Twelve pending'));
    if (floor) badges.push(badge('caveat', `under ${floor}′`));
    if (o.caveat) badges.push(badge('caveat', `caveat ${o.caveat}`));
    if (o.mod) badges.push(badge('mod', 'modelled'));
    if (state.staff && o.key) badges.push(badge(SRC_BADGE[r.source] || 'derived', r.source));
    const def = `${label} · ${srcWords(o.src || r.source)}${r.opp_share != null ? ` · ${Math.round(r.opp_share * 100)}% of its variation is fixture` : ''}`;
    return `<div class="kpi ${pending ? 'kpi--pending' : ''} ${floor ? 'kpi--floor' : ''}" data-tip="${esc(def)}" tabindex="0">
      <div class="kpi__lab">${esc(label)}${srSource(def)}</div>
      <div class="kpi__v"><span class="t-kpi">${pending ? '—' : esc(o.value)}</span>${unit && !pending ? `<span class="kpi__u">${esc(unit)}</span>` : ''}</div>
      <div class="kpi__ctx">${esc(o.note || '')}</div>
      ${badges.length ? `<div class="kpi__badges">${badges.join('')}</div>` : ''}
    </div>`;
  }
  function panel(o) {
    if (o.data) EXPORTS[o.id] = o.data;
    const foot = [];
    if (o.n !== undefined) foot.push(sampleBadge(o.n, o.nWord));
    if (o.pending) foot.push(badge('pending', typeof o.pending === 'string' ? o.pending : 'Twelve pending'));
    if (o.mod) foot.push(badge('mod', 'modelled'));
    if (o.validated) foot.push(badge('verified', o.validated));
    if (o.src) foot.push(`<span>${esc(srcWords(o.src))} ·</span>`);
    if (o.note) foot.push(`<span>${esc(o.note)}</span>`);
    return `<section class="panel ${o.locked ? 'panel--locked' : ''}" id="${o.id || ''}">
      <div class="panel__head"><div><h2 class="panel__title">${esc(o.title)}</h2>${o.intro ? `<p class="panel__intro">${esc(o.intro)}</p>` : ''}</div>
        ${o.locked ? '' : `<button class="panel__export" data-export="${o.id || ''}" title="Download the rows behind this panel as CSV">↓ Export</button>`}</div>
      ${o.filters ? `<div class="panel__filters">${o.filters}</div>` : ''}
      <div class="panel__body">${o.locked ? `<b>Unlocks at ${o.locked.at} matches</b><span class="t-cap">${o.locked.played} played · ${esc(o.locked.why || 'the sample needs to exist before the pattern can be read')}</span>` : o.body}</div>
      ${foot.length ? `<div class="panel__foot">${foot.join('')}</div>` : ''}
    </section>`;
  }
  function filterChips(param, current, options) {
    return options.map(([v, label, count]) => `<button class="chip chip--filter ${(current || 'all') === v ? 'on' : ''}" data-filter="${param}" data-v="${v}">${esc(label)}${count !== undefined ? `<span class="n">${count}</span>` : ''}</button>`).join('');
  }
  function cmpRow(o) {
    const a = Number(o.united), b = Number(o.opp);
    const f = (Number.isFinite(a) && Number.isFinite(b) && a + b > 0) ? a / (a + b) : 0.5;
    const r = o.key ? reg(o.key) : {};
    const d = o.key ? (r.fmt ?? '1') : (o.d ?? 1);
    // A row whose supplier has reported for fewer matches than the season has played is
    // an average over a different denominator. Say which, rather than letting it sit in a
    // column of rows that all look like they cover the same matches.
    const short = o.n !== undefined && o.seasonN !== undefined && o.n < o.seasonN;
    let delta = '';
    if (o.delta !== undefined) { const good = r.direction === 'higher' ? o.delta > 0 : (r.direction === 'lower' ? o.delta < 0 : null); delta = `<span class="cmp__delta ${good === null ? '' : good ? 'good' : 'bad'}">${o.delta > 0 ? '+' : ''}${fmt(o.delta, d)}</span>`; }
    const tick = (state.baseline && o.baseline !== undefined && Number.isFinite(o.baseline) && a > 0) ? `<i class="cmp__tick" style="left:${Math.min(49, Math.max(1, (1 - Math.min(1, o.baseline / (a + b))) * 50)).toFixed(1)}%" data-tip="25/26 median ${o.baseline}"></i>` : '';
    // A row whose source has not landed yet reads as a dash with no bar. Drawing a
    // half-and-half bar off two nulls would say "level", which is a claim we do not have.
    const pend = !!o.pending;
    const bars = `${tick}<span class="cmp__bar u"><i style="width:${(f * 100).toFixed(1)}%"></i></span><span class="cmp__bar o ${o.grey ? 'grey' : ''}"><i style="width:${((1 - f) * 100).toFixed(1)}%"></i></span>`;
    const tip = (o.label || r.label) + ' · ' + (pend ? 'Twelve report pending' : srcWords(o.src || r.source))
      + (short ? ` · averaged over ${o.n} of ${o.seasonN} matches` : '');
    return `<div class="cmp${pend ? ' cmp--pending' : ''}" data-tip="${esc(tip)}" tabindex="0">
      <span class="cmp__lab ${o.hot ? 'hot' : ''}">${esc(o.label || r.label)}${srSource(tip)}</span>
      <span class="cmp__u">${pend ? '—' : (o.uText ?? fmt(a, d))}</span>
      <span class="cmp__bars">${pend ? '' : bars}</span>
      <span class="cmp__o">${pend ? '—' : (o.oText ?? fmt(b, d))}</span>
      <span>${pend ? '<span class="cmp__base">Twelve pending</span>' : delta + (short ? `<span class="cmp__base cmp__base--short">n = ${o.n} of ${o.seasonN}</span>` : (o.base ? `<span class="cmp__base">${esc(o.base)}</span>` : ''))}</span>
    </div>`;
  }
  function fixtureHeader(fx, opts = {}) {
    const played = fx.status === 'played';
    const title = fx.venue === 'H' ? `Man United v ${fx.opp}` : `${fx.opp} v Man United`;
    const eyebrow = `${fx.comp === 'PL' ? 'MW' + fx.round : 'MD' + fx.round} · ${fx.comp === 'PL' ? 'Premier League' : 'Champions League'} · ${new Date(fx.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}`;
    let status;
    if (opts.back) status = `<a class="fx__status" href="${opts.back}">‹ Back to ${esc(opts.backLabel || 'match')}</a>`;
    else if (played) status = `<span class="fx__status played ${fx.result}">${esc(fx.score.replace('-', '–'))}<small>${fx.result}</small></span>`;
    else if (fx.scout) status = `<a class="fx__status scout" href="${href('opponents', fx.scout)}">Scout ready ›</a>`;
    else status = `<span class="fx__status">Scheduled</span>`;
    let crest = `<span class="fx__crest" data-crest="${esc(fx.code)}"></span>`;
    if (IDX.crests && IDX.crests[fx.code]) crest = `<img class="fx__crest" src="${IDX.crests[fx.code]}" alt="">`;
    else M.crests().then(c => { const slot = document.querySelector(`[data-crest="${fx.code}"]`);
      if (slot && c[fx.code]) slot.outerHTML = `<img class="fx__crest" src="${c[fx.code]}" alt="">`; });
    return `<div class="fx ${opts.opp ? 'opp' : ''}"><span class="fx__rule"></span>${crest}
      <div class="fx__text"><div class="fx__eye">${esc(eyebrow)}</div><div class="fx__title">${esc(title)}</div>
      <div class="fx__det">${played ? `Full time · ${fx.venue === 'H' ? 'Home' : 'Away'} · xG ${fmt(fx.xg, 2)} : ${fmt(fx.oxg, 2)}` : `${esc(fx.ko)} · ${fx.venue === 'H' ? 'Home' : 'Away'} · ${esc(fx.tv || '')}${fx.rest_days ? ` · ${fx.rest_days}d rest` : ''}`}</div></div>
      ${status}</div>`;
  }
  function table(cols, rows, opts = {}) {
    if (opts.id) EXPORTS[opts.id] = {
      head: cols.map(c => c.h),
      rows: rows.map(r => cols.map(c => r[c.key] !== undefined ? r[c.key] : ''))};
    const th = cols.map(c => `<th class="${c.r ? 'r' : ''} ${c.cls || ''}">${esc(c.h)}</th>`).join('');
    // A drill-down used to be a click handler on the <tr>: no tab stop, no Enter,
    // no middle-click, nothing for a crawler. The naming column now carries a real
    // anchor to the same hash, and the row-wide click stays as a mouse convenience
    // (the handler already ignores clicks that land on an a or a button).
    const linkCol = Math.max(0, cols.findIndex(c => c.k));
    const body = rows.map(r => `<tr class="${r._cls || ''} ${r._href ? 'link' : ''}" ${r._href ? `data-href="${r._href}"` : ''}>${cols.map((c, i) => {
      const inner = c.f ? c.f(r) : esc(r[c.key]);
      const cell = (r._href && i === linkCol) ? `<a class="cell__link" href="${esc(r._href)}">${inner}</a>` : inner;
      return `<td class="${c.r ? 'r' : ''} ${c.k ? 'k' : ''} ${c.m ? 'm' : ''} ${c.cls || ''} ${i === 0 && r._href ? 'drill' : ''}">${cell}</td>`;
    }).join('')}</tr>`).join('');
    return `<div class="wide"><table>${opts.noHead ? '' : `<thead><tr>${th}</tr></thead>`}<tbody>${body}</tbody></table>${opts.more ? `<div class="more">${opts.more}</div>` : ''}</div>`;
  }
  function locked(id, title, intro, at, played, why) { return panel({ id, title, intro, locked: { at, played, why } }); }

  // ------------------------------------------------------------------ pages
  async function pageSeason(route) {
    if (state.season === '25-26') return pageSeasonComplete(route);
    const S = await load('26-27/season.json');
    const n = S.meta.sample.matches;
    const kpis = S.kpis.map(k => kpi({ ...k, n, value: k.value, note: k.note }));
    const ledgerRows = [];
    IDX.fixtures.filter(f => f.comp === 'PL').forEach(f => {
      const pl = S.ledger.find(r => r.round === f.round);
      const isCur = state.fixture ? state.fixture === f.fixture_id : (!pl && !ledgerRows.some(r => r._cls === 'hot'));
      ledgerRows.push(pl ? { mw: `MW${f.round}`, opp: `${f.opp}  ${f.venue}`, res: pl.result, score: `${pl.result} ${pl.gf}–${pl.ga}`, xg: `${fmt(pl.xg, 2)} : ${fmt(pl.oxg, 2)}`, _href: href('matches', pl.match), _cls: '' }
        : { mw: `MW${f.round}`, opp: `${f.opp}  ${f.venue}`, res: '', score: new Date(f.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }), xg: f.scout ? 'Scout ready ›' : '—', _href: f.scout ? href('opponents', f.scout) : null, _cls: isCur ? 'hot' : 'future' });
    });
    const shown = route.query.all ? ledgerRows : ledgerRows.slice(0, 6);
    const ledger = table([{ h: '#', key: 'mw', cls: 'mono' }, { h: 'Opponent', key: 'opp', k: true }, { h: 'Result', key: 'score', f: r => `<span class="res-${r.res}">${esc(r.score)}</span>` }, { h: 'xG for : against', key: 'xg', m: true, f: r => r.xg.startsWith('Scout') ? `<span style="color:var(--opponent);font-weight:600">${r.xg}</span>` : esc(r.xg) }], shown,
      { id: 'ledger', more: route.query.all ? '' : `… ${ledgerRows.length - 6} more rows · <button data-q="all=1">show all</button>` });
    // Three of the five panels on this page were locked, and the layout put one live
    // panel beside one locked one and then a whole row of two more. Locked panels are
    // the right idea — they are the most honest thing on the site — but at n = 3 they
    // made the front door read as an empty building. They collapse into one strip,
    // and the space goes to the match that was actually played.
    const LOCKS = [
      ['The dominance trap', S.locks.dominance.at, 'points per game by possession band, split on ws_possession_pct'],
      ['Game state', S.locks.gamestate.at, 'shots, xG and goals per 90 while level, ahead and behind'],
      ['Opponent-adjusted', S.locks.adjusted.at, 'each match against what the fixture alone would predict']];
    const unlocks = `<section class="unlocks" id="unlocks"><div class="unlocks__head"><span class="t-label">What unlocks as the season builds</span><span class="t-cap">${n} of 38 played · these stay closed until the sample can carry them</span></div>
      <div class="unlocks__list">${LOCKS.map(([t, at, why]) => `<div class="unlocks__item ${n >= at ? 'open' : ''}"><b>${esc(t)}</b><span class="t-cap">${esc(why)}</span><span class="pill ${n >= at ? '' : 'warn'}">${n >= at ? 'open' : `${at - n} more`}</span></div>`).join('')}</div></section>`;

    const lastPlayed = [...IDX.fixtures].filter(f => f.status === 'played').at(-1);
    const latest = lastPlayed ? `<a class="latest" href="${href('matches', lastPlayed.match)}">
      <span class="t-label">Last played · MW${lastPlayed.round}</span>
      <div class="latest__score"><span class="res-${lastPlayed.result}">${esc(lastPlayed.score.replace('-', '–'))}</span><span>${esc(lastPlayed.opp)} (${lastPlayed.venue})</span></div>
      <div class="latest__k"><span>xG</span><b>${fmt(lastPlayed.xg, 2)} : ${fmt(lastPlayed.oxg, 2)}</b></div>
      <span class="latest__go">Open the match ›</span></a>` : '';

    EXPORTS.svs = { head: ['metric', '26/27 per match', '25/26 per match', 'delta', 'matches averaged'],
      rows: S.season_v_season.map(r => [reg(r.key).label, r.now, r.base,
        r.now === null ? '' : Number((r.now - r.base).toFixed(3)), r.n]) };
    const svs = S.season_v_season.map(r => cmpRow({ key: r.key, united: r.now, opp: r.base, grey: true, base: '25/26',
      delta: (r.now === null || r.now === undefined) ? undefined : r.now - r.base,
      pending: r.pending, n: r.n, seasonN: n }));
    return {
      lineage: `26/27 › Season`,
      rail: [['claim', 'Claim & numbers'], ['ledger', 'Ledger, 1–38'], ['svs', 'Season v baseline'], ['unlocks', 'What unlocks next']],
      body: `${claim(S.claim, { badge: sampleBadge(n) })}
        <div class="kpis">${kpis.join('')}</div>
        ${panel({ id: 'ledger', title: 'Ledger · every matchweek, 1–38', intro: 'One row per fixture in order. Played rows carry the result and both xG figures; the selected fixture is highlighted; future rows open the scout when one exists.', body: ledger, n, src: 'counted', note: '38 fixtures · identity layer of the team master' })}
        <div class="row row--wide">
          ${panel({ id: 'svs', title: 'Season against season', intro: `26/27 per match in red, 25/26 per match in grey. ${n < 6 ? `${n} matches is not a season — read the direction, not the size.` : 'Read the direction before the size.'}`, body: svs.join(''), n, src: 'mixed', note: 'derived from the two team masters' })}
          ${latest}
        </div>
        ${unlocks}`
    };
  }

  async function pageSeasonComplete() {
    const S = await load('25-26/season.json');
    const rows = S.ledger.map(m => ({ mw: `MW${m.gw}`, opp: `${m.opp}  ${m.ven}`, res: m.res, score: `${m.res} ${m.gf}–${m.ga}`, xg: `${fmt(m.xg, 2)} : ${fmt(m.oxg, 2)}`, pts: m.pts }));
    const buckets = S.buckets.map(b => `<div class="tile"><span class="t-code">${esc(b.lab)}</span><b>${fmt(b.ppg, 2)}<small>ppg</small></b><span>${b.n} matches · ${b.pts} points</span></div>`).join('');
    const states = S.gamestate.states.map(s => `<tr><td class="k">${esc(s.s)}</td><td class="r">${s.min}</td><td class="r">${s.n}</td><td class="r">${fmt(s.poss, 0)}%</td><td class="r">${fmt(s.sh, 1)}</td><td class="r">${fmt(s.xg, 2)}</td><td class="r">${fmt(s.xga, 2)}</td><td class="r">${s.goals}</td><td class="r">${s.conc}</td></tr>`).join('');
    return {
      lineage: '25/26 › Season · complete',
      rail: [['claim', 'Claim & numbers'], ['trap', 'Dominance trap'], ['ledger', 'Ledger, 1–38'], ['gamestate', 'Game state']],
      body: `${claim(S.claim, { badge: badge('verified', 'validated 20 / 20') })}
        ${panel({ id: 'trap', title: 'The dominance trap · points per game by possession band', intro: 'Split on ws_possession_pct and named as such: the two suppliers measure possession differently, and a split that does not name its column is not reproducible.', body: `<div class="tiles">${buckets}</div>`, n: 38, src: 'whoscored', note: `correlation r = ${S.trap.r} · p = ${S.trap.p}` })}
        ${panel({ id: 'ledger', title: 'Ledger · 2025/26', body: table([{ h: '#', key: 'mw' }, { h: 'Opponent', key: 'opp', k: true }, { h: 'Result', key: 'score', f: r => `<span class="res-${r.res}">${esc(r.score)}</span>` }, { h: 'xG', key: 'xg', m: true }, { h: 'Pts', key: 'pts', r: true }], rows), n: 38, src: 'mixed' })}
        ${panel({ id: 'gamestate', title: 'Game state · what changed with the score', intro: 'Per state: minutes, matches, possession, shots and xG per 90, goals for and against.', body: `<div class="wide"><table><thead><tr><th>State</th><th class="r">Min</th><th class="r">Matches</th><th class="r">Poss</th><th class="r">Shots/90</th><th class="r">xG/90</th><th class="r">xGA/90</th><th class="r">G</th><th class="r">GA</th></tr></thead><tbody>${states}</tbody></table></div>`, n: 38, src: 'mixed', note: `${S.gamestate.totMin} minutes across ${S.gamestate.nRows} state windows` })}`
    };
  }

  async function pageMatches() {
    const rows = IDX.fixtures.filter(f => state.comp === 'ALL' || f.comp === state.comp).map(f => ({
      date: new Date(f.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }), comp: f.comp, rd: (f.comp === 'PL' ? 'MW' : 'MD') + f.round,
      opp: f.opp, ven: f.venue === 'H' ? 'Home' : 'Away', rest: f.rest_days ? `${f.rest_days}d` : '—', tv: f.tv || 'Not selected',
      ko: f.status === 'played' ? f.score.replace('-', '–') : f.ko, res: f.result || '', _href: f.match ? href('matches', f.match) : (f.scout ? href('opponents', f.scout) : null), _cls: f.status === 'played' ? '' : (f.scout ? 'hot' : 'future')
    }));
    const next = IDX.fixtures.find(f => f.status !== 'played');
    return {
      lineage: '26/27 › Matches',
      rail: [['next', 'Next up'], ['calendar', 'Calendar · 46 fixtures']],
      body: `<div id="next">${fixtureHeader(next)}</div>
        ${panel({ id: 'calendar', title: 'Every fixture, league and Europe', intro: 'One column in date order so the calendar reads the way the season is played. Rest is days since the previous match in either competition. Played rows open the match; the next fixture opens the scout.', body: table([{ h: 'Date', key: 'date' }, { h: 'Comp', key: 'comp', cls: 'mono' }, { h: 'Round', key: 'rd', cls: 'mono' }, { h: 'Opponent', key: 'opp', k: true }, { h: 'Venue', key: 'ven', cls: 'tab-hide' }, { h: 'Rest', key: 'rest', cls: 'tab-hide' }, { h: 'Broadcast', key: 'tv', m: true, cls: 'ph-hide' }, { h: 'Kick-off / score', key: 'ko', r: true, f: r => r.res ? `<span class="res-${r.res}">${esc(r.ko)}</span>` : esc(r.ko) }], rows, { id: 'calendar' }), src: 'counted', note: '46 fixtures · 38 league, 8 Champions League · kick-offs subject to change' })}`
    };
  }

  const SIT = { open: 'Open play', corner: 'Corner', freekick: 'Free kick', throwin: 'Throw-in', fastbreak: 'Fast break', penalty: 'Penalty' };
  function sitsList(obj, who, cls) {
    // `v.xg ?? v[1] ?? 0` turned a pending null into a printed 0.00 xG. A shot
    // count is counted from the event stream and is known; the xG beside it is
    // Twelve's and may not be, so it is dropped rather than zeroed.
    const rows = Object.entries(obj).map(([k, v]) => ({ k, n: v.n ?? v[0] ?? 0, xg: v.xg ?? v[1] ?? null })).sort((a, b) => b.n - a.n);
    const tot = rows.reduce((a, r) => a + r.n, 0) || 1;
    return `<div class="t-label" style="color:var(--muted);margin-bottom:4px">${esc(who)}</div>` + C.barList(rows.map(r => ({ label: SIT[r.k] || r.k, value: r.xg === null ? `${r.n} sh` : `${r.n} sh · ${fmt(r.xg, 2)} xG`, frac: r.n / tot })), cls);
  }
  async function pageMatch(route) {
    const id = route.id; const Mx = await load(`26-27/matches/${id}.json`);
    const fx = IDX.fixtures.find(f => f.match === id);
    state.fixture = fx.fixture_id;
    const q = route.query;
    const shotsU = Mx.shots.united, shotsO = Mx.shots.opp;
    // One test for the whole page: if the supplier has not priced the shots, the
    // panels that encode xG say so instead of drawing an encoding with no values.
    const xgPending = [...shotsU, ...shotsO].every(s => s.xg === null || s.xg === undefined);
    const tlPending = !(Mx.timeline.united || []).length && !(Mx.timeline.opp || []).length;
    // Three states, and they are three different claims about the same circle.
    //   vendor    Twelve priced every shot        source: twelve
    //   modelled  Twelve priced the side only,    source: modelled — the total is
    //             the split is geometric          theirs, the split is ours
    //   pending   nobody has priced anything      source: counted, no encoding drawn
    const vendorIn = !!Mx.twelve;
    const proxy = Mx.shots.priced || null;
    const xgSrc = xgPending ? 'counted' : (proxy ? 'modelled' : 'twelve');
    const shotBadge = vendorIn ? 'no per-shot xG' : 'Twelve pending';
    const shotWhy = vendorIn
      ? 'the Twelve report gives team totals, not a value per shot'
      : 'until the Twelve report lands';
    const proxyNote = proxy ? ` · ${proxy.note}` : '';
    const cnt = (arr, fn) => arr.filter(fn).length;
    const filters = filterChips('shots', q.shots, [['all', 'All', shotsU.length + shotsO.length], ['open', 'Open play', cnt([...shotsU, ...shotsO], s => s.sit === 'open')], ['setpiece', 'Set piece', cnt([...shotsU, ...shotsO], s => ['corner', 'freekick', 'throwin', 'penalty'].includes(s.sit))], ['fastbreak', 'Fast break', cnt([...shotsU, ...shotsO], s => s.sit === 'fastbreak')]])
      + filterChips('outcome', q.outcome, [['all', 'Any outcome'], ['goal', 'Goals'], ['sot', 'On target'], ['blocked', 'Blocked']]);
    EXPORTS.tape = { head: ['metric', 'united', Mx.meta.opp, 'source'],
      rows: Mx.tape.map(t => [reg(t.key).label, t.united, t.opp, t.pending ? 'pending' : (t.src || reg(t.key).source)]) };
    const tape = Mx.tape.map(t => cmpRow({ key: t.key, united: t.united, opp: t.opp, src: t.src, pending: t.pending, baseline: Mx.baseline[t.key]?.median, base: Mx.baseline[t.key] ? `25/26 ${Mx.baseline[t.key].median}` : '' }));
    const players = Mx.players.map(p => ({ ...p, name: `${p.shirt}  ${p.name} · ${p.pos}`, pass: `${p.passes_cmp}/${p.passes_att}`, sh: `${p.shots}${p.sot ? ` (${p.sot})` : ''}`, _href: href('players', p.player_id) }));
    // The teaser used to hardcode 41.5%, 10 and 31% — Everton's numbers, typed into
    // the view layer, on every match page regardless of who the next opponent was.
    // They come from the scout payload now, so the card is right for whoever it is.
    const scoutFx = IDX.fixtures.find(f => f.scout && f.status !== 'played') || IDX.fixtures.find(f => f.scout);
    let scout = '';
    if (scoutFx) {
      const S2 = await load(`26-27/opponents/${scoutFx.scout}.json`).catch(() => null);
      const keys = (S2 && S2.teaser || []).map(t => `<div class="scout__k"><b>${esc(t.value)}</b><span>${esc(t.label)}</span></div>`).join('');
      const built = S2 ? S2.meta.sample.matches : 0;
      scout = `<a class="scout" href="${href('opponents', scoutFx.scout)}"><span class="t-label">Next: ${esc(scoutFx.opp)} · opposition scout</span>
      ${keys}<span class="scout__go">${built ? `Built from ${built} match${built === 1 ? '' : 'es'} · ` : ''}Open ›</span></a>`;
    }
    const hero = Mx.kpis.map((k, i) => kpi({ key: k.key, value: k.value, note: k.note, n: 1, unit: k.key === 'field_tilt' ? '%' : '' }));
    return {
      lineage: `26/27 › <a href="${href('matches')}">Matches</a> › ${Mx.meta.opp} (${Mx.meta.venue}) ${Mx.meta.score.replace('-', '–')}`,
      rail: [['claim', 'Story & numbers'], ['tape', 'Match tape'], ['timeline', 'Minute by minute'], ['shots', 'Shots'], ['territory', 'Territory & network'], ['players', `Players · ${Mx.players.length}`]],
      body: `${fixtureHeader(fx)}
        <div class="story">${claim({ eyebrow: Mx.story.eyebrow, headline: Mx.story.headline, lead: Mx.story.lead }, { badge: sampleBadge(1) })}${scout}</div>
        <div class="kpis">${hero.join('')}</div>
        ${panel({ id: 'tape', title: `Match tape · United against ${Mx.meta.opp}`, intro: 'Fourteen published figures, both sides. Red grows left from the centre, blue grows right; the tick is the 25/26 median for United where one exists.', body: tape.join(''), n: 1, src: 'mixed', note: 'per-row source on hover: Twelve · WhoScored · counted from the event bundle' })}
        <div class="row row--wide">
          ${panel({ id: 'timeline', title: tlPending ? 'The match, minute by minute · goals' : 'The match, minute by minute', intro: tlPending ? `When the goals went in. The line needs a value per shot to accumulate, and ${shotWhy}${vendorIn ? ` — the full-time totals are on the tape above` : ''}.` : `Expected goals accumulated as each shot was taken. A steep step is a good chance; a long flat run is possession without penetration.${proxy ? ' The step heights are modelled — the full-time totals are Twelve’s, the shape between them is geometric.' : ''}`, body: C.xgRace(Mx.timeline, Mx.meta.opp), n: 1, src: tlPending ? 'counted' : (Mx.timeline.src || 'twelve'), pending: tlPending && shotBadge, mod: !tlPending && Mx.timeline.src === 'modelled', note: Mx.timeline.goals.map(g => `${g.min}′ ${g.who} · ${g.sit}`).join(' · ') })}
          ${panel({ id: 'situations', title: 'Where the chances came from', intro: `United first, then ${Mx.meta.opp}. Bar = share of that side's shots; the label carries the xG${xgPending ? ` — ${shotWhy}, so the counts stand alone` : (proxy ? ', modelled from the side total' : '')}.`, pending: xgPending && shotBadge, mod: !!proxy, body: sitsList(Mx.shots.situations.u, 'United', '') + `<div style="height:10px"></div>` + sitsList(Mx.shots.situations.o, Mx.meta.opp, 'blue'), n: 1, src: proxy ? 'modelled' : 'counted', note: Mx.story.sits_note })}
        </div>
        ${panel({ id: 'shots', title: Mx.story.shots_h2, intro: Mx.story.shots_intro, filters, body: C.shotMap(shotsU, shotsO, { source: q.shots, outcome: q.outcome }), n: 1, src: xgSrc, pending: xgPending && shotBadge, mod: !!proxy, note: `${shotsU.length} United · ${shotsO.length} ${Mx.meta.opp}${xgPending ? ` · positions and outcomes only — ${shotWhy}` : proxyNote} · filters narrow both sides at once and write to the URL` })}
        <div class="row">
          ${panel({ id: 'territory', title: 'Touch density · United', intro: 'Touches across the pitch in twelfths, attacking left → right.', body: C.heatGrid(Mx.heat, 'u'), n: 1, src: 'counted', note: `peak ${Math.max(...Mx.heat.u)} touches per cell` })}
          ${panel({ id: 'network', title: Mx.story.net_title, intro: 'Nodes at each player’s average in-possession position; node size = passes played, link width = passes between the pair.', body: C.network(Mx.network.nodes, Mx.network.links, 6), n: 1, src: 'counted', note: `${Mx.network.links.length} links · min 6 drawn` })}
        </div>
        ${panel({ id: 'players', title: `${Mx.players.length} players, counted`, intro: 'Raw counts from the event stream, not copied from the supplier. Minutes sit beside each number rather than dividing into it. Click a name for the player page.', body: table([{ h: 'Player', key: 'name', k: true }, { h: 'Min', key: 'mins', r: true }, { h: 'Tch', key: 'touches', r: true }, { h: 'Box', key: 'box_touches', r: true, cls: 'tab-hide' }, { h: 'Pass', key: 'pass', r: true }, { h: 'Acc%', key: 'pass_acc', r: true }, { h: 'KP', key: 'key_passes', r: true }, { h: 'F3', key: 'final_third_passes', r: true, cls: 'tab-hide' }, { h: 'Shots', key: 'sh', r: true }, { h: 'G', key: 'goals', r: true }, { h: 'A', key: 'assists', r: true }, { h: 'Def', key: 'def_actions', r: true, cls: 'tab-hide' }, { h: 'Rec', key: 'recoveries', r: true, cls: 'tab-hide' }], players, { id: 'players' }), n: 1, src: 'counted', note: `${Mx.unused.length} unused: ${Mx.unused.join(', ')}` })}`
    };
  }

  async function pageOpponents() {
    const rows = IDX.fixtures.filter(f => f.comp === 'PL').map(f => ({ rd: `MW${f.round}`, opp: f.opp, ven: f.venue === 'H' ? 'Home' : 'Away', tier: (IDX.teams[f.opp] || {}).tier_25_26 || '—', status: f.status === 'played' ? `Played ${f.score.replace('-', '–')}` : (f.scout ? 'Scout ready ›' : 'Not yet scouted'), _href: f.scout ? href('opponents', f.scout) : (f.match ? href('matches', f.match) : null), _cls: f.scout ? 'hot' : (f.status === 'played' ? '' : 'future') }));
    return {
      lineage: '26/27 › Opponents',
      rail: [['list', 'By fixture']],
      body: panel({ id: 'list', title: 'Opponents · by fixture', intro: 'An opponent is reached through a fixture. The scout is built for the next match and stays attached to it afterwards, so "did it hold?" has somewhere to live.', body: table([{ h: 'Round', key: 'rd', cls: 'mono' }, { h: 'Club', key: 'opp', k: true }, { h: 'Venue', key: 'ven' }, { h: '25/26 tier', key: 'tier', f: r => `<span class="stripe ${r.tier}"></span>${esc(IDX.tier_names[r.tier] || r.tier)}` }, { h: 'Status', key: 'status', f: r => r.status.startsWith('Scout') ? `<span style="color:var(--opponent);font-weight:600">${r.status}</span>` : esc(r.status) }], rows), src: 'counted', note: 'tiers from where each club finished in 25/26' })
    };
  }

  async function pageOpponent(route) {
    const O = await load(`26-27/opponents/${route.id}.json`);
    const fx = IDX.fixtures.find(f => f.scout === route.id);
    state.fixture = fx.fixture_id;
    const kpis = O.kpis.map(k => kpi({ label: k.label, value: k.value, unit: k.unit, note: k.note, src: k.src, n: 2 }));
    const P = O.panels || {};
    const D = { intro: '', note: '' };
    ['block','losses','channels','shots','network'].forEach(k => { P[k] = P[k] || D; });
    const bh = O.block_height.blocks.map((b, i) => cmpRow({ label: b === '60–75' ? '60–75′ · the window' : b + '′', united: O.block_height.v_palace[i], opp: O.block_height.v_bournemouth[i], d: 1, grey: true, hot: b === (P.block.hot_block || '') }));
    const losses = C.barList(O.losses.zones.map(([z, n]) => ({ label: z, value: `${n} · ${(n / O.losses.total * 100).toFixed(1)}%`, frac: n / O.losses.zones[0][1] })), 'blue');
    const chans = O.channels.map(c => cmpRow({ label: c.ch, united: c.entries, opp: c.shots, d: 0, grey: true }));
    const shots = O.shots.map(s => ({ x: s.x, y: s.y, xg: s.q, t: s.g ? 'goal' : (s.r === 'SavedShot' ? 'sot' : (s.r === 'BlockedShot' ? 'blocked' : 'off')), min: s.m, who: s.p, sit: s.tags.includes('RegularPlay') ? 'open' : 'set piece' }));
    const subj = shots.filter((s, i) => O.shots[i].t === O.meta.subject), foe = shots.filter((s, i) => O.shots[i].t !== O.meta.subject);
    const net = C.network(O.network.nodes.map(n => ({ nm: n.nm, x: n.x, y: n.y, n: n.inv })), O.network.links.map(l => { const a = O.network.nodes.find(n => n.nm === l.a), b = O.network.nodes.find(n => n.nm === l.b); return a && b ? { x1: a.x, y1: a.y, x2: b.x, y2: b.y, n: l.n, a: l.a, b: l.b } : null; }).filter(Boolean), 5, 'opp');
    let calls = null; if (state.staff) { try { calls = (await load(`private/${route.id}-staff.json`)).calls; } catch (e) { calls = null; } }
    const staff = staffCalls(O, calls);
    return {
      lineage: `26/27 › <a href="${href('matches')}">MW${fx.round} ${esc(fx.opp)} (${fx.venue})</a> › Scout`,
      rail: [['claim', 'What they do'], ...(calls ? [['calls', 'Coaching calls · staff']] : []), ['block', 'Where they defend'], ['losses', 'Where they lose it'], ['channels', 'Entries & shots'], ['shots', 'Their shots'], ['network', 'Their network'], ['after', 'After the match']],
      body: `${fixtureHeader(fx, { opp: true, back: href('matches'), backLabel: 'matches' })}
        <div class="built"><span class="t-label">Built from</span>${O.meta.built_from.map(b => `<span class="src">${esc(b.label)} · ${esc(b.date)} · WS ${esc(b.ws)}</span>`).join('')}${O.meta.vendor_report ? `<span class="src">${esc(O.meta.vendor_report.label)} · ${esc(O.meta.vendor_report.date)}</span>` : ''}</div>
        ${claim({ eyebrow: `MW${fx.round} · pre-match scout · ${fx.opp} (${fx.venue})`, headline: O.claim.headline, lead: O.claim.lead }, { opp: true, badge: badge('sample', `built from ${O.meta.sample.matches + 1} matches`) })}
        ${staff}
        <div class="kpis">${kpis.join('')}</div>
        ${panel({ id: 'block', title: P.block.title || 'Where they defend', intro: P.block.intro, body: bh.join(''), n: 2, src: 'counted', note: P.block.note })}
        <div class="row">
          ${panel({ id: 'losses', title: `Where they lose it · ${O.losses.total} losses in two matches`, intro: P.losses.intro, body: losses, n: 2, src: 'counted', note: P.losses.note })}
          ${panel({ id: 'channels', title: 'Entries and shots by channel', intro: P.channels.intro, body: chans.join(''), n: 2, src: 'counted', note: P.channels.note })}
        </div>
        <div class="row">
          ${panel({ id: 'shots', title: `Their ${subj.length} shots, and the ${foe.length} against them · v Bournemouth`, intro: P.shots.intro, body: C.shotMap(subj, foe, null, { mirror: false, uClass: 'o', oClass: 'g' }), n: 1, src: 'modelled', note: P.shots.note })}
          ${panel({ id: 'network', title: 'Their network · v Bournemouth', intro: P.network.intro, body: net, n: 1, src: 'inferred', note: `${O.network.nodes.length} players · ${O.network.links.length} pairs` })}
        </div>
        <div class="after" id="after"><span class="t-label">After the match · did it hold?</span><span class="t-intro">Populates from the MW${fx.round} match payload once the fixture is played: each scout figure above against what actually happened, with the delta. Until then this strip is the only empty thing on the page — by design.</span><a href="${href('matches')}#compare=scout">Opens on the Match page with #compare=scout ›</a></div>`
    };
  }
  function staffCalls(O, calls) {
    if (!calls) return '';
    return `<section class="panel" id="calls" style="border:2px solid var(--united)"><div class="panel__head"><div><h2 class="panel__title" style="color:var(--united)">Coaching calls · ${calls.length}, each with its evidence</h2><p class="panel__intro">What we would do about the findings on this page. Every call carries the figure it rests on and the denominator. This panel exists only in the private export.</p></div>${badge('staff', 'Private')}</div>
      <div class="panel__body">${calls.map((c, i) => `<div style="display:grid;grid-template-columns:32px 1fr;gap:16px;padding:12px 0;border-top:1px solid var(--line-2)"><span class="ph__shirt" style="width:32px;height:32px;font-size:14px">${i + 1}</span><div><div class="t-h3">${esc(c.title)}</div><p class="t-intro" style="margin:4px 0">${esc(c.body)}</p><span class="pill">Evidence</span> <span class="t-cap" style="color:var(--ink)">${esc(c.evidence)}</span> <span class="t-cap">· ${esc(c.src)}</span></div></div>`).join('')}</div>
      <div class="panel__foot">${sampleBadge(2, 'league match')}<span>calls are authored in notes.yaml with cites and asserts, so a revised feed that breaks one fails the build</span></div></section>`;
  }
  async function pageSquad(route) {
    const S = await load('26-27/squad.json');
    const n = S.meta.sample.matches, avail = S.meta.sample.minutes_available;
    const k = S.kpis;
    const kpis = [kpi({ label: 'Matches played', value: k.matches, note: `${k.team_goals} goals scored · 2 different scorers` }), kpi({ label: 'Goals attributed', value: k.attributed, note: `of ${k.team_goals} · ${k.team_goals - k.attributed} own goal carries no United scorer` }), kpi({ label: 'Assists', value: k.assists, note: '3 players have an involvement' }), kpi({ label: 'Players used', value: k.players_used, note: `an ever-present has ${avail} minutes available` }), kpi({ label: `Over the ${S.meta.floor}′ floor`, value: k.over_floor, note: `of ${k.players_used} · per-90 unlocks at ${S.meta.floor}′ · ~5 matches`, floor: S.meta.floor })];
    const leader = S.season_to_date[0].ga || 1;
    const strip = S.season_to_date.slice(0, route.query.all ? 99 : 10).map((p, i) => ({ rk: p.ga ? String(i + 1) : '—', name: `${p.name} · ${p.pos}`, apps: `${p.apps} · ${p.starts} · ${p.mins}′`, bars: `<div class="bar"><i style="width:${(p.mins / avail * 100).toFixed(1)}%"></i></div>${p.ga ? `<div class="bar amber" style="margin-top:3px"><i style="width:${(p.ga / leader * 100).toFixed(1)}%"></i></div>` : ''}`, g: p.g, a: p.a, ga: p.ga, p90: fmt(p.per90_running, 2), _href: href('players', p.player_id), _tip: (p.involvements || []).map(r => `${r.g} G ${r.a} A v ${r.opp} (${r.ven}), MW${r.mw}`).join(' · ') }));
    const metric = route.query.metric || 'touches';
    const metricChips = filterChips('metric', metric, [['touches', 'Touches'], ['passes', 'Passes'], ['key', 'Key passes'], ['shots', 'Shots'], ['tackles', 'Tackles won'], ['aerials', 'Aerials won'], ['drib', 'Dribbles']]);
    const ranked = S.per90_baseline.filter(p => p.over_floor && p[metric] !== null).sort((a, b) => b[metric] - a[metric]);
    const top = ranked[0]?.[metric] || 1;
    const per90 = C.barList([...ranked.slice(0, 10).map(p => ({ label: `${p.name} · ${p.pos}`, sub: `${num(p.mins)}′`, value: fmt(p[metric], 1), frac: p[metric] / top })), ...S.per90_baseline.filter(p => !p.over_floor).slice(0, 2).map(p => ({ label: `${p.name} · ${p.pos}`, sub: `${num(p.mins)}′ · under the floor`, value: '—', frac: 0.3, muted: true }))]);
    const ga = S.goals_assists_25_26.rows.slice(0, 8).map(r => ({ name: `${r.nm} · ${r.pos}`, g: r.g, a: r.a, ga: r.ga, mins: num(r.mins), p90: fmt(r.per90, 2) }));
    // 38 cells a row across ten rows is 380 tipped elements. Making each one a tab
    // stop would be a worse keyboard experience than none, so the row carries one
    // summary a screen reader can read and the cells keep hover for the eye.
    const CELL = { S: 'started', N: 'came on', B: 'unused sub', O: 'not in squad' };
    const availRows = [...S.availability.rows].sort((a, b) => b.mins - a.mins).slice(0, route.query.all ? 99 : 10).map(r => {
      const tally = Object.entries(CELL).map(([k, w]) => [r.cells.filter(c => c === k).length, w]).filter(([n]) => n).map(([n, w]) => `${n} ${w}`).join(', ');
      return `<div class="avail__row"><span>${esc(r.nm.split(' ').at(-1))}</span><div class="avail__cells" role="img" aria-label="${esc(r.nm)}: ${esc(tally)} across ${r.cells.length} matchweeks">${r.cells.map((c, i) => `<i class="${c}" aria-hidden="true" data-tip="MW${i + 1} · ${CELL[c]}"></i>`).join('')}</div></div>`;
    }).join('');
    return {
      lineage: '26/27 › Squad',
      rail: [['claim', 'Season to date'], ['per90', 'Per 90 · 25/26 baseline'], ['ga', 'Goals & assists'], ['avail', 'Availability']],
      body: `${claim(S.claim, { badge: sampleBadge(n) })}
        <div class="kpis">${kpis.join('')}</div>
        ${panel({ id: 'strip', title: 'Season to date, 26/27 — contributions', intro: `One row per player who has been on the pitch, ranked by goal involvements then goals then minutes, with no floor. Red bar = minutes as a share of what was available (${avail}′ today, 3,420′ in May). Amber bar = involvements as a share of the leader’s. Hover a row for the matches they came from.`, body: table([{ h: '#', key: 'rk', cls: 'mono' }, { h: 'Player', key: 'name', k: true }, { h: 'Apps · starts · min', key: 'apps', m: true, cls: 'tab-hide' }, { h: 'Minutes · involvements', key: 'bars', f: r => `<div data-tip="${esc(r._tip)}">${r.bars}</div>` }, { h: 'G', key: 'g', r: true }, { h: 'A', key: 'a', r: true }, { h: 'G+A', key: 'ga', r: true, k: true }, { h: 'Per 90', key: 'p90', r: true }], strip, { more: route.query.all ? '' : `… ${S.season_to_date.length - 10} more · <button data-q="all=1">show all</button> · running per 90 = involvements ÷ minutes × 90, not a projection` }), n, src: 'counted', note: 'own goals stay in the team total' })}
        <div class="row">
          ${panel({ id: 'per90', title: 'Per 90, season 25/26 · baseline', intro: `Rates from the 51-column season file, ranked among the ${S.per90_baseline.filter(p => p.over_floor).length} of ${S.per90_baseline.length} players past ${S.meta.floor} minutes. Below the floor a player is listed grey and unranked.`, filters: metricChips, body: per90, n: 38, src: 'counted', note: `floor ${S.meta.floor}′ · rate = total ÷ minutes × 90` })}
          ${panel({ id: 'ga', title: 'Who scored them, and who made them · 25/26', intro: `Goals and assists from the 760 player-match rows. ${S.goals_assists_25_26.attributed} attributed of ${S.goals_assists_25_26.master} in the master; three own goals.`, body: table([{ h: 'Player', key: 'name', k: true }, { h: 'G', key: 'g', r: true }, { h: 'A', key: 'a', r: true }, { h: 'G+A', key: 'ga', r: true, k: true }, { h: 'Min', key: 'mins', r: true, m: true }, { h: 'Per 90', key: 'p90', r: true }], ga, { more: `… ${S.goals_assists_25_26.rows.length - 8} more` }), n: 38, src: 'counted', note: `${S.goals_assists_25_26.assists} assists` })}
        </div>
        ${panel({ id: 'avail', title: `${S.availability.gw_count} weeks, ${S.availability.rows.length} players · 25/26 availability`, intro: 'One cell per player per matchweek. Ten most-used shown.', body: `<div class="legend"><span><i style="background:var(--ink)"></i>Started</span><span><i style="background:var(--baseline)"></i>Came on</span><span><i style="background:var(--grid)"></i>Unused sub</span><span><i style="background:var(--tint);border:1px solid var(--line)"></i>Not in squad</span></div><div class="avail" style="margin-top:8px">${availRows}</div>${route.query.all ? '' : `<div class="more">… ${S.availability.rows.length - 10} more players · <button data-q="all=1">show all</button></div>`}`, n: 38, src: 'counted', note: 'from 760 player-match rows and 38 squad lists' })}`
    };
  }

  async function pagePlayer(route) {
    const P = await load(`26-27/players/${route.id}.json`);
    const s26 = P.seasons['26-27'] || {}, s25 = P.seasons['25-26'] || null;
    const log = P.match_log;
    const mins = log.reduce((a, r) => a + (r.minutes || 0), 0), ga = log.reduce((a, r) => a + (r.goals || 0) + (r.assists || 0), 0);
    const cur = route.query.m || log.at(-1)?.match;
    const plot = P.plots[cur]; const curRow = log.find(r => r.match === cur);
    const chips = filterChips('m', cur, log.map(r => [r.match, `MW${r.round} ${r.opp.split(' ')[0]}`]));
    const running = k => mins ? (log.reduce((a, r) => a + (r[k] || 0), 0) / mins * 90) : null;
    const svs = s25 ? [['Touches', running('touches'), s25.per90.touches], ['Passes attempted', running('passes_attempted'), s25.per90.passes], ['Key passes', running('key_passes'), s25.per90.key], ['Shots', running('shots'), s25.per90.shots], ['Tackles', running('tackles'), s25.per90.tackles], ['Goals + assists', mins ? ga / mins * 90 : null, s25.ga90 ?? (s25.ga && s25.mins ? s25.ga / s25.mins * 90 : null)]].map(([l, a, b]) => cmpRow({ label: l, united: a, opp: b, d: 2, grey: true, base: '25/26' })) : [];
    const logRows = log.slice().reverse().map(r => ({ m: `MW${r.round} · ${r.opp} (${r.venue}) · ${r.result} ${r.score.replace('-', '–')}`, min: r.minutes, tch: r.touches, box: r.box_touches, pass: `${r.passes_completed}/${r.passes_attempted}`, acc: fmt(r.pass_accuracy_pct, 1), kp: r.key_passes, f3: r.final_third_passes, sh: `${r.shots}${r.shots_on_target ? ` (${r.shots_on_target})` : ''}`, g: r.goals, a: r.assists, def: r.def_actions, rec: r.recoveries, _href: href('matches', r.match), _cls: r.match === cur ? 'hot' : '' }));
    return {
      lineage: `26/27 › <a href="${href('squad')}">Squad</a> › ${esc(P.meta.name)}`,
      rail: [['claim', 'This season'], ['log', 'Match log'], ['touch', 'Touch map'], ['svs', 'Season against season'], ...(s25 ? [['rates', 'Success rates']] : [])],
      body: `<div class="ph"><span class="fx__rule"></span><span class="ph__shirt">${P.meta.shirt}</span><div class="fx__text"><div class="fx__eye">${esc(P.meta.group)} · ${esc(P.meta.pos)} · player_id ${esc(P.meta.player_id)}</div><h1 class="ph__name">${esc(P.meta.name)}</h1><div class="fx__det">26/27: ${log.length} apps · ${log.filter(r => r.started).length} starts · ${mins}′${s25 ? ` · 25/26: ${s25.apps} apps · ${num(s25.mins)}′ · rating ${s25.rating_wtd} · ${s25.mom} MoM` : ''}</div></div>${sampleBadge(log.length)}</div>
        <div class="kpis">${kpi({ label: 'Minutes', value: mins, unit: '′', note: `of ${log.length * 90} available · ${log.filter(r => r.started).length} starts`, src: 'counted' })}${kpi({ label: 'Goals + assists', value: ga, note: `${log.reduce((a, r) => a + r.goals, 0)} G · ${log.reduce((a, r) => a + r.assists, 0)} A`, src: 'counted' })}${kpi({ label: 'Involvements per 90', value: fmt(mins ? ga / mins * 90 : null, 2), note: `running · ${s25 ? `25/26 was ${fmt(s25.ga90 ?? (s25.ga / s25.mins * 90), 2)} · ` : ''}floor at 450′`, floor: mins < 450 ? 450 : null, src: 'counted' })}${kpi({ label: 'Touches', value: log.reduce((a, r) => a + (r.touches || 0), 0), note: log.map(r => `${r.touches} v ${r.opp.split(' ')[0]}`).join(' · '), src: 'counted' })}${s26.rating_wtd ? kpi({ label: 'Rating', value: fmt(s26.rating_wtd, 2), note: `WhoScored, published, minutes-weighted${s25 ? ` · 25/26 ${s25.rating_wtd}` : ''}`, src: 'whoscored' }) : ''}</div>
        ${panel({ id: 'log', title: 'Match log', intro: 'One row per match from the 53-column player-match log, counted from the event stream. Click a row to open that match.', body: table([{ h: 'Match', key: 'm', k: true }, { h: 'Min', key: 'min', r: true }, { h: 'Tch', key: 'tch', r: true }, { h: 'Box', key: 'box', r: true, cls: 'tab-hide' }, { h: 'Pass', key: 'pass', r: true }, { h: 'Acc%', key: 'acc', r: true }, { h: 'KP', key: 'kp', r: true }, { h: 'F3', key: 'f3', r: true, cls: 'tab-hide' }, { h: 'Shots', key: 'sh', r: true }, { h: 'G', key: 'g', r: true }, { h: 'A', key: 'a', r: true }, { h: 'Def', key: 'def', r: true, cls: 'tab-hide' }, { h: 'Rec', key: 'rec', r: true, cls: 'tab-hide' }], logRows, { id: 'log' }), n: log.length, src: 'counted', note: 'pass column is completed / attempted' })}
        <div class="row">
          ${panel({ id: 'touch', title: `Touch map · ${curRow ? `MW${curRow.round} v ${curRow.opp}` : ''}`, intro: 'Every touch, with the player’s shots on top sized by expected goals; goals ringed and timed.', filters: chips, body: plot ? C.touchPlot(plot.t, plot.s) : '<p class="t-cap">No touch data for this match.</p>', n: 1, src: 'counted', note: plot ? `${plot.t.length} touches · ${plot.s.length} shots · xG from Twelve` : '' })}
          ${s25 ? panel({ id: 'svs', title: 'Season against season · per 90', intro: '26/27 running rate (red) against the finished 25/26 rate (grey). The delta is arithmetic, not evidence, until 450′.', body: svs.join(''), n: log.length, src: 'counted', note: `25/26 over ${num(s25.mins)}′ · 26/27 over ${mins}′ · running, not projected` }) : ''}
        </div>
        ${s25 ? panel({ id: 'rates', title: 'Success rates · 25/26', intro: 'Completed over attempted, attempts printed beside the rate so a 100% on two attempts cannot pass for a habit.', body: table([{ h: 'Measure', key: 'm', k: true }, { h: '25/26', key: 'v', r: true }, { h: 'Attempts', key: 'n', r: true, m: true }], [['Pass completion', s25.pct.pass, s25.attempts.pass], ['Tackles won', s25.pct.tackle, s25.attempts.tackle], ['Take-ons completed', s25.pct.drib, s25.attempts.drib], ['Aerials won', s25.pct.aerial, s25.attempts.aerial]].map(([m, v, n]) => ({ m, v: v == null ? '—' : `${fmt(v, 1)}%`, n: num(n) }))), n: 38, src: 'counted' }) : ''}`
    };
  }

  async function pageLeague() {
    const L = await load('league/25-26.json');
    const played = IDX.fixtures.filter(f => f.status === 'played').length;
    const tier = t => `<span class="stripe ${t}"></span>`;
    const tbl = L.table.map(r => ({ pos: r.pos, club: r.team.replace('Manchester United', 'Man United').replace('Manchester City', 'Man City').replace('Nottingham Forest', "Nott'm Forest").replace('Tottenham Hotspur', 'Tottenham').replace('Wolverhampton Wanderers', 'Wolves').replace('West Ham United', 'West Ham').replace('Newcastle United', 'Newcastle'), p: r.p, w: r.w, d: r.d, l: r.l, gf: r.gf, ga: r.ga, gd: r.gd > 0 ? `+${r.gd}` : r.gd, pts: r.pts, h: r.hpts, a: r.apts, cs: r.cs, tier: r.tier, _cls: r.mu ? 'hot' : '' }));
    const ranks = '<div class="ranks">' + L.ranks.map(r => `<div class="cmp"><span><span class="cmp__lab">${esc(r.lab)}</span><br><span class="t-cap">best ${r.best} · ${esc(r.bestTeam)} · med ${r.med}</span></span><span class="slots">${Array.from({ length: 20 }, (_, i) => `<i class="${i + 1 === r.rank ? 'on' + (r.rank >= 10 ? ' warn' : '') : ''}"></i>`).join('')}</span><span class="cmp__o">${r.v}</span><span class="pill ${r.rank >= 10 ? 'warn' : ''}">${r.rank}${['st', 'nd', 'rd'][r.rank - 1] || 'th'}</span></div>`).join('') + '</div>';
    const tiers = ['top', 'mid', 'bot'].map(t => { const r = L.tier_record[t]; return `<div class="tile" style="border-color:${t === 'top' ? 'var(--opponent)' : t === 'mid' ? 'var(--baseline)' : 'var(--line)'}"><span class="t-code">${esc(IDX.tier_names[t])}</span><b>${fmt(r.ppg, 2)}<small>ppg</small></b><span>W${r.w} D${r.d} L${r.l} · ${r.gf}–${r.ga}</span></div>`; }).join('');
    const tm = L.tier_metrics.map(m => `<tr><td class="k">${esc(m.lab)}</td><td class="r">${m.top}</td><td class="r">${m.mid}</td><td class="r">${m.bot}</td><td class="r m">${m.home} / ${m.away}</td><td class="r" style="color:${m.r2 > 0.2 ? 'var(--caveat)' : 'var(--muted)'};font-weight:${m.r2 > 0.2 ? 600 : 400}">${Math.round(m.r2 * 100)}%</td></tr>`).join('');
    const drop = L.dropped.rows.slice(0, 8).map(r => ({ m: `MW${r.gw} · ${r.opp} (${r.ven})`, sc: `${r.res} ${r.sc}`, res: r.res, lost: r.lost, pos: `${r.pos}th`, ppg: fmt(r.restPPG, 2) }));
    const bw = L.best_wins.map(r => ({ m: `MW${r.gw} · ${r.opp} (${r.ven})`, sc: `W ${r.sc}`, pos: `${r.pos}${['st', 'nd', 'rd'][r.pos - 1] || 'th'}`, ppg: fmt(r.restPPG, 2), rec: r.restRec }));
    return {
      lineage: '26/27 › League · showing 25/26 final',
      rail: [['claim', 'Claim & ranks'], ['table', 'Table · rebuilt from 380'], ['ranks', 'Rank of twenty'], ['tiers', 'Good against whom'], ['dropped', 'Dropped points'], ['best', 'Best afternoons']],
      body: `<div class="notice"><span class="t-label">26/27 league view · locked</span><span>Unlocks at round ${L.meta.locks.league} · ${played} played. A table rebuilt from ${played * 10} results says nothing yet, so this page shows the finished 25/26 season until then.</span></div>
        ${claim(L.claim, { badge: badge('verified', `validated ${L.meta.validated.matched + 2} / ${L.meta.validated.of}`) })}
        <div class="kpis">${kpi({ label: 'Finished', value: '3rd', note: '71 points · 20W 11D 7L · Arsenal 85', src: 'derived' })}${kpi({ label: 'Goals scored', value: 69, note: '3rd of 20 · Man City 77 · median 52', src: 'derived' })}${kpi({ label: 'Goals conceded', value: 50, note: '6th of 20 · Arsenal 27 · median 51', src: 'derived' })}${kpi({ label: 'Clean sheets', value: 8, note: '15th of 20 · Arsenal 19 · median 9', src: 'derived' })}${kpi({ label: 'Points v top six', value: 17, note: '4th of 20 · Villa 19 · median 9', src: 'derived' })}</div>
        <div class="row row--wide">
          ${panel({ id: 'table', title: 'Premier League 2025/26 · computed from 380 results', intro: 'Every column is recomputed from the results file rather than copied. Tier stripes: top six, 7th–13th, 14th or lower.', body: table([{ h: '#', key: 'pos', f: r => `${tier(r.tier)}${r.pos}` }, { h: 'Club', key: 'club', k: true }, { h: 'P', key: 'p', r: true, cls: 'tab-hide' }, { h: 'W', key: 'w', r: true }, { h: 'D', key: 'd', r: true }, { h: 'L', key: 'l', r: true }, { h: 'GF', key: 'gf', r: true }, { h: 'GA', key: 'ga', r: true }, { h: 'GD', key: 'gd', r: true }, { h: 'Pts', key: 'pts', r: true, k: true }, { h: 'H', key: 'h', r: true, m: true, cls: 'tab-hide' }, { h: 'A', key: 'a', r: true, m: true, cls: 'tab-hide' }, { h: 'CS', key: 'cs', r: true, cls: 'tab-hide', f: r => r._cls ? `<span style="color:var(--united);font-weight:600">${r.cs}</span>` : r.cs }], tbl, { id: 'table' }) + `<div class="legend" style="margin-top:8px"><span>${tier('top')}Top six</span><span>${tier('mid')}7th–13th</span><span>${tier('bot')}14th or lower</span></div>`, validated: 'PASS · 20 of 20 clubs', src: 'derived', note: '380 results · Wikipedia rejected as a source (28-game snapshot)' })}
          ${panel({ id: 'ranks', title: 'United’s rank of twenty', intro: 'One slot per club on each measure, United’s slot lit. Third in nearly everything is the pattern; clean sheets and wins by three or more break it.', body: ranks, src: 'derived', note: 'rank 1 = best in the direction that matters' })}
        </div>
        <div class="row">
          ${panel({ id: 'tiers', title: 'Good against whom · United by opponent tier', intro: 'Opponents tiered by where they finished. The last column is the share of each metric’s variation across 38 matches explained by opponent and venue alone.', body: `<div class="tiles" style="margin-bottom:12px">${tiers}</div><div class="wide"><table><thead><tr><th>Metric</th><th class="r">Top six</th><th class="r">7–13</th><th class="r">14+</th><th class="r">H / A</th><th class="r">Fixture</th></tr></thead><tbody>${tm}</tbody></table></div>`, n: 38, src: 'derived', note: 'context.json tiers · actions.json opp_share' })}
          ${panel({ id: 'dropped', title: `Where the ${L.dropped.total} dropped points went`, intro: `${L.dropped.by_tier.top} to the top six, ${L.dropped.by_tier.mid} to the middle, ${L.dropped.by_tier.bot} to the bottom seven. The cheapest results: what the rest of the league took from the same opponent, per game.`, body: table([{ h: 'Match', key: 'm', k: true }, { h: 'Result', key: 'sc', r: true, f: r => `<span class="res-${r.res}">${esc(r.sc)}</span>` }, { h: 'Lost', key: 'lost', r: true }, { h: 'Opp pos', key: 'pos', r: true, m: true }, { h: 'Rest PPG', key: 'ppg', r: true, k: true }], drop, { more: `… ${L.dropped.rows.length - 8} more · ${L.dropped.cheap_count} results v bottom-seven clubs cost ${L.dropped.cheap_pts} points` }), n: 38, src: 'derived' })}
        </div>
        ${panel({ id: 'best', title: 'The best afternoons, once you allow for the fixture', intro: 'Wins against the sides the rest of the league could not beat.', body: table([{ h: 'Match', key: 'm', k: true }, { h: 'Result', key: 'sc', r: true, f: r => `<span class="res-W">${esc(r.sc)}</span>` }, { h: 'Opp finished', key: 'pos', r: true, m: true }, { h: 'Rest PPG', key: 'ppg', r: true }, { h: 'Rest record', key: 'rec', r: true, m: true }], bw), n: 38, src: 'derived' })}`
    };
  }

  // ------------------------------------------------------------------ render
  const PAGES = { season: pageSeason, matches: pageMatches, opponents: pageOpponents, squad: pageSquad, players: pagePlayer, league: pageLeague };
  async function render() {
    const route = parse();
    state.season = route.season;
    state.comp = route.query.comp || 'PL';
    state.baseline = route.query.baseline !== '0';
    state.staff = !!window.__STAFF__;
    const app = document.getElementById('app');
    let view;
    try {
      if (route.page === 'matches' && route.id) view = await pageMatch(route);
      else if (route.page === 'opponents' && route.id) view = await pageOpponent(route);
      else view = await (PAGES[route.page] || pageSeason)(route);
    } catch (e) {
      view = { lineage: '', rail: [], body: `<section class="panel"><div class="panel__body"><b>Could not load this page.</b><p class="t-cap">${esc(e.message)} · the payload may not have been built yet.</p></div></section>` };
      console.error(e);
    }
    // innerHTML replaces the whole page, so whatever had focus is gone. Scroll was
    // already preserved through ?keep=1; this preserves the user's place in the tab
    // order too, by finding the element that answers to the same data attributes.
    const was = document.activeElement;
    const sig = was && was.dataset && (was.dataset.filter || was.dataset.act || was.dataset.q)
      ? { f: was.dataset.filter, a: was.dataset.act, q: was.dataset.q, v: was.dataset.v } : null;
    app.innerHTML = `${contextBar(route)}${nav(route, view.lineage)}<div class="page">${rail(view.rail)}<main class="content">${view.body}</main></div><div class="tip" id="tip" role="tooltip"></div><div class="sr" id="announce" role="status" aria-live="polite"></div>`;
    const title = `MUFC · ${view.lineage.replace(/<[^>]+>/g, '')}`;
    document.title = title;
    if (sig) {
      const sel = sig.f ? `[data-filter="${sig.f}"][data-v="${sig.v}"]`
        : sig.a ? `[data-act="${sig.a}"]${sig.v ? `[data-v="${sig.v}"]` : ''}`
        : `[data-q="${sig.q}"]`;
      document.querySelector(sel)?.focus({ preventScroll: true });
    }
    // A hash router changes the page without a navigation, so a screen reader is
    // told nothing. document.title updating is not announced on its own.
    const say = document.getElementById('announce');
    if (say) setTimeout(() => { say.textContent = title.replace('MUFC · ', '') + ' — loaded'; }, 120);
    if (!route.query.keep) window.scrollTo(0, 0);
    watchRail();
  }
  function watchRail() {
    const links = [...document.querySelectorAll('.rail a')]; if (!links.length) return;
    const obs = new IntersectionObserver(entries => { entries.forEach(en => { if (en.isIntersecting) { links.forEach(l => l.classList.toggle('on', l.dataset.rail === en.target.id)); } }); }, { rootMargin: '-120px 0px -70% 0px' });
    links.forEach(l => { const t = document.getElementById(l.dataset.rail); if (t) obs.observe(t); });
  }

  // ------------------------------------------------------------------ events
  document.addEventListener('click', e => {
    const chip = e.target.closest('[data-act]');
    if (chip) { const a = chip.dataset.act;
      // The README's contract is "the URL is the state ... so any view can be sent to
      // someone". Competition and baseline were changing state and re-rendering
      // without touching the hash, so a shared link carried the recipient's defaults
      // and not the sender's view. The season chip did write the hash but rebuilt it
      // from scratch, discarding any query string with it.
      if (a === 'season') { state.season = chip.dataset.v; const r = parse();
        const page = r.page === 'league' ? 'season' : r.page;
        location.hash = `/${state.season}/${page}${r.id ? '/' + r.id : ''}` + (Object.keys(r.query).length ? '?' + new URLSearchParams(r.query) : ''); return; }
      if (a === 'comp') { setQuery({ comp: chip.dataset.v === 'PL' ? null : chip.dataset.v, keep: 1 }); return; }
      if (a === 'baseline') { setQuery({ baseline: state.baseline ? '0' : null, keep: 1 }); return; }
      if (a === 'fixture') { const f = IDX.fixtures.find(x => x.fixture_id === chip.dataset.v); if (f?.match) go('matches', f.match); else if (f?.scout) go('opponents', f.scout); else go('matches'); return; } }
    const f = e.target.closest('[data-filter]'); if (f) { setQuery({ [f.dataset.filter]: f.dataset.v, keep: 1 }); return; }
    const q = e.target.closest('[data-q]'); if (q) { const [k, v] = q.dataset.q.split('='); setQuery({ [k]: v, keep: 1 }); return; }
    const row = e.target.closest('tr[data-href]'); if (row && !e.target.closest('a,button')) { location.hash = row.dataset.href.slice(1); return; }
    // Tap to reveal, for the touch users who have no hover at all. Only on tipped
    // elements that do not already do something when tapped, so this can never
    // swallow a navigation or a filter.
    const tapped = e.target.closest('[data-tip]');
    if (tapped && !tapped.closest('a,button,tr[data-href],[data-act],[data-filter],[data-q]')) {
      // A focusable element already got its tip from focusin when the tap focused
      // it. Toggling here would close it again on the same tap.
      if (tapped.matches('[tabindex]')) return;
      if (pinned === tapped) hideTip(); else { pinned = tapped; showTip(tapped, true); }
      return;
    }
    if (pinned && !pinned.contains(e.target)) hideTip();
    const ex = e.target.closest('[data-export]'); if (ex) { exportPanel(ex.closest('.panel')); return; }
    const rl = e.target.closest('.rail a'); if (rl) { e.preventDefault(); document.getElementById(rl.dataset.rail)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });
  // ---------------------------------------------------------------- provenance
  // "Hover any number for its source" was the whole promise of this dashboard and
  // it was bound to mouseover alone: no keyboard route, no touch route, and nothing
  // for a screen reader. Four channels now carry the same string.
  //   1. hover        — unchanged, follows the pointer
  //   2. focus        — the same tip, anchored to the element
  //   3. tap          — same, on any tipped element that is not itself a link
  //   4. screen reader— srSource() writes the text into the element as visually
  //                     hidden copy, so it is read without any of the above
  // Escape closes it, and it closes on scroll so it cannot be left stranded.
  const tip = () => document.getElementById('tip');
  let pinned = null;
  function showTip(t, anchor) {
    const el = tip(); if (!t || !el) return;
    el.innerHTML = `<b>Source</b>${esc(t.dataset.tip)}`;
    el.classList.add('show');
    if (anchor) {
      const r = t.getBoundingClientRect();
      el.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 300)) + 'px';
      el.style.top = (r.bottom + 8) + 'px';
    }
  }
  function hideTip() { tip()?.classList.remove('show'); pinned = null; }
  document.addEventListener('mouseover', e => { const t = e.target.closest('[data-tip]'); if (t && !pinned) showTip(t, false); });
  document.addEventListener('mousemove', e => { const el = tip(); if (!el || pinned || !el.classList.contains('show')) return; el.style.left = Math.min(e.clientX + 14, window.innerWidth - 300) + 'px'; el.style.top = (e.clientY + 16) + 'px'; });
  document.addEventListener('mouseout', e => { if (!pinned && e.target.closest && e.target.closest('[data-tip]')) hideTip(); });
  document.addEventListener('focusin', e => { const t = e.target.closest && e.target.closest('[data-tip]'); if (t) { pinned = t; showTip(t, true); } });
  document.addEventListener('focusout', e => { if (pinned && e.target.closest && e.target.closest('[data-tip]') === pinned) hideTip(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hideTip(); });
  // Tabbing to an element below the fold scrolls the page to reach it, so dismissing
  // on scroll dismissed the tip on the very scroll that focus had just caused. Follow
  // the element instead, and let go only once it has left the viewport.
  window.addEventListener('scroll', () => {
    if (!pinned) return;
    const r = pinned.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) hideTip(); else showTip(pinned, true);
  }, { passive: true });
  // Export used to scrape textContent, so it wrote rounded display strings and
  // inherited whatever the current breakpoint had hidden — below 900px the delta
  // and baseline columns are display:none, which made a phone export a different
  // file from a desktop one. It now writes the rows the panel was built from,
  // and says so in the header when it has to fall back to the rendered table.
  function exportPanel(p) {
    const q = s => '"' + String(s ?? '').replace(/"/g, '""') + '"';
    const src = EXPORTS[p.id];
    let lines;
    if (src) lines = [src.head.map(q).join(','), ...src.rows.map(r => r.map(q).join(','))];
    else {
      lines = [...p.querySelectorAll('tr')].map(tr => [...tr.children].map(td => q(td.textContent.trim())).join(','));
      if (!lines.length) lines = [...p.querySelectorAll('.cmp')].map(c => [...c.children].map(x => q(x.textContent.trim())).join(','));
    }
    const title = p.querySelector('.panel__title')?.textContent || 'panel';
    const foot = p.querySelector('.panel__foot')?.textContent || '';
    const csv = `# ${title}\n# ${foot.trim()}\n# ${location.href}\n`
      + `# exported ${new Date().toISOString().slice(0, 10)}`
      + `${src ? ' · source rows' : ' · scraped from the rendered table, columns hidden at this width are missing'}\n`
      + lines.join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url;
    a.download = `${title.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);   // was never released
  }
  window.addEventListener('hashchange', render);
  // crests.json is 51 kB of base64 and only two of the eight routes draw a crest.
  // It used to be awaited before the first render on every one of them.
  M.crests = () => (M._crests = M._crests || load('crests.json').then(c => (IDX.crests = c)).catch(() => (IDX.crests = {})));
  (async () => { IDX = await load('index.json'); REG = Object.fromEntries(IDX.registry.map(r => [r.key, r])); IDX.crests = {}; if (!location.hash) location.hash = '/26-27/season'; render(); })();
  M.app = { state, load, render };
})(window.MUFC);
