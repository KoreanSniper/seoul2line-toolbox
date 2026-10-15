from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
import time
from copy import deepcopy
import tkinter as tk
from tkinter import messagebox
import matplotlib
import matplotlib.pyplot as plt
from datetime import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from pathlib import Path
from app.economy import add_coins, balance, format_coins, spend_coins
from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame
from app.config import APP_DIR


# 한글 폰트 설정 (윈도우 기준)
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False
STATE_KEY = "korean_stock_game"
MARKET_PRICE_SCALE = 100
STOCKS_DB_PATH = APP_DIR / "stocks.db"
OFFLINE_CATCHUP_LIMIT = 500


class StockPriceEngine:
    """Keeps market prices alive while the user switches between tools."""

    def __init__(self, app: object) -> None:
        self.app = app
        self._db_lock = threading.RLock()
        STOCKS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(STOCKS_DB_PATH, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # 가격 갱신 스레드와 매수/매도 UI가 함께 접근해도 짧은 충돌은 SQLite가 기다리게 한다.
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
        self._initialize_database()
        self.state = self._load_database_state()
        self.stocks = self.state["stocks"]
        self.recent_trades = self._load_recent_trades()
        self._last_tick_at = self._load_last_tick_at()
        self.running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._price_lock = threading.RLock()
        self._listeners: set[object] = set()
        self.last_error = ""
        self.update_version = 0
        self._closed = False
        self._drift_stamp = ""
        self.market_average = 50000.0
        self.market_trend = 0
        self.market_label = "횡보장"
        self._market_stamp = ""
        self.refresh_drifts(datetime.now().strftime("%H:%M"))
        self.save_state()

    def _initialize_database(self) -> None:
        # sqlite3 연결을 만들고 stocks/holdings 테이블을 준비한다.
        # 기존 config.json 데이터가 있으면 DB가 비어 있을 때 한 번만 이전한다.
        with self._db:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS stocks (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    fallback REAL NOT NULL,
                    history TEXT NOT NULL,
                    volume_history TEXT NOT NULL DEFAULT '[]',
                    drift_low REAL NOT NULL,
                    drift_high REAL NOT NULL
                )
                """
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS holdings (
                    code TEXT PRIMARY KEY,
                    shares INTEGER NOT NULL,
                    avg_cost REAL NOT NULL
                )
                """
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    code TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    total INTEGER NOT NULL
                )
                """
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._db.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '3')"
            )
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(stocks)").fetchall()}
            if "volume_history" not in columns:
                self._db.execute("ALTER TABLE stocks ADD COLUMN volume_history TEXT NOT NULL DEFAULT '[]'")
        if self._db.execute("SELECT 1 FROM stocks LIMIT 1").fetchone() is None:
            legacy = self.app.config_store.get(STATE_KEY, default={})
            if isinstance(legacy, dict) and isinstance(legacy.get("stocks"), list) and legacy["stocks"]:
                self._write_database_state(legacy)
        self._remove_legacy_config()

    def _load_last_tick_at(self) -> float:
        try:
            row = self._db.execute("SELECT value FROM schema_meta WHERE key = 'last_tick_at'").fetchone()
            value = float(row[0]) if row else time.time()
            return value if math.isfinite(value) and value > 0 else time.time()
        except (TypeError, ValueError, OverflowError, sqlite3.DatabaseError):
            return time.time()

    def _save_last_tick_at(self, timestamp: float | None = None) -> None:
        value = float(timestamp if timestamp is not None else time.time())
        with self._db_lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('last_tick_at', ?)",
                (str(value),),
            )

    def _catch_up_elapsed(self) -> int:
        """중지·종료된 동안의 경과 시간을 가격 시뮬레이션으로 보충한다."""
        elapsed = max(0, int(time.time() - self._last_tick_at))
        if elapsed <= 0:
            return 0
        steps = min(elapsed, OFFLINE_CATCHUP_LIMIT)
        with self._price_lock:
            for _ in range(steps):
                self._advance_prices()
            self.state["stocks"] = self.stocks
        if not self.save_state():
            return 0
        self._last_tick_at = time.time()
        self._save_last_tick_at(self._last_tick_at)
        return elapsed

    def record_trade(self, action: str, code: str, shares: int, price: int) -> None:
        """거래 결과를 별도 테이블에 남겨 나중에 거래 내역을 복원할 수 있게 한다."""
        try:
            with self._db_lock, self._db:
                self._db.execute(
                    "INSERT INTO trade_history(created_at, action, code, shares, price, total) VALUES (?, ?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(timespec="seconds"), action, str(code), int(shares), int(price), int(shares) * int(price)),
                )
            self.recent_trades.insert(0, {
                "created_at": datetime.now().strftime("%m-%d %H:%M:%S"),
                "action": action,
                "code": str(code),
                "shares": int(shares),
                "price": int(price),
                "total": int(shares) * int(price),
            })
            del self.recent_trades[20:]
        except sqlite3.DatabaseError as exc:
            self.last_error = f"거래 내역 저장 실패: {exc}"

    def _load_recent_trades(self) -> list[dict[str, object]]:
        try:
            with self._db_lock:
                rows = self._db.execute(
                    "SELECT created_at, action, code, shares, price, total "
                    "FROM trade_history ORDER BY id DESC LIMIT 20"
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.DatabaseError as exc:
            self.last_error = f"거래 내역 읽기 실패: {exc}"
            return []

    def _load_database_state(self) -> dict[str, object]:
        with self._db_lock:
            stock_rows = self._db.execute(
                "SELECT code, name, fallback, history, volume_history, drift_low, drift_high FROM stocks ORDER BY rowid"
            ).fetchall()
        stocks = []
        for row in stock_rows:
            try:
                raw_history = json.loads(row["history"])
                history = [int(value) for value in raw_history if isinstance(value, (int, float)) and math.isfinite(value)]
            except (TypeError, ValueError, json.JSONDecodeError):
                history = []
            try:
                raw_volume = json.loads(row["volume_history"])
                volume_history = [max(1, int(value)) for value in raw_volume if isinstance(value, (int, float)) and math.isfinite(value)]
            except (TypeError, ValueError, json.JSONDecodeError, IndexError):
                volume_history = []
            try:
                low = float(row["drift_low"])
                high = float(row["drift_high"])
            except (TypeError, ValueError):
                low, high = 0.98, 1.02
            if not (math.isfinite(low) and math.isfinite(high) and 0 < low < 1 < high):
                low, high = 0.98, 1.02
            try:
                fallback = float(row["fallback"])
            except (TypeError, ValueError):
                fallback = 50000
            if not math.isfinite(fallback) or fallback <= 0:
                fallback = 50000
            stocks.append(
                {
                    "code": row["code"],
                    "name": row["name"],
                    "fallback": fallback,
                    "history": history[-500:],
                    "volume_history": volume_history[-500:],
                    "drift": [low, high],
                }
            )
        holdings = {}
        with self._db_lock:
            holding_rows = self._db.execute("SELECT code, shares, avg_cost FROM holdings").fetchall()
        for row in holding_rows:
            try:
                shares = max(0, int(row["shares"]))
                avg_cost = max(0.0, float(row["avg_cost"]))
            except (TypeError, ValueError):
                continue
            if shares:
                holdings[row["code"]] = {"shares": shares, "avg_cost": avg_cost}
        # DB가 일부만 남거나 중복/알 수 없는 종목을 포함해도 기본 14종목으로 복구한다.
        defaults = self._default_stocks()
        default_by_code = {str(stock["code"]): stock for stock in defaults}
        existing_by_code = {
            str(stock["code"]): stock for stock in stocks
            if str(stock.get("code", "")) in default_by_code
        }
        stocks = [existing_by_code.get(code, default_by_code[code]) for code in default_by_code]
        valid_codes = set(default_by_code)
        holdings = {code: position for code, position in holdings.items() if code in valid_codes}
        if not stocks:
            stocks = self._default_stocks()
            state = {"stocks": stocks, "holdings": holdings}
            self._write_database_state(state)
        elif len(existing_by_code) != len(default_by_code) or len(stock_rows) != len(default_by_code):
            self._write_database_state({"stocks": stocks, "holdings": holdings})
        return {"stocks": stocks, "holdings": holdings}

    @staticmethod
    def _default_stocks() -> list[dict[str, object]]:
        return [
            {"code": "005930", "name": "삼성", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "000660", "name": "SK", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "035420", "name": "NAVER", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "035720", "name": "카카오", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "373220", "name": "LG", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "005380", "name": "현대", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "000270", "name": "기아", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "068270", "name": "셀트리온", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "105560", "name": "KB", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "055550", "name": "신한", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "207940", "name": "삼성바이오로직스", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "012450", "name": "한화", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "005490", "name": "POSCO", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
            {"code": "323410", "name": "카카오뱅크", "fallback": 50000, "history": [], "drift": [0.98, 1.02]},
        ]

    def _write_database_state(self, state: dict[str, object]) -> None:
        stocks = state.get("stocks", [])
        holdings = state.get("holdings", {})
        with self._db:
            stock_list = stocks if isinstance(stocks, list) else []
            valid_codes = {str(stock["code"]) for stock in stock_list if isinstance(stock, dict) and "code" in stock}
            if valid_codes:
                placeholders = ",".join("?" for _ in valid_codes)
                self._db.execute(f"DELETE FROM stocks WHERE code NOT IN ({placeholders})", tuple(valid_codes))
            else:
                self._db.execute("DELETE FROM stocks")
            for stock in stock_list:
                if not isinstance(stock, dict):
                    continue
                code = str(stock.get("code", "")).strip()
                name = str(stock.get("name", code)).strip() or code
                if not code:
                    continue
                try:
                    fallback = float(stock.get("fallback", 50000))
                except (TypeError, ValueError):
                    fallback = 50000
                if not math.isfinite(fallback) or fallback <= 0:
                    fallback = 50000
                drift = stock.get("drift", [0.98, 1.02])
                try:
                    low, high = float(drift[0]), float(drift[1])
                except (TypeError, ValueError, IndexError):
                    low, high = 0.98, 1.02
                if not (math.isfinite(low) and math.isfinite(high) and 0 < low < 1 < high):
                    low, high = 0.98, 1.02
                history = stock.get("history", [])
                if not isinstance(history, list):
                    history = []
                clean_history = []
                for value in history[-500:]:
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        continue
                    if value > 0:
                        clean_history.append(value)
                volume_history = stock.get("volume_history", [])
                if not isinstance(volume_history, list):
                    volume_history = []
                clean_volume = []
                for value in volume_history[-500:]:
                    try:
                        clean_volume.append(max(1, int(value)))
                    except (TypeError, ValueError):
                        continue
                self._db.execute(
                    """
                    INSERT OR REPLACE INTO stocks(code, name, fallback, history, volume_history, drift_low, drift_high)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code, name, fallback,
                        json.dumps(clean_history), json.dumps(clean_volume), low, high,
                    ),
                )
            self._db.execute("DELETE FROM holdings")
            if isinstance(holdings, dict):
                for code, position in holdings.items():
                    try:
                        if isinstance(position, dict):
                            shares = int(position.get("shares", 0))
                            avg_cost = float(position.get("avg_cost", 0))
                        else:
                            shares = int(position)
                            avg_cost = 0.0
                    except (TypeError, ValueError):
                        continue
                    if not math.isfinite(avg_cost) or avg_cost < 0:
                        avg_cost = 0.0
                    if shares > 0 and str(code) in valid_codes:
                        self._db.execute(
                            "INSERT OR REPLACE INTO holdings(code, shares, avg_cost) VALUES (?, ?, ?)",
                            (str(code), shares, avg_cost),
                        )

    def save_state(self) -> bool:
        """상태 저장 실패가 가격 갱신 스레드를 죽이지 않도록 재시도한다."""
        for attempt in range(3):
            try:
                with self._price_lock, self._db_lock:
                    self._write_database_state(self.state)
                self.last_error = ""
                return True
            except sqlite3.OperationalError as exc:
                self.last_error = f"SQLite 저장 대기 중: {exc}"
                if attempt < 2 and "locked" in str(exc).lower():
                    time.sleep(0.15 * (attempt + 1))
                    continue
                return False
            except sqlite3.DatabaseError as exc:
                self.last_error = f"SQLite 저장 실패: {exc}"
                return False
        return False

    def save_prices(self) -> bool:
        """가격 스레드에서는 holdings 전체를 다시 쓰지 않고 가격 데이터만 저장한다."""
        try:
            with self._price_lock, self._db_lock, self._db:
                for stock in self.stocks:
                    self._db.execute(
                        "UPDATE stocks SET fallback = ?, history = ?, volume_history = ?, drift_low = ?, drift_high = ? WHERE code = ?",
                        (
                            float(stock.get("fallback", 50000)),
                            json.dumps(stock.get("history", [])[-500:]),
                            json.dumps(stock.get("volume_history", [])[-500:]),
                            float(stock.get("drift", [0.98, 1.02])[0]),
                            float(stock.get("drift", [0.98, 1.02])[1]),
                            str(stock.get("code", "")),
                        ),
                    )
                self._db.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('last_tick_at', ?)",
                    (str(time.time()),),
                )
            self.last_error = ""
            return True
        except sqlite3.OperationalError as exc:
            self.last_error = f"SQLite 가격 저장 대기 중: {exc}"
            return False
        except sqlite3.DatabaseError as exc:
            self.last_error = f"SQLite 가격 저장 실패: {exc}"
            return False

    def _remove_legacy_config(self) -> None:
        data = getattr(self.app.config_store, "data", None)
        if not isinstance(data, dict) or STATE_KEY not in data:
            return
        data.pop(STATE_KEY, None)
        try:
            self.app.config_store.save()
        except (OSError, TypeError, ValueError):
            return

    def add_listener(self, listener: object) -> None:
        self._listeners.add(listener)

    def remove_listener(self, listener: object) -> None:
        self._listeners.discard(listener)

    def start(self) -> None:
        with self._thread_lock:
            if self._closed:
                return
            if self._thread and self._thread.is_alive():
                if self._stop_event.is_set():
                    self._thread.join(timeout=1.2)
                if self._thread.is_alive():
                    return
            self._catch_up_elapsed()
            self._stop_event.clear()
            self.running = True
            self._thread = threading.Thread(target=self._run, daemon=True, name="KoreanStockPrices")
            self._thread.start()

    def stop(self) -> None:
        with self._thread_lock:
            self.running = False
            self._stop_event.set()

    def close(self) -> None:
        self._closed = True
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=7.0)
        if self._thread and self._thread.is_alive():
            self.last_error = "가격 스레드가 종료되지 않아 DB 연결을 유지합니다."
            return
        with self._db_lock:
            if self._db:
                self._db.close()
                self._db = None

    def toggle(self) -> bool:
        if self.running:
            self.stop()
        else:
            self.start()
        return self.running

    def _run(self) -> None:
        # threading.Thread가 실행하는 백그라운드 루프다.
        # Tkinter 위젯은 직접 건드리지 않고 데이터 저장과 listener 호출만 담당한다.
        try:
            while not self._stop_event.wait(1):
                self._advance_prices()
                self.state["stocks"] = self.stocks
                if not self.save_prices():
                    continue
                self.update_version += 1
                for listener in tuple(self._listeners):
                    try:
                        listener()
                    except Exception as exc:
                        self.last_error = f"UI 갱신 실패: {exc}"
        except Exception as exc:
            self.last_error = f"가격 엔진 중단: {exc}"
        finally:
            self._last_tick_at = time.time()
            try:
                self._save_last_tick_at(self._last_tick_at)
            except sqlite3.DatabaseError as exc:
                self.last_error = f"마지막 갱신 시각 저장 실패: {exc}"
            self.running = False

    def _advance_prices(self) -> None:
        # history 평균과 drift를 이용해 다음 가격을 계산하고 history에 기록한다.
        # UI 갱신은 별도의 after() 콜백에서 처리해야 하므로 이 함수는 위젯을 만지지 않는다.
        stamp = datetime.now().strftime("%H:%M")
        self.refresh_drifts(stamp)
        with self._price_lock:
            self._refresh_market(stamp)
            for stock in self.stocks:
                history = stock["history"][-100:]
                history_price = (sum(history) if sum(history) != 0 else 50000) / (len(history) if history else 1)
                avg_price = history_price * 0.7 + self.market_average * 0.3
                reversion = (avg_price - stock["fallback"]) / avg_price
                drift = random.uniform(stock["drift"][0], stock["drift"][1])
                change = (drift - 1) + reversion * 0.05 + self.market_trend * 0.0008
                old_price = float(stock["fallback"])
                stock["fallback"] *= 1 + change
                if random.randint(1, 10000) == 1:
                    stock["fallback"] *= random.uniform(1.05, 1.15)
                stock["fallback"] = max(100, stock["fallback"])
                stock["history"].append(int(stock["fallback"]))
                volume = max(1, int(800 + abs(stock["fallback"] - old_price) * 2 + random.randint(0, 900)))
                stock.setdefault("volume_history", []).append(volume)
                while len(stock["history"]) > 500:
                    stock["history"].pop(0)
                while len(stock["volume_history"]) > 500:
                    stock["volume_history"].pop(0)

    def _refresh_market(self, stamp: str) -> None:
        """시장 기준값을 조금씩 움직여 상승장·하락장·횡보장을 만든다."""
        if stamp != self._market_stamp:
            self._market_stamp = stamp
            self.market_trend = random.choices((-1, 0, 1), weights=(30, 40, 30), k=1)[0]
            self.market_label = {-1: "하락장", 0: "횡보장", 1: "상승장"}[self.market_trend]
        if self.market_trend:
            self.market_average += self.market_trend * random.uniform(40, 130)
        else:
            self.market_average += random.uniform(-55, 55)
        self.market_average = max(100, self.market_average)

    def refresh_drifts(self, stamp: str) -> None:
        if stamp == self._drift_stamp:
            return
        with self._price_lock:
            for stock in self.stocks:
                distance = random.randint(1, 7) / 100
                stock["drift"] = [round(1 - distance, 2), round(1 + distance, 2)]
            self._drift_stamp = stamp

    def reset_market(self) -> tuple[int, int]:
        liquidation_value = 0
        liquidated_shares = 0
        with self._price_lock:
            old_stocks = deepcopy(self.stocks)
            old_holdings = deepcopy(self.state.get("holdings", {}))
            holdings = self.state.get("holdings", {})
            if isinstance(holdings, dict):
                for code, position in holdings.items():
                    if isinstance(position, dict):
                        shares = int(position.get("shares", 0))
                    else:
                        shares = int(position)
                    liquidated_shares += max(0, shares)
                    stock = next((item for item in self.stocks if item["code"] == code), None)
                    if stock is not None:
                        liquidation_value += max(1, round(float(stock["fallback"]) / MARKET_PRICE_SCALE)) * max(0, shares)

            for stock in self.stocks:
                stock["fallback"] = 50000
                stock["history"] = [50000] * 100
                stock["volume_history"] = [1000] * 100
            self.state["stocks"] = self.stocks
            self.state["holdings"] = {}
            self._drift_stamp = ""
            if not self.save_state():
                self.stocks[:] = old_stocks
                self.state["stocks"] = self.stocks
                self.state["holdings"] = old_holdings
                return 0, 0

        if liquidation_value:
            try:
                add_coins(self.app.config_store, liquidation_value)
            except (OSError, ValueError, TypeError):
                with self._price_lock:
                    self.stocks[:] = old_stocks
                    self.state["stocks"] = self.stocks
                    self.state["holdings"] = old_holdings
                    self.save_state()
                return 0, 0
        return liquidation_value, liquidated_shares



