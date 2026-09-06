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
    const mark = (s, side, mirror) => {
      const x = mirror ? 100 - s.x : s.x, y = mirror ? 100 - s.y : s.y;
      const r = Math.max(4, Math.sqrt(s.xg) * 22);
      const goal = s.t === 'goal' || s.goal;
      const filled = goal || s.t === 'sot';
      const cls = `${side} ${filled ? '' : 'hollow'} ${s.t === 'blocked' ? 'blocked' : ''}`;
      const tip = `${s.who || ''} ${s.min}′ · xG ${s.xg} · ${goal ? 'goal' : s.t} · ${s.sit || ''}`;
      return `<circle class="${cls}" cx="${px(x).toFixed(1)}" cy="${py(y).toFixed(1)}" r="${r.toFixed(1)}" stroke-width="${goal ? 3 : 1.5}" data-tip="${esc(tip)}"/>`;
    };
    const u = united.filter(keep).map(s => mark(s, uCls, false)).join('');
    const o = opp.filter(keep).map(s => mark(s, oCls, mirror)).join('');
    return pitchFrame(o + u, '', 'Shot map, circle area proportional to expected goals');
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
      const r = Math.max(4, Math.sqrt(sh.xg) * 22); const goal = sh.t === 'goal';
      return `<circle class="u ${goal || sh.t === 'sot' ? '' : 'hollow'} ${sh.t === 'blocked' ? 'blocked' : ''}" cx="${px(sh.x).toFixed(1)}" cy="${py(sh.y).toFixed(1)}" r="${r.toFixed(1)}" stroke-width="${goal ? 3 : 1.5}" data-tip="${sh.min}′ · xG ${sh.xg} · ${sh.t}"/>` +
        (goal ? `<text x="${(px(sh.x) + r + 2).toFixed(1)}" y="${(py(sh.y) + 3).toFixed(1)}">${sh.min}′</text>` : '');
    }).join('');
    return pitchFrame(t + s, '', `${points.length} touches with shots overlaid`);
  }

  // Cumulative xG race: series [[min,xg],…] for both sides, goals [{min,team}].
  function xgRace(tl, oppName) {
    const w = 520, h = 200, padL = 30, padR = 12, padT = 10, padB = 22;
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

  M.charts = { shotMap, heatGrid, network, touchPlot, xgRace, barList, pitchFrame, W, H, px, py };
})(window.MUFC);
