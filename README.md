# 台股主動式 ETF 每日追蹤

線上站台：[active-etf](https://nctuwanglin.github.io/active-etf/)。本機修改不會自動發布。

## 畫面與使用方式

| 分頁 | 內容 |
|---|---|
| 今日異動 | 同一持股期間的重大異動／共識；金額是收盤價估值，不是實際成交 |
| 各檔 ETF | 持股、規模、NAV、同日折溢價及來源日期 |
| 個股反查／趨勢 | 目前持有者、已出清事件、個股每日／累積淨調整、總持股、ETF 貢獻、CSV |
| 累積加減碼排行 | 5／20／60 日及全部歷史；依淨調整張數或同方向 ETF 家數排序，點股票開趨勢 |

趨勢預設 20 個交易日；60 日不足會顯示不足，不用較短歷史冒充。股票搜尋涵蓋歷史聯集，已全部出清股票仍可查詢。圖表單位是張（1,000 股），底下提供每日數據及持有家數。點柱狀圖或選日期可追溯逐 ETF 明細。

## 趨勢計算與限制

**這是持股端點變化估算，不是基金實際成交紀錄。**

```text
raw_delta      = 本期股數 − 前期股數
scale          = 共同持股股數比率的中位數
adjusted_delta = 本期股數 − 前期股數 × scale
```

- 趨勢從完整 history 重算，包含低於重大異動門檻的小幅變化；不直接加總 perf_stats。
- 一個視窗內使用固定 ETF 樣本：需每個日期都有有效持股，且每段均可比。圖表顯示「可比／追蹤」家數，不代表全市場完整買賣量。
- 同一股另遇疑似公司行動時，可再排除受影響 ETF，仍使用固定樣本；未取得完整公司行動調整資料，異常判斷僅為保守篩檢，不保證辨識所有配股／拆併股。
- 最早觀測只是基準，不算買入。新增與出清均套同一公式；缺整份快照不代表持股歸零。
- 缺資料是未知，不補成零；跨多日差額標為區間，不塞進恢復日。未知區間不拿來延續連續增持。
- 累積淨調整是各期估算之和，不等於期末總股數減期初總股數。增持量、減持量及原始差額分開保留。
- 股數先加總，最後才換張數／四捨五入。跨股票張數排序不是資金規模排序。
- 5 日與 20 日可能採不同樣本；不能直接相減推算中間期間。
- CSV 匯出含所有相關區間（包含未納入樣本者）、股數、校正值、品質、前後日期、快照來源及是否納入固定樣本。

`data/trading_calendar.json` 保存證交所例行休市表來源及涵蓋期間。目前涵蓋 2026-08-01 至 2026-12-31；9/25、9/28 等休市不當缺日。臨時休市需補入 `closed_dates`，不能由缺快照直接猜測。超出日曆範圍會顯示「觀測日」並拒絕提供未驗證的每日估算；新增年度前須更新官方日曆。

目前舊台新快照在 2026-09-10 前使用公告日，衍生趨勢會將這些記錄隔離，保留原因。它們沒有被改寫或自動減一天。其他同日修訂保留來源，以最新觀測版本為準。

## 更新與資料安全

- 自動排程：台北時間 14:20、18:00，GitHub 實際啟動可能延遲。
- 單檔抓取失敗沿用最新有效持股並標 stale；來源回舊也不能覆蓋較新資料。
- 先合併最新已知狀態，再決定發布日期；比較基準取每檔真正前一持股日。
- 同日持股不變仍抓行情與重新渲染，讓行情恢復、NAV 更正和 UI 改版生效。
- NAV 與報價日期都已知且相同才算折溢價。每證券保留 quote_date，TWSE／TPEx 日期不混用。
- 異動保存 from_date／to_date；每日共識只接受同一、相鄰交易期間。跨期調整保留在明細且顯示區間。
- 快照保存 meta。已存在的原始 history 不覆寫；同日修訂另存 `data/history/revisions/`。
- 先在暫存檔完成全部產物再替換；遇到一般寫入錯誤會回復原檔。多檔 rename 不是檔案系統交易，突然斷電仍須用最後成功標記和重建檢查一致性。
- 本機更新與離線重建共用 `.update.lock`；GitHub workflow 設定 concurrency。
- Pages 驗證比較完整 HTML 與 active.json 的 SHA-256；同日 UI 更正也驗得出來。

`--force` 只略過持股檔數驟降防護，不略過日期防倒退、來源驗證或價格同日檢查。

## 本機命令

使用已安裝 `requests` 的 Python 3.9+。目前唯一 Python runtime dependency 為 requests；圖表使用內嵌 SVG／JS，沒有 CDN 或前端框架。本機預覽請用 HTTP 伺服器開（例如 `python3 -m http.server`），直接雙擊 `index.html` 時趨勢資料載不進來（瀏覽器禁止 file:// fetch）。

```bash
# 不上網，不改 raw history／registry／perf_stats；重建目前頁面及衍生趨勢
python3 scripts/build_local.py

# 回歸測試
python3 -m unittest discover -s tests -q
node tests/test_trends_ui.js
node tests/test_dashboard_smoke.js

# 從官方來源更新；run_local.sh 會先 pull --rebase 及跑 Python 測試
scripts/run_local.sh
```

`test_dashboard_smoke.js` 是無網路的單元 DOM 模擬（stub fetch 讀本機 `data/stock_trends.json`），驗證頁面初始化、趨勢檔延遲載入、載入前點選排隊、載入失敗、切換、CSV；**不是瀏覽器視覺／手機版面驗收**。斷言不得依賴目前累積的歷史天數。GitHub 排程會在更新後對新產出的頁面執行兩個 JS 測試；實際更新程式仍只依賴 Python。

## 資料檔與 API v3

- `data/history/YYYY-MM-DD.json`：原始批次快照。
- `data/history/revisions/`：同批次後續修訂，含遞增 revision。
- `data/stock_trends.json`：可刪除重建的趨勢資料，schema_version=1、method=median-v1。
- `data/perf_stats.json`：事件庫；新版按 ETF／實際期間終點 upsert。首次正常更新將缺乏期間來源的舊事件原樣移至 `legacy_events`，避免與新版事件跨日期重複。下游分析請使用 `events`；`legacy_events` 僅供原始紀錄查核，不應併入買賣／績效加總。離線重建不動此檔。
- `active.json`：最新反向索引，schema_version=3；保留舊欄位並增加事件期間、行情日、趨勢內容 hash。
- `index.html`：頁面與當日資料（約 330 KB）；**不含趨勢資料**。2026-11-13 起趨勢改另檔載入——內嵌時頁面已長到 12 MB 且隨歷史天數持續變大。
- `data/stock_trends.json`：個股累積趨勢，頁面以 `data/stock_trends.json?v=<trend_build_id>` 載入（內容變更時網址必變，避開快取）。部署驗證會一併比對此檔。
- `docs/reviews/2026-10-03-migration.json`：離線重算品質／固定樣本／來源 hash 摘要。

### active.json 新增／修正語意

```jsonc
{
  "schema_version": 3,
  "updated": "2026-10-02",             // 發布批次標籤；不是每檔資料日期
  "trend_build_id": "...",             // 衍生趨勢內容 hash
  "build_id": "...",                   // 資料＋renderer／UI 資產版本
  "quote_failures": [],
  "etfs": {
    "00981A": {
      "data_date": "2026-10-02",
      "nav_date": "2026-10-02",
      "quote_date": "2026-10-02",
      "events": [{
        "code": "2330", "type": "INCREASE",
        "from_date": "2026-10-01", "to_date": "2026-10-02",
        "shares_delta": 1000,           // 原始持股差額
        "adjusted_shares_delta": 500,   // 校正估算；未知為 null
        "method": "median-v1", "daily_comparable": true
      }]
    }
  }
}
```

共識中的 shares_delta 延續 v2 的「校正估算」語意；股票 total_weight 是跨基金權重加總，只是熱度，不能當真實配置比例。stock.close 若為舊產物留下的價格但未知 quote_date，離線重建保留價格而不假造日期，total_value 留白；下次成功官方報價更新後恢復。

### 趨勢資料格式

`windows["5"|"20"|"60"|"all"]` 包含 available、from_date、to_date、dates、cohort_etfs、excluded_etfs、stocks。每個股票包含 series、net_delta、positive_delta、negative_delta、contributions 與股票層級排除項目。

完整區間以 `interval_table.fields/strings/rows` 無損字典編碼，降低檔案大小；可使用 `trends.unpack_intervals()` 或 `ETFTrends.unpack()` 還原。日期／ETF／股票／品質欄位是 strings 索引；source_snapshot_refs 為兩個 strings 索引。其他欄位為原數值／null。內建 method=median-v1、calculation_version=1。

歷史整合時請由 code＋ETF＋from_date＋to_date＋方法版本識別一段變化，不要由觀測批次日期重複累加。正式歷史回補／遷移應先檢查品質報告，再另行執行。

批次快照的新檔名日期採本批最新有效持股日，避免先更新的少數 ETF 被排除；它是資料上界而非抓取時間。CSV 的 `observed_date` 同樣是來源批次標籤。舊版超出批次標籤、無法確認來源的日期仍保守排除。

00996A（兆豐）停止追蹤（registry `status: disabled`）：兆豐網站自 2026-09-21 起對 GitHub Actions 回 HTTP 403（本機直抓正常），且沒有其他公開官方來源（證交所 PCF 僅供券商查詢），無法由 GitHub 排程自動更新。2026-11-13 曾重新啟用試抓，CI 仍被擋，11-14 依使用者決定再次停用。停用的 ETF 不抓取、不顯示，也不納入持股反查與累積趨勢；原始歷史快照保留供查核。adapter（`megafunds.py`）保留，若兆豐解除封鎖，把 status 改回 `active` 即可。

00413A（玉山）2026-11-13 起支援：`scripts/adapters/esun.py`，資料取自 esunam.com 的 ETFAPI JSON。

2026-10-29 修正：依證交所公告加入 10/23 薔琵颱風臨時休市，使 10/22 → 10/27 視為相鄰交易日。休市來源保存在日曆的 `exceptional_closures`。無完整可比樣本時，排行榜明確提示資料不足，不解讀為沒有加減碼。