class KoreanStockGame(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.engine: StockPriceEngine = app.stock_price_engine
        self.state = self.engine.state
        self.stocks = self.engine.stocks
        self.selected_code = self.stocks[0]["code"]
        self.status = tk.StringVar(value="구매를 눌러 주식을 구매하세요")
        self._status_until = 0.0
        self.rows: dict[str, dict[str, tk.Label]] = {}
        self.qty_var = tk.StringVar(value="1")
        self.graph_all = False
        self.graph_view_button: RoundedButton | None = None
        self.graph_options = {
            "ma": tk.BooleanVar(value=True),
            "bollinger": tk.BooleanVar(value=True),
            "baseline": tk.BooleanVar(value=True),
        }
        self._destroyed = False
        self._refresh_job: str | None = None
        self._poll_job: str | None = None
        self._seen_update_version = -1
        self._last_engine_error = ""
        self._build()
        self.engine.start()
        self._apply_price_refresh()
        self._poll_job = self.after(250, self._poll_price_updates)

    def destroy(self) -> None:
        self._destroyed = True
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        if hasattr(self, "graph_fig"):
            plt.close(self.graph_fig)
        super().destroy()

    def _on_price_update(self) -> None:
        return

    def _poll_price_updates(self) -> None:
        if self._destroyed or not self.winfo_exists():
            return
        if self._seen_update_version != self.engine.update_version:
            self._seen_update_version = self.engine.update_version
            self._apply_price_refresh()
        if self.engine.last_error and self.engine.last_error != self._last_engine_error:
            self._last_engine_error = self.engine.last_error
            self._set_status(self.engine.last_error, seconds=8.0)
        refresh_button = getattr(self.app, "_refresh_stock_price_button", None)
        if callable(refresh_button):
            refresh_button()
        self._poll_job = self.after(250, self._poll_price_updates)


    def _save_state(self) -> bool:
        return self.engine.save_state()

    def _set_status(self, message: str, seconds: float = 4.0) -> None:
        self.status.set(message)
        self._status_until = time.monotonic() + seconds


        

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="한국 주식 미니게임", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="가상 한국 종목이 있는 가상 주식 미니게임입니다. 거래는 100원 = 1 TC 환산가로 진행합니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).grid(row=1, column=0, sticky="w")

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        market = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=18, padding=14)
        market.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        market.body.columnconfigure(0, weight=1)
        tk.Label(market.body, text="시장", font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["surface"]).pack(anchor="w")
        header_row = tk.Frame(market.body, bg=colors["surface"])
        header_row.pack(fill="x", pady=(10, 4))
        for text, width in (("종목", 15), ("시뮬레이션 종가", 13), ("보유", 7), ("평균", 9), ("평가", 10), ("손익", 10)):
            tk.Label(header_row, text=text, width=width, anchor="w", font=("Segoe UI", 8, "bold"), fg=colors["subtle"], bg=colors["surface"]).pack(side="left")
        for stock in self.stocks:
            self._stock_row(market.body, stock)

        side = tk.Frame(body, bg=colors["panel"])
        side.grid(row=0, column=1, sticky="nsew")
        trade = RoundedFrame(side, colors, colors["panel_soft"], colors["border"], radius=16, padding=14)
        trade.pack(fill="x")
        tk.Label(trade.body, text="주문", font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(anchor="w")
        self.selected_label = tk.Label(trade.body, text="", font=("Segoe UI", 11, "bold"), fg=colors["text"], bg=colors["panel_soft"])
        self.selected_label.pack(anchor="w", pady=(12, 4))
        qty_row = tk.Frame(trade.body, bg=colors["panel_soft"])
        qty_row.pack(fill="x", pady=(8, 8))
        tk.Label(qty_row, text="수량", font=("Segoe UI", 9), fg=colors["muted"], bg=colors["panel_soft"]).pack(side="left")
        tk.Entry(qty_row, textvariable=self.qty_var, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", width=10, justify="right").pack(side="right", ipady=6)
        actions = tk.Frame(trade.body, bg=colors["panel_soft"])
        actions.pack(fill="x")
        RoundedButton(actions, "매수", self.buy_selected, colors, accent=True, compact=False, radius=12).pack(side="left", fill="x", expand=True, padx=(0, 5))
        RoundedButton(actions, "매도", self.sell_selected, colors, compact=False, radius=12).pack(side="left", fill="x", expand=True, padx=(5, 0))
        RoundedButton(trade.body, "시장 초기화", self.reset_market, colors, compact=True, radius=10).pack(fill="x", pady=(8, 0))
        tk.Label(trade.body, textvariable=self.status, font=("Segoe UI", 9), fg=colors["muted"], bg=colors["panel_soft"], wraplength=280, justify="left").pack(anchor="w", fill="x", pady=(12, 0))

        portfolio = RoundedFrame(side, colors, colors["panel_soft"], colors["border"], radius=16, padding=14)
        portfolio.pack(fill="both", expand=True, pady=(14, 0))
        portfolio_header = tk.Frame(portfolio.body, bg=colors["panel_soft"])
        portfolio_header.pack(fill="x")
        tk.Label(portfolio_header, text="포트폴리오", font=("Segoe UI", 13, "bold"), fg=colors["text"], bg=colors["panel_soft"]).pack(side="left")
        self.graph_view_button = RoundedButton(
            portfolio_header,
            "전체 보기",
            self.toggle_graph_view,
            colors,
            compact=True,
            radius=9,
        )
        self.graph_view_button.pack(side="right")
        indicator_bar = tk.Frame(portfolio.body, bg=colors["panel_soft"])
        indicator_bar.pack(fill="x", pady=(8, 0))
        for key, label in (("ma", "MA"), ("bollinger", "볼린저"), ("baseline", "기준선")):
            tk.Checkbutton(
                indicator_bar,
                text=label,
                variable=self.graph_options[key],
                command=self._draw_graph,
                bg=colors["panel_soft"],
                fg=colors["muted"],
                activebackground=colors["panel_soft"],
                activeforeground=colors["text"],
                selectcolor=colors["field"],
                font=("Segoe UI", 8),
                padx=2,
            ).pack(side="left")
        self.graph_fig, self.graph_ax = plt.subplots(figsize=(4, 3))

        self.canvas = FigureCanvasTkAgg(self.graph_fig, master=portfolio)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True, pady=(14, 0))
        portfolio_scroll = tk.Frame(portfolio.body, bg=colors["panel_soft"])
        portfolio_scroll.pack(fill="x", pady=(12, 0))
        portfolio_scroll.columnconfigure(0, weight=1)
        self.portfolio_label = tk.Text(
            portfolio_scroll,
            height=5,
            wrap="word",
            font=("Segoe UI", 10),
            fg=colors["text"],
            bg=colors["panel_soft"],
            insertbackground=colors["text"],
            relief="flat",
            borderwidth=0,
            state="disabled",
        )
        self.portfolio_label.grid(row=0, column=0, sticky="ew")
        portfolio_bar = tk.Scrollbar(portfolio_scroll, orient="vertical", command=self.portfolio_label.yview)
        portfolio_bar.grid(row=0, column=1, sticky="ns")
        self.portfolio_label.configure(yscrollcommand=portfolio_bar.set)
        self._select(self.selected_code)

    def _stock_row(self, parent: tk.Widget, stock: dict[str, object]) -> None:
        colors = palette(self.app.dark_mode)
        code = str(stock["code"])
        row = tk.Frame(parent, bg=colors["surface_hover"], highlightthickness=1, highlightbackground=colors["border"])
        row.pack(fill="x", pady=4)
        row.bind("<Button-1>", lambda _event, code=code: self._select(code))
        labels: dict[str, tk.Label] = {}
        for key, text, width, bold in (
            ("name", f"{stock['name']} {code}", 15, True),
            ("price", "-", 11, False),
            ("owned", "0", 7, False),
            ("avg", "-", 9, False),
            ("value", "-", 10, True),
            ("profit", "-", 10, True),
        ):
            label = tk.Label(row, text=text, width=width, anchor="w", font=("Segoe UI", 9, "bold" if bold else "normal"), fg=colors["text"], bg=colors["surface_hover"])
            label.pack(side="left", padx=(8 if key == "name" else 0, 0), pady=9)
            label.bind("<Button-1>", lambda _event, code=code: self._select(code))
            labels[key] = label
        self.rows[code] = labels

    def _select(self, code: str) -> None:
        self.selected_code = code
        stock = self._stock(code)
        price = self._price(code)
        self.selected_label.configure(
            text=f"{stock['name']} {code} / {price:,}원 ({format_coins(self._trade_price(code))})\n"
            f"{stock['drift'][0]}~{stock['drift'][1]}"
        )
        self._refresh_rows()
        if hasattr(self, "graph_ax"):
            self._draw_graph()

    def toggle_graph_view(self) -> None:
        self.graph_all = not self.graph_all
        if self.graph_view_button is not None:
            self.graph_view_button.text = "선택 종목 보기" if self.graph_all else "전체 보기"
            self.graph_view_button._draw()
        self._draw_graph()

    def _draw_graph(self) -> None:
        if self._destroyed or not self.winfo_exists():
            return
        self.graph_fig.clear()
        price_ax = self.graph_fig.add_subplot(111)
        self.graph_ax = price_ax
        price_ax.grid(True, alpha=0.16, linewidth=0.6)
        price_ax.set_ylabel("가격")
        price_ax.set_xlabel("시간(초)")
        if self.graph_all:
            color_map = plt.get_cmap("tab20")
            divisor = max(len(self.stocks) - 1, 1)
            for index, stock in enumerate(self.stocks):
                history = stock["history"]
                price_ax.plot(
                    history,
                    label=f"{stock['name']} {stock['code']}",
                    color=color_map(index / divisor),
                    linewidth=1.4,
                )
            if self.graph_options["baseline"].get():
                price_ax.axhline(50000, color="#888888", linestyle="--", linewidth=0.8, label="기준 50,000원")
            price_ax.set_title("전체 종목 그래프")
            price_ax.legend(loc="upper left", fontsize=7, ncol=2)
        else:
            stock = self._stock(self.selected_code)
            history = stock["history"]
            values = [float(value) for value in history]
            if len(history) < 2:
                price_ax.plot(history, color="#3498db", linewidth=2)
            else:
                segments = [
                    [(index, history[index]), (index + 1, history[index + 1])]
                    for index in range(len(history) - 1)
                ]
                colors = [
                    "#e74c3c" if history[index + 1] >= history[index] else "#3498db"
                    for index in range(len(history) - 1)
                ]
                price_ax.add_collection(LineCollection(segments, colors=colors, linewidths=2))
                price_ax.autoscale_view()
            if self.graph_options["ma"].get():
                price_ax.plot(self._rolling_mean(values, 20), color="#f39c12", linewidth=1.2, label="MA20")
                price_ax.plot(self._rolling_mean(values, 50), color="#9b59b6", linewidth=1.2, label="MA50")
            if self.graph_options["bollinger"].get():
                middle = self._rolling_mean(values, 20)
                upper, lower = [], []
                for index, mean in enumerate(middle):
                    if math.isnan(mean):
                        upper.append(math.nan)
                        lower.append(math.nan)
                        continue
                    window = values[max(0, index - 19):index + 1]
                    deviation = math.sqrt(sum((item - mean) ** 2 for item in window) / len(window))
                    upper.append(mean + deviation * 2)
                    lower.append(mean - deviation * 2)
                price_ax.plot(upper, color="#7f8c8d", linewidth=0.9, linestyle=":", label="볼린저 상단")
                price_ax.plot(lower, color="#7f8c8d", linewidth=0.9, linestyle=":", label="볼린저 하단")
                price_ax.fill_between(range(len(values)), lower, upper, color="#95a5a6", alpha=0.08)
            if self.graph_options["baseline"].get() and values:
                price_ax.axhline(values[0], color="#16a085", linestyle="--", linewidth=0.9, label=f"기준 {values[0]:,.0f}원")
            if history:
                low_index = min(range(len(history)), key=history.__getitem__)
                high_index = max(range(len(history)), key=history.__getitem__)
                low_value = history[low_index]
                high_value = history[high_index]
                price_ax.scatter(
                    [high_index], [high_value], color="#f1c40f", s=42,
                    zorder=5, label=f"최고 {high_value:,}원",
                )
                price_ax.scatter(
                    [low_index], [low_value], color="#00bcd4", s=42,
                    zorder=5, label=f"최저 {low_value:,}원",
                )
                price_ax.annotate(
                    f"최고 {high_value:,}원", (high_index, high_value),
                    xytext=(0, 10), textcoords="offset points", ha="center",
                    fontsize=8, color="#9a7d0a",
                )
                price_ax.annotate(
                    f"최저 {low_value:,}원", (low_index, low_value),
                    xytext=(0, -16), textcoords="offset points", ha="center",
                    fontsize=8, color="#008c9e",
                )
            change_rate = ((values[-1] - values[-2]) / values[-2] * 100) if len(values) > 1 and values[-2] else 0.0
            total_rate = ((values[-1] - values[0]) / values[0] * 100) if values and values[0] else 0.0
            price_ax.set_title(f"{stock['name']} 그래프 | 이전 대비 {change_rate:+.2f}% | 시작 대비 {total_rate:+.2f}%")
            price_ax.legend(loc="upper left", fontsize=7, ncol=2)
        self.canvas.draw_idle()

    @staticmethod
    def _rolling_mean(values: list[float], period: int) -> list[float]:
        result = [math.nan] * len(values)
        for index in range(period - 1, len(values)):
            result[index] = sum(values[index - period + 1:index + 1]) / period
        return result

    @staticmethod
    def _rsi(values: list[float], period: int) -> list[float]:
        result = [math.nan] * len(values)
        if len(values) <= period:
            return result
        gains = [max(0.0, values[index] - values[index - 1]) for index in range(1, len(values))]
        losses = [max(0.0, values[index - 1] - values[index]) for index in range(1, len(values))]
        for index in range(period, len(values)):
            average_gain = sum(gains[index - period:index]) / period
            average_loss = sum(losses[index - period:index]) / period
            result[index] = 100.0 if average_loss == 0 else 100 - (100 / (1 + average_gain / average_loss))
        return result

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(value * alpha + result[-1] * (1 - alpha))
        return result

    @classmethod
    def _macd(cls, values: list[float]) -> tuple[list[float], list[float]]:
        fast = cls._ema(values, 12)
        slow = cls._ema(values, 26)
        macd = [fast[index] - slow[index] for index in range(len(values))]
        return macd, cls._ema(macd, 9)

    def _stock(self, code: str) -> dict[str, object]:
        return next(stock for stock in self.stocks if stock["code"] == code)

    def _price(self, code: str) -> int:
        return int(self._stock(code)["fallback"])

    def _trade_price(self, code: str) -> int:
        return max(1, round(self._price(code) / MARKET_PRICE_SCALE))

    def _owned(self, code: str) -> int:
        holdings = self.state.get("holdings", {})
        if not isinstance(holdings, dict):
            return 0
        position = holdings.get(code, 0)
        try:
            if isinstance(position, dict):
                return max(0, int(position.get("shares", 0)))
            return max(0, int(position))
        except (TypeError, ValueError):
            return 0

    def _avg_cost(self, code: str) -> float:
        holdings = self.state.get("holdings", {})
        if not isinstance(holdings, dict):
            return 0.0
        position = holdings.get(code, 0)
        if isinstance(position, dict):
            try:
                return max(0.0, float(position.get("avg_cost", 0)))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _quantity(self) -> int | None:
        try:
            qty = int(self.qty_var.get().strip())
        except ValueError:
            self.status.set("수량은 정수로 입력하세요.")
            return None
        if qty <= 0:
            self.status.set("수량은 1 이상이어야 합니다.")
            return None
        if qty > 1_000_000:
            self.status.set("한 번에 최대 1,000,000주까지 거래할 수 있습니다.")
            return None
        return qty

    def refresh_prices(self) -> None:
        self._apply_price_refresh()

    def reset_market(self) -> None:
        if not messagebox.askyesno(
            "시장 초기화",
            "모든 종목을 50,000원으로 초기화하고 보유 주식을 전부 매도할까요?",
            parent=self,
        ):
            return
        liquidation_value, liquidated_shares = self.engine.reset_market()
        self._apply_price_refresh()
        self._set_status(
            f"시장 초기화 완료 / {liquidated_shares:,}주 자동 매도 / "
            f"{format_coins(liquidation_value)} 정산"
        )

    def _apply_price_refresh(self) -> None:
        self._refresh_job = None
        if self._destroyed or not self.winfo_exists():
            return
        stamp = datetime.now().strftime("%H:%M")
        self.engine.refresh_drifts(stamp)
        if time.monotonic() >= self._status_until:
            self.status.set(
                f"{len(self.stocks)}개 종가 반영 / {self.engine.market_label} / "
                f"시장 기준 {self.engine.market_average:,.0f}원 / 갱신 {stamp}"
            )
        self._select(self.selected_code)

    def buy_selected(self) -> None:
        qty = self._quantity()
        if qty is None:
            return
        with self.engine._price_lock:
            price = self._trade_price(self.selected_code)
            cost = price * qty
            try:
                affordable = spend_coins(self.app.config_store, cost)
            except (OSError, ValueError, TypeError):
                self._set_status("매수 실패: 재화 저장에 실패했습니다.")
                return
            if not affordable:
                self.status.set(f"매수 실패: {format_coins(cost)} 필요")
                return
            holdings = self.state.setdefault("holdings", {})
            old_position = holdings.get(self.selected_code)
            owned = self._owned(self.selected_code)
            avg_cost = self._avg_cost(self.selected_code)
            new_owned = owned + qty
            new_avg = ((avg_cost * owned) + cost) / max(1, new_owned)
            holdings[self.selected_code] = {"shares": new_owned, "avg_cost": round(new_avg, 2)}
            if not self._save_state():
                if old_position is None:
                    holdings.pop(self.selected_code, None)
                else:
                    holdings[self.selected_code] = old_position
                add_coins(self.app.config_store, cost)
                self.status.set("매수 실패: 주식 저장에 실패했습니다.")
                return
            self.engine.record_trade("매수", self.selected_code, qty, price)
        self._set_status(f"{self._stock(self.selected_code)['name']} {qty:,}주 매수 / 평균 {format_coins(round(new_avg))}")
        self._refresh_rows()

    def sell_selected(self) -> None:
        qty = self._quantity()
        if qty is None:
            return
        owned = self._owned(self.selected_code)
        if owned < qty:
            self.status.set("보유 수량이 부족합니다.")
            return
        with self.engine._price_lock:
            price = self._trade_price(self.selected_code)
            holdings = self.state.setdefault("holdings", {})
            old_position = holdings.get(self.selected_code)
            remaining = owned - qty
            if remaining <= 0:
                holdings.pop(self.selected_code, None)
            else:
                holdings[self.selected_code] = {"shares": remaining, "avg_cost": round(self._avg_cost(self.selected_code), 2)}
            if not self._save_state():
                if old_position is not None:
                    holdings[self.selected_code] = old_position
                self.status.set("매도 실패: 주식 저장에 실패했습니다.")
                return
            try:
                add_coins(self.app.config_store, price * qty)
            except (OSError, ValueError, TypeError):
                if old_position is not None:
                    holdings[self.selected_code] = old_position
                else:
                    holdings.pop(self.selected_code, None)
                self._save_state()
                self.status.set("매도 실패: 재화 저장에 실패했습니다.")
                return
            self.engine.record_trade("매도", self.selected_code, qty, price)
        self._set_status(f"{self._stock(self.selected_code)['name']} {qty:,}주 매도")
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        if self._destroyed or not self.winfo_exists():
            return
        try:
            total = balance(self.app.config_store)
            lines = [f"현금성 재화: {format_coins(total)}"]
            stock_total = 0
            cost_total = 0.0
            for stock in self.stocks:
                code = str(stock["code"])
                price = self._price(code)
                trade_price = self._trade_price(code)
                owned = self._owned(code)
                avg_cost = self._avg_cost(code)
                value = owned * trade_price
                cost_basis = owned * avg_cost
                profit = value - cost_basis
                stock_total += value
                cost_total += cost_basis
                row = self.rows.get(code)
                if row:
                    row["price"].configure(text=f"{price:,}원")
                    row["owned"].configure(text=f"{owned:,}")
                    row["avg"].configure(text=format_coins(round(avg_cost)) if owned else "-")
                    row["value"].configure(text=format_coins(value))
                    row["profit"].configure(text=self._profit_text(profit, cost_basis))
                    bg = palette(self.app.dark_mode)["accent_soft"] if code == self.selected_code else palette(self.app.dark_mode)["surface_hover"]
                    for label in row.values():
                        label.master.configure(bg=bg)
                        label.configure(bg=bg)
                if owned:
                    lines.append(f"{stock['name']}: {owned:,}주 / 평가 {format_coins(value)} / 손익 {self._profit_text(profit, cost_basis)}")
            lines.append(f"주식 평가: {format_coins(stock_total)}")
            lines.append(f"총 평가: {format_coins(total + stock_total)}")
            if cost_total:
                lines.append(f"누적 수익률: {self._profit_text(stock_total - cost_total, cost_total)}")
            if self.engine.recent_trades:
                lines.append("최근 거래")
                for trade in self.engine.recent_trades[:5]:
                    lines.append(
                        f"{trade['created_at']} {trade['action']} {trade['code']} "
                        f"{int(trade['shares']):,}주 / {format_coins(int(trade['total']))}"
                    )
            self.portfolio_label.configure(state="normal")
            self.portfolio_label.delete("1.0", "end")
            self.portfolio_label.insert("1.0", "\n".join(lines))
            self.portfolio_label.configure(state="disabled")
        except tk.TclError:
            self._destroyed = True

    def _profit_text(self, profit: float, basis: float) -> str:
        if basis <= 0:
            return "-"
        sign = "+" if profit >= 0 else ""
        rate = profit / basis * 100
        return f"{sign}{format_coins(round(profit))} ({sign}{rate:.1f}%)"


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return KoreanStockGame(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("minigame.korean_stocks", "한국 주식", "미니게임", build, 26))
