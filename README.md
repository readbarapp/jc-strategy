# HKJC Quant Desk

100% 託管在 GitHub 上的香港賽馬（HKJC）量化交易、數據管理與策略回測平台。

- 前端：`docs/` 純 HTML + Tailwind CSS + JavaScript（GitHub Pages）
- 後端：`scraper_runner.py` + GitHub Actions（高頻賠率監控、賽果、Telegram）
- 時區：全程 **Asia/Hong_Kong（UTC+8）**
- 不使用 Streamlit；在 GitHub 網頁上即可調整參數、回測、觸發 Action、下載 CSV

本專案只讀取 HKJC 公開賽事／賠率資料，供研究與回測。不是投注建議。

詳細說明（網站「使用說明」分頁同一份）：

1. [用家說明：每個賽馬日應該做咩](docs/guides/user-guide.md)
2. [資料收集、分析同警報（去邊個網站、抄邊格）](docs/guides/data-pipeline.md)

### 點樣收數據（唔使識寫程式都睇得明）

1. 全日每隔大約半個鐘問馬會：「今日沙田或者跑馬地有冇賽馬？第一場幾點開跑？」冇就收工。有就跟當日官方第一場時間倒數，唔係寫死 11:00／17:30。
2. 有賽事就喺開跑前 15、10、5、1 分鐘同開跑嗰下，**分開**抄低每隻馬嘅獨贏（WIN）同位置（PLA）賠率。兩個彩池兩個數字，唔會撈亂。唔再抄開賽前 3 分鐘。
3. 如果呢個鐘點嘅獨贏比起上一個鐘點（大約 5 分鐘前，例如 T-1 對 T-5）平咗一半或以上，就標「啡格」。位置表用位置賠率自己計急跌，但策略／Telegram 預設仍然用獨贏啡格做訊號。
4. 賽事完咗再抄官方名次、獨贏派彩、位置派彩。回測「只買位置」用官方位置派彩，唔係用獨贏去估。
5. 網站而家見到嘅舊日子多數係示範用嘅假數據（欄位同真 crawl 一樣）；真賽日同一套程式寫入真實 WIN／PLA。

---

## 架構

```
config.json                     策略、啡格門檻、Telegram、抓取間隔
scraper_runner.py               Actions 進入點
src/                            時間、HKJC client、監控、Telegram、回測
data/odds_snapshots.csv         長表：每個時間點一列，同時有 win_odds 同 place_odds 兩欄
data/win_board.csv              獨贏寬表（一馬一行，T-15…T-0）
data/place_board.csv            位置寬表（一馬一行，T-15…T-0）
data/odds_board.csv             獨贏寬表別名（兼容舊下載）
data/race_results.csv           官方名次與每 $10 獨贏／位置派彩
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
| `0,30 1-16 * * *` | 09:00–00:30 每隔 30 分鐘 | 偵測今日有冇賽、讀官方第一場 `postTime` |
| `20 16 * * *` | 00:20 | 再收一次官方賽果 |

`auto` 模式會先問馬會**今日香港是否有 ST / HV 賽馬日**，再讀當日每一場官方開跑時間。沒有賽事就快速結束。有賽但距離第一場監控窗仍超過約 45 分鐘，同樣結束，等下一格排程（避免 GitHub Actions 6 小時上限由朝空等到晚）。接近第一場前 20 分鐘才進入高頻迴圈（預設 10 秒），把 T-15、T-10、T-5、T-1、T-0 寫進 CSV（唔再寫 T-3）；接近啡格或 Telegram 條件時立即推播。數據約每 120 秒 commit 一次，避免 10 秒一 commit 打爆 git。

**PAT 唔負責自動跑。** 你貼喺網站嘅 Personal Access Token 只係改 `config.json` 同人手撳「觸發今日監控」。賽馬日自動監控係 GitHub Actions 排程，電腦同網站都唔使開。Telegram 推播另外要 repo Secret `TELEGRAM_BOT_TOKEN`。

也可在 Actions 頁手動 **Run workflow**：`auto` / `monitor` / `results` / `once` / `test-telegram`。

---

## 3. 用網頁授權寫入 `config.json`

GitHub Pages 本身是靜態的。要從瀏覽器改 repo 檔案或觸發 Action，需要一枚 **Personal Access Token**（只存在你的瀏覽器 `localStorage`，不會進 git）。PAT **唔會**令賽馬日自動跑；自動跑係上一節的 Actions 排程。

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
4. **Telegram** 可獨立設定投注方法、開賽前幾多分鐘、獨贏賠率範圍（同策略頁一樣），亦可撳「抄策略設定」。
5. **發送測試訊息**：先嘗試直接打 Telegram API；若被瀏覽器 CORS 擋住，會改觸發 `test-telegram` workflow（由 Actions 發送）。
6. **觸發今日監控** / **單次快照** / **收取賽果** 都會 `workflow_dispatch` `hkjc_monitor.yml`。

---

## 4. 數據欄位

馬名一律優先用 **中文名**（GraphQL `name_ch`／中文賽果頁）。

### 示範數據 vs 真實數據

`scripts/generate_sample_data.py` 產生的歷史賽日是 **模擬示範數據**（假數據），方便 Pages 一打開就能回測，**不是**馬會官方紀錄。第一次 GitHub Actions 成功抄到真實馬會賠率／賽果時，會**刪除全部示範列**，之後回測只用真實紀錄。

### 數據中心：獨贏同位置分開兩張表

畫面可以撳 **獨贏賠率**、**位置賠率** 或 **賽果派彩**。賠率表是 **一隻馬一行**，欄位為開賽前 15、10、5、1 分鐘及開跑的**該彩池實際賠率**。「只看啡格」同「只看開賽1分鐘前出現啡格」三張表都適用（賽果用獨贏急跌去對同一隻馬）。

- 獨贏表只顯示馬會 **WIN** 彩池
- 位置表只顯示馬會 **PLA** 彩池
- 長表 `odds_snapshots.csv` 仍然一列同時有 `win_odds`、`place_odds` 兩欄（方便監控寫入），但前端唔會把兩個數字撈成一欄

**啡格（獨贏表）**：該時間點的獨贏較 **上一個時間點（大約 5 分鐘前）** 下跌 ≥ 門檻（預設 50%）。例如開賽前 1 分鐘比 5 分鐘低 50%，T-1 格會標啡色。唔再抄開賽前 3 分鐘。位置表用同樣方法睇位置急跌，但策略／Telegram 訊號預設仍然用獨贏啡格。

### 馬會賠率點樣拎（真賽日同一條路，唔係亂填）

`src/hkjc_client.py` 只讀馬會公開接口，順序如下。

1. **今日有冇賽**  
   POST `https://info.cld.hkjc.com/graphql/base/`，query 是馬會投注網頁用緊嗰條 `raceMeetings`（whitelist；改 query 會 `WHITELIST_ERROR`）。只接受沙田 `ST`、跑馬地 `HV`。失敗則改睇中文賽程頁 `Fixture.aspx`。

