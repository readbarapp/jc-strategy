# 資料收集、分析同警報：技術說明

呢份講程式 **實際去邊、抄邊格、點計、點推播**。對應程式：`src/hkjc_client.py`（拎數）、`src/monitor.py`（時間同寫入）、`src/odds_math.py`（啡格）、`src/backtest.py` 同 `docs/assets/engine.js`（分析）、`src/telegram_notify.py`（警報）。

示範 CSV 由 `scripts/generate_sample_data.py` 產生，**真賽日唔會跑呢個產生器**。第一次真實 crawl 會刪晒示範列（`data/dataset_origin.json` 由 `demo` 轉 `live`）。

---

## 一、整體流程

```
GitHub Actions（香港時間 09:00–00:30 每隔約 30 分鐘偵測，或你人手觸發）
        │
        ▼
scraper_runner.py auto
        │
        ├─ 問：今日沙田或跑馬地有冇賽？第一場官方 postTime 幾點？
        │     冇 → 收工（零晨再試收昨夜賽果）
        │     有、第一場仍遠（>約 45 分鐘先到監控窗）→ 記低時間、收工等下一格
        │     有、接近第一場前 20 分鐘 → 等到監控窗再高頻抄賠率
        │     有、賽日進行中 → 高頻抄賠率
        │     有、全部完咗 → 抄官方賽果
        │
        ├─ 第一次真實寫入 → 刪晒示範 CSV
        ├─ 每個時間點：投注盤 getJSON 獨贏+位置+啡格（失敗改 GraphQL；紅／綠丟棄）
        ├─ 約每 45 秒重讀賽程：postTime 改 ≥ 2 分鐘就刪嗰場舊 checkpoint 再抄；取消／中止停抄；SCR／後備唔寫
        ├─ 延誤但未改鐘：唔當完場，延長監控最多 3 小時
        ├─ HTTP 429／403／斷線 → 退後 8–120 秒再試，之後減慢輪詢
        ├─ 啡格跟馬會投注盤官方顏色（標記 3）；舊數據先用跌幅門檻
        ├─ 符合 Telegram 規則 → Bot API 即刻 sendMessage
        ├─ 寫入 data/*.csv，大約每 120 秒 git push
        ├─ 接近 Actions 6 小時上限（約 5 小時 30 分）→ 開新 workflow 繼續
        └─ 鏡像到 docs/ 畀 GitHub Pages 顯示
```

瀏覽器 **唔會** 自己去馬會網站爬。你開網站只係讀 repo 入面已經寫好嘅 CSV。真正 crawl 只發生喺 GitHub Actions 嘅 Ubuntu runner。

---

## 二、去邊個網站、抄邊啲欄

全部只讀馬會 **公開** 接口，User-Agent 扮普通 Chrome，`Origin` / `Referer` 寫 `https://bet.hkjc.com/racing`（同官方投注頁一致）。GraphQL query 係馬會網頁用緊嗰條 **whitelist**；改字段會回 `WHITELIST_ERROR`，所以程式係原句送出，唔係自己發明 query。

### 1. 今日有冇賽、場次、中文馬名

| | |
| --- | --- |
| 網址 | `POST https://info.cld.hkjc.com/graphql/base/` |
| Query 名 | `raceMeetings`（`QUERY_RACE_MEETINGS_FULL`） |
| 參數 | `date` = 香港日期 `YYYY-MM-DD`，`venueCode` = `ST` 或 `HV` |
| 先試 | 沙田，冇 races 再試跑馬地 |

從 JSON 拎呢啲格：

| JSON 路徑 | 用途 |
| --- | --- |
| `raceMeetings[].venueCode` | 場地，只接受 `ST` / `HV` |
| `raceMeetings[].date` | 賽日 |
| `races[].no` | 第幾場 |
| `races[].postTime` | 開跑時間 → 轉成香港 `HH:MM:SS` |
| `races[].status` | 賽事狀態 |
| `runners[].no` | 馬號 |
| `runners[].name_ch` | **中文馬名**（優先） |
| `runners[].name_en` | 冇中文先用 |

如果 GraphQL 失敗，後備網頁：

| | |
| --- | --- |
| 網址 | `https://racing.hkjc.com/racing/information/Chinese/Racing/Fixture.aspx` |
| 抄法 | 所有 `<a href>` 入面 `RaceDate=YYYY/MM/DD`、`Racecourse=ST|HV`，或者連結文字有「沙田／Sha Tin」「跑馬地／Happy Valley」 |
| 另一後備 | 中文賽果頁 `LocalResults.aspx?RaceDate=…&Racecourse=ST&RaceNo=1`，用下拉 option 1–14 估有幾場 |

