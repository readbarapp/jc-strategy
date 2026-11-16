# HKJC Quant Desk

100% 託管在 GitHub 上的香港賽馬（HKJC）量化交易、數據管理與策略回測平台。

- 前端：`docs/` 純 HTML + Tailwind CSS + JavaScript（GitHub Pages）
- 後端：`scraper_runner.py` + GitHub Actions（高頻賠率監控、賽果、Telegram）
- 時區：全程 **Asia/Hong_Kong（UTC+8）**
- 不使用 Streamlit；在 GitHub 網頁上即可調整參數、回測、觸發 Action、下載 CSV

本專案只讀取 HKJC 公開賽事／賠率資料，供研究與回測。不是投注建議。

---

## 架構

```
config.json                     策略、啡格門檻、Telegram、抓取間隔
scraper_runner.py               Actions 進入點
src/                            時間、HKJC client、監控、Telegram、回測
data/odds_snapshots.csv         賠率走勢（T-15…T-0）
data/race_results.csv           官方名次與每 $10 派彩
logs/latest.log                 爬蟲即時日誌
status.json                     給 Pages 讀的系統狀態
docs/                           GitHub Pages 網站（含 data/ 鏡像）
.github/workflows/hkjc_monitor.yml
```

GitHub Actions 每次提交數據時，會把 `data/`、`config.json`、`status.json`、`logs/latest.log` 鏡像到 `docs/`，所以 Pages 不需後端即可顯示最新表格與日誌。

網頁端若貼上 Personal Access Token，還可以直接：

1. 把參數寫回 `config.json`
2. `workflow_dispatch` 觸發監控 / 單次快照 / 收取賽果 / Telegram 測試

---

## 1. 啟用 GitHub Pages

1. 把本 repo push 到 GitHub（預設分支 `main`）。
2. **Settings → Pages**
   - Source: **Deploy from a branch**
   - Branch: `main`
   - Folder: `/docs`
3. 儲存後等 1–2 分鐘。網址會是：
   - `https://<owner>.github.io/<repo>/`
4. 用瀏覽器打開後即可看到數據中心、回測與示範歷史數據。

若 Jekyll 干擾靜態檔，repo 已包含 `docs/.nojekyll`。

---

## 2. GitHub Actions 與 Secrets

### Workflow 寫入權限

**Settings → Actions → General → Workflow permissions**

- 選 **Read and write permissions**
- 勾選 **Allow GitHub Actions to create and approve pull requests**（可選）

否則監控程式無法 `git push` 最新 CSV / log。

### Secrets（Telegram）

**Settings → Secrets and variables → Actions** 新增：

| Name | 說明 |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather 發給你的 token |
| `TELEGRAM_CHAT_ID` | 頻道或個人 chat id（可選，也可寫在網頁的 config） |

**千萬不要**把 Bot Token 提交進 `config.json`。前端儲存設定時會自動剔除 token。正式監控一律讀 GitHub Secret。

### 排程（香港時間）

| UTC cron | 香港時間 | 用途 |
| --- | --- | --- |
| `0 3 * * *` | 11:00 | 沙田日賽監控視窗 |
| `30 9 * * *` | 17:30 | 跑馬地／夜賽監控視窗 |
| `20 16 * * *` | 00:20 | 收官方賽果 |

`auto` 模式會先偵測**今日香港是否有 ST / HV 賽馬日**。沒有賽事就快速結束，不空轉 6 小時。有賽事則在開跑前 20 分鐘進入高頻迴圈（預設 10 秒），把 T-15、T-10、T-5、T-3、T-1、T-0 寫進 CSV；接近啡格或 Telegram 條件時立即推播。數據約每 120 秒 commit 一次，避免 10 秒一 commit 打爆 git。

也可在 Actions 頁手動 **Run workflow**：`auto` / `monitor` / `results` / `once` / `test-telegram`。

---

## 3. 用網頁授權寫入 `config.json`

GitHub Pages 本身是靜態的。要從瀏覽器改 repo 檔案或觸發 Action，需要一枚 **Personal Access Token**（只存在你的瀏覽器 `localStorage`，不會進 git）。

### 建立 PAT

1. GitHub → **Settings → Developer settings → Personal access tokens**
2. 建議 **Fine-grained**：只授權這個 repo
   - **Contents**: Read and write
   - **Actions**: Read and write
   - **Metadata**: Read
3. 或 classic token，勾選 `repo`（private 必備）以及 `workflow`
4. 複製 token，只貼到本站「即時狀態」分頁的輸入框，按 **僅儲存授權到瀏覽器**

公開 repo 讀 CSV 不需要 token；**寫入與觸發 Action 需要**。

### 網頁操作

1. Owner / Repo 一般會從 `*.github.io` 網址自動偵測；不對就手動改。
2. Branch 預設 `main`。
3. **數據中心** 調整啡格門檻、抓取間隔 → **儲存參數到 GitHub**。
4. **Telegram** 填 chat id、開關、3.5–9.0 / 跌幅 20% 等條件 → **儲存 Telegram 設定**。
5. **發送測試訊息**：先嘗試直接打 Telegram API；若被瀏覽器 CORS 擋住，會改觸發 `test-telegram` workflow（由 Actions 發送）。
6. **觸發今日監控** / **單次快照** / **收取賽果** 都會 `workflow_dispatch` `hkjc_monitor.yml`。

---

## 4. 數據欄位

### `data/odds_snapshots.csv`

`race_date, venue, race_no, scheduled_time, checkpoint, capture_timestamp, horse_no, horse_name, win_odds, place_odds, prev_win_odds, win_drop_pct, is_brown_grid`

- `checkpoint`：`T-15` `T-10` `T-5` `T-3` `T-1` `T-0`（或急跌時的 `ALERT`）
- `win_drop_pct`：相對**上一個時間點**的獨贏跌幅（%），正數代表縮價
- `is_brown_grid`：`win_drop_pct >=` 設定門檻（預設 50%）

### `data/race_results.csv`

`race_date, venue, race_no, horse_no, horse_name, finish_rank, final_sp, win_dividend, placedividend`

派彩為官方 **每 $10 實收**；未中為 `0`。

---

## 5. 本地執行（可選）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scraper_runner.py once            # 單次快照
python scraper_runner.py auto            # 與 Actions 相同邏輯
python scraper_runner.py demo-data       # 重產示範歷史 CSV
python scraper_runner.py test-telegram   # 需環境變數 TELEGRAM_BOT_TOKEN
```

前端開發：在 `docs/` 開靜態伺服器（例如 `python3 -m http.server 8080 --directory docs`）。

---

## 6. 策略與蒙地卡羅

前端用已存 CSV **即時重算**（改滑桿不必等 Python）：

- 觸發條件：啡格（或即時跌幅 ≥ 門檻）且獨贏落在 Min–Max
- 投注：淨買獨贏 / 淨買位置 / 獨贏+位置，每注 $10
- 輸出：觸發次數、勝率、平均命中派彩賠率、總本金、淨盈虧、**EV/ROI%**
- 蒙地卡羅：對歷史 PnL 做 1,000 次有放回路徑，畫 Chart.js 資金 P10/P25/P50/P75/P90 區間，並給出預期年化回報、**MDD**、破產概率

Repo 內已附示範賽日數據，clone 後立刻可回測。真實監控開始後會由 Actions 持續追加。
