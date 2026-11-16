/* HKJC Quant Desk SPA */
(function () {
  const { formatHk, weekdayZh, parseCsv, toCsv, downloadBlob, detectRepo, saveRepo,
    loadRelativeOrRaw, ghPutFile, ghDispatch, ghLatestRun, num, isTrue } = window.HKJC;
  const { evaluate, monteCarlo, pivotOdds } = window.HKJCEngine;

  const ODDS_BOARD_COLS = [
    { key: "odds_t15", label: "開賽前15分鐘", brownKey: null },
    { key: "odds_t10", label: "開賽前10分鐘", brownKey: "brown_t10" },
    { key: "odds_t5", label: "開賽前5分鐘", brownKey: "brown_t5" },
    { key: "odds_t1", label: "開賽前1分鐘", brownKey: "brown_t1" },
    { key: "odds_t0", label: "開跑", brownKey: "brown_t0" },
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
    guideKind: "user",
    chart: null,
    backtest: null,
    mc: null,
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
    if (id === "status") refreshStatus();
    if (id === "guide") showGuide(state.guideKind || "user");
  }

  async function loadAll() {
    const g = state.github;
    try {
      const [cfgText, oddsText, resText, statusText, logText] = await Promise.all([
        loadRelativeOrRaw(g, "./config.json", "config.json").catch(() => "{}"),
        loadRelativeOrRaw(g, "./data/odds_snapshots.csv", "data/odds_snapshots.csv"),
        loadRelativeOrRaw(g, "./data/race_results.csv", "data/race_results.csv"),
        loadRelativeOrRaw(g, "./status.json", "status.json").catch(() => "{}"),
        loadRelativeOrRaw(g, "./logs/latest.log", "logs/latest.log").catch(() => ""),
      ]);
      state.config = JSON.parse(cfgText || "{}");
      state.odds = parseCsv(oddsText);
      state.results = parseCsv(resText);
      state.status = JSON.parse(statusText || "{}");
      state.logText = logText;
      hydrateForms();
      fillFilterOptions();
      renderDataTable();
      renderStatus();
      runStrategy();
      toast(`已載入 ${oddsBoard().length} 匹馬賠率走勢、賽果 ${state.results.length} 列（示範歷史為模擬數據）`, "ok");
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
    $("scrape-interval").value = d.scrape_interval_seconds ?? 10;
    $("min-odds").value = s.min_odds ?? 3.5;
    $("max-odds").value = s.max_odds ?? 9.0;
    $("min-odds-val").textContent = Number($("min-odds").value).toFixed(1);
    $("max-odds-val").textContent = Number($("max-odds").value).toFixed(1);
    $("bet-type").value = s.bet_type || "win";
    $("checkpoint").value = s.checkpoint || "T-1";
    $("mc-bankroll").value = m.initial_bankroll ?? 10000;
    $("mc-stake").value = m.stake ?? 10;
    $("mc-races").value = m.races_per_year ?? 400;
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

  function updateGhBadge() {
    const ok = !!(state.github.owner && state.github.repo && state.github.token);
    $("gh-badge").textContent = ok ? "GitHub 已授權" : "未授權寫入";
    $("gh-badge").className =
      "rounded-full px-3 py-1 text-xs font-medium " +
      (ok ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-200");
  }

  function fillFilterOptions() {
    const dates = [...new Set(state.odds.map((r) => r.race_date).filter(Boolean))].sort().reverse();
    const races = [...new Set(state.odds.map((r) => String(r.race_no)).filter(Boolean))].sort(
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
      const drop = num(row.win_drop_pct, 0);
      const brown = isTrue(row.is_brown_grid) || drop >= threshold;
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

  function brownFlags(row, lookup) {
    if (state.tableSource !== "results") {
      return {
        any: isTrue(row.is_brown_grid) || !!row.brown_at,
        t1: isTrue(row.brown_t1),
      };
    }
    if (!lookup) return { any: false, t1: false };
    return lookup.get(horseKey(row)) || { any: false, t1: false };
  }

  function filteredRows() {
    const date = $("filter-date") ? $("filter-date").value : "";
    const venue = $("filter-venue") ? $("filter-venue").value : "";
    const race = $("filter-race") ? $("filter-race").value : "";
    const horse = $("filter-horse") ? $("filter-horse").value.trim() : "";
    const brown = !!( $("filter-brown") && $("filter-brown").checked );
    const brownT1 = !!( $("filter-brown-t1") && $("filter-brown-t1").checked );
    const src = state.tableSource === "results" ? state.results : oddsBoard(state.tableSource);
    const lookup = brown || brownT1 ? winBrownLookup() : null;
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
      return true;
    });
  }

  function fmtOdds(v) {
    if (v === "" || v == null || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(1);
  }

  function renderDataTable() {
    let rows;
    try {
      rows = filteredRows();
    } catch (err) {
      toast(err.message || String(err), "error");
      return;
    }
    const pageSize = 80;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (state.page > pages) state.page = pages;
    const slice = rows.slice((state.page - 1) * pageSize, state.page * pageSize);
    if (state.tableSource === "results") {
      const brownOn = $("filter-brown").checked || ($("filter-brown-t1") && $("filter-brown-t1").checked);
      $("table-meta").textContent =
        `顯示 ${rows.length} / ${state.results.length} 列 · 第 ${state.page}/${pages} 頁` +
        (brownOn ? " · 啡格 filter 用獨贏急跌對應同一隻馬" : "");
      if ($("board-legend")) {
        $("board-legend").innerHTML =
          "呢張表係<strong class=\"text-slate-300\">官方賽果派彩</strong>。上面「只看啡格／只看開賽1分鐘前出現啡格」同樣適用：用獨贏表嘅急跌（T-1 對 T-5）去篩選呢啲馬。";
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
          `<tr><td colspan="${RESULT_FIELDS.length}" class="text-slate-500">呢個 filter 之下冇賽果。啡格係用獨贏急跌對同一隻馬（開賽前1分鐘 = T-1 對 T-5）。</td></tr>`;
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
            return `<tr>${tds}</tr>`;
          })
          .join("");
      }
    } else {
      const poolName = state.tableSource === "place" ? "位置賠率" : "獨贏賠率";
      $("table-meta").textContent = `顯示 ${rows.length} 匹馬 · ${poolName} · 第 ${state.page}/${pages} 頁 · 急跌格 = 較約 5 分鐘前（上一節點）跌 ≥ ${currentThreshold()}%`;
      if ($("board-legend")) {
        $("board-legend").innerHTML =
          state.tableSource === "place"
            ? "呢張表淨係<strong class=\"text-slate-300\">位置賠率</strong>（馬會 PLA 彩池）。急跌格＝較上一個時間點（約 5 分鐘前）跌 ≥ 門檻，例如開賽前 1 分鐘同開賽前 5 分鐘比。冇開賽前 3 分鐘欄。"
            : "呢張表淨係<strong class=\"text-slate-300\">獨贏賠率</strong>（馬會 WIN 彩池）。啡格＝較上一個時間點（約 5 分鐘前）跌 ≥ 門檻；開賽前 1 分鐘同開賽前 5 分鐘比。唔再抄開賽前 3 分鐘。";
      }
      $("data-head").innerHTML = `<tr>
        <th>日期</th><th>場地</th><th>場次</th><th>開跑</th><th>馬號</th><th>馬名</th>
        ${ODDS_BOARD_COLS.map((c) => `<th>${c.label}</th>`).join("")}
        <th>啡格時間點</th>
      </tr>`;
      $("data-body").innerHTML = slice
        .map((row) => {
          const cells = ODDS_BOARD_COLS.map((c) => {
            const brown = c.brownKey && isTrue(row[c.brownKey]);
            return `<td class="${brown ? "cell-brown" : ""}">${fmtOdds(row[c.key])}</td>`;
          }).join("");
          const flag = row.brown_at
            ? `<td class="cell-brown">${row.brown_at}</td>`
            : `<td>—</td>`;
          return `<tr>
            <td>${row.race_date}</td>
            <td>${venueName(row.venue)}</td>
            <td>${row.race_no}</td>
            <td>${row.scheduled_time || "—"}</td>
            <td>${row.horse_no}</td>
            <td>${row.horse_name || "—"}</td>
            ${cells}${flag}
          </tr>`;
        })
        .join("");
    }
    $("page-indicator").textContent = `${state.page} / ${pages}`;
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
    });
    state.backtest = bt;
    const tone = bt.roi >= 0 ? "up" : "down";
    const whenLabel = ($("checkpoint").selectedOptions[0] && $("checkpoint").selectedOptions[0].text) || checkpoint;
    $("bt-kpis").innerHTML = [
      kpi("t", "總觸發次數", bt.triggers, `${whenLabel} 啡格 ∩ 賠率範圍`),
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
      $("mc-kpis").innerHTML = kpi("x", "需要回測注", "—", "先讓策略產生觸發");
      if (state.chart) {
        state.chart.destroy();
        state.chart = null;
      }
      return;
    }
    const mc = monteCarlo(bt.trades, {
      bankroll: num($("mc-bankroll").value, 10000),
      stake: num($("mc-stake").value, 10),
      races: num($("mc-races").value, 400),
      sims: num($("mc-sims").value, 1000),
    });
    state.mc = mc;
    $("mc-kpis").innerHTML = [
      kpi("e", "預期年化回報", (mc.expected_pnl >= 0 ? "+" : "") + Math.round(mc.expected_pnl), `期末資金 $${Math.round(mc.expected_final)}`),
      kpi("d", "最大回撤 MDD", (mc.mdd_median * 100).toFixed(1) + "%", `P95 ${(mc.mdd_p95 * 100).toFixed(1)}%`, "down"),
      kpi("u", "破產概率", mc.ruin.toFixed(2) + "%", `${mc.sims} 條隨機路徑`, mc.ruin > 5 ? "down" : "up"),
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
    cfg.data.scrape_interval_seconds = num($("scrape-interval").value, 10);
    cfg.strategy.min_odds = num($("min-odds").value, 3.5);
    cfg.strategy.max_odds = num($("max-odds").value, 9.0);
    cfg.strategy.bet_type = $("bet-type").value;
    cfg.strategy.checkpoint = $("checkpoint").value || "T-1";
    cfg.monte_carlo.initial_bankroll = num($("mc-bankroll").value, 10000);
    cfg.monte_carlo.stake = num($("mc-stake").value, 10);
    cfg.monte_carlo.races_per_year = num($("mc-races").value, 400);
    cfg.monte_carlo.simulations = num($("mc-sims").value, 1000);
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

  function bind() {
    document.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
    });
    $("brown-threshold").addEventListener("input", () => {
      $("brown-threshold-val").textContent = `${$("brown-threshold").value}%`;
      renderDataTable();
      runStrategy();
    });
    $("min-odds").addEventListener("input", () => {
      $("min-odds-val").textContent = Number($("min-odds").value).toFixed(1);
      runStrategy();
    });
    $("max-odds").addEventListener("input", () => {
      $("max-odds-val").textContent = Number($("max-odds").value).toFixed(1);
      runStrategy();
    });
    ["bet-type", "checkpoint", "mc-bankroll", "mc-stake", "mc-races", "mc-sims"].forEach((id) => {
      $(id).addEventListener("change", runStrategy);
      $(id).addEventListener("input", runStrategy);
    });
    ["filter-date", "filter-venue", "filter-race", "filter-horse", "filter-brown", "filter-brown-t1"].forEach((id) => {
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
    $("btn-tg-test").addEventListener("click", testTelegram);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bind();
    tickClock();
    setInterval(tickClock, 1000);
    showTab("data");
    loadAll();
  });
})();