海外場地會被丟掉。

### 2. 即時獨贏、位置同啡格（主通道：投注盤）

呢條就係投注 app／bet.hkjc.com 即時盤用嘅公開 JSON，賠率同格色一齊嚟，唔使自己估 50% 先當啡格。

```
GET https://bet.hkjc.com/racing/getJSON.aspx
    ?type=winplaodds
    &date=YYYY-MM-DD
    &venue=ST 或 HV
    &start=場次
    &end=場次
```

回覆 JSON 入面 `OUT` 係一條字串，典型：

```
WIN;1=8.4=0;2=3.5=1;3=12=2;14=3.4=3#PLA;1=2.1=0;2=1.4=1
```

點拆：

1. 用 `#` 切開：前半獨贏，後半位置。
2. 每半邊用 `;` 切開。第一段係 `WIN` 或 `PLA` 標籤，其餘每段 `馬號=賠率=標記`。
3. **第一個數字** = 馬號；**第二個** = 賠率（寫入對應欄）。
4. **第三個** = 官方格色。只把 `3` 當啡格寫入 `hkjc_grid`／`place_grid`；`0`／`1` 紅／`2` 綠一律當 `none`。
5. 獨贏 map 同位置 map 分開填，最後用馬號合併成同一隻馬兩欄。

所以「crawl 邊一格」喺呢條通道就係：**`OUT` 字串、`#` 前 WIN 段、`#` 後 PLA 段、每個 `馬號=賠率=格色`。**

### 3. 即時賠率後備：GraphQL

| | |
| --- | --- |
| 網址 | 同一個 `POST https://info.cld.hkjc.com/graphql/base/` |
| Query 名 | `racing`（`QUERY_PM_POOLS_ODDS`） |
| 參數 | `date`、`venueCode`、`raceNo`、`oddsTypes: ["WIN", "PLA"]` |

回覆 `raceMeetings[0].pmPools[]` 係 **兩個獨立彩池**，唔係一格撈埋：

| 條件 | 抄邊格 | 寫入邊欄 |
| --- | --- | --- |
| `pmPools[].oddsType == "WIN"` | `oddsNodes[].combString` + `oddsValue` + `oddsDropValue` / `hotFavourite` | `win_odds`、`hkjc_grid` |
| `pmPools[].oddsType == "PLA"` | 同樣 | `place_odds`、`place_grid` |
| 其他 `oddsType`（QIN、QPL…） | **整池跳過** | 唔寫 |

`oddsDropValue == 3` 先當啡格；`hotFavourite`／紅／綠唔存。兩個 map 都空 → 當 getJSON 同 GraphQL 都失敗，唔會把空白當真實賠率。馬名用第 1 步已經備好嘅 `name_ch`。

### 4. 官方賽果同派彩

主通道係中文賽果頁（用瀏覽器打開就係你平日睇派彩嗰版）：

```
GET https://racing.hkjc.com/racing/information/Chinese/Racing/LocalResults.aspx
    ?RaceDate=YYYY/MM/DD
    &Racecourse=ST 或 HV
    &RaceNo=1 至 14
```

程式用 BeautifulSoup 搵 **整張表文字同時包含「名次」「馬號」「馬名」** 嗰個 `<table>`（英文頁就搵 Pla / Horse No / Horse / Win Odds）。然後按 **表頭欄名** 對列，唔係死記第幾格，因為馬會間中會加欄：

| 表頭（中文或英文） | 寫入 |
| --- | --- |
| 名次 / Pla. | `finish_rank` |
| 馬號 / Horse No | `horse_no` |
| 馬名 / Horse | `horse_name`（去掉尾 ` (C123)` 編號） |
| 獨贏賠率 / Win Odds | `final_sp`（終賠，唔係派彩） |

派彩係 **另一張表**：表內文字有「派彩」或 `DIVIDEND`。逐行睇第一格：

| 第一格 | 抄法 |
| --- | --- |
| `獨贏` 或 `WIN` | 該行馬號 + 金額（例如 `52.50`）→ `win_dividend`（每 $10） |
| `位置` 或 `PLACE` | 該行馬號 + 金額 → `placedividend` |

