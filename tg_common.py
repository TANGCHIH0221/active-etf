# -*- coding: utf-8 -*-
"""Telegram 推播與狀態檔的共用工具。

刻意跟報告邏輯分開放:之後要加「券商分點」那支腳本時,直接 import 這裡的
tg_send / load_state / save_state 就好,不必再抄一份 HTTP 重試與時區邏輯。
"""
import html
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAIPEI = timezone(timedelta(hours=8))

# Telegram 單則訊息上限 4096 字元。留餘裕給分段標題,超過就切段。
TG_LIMIT = 3800
API = "https://api.telegram.org/bot{token}/sendMessage"


def now_tpe():
    return datetime.now(TAIPEI)


def session_date(now=None):
    """把一次執行歸到哪個「交易日場次」。

    GitHub 排程會延遲 1-3 小時,22:30 那班可能被推到台灣時間隔天凌晨才跑。
    若直接用當下日期,那班會誤判成「新的一天沒資料」而重複發提醒。
    故凌晨 06:00 前的執行一律歸給前一天。
    """
    n = now or now_tpe()
    d = n.date()
    if n.hour < 6:
        d -= timedelta(days=1)
    return d.isoformat()


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def fmt_amount(yuan):
    """金額 → 人看得懂的字串。None 代表算不出來。"""
    if yuan is None:
        return "—"
    v, sign = abs(yuan), ("-" if yuan < 0 else "+")
    if v >= 1e8:
        return "%s%.2f 億" % (sign, v / 1e8)
    if v >= 1e4:
        return "%s%.0f 萬" % (sign, v / 1e4)
    return "%s%.0f 元" % (sign, v)


def fmt_lots(shares):
    """股 → 張(1 張 = 1000 股),台股習慣單位。"""
    if shares is None:
        return "—"
    lots = shares / 1000.0
    sign = "-" if lots < 0 else "+"
    a = abs(lots)
    if a >= 100:
        return "%s%s 張" % (sign, format(int(round(a)), ","))
    return "%s%.1f 張" % (sign, a)


# ---------------------------------------------------------------- 狀態檔

def load_state(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        # 狀態檔壞掉不該讓整支腳本掛掉;當成首次執行重新開始,頂多少一次連續天數。
        print("[warn] 狀態檔讀取失敗 (%s),視為首次執行" % e)
        return None


def save_state(path, state):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)          # 原子寫入:中途被砍不會留半個壞檔


# ---------------------------------------------------------------- 推播

def _chunks(text):
    """照行切段,不把一行切斷。單行超長才硬切。"""
    out, buf = [], ""
    for line in text.split("\n"):
        while len(line) > TG_LIMIT:
            out.append(line[:TG_LIMIT])
            line = line[TG_LIMIT:]
        if len(buf) + len(line) + 1 > TG_LIMIT:
            out.append(buf.rstrip("\n"))
            buf = ""
        buf += line + "\n"
    if buf.strip():
        out.append(buf.rstrip("\n"))
    return out


def tg_send(text, token=None, chat_id=None, dry_run=False):
    """發送訊息。回傳 True 表示成功(dry-run 也算成功)。"""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    parts = _chunks(text)

    if dry_run or not token or not chat_id:
        why = "--dry-run" if dry_run else "未設定 TELEGRAM_BOT_TOKEN/CHAT_ID"
        print("=" * 60)
        print("[dry-run: %s] 共 %d 則訊息" % (why, len(parts)))
        print("=" * 60)
        for i, p in enumerate(parts, 1):
            print("----- 第 %d/%d 則 (%d 字) -----" % (i, len(parts), len(p)))
            print(p)
        return True

    import requests

    ok = True
    for i, part in enumerate(parts, 1):
        for attempt in range(1, 4):
            try:
                r = requests.post(
                    API.format(token=token),
                    json={"chat_id": chat_id, "text": part,
                          "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=30,
                )
                if r.status_code == 429:
                    wait = 5
                    try:
                        wait = int(r.json()["parameters"]["retry_after"]) + 1
                    except Exception:
                        pass
                    print("[warn] 被限流,等 %ds 重試" % wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                print("[ok] 已送出第 %d/%d 則" % (i, len(parts)))
                break
            except Exception as e:
                print("[warn] 第 %d/%d 則第 %d 次嘗試失敗: %s" % (i, len(parts), attempt, e))
                if attempt == 3:
                    ok = False
                else:
                    time.sleep(attempt * 3)
        time.sleep(1)   # 同一 chat 連發要間隔,免得觸發限流
    return ok