2. **中文馬名**  
   同一條 GraphQL 的 `runners.name_ch`。冇中文先用英文。

3. **獨贏 + 位置（主通道）**  
   再 POST 同一 GraphQL，變數 `oddsTypes: [WIN, PLA]`、`raceNo`。回覆有多個 `pmPools`：
   - `oddsType == "WIN"` → 每個 `oddsNodes.combString`（馬號）的 `oddsValue` 寫入 `win_odds`
   - `oddsType == "PLA"` → 同樣用馬號寫入 `place_odds`
   - 其他彩池（QIN 等）直接跳過，唔會誤寫入位置欄
   - 兩個 map 都空 → 當 GraphQL 失敗，改走後備，唔會用空白當真實賠率

4. **後備 JSON**  
   `https://bet.hkjc.com/racing/getJSON.aspx?type=winplaodds&date=年-月-日&venue=ST或HV&start=場次&end=場次`  
   `OUT` 字串用 `#` 切開：前半 `WIN;馬號=賠率=…`，後半 `PLA;馬號=賠率=…`。兩邊分開 parse，再對馬號合併成同一 runner 的兩欄。

5. **示範數據**  
   `scripts/generate_sample_data.py` 只係填滿表格用。Actions 真賽日跑 `scraper_runner.py auto`，**唔會**呼叫呢個產生器。

6. **賽果**  
   中文 `LocalResults.aspx` 抄名次同派彩表（獨贏／位置每 $10）；失敗先用 GraphQL `resPools` 官方 dividends。

### `data/odds_snapshots.csv`

監控寫入的長表：`race_date, venue, race_no, scheduled_time, checkpoint, capture_timestamp, horse_no, horse_name, win_odds, place_odds, prev_win_odds, win_drop_pct, is_brown_grid`

- `checkpoint`：`T-15` `T-10` `T-5` `T-1` `T-0`（唔再寫 `T-3`）
- `win_odds` / `place_odds`：同一時間點兩個獨立彩池
- `prev_win_odds` / `win_drop_pct`：相對 **上一個 checkpoint 的獨贏**（T-1 對 T-5，大約 5 分鐘；不是 10 秒一跳）
- `is_brown_grid`：該 checkpoint 獨贏跌幅 ≥ 門檻

### `data/win_board.csv` / `data/place_board.csv`

同一批 snapshot 轉成一馬一行。`odds_board.csv` 係獨贏寬表嘅別名。網頁下載鈕分別匯出獨贏／位置。

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

## 6. 策略與蒙地卡羅（預設：開賽前 1 分鐘啡格）

回測規則（同網頁可以改）：

1. 只睇你揀嘅時間點（預設 **開賽前 1 分鐘**）
2. 嗰一刻要係**獨贏啡格**（獨贏比起上一個時間點跌 ≥ 門檻，預設 50%；T-1 同 T-5 比）
3. 嗰一刻**獨贏**要喺你設定嘅賠率範圍（例如 3.5–9.0）
4. 投注方法：只買獨贏 / 只買位置 / 獨贏+位置，每注 $10

盈虧來源（唔會用獨贏去假扮位置）：

- 只買獨贏：官方 `win_dividend` − $10（唔中 −$10）
- 只買位置：官方 `placedividend` − $10。揀馬仍然用獨贏啡格，但結算用位置派彩
- 獨贏 + 位置：兩筆 $10 分開計再加總（本金 $20）

EV／ROI = 歷史上每次跟呢條規則落注，總盈虧 ÷ 總本金。

### Telegram

通知條件同策略一樣可以獨立設定：投注方法、開賽前幾多分鐘、獨贏賠率範圍、啡格跌幅。推播時會同時顯示獨贏同位置數字，方便你決定點買。網頁有「抄策略設定」掣。

蒙地卡羅每年落注場次用策略頻率 × 一年賽馬日（預設 88）自動計；模擬下注次數係隨機重抽幾多條一年路徑，估計一年後賺幾多、最大回撤同破產機會。

Repo 內已附示範賽日數據，clone 後立刻可回測。真實監控開始後會由 Actions 持續追加。
