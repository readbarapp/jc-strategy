/* HKJC Quant Desk SPA */
(function () {
  const { formatHk, weekdayZh, parseCsv, toCsv, downloadBlob, detectRepo, saveRepo,
    loadRelativeOrRaw, ghPutFile, ghDispatch, ghLatestRun, num, isTrue } = window.HKJC;
  const { evaluate, monteCarlo } = window.HKJCEngine;

  const ODDS_FIELDS = [
    "race_date", "venue", "race_no", "scheduled_time", "checkpoint", "capture_timestamp",
    "horse_no", "horse_name", "win_odds", "place_odds", "prev_win_odds", "win_drop_pct", "is_brown_grid",
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
    tableSource: "odds",
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

  function isBrownLive(row) {
    return isTrue(row.is_brown_grid) || num(row.win_drop_pct, 0) >= currentThreshold();
  }

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
      toast(`已載入賠率 ${state.odds.length} 列、賽果 ${state.results.length} 列`, "ok");
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
    $("mc-bankroll").value = m.initial_bankroll ?? 10000;
    $("mc-stake").value = m.stake ?? 10;
    $("mc-races").value = m.races_per_year ?? 400;
    $("mc-sims").value = m.simulations ?? 1000;
    $("tg-enabled").checked = !!t.enabled;
    $("tg-chat").value = t.chat_id || "";
    $("tg-token").value = t.bot_token || "";
    $("tg-min-odds").value = t.min_odds ?? 3.5;
    $("tg-max-odds").value = t.max_odds ?? 9.0;
    $("tg-drop").value = t.min_drop_pct ?? 20;
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

  function filteredRows() {
    const date = $("filter-date").value;
    const venue = $("filter-venue").value;
    const race = $("filter-race").value;
    const horse = $("filter-horse").value.trim();
    const brown = $("filter-brown").checked;
    const src = state.tableSource === "results" ? state.results : state.odds;
    return src.filter((row) => {
      if (date && row.race_date !== date) return false;
      if (venue && row.venue !== venue) return false;
      if (race && String(row.race_no) !== race) return false;
      if (horse && String(row.horse_no) !== horse) return false;
      if (brown && state.tableSource === "odds" && !isBrownLive(row)) return false;
      return true;
    });
  }

  function renderDataTable() {
    const rows = filteredRows();
    const pageSize = 80;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (state.page > pages) state.page = pages;
    const slice = rows.slice((state.page - 1) * pageSize, state.page * pageSize);
    $("table-meta").textContent = `顯示 ${rows.length} / 原始 ${
      state.tableSource === "results" ? state.results.length : state.odds.length
    } 列 · 第 ${state.page}/${pages} 頁`;
    const fields = state.tableSource === "results" ? RESULT_FIELDS : ODDS_FIELDS;
    const labels = {
      race_date: "日期",
      venue: "場地",
      race_no: "場次",
      scheduled_time: "開跑",
      checkpoint: "節點",
      capture_timestamp: "捕捉時間",
      horse_no: "馬號",
      horse_name: "馬名",
      win_odds: "獨贏",
      place_odds: "位置",
      prev_win_odds: "上一賠率",
      win_drop_pct: "跌幅%",
      is_brown_grid: "啡格",
      finish_rank: "名次",
      final_sp: "終賠",
      win_dividend: "獨贏派彩",
      placedividend: "位置派彩",
    };
    $("data-head").innerHTML =
      "<tr>" + fields.map((f) => `<th>${labels[f] || f}</th>`).join("") + "</tr>";
    $("data-body").innerHTML = slice
      .map((row) => {
        const brown = state.tableSource === "odds" && isBrownLive(row);
        const tds = fields
          .map((f) => {
            let v = row[f];
            if (f === "venue") v = venueName(v);
            if (f === "is_brown_grid") v = brown ? "YES" : "";
            if (f === "win_drop_pct" && v !== "" && v != null) v = Number(v).toFixed(2);
            return `<td>${v == null || v === "" ? "—" : v}</td>`;
          })
          .join("");
        return `<tr class="${brown ? "row-brown" : ""}">${tds}</tr>`;
      })
      .join("");
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
    const bt = evaluate(state.odds, state.results, {
      minOdds: Math.min(minOdds, maxOdds),
      maxOdds: Math.max(minOdds, maxOdds),
      betType,
      stake: 10,
      threshold: currentThreshold(),
    });
    state.backtest = bt;
    const tone = bt.roi >= 0 ? "up" : "down";
    $("bt-kpis").innerHTML = [
      kpi("t", "總觸發次數", bt.triggers, "啡格 ∩ 賠率區間"),
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
    cfg.monte_carlo.initial_bankroll = num($("mc-bankroll").value, 10000);
    cfg.monte_carlo.stake = num($("mc-stake").value, 10);
    cfg.monte_carlo.races_per_year = num($("mc-races").value, 400);
    cfg.monte_carlo.simulations = num($("mc-sims").value, 1000);
    cfg.telegram.enabled = $("tg-enabled").checked;
    cfg.telegram.chat_id = $("tg-chat").value.trim();
    cfg.telegram.min_odds = num($("tg-min-odds").value, 3.5);
    cfg.telegram.max_odds = num($("tg-max-odds").value, 9.0);
    cfg.telegram.min_drop_pct = num($("tg-drop").value, 20);
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
    ["bet-type", "mc-bankroll", "mc-stake", "mc-races", "mc-sims"].forEach((id) => {
      $(id).addEventListener("change", runStrategy);
      $(id).addEventListener("input", runStrategy);
    });
    ["filter-date", "filter-venue", "filter-race", "filter-horse", "filter-brown"].forEach((id) => {
      $(id).addEventListener("input", () => {
        state.page = 1;
        renderDataTable();
      });
      $(id).addEventListener("change", () => {
        state.page = 1;
        renderDataTable();
      });
    });
    $("src-odds").addEventListener("click", () => {
      state.tableSource = "odds";
      state.page = 1;
      $("src-odds").classList.add("chip-on");
      $("src-results").classList.remove("chip-on");
      renderDataTable();
    });
    $("src-results").addEventListener("click", () => {
      state.tableSource = "results";
      state.page = 1;
      $("src-results").classList.add("chip-on");
      $("src-odds").classList.remove("chip-on");
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
    $("dl-odds").addEventListener("click", () => {
      downloadBlob("odds_snapshots.csv", toCsv(state.odds, ODDS_FIELDS), "text/csv;charset=utf-8");
    });
    $("dl-results").addEventListener("click", () => {
      downloadBlob("race_results.csv", toCsv(state.results, RESULT_FIELDS), "text/csv;charset=utf-8");
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
