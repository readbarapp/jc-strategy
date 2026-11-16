/* HKJC Quant Desk — time, CSV, GitHub, persistence. All clocks: Asia/Hong_Kong. */
(function (global) {
  const TZ = "Asia/Hong_Kong";
  const LS_TOKEN = "hkjc_github_token";
  const LS_REPO = "hkjc_github_repo";

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function hkParts(date) {
    const fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      weekday: "short",
    });
    const parts = Object.fromEntries(
      fmt.formatToParts(date || new Date()).map((p) => [p.type, p.value])
    );
    return parts;
  }

  function formatHk(date, withSeconds) {
    const p = hkParts(date);
    const time = withSeconds === false ? `${p.hour}:${p.minute}` : `${p.hour}:${p.minute}:${p.second}`;
    return `${p.year}-${p.month}-${p.day} ${time}`;
  }

  function weekdayZh(date) {
    const map = { Mon: "一", Tue: "二", Wed: "三", Thu: "四", Fri: "五", Sat: "六", Sun: "日" };
    return map[hkParts(date).weekday] || "";
  }

  function parseCsv(text) {
    const rows = [];
    let i = 0;
    const src = String(text || "").replace(/^\uFEFF/, "");
    function readRow() {
      const cells = [];
      let cur = "";
      let q = false;
      while (i < src.length) {
        const ch = src[i++];
        if (q) {
          if (ch === '"') {
            if (src[i] === '"') {
              cur += '"';
              i++;
            } else q = false;
          } else cur += ch;
        } else if (ch === '"') q = true;
        else if (ch === ",") {
          cells.push(cur);
          cur = "";
        } else if (ch === "\n") {
          if (cur.endsWith("\r")) cur = cur.slice(0, -1);
          cells.push(cur);
          return cells;
        } else cur += ch;
      }
      if (cur.length || cells.length) cells.push(cur);
      return cells.length ? cells : null;
    }
    const header = readRow();
    if (!header) return [];
    const keys = header.map((h) => h.trim());
    let row;
    while ((row = readRow())) {
      if (row.every((c) => !c)) continue;
      const obj = {};
      keys.forEach((k, idx) => {
        obj[k] = row[idx] == null ? "" : row[idx];
      });
      rows.push(obj);
    }
    return rows;
  }

  function toCsv(rows, fields) {
    const esc = (v) => {
      const s = v == null ? "" : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [fields.join(",")];
    for (const row of rows) lines.push(fields.map((f) => esc(row[f])).join(","));
    return lines.join("\n") + "\n";
  }

  function downloadBlob(filename, text, mime) {
    const blob = new Blob([text], { type: mime || "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  function detectRepo() {
    const saved = safeJson(localStorage.getItem(LS_REPO));
    const host = location.hostname;
    let owner = (saved && saved.owner) || "";
    let repo = (saved && saved.repo) || "";
    let branch = (saved && saved.branch) || "main";
    if (!owner && host.endsWith(".github.io")) {
      owner = host.split(".")[0];
      const parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
      repo = parts[0] || `${owner}.github.io`;
    }
    return {
      owner,
      repo,
      branch,
      token: localStorage.getItem(LS_TOKEN) || "",
    };
  }

  function saveRepo(github) {
    localStorage.setItem(
      LS_REPO,
      JSON.stringify({ owner: github.owner, repo: github.repo, branch: github.branch || "main" })
    );
    if (github.token) localStorage.setItem(LS_TOKEN, github.token);
    else localStorage.removeItem(LS_TOKEN);
  }

  function safeJson(text) {
    try {
      return text ? JSON.parse(text) : null;
    } catch {
      return null;
    }
  }

  async function fetchText(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    return res.text();
  }

  async function loadRelativeOrRaw(github, relativePath, rawPath) {
    try {
      return await fetchText(relativePath);
    } catch {
      /* fall through */
    }
    if (github.owner && github.repo) {
      const raw = `https://raw.githubusercontent.com/${github.owner}/${github.repo}/${github.branch || "main"}/${rawPath}`;
      try {
        return await fetchText(raw);
      } catch {
        /* fall through */
      }
      if (github.token) {
        return ghGetFile(github, rawPath);
      }
    }
    throw new Error("無法載入 " + relativePath);
  }

  async function ghRequest(github, path, options) {
    if (!github.owner || !github.repo) throw new Error("尚未設定 GitHub owner/repo");
    const url = `https://api.github.com/repos/${github.owner}/${github.repo}${path}`;
    const headers = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    };
    if (github.token) headers.Authorization = `Bearer ${github.token}`;
    if (options && options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(url, { ...(options || {}), headers });
    const text = await res.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      json = { raw: text };
    }
    if (!res.ok) {
      const msg = (json && (json.message || json.error)) || res.statusText;
      throw new Error(`GitHub API ${res.status}: ${msg}`);
    }
    return json;
  }

  function b64encode(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }

  function b64decode(str) {
    return decodeURIComponent(escape(atob(str.replace(/\n/g, ""))));
  }

  async function ghGetFile(github, path) {
    const json = await ghRequest(github, `/contents/${path}?ref=${encodeURIComponent(github.branch || "main")}`);
    if (json && json.content) return b64decode(json.content);
    throw new Error("empty file " + path);
  }

  async function ghPutFile(github, path, content, message) {
    let sha;
    try {
      const existing = await ghRequest(
        github,
        `/contents/${path}?ref=${encodeURIComponent(github.branch || "main")}`
      );
      sha = existing.sha;
    } catch {
      sha = undefined;
    }
    return ghRequest(github, `/contents/${path}`, {
      method: "PUT",
      body: JSON.stringify({
        message,
        content: b64encode(content),
        branch: github.branch || "main",
        sha,
      }),
    });
  }

  async function ghDispatch(github, command, raceDate) {
    const inputs = { command: command || "auto" };
    if (raceDate) inputs.race_date = raceDate;
    return ghRequest(github, "/actions/workflows/hkjc_monitor.yml/dispatches", {
      method: "POST",
      body: JSON.stringify({ ref: github.branch || "main", inputs }),
    });
  }

  async function ghLatestRun(github) {
    return ghRequest(
      github,
      "/actions/workflows/hkjc_monitor.yml/runs?per_page=1"
    );
  }

  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function isTrue(v) {
    return String(v).toLowerCase() === "true" || v === "1" || v === true;
  }

  global.HKJC = {
    TZ,
    formatHk,
    weekdayZh,
    parseCsv,
    toCsv,
    downloadBlob,
    detectRepo,
    saveRepo,
    loadRelativeOrRaw,
    ghRequest,
    ghGetFile,
    ghPutFile,
    ghDispatch,
    ghLatestRun,
    num,
    isTrue,
  };
})(window);