未中嘅馬派彩寫 `0`。呢兩個數字先係回測盈虧來源。

GraphQL 後備：`resultMeetings`，`resPools` 入面 `oddsType` WIN／PLA 嘅 `dividends[].winComb`（馬號）同 `div`（派彩）。呢條後備好多時 **冇名次**，所以優先用 HTML 成績表。

---

## 三、幾時抄、抄幾密

設定喺 `config.json` → `data`（網站數據中心可改門檻同間隔）：

| 設定 | 預設 | 意思 |
| --- | --- | --- |
| `checkpoints_minutes` | `[15, 10, 5, 1, 0]` | 只認呢幾個鐘點；**冇 3** |
| `scrape_interval_seconds` | `10` | 高頻時每隔幾秒問馬會 |
| `idle_poll_seconds` | `60` | 20 分鐘內都冇場要開，就問得慢啲 |
| `monitor_lead_minutes` | `20` | 第一場前幾多分鐘開始密問 |
| `monitor_trail_minutes` | `25` | 最後一場後再留幾耐 |
| `commit_every_seconds` | `120` | 幾耐先 git push 一次（存檔用；網站即時欄唔經呢條） |
| `brown_grid_drop_pct` | `50` | 舊數據（未有官方格色）先用嘅跌幅門檻 |

免費 GitHub Pages **唔係** live server。每次改 CSV 都要 git commit + Pages 重建／CDN，所以 120 秒係存檔節奏，唔係畫面節奏。以前 iPhone monitor 之所以密，幾乎肯定係部機自己問馬會。

免費情況下最密嘅做法：

| 通道 | 由邊度打 | 密到幾密 | 限制 |
| --- | --- | --- | --- |
| GraphQL `info.cld.hkjc.com/graphql/base/` | 你部瀏覽器（github.io） | 約 4 秒 | CORS `Access-Control-Allow-Origin: *`；要用官方 whitelist query |
| getJSON `bet.hkjc.com/racing/getJSON.aspx` | GitHub Actions | 10 秒存檔 | 由 github.io Origin 開會被擋／回 SPA HTML，唔能當網站 live |
| git push CSV | Actions → Pages | 約 120 秒 | 歷史時間點、走勢圖、回測 |

網站「即時」欄走 GraphQL（現在場 + 下一場）。Telegram 仍然係 Actions 抄到嗰下即刻送。

每一場開跑時間 `postTime` 減而家香港時間 = 仲有幾多分鐘。窗口只喺**該鐘點當刻或之後**先開，唔會提早 30–45 秒定格：

| 標籤 | 大約窗口 | 格色 |
| --- | --- | --- |
| T-15 | 15.0–13.5 分鐘 | 嗰下投注盤官方啡格（紅／綠丟棄） |
| T-10 | 10.0–8.5 | 同上 |
| T-5 | 5.0–3.5 | 同上 |
| （3 分鐘） | **唔抄** | — |
| T-1 | 1.0–0.5 | 同上 |
| T-0 | 開跑當刻至開跑後約 1.5 分鐘（期間覆寫到最後一盤） | 同上；終賠校正唔會改已經抄到嘅官方格色 |

T-15…T-1 唔再「窗口一開就定格」。系統把開賽前 16 分鐘到開跑後約 1.5 分鐘嘅每 10 秒獨贏／位置寫入 `odds_ticks.csv`，到點先揀**最接近嗰一下**（T-1 用已到達 1 分鐘嘅樣本，唔好用 1 分 40 秒前嗰下）。T-0 一直覆寫到收秤，再用官方終賠校正。

寫入長表 `data/odds_snapshots.csv` 一列嘅欄：

`race_date, venue, race_no, scheduled_time, checkpoint, capture_timestamp, horse_no, horse_name, win_odds, place_odds, prev_win_odds, win_drop_pct, is_brown_grid, hkjc_grid, place_grid`

之後 pivot 成寬表 `win_board.csv` / `place_board.csv`（一馬一行，T-15…T-0 各一欄）。網站下載鈕匯出嘅就係呢種寬表。`odds_board.csv` 係獨贏寬表別名。

---

## 四、點樣「分析」

### 啡格（跟馬會顯示，唔係自己估 50%）

新數據：`hkjc_grid == brown`（getJSON 標記 `3`，或者 GraphQL `oddsDropValue == 3`）先當啡格。紅格、綠格唔會寫入。

舊數據未有 `hkjc_grid`：先用跌幅門檻（預設 50%），方便示範同歷史列仍然睇到急跌。

