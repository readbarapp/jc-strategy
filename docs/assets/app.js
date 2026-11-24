/* HKJC Quant Desk SPA */
(function () {
  const { formatHk, weekdayZh, parseCsv, toCsv, downloadBlob, detectRepo, saveRepo,
    loadRelativeOrRaw, ghPutFile, ghDispatch, ghLatestRun, num, isTrue } = window.HKJC;
  const { evaluate, monteCarlo, pivotOdds, yearlyBets, triggers, officialBrown } = window.HKJCEngine;

  const ODDS_BOARD_COLS = [
    { key: "odds_t15", label: "開賽前15分鐘", brownKey: null, gridKey: "grid_t15" },
    { key: "odds_t10", label: "開賽前10分鐘", brownKey: "brown_t10", gridKey: "grid_t10" },
    { key: "odds_t5", label: "開賽前5分鐘", brownKey: "brown_t5", gridKey: "grid_t5" },
    { key: "odds_t1", label: "開賽前1分鐘", brownKey: "brown_t1", gridKey: "grid_t1" },
    { key: "odds_t0", label: "開跑", brownKey: "brown_t0", gridKey: "grid_t0" },
  ];
  const WIDE_EXPORT_PAIRS = [
    ["pool", "彩池"],
    ["race_date", "日期"],
    ["venue", "場地"],
    ["race_no", "場次"],
    ["scheduled_time", "開跑時間"],
    ["horse_no", "馬號"],
    ["horse_name", "馬名"],
    ["odds_t15", "開賽前15分鐘"],
    ["odds_t10", "開賽前10分鐘"],
    ["odds_t5", "開賽前5分鐘"],
    ["odds_t1", "開賽前1分鐘"],
    ["odds_t0", "開跑"],
    ["brown_at", "急跌時間點"],
  ];

  const RESULT_FIELDS = [
    "race_date", "venue", "race_no", "horse_no", "horse_name", "finish_rank", "final_sp", "win_dividend", "placedividend",
  ];
  const ODDS_SNAPSHOT_FIELDS = [
    "race_date", "venue", "race_no", "scheduled_time", "checkpoint", "capture_timestamp",
    "minutes_to_post", "horse_no", "horse_name", "win_odds", "place_odds", "prev_win_odds",
    "win_drop_pct", "is_brown_grid", "hkjc_grid", "place_grid", "brown_hold_seconds",
  ];

  const state = {
    tab: "data",
    config: null,
    odds: [],
    results: [],
    logText: "",
    status: {},
    github: detectRepo(),
    notice: "",
    noticeKind: "info",
    page: 1,
    tableSource: "win",
    liveRows: [],
    liveFetchedAt: "",
    liveError: "",
    liveDelay: 4000,
    guideKind: "user",
    chart: null,
    pathChart: null,
    backtest: null,
    mc: null,
    dataOrigin: "demo",
    ticks: [],
    inspect: null,
  };

  const $ = (id) => document.getElementById(id);
  const venueName = (v) => (v === "ST" ? "沙田 ST" : v === "HV" ? "跑馬地 HV" : v || "—");

  function toast(msg, kind) {
    state.notice = msg;
    state.noticeKind = kind || "info";
    const el = $("notice");
    if (!el) return;
    el.textContent = msg;
    el.className =
      "rounded-lg px-3 py-2 text-sm " +
      (kind === "error"
        ? "bg-rose-500/15 text-rose-200 border border-rose-500/30"
        : kind === "ok"
          ? "bg-emerald-500/15 text-emerald-200 border border-emerald-500/30"
          : "bg-white/5 text-slate-300 border border-white/10");
    el.classList.toggle("hidden", !msg);
  }

  function currentThreshold() {
    return num($("brown-threshold") && $("brown-threshold").value, 50);
  }

  function currentHoldNeed() {
    return num($("brown-hold") && $("brown-hold").value, 20);
  }

  function oddsBoard(pool) {
    const which = pool || (state.tableSource === "place" ? "place" : "win");
    return pivotOdds(state.odds, currentThreshold(), which);
  }

  function setSourceChip(id) {
    ["src-win", "src-place", "src-results"].forEach((chip) => {
      if ($(chip)) $(chip).classList.toggle("chip-on", chip === id);
    });
  }

  function showGuide(kind) {
    state.guideKind = kind === "pipeline" ? "pipeline" : "user";
    const userBtn = $("guide-user");
    const pipeBtn = $("guide-pipeline");
    const userPanel = $("guide-panel-user");
    const pipePanel = $("guide-panel-pipeline");
    if (userBtn) {
      userBtn.classList.toggle("chip-on", state.guideKind === "user");
      userBtn.classList.toggle("text-slate-400", state.guideKind !== "user");
    }
    if (pipeBtn) {
      pipeBtn.classList.toggle("chip-on", state.guideKind === "pipeline");
      pipeBtn.classList.toggle("text-slate-400", state.guideKind !== "pipeline");
    }
    if (userPanel) userPanel.classList.toggle("hidden", state.guideKind !== "user");
    if (pipePanel) pipePanel.classList.toggle("hidden", state.guideKind !== "pipeline");
  }
  window.HKJCDesk = { showGuide };

  function tickClock() {
    const now = new Date();
    $("hk-clock").textContent = formatHk(now);
    $("hk-weekday").textContent = `星期${weekdayZh(now)} · Asia/Hong_Kong`;
    renderLiveBadge();
  }

  function showTab(id) {
    state.tab = id;
    document.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.classList.toggle("nav-active", btn.getAttribute("data-tab") === id);
    });
    document.querySelectorAll("[data-panel]").forEach((panel) => {
      panel.classList.toggle("hidden", panel.getAttribute("data-panel") !== id);
    });
    if (id === "strategy" || id === "monte") runStrategy();
    if (id === "data") renderDataTable();
    if (id === "status") refreshStatus();
    if (id === "guide") showGuide(state.guideKind || "user");
  }

  async function loadAll() {
    const g = state.github;
    try {
      const [cfgText, oddsText, resText, statusText, logText, originText, tickText] = await Promise.all([
        loadRelativeOrRaw(g, "./config.json", "config.json").catch(() => "{}"),
        loadRelativeOrRaw(g, "./data/odds_snapshots.csv", "data/odds_snapshots.csv"),
        loadRelativeOrRaw(g, "./data/race_results.csv", "data/race_results.csv"),
        loadRelativeOrRaw(g, "./status.json", "status.json").catch(() => "{}"),
        loadRelativeOrRaw(g, "./logs/latest.log", "logs/latest.log").catch(() => ""),
        loadRelativeOrRaw(g, "./data/dataset_origin.json", "data/dataset_origin.json").catch(() => '{"origin":"demo"}'),
        loadRelativeOrRaw(g, "./data/odds_ticks.csv", "data/odds_ticks.csv").catch(() => ""),
      ]);
      state.config = JSON.parse(cfgText || "{}");
      state.odds = parseCsv(oddsText);
      state.results = parseCsv(resText);
      state.ticks = tickText ? parseCsv(tickText) : [];
      state.status = JSON.parse(statusText || "{}");
      state.logText = logText;
      try {
        state.dataOrigin = JSON.parse(originText || "{}").origin || "demo";
      } catch {
        state.dataOrigin = "demo";
      }
      hydrateForms();
      fillFilterOptions();
      renderDataTable();
      renderSpAudit();
      renderHorseAudit();
      renderStatus();
      runStrategy();
      renderDataOrigin();
      const live = state.dataOrigin === "live";
      toast(
        live
          ? `已載入真實馬會數據：${oddsBoard().length} 匹馬賠率走勢、賽果 ${state.results.length} 列（示範已刪）`
          : `已載入 ${oddsBoard().length} 匹馬賠率走勢、賽果 ${state.results.length} 列（而家仲係示範假數據；第一次真實 crawl 會刪晒）`,
        "ok"
      );
    } catch (err) {
      toast(err.message || String(err), "error");
    }
  }

  function hydrateForms() {
    const c = state.config || {};
    const d = c.data || {};
    const s = c.strategy || {};
    const m = c.monte_carlo || {};
    const t = c.telegram || {};
    const gh = c.github || {};
    if (!state.github.owner && gh.owner) state.github.owner = gh.owner;
    if (!state.github.repo && gh.repo) state.github.repo = gh.repo;
    $("brown-threshold").value = d.brown_grid_drop_pct ?? 50;
    $("brown-threshold-val").textContent = `${$("brown-threshold").value}%`;
    if ($("brown-hold")) $("brown-hold").value = d.brown_hold_seconds ?? 20;
    $("scrape-interval").value = d.scrape_interval_seconds ?? 10;
    $("min-odds").value = s.min_odds ?? 3.5;
    $("max-odds").value = s.max_odds ?? 9.0;
    $("min-odds-val").textContent = Number($("min-odds").value).toFixed(1);
    $("max-odds-val").textContent = Number($("max-odds").value).toFixed(1);
    $("bet-type").value = s.bet_type || "win";
    $("checkpoint").value = s.checkpoint || "T-1";
    $("mc-bankroll").value = m.initial_bankroll ?? 10000;
    $("mc-stake").value = m.stake ?? 10;
    $("mc-days").value = m.race_days_per_year ?? 88;
    $("mc-sims").value = m.simulations ?? 1000;
    $("tg-enabled").checked = !!t.enabled;
    $("tg-chat").value = t.chat_id || "";
    $("tg-token").value = t.bot_token || "";
    $("tg-bet-type").value = t.bet_type || s.bet_type || "win";
    $("tg-checkpoint").value = t.checkpoint || s.checkpoint || "T-1";
    $("tg-min-odds").value = t.min_odds ?? 3.5;
    $("tg-max-odds").value = t.max_odds ?? 9.0;
    $("tg-drop").value = t.min_drop_pct ?? d.brown_grid_drop_pct ?? 50;
    if (typeof renderTelegramPreview === "function") renderTelegramPreview();
    $("gh-owner").value = state.github.owner || "";
    $("gh-repo").value = state.github.repo || "";
    $("gh-branch").value = state.github.branch || "main";
    $("gh-token").value = state.github.token || "";
    updateGhBadge();
  }

  function renderDataOrigin() {
    const el = $("data-origin-banner");
    if (!el) return;
    const live = state.dataOrigin === "live";
    el.className = live
      ? "rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100"
      : "rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100";
    const overlay = " 即時欄由你部機直接問馬會 GraphQL（CORS *，約 4 秒一轉），唔使等 git push。時間點／走勢 CSV 仍然約 2 分鐘先上 GitHub Pages。";
    el.textContent = (live
      ? "數據來源：真實馬會紀錄。示範假數據已喺第一次成功 crawl 時全部刪除，策略回測只用真實場次。"
      : "數據來源：示範假數據。等星期三（或任何真賽日）第一次抄到馬會賠率／賽果，就會自動刪晒呢批示範，之後只顯示真實紀錄。") + overlay;
  }

  function updateGhBadge() {
    const ok = !!(state.github.owner && state.github.repo && state.github.token);
    $("gh-badge").textContent = ok ? "GitHub 已授權" : "未授權寫入";
    $("gh-badge").className =
      "rounded-full px-3 py-1 text-xs font-medium " +
      (ok ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-200");
  }

  function fillFilterOptions() {
    const rows = (state.odds || []).concat(state.liveRows || []);
    const dates = [...new Set(rows.map((r) => r.race_date).filter(Boolean))].sort().reverse();
    const races = [...new Set(rows.map((r) => String(r.race_no)).filter(Boolean))].sort(
      (a, b) => Number(a) - Number(b)
    );
    setOptions($("filter-date"), dates, "全部日期");
    setOptions($("filter-race"), races, "全部場次");
  }

  function setOptions(select, values, allLabel) {
    const current = select.value;
    select.innerHTML = `<option value="">${allLabel}</option>` +
      values.map((v) => `<option value="${v}">${v}</option>`).join("");
    if ([...select.options].some((o) => o.value === current)) select.value = current;
  }

  function normId(value) {
    const n = parseInt(String(value == null ? "" : value).trim(), 10);
    return Number.isFinite(n) ? String(n) : String(value == null ? "" : value).trim();
  }

  function horseKey(row) {
    return [
      String(row.race_date || "").trim(),
      String(row.venue || "").trim().toUpperCase(),
      normId(row.race_no),
      normId(row.horse_no),
    ].join("|");
  }

  function winBrownLookup() {
    const map = new Map();
    const threshold = currentThreshold();
    for (const row of state.odds || []) {
      const key = horseKey(row);
      const prev = map.get(key) || { any: false, t1: false };
      const brown = officialBrown(row, threshold);
      if (brown) prev.any = true;
      if (brown && String(row.checkpoint || "").toUpperCase() === "T-1") prev.t1 = true;
      map.set(key, prev);
    }
    for (const row of oddsBoard("win")) {
      const key = horseKey(row);
      const prev = map.get(key) || { any: false, t1: false };
      if (isTrue(row.is_brown_grid) || row.brown_at) prev.any = true;
      if (isTrue(row.brown_t1)) prev.t1 = true;
      map.set(key, prev);
    }
    return map;
  }

  function liveGridOf(row) {
    return window.HKJCEngine.parseHkjcGrid(row && row.live_grid);
  }

  function brownFlags(row, lookup) {
    if (state.tableSource !== "results") {
      return {
        any: isTrue(row.is_brown_grid) || !!row.brown_at || liveGridOf(row) === "brown",
        t1: isTrue(row.brown_t1),
      };
    }
    if (!lookup) return { any: false, t1: false };
    return lookup.get(horseKey(row)) || { any: false, t1: false };
  }

  function strategyFilterOn() {
    return !!( $("filter-strategy") && $("filter-strategy").checked );
  }

  function strategyParams() {
    const minOdds = num($("min-odds") && $("min-odds").value, 3.5);
    const maxOdds = num($("max-odds") && $("max-odds").value, 9.0);
    return {
      minOdds: Math.min(minOdds, maxOdds),
      maxOdds: Math.max(minOdds, maxOdds),
      checkpoint: ($("checkpoint") && $("checkpoint").value) || "T-1",
      threshold: currentThreshold(),
      holdNeed: currentHoldNeed(),
    };
  }

  function strategySettingLabel() {
    const p = strategyParams();
    const when =
      ($("checkpoint") && $("checkpoint").selectedOptions[0] && $("checkpoint").selectedOptions[0].text) ||
      p.checkpoint;
    const hold = p.holdNeed > 0 ? `持續 ≥ ${p.holdNeed}s` : "當刻啡格";
    return `${when} · 獨贏 ${p.minOdds.toFixed(1)}–${p.maxOdds.toFixed(1)} · 馬會啡格 ${hold}`;
  }

  function strategyMatchKeys() {
    const p = strategyParams();
    return new Set(
      triggers(state.odds, p.minOdds, p.maxOdds, p.threshold, p.checkpoint, p.holdNeed).map(horseKey)
    );
  }

  function strategyLegendNote() {
    if (!strategyFilterOn()) return "";
    return (
      `「只看符合策略」跟<strong class="text-gold-300">策略回測</strong>頁同一套揀馬：` +
      `${strategySettingLabel()}。投注方法（獨贏／位置）唔影響顯示邊啲馬。`
    );
  }

  function updateStrategyFilterHint() {
    const hint = $("filter-strategy-hint");
    if (hint) hint.textContent = "跟策略回測：" + strategySettingLabel();
    const box = $("filter-strategy");
    const label = box && box.closest("label");
    if (label) {
      label.classList.toggle("border-gold-500/80", strategyFilterOn());
      label.classList.toggle("bg-gold-500/20", strategyFilterOn());
    }
  }

  function refreshStrategyFilterTable() {
    if (strategyFilterOn()) {
      state.page = 1;
      renderDataTable();
      return;
    }
    updateStrategyFilterHint();
  }

  function filteredRows() {
    const date = $("filter-date") ? $("filter-date").value : "";
    const venue = $("filter-venue") ? $("filter-venue").value : "";
    const race = $("filter-race") ? $("filter-race").value : "";
    const horse = $("filter-horse") ? $("filter-horse").value.trim() : "";
    const brown = !!( $("filter-brown") && $("filter-brown").checked );
    const brownT1 = !!( $("filter-brown-t1") && $("filter-brown-t1").checked );
    const strategyOnly = strategyFilterOn();
    const src = state.tableSource === "results" ? state.results : withLiveOdds(oddsBoard(state.tableSource));
    const lookup = brown || brownT1 ? winBrownLookup() : null;
    const strategyKeys = strategyOnly ? strategyMatchKeys() : null;
    return src.filter((row) => {
      if (date && row.race_date !== date) return false;
      if (venue && String(row.venue).toUpperCase() !== venue.toUpperCase()) return false;
      if (race && normId(row.race_no) !== normId(race)) return false;
      if (horse && normId(row.horse_no) !== normId(horse)) return false;
      if (brownT1 || brown) {
        const flags = brownFlags(row, lookup);
        if (brownT1 && !flags.t1) return false;
        if (brown && !brownT1 && !flags.any) return false;
      }
      if (strategyOnly && !strategyKeys.has(horseKey(row))) return false;
      return true;
    });
  }

  function fmtOdds(v) {
    if (v === "" || v == null || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(1);
  }

  function gridLabel(value) {
    const grid = window.HKJCEngine.parseHkjcGrid(value);
    if (grid === "brown") return "啡";
    return "—";
  }

  function gridCellClass(value, brownFlag) {
    const grid = window.HKJCEngine.parseHkjcGrid(value);
    if (grid === "brown") return "cell-brown";
    return brownFlag ? "cell-brown" : "";
  }

  function horseKey(row) {
    return [row.race_date, row.venue, String(row.race_no), String(row.horse_no)].join("|");
  }

  function renderSpAudit() {
    const el = $("sp-audit-banner");
    if (!el) return;
    const date = $("filter-date") ? $("filter-date").value : "";
    const t0 = {};
    state.odds.forEach((row) => {
      if (String(row.checkpoint || "").toUpperCase() !== "T-0") return;
      if (date && row.race_date !== date) return;
      t0[horseKey(row)] = Number(row.win_odds);
    });
    const gaps = [];
    state.results.forEach((row) => {
      if (date && row.race_date !== date) return;
      const sp = Number(row.final_sp);
      const live = t0[horseKey(row)];
      if (!Number.isFinite(sp) || sp <= 0 || !Number.isFinite(live) || live <= 0) return;
      const pct = Math.abs(live - sp) / sp * 100;
      if (pct >= 10) {
        gaps.push(`${row.horse_name || row.horse_no} 第${row.race_no}場 T-0 ${live} vs 終賠 ${sp}`);
      }
    });
    if (!Object.keys(t0).length) {
      el.textContent = "撳表入面一隻馬可以核對時間點。馬會冇公開走勢，系統會自己存 10 秒路徑；終賠用來教開跑格。";
      return;
    }
    if (!gaps.length) {
      el.textContent = (date ? date + "：" : "") + "開跑格同官方終賠相差都 < 10%。撳一隻馬睇時間點同 10 秒走勢。";
      return;
    }
    el.textContent = `開跑格同官方終賠差 ≥ 10%（${gaps.length} 隻）：` + gaps.slice(0, 6).join("；") +
      (gaps.length > 6 ? "…" : "") + "。撳馬可以人手更正。";
  }

  function renderHorseAudit() {
    const box = $("horse-audit");
    if (!box) return;
    const key = state.inspect;
    if (!key) {
      box.classList.add("hidden");
      if (state.pathChart) {
        state.pathChart.destroy();
        state.pathChart = null;
      }
      return;
    }
    box.classList.remove("hidden");
    const snaps = state.odds.filter((row) => horseKey(row) === key);
    const result = state.results.find((row) => horseKey(row) === key) || {};
    const ticks = (state.ticks || []).filter((row) => horseKey(row) === key)
      .sort((a, b) => String(a.capture_timestamp).localeCompare(String(b.capture_timestamp)));
    const sample = snaps[0] || result;
    $("horse-audit-title").textContent = sample
      ? `${sample.race_date || ""} ${venueName(sample.venue)} 第 ${sample.race_no} 場  ${sample.horse_no}. ${sample.horse_name || ""}`
      : key;
    const t0 = snaps.find((row) => String(row.checkpoint).toUpperCase() === "T-0");
    const sp = Number(result.final_sp);
    const live = t0 ? Number(t0.win_odds) : NaN;
    let spLine = result.final_sp ? `官方終賠 ${fmtOdds(result.final_sp)} · 獨贏派彩 ${result.win_dividend || "—"} · 位置 ${result.placedividend || "—"}` : "未有官方賽果／終賠";
    if (Number.isFinite(sp) && Number.isFinite(live) && sp > 0) {
      const pct = ((live - sp) / sp * 100);
      spLine += ` · T-0 ${fmtOdds(live)}（${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%）`;
    }
    $("horse-audit-sp").textContent = spLine;
    const order = ["T-15", "T-10", "T-5", "T-1", "T-0"];
    const byCp = {};
    snaps.forEach((row) => { byCp[String(row.checkpoint).toUpperCase()] = row; });
    $("horse-audit-cps").innerHTML =
      `<table class="grid-table text-xs"><thead><tr><th>時間點</th><th>獨贏</th><th>對上</th><th>格</th><th>位置</th><th>抄低時間</th><th>距開跑(分)</th></tr></thead><tbody>` +
      order.map((cp, i) => {
        const row = byCp[cp];
        if (!row) return `<tr><td>${cp}</td><td colspan="6" class="text-slate-500">未抄到</td></tr>`;
        const prev = i ? byCp[order[i - 1]] : null;
        return `<tr><td>${cp}</td><td class="${gridCellClass(row.hkjc_grid)}">${fmtOdds(row.win_odds)}</td><td class="mono">${oddsMoveLabel(prev && prev.win_odds, row.win_odds)}</td><td class="${gridCellClass(row.hkjc_grid)}">${gridLabel(row.hkjc_grid)}</td><td>${fmtOdds(row.place_odds)}</td><td class="mono">${row.capture_timestamp || "—"}</td><td class="mono">${row.minutes_to_post || "—"}</td></tr>`;
      }).join("") + "</tbody></table>";
    const holdEl = $("horse-audit-hold");
    if (holdEl) holdEl.textContent = holdSummary(byCp);
    const pathEl = $("horse-audit-path");
    if (pathEl) pathEl.textContent = pathStats(ticks);
    drawHorsePath(ticks, byCp);
    if (!ticks.length) {
      $("horse-audit-ticks").innerHTML = `<p class="text-[11px] text-slate-500">呢日未有 10 秒走勢（舊數據只得 5 個時間點）。下一個賽日起會開始存，你就唔使盯盤。</p>`;
    } else {
      const changes = tickChangeRows(ticks);
      $("horse-audit-ticks").innerHTML =
        `<p class="mb-1 text-[11px] text-slate-500">10 秒路徑：只列出獨贏／位置／格色有變嘅 ${changes.length} / ${ticks.length} 下（中間冇變即係投注盤當時真係同一個價，唔係抄重）。</p>` +
        `<table class="grid-table text-xs"><thead><tr><th>時間</th><th>距開跑</th><th>獨贏</th><th>格</th><th>位置</th></tr></thead><tbody>` +
        changes.map((row) => `<tr><td class="mono">${row.capture_timestamp}</td><td class="mono">${row.minutes_to_post}</td><td class="${gridCellClass(row.hkjc_grid)}">${fmtOdds(row.win_odds)}</td><td class="${gridCellClass(row.hkjc_grid)}">${gridLabel(row.hkjc_grid)}</td><td>${fmtOdds(row.place_odds)}</td></tr>`).join("") +
        "</tbody></table>";
    }
  }

  function gridStroke(grid) {
    if (grid === "brown") return "#d97706";
    return "#e4c36a";
  }

  function oddsMoveLabel(from, to) {
    const a = num(from, NaN);
    const b = num(to, NaN);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0) return "—";
    if (a === b) return "＝";
    const pct = (a - b) / a * 100;
    const arrow = pct > 0 ? "↓" : "↑";
    return `${arrow}${Math.abs(pct).toFixed(1)}%`;
  }

  function pathStats(ticks) {
    if (!ticks || !ticks.length) return "";
    const odds = ticks.map((row) => num(row.win_odds, NaN)).filter(Number.isFinite);
    if (!odds.length) return "";
    const unique = [];
    odds.forEach((value) => {
      const key = value.toFixed(1);
      if (!unique.includes(key)) unique.push(key);
    });
    let changes = 0;
    let brown = 0;
    let brownSame = 0;
    ticks.forEach((row, i) => {
      const grid = window.HKJCEngine.parseHkjcGrid(row.hkjc_grid);
      const cur = num(row.win_odds, NaN);
      if (grid === "brown") {
        brown += 1;
        if (i > 0 && cur === num(ticks[i - 1].win_odds, NaN)) brownSame += 1;
      }
      if (i > 0 && cur !== num(ticks[i - 1].win_odds, NaN)) changes += 1;
    });
    const start = odds[0].toFixed(1);
    const end = odds[odds.length - 1].toFixed(1);
    const lo = Math.min(...odds).toFixed(1);
    const hi = Math.max(...odds).toFixed(1);
    let text = `${ticks.length} 下（約 10 秒一格）· 獨贏 ${start}→${end}（區間 ${lo}–${hi}，${unique.length} 個價）· 變盤 ${changes} 次 · 官方啡格 ${brown} 下`;
    if (brownSame) text += `（其中 ${brownSame} 下賠率冇郁都繼續啡）`;
    text += "。馬會獨贏多數只出到 1 個位小數，熱門可以幾分鐘同一個價，圖上會長橫線。";
    return text;
  }

  function tickChangeRows(ticks) {
    const out = [];
    (ticks || []).forEach((row, i) => {
      if (!i) {
        out.push(row);
        return;
      }
      const prev = ticks[i - 1];
      const sameOdds = String(row.win_odds) === String(prev.win_odds)
        && String(row.place_odds) === String(prev.place_odds);
      const sameGrid = window.HKJCEngine.parseHkjcGrid(row.hkjc_grid)
        === window.HKJCEngine.parseHkjcGrid(prev.hkjc_grid);
      if (!sameOdds || !sameGrid) out.push(row);
    });
    const last = ticks && ticks[ticks.length - 1];
    if (last && out[out.length - 1] !== last) out.push(last);
    return out;
  }

  function holdSummary(byCp) {
    const t1 = byCp && byCp["T-1"];
    const t15 = byCp && byCp["T-15"];
    const t5 = byCp && byCp["T-5"];
    const need = currentHoldNeed();
    if (!t1) return "未有開賽前 1 分鐘紀錄。通知／策略只睇你揀嘅時間點當刻格色，再加連續秒數。";
    const grid = window.HKJCEngine.parseHkjcGrid(t1.hkjc_grid);
    const hold = num(t1.brown_hold_seconds, NaN);
    const heldTxt = Number.isFinite(hold) ? `連續 ${hold} 秒` : "舊數據冇 10 秒路徑，唔知持續幾耐";
    const from15 = t15 ? `開賽前 15 分鐘 ${fmtOdds(t15.win_odds)} → 開賽前 1 分鐘 ${fmtOdds(t1.win_odds)}（${oddsMoveLabel(t15.win_odds, t1.win_odds)}）` : `開賽前 1 分鐘 ${fmtOdds(t1.win_odds)}`;
    const from5 = t5 ? `；對上一個時間點開賽前 5 分鐘 ${fmtOdds(t5.win_odds)}（${oddsMoveLabel(t5.win_odds, t1.win_odds)}）` : "";
    if (grid === "brown") {
      const flash = Number.isFinite(hold) && need > 0 && hold < need;
      const signal = !Number.isFinite(hold)
        ? `開賽前 1 分鐘投注盤顯示啡格（${heldTxt}）`
        : (flash
          ? `開賽前 1 分鐘投注盤顯示啡格，但只係 ${heldTxt}（門檻 ${need}s）→ 當閃過，唔發通知`
          : `開賽前 1 分鐘投注盤顯示啡格，${heldTxt}（門檻 ${need}s）→ 會當訊號`);
      return `${from15}${from5}。${signal}。馬會啡格可以只係跌 0.1 都繼續標，唔等於急跌一半。`;
    }
    return `${from15}${from5}。開賽前 1 分鐘投注盤冇啡格。紅格／綠格唔會存。之前閃過啡格都唔會通知，除非你揀嘅時間點當刻仍然係啡格而且夠持續。`;
  }

  function drawHorsePath(ticks, byCp) {
    const wrap = $("horse-audit-chart-wrap");
    const canvas = $("horse-audit-chart");
    if (!wrap || !canvas || typeof Chart === "undefined") return;
    const tickPts = (ticks || [])
      .map((row) => ({
        x: num(row.minutes_to_post, NaN),
        y: num(row.win_odds, NaN),
        grid: window.HKJCEngine.parseHkjcGrid(row.hkjc_grid),
      }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
      .sort((a, b) => b.x - a.x);
    const cpMap = { "T-15": 15, "T-10": 10, "T-5": 5, "T-1": 1, "T-0": 0 };
    const cpPts = Object.keys(cpMap)
      .map((cp) => {
        const row = byCp[cp];
        if (!row) return null;
        const y = num(row.win_odds, NaN);
        if (!Number.isFinite(y)) return null;
        return { x: cpMap[cp], y, grid: window.HKJCEngine.parseHkjcGrid(row.hkjc_grid), label: cp };
      })
      .filter(Boolean);
    const series = tickPts.length ? tickPts : cpPts;
    if (!series.length) {
      wrap.classList.add("hidden");
      if (state.pathChart) {
        state.pathChart.destroy();
        state.pathChart = null;
      }
      return;
    }
    const changePts = series.filter((p, i) => {
      if (!i) return true;
      const prev = series[i - 1];
      return p.y !== prev.y || p.grid !== prev.grid;
    });
    const stair = [];
    series.forEach((p, i) => {
      if (i && series[i - 1].y !== p.y) {
        stair.push({ x: p.x, y: series[i - 1].y, grid: series[i - 1].grid });
      }
      stair.push(p);
    });
    wrap.classList.remove("hidden");
    if (state.pathChart) state.pathChart.destroy();
    state.pathChart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        datasets: [
          {
            label: tickPts.length ? "獨贏（10 秒，階梯）" : "獨贏（時間點）",
            data: stair,
            parsing: false,
            borderColor: "rgba(228,195,106,0.85)",
            backgroundColor: "transparent",
            tension: 0,
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: 2,
          },
          {
            label: "變盤／啡格",
            data: changePts,
            parsing: false,
            showLine: false,
            pointRadius: changePts.map((p) => (p.grid === "brown" ? 5 : 3)),
            pointHoverRadius: 7,
            pointBackgroundColor: changePts.map((p) => gridStroke(p.grid)),
            pointBorderColor: changePts.map((p) => gridStroke(p.grid)),
          },
          {
            label: "時間點",
            data: cpPts,
            parsing: false,
            showLine: false,
            pointRadius: 6,
            pointHoverRadius: 8,
            pointBackgroundColor: cpPts.map((p) => gridStroke(p.grid)),
            pointBorderColor: "#0b1220",
            pointBorderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { labels: { color: "#94a3b8", boxWidth: 12 } },
          tooltip: {
            callbacks: {
              title: (items) => {
                const p = items[0] && items[0].raw;
                if (!p) return "";
                return (p.label ? p.label + " · " : "") + "開跑前 " + Number(p.x).toFixed(2) + " 分鐘";
              },
              label: (item) => {
                const p = item.raw || {};
                const g = p.grid === "brown" ? "啡格" : "無啡格";
                return "獨贏 " + Number(p.y).toFixed(1) + " · " + g;
              },
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            reverse: true,
            title: { display: true, text: "距開跑（分鐘）", color: "#94a3b8" },
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          y: {
            title: { display: true, text: "獨贏賠率", color: "#94a3b8" },
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(255,255,255,0.06)" },
            grace: "12%",
          },
        },
      },
    });
  }

  function inspectHorse(row) {
    state.inspect = horseKey(row);
    renderHorseAudit();
    const box = $("horse-audit");
    if (box) box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function correctInspectedOdds() {
    if (!state.inspect) {
      toast("先撳表入面一隻馬", "error");
      return;
    }
    const checkpoint = ($("correct-checkpoint") && $("correct-checkpoint").value) || "T-1";
    const win = Number($("correct-win") && $("correct-win").value);
    if (!Number.isFinite(win) || win <= 0) {
      toast("請填正確獨贏賠率", "error");
      return;
    }
    persistGithubForm();
    if (!state.github.token) {
      toast("更正要喺狀態頁貼 PAT", "error");
      return;
    }
    const parts = state.inspect.split("|");
    const prevCp = { "T-10": "T-15", "T-5": "T-10", "T-1": "T-5", "T-0": "T-1" }[checkpoint];
    const prevRow = state.odds.find((row) => horseKey(row) === state.inspect && String(row.checkpoint).toUpperCase() === prevCp);
    const prevWin = prevRow ? Number(prevRow.win_odds) : NaN;
    const drop = Number.isFinite(prevWin) && prevWin > 0 ? Math.round((prevWin - win) / prevWin * 10000) / 100 : 0;
    const threshold = currentThreshold();
    let found = false;
    state.odds = state.odds.map((row) => {
      if (horseKey(row) !== state.inspect || String(row.checkpoint).toUpperCase() !== checkpoint) return row;
      found = true;
      const next = {
        ...row,
        win_odds: win,
        prev_win_odds: Number.isFinite(prevWin) ? prevWin : row.prev_win_odds,
        win_drop_pct: drop,
      };
      next.is_brown_grid = officialBrown(next, threshold) ? "true" : "false";
      return next;
    });
    if (!found) {
      toast("呢個時間點未有列可改", "error");
      return;
    }
    try {
      const csv = toCsv(state.odds, ODDS_SNAPSHOT_FIELDS);
      const message = `data: correct ${state.inspect} ${checkpoint} to ${win}`;
      await ghPutFile(state.github, "data/odds_snapshots.csv", csv, message);
      await ghPutFile(state.github, "docs/data/odds_snapshots.csv", csv, message);
      renderDataTable();
      renderHorseAudit();
      runStrategy();
      toast(`已把 ${checkpoint} 獨贏改成 ${win}`, "ok");
    } catch (err) {
      toast(err.message || String(err), "error");
    }
  }

  function withLiveOdds(rows) {
    const liveRows = state.liveRows || [];
    if (!liveRows.length) return rows;
    const out = (rows || []).map((row) => ({ ...row }));
    const map = new Map(out.map((row) => [horseKey(row), row]));
    const extras = [];
    for (const live of liveRows) {
      const key = horseKey(live);
      const existing = map.get(key);
      const odds = state.tableSource === "place" ? live.place_odds : live.win_odds;
      const grid = state.tableSource === "place" ? live.place_grid : live.hkjc_grid;
      if (existing) {
        existing.live_odds = odds;
        existing.live_grid = grid;
        continue;
      }
      const next = {
        race_date: live.race_date,
        venue: live.venue,
        race_no: live.race_no,
        scheduled_time: "",
        horse_no: live.horse_no,
        horse_name: live.horse_name,
        live_odds: odds,
        live_grid: grid,
        live_only: true,
        is_brown_grid: grid === "brown" ? "true" : "false",
        brown_at: grid === "brown" ? "即時" : "",
      };
      map.set(key, next);
      extras.push(next);
    }
    return extras.concat(out);
  }

  function renderDataTable() {
    let rows;
    try {
      rows = filteredRows();
    } catch (err) {
      toast(err.message || String(err), "error");
      return;
    }
    updateStrategyFilterHint();
    const pageSize = 80;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (state.page > pages) state.page = pages;
    const slice = rows.slice((state.page - 1) * pageSize, state.page * pageSize);
    if (state.tableSource === "results") {
      const brownOn = $("filter-brown").checked || ($("filter-brown-t1") && $("filter-brown-t1").checked);
      $("table-meta").textContent =
        `顯示 ${rows.length} / ${state.results.length} 列 · 第 ${state.page}/${pages} 頁` +
        (brownOn ? " · 啡格 filter 用獨贏急跌對應同一隻馬" : "") +
        (strategyFilterOn() ? ` · 符合策略 ${strategySettingLabel()}` : "");
      if ($("board-legend")) {
        $("board-legend").innerHTML =
          "呢張表係<strong class=\"text-slate-300\">官方賽果派彩</strong>。上面「只看啡格／只看開賽1分鐘前出現啡格／只看符合策略」同樣適用：用獨贏表嘅急跌同策略回測設定去篩選呢啲馬。" +
          (strategyLegendNote() ? " " + strategyLegendNote() : "");
      }
      const labels = {
        race_date: "日期",
        venue: "場地",
        race_no: "場次",
        horse_no: "馬號",
        horse_name: "馬名",
        finish_rank: "名次",
        final_sp: "終賠",
        win_dividend: "獨贏派彩",
        placedividend: "位置派彩",
      };
      $("data-head").innerHTML =
        "<tr>" + RESULT_FIELDS.map((f) => `<th>${labels[f] || f}</th>`).join("") + "</tr>";
      if (!slice.length) {
        $("data-body").innerHTML =
          `<tr><td colspan="${RESULT_FIELDS.length}" class="text-slate-500">呢個 filter 之下冇賽果。啡格用獨贏急跌對同一隻馬；符合策略跟策略回測頁嘅時間點、獨贏範圍同啡格門檻。</td></tr>`;
      } else {
        $("data-body").innerHTML = slice
          .map((row) => {
            const tds = RESULT_FIELDS
              .map((f) => {
                let v = row[f];
                if (f === "venue") v = venueName(v);
                return `<td>${v == null || v === "" ? "—" : v}</td>`;
              })
              .join("");
            return `<tr class="cursor-pointer" data-horse-key="${horseKey(row)}">${tds}</tr>`;
          })
          .join("");
      }
    } else {
      const poolName = state.tableSource === "place" ? "位置賠率" : "獨贏賠率";
      const liveNote = state.liveFetchedAt
        ? ` · 即時 ${liveAgeLabel()}`
        : (state.liveError ? ` · 即時 ${state.liveError}` : "");
      $("table-meta").textContent =
        `顯示 ${rows.length} 匹馬 · ${poolName} · 第 ${state.page}/${pages} 頁 · 只標馬會啡格` +
        liveNote +
        (strategyFilterOn() ? ` · 符合策略 ${strategySettingLabel()}` : "");
      if ($("board-legend")) {
        const base =
          state.tableSource === "place"
            ? "呢張表淨係<strong class=\"text-slate-300\">位置賠率</strong>（馬會 PLA 彩池）。只標<strong class=\"text-amber-200\">啡格</strong>；紅／綠唔存。即時欄由瀏覽器直接問馬會 GraphQL（約 4 秒），唔經 git。啡格可以只係跌 0.1。"
            : "呢張表淨係<strong class=\"text-slate-300\">獨贏賠率</strong>（馬會 WIN 彩池）。只標<strong class=\"text-amber-200\">啡格</strong>（標記 3）；紅／綠當無色。啡格＝投注盤當時標咗，<strong class=\"text-slate-300\">可以只係 2.8→2.6</strong>，唔等於急跌一半。時間點下面嘅 % 係對上一個時間點。熱門多數幾分鐘同一個價，走勢圖會長橫線。";
        const note = strategyLegendNote();
        $("board-legend").innerHTML = note ? base + " " + note : base;
      }
      const oddsColspan = 7 + ODDS_BOARD_COLS.length + 1;
      $("data-head").innerHTML = `<tr>
        <th>日期</th><th>場地</th><th>場次</th><th>開跑</th><th>馬號</th><th>馬名</th>
        <th>即時</th>
        ${ODDS_BOARD_COLS.map((c) => `<th>${c.label}</th>`).join("")}
        <th>啡格時間點</th>
      </tr>`;
      if (!slice.length) {
        $("data-body").innerHTML =
          `<tr><td colspan="${oddsColspan}" class="text-slate-500">呢個 filter 之下冇馬。符合策略 = 策略回測頁揀嘅時間點出現獨贏啡格，而且嗰刻獨贏喺範圍內。</td></tr>`;
      } else {
        $("data-body").innerHTML = slice
          .map((row) => {
            const liveTd = `<td class="${gridCellClass(row.live_grid)}">${row.live_odds == null || row.live_odds === "" ? "—" : fmtOdds(row.live_odds)}</td>`;
            const cells = ODDS_BOARD_COLS.map((c, i) => {
              const brown = c.brownKey && isTrue(row[c.brownKey]);
              const prev = i ? ODDS_BOARD_COLS[i - 1] : null;
              const move = prev ? oddsMoveLabel(row[prev.key], row[c.key]) : "";
              const note = move && move !== "—" && move !== "＝"
                ? `<div class="text-[10px] leading-tight opacity-80">${move}</div>`
                : "";
              return `<td class="${gridCellClass(row[c.gridKey], brown)}">${fmtOdds(row[c.key])}${note}</td>`;
            }).join("");
            const flag = row.brown_at
              ? `<td class="cell-brown">${row.brown_at}</td>`
              : `<td>—</td>`;
            return `<tr class="cursor-pointer" data-horse-key="${horseKey(row)}">
              <td>${row.race_date}</td>
              <td>${venueName(row.venue)}</td>
              <td>${row.race_no}</td>
              <td>${row.scheduled_time || "—"}</td>
              <td>${row.horse_no}</td>
              <td>${row.horse_name || "—"}</td>
              ${liveTd}${cells}${flag}
            </tr>`;
          })
          .join("");
      }
    }
    $("page-indicator").textContent = `${state.page} / ${pages}`;
    renderSpAudit();
    if (state.inspect) renderHorseAudit();
  }

  function fmtSignedMoney(n) {
    const v = Math.round(Number(n) || 0);
    const abs = Math.abs(v).toLocaleString("en-US");
    if (v > 0) return "+$" + abs;
    if (v < 0) return "-$" + abs;
    return "$0";
  }

  function kpi(id, label, value, sub, tone) {
    const toneClass =
      tone === "up" ? "text-emerald-300" : tone === "down" ? "text-rose-300" : "text-gold-300";
    return `<article class="kpi-card">
      <p class="text-[11px] uppercase tracking-[0.18em] text-slate-500">${label}</p>
      <p class="mt-2 font-mono text-2xl ${toneClass}">${value}</p>
      <p class="mt-1 text-xs text-slate-500">${sub || ""}</p>
    </article>`;
  }

  function runStrategy() {
    if (!state.odds.length) return;
    const minOdds = num($("min-odds").value, 3.5);
    const maxOdds = num($("max-odds").value, 9.0);
    const betType = $("bet-type").value;
    const checkpoint = $("checkpoint").value || "T-1";
    const bt = evaluate(state.odds, state.results, {
      minOdds: Math.min(minOdds, maxOdds),
      maxOdds: Math.max(minOdds, maxOdds),
      betType,
      checkpoint,
      stake: 10,
      threshold: currentThreshold(),
      holdNeed: currentHoldNeed(),
    });
    state.backtest = bt;
    const tone = bt.roi >= 0 ? "up" : "down";
    const whenLabel = ($("checkpoint").selectedOptions[0] && $("checkpoint").selectedOptions[0].text) || checkpoint;
    const perDay = Number(bt.triggers_per_race_day || 0);
    const raceDays = Number(bt.race_days || 0);
    $("bt-kpis").innerHTML = [
      kpi("t", "總觸發次數", bt.triggers, `${whenLabel} 啡格 ∩ 賠率範圍`),
      kpi(
        "f",
        "策略頻率",
        perDay.toFixed(1) + " 注／賽馬日",
        `覆蓋 ${raceDays} 個賽馬日 · 總觸發 ÷ 樣本日數`
      ),
      kpi("w", "策略勝率", bt.win_rate.toFixed(2) + "%", `${bt.hits} 次命中`),
      kpi("p", "平均命中派彩賠率", bt.avg_payout_odds.toFixed(2), "中獎注的 dividend / $10"),
      kpi("s", "總投入本金", "$" + bt.staked.toFixed(0), "每注 $10"),
      kpi("n", "淨盈虧", (bt.pnl >= 0 ? "+" : "") + bt.pnl.toFixed(0), "含本金回收"),
      kpi("r", "EV / ROI", bt.roi.toFixed(2) + "%", "淨盈虧 ÷ 本金", tone),
    ].join("");
    const trades = bt.trades.slice(-80).reverse();
    $("trade-body").innerHTML = trades
      .map((t) => {
        const cls = t.hit ? "text-emerald-300" : "text-rose-300";
        return `<tr>
          <td>${t.race_date}</td><td>${venueName(t.venue)}</td><td>${t.race_no}</td>
          <td>${t.horse_no} ${t.horse_name || ""}</td>
          <td>${t.checkpoint}</td><td>${Number(t.win_odds).toFixed(1)}</td>
          <td>${Number(t.win_drop_pct).toFixed(1)}%</td>
          <td>${t.finish_rank || "—"}</td>
          <td class="${cls}">${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(0)}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="9" class="text-slate-500">此參數組合沒有觸發注。</td></tr>`;
    runMonteCarlo();
  }

  function runMonteCarlo() {
    const bt = state.backtest;
    if (!bt || !bt.trades.length) {
      if ($("mc-year-bets")) $("mc-year-bets").textContent = "每年預計落注場次：—（呢組參數未有觸發注）";
      $("mc-kpis").innerHTML = kpi("x", "需要回測注", "—", "先讓策略產生觸發");
      if (state.chart) {
        state.chart.destroy();
        state.chart = null;
      }
      return;
    }
    const days = Math.max(1, Math.floor(num($("mc-days").value, 88)));
    const freq = Number(bt.triggers_per_race_day || 0);
    const races = yearlyBets(freq, days);
    if ($("mc-year-bets")) {
      $("mc-year-bets").innerHTML =
        `每年預計落注場次：<span class="font-mono text-gold-300">${races}</span> 注` +
        `　（頻率 ${freq.toFixed(1)} 注／賽馬日 × ${days} 個賽馬日）`;
    }
    const mcStake = num($("mc-stake").value, 10);
    const mc = monteCarlo(bt.trades, {
      bankroll: num($("mc-bankroll").value, 10000),
      stake: mcStake,
      unitStake: 10,
      races: Math.max(1, races),
      sims: num($("mc-sims").value, 1000),
    });
    state.mc = mc;
    const pnl = Math.round(mc.expected_pnl);
    const pct = Number(mc.expected_roi || 0);
    const dollar = fmtSignedMoney(mc.expected_pnl);
    const pctTxt = (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
    const scale = Number(mc.scale || mcStake / 10);
    $("mc-kpis").innerHTML = [
      kpi(
        "e",
        "預期年化回報",
        `${dollar}  ·  ${pctTxt}`,
        `金額按每注 $${Math.round(mcStake).toLocaleString("en-US")}（${scale.toLocaleString("en-US")} 張 $10 票）放大；% 相對本金。期末 $${Math.round(mc.expected_final).toLocaleString("en-US")} · ${mc.races} 注／年`,
        pnl >= 0 ? "up" : "down"
      ),
      kpi("d", "最大回撤 MDD", (mc.mdd_median * 100).toFixed(1) + "%", `P95 ${(mc.mdd_p95 * 100).toFixed(1)}%`, "down"),
      kpi("u", "破產概率", mc.ruin.toFixed(2) + "%", `${mc.sims} 次模擬下注`, mc.ruin > 5 ? "down" : "up"),
      kpi("b", "P10–P90 期末", `$${Math.round(mc.p10_final)} – $${Math.round(mc.p90_final)}`, "資金分佈區間"),
    ].join("");
    drawChart(mc);
  }

  function drawChart(mc) {
    const ctx = $("mc-chart").getContext("2d");
    const labels = mc.bands.map((b) => b.x);
    if (state.chart) state.chart.destroy();
    state.chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "P90", data: mc.bands.map((b) => b.p90), borderColor: "rgba(228,195,106,0.35)", backgroundColor: "rgba(228,195,106,0.08)", fill: "+1", tension: 0.25, pointRadius: 0, borderWidth: 1 },
          { label: "P75", data: mc.bands.map((b) => b.p75), borderColor: "rgba(52,211,153,0.25)", backgroundColor: "rgba(52,211,153,0.10)", fill: "+1", tension: 0.25, pointRadius: 0, borderWidth: 1 },
          { label: "中位 P50", data: mc.bands.map((b) => b.p50), borderColor: "#e4c36a", backgroundColor: "transparent", fill: false, tension: 0.25, pointRadius: 0, borderWidth: 2 },
          { label: "P25", data: mc.bands.map((b) => b.p25), borderColor: "rgba(52,211,153,0.25)", backgroundColor: "rgba(244,63,94,0.08)", fill: "+1", tension: 0.25, pointRadius: 0, borderWidth: 1 },
          { label: "P10", data: mc.bands.map((b) => b.p10), borderColor: "rgba(244,63,94,0.35)", backgroundColor: "transparent", fill: false, tension: 0.25, pointRadius: 0, borderWidth: 1 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#94a3b8", boxWidth: 12 } },
          tooltip: {
            callbacks: {
              title: (items) => `第 ${items[0].label} 注`,
            },
          },
        },
        scales: {
          x: { ticks: { color: "#64748b", maxTicksLimit: 10 }, grid: { color: "rgba(255,255,255,0.04)" }, title: { display: true, text: "年度落注場次", color: "#64748b" } },
          y: { ticks: { color: "#64748b" }, grid: { color: "rgba(255,255,255,0.04)" }, title: { display: true, text: "資金 (HKD)", color: "#64748b" } },
        },
      },
    });
  }

  function renderStatus() {
    const s = state.status || {};
    const running = s.state === "running";
    $("sys-state").textContent = running ? "運行中" : s.state === "error" ? "錯誤" : "待機中";
    $("sys-state").className = "font-mono text-xl " + (running ? "text-emerald-300" : s.state === "error" ? "text-rose-300" : "text-gold-300");
    $("sys-races").textContent = (s.races_monitored_today && s.races_monitored_today.length)
      ? s.races_monitored_today.join(", ")
      : "—";
    $("sys-sync").textContent = s.last_sync || "—";
    $("sys-msg").textContent = s.last_message || "—";
    $("sys-venue").textContent = s.is_race_day ? venueName(s.venue) : "今日非香港賽馬日 / 待命";
    $("log-view").textContent = state.logText || "尚無日誌";
    $("log-view").scrollTop = $("log-view").scrollHeight;
  }

  async function refreshStatus() {
    renderStatus();
    if (!state.github.owner || !state.github.repo) return;
    try {
      const data = await ghLatestRun(state.github);
      const run = data.workflow_runs && data.workflow_runs[0];
      if (run) {
        const live = run.status === "in_progress" || run.status === "queued";
        $("gh-run").textContent = `${live ? "Actions 運行中" : "Actions 待機"} · ${run.conclusion || run.status}`;
        $("gh-run-link").href = run.html_url;
        $("gh-run-link").classList.remove("hidden");
        if (live) $("sys-state").textContent = "運行中";
      }
    } catch (err) {
      $("gh-run").textContent = err.message;
    }
  }

  function readUiConfig() {
    const cfg = JSON.parse(JSON.stringify(state.config || {}));
    cfg.timezone = "Asia/Hong_Kong";
    cfg.data = cfg.data || {};
    cfg.strategy = cfg.strategy || {};
    cfg.monte_carlo = cfg.monte_carlo || {};
    cfg.telegram = cfg.telegram || {};
    cfg.github = cfg.github || {};
    cfg.data.brown_grid_drop_pct = num($("brown-threshold").value, 50);
    cfg.data.brown_hold_seconds = num($("brown-hold") && $("brown-hold").value, 20);
    cfg.data.scrape_interval_seconds = num($("scrape-interval").value, 10);
    cfg.strategy.min_odds = num($("min-odds").value, 3.5);
    cfg.strategy.max_odds = num($("max-odds").value, 9.0);
    cfg.strategy.bet_type = $("bet-type").value;
    cfg.strategy.checkpoint = $("checkpoint").value || "T-1";
    cfg.monte_carlo.initial_bankroll = num($("mc-bankroll").value, 10000);
    cfg.monte_carlo.stake = num($("mc-stake").value, 10);
    cfg.monte_carlo.race_days_per_year = Math.max(1, Math.floor(num($("mc-days").value, 88)));
    cfg.monte_carlo.simulations = num($("mc-sims").value, 1000);
    const freq = state.backtest ? Number(state.backtest.triggers_per_race_day || 0) : 0;
    cfg.monte_carlo.races_per_year = yearlyBets(freq, cfg.monte_carlo.race_days_per_year);
    cfg.telegram.enabled = $("tg-enabled").checked;
    cfg.telegram.chat_id = $("tg-chat").value.trim();
    cfg.telegram.bet_type = $("tg-bet-type").value;
    cfg.telegram.checkpoint = $("tg-checkpoint").value || "T-1";
    cfg.telegram.min_odds = num($("tg-min-odds").value, 3.5);
    cfg.telegram.max_odds = num($("tg-max-odds").value, 9.0);
    cfg.telegram.min_drop_pct = num($("tg-drop").value, 50);
    cfg.telegram.bot_token = "";
    cfg.github.owner = $("gh-owner").value.trim();
    cfg.github.repo = $("gh-repo").value.trim();
    cfg.github.branch = $("gh-branch").value.trim() || "main";
    return cfg;
  }

  function persistGithubForm() {
    state.github = {
      owner: $("gh-owner").value.trim(),
      repo: $("gh-repo").value.trim(),
      branch: $("gh-branch").value.trim() || "main",
      token: $("gh-token").value.trim(),
    };
    saveRepo(state.github);
    updateGhBadge();
  }

  async function saveConfigRemote() {
    persistGithubForm();
    const cfg = readUiConfig();
    const text = JSON.stringify(cfg, null, 2) + "\n";
    try {
      await ghPutFile(state.github, "config.json", text, "config: update from Pages desk");
      await ghPutFile(state.github, "docs/config.json", text, "config: mirror for GitHub Pages");
      state.config = cfg;
      toast("config.json 已寫入 GitHub（Bot Token 不會提交）", "ok");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function purgeSelectedDate() {
    persistGithubForm();
    const date =
      ($("filter-date") && $("filter-date").value) ||
      ($("force-date") && $("force-date").value.trim()) ||
      "";
    if (!date) {
      toast("先喺表上面揀要刪嘅日期，或填「可選日期」", "error");
      return;
    }
    if (!state.github.token) {
      toast("刪除紀錄要喺狀態頁貼 PAT", "error");
      return;
    }
    const ok = window.confirm(
      `確定刪除 ${date} 全部賠率同賽果？策略回測會即時少呢一日。GitHub 舊 commit 仍可還原。`
    );
    if (!ok) return;
    const oddsKeep = state.odds.filter((row) => row.race_date !== date);
    const resKeep = state.results.filter((row) => row.race_date !== date);
    const removed = state.odds.length - oddsKeep.length + state.results.length - resKeep.length;
    if (!removed) {
      toast(`${date} 冇任何列可刪`, "info");
      return;
    }
    try {
      const oddsCsv = toCsv(oddsKeep, ODDS_SNAPSHOT_FIELDS);
      const resCsv = toCsv(resKeep, RESULT_FIELDS);
      const message = `data: drop ${date} records from Pages desk`;
      await ghPutFile(state.github, "data/odds_snapshots.csv", oddsCsv, message);
      await ghPutFile(state.github, "docs/data/odds_snapshots.csv", oddsCsv, message);
      await ghPutFile(state.github, "data/race_results.csv", resCsv, message);
      await ghPutFile(state.github, "docs/data/race_results.csv", resCsv, message);
      state.odds = oddsKeep;
      state.results = resKeep;
      fillFilterOptions();
      state.page = 1;
      renderDataTable();
      runStrategy();
      toast(`已刪 ${date}（${removed} 列）並寫入 GitHub`, "ok");
    } catch (err) {
      toast(err.message || String(err), "error");
    }
  }

  async function trigger(command) {
    persistGithubForm();
    try {
      await ghDispatch(state.github, command, $("force-date").value.trim());
      toast(`已觸發 GitHub Action：${command}`, "ok");
      setTimeout(refreshStatus, 2000);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function testTelegram() {
    persistGithubForm();
    const token = $("tg-token").value.trim();
    const chat = $("tg-chat").value.trim();
    if (token && chat) {
      try {
        const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chat,
            text: `✅ HKJC 量化平台測試訊息\n連線正常 · ${formatHk(new Date())} HKT`,
            parse_mode: "HTML",
          }),
        });
        if (res.ok) {
          toast("已直接呼叫 Telegram API 發送測試訊息", "ok");
          return;
        }
      } catch {
        /* CORS often blocks this; fall back to Actions */
      }
    }
    toast("瀏覽器可能被 Telegram CORS 擋下，改由 GitHub Actions 發送…");
    await saveConfigRemote().catch(() => {});
    await trigger("test-telegram");
  }

  function renderTelegramPreview() {
    const el = $("tg-preview");
    if (!el) return;
    const betLabels = { win: "只買獨贏", place: "只買位置", win_place: "獨贏 + 位置" };
    const bet = betLabels[$("tg-bet-type") && $("tg-bet-type").value] || "只買獨贏";
    const cp = ($("tg-checkpoint") && $("tg-checkpoint").value) || "T-1";
    const lo = Number(($("tg-min-odds") && $("tg-min-odds").value) || 3.5).toFixed(1);
    const hi = Number(($("tg-max-odds") && $("tg-max-odds").value) || 9.0).toFixed(1);
    const drop = Number(($("tg-drop") && $("tg-drop").value) || 50).toFixed(0);
    el.textContent =
      `🚨 落飛警報 · 🟤 啡格\n\n` +
      `📅 2026-11-15（日）沙田\n` +
      `🏁 第 5 場  開跑 15:20:00\n` +
      `🐴 7. 金程千里\n` +
      `📉 獨贏 8.4 → 3.8  (-54.8%)\n` +
      `📍 位置 1.9\n` +
      `🎯 ${bet} · ${cp}\n` +
      `⏰ ${cp}  ·  獨贏範圍 ${lo}–${hi}  ·  跌幅 ≥ ${drop}%`;
  }

  function hkDate() {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Hong_Kong",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  }

  function liveAgeLabel() {
    if (!state.liveFetchedAt) return "未連";
    const age = Math.max(0, Math.round((Date.now() - Date.parse(state.liveFetchedAt)) / 1000));
    return age < 2 ? "剛剛" : age + " 秒前";
  }

  function renderLiveBadge() {
    const el = $("live-badge");
    if (!el) return;
    if (state.liveError) {
      el.textContent = "即時 · " + state.liveError;
      el.className = "rounded-full bg-rose-500/15 px-3 py-1 text-xs text-rose-200";
      return;
    }
    if (state.liveRows && state.liveRows.length) {
      const raceNos = [...new Set(state.liveRows.map((r) => r.race_no))].join("/");
      el.textContent = `即時 第${raceNos}場 · ${liveAgeLabel()}`;
      el.className = "rounded-full bg-emerald-500/15 px-3 py-1 text-xs text-emerald-200";
      return;
    }
    el.textContent = "即時待機";
    el.className = "rounded-full bg-slate-500/20 px-3 py-1 text-xs text-slate-300";
  }

  function liveVenueGuess() {
    const st = state.status || {};
    if (st.venue) return String(st.venue).toUpperCase();
    const today = String(st.race_date || hkDate());
    const hit = (state.odds || []).find((row) => String(row.race_date) === today && row.venue);
    return hit ? String(hit.venue).toUpperCase() : "ST";
  }

  async function pollHkjcLive() {
    if (document.hidden) return;
    if (!window.HKJCLive || typeof window.HKJCLive.fetchLiveBoard !== "function") return;
    const st = state.status || {};
    const date = String(st.race_date || hkDate());
    try {
      let board = await window.HKJCLive.fetchLiveBoard(date, liveVenueGuess());
      if ((!board || !board.rows || !board.rows.length) && liveVenueGuess() === "ST") {
        board = await window.HKJCLive.fetchLiveBoard(date, "HV");
      }
      state.liveRows = (board && board.rows) || [];
      state.liveFetchedAt = (board && board.fetched_at) || new Date().toISOString();
      state.liveError = state.liveRows.length ? "" : (board && board.error) || "未有即時盤";
      state.liveDelay = 4000;
      fillFilterOptions();
      if (state.tab === "data") renderDataTable();
      else renderLiveBadge();
    } catch (err) {
      state.liveError = String(err && err.message ? err.message : err).slice(0, 80);
      state.liveDelay = Math.min((state.liveDelay || 4000) * 1.5, 20000);
      renderLiveBadge();
    }
  }

  async function refreshArchiveQuiet() {
    if (document.hidden) return;
    const g = state.github;
    try {
      const [oddsText, statusText, tickText] = await Promise.all([
        loadRelativeOrRaw(g, "./data/odds_snapshots.csv", "data/odds_snapshots.csv"),
        loadRelativeOrRaw(g, "./status.json", "status.json").catch(() => "{}"),
        loadRelativeOrRaw(g, "./data/odds_ticks.csv", "data/odds_ticks.csv").catch(() => ""),
      ]);
      state.odds = parseCsv(oddsText);
      state.ticks = tickText ? parseCsv(tickText) : [];
      state.status = JSON.parse(statusText || "{}");
      if (state.tab === "data") renderDataTable();
      if (state.tab === "status") renderStatus();
    } catch {
      /* keep last good archive */
    }
  }

  function startLiveLoop() {
    if (state.liveTimer) return;
    const tick = async () => {
      await pollHkjcLive();
      state.liveTimer = setTimeout(tick, state.liveDelay || 4000);
    };
    tick();
    if (!state.archiveTimer) state.archiveTimer = setInterval(refreshArchiveQuiet, 30000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) pollHkjcLive();
    });
  }

  function bind() {
    document.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
    });
    $("brown-threshold").addEventListener("input", () => {
      $("brown-threshold-val").textContent = `${$("brown-threshold").value}%`;
      renderDataTable();
      runStrategy();
    });
    if ($("brown-hold")) {
      $("brown-hold").addEventListener("input", () => {
        renderDataTable();
        renderHorseAudit();
        runStrategy();
      });
    }
    $("min-odds").addEventListener("input", () => {
      $("min-odds-val").textContent = Number($("min-odds").value).toFixed(1);
      runStrategy();
      refreshStrategyFilterTable();
    });
    $("max-odds").addEventListener("input", () => {
      $("max-odds-val").textContent = Number($("max-odds").value).toFixed(1);
      runStrategy();
      refreshStrategyFilterTable();
    });
    ["bet-type", "checkpoint", "mc-bankroll", "mc-stake", "mc-days", "mc-sims"].forEach((id) => {
      $(id).addEventListener("change", () => {
        runStrategy();
        if (id === "checkpoint" || id === "bet-type") refreshStrategyFilterTable();
      });
      $(id).addEventListener("input", () => {
        runStrategy();
        if (id === "checkpoint" || id === "bet-type") refreshStrategyFilterTable();
      });
    });
    ["filter-date", "filter-venue", "filter-race", "filter-horse", "filter-brown", "filter-brown-t1", "filter-strategy"].forEach((id) => {
      $(id).addEventListener("input", () => {
        state.page = 1;
        renderDataTable();
      });
      $(id).addEventListener("change", () => {
        state.page = 1;
        renderDataTable();
      });
    });
    if ($("guide-user")) $("guide-user").addEventListener("click", (ev) => { ev.preventDefault(); showGuide("user"); });
    if ($("guide-pipeline")) $("guide-pipeline").addEventListener("click", (ev) => { ev.preventDefault(); showGuide("pipeline"); });
    $("src-win").addEventListener("click", () => {
      state.tableSource = "win";
      state.page = 1;
      setSourceChip("src-win");
      renderDataTable();
    });
    $("src-place").addEventListener("click", () => {
      state.tableSource = "place";
      state.page = 1;
      setSourceChip("src-place");
      renderDataTable();
    });
    $("src-results").addEventListener("click", () => {
      state.tableSource = "results";
      state.page = 1;
      setSourceChip("src-results");
      renderDataTable();
    });
    $("page-prev").addEventListener("click", () => {
      state.page = Math.max(1, state.page - 1);
      renderDataTable();
    });
    $("page-next").addEventListener("click", () => {
      state.page += 1;
      renderDataTable();
    });
    function downloadPool(pool, filename) {
      const wide = oddsBoard(pool);
      const labels = WIDE_EXPORT_PAIRS.map((p) => p[1]);
      const keys = WIDE_EXPORT_PAIRS.map((p) => p[0]);
      const esc = (v) => {
        const s = v == null ? "" : String(v);
        return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const lines = [labels.join(",")];
      for (const row of wide) {
        lines.push(keys.map((k) => esc(k === "venue" ? venueName(row[k]) : row[k])).join(","));
      }
      downloadBlob(filename, lines.join("\n") + "\n", "text/csv;charset=utf-8");
    }
    $("dl-win").addEventListener("click", () => downloadPool("win", "win_odds_board.csv"));
    $("dl-place").addEventListener("click", () => downloadPool("place", "place_odds_board.csv"));
    $("dl-results").addEventListener("click", () => {
      downloadBlob("race_results.csv", toCsv(state.results, RESULT_FIELDS), "text/csv;charset=utf-8");
    });
    $("btn-tg-copy-strategy").addEventListener("click", () => {
      $("tg-bet-type").value = $("bet-type").value;
      $("tg-checkpoint").value = $("checkpoint").value;
      $("tg-min-odds").value = $("min-odds").value;
      $("tg-max-odds").value = $("max-odds").value;
      $("tg-drop").value = $("brown-threshold").value;
      renderTelegramPreview();
      toast("已把策略頁嘅投注方法、時間點、賠率範圍抄到 Telegram", "ok");
    });
    ["tg-bet-type", "tg-checkpoint", "tg-min-odds", "tg-max-odds", "tg-drop"].forEach((id) => {
      $(id).addEventListener("input", renderTelegramPreview);
      $(id).addEventListener("change", renderTelegramPreview);
    });
    $("btn-reload").addEventListener("click", loadAll);
    $("btn-save-config").addEventListener("click", saveConfigRemote);
    $("btn-save-github").addEventListener("click", () => {
      persistGithubForm();
      toast("GitHub 授權已存到此瀏覽器（不會寫入 repo）", "ok");
    });
    $("btn-save-data-params").addEventListener("click", saveConfigRemote);
    $("btn-save-tg").addEventListener("click", saveConfigRemote);
    $("btn-monitor").addEventListener("click", () => trigger("auto"));
    $("btn-once").addEventListener("click", () => trigger("once"));
    $("btn-results").addEventListener("click", () => trigger("results"));
    if ($("btn-purge-date")) $("btn-purge-date").addEventListener("click", purgeSelectedDate);
    if ($("btn-correct-odds")) $("btn-correct-odds").addEventListener("click", correctInspectedOdds);
    if ($("data-body")) {
      $("data-body").addEventListener("click", (ev) => {
        const tr = ev.target && ev.target.closest ? ev.target.closest("tr[data-horse-key]") : null;
        if (!tr) return;
        const key = tr.getAttribute("data-horse-key");
        const [race_date, venue, race_no, horse_no] = (key || "").split("|");
        inspectHorse({ race_date, venue, race_no, horse_no });
      });
    }
    $("btn-tg-test").addEventListener("click", testTelegram);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bind();
    tickClock();
    setInterval(tickClock, 1000);
    showTab("data");
    startLiveLoop();
    loadAll();
  });
})();
