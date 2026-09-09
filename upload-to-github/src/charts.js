/* charts.js — SVG builders. Every chart takes payload rows and returns an SVG string.
   Coordinates: WhoScored 0–100 on both axes, United attacking left → right. */
window.MUFC = window.MUFC || {};
(function (M) {
  const W = 420, H = 272;
  const px = x => (x / 100) * W;
  const py = y => ((100 - y) / 100) * H;
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

  function pitchFrame(inner, cls = '', label = 'pitch') {
    return `<svg class="pitch ${cls}" viewBox="-6 -6 ${W + 12} ${H + 12}" role="img" aria-label="${esc(label)}">
      <rect class="turf" x="0" y="0" width="${W}" height="${H}"/>
      <line class="line" x1="${W / 2}" y1="0" x2="${W / 2}" y2="${H}"/>
      <rect class="line" x="0" y="${H * 0.2}" width="${W * 0.165}" height="${H * 0.6}"/>
      <rect class="line" x="${W - W * 0.165}" y="${H * 0.2}" width="${W * 0.165}" height="${H * 0.6}"/>
      <rect class="line" x="0" y="${H * 0.37}" width="${W * 0.055}" height="${H * 0.26}"/>
      <rect class="line" x="${W - W * 0.055}" y="${H * 0.37}" width="${W * 0.055}" height="${H * 0.26}"/>
      <circle class="line" cx="${W / 2}" cy="${H / 2}" r="${H * 0.135}"/>
      ${inner}
    </svg>`;
  }

  // Shot map: united shots as given; opponent shots mirrored onto the same frame.
  function shotMap(united, opp, filter, opts = {}) {
    const mirror = opts.mirror !== false, uCls = opts.uClass || 'u', oCls = opts.oClass || 'o';
    const keep = s => {
      if (!filter) return true;
      if (filter.source && filter.source !== 'all') {
        const sp = ['corner', 'freekick', 'throwin', 'penalty'];
        if (filter.source === 'setpiece' && !sp.includes(s.sit)) return false;
        if (filter.source === 'open' && s.sit !== 'open') return false;
        if (filter.source === 'fastbreak' && s.sit !== 'fastbreak') return false;
      }
      if (filter.outcome && filter.outcome !== 'all') {
        const isGoal = s.t === 'goal' || s.goal;
        if (filter.outcome === 'goal' && !isGoal) return false;
        if (filter.outcome === 'sot' && !(s.t === 'sot' || isGoal)) return false;
        if (filter.outcome === 'off' && s.t !== 'off') return false;
        if (filter.outcome === 'blocked' && s.t !== 'blocked') return false;
      }
      return true;
    };
    // A shot with no xG is not a shot with a small xG. Math.sqrt(null) is 0, so
    // sizing an unpriced shot by the same formula draws every one of them at the
    // 4px floor — a map that looks like thirty-two identical chances under a
    // caption promising that circle area is xG. Until the Twelve report lands
    // the marks carry position and outcome only, and say so.
    const mark = (s, side, mirror) => {
      const x = mirror ? 100 - s.x : s.x, y = mirror ? 100 - s.y : s.y;
      const priced = s.xg !== null && s.xg !== undefined && !Number.isNaN(Number(s.xg));
      const r = priced ? Math.max(4, Math.sqrt(s.xg) * 22) : 7;
      const goal = s.t === 'goal' || s.goal;
      const filled = goal || s.t === 'sot';
      const cls = `${side} ${filled ? '' : 'hollow'} ${s.t === 'blocked' ? 'blocked' : ''} ${priced ? '' : 'unpriced'}`;
      const xgTxt = priced ? `xG ${Number(s.xg).toFixed(2)}${s.xg_src === 'modelled' ? ' modelled' : ''}` : 'xG pending';
      const tip = `${s.who || ''} ${s.min}′ · ${xgTxt} · ${goal ? 'goal' : s.t} · ${s.sit || ''}`;
      return `<circle class="${cls}" cx="${px(x).toFixed(1)}" cy="${py(y).toFixed(1)}" r="${r.toFixed(1)}" stroke-width="${goal ? 3 : 1.5}" data-tip="${esc(tip)}"/>`;
    };
    const kept = [...united.filter(keep), ...opp.filter(keep)];
    const anyPriced = kept.some(s => s.xg !== null && s.xg !== undefined);
    const u = united.filter(keep).map(s => mark(s, uCls, false)).join('');
    const o = opp.filter(keep).map(s => mark(s, oCls, mirror)).join('');
    const label = anyPriced
      ? 'Shot map, circle area proportional to expected goals'
      : 'Shot map, positions and outcomes only — expected goals not yet available, so every mark is drawn the same size';
    return pitchFrame(o + u, anyPriced ? '' : 'pitch--unpriced', label);
  }

  // Heat grid: cols × rows counts, opacity ramp on the accent.
  function heatGrid(heat, side = 'u') {
    const cells = side === 'u' ? heat.u : heat.o;
    const mx = Math.max(...cells, 1);
    const cw = W / heat.cols, ch = H / heat.rows;
    let out = '';
    for (let r = 0; r < heat.rows; r++) for (let c = 0; c < heat.cols; c++) {
      const v = cells[r * heat.cols + c];
      out += `<rect class="cell" x="${(c * cw + 0.5).toFixed(1)}" y="${(r * ch + 0.5).toFixed(1)}" width="${(cw - 1).toFixed(1)}" height="${(ch - 1).toFixed(1)}" opacity="${(0.05 + 0.85 * v / mx).toFixed(2)}" data-tip="${v} touches"/>`;
    }
    return pitchFrame(out, '', `Touch density, ${heat.cols} by ${heat.rows} grid, peak ${mx} touches per cell`);
  }

  // Pass network from nodes {nm,x,y,n} and links {x1,y1,x2,y2,n,a,b}.
  function network(nodes, links, minPasses = 6, cls = '') {
    const l = links.filter(k => k.n >= minPasses).map(k =>
      `<line class="link" x1="${px(k.x1).toFixed(1)}" y1="${py(k.y1).toFixed(1)}" x2="${px(k.x2).toFixed(1)}" y2="${py(k.y2).toFixed(1)}" stroke-width="${Math.max(1, k.n / 8).toFixed(1)}" data-tip="${esc(k.a)} → ${esc(k.b)} · ${k.n} passes"/>`).join('');
    const n = nodes.map(d => {
      const r = 6 + d.n / 9;
      return `<circle class="node" cx="${px(d.x).toFixed(1)}" cy="${py(d.y).toFixed(1)}" r="${r.toFixed(1)}" data-tip="${esc(d.nm)} · ${d.n} passes · ${d.mins || ''}${d.mins ? '′' : ''}"/>
        <text x="${px(d.x).toFixed(1)}" y="${(py(d.y) + r + 10).toFixed(1)}" text-anchor="middle">${esc(d.nm)}</text>`;
    }).join('');
    return pitchFrame(l + n, cls, `Passing network, node size = passes played, link width = passes between the pair, links under ${minPasses} hidden`);
  }

  // Player touch plot: points [[x,y],…] plus that player's shots.
  function touchPlot(points, shots) {
    const t = points.filter(p => !(p[0] > 99 && p[1] > 99)).map(p => `<circle class="touch" cx="${px(p[0]).toFixed(1)}" cy="${py(p[1]).toFixed(1)}" r="2.5"/>`).join('');
    const s = (shots || []).map(sh => {
      const priced = sh.xg !== null && sh.xg !== undefined;
      const r = priced ? Math.max(4, Math.sqrt(sh.xg) * 22) : 7; const goal = sh.t === 'goal';
      return `<circle class="u ${goal || sh.t === 'sot' ? '' : 'hollow'} ${sh.t === 'blocked' ? 'blocked' : ''} ${priced ? '' : 'unpriced'}" cx="${px(sh.x).toFixed(1)}" cy="${py(sh.y).toFixed(1)}" r="${r.toFixed(1)}" stroke-width="${goal ? 3 : 1.5}" data-tip="${sh.min}′ · ${priced ? `xG ${sh.xg}` : 'xG pending'} · ${sh.t}"/>` +
        (goal ? `<text x="${(px(sh.x) + r + 2).toFixed(1)}" y="${(py(sh.y) + 3).toFixed(1)}">${sh.min}′</text>` : '');
    }).join('');
    return pitchFrame(t + s, '', `${points.length} touches with shots overlaid`);
  }

  // Cumulative xG race: series [[min,xg],…] for both sides, goals [{min,team}].
  function xgRace(tl, oppName) {
    const w = 520, h = 200, padL = 30, padR = 12, padT = 10, padB = 22;
    // Until the Twelve report lands there is no xG to accumulate — WhoScored's match
    // centre carries no expectedGoals field. The goals and their minutes are counted
    // from the event stream and ARE known, so the panel shows when the match turned
    // rather than an empty pair of axes captioned as a chart.
    if (!(tl.united && tl.united.length) && !(tl.opp && tl.opp.length)) {
      const bh = 118, dotY = bh - padB - 16;
      const bx = m => padL + (Math.min(m, 95) / 95) * (w - padL - padR);
      const ticks = [0, 15, 30, 45, 60, 75, 90].map(m =>
        `<line class="grid" x1="${bx(m).toFixed(1)}" y1="${padT}" x2="${bx(m).toFixed(1)}" y2="${bh - padB}"/>` +
        `<text x="${bx(m).toFixed(1)}" y="${bh - 6}" text-anchor="middle">${m === 45 ? 'HT' : m}</text>`).join('');
      const goals = (tl.goals || []).slice().sort((a, b) => a.min - b.min);
      // Two goals five minutes apart put their labels on top of each other. Lanes are
      // assigned greedily by measured width, so a label only moves up when the one
      // beside it would collide — the common case stays on a single line.
      const lanes = [];
      const stems = [], dots = [], labels = [];
      let gu = 0, go = 0;
      goals.forEach(g => {
        if (g.team === 'u') gu++; else go++;
        const who = String(g.who || '').split(' ').slice(-1)[0];
        const text = `${g.min}′ ${who}`;
        const x = bx(g.min), tw = text.length * 5.4;
        let left = x - tw / 2, right = x + tw / 2, anchor = 'middle';
        if (right > w - padR) { right = w - padR; left = right - tw; anchor = 'end'; }
        if (left < padL) { left = padL; right = left + tw; anchor = 'start'; }
        const tx = anchor === 'end' ? right : (anchor === 'start' ? left : x);
        let lane = 0;
        while ((lanes[lane] || []).some(s => left < s[1] + 7 && right > s[0] - 7)) lane++;
        (lanes[lane] = lanes[lane] || []).push([left, right]);
        const ly = dotY - 11 - lane * 12;
        const mine = g.team === 'u';
        // Emitted in three passes rather than three-per-goal: a stem drawn after a
        // neighbour's label paints over it, and SVG has no z-index to fix it with.
        stems.push(`<line class="grid" x1="${x.toFixed(1)}" y1="${(ly + 3).toFixed(1)}" x2="${x.toFixed(1)}" y2="${bh - padB}"/>`);
        dots.push(`<circle class="goal ${mine ? 'u' : 'o'}" cx="${x.toFixed(1)}" cy="${dotY}" r="5" ` +
          `stroke="${mine ? 'var(--united)' : 'var(--opponent)'}" ` +
          `data-tip="${g.min}′ ${esc(g.who || '')} · ${g.sit || ''} · ${gu}–${go}"/>`);
        labels.push(`<text x="${tx.toFixed(1)}" y="${ly}" text-anchor="${anchor}">${esc(text)}</text>`);
      });
      const marks = stems.join('') + dots.join('') + labels.join('');
      const label = goals.length
        ? `Goal timeline, United ${gu} Everton ${go}`.replace('Everton', esc(oppName)) + ' — ' +
          goals.map(g => `${g.min} minutes ${esc(String(g.who || ''))}`).join(', ') +
          '. Expected goals are not yet available from the supplier, so no xG line is drawn.'
        : 'Goal timeline — no goals, and expected goals not yet available from the supplier.';
      return `<svg class="xgline" viewBox="0 0 ${w} ${bh}" role="img" aria-label="${label}">${ticks}` +
        `<line class="grid" x1="${padL}" y1="${bh - padB}" x2="${w - padR}" y2="${bh - padB}"/>${marks}</svg>`;
    }
    const maxX = 95, maxY = Math.max(tl.united.at(-1)[1], tl.opp.at(-1)[1], 1) * 1.08;
    const sx = m => padL + (m / maxX) * (w - padL - padR);
    const sy = v => padT + (1 - v / maxY) * (h - padT - padB);
    const path = pts => pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`).join(' ');
    const step = pts => { let d = `M${sx(0)} ${sy(0)}`, last = 0; pts.forEach(p => { d += ` L${sx(p[0]).toFixed(1)} ${sy(last).toFixed(1)} L${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`; last = p[1]; }); return d; };
    const goalMark = g => { const series = g.team === 'u' ? tl.united : tl.opp; const at = series.filter(p => p[0] <= g.min).at(-1) || [g.min, 0];
      return `<circle class="goal ${g.team === 'u' ? 'u' : 'o'}" cx="${sx(g.min).toFixed(1)}" cy="${sy(at[1]).toFixed(1)}" r="5" data-tip="${g.min}′ ${esc(g.who || '')} · ${g.sit || ''}" stroke="${g.team === 'u' ? 'var(--united)' : 'var(--opponent)'}"/>`; };
    const ticks = [0, 15, 30, 45, 60, 75, 90].map(m => `<line class="grid" x1="${sx(m)}" y1="${padT}" x2="${sx(m)}" y2="${h - padB}"/><text x="${sx(m)}" y="${h - 6}" text-anchor="middle">${m === 45 ? 'HT' : m}</text>`).join('');
    const yt = [0.5, 1, 1.5, 2, 3, 4, 5].filter(v => v < maxY).map(v => `<line class="grid" x1="${padL}" y1="${sy(v)}" x2="${w - padR}" y2="${sy(v)}"/><text x="${padL - 4}" y="${sy(v) + 3}" text-anchor="end">${v}</text>`).join('');
    return `<svg class="xgline" viewBox="0 0 ${w} ${h}" role="img" aria-label="Cumulative expected goals by minute, United against ${esc(oppName)}">
      ${ticks}${yt}
      <path class="o" d="${step(tl.opp)}"/><path class="u" d="${step(tl.united)}"/>
      ${tl.goals.map(goalMark).join('')}
    </svg>`;
  }

  // Simple horizontal bar list (label, value, frac) for per-90 rankings etc.
  function barList(rows, cls = '') {
    return rows.map(r => `<div class="cmp" style="grid-template-columns:minmax(110px,170px) minmax(0,1fr) auto"><span class="cmp__lab ${r.hot ? 'hot' : ''}">${esc(r.label)}${r.sub ? `<br><span class="t-cap">${esc(r.sub)}</span>` : ''}</span><span class="bar ${cls} ${r.muted ? 'grey' : ''}"><i style="width:${(r.frac * 100).toFixed(1)}%"></i></span><span class="cmp__o" style="text-align:right;white-space:nowrap;color:${r.muted ? 'var(--muted)' : 'inherit'}">${r.value}</span></div>`).join('');
  }

  // ------------------------------------------------------------------ story charts
  // Shared frame for the season-scale charts: x is the matchweek, y a value.
  // Grid and axes are solid hairlines one step off the surface; the reference
  // series (25/26) is grey AND dashed so the pair never rests on hue alone.
  function frame(w, h, pad, xs, ys, opts = {}) {
    const sx = x => pad.l + ((x - xs.min) / (xs.max - xs.min || 1)) * (w - pad.l - pad.r);
    const sy = y => pad.t + (1 - (y - ys.min) / (ys.max - ys.min || 1)) * (h - pad.t - pad.b);
    const xt = (opts.xTicks || []).map(t => `<line class="grid" x1="${sx(t).toFixed(1)}" y1="${pad.t}" x2="${sx(t).toFixed(1)}" y2="${h - pad.b}"/><text x="${sx(t).toFixed(1)}" y="${h - 6}" text-anchor="middle">${opts.xFmt ? opts.xFmt(t) : t}</text>`).join('');
    const yt = (opts.yTicks || []).map(t => `<line class="grid ${t === 0 ? 'zero' : ''}" x1="${pad.l}" y1="${sy(t).toFixed(1)}" x2="${w - pad.r}" y2="${sy(t).toFixed(1)}"/><text x="${pad.l - 5}" y="${(sy(t) + 3).toFixed(1)}" text-anchor="end">${opts.yFmt ? opts.yFmt(t) : t}</text>`).join('');
    return { sx, sy, axes: xt + yt };
  }
  function ticks(min, max, n = 5) {
    const span = max - min || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n + 1) || mag * 10;
    const out = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(6)));
    return out;
  }

  // Multi-series line over matchweeks with optional era bands and event marks.
  //   series: [{label, pts:[[round,value],…], cls:'u'|'base'|'o', dash?:bool, endLabel?:string}]
  //   bands:  [{from,to,label,cls}]  — shaded x-ranges (manager eras)
  //   marks:  [{x,y,label,cls,tip}]  — dots with a stem (turning points)
  function lineChart(o) {
    const w = o.w || 560, h = o.h || 220, pad = { l: 34, r: o.padR || 60, t: 14, b: 24 };
    const all = o.series.flatMap(s => s.pts).filter(p => p[1] !== null && p[1] !== undefined);
    if (!all.length) return '<p class="t-cap">Nothing to draw yet.</p>';
    const xs = { min: o.xMin ?? 1, max: o.xMax ?? Math.max(...all.map(p => p[0]), 2) };
    let ymin = Math.min(0, ...all.map(p => p[1])), ymax = Math.max(...all.map(p => p[1]));
    if (ymax === ymin) ymax = ymin + 1;
    const yT = ticks(ymin, ymax, 4); ymin = Math.min(ymin, yT[0]); ymax = Math.max(ymax, yT.at(-1));
    const xT = o.xTicks || (xs.max - xs.min > 12 ? [1, 5, 10, 15, 20, 25, 30, 35, 38].filter(t => t <= xs.max) : Array.from({ length: xs.max - xs.min + 1 }, (_, i) => xs.min + i));
    const F = frame(w, h, pad, xs, { min: ymin, max: ymax }, { xTicks: xT, yTicks: yT, yFmt: o.yFmt });
    const bands = (o.bands || []).map(b => {
      const x0 = Math.max(pad.l, F.sx(b.from - 0.5)), x1 = Math.min(w - pad.r, F.sx(b.to + 0.5)), bw = x1 - x0;
      const lab = bw >= b.label.length * 6.5 + 8 ? `<text class="band__lab" x="${(x0 + 4).toFixed(1)}" y="${pad.t + 10}">${esc(b.label)}</text>` : '';
      return `<rect class="band ${b.cls || ''}" x="${x0.toFixed(1)}" y="${pad.t}" width="${bw.toFixed(1)}" height="${h - pad.t - pad.b}" data-tip="${esc(b.tip || b.label)}" tabindex="0"/>${lab}`;
    }).join('');
    const lines = o.series.map(s => {
      const pts = s.pts.filter(p => p[1] !== null && p[1] !== undefined);
      if (!pts.length) return '';
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${F.sx(p[0]).toFixed(1)} ${F.sy(p[1]).toFixed(1)}`).join(' ');
      const last = pts.at(-1);
      const dots = pts.length <= 12 ? pts.map(p => `<circle class="pt ${s.cls}" cx="${F.sx(p[0]).toFixed(1)}" cy="${F.sy(p[1]).toFixed(1)}" r="4" data-tip="${esc(`${s.label} · ${o.xWord || 'MW'}${p[0]} · ${o.yFmt ? o.yFmt(p[1]) : p[1]}${p[2] ? ' · ' + p[2] : ''}`)}"/>`).join('')
        : pts.map(p => `<circle class="hit" cx="${F.sx(p[0]).toFixed(1)}" cy="${F.sy(p[1]).toFixed(1)}" r="7" data-tip="${esc(`${s.label} · ${o.xWord || 'MW'}${p[0]} · ${o.yFmt ? o.yFmt(p[1]) : p[1]}${p[2] ? ' · ' + p[2] : ''}`)}"/>`).join('');
      return `<path class="ln ${s.cls} ${s.dash ? 'dash' : ''}" d="${d}"/>${dots}` +
        `<text class="end ${s.cls}" x="${(F.sx(last[0]) + 6).toFixed(1)}" y="${(F.sy(last[1]) + 4).toFixed(1)}">${esc(s.endLabel ?? (o.yFmt ? o.yFmt(last[1]) : last[1]))}</text>`;
    }).join('');
    const marks = (o.marks || []).map(m => `<line class="stem" x1="${F.sx(m.x).toFixed(1)}" y1="${pad.t}" x2="${F.sx(m.x).toFixed(1)}" y2="${h - pad.b}"/>` +
      `<circle class="mark ${m.cls || ''}" cx="${F.sx(m.x).toFixed(1)}" cy="${F.sy(m.y).toFixed(1)}" r="6" data-tip="${esc(m.tip || m.label)}" tabindex="0"/>` +
      (m.label ? `<text class="mark__lab" x="${F.sx(m.x).toFixed(1)}" y="${pad.t + (m.dy || 22)}" text-anchor="middle">${esc(m.label)}</text>` : '')).join('');
    return `<svg class="story" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(o.aria || o.title || 'line chart')}">${bands}${F.axes}${lines}${marks}</svg>`;
  }

  // Scatter with an optional fitted line and a vertical guide (the dominance trap).
  function scatter(o) {
    const w = o.w || 520, h = o.h || 260, pad = { l: 34, r: 16, t: 18, b: 26 };
    const xs = { min: Math.floor(Math.min(...o.pts.map(p => p.x)) / 5) * 5, max: Math.ceil(Math.max(...o.pts.map(p => p.x)) / 5) * 5 };
    const ys = { min: 0, max: Math.max(...o.pts.map(p => p.y)) + 0.5 };
    const F = frame(w, h, pad, xs, ys, { xTicks: ticks(xs.min, xs.max, 6), yTicks: o.yTicks || [0, 1, 3] });
    const guide = o.guides ? o.guides.map(g => `<line class="guide" x1="${F.sx(g.x).toFixed(1)}" y1="${pad.t}" x2="${F.sx(g.x).toFixed(1)}" y2="${h - pad.b}"/><text class="guide__lab" x="${(F.sx(g.x) + 4).toFixed(1)}" y="${pad.t + 10}">${esc(g.label)}</text>`).join('') : '';
    const fit = o.fit ? `<line class="fit" x1="${F.sx(xs.min).toFixed(1)}" y1="${F.sy(Math.max(ys.min, Math.min(ys.max, o.fit.icept + o.fit.slope * xs.min))).toFixed(1)}" x2="${F.sx(xs.max).toFixed(1)}" y2="${F.sy(Math.max(ys.min, Math.min(ys.max, o.fit.icept + o.fit.slope * xs.max))).toFixed(1)}"/>` : '';
    // jitter y a little so ten identical "3 points" do not stack into one dot
    const dots = o.pts.map((p, i) => `<circle class="pt ${p.cls || 'base'}" cx="${F.sx(p.x).toFixed(1)}" cy="${(F.sy(p.y) + ((i % 3) - 1) * 3).toFixed(1)}" r="${p.r || 5}" data-tip="${esc(p.tip || p.label)}" tabindex="0"/>` +
      (p.label ? `<text class="pt__lab" x="${(F.sx(p.x) + 8).toFixed(1)}" y="${(F.sy(p.y) + 3).toFixed(1)}">${esc(p.label)}</text>` : '')).join('');
    return `<svg class="story" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(o.aria || 'scatter')}">${F.axes}${guide}${fit}${dots}` +
      `<text class="axis__lab" x="${w - pad.r}" y="${pad.t - 4}" text-anchor="end">${esc(o.xLabel || '')} →</text><text class="axis__lab" x="${pad.l + 4}" y="${pad.t + 10}">${esc(o.yLabel || '')}</text></svg>`;
  }

  // Per-matchweek paired bars: United up from the axis in red, the opponent down in blue.
  function pairedBars(o) {
    const w = o.w || 560, h = o.h || 200, pad = { l: 30, r: 12, t: 14, b: 22 };
    const n = o.rows.length, mx = Math.max(...o.rows.flatMap(r => [r.a || 0, r.b || 0]), 0.01);
    const bw = Math.max(3, (w - pad.l - pad.r) / n - 2);
    const mid = pad.t + (h - pad.t - pad.b) / 2, sc = v => (v / mx) * ((h - pad.t - pad.b) / 2 - 2);
    const bars = o.rows.map((r, i) => {
      const x = pad.l + i * ((w - pad.l - pad.r) / n) + 1;
      const tip = esc(r.tip || r.label);
      return `<rect class="xbar u" x="${x.toFixed(1)}" y="${(mid - sc(r.a || 0)).toFixed(1)}" width="${bw.toFixed(1)}" height="${sc(r.a || 0).toFixed(1)}" rx="1" data-tip="${tip}"/>` +
        `<rect class="xbar o" x="${x.toFixed(1)}" y="${(mid + 1).toFixed(1)}" width="${bw.toFixed(1)}" height="${sc(r.b || 0).toFixed(1)}" rx="1" data-tip="${tip}"/>` +
        (r.res ? `<rect class="res ${r.res}" x="${x.toFixed(1)}" y="${h - pad.b + 4}" width="${bw.toFixed(1)}" height="3"/>` : '') +
        (o.labelEvery && i % o.labelEvery === 0 ? `<text x="${(x + bw / 2).toFixed(1)}" y="${h - 6}" text-anchor="middle">${r.x}</text>` : '');
    }).join('');
    const yl = [mx].map(v => `<text x="${pad.l - 5}" y="${(mid - sc(v) + 3).toFixed(1)}" text-anchor="end">${v.toFixed(o.dp ?? 1)}</text><text x="${pad.l - 5}" y="${(mid + sc(v) + 3).toFixed(1)}" text-anchor="end">${v.toFixed(o.dp ?? 1)}</text>`).join('');
    return `<svg class="story" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(o.aria || 'paired bars')}"><line class="grid zero" x1="${pad.l}" y1="${mid}" x2="${w - pad.r}" y2="${mid}"/>${yl}${bars}</svg>`;
  }

  // One 25/26 distribution as a range strip (min–max, q1–q3, median) with the
  // 26/27 matches as dots on it. Colour is never the only signal: each dot is
  // labelled by matchweek and the tooltip carries the percentile.
  function distStrip(row, opts = {}) {
    const w = 360, h = 44, l = 8, r = 8;
    const span = row.max - row.min || 1, sx = v => l + ((v - row.min) / span) * (w - l - r);
    const dots = row.matches.map(m => m.value === null || m.value === undefined ? '' :
      `<circle class="pt u" cx="${sx(m.value).toFixed(1)}" cy="18" r="6" data-tip="${esc(`MW${m.round} ${m.opp} · ${m.value} · ${m.pct}th percentile of 25/26`)}" tabindex="0"/>` +
      `<text class="dot__lab" x="${sx(m.value).toFixed(1)}" y="40" text-anchor="middle">${m.round}</text>`).join('');
    return `<svg class="strip" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(`${row.label}: 25/26 ranged ${row.min} to ${row.max}, median ${row.median}; ${row.matches.map(m => `MW${m.round} ${m.value} (${m.pct}th percentile)`).join(', ')}`)}">` +
      `<line class="range" x1="${sx(row.min)}" y1="18" x2="${sx(row.max)}" y2="18"/>` +
      `<rect class="iqr" x="${sx(row.q1).toFixed(1)}" y="12" width="${(sx(row.q3) - sx(row.q1)).toFixed(1)}" height="12" rx="2" data-tip="${esc(`25/26 middle half: ${row.q1} to ${row.q3}`)}"/>` +
      `<line class="med" x1="${sx(row.median).toFixed(1)}" y1="8" x2="${sx(row.median).toFixed(1)}" y2="28" data-tip="${esc(`25/26 median ${row.median}`)}"/>` +
      `<text class="dot__lab" x="${sx(row.min)}" y="40" text-anchor="start">${row.min}</text><text class="dot__lab" x="${sx(row.max)}" y="40" text-anchor="end">${row.max}</text>${dots}</svg>`;
  }

  // Formation slots, one full pitch per side so eleven names have room to be
  // read. `v` runs 0 (own goal line) to 10 (attacking), `h` 0 to 10 across; each
  // side attacks left → right on its own frame, the way the shot map's per-team
  // frames do.
  function lineupPitch(uSide, oSide, opts = {}) {
    const place = p => [6 + (p.v ?? 0) * 8.8, 6 + (p.h ?? 5) * 8.8];
    const draw = (side, cls) => (side?.xi || []).map(p => {
      const [x, y] = place(p);
      const tip = `${p.name} · ${p.pos}${p.rating != null ? ` · rating ${p.rating.toFixed(2)} (WhoScored)` : ''}${p.captain ? ' · captain' : ''}`;
      return `<g class="slot ${cls}" data-tip="${esc(tip)}" tabindex="0"><circle cx="${px(x).toFixed(1)}" cy="${py(y).toFixed(1)}" r="12"/>` +
        `<text class="shirt" x="${px(x).toFixed(1)}" y="${(py(y) + 3.5).toFixed(1)}" text-anchor="middle">${p.shirt ?? ''}</text>` +
        `<text class="nm" x="${px(x).toFixed(1)}" y="${(py(y) + 24).toFixed(1)}" text-anchor="middle">${esc((p.short || p.name).slice(0, 12))}</text>` +
        (p.rating != null && opts.ratings !== false ? `<text class="rt" x="${px(x).toFixed(1)}" y="${(py(y) - 16).toFixed(1)}" text-anchor="middle">${p.rating.toFixed(1)}</text>` : '') + `</g>`;
    }).join('');
    const one = (side, cls, name) => side ? `<figure class="lineup__side"><figcaption class="t-label">${esc(name)} · ${esc(side.formation || '')}</figcaption>${pitchFrame(draw(side, cls), 'pitch--lineup', `${name} starting shape ${side.formation || ''}: ${(side.xi || []).map(p => `${p.shirt} ${p.short || p.name}${p.rating != null ? ` rated ${p.rating.toFixed(1)}` : ''}`).join(', ')}`)}</figure>` : '';
    return `<div class="lineup">${one(uSide, 'u', 'United')}${one(oSide, 'o', opts.oppName || 'Opponent')}</div>`;
  }

  // Minute rail: goals, substitutions and cards for both sides on one 0–95 axis.
  function eventRail(events, oppName) {
    const w = 560, h = 112, padL = 30, padR = 12, mid = 52;
    const bx = m => padL + (Math.min(m, 97) / 97) * (w - padL - padR);
    const ticks = [0, 15, 30, 45, 60, 75, 90].map(m => `<line class="grid" x1="${bx(m).toFixed(1)}" y1="16" x2="${bx(m).toFixed(1)}" y2="88"/><text x="${bx(m).toFixed(1)}" y="${h - 4}" text-anchor="middle">${m === 45 ? 'HT' : m}</text>`).join('');
    const glyph = e => {
      const x = bx(e.min).toFixed(1), up = e.team === 'u', y = up ? 34 : 70;
      const lx = Math.max(padL + 14, Math.min(w - padR - 14, Number(x))).toFixed(1);
      const tip = e.kind === 'goal' ? `${e.min}′ goal · ${e.who}${e.pen ? ' (pen)' : ''}` : e.kind === 'sub' ? `${e.min}′ ${e.who} on for ${e.off}` : `${e.min}′ ${e.card} card · ${e.who}`;
      const cls = `ev ${e.team} ${e.kind} ${e.card || ''}`;
      let g = '';
      if (e.kind === 'goal') g = `<circle cx="${x}" cy="${y}" r="7"/>`;
      else if (e.kind === 'sub') g = `<path d="M${x} ${y - 6} l5 6 h-10 z M${x} ${y + 6} l5 -6 h-10 z"/>`;
      else g = `<rect x="${(Number(x) - 3).toFixed(1)}" y="${y - 6}" width="6" height="12" rx="1"/>`;
      return `<g class="${cls}" data-tip="${esc(tip)}" tabindex="0">${g}<rect class="hit" x="${(Number(x) - 10).toFixed(1)}" y="${y - 12}" width="20" height="24"/></g>` +
        (e.kind === 'goal' ? `<text class="ev__lab" x="${lx}" y="${up ? 18 : 92}" text-anchor="middle">${esc(e.who.split(' ')[0].slice(0, 12))}</text>` : '');
    };
    const sideLab = `<text class="side" x="2" y="37">MUFC</text><text class="side" x="2" y="73">${esc((oppName || 'OPP').slice(0, 4).toUpperCase())}</text>`;
    return `<svg class="rail" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(`Match events: ${events.map(e => `${e.min} minutes ${e.kind} ${e.who}`).join(', ')}`)}">${ticks}<line class="grid zero" x1="${padL}" y1="${mid}" x2="${w - padR}" y2="${mid}"/>${sideLab}${events.map(glyph).join('')}</svg>`;
  }

  M.charts = { shotMap, heatGrid, network, touchPlot, xgRace, barList, pitchFrame, lineChart, scatter, pairedBars, distStrip, lineupPitch, eventRail, W, H, px, py };
})(window.MUFC);