```
跌幅% = (上一時間點獨贏 − 呢個時間點獨贏) / 上一時間點獨贏 × 100   ← 只係參考
啡格 = 馬會顯示啡格；冇官方格色先用 跌幅 ≥ 門檻
```

位置表用 **位置官方格色** 上色；策略同 Telegram 預設仍然用 **獨贏啡格** 做訊號。

### 策略回測（網站即時計，唔使再爬）

讀已經存檔嘅 CSV：

1. 只取你揀嘅 checkpoint（預設 T-1）而且官方獨贏啡格（舊數據先用跌幅門檻）。
2. 嗰刻 `win_odds` 要喺最低–最高範圍。
3. 用 `race_date + venue + race_no + horse_no` 對賽果。
4. 盈虧：
   - 獨贏：`win_dividend − 10`，派彩 0 就 −10
   - 位置：`placedividend − 10`（官方位置派彩；**唔用**開賽前 `place_odds` 去估）
   - 兩者：兩筆加總，本金 20
5. EV／ROI = 總盈虧 ÷ 總本金。

蒙地卡羅：每年落注場次 = 策略頻率 × 一年賽馬日（預設 88）。模擬下注次數係隨機重抽幾多條一年路徑，每條用歷史每注實際 PnL 有放回抽樣，畫資金 P10–P90。

---

## 五、點樣 send alert

程式 **唔經網站轉發**。Actions 跑緊 `snapshot_race` 寫完一列，即刻喺同一進程呼叫 Telegram。

### 要全部成立先會送

1. `telegram.enabled` 開咗，而且有 bot token（Secret 或環境變數）同 chat id。
2. 呢一列嘅 `checkpoint` **等於** Telegram 設定嗰個（預設 T-1）。其他時間點即使啡格都唔送。
3. 有有效獨贏。
4. 官方獨贏啡格（`hkjc_grid` = brown）。舊數據未有格色先用 `win_drop_pct` ≥ Telegram 門檻。
5. 獨贏喺 Telegram 最低–最高範圍。
6. 呢場呢隻馬今日未送過（每馬每場一條）。

投注方法（只買獨贏／位置／兩者）**唔影響準唔準則**，只寫入訊息，提醒你打算點買。

### 送到邊

```
POST https://api.telegram.org/bot<TOKEN>/sendMessage
```

內容包括：日期、場地、場次、開跑時間、馬號、中文馬名、獨贏由邊位跌到邊位、跌幅、**當時位置賠率**、你揀嘅投注方法、checkpoint、抄低時間（HKT）。

網站「發送測試訊息」會先由瀏覽器打同一條 Bot API；被 CORS 擋就改觸發 Actions `test-telegram`。

---

## 六、檔案去邊、網站點讀

| 檔 | 誰寫 | 誰讀 |
| --- | --- | --- |
| `data/odds_snapshots.csv` | Actions 監控 | 回測、網站 pivot |
| `data/win_board.csv` / `place_board.csv` | 每次 upsert 後重建 | 下載／核對 |
| `data/race_results.csv` | 收賽果 | 回測 EV |
| `config.json` | 你由網站儲存（PAT）或人手改 | Actions 每次 loop 重讀 |
| `status.json` / `logs/latest.log` | 監控 | 狀態頁 |
| `docs/` 下面嘅鏡像 | `copy_to_docs()` | GitHub Pages |

Pages 只係靜態檔。你撳「重新載入數據」= 再 fetch 呢啲 CSV，唔會即場問馬會。

---

## 七、真賽日同示範數據

| | 示範 | 真賽日 |
| --- | --- | --- |
| 邊個產生 | `generate_sample_data.py`（人手或 `demo-data`） | `scraper_runner.py auto` |
| 馬名 | 程式內建中文名單 | GraphQL `name_ch` |
| 獨贏／位置 | 隨機模擬，兩欄分開 | 馬會 WIN／PLA 兩池 |
| 派彩 | 用終賠估算 | 賽果頁派彩表 |
| 會唔會互相覆蓋 | 只喺你故意跑 `demo-data` | upsert：同一場同一時間點會更新，唔同時間點就追加 |

想核對「而家係咪真係抄緊馬會」：賽日開住 Actions log，應該見到 GraphQL 或 `getJSON winplaodds`，同埋 `Wrote N odds rows`。網站馬名應係中文，獨贏同位置數字唔應該成表相同。
