/* Backtest + Monte Carlo — runs entirely in the browser against stored CSVs. */
(function (global) {
  const { num, isTrue } = global.HKJC;

  function placeOk(rank, field) {
    if (rank <= 0) return false;
    if (field <= 3) return rank === 1;
    if (field <= 6) return rank <= 2;
    return rank <= 3;
  }

  function normalizeCheckpoint(value) {
    const text = String(value || "T-1").trim().toUpperCase();
    if (/^\d+$/.test(text)) return "T-" + text;
    return text;
  }

  function triggers(odds, minOdds, maxOdds, threshold, checkpoint) {
    const wanted = normalizeCheckpoint(checkpoint);
    const best = new Map();
    for (const row of odds) {
      if (String(row.checkpoint || "").toUpperCase() !== wanted) continue;
      const win = num(row.win_odds, NaN);
      const drop = num(row.win_drop_pct, 0);
      const brown = isTrue(row.is_brown_grid) || drop >= threshold;
      if (!Number.isFinite(win) || !brown) continue;
      if (win < minOdds || win > maxOdds) continue;
      const key = `${row.race_date}|${row.venue}|${row.race_no}|${row.horse_no}`;
      best.set(key, row);
    }
    return [...best.values()];
  }

  function evaluate(odds, results, opts) {
    const minOdds = num(opts.minOdds, 3.5);
    const maxOdds = num(opts.maxOdds, 9.0);
    const threshold = num(opts.threshold, 50);
    const betType = opts.betType || "win";
    const checkpoint = opts.checkpoint || "T-1";
    const stake = num(opts.stake, 10);
    const resultMap = new Map();
    const field = new Map();
    for (const r of results) {
      const key = `${r.race_date}|${r.venue}|${r.race_no}|${r.horse_no}`;
      resultMap.set(key, r);
      const fk = `${r.race_date}|${r.venue}|${r.race_no}`;
      field.set(fk, (field.get(fk) || 0) + 1);
    }
    const trades = [];
    for (const t of triggers(odds, minOdds, maxOdds, threshold, checkpoint)) {
      const key = `${t.race_date}|${t.venue}|${t.race_no}|${t.horse_no}`;
      const res = resultMap.get(key);
      if (!res) continue;
      const rank = num(res.finish_rank, 0);
      const winDiv = num(res.win_dividend, 0);
      const plaDiv = num(res.placedividend, 0);
      const fsize = field.get(`${t.race_date}|${t.venue}|${t.race_no}`) || 14;
      let pnl = 0;
      let hit = false;
      let payoutOdds = 0;
      if (betType === "win" || betType === "win_place") {
        pnl += winDiv > 0 ? winDiv - stake : -stake;
        if (winDiv > 0) {
          hit = true;
          payoutOdds = winDiv / stake;
        }
      }
      if (betType === "place" || betType === "win_place") {
        const got = plaDiv > 0 ? plaDiv : placeOk(rank, fsize) ? 0 : 0;
        pnl += got > 0 ? got - stake : -stake;
        if (got > 0) {
          hit = true;
          payoutOdds = Math.max(payoutOdds, got / stake);
        }
      }
      trades.push({
        ...t,
        finish_rank: rank,
        win_dividend: winDiv,
        placedividend: plaDiv,
        pnl: Math.round(pnl * 100) / 100,
        hit,
        payout_odds: payoutOdds,
        stakes: stake * (betType === "win_place" ? 2 : 1),
      });
    }
    const n = trades.length;
    const hits = trades.filter((t) => t.hit).length;
    const staked = trades.reduce((s, t) => s + t.stakes, 0);
    const pnl = trades.reduce((s, t) => s + t.pnl, 0);
    const avgPay =
      hits > 0
        ? trades.filter((t) => t.hit).reduce((s, t) => s + t.payout_odds, 0) / hits
        : 0;
    return {
      triggers: n,
      hits,
      win_rate: n ? (hits / n) * 100 : 0,
      avg_payout_odds: avgPay,
      staked,
      pnl,
      roi: staked ? (pnl / staked) * 100 : 0,
      trades,
    };
  }

  function percentile(sorted, p) {
    if (!sorted.length) return 0;
    const idx = (p / 100) * (sorted.length - 1);
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    if (lo === hi) return sorted[lo];
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
  }

  function monteCarlo(trades, opts) {
    const pnls = trades.map((t) => t.pnl);
    if (!pnls.length) return null;
    const bank0 = num(opts.bankroll, 10000);
    const stake = num(opts.stake, 10);
    const races = Math.max(1, Math.floor(num(opts.races, 400)));
    const sims = Math.max(50, Math.floor(num(opts.sims, 1000)));
    const points = Math.min(80, races);
    const step = Math.max(1, Math.floor(races / points));
    const buckets = Array.from({ length: Math.floor((races - 1) / step) + 1 }, () => []);
    const finals = [];
    const mdds = [];
    let ruin = 0;
    for (let s = 0; s < sims; s++) {
      let eq = bank0;
      let peak = bank0;
      let mdd = 0;
      let ruined = false;
      for (let i = 0; i < races; i++) {
        if (!ruined) {
          eq += pnls[Math.floor(Math.random() * pnls.length)];
          if (eq > peak) peak = eq;
          const dd = peak > 0 ? (peak - eq) / peak : 0;
          if (dd > mdd) mdd = dd;
          if (eq < stake) ruined = true;
        }
        if (i % step === 0) buckets[i / step].push(eq);
      }
      if (ruined) ruin += 1;
      mdds.push(mdd);
      finals.push(eq);
    }
    const bands = buckets.map((col, i) => {
      const sorted = col.slice().sort((a, b) => a - b);
      return {
        x: Math.min(races, i * step + 1),
        p10: percentile(sorted, 10),
        p25: percentile(sorted, 25),
        p50: percentile(sorted, 50),
        p75: percentile(sorted, 75),
        p90: percentile(sorted, 90),
      };
    });
    finals.sort((a, b) => a - b);
    mdds.sort((a, b) => a - b);
    const expectedFinal = finals.reduce((s, v) => s + v, 0) / sims;
    return {
      expected_pnl: expectedFinal - bank0,
      expected_final: expectedFinal,
      mdd_median: percentile(mdds, 50),
      mdd_p95: percentile(mdds, 95),
      ruin: (ruin / sims) * 100,
      p10_final: percentile(finals, 10),
      p90_final: percentile(finals, 90),
      bands,
      sims,
      races,
    };
  }

  const CHECKPOINTS = ["T-15", "T-10", "T-5", "T-3", "T-1", "T-0"];
  const CP_SUFFIX = { "T-15": "t15", "T-10": "t10", "T-5": "t5", "T-3": "t3", "T-1": "t1", "T-0": "t0" };

  function pivotOdds(rows, threshold) {
    const grouped = new Map();
    for (const row of rows) {
      const cp = row.checkpoint;
      if (!CP_SUFFIX[cp]) continue;
      const key = `${row.race_date}|${row.venue}|${row.race_no}|${row.horse_no}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          race_date: row.race_date,
          venue: row.venue,
          race_no: row.race_no,
          scheduled_time: row.scheduled_time,
          horse_no: row.horse_no,
          horse_name: row.horse_name,
          odds: {},
        });
      }
      const item = grouped.get(key);
      if (row.horse_name) item.horse_name = row.horse_name;
      if (row.scheduled_time) item.scheduled_time = row.scheduled_time;
      item.odds[cp] = num(row.win_odds, NaN);
    }
    const wide = [];
    for (const item of grouped.values()) {
      const out = {
        race_date: item.race_date,
        venue: item.venue,
        race_no: item.race_no,
        scheduled_time: item.scheduled_time,
        horse_no: item.horse_no,
        horse_name: item.horse_name,
      };
      const brownAt = [];
      let prevCp = null;
      for (const cp of CHECKPOINTS) {
        const suffix = CP_SUFFIX[cp];
        const current = item.odds[cp];
        out["win_" + suffix] = Number.isFinite(current) ? current : "";
        if (!prevCp) {
          prevCp = cp;
          continue;
        }
        const prev = item.odds[prevCp];
        let drop = 0;
        if (Number.isFinite(prev) && prev > 0 && Number.isFinite(current)) {
          drop = Math.round(((prev - current) / prev) * 10000) / 100;
        }
        const brown = Number.isFinite(current) && Number.isFinite(prev) && drop >= threshold;
        out["drop_" + suffix] = drop;
        out["brown_" + suffix] = brown;
        if (brown) brownAt.push(cp);
        prevCp = cp;
      }
      out.is_brown_grid = brownAt.length > 0;
      out.brown_at = brownAt.join("、");
      wide.push(out);
    }
    wide.sort((a, b) => {
      if (a.race_date !== b.race_date) return a.race_date < b.race_date ? 1 : -1;
      if (a.venue !== b.venue) return String(a.venue).localeCompare(String(b.venue));
      const rn = Number(a.race_no) - Number(b.race_no);
      if (rn) return rn;
      return Number(a.horse_no) - Number(b.horse_no);
    });
    return wide;
  }

  global.HKJCEngine = { evaluate, monteCarlo, triggers, pivotOdds };
})(window);
