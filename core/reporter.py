# -*- coding: utf-8 -*-
"""第 9 步 · 自动复盘报告（Reporter）——第三个信号出口 ``report_plan``。

**9.0 报告只报成交、不报拦截 = 替闸门掩盖**
================================================================
报告不是「另算一套」的旁路，必须与引擎同源：

1. **同源**：信号/成交/持仓只读 ``account.trades``、``account.rejected_orders``、
   ``paper_trader.bills`` 与 ``signal_gate.decision_log()``，**禁止 Reporter 重跑
   策略或自行统计拦截数**。
2. **披露被拦掉的信号**：按 ``config.REPORT_CONFORMANCE["suppression_reasons"]``
   逐项计数 ``warmup / stale / off_session / limit_up_down / volume_limit /
   risk_block``；「0 笔交易」必须拆解为「策略无信号」/「闸门拦截 N 笔」
   （``zero_trade_disclosure=True``），否则 fail-closed 锁死在报告里完全不可见。
3. **明日候选是未登记的信号出口**：已登记为 ``report_plan``，候选必须逐标的过
   ``signal_gate.check_plan_candidate``；预热期/停更/非交易时段不得进入候选清单
   （``include_observations=True`` 时才可显示为「仅供观察」），并标注数据截至日期。
4. **绩效同源**：日/周/月报的胜率、盈亏比、最大回撤、年化直接复用引擎
   ``BacktestResult.metrics`` 或 ``core.backtester.calc_metrics``，不另算一份。
5. **自动发送**：走 ``core/notifier.py``，发送前过数据时效闸门
   （``auto_send_requires_fresh=True``），停更只发数据告警、不发交易内容。

**报告格式（9.5）**：Jinja2 模板（``templates/``）渲染单文件 HTML，CSS 内联；
图表优先 plotly 交互图，plotly 缺失时降级 matplotlib 静态图（base64 内嵌）；
可选 PDF 导出（需 wkhtmltopdf + pdfkit，缺失时跳过并告警，不影响 HTML）。
"""
from __future__ import annotations

import base64
import html
import io
import logging
import shutil
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

import config
import core.signal_gate as signal_gate
from core.backtester import calc_metrics
from core.notifier import BaseNotifier, create_notifiers
from core.utils import get_trading_sessions, is_trading_day

try:                                            # Jinja2：9.5 要求模板渲染
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from markupsafe import Markup
    HAS_JINJA2 = True
except Exception:                               # noqa: BLE001 —— 无 Jinja2 时降级
    HAS_JINJA2 = False
    Markup = str                                # type: ignore

try:                                            # plotly：交互图
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except Exception:                               # noqa: BLE001
    HAS_PLOTLY = False

try:                                            # matplotlib：plotly 缺失时的静态图
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:                               # noqa: BLE001
    HAS_MPL = False

logger = logging.getLogger(__name__)

PERF_FIELDS = ("total_return", "annual_return", "max_drawdown", "sharpe",
               "sortino", "calmar", "win_rate", "profit_factor", "trade_count",
               "avg_holding_days", "total_commission")

METRIC_LABELS = {
    "total_return": "总收益率", "annual_return": "年化收益", "max_drawdown": "最大回撤",
    "sharpe": "夏普比率", "sortino": "索提诺比率", "calmar": "卡玛比率",
    "win_rate": "胜率", "profit_factor": "盈亏比", "trade_count": "交易笔数",
    "avg_holding_days": "平均持仓天数", "total_commission": "手续费合计",
    "benchmark_return": "基准收益", "excess_return": "超额收益",
    "information_ratio": "信息比率", "volatility": "波动率",
    "avg_margin_utilization": "平均保证金使用率", "margin_call_count": "爆仓次数",
}

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


class Reporter:
    """自动复盘报告：同源取数 + 拦截披露 + 候选闸门 + 图表 + 自动发送。"""

    def __init__(self,
                 paper_trader=None,
                 backtester=None,
                 result=None,
                 report_dir=None,
                 notifiers: Optional[List[BaseNotifier]] = None,
                 fresh_checker: Optional[Callable] = None,
                 in_session_checker: Optional[Callable] = None,
                 sentiment_provider: Optional[Callable] = None,
                 template_dir=None,
                 embed_plotly_js: bool = False,
                 logger: Optional[logging.Logger] = None) -> None:
        self.paper_trader = paper_trader
        self.backtester = backtester
        self.result = result
        self.report_dir = Path(report_dir or config.REPORT_DIR)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.notifiers = list(notifiers) if notifiers else create_notifiers()
        self.fresh_checker = fresh_checker
        self.in_session_checker = in_session_checker or _default_in_session
        self.sentiment_provider = sentiment_provider
        self.template_dir = Path(template_dir or TEMPLATE_DIR)
        self.embed_plotly_js = bool(embed_plotly_js)
        self.logger = logger or globals()["logger"]
        self._env = self._make_env()

    def _make_env(self):
        if not HAS_JINJA2:
            self.logger.warning("[报告] 未安装 Jinja2，HTML 渲染降级为内置简化模板")
            return None
        try:
            return Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=select_autoescape(["html", "xml"]),
                trim_blocks=True, lstrip_blocks=True)
        except Exception as exc:                # noqa: BLE001
            self.logger.error("[报告] Jinja2 模板目录不可用：%s", exc)
            return None

    # ------------------------------------------------------------------
    # 同源取数
    # ------------------------------------------------------------------
    @property
    def account(self):
        return getattr(self.paper_trader, "account", None)

    def _last_result(self):
        if self.result is not None:
            return self.result
        for attr in ("result", "_last_result"):
            found = getattr(self.backtester, attr, None)
            if found is not None:
                return found
        return None

    def metrics(self) -> dict:
        """绩效口径唯一来源：引擎结果 → 引擎 calc_metrics，绝不另算。"""
        result = self._last_result()
        if result is not None and getattr(result, "metrics", None) is not None:
            return dict(result.metrics)
        if self.paper_trader is None:
            return {}
        account = self.account
        if account is None:
            return {}
        nav = self._nav_frame()
        trades = self._trade_frame()
        if not len(nav) or not len(trades):
            return {}
        return dict(calc_metrics(nav, trades,
                                 initial_capital=getattr(account, "initial_capital",
                                                         None)))

    def _nav_frame(self) -> pd.DataFrame:
        bills = list(getattr(self.paper_trader, "bills", []) or [])
        if bills:
            return pd.DataFrame(bills)
        account = self.account
        rows = list(getattr(account, "daily_equity", []) or []) if account else []
        return pd.DataFrame(rows)

    def _trade_frame(self) -> pd.DataFrame:
        return pd.DataFrame(list(getattr(self.account, "trades", []) or []))

    def trades(self, on: _date = None) -> List[dict]:
        items = list(getattr(self.account, "trades", []) or [])
        if on is None:
            return items
        return [t for t in items if _same_day(t.get("timestamp"), on)]

    def positions(self) -> List[dict]:
        account = self.account
        if account is None:
            return []
        out = []
        for direction, book in (("long", getattr(account, "positions", {}) or {}),
                                ("short", getattr(account, "short_positions", {}) or {})):
            for symbol, pos in dict(book).items():
                volume = float(getattr(pos, "volume", 0) or 0)
                if volume == 0:
                    continue
                cost = float(getattr(pos, "avg_cost", 0) or 0)
                price = float(getattr(pos, "last_price", None)
                              or getattr(pos, "market_price", None) or cost)
                prev = _to_float(getattr(pos, "prev_close", None)
                                 or getattr(pos, "pre_close", None))
                change = (price / prev - 1.0) if prev else _to_float(
                    getattr(pos, "change_pct", None))
                out.append({"symbol": str(symbol), "direction": direction,
                            "volume": volume, "avg_cost": cost, "price": price,
                            "day_change": change,
                            "pnl": (price - cost) * volume
                            * (1 if direction == "long" else -1)})
        return out

    # ------------------------------------------------------------------
    # 拦截披露（报告的核心）
    # ------------------------------------------------------------------
    def collect_suppressions(self, on: _date = None) -> Dict:
        """合并 account.rejected_orders 与 signal_gate 裁决日志（按 reject_id 去重）。

        ``on`` 仅为 API 兼容保留：拒单记录可能无时间戳，按日过滤会漏计，
        因此默认统计全量拦截记录。
        """
        _ = on
        reasons = list(signal_gate.suppression_reasons())
        items: List[dict] = []
        seen = set()

        def _add(rec: dict, source: str) -> None:
            if rec.get("status") not in (None, "rejected") and rec.get("allowed"):
                return
            if rec.get("allowed") is True:
                return
            key = rec.get("reject_id")
            if key is not None and key in seen:
                return
            if key is not None:
                seen.add(key)
            code = str(rec.get("code") or rec.get("reason_code")
                       or signal_gate.classify_rejection(rec.get("reason")))
            items.append({
                "symbol": str(rec.get("symbol", "")),
                "direction": str(rec.get("direction", "")),
                "code": code,
                "reason": str(rec.get("reason", "")),
                "source": str(rec.get("source") or source),
                "reject_id": key,
            })

        for rec in list(getattr(self.account, "rejected_orders", []) or []):
            _add(dict(rec), "place_order")
        for rec in signal_gate.decision_log():
            if rec.get("allowed") is False:
                _add(dict(rec), rec.get("source", "place_order"))

        counts = {r: 0 for r in reasons}
        for item in items:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
        return {"counts": counts, "items": items, "total": len(items),
                "reasons": reasons}

    def zero_trade_text(self, trade_count: int, suppression: Dict) -> str:
        """「0 笔交易」必须拆解，禁止笼统显示 0。"""
        if trade_count > 0:
            return ""
        total = int(suppression.get("total", 0))
        if total > 0:
            detail = "、".join(f"{k} {v} 笔" for k, v in
                              suppression.get("counts", {}).items() if v)
            return f"0 笔交易 = 策略无信号 0 笔 + 闸门拦截 {total} 笔（{detail}）"
        return "0 笔交易：策略无信号（当日无拦截记录）"

    # ------------------------------------------------------------------
    # 明日候选（report_plan 第三出口）
    # ------------------------------------------------------------------
    def build_plan(self, candidates: Dict[str, dict] = None,
                   now: datetime = None, include_observations: bool = False) -> Dict:
        """候选必须过 signal_gate.check_plan_candidate + 时效/时段闸门。

        ``candidates``：``{symbol: bar}`` 或 ``{symbol: {"bar": bar, "market": m}}``；
        ``bar`` 必须带 ``warmup_ok / data_asof_date / price_adjust``。
        """
        now = now or datetime.now()
        plan, excluded = [], []
        for symbol, payload in dict(candidates or {}).items():
            if isinstance(payload, dict) and "bar" in payload:
                bar = payload["bar"]
                market = str(payload.get("market") or self._market_of(symbol))
            else:
                bar = payload
                market = self._market_of(symbol)

            fresh_ok, asof = self._bar_fresh(bar, market, now)
            in_session = bool(self.in_session_checker(market, now))
            rejection = signal_gate.check_plan_candidate(
                bar, fresh_ok=fresh_ok, in_session=in_session, symbol=symbol)
            if rejection is not None:
                code = rejection.get("stage", "stale")
                row = {"symbol": str(symbol), "market": market,
                       "code": code, "reason": rejection.get("reason", ""),
                       "data_asof_date": asof,
                       "tag": _observation_tag(code)}
                if include_observations:
                    row["observable"] = True
                    plan.append(row)
                else:
                    excluded.append(row)
                continue
            plan.append({"symbol": str(symbol), "market": market,
                         "close": _to_float(bar.get("close")),
                         "data_asof_date": asof, "warmup_ok": True,
                         "tag": "已过预热/时效/时段闸门"})
        return {"plan": plan, "excluded": excluded}

    def _market_of(self, symbol: str) -> str:
        market_of = getattr(self.paper_trader, "market_of", None)
        if isinstance(market_of, dict):
            return str(market_of.get(symbol) or "cn_stock")
        if callable(market_of):
            try:
                return str(market_of(symbol) or "cn_stock")
            except Exception:                   # noqa: BLE001
                pass
        return "cn_stock"

    def _bar_fresh(self, bar: dict, market: str, now: datetime):
        """数据时效（refetch 同源口径）：返回 (fresh, asof_str)。"""
        if self.fresh_checker is not None:
            try:
                return bool(self.fresh_checker(bar, market, now)), _asof_str(bar)
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 时效校验失败：%s", exc)
                return False, _asof_str(bar)
        asof = _asof_date(bar)
        if asof is None:
            return False, "未知"
        limit = int(config.STALE_LIMIT.get("daily", 5))
        days = _trading_days_between(asof, _to_date(now), market)
        return days <= limit, asof.isoformat()

    # ------------------------------------------------------------------
    # 市场情绪（可注入；无数据源时如实标注，不编造）
    # ------------------------------------------------------------------
    def market_sentiment(self, day: _date = None, sentiment: dict = None) -> Dict:
        day = _to_date(day)
        if sentiment is None and self.sentiment_provider is not None:
            try:
                sentiment = self.sentiment_provider(day)
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 市场情绪取数失败：%s", exc)
        if sentiment is None:
            sentiment = self._cached_index_sentiment(day)
        data = _normalize_sentiment(sentiment)
        data["available"] = any(v is not None for k, v in data.items()
                                if k not in ("available", "source", "index_name"))
        return data

    def _cached_index_sentiment(self, day: _date) -> Optional[dict]:
        """离线兜底：读本地指数日线缓存算大盘涨跌（不联网、不编造）。"""
        raw_dir = Path(config.DATA_CACHE_DIR) / "raw"
        try:
            files = sorted(raw_dir.glob("cn_index_*_daily_*.csv"))
        except Exception:                       # noqa: BLE001
            return None
        for path in files:
            try:
                df = pd.read_csv(path)
                date_col = _first_col(df, ("date", "日期", "time", "datetime"))
                close_col = _first_col(df, ("close", "收盘", "收盘价"))
                if date_col is None or close_col is None:
                    continue
                df = df[[date_col, close_col]].dropna()
                df["_d"] = pd.to_datetime(df[date_col]).dt.date
                df = df[df["_d"] <= day].tail(2)
                if len(df) < 2:
                    continue
                change = float(df[close_col].iloc[-1] / df[close_col].iloc[-2] - 1.0)
                symbol = path.name.split("_")[2] if "_" in path.name else path.stem
                return {"index_name": symbol, "index_change": change,
                        "source": f"本地指数缓存 {path.name}"}
            except Exception:                   # noqa: BLE001
                continue
        return None

    # ------------------------------------------------------------------
    # 日报
    # ------------------------------------------------------------------
    def generate_daily_report(self, date: _date = None, auto_send: bool = False,
                              candidates: Dict[str, dict] = None,
                              sentiment: dict = None,
                              events: List = None,
                              pdf: bool = False) -> Dict:
        day = _to_date(date)
        trades = self.trades(day)
        suppression = self.collect_suppressions(day)
        plan_info = self.build_plan(candidates, now=_end_of_day(day))
        metrics = self.metrics()
        positions = self.positions()
        account = self.account

        equity = _account_value(account, "equity")
        cash = _account_value(account, "cash")
        initial = _account_value(account, "initial_capital")
        position_value = sum(abs(p["volume"] * p["price"]) for p in positions)
        exposure = (position_value / equity) if equity else 0.0
        daily_pnl = self._daily_pnl(day)
        market_pnl: Dict[str, float] = {}
        market_count: Dict[str, int] = {}
        for t in trades:
            key = str(t.get("market") or "unknown")
            market_pnl[key] = market_pnl.get(key, 0.0) + float(t.get("pnl") or 0.0)
            market_count[key] = market_count.get(key, 0) + 1

        sentiment_data = self.market_sentiment(day, sentiment)
        risk = _risk_check(equity, exposure, positions, account, daily_pnl)

        report = {
            "kind": "daily",
            "date": day.isoformat(),
            "data_asof": self._data_asof_str(),
            "equity": equity, "cash": cash, "initial_capital": initial,
            "daily_pnl": daily_pnl,
            "total_pnl": (equity - initial) if equity and initial else None,
            "exposure": exposure,
            "positions": positions,
            "trades": trades,
            "trade_count": len(trades),
            "suppressions": suppression,
            "suppression_total": suppression["total"],
            "plan": plan_info["plan"],
            "excluded": plan_info["excluded"],
            "metrics": metrics,
            "market_pnl": market_pnl,
            "sentiment": sentiment_data,
            "zero_trade_text": self.zero_trade_text(len(trades), suppression),
            "risk": risk,
        }
        report.update(self._daily_view(report, market_count, events))
        report["charts"] = {"equity": self._chart_equity(
            self._nav_frame(), "权益曲线", first=True)}
        report["traps"] = self._traps()
        report["trap_rows"] = _trap_rows(report["traps"])

        title = f"每日复盘 {day.isoformat()}"
        html_text = self.render_html(report, title=title)
        path = self.report_dir / f"daily_{day.isoformat()}.html"
        path.write_text(html_text, encoding="utf-8")
        report["html_path"] = str(path)
        report["pdf_path"] = self._export_pdf(path) if pdf else None

        if auto_send:
            report["sent"] = self._auto_send(
                title, self._summary_text(report), day)
        return report

    def _daily_pnl(self, day: _date) -> Optional[float]:
        """当日盈亏：账单权益差分（引擎产物），无账单时返回 None。"""
        nav = self._nav_frame()
        if not len(nav) or "equity" not in nav.columns or "date" not in nav.columns:
            return None
        try:
            nav = nav.copy()
            nav["date"] = pd.to_datetime(nav["date"]).dt.date
            nav = nav[nav["date"] <= day].sort_values("date")
            if len(nav) < 2:
                return None
            return float(nav["equity"].iloc[-1] - nav["equity"].iloc[-2])
        except Exception:                       # noqa: BLE001
            return None

    def _daily_view(self, report: Dict, market_count: Dict, events) -> Dict:
        metrics = report["metrics"]
        sent = report["sentiment"]
        supp = report["suppressions"]
        return {
            "perf_rows": _perf_rows(metrics),
            "account_rows": [
                ("总权益", _fmt(report["equity"])),
                ("可用资金", _fmt(report["cash"])),
                ("当日盈亏", _signed(report["daily_pnl"])),
                ("总盈亏", _signed(report["total_pnl"])),
                ("仓位比例", _pct(report["exposure"])),
                ("初始资金", _fmt(report["initial_capital"])),
            ],
            "position_rows": [
                [p["symbol"], _dir_text(p["direction"]), f"{p['volume']:g}",
                 _num(p["avg_cost"]), _num(p["price"]), _signed(p["pnl"]),
                 _pct_signed(p["day_change"])] for p in report["positions"]],
            "trade_rows": [
                [_when(t.get("timestamp")), t.get("symbol", ""),
                 t.get("market", ""), _dir_text(t.get("direction")),
                 _num(t.get("price")), f"{_to_float(t.get('volume')) or 0:g}",
                 _signed(t.get("pnl"))] for t in report["trades"]],
            "market_pnl_rows": [
                [k, _signed(v), market_count.get(k, 0)]
                for k, v in report["market_pnl"].items()],
            "sentiment_rows": _sentiment_rows(sent),
            "sentiment_note": "" if sent.get("available") else
            "市场情绪数据源未接入：可注入 sentiment_provider 或直接传 sentiment= "
            "{index_change, up_count, down_count, limit_up, limit_down, turnover, "
            "northbound}；本报告不编造缺失数据。",
            "risk_rows": _risk_rows(report["risk"]),
            "suppression_count_rows": [
                [k, v] for k, v in supp["counts"].items()],
            "suppression_detail_rows": [
                [i["symbol"], _dir_text(i["direction"]), i["code"],
                 i["reason"], i["source"]] for i in supp["items"]],
            "executed_rows": [
                [_when(t.get("timestamp")), t.get("symbol", ""),
                 _dir_text(t.get("direction")), _num(t.get("price")),
                 f"{_to_float(t.get('volume')) or 0:g}"]
                for t in report["trades"]],
            "plan_rows": [
                [p["symbol"], p.get("market", ""), _num(p.get("close")),
                 str(p.get("data_asof_date", "")), p.get("tag", "")]
                for p in report["plan"]],
            "excluded_rows": [
                [x["symbol"], x.get("market", ""), x.get("code", ""),
                 x.get("tag", ""), str(x.get("data_asof_date", ""))]
                for x in report["excluded"]],
            "event_rows": _event_rows(events),
        }

    # ------------------------------------------------------------------
    # 周报 / 月报
    # ------------------------------------------------------------------
    def generate_weekly_report(self, end_date: _date = None,
                               auto_send: bool = False, pdf: bool = False) -> Dict:
        return self._generate_period("weekly", end_date, auto_send, days=7, pdf=pdf)

    def generate_monthly_report(self, end_date: _date = None,
                                auto_send: bool = False, pdf: bool = False) -> Dict:
        return self._generate_period("monthly", end_date, auto_send, days=30, pdf=pdf)

    def _generate_period(self, period: str, end_date, auto_send: bool,
                         days: int, pdf: bool = False) -> Dict:
        end = _to_date(end_date)
        start = end - timedelta(days=days)
        trades = [t for t in self.trades()
                  if start <= _to_date(t.get("timestamp")) <= end]
        nav = self._nav_window(start, end)
        suppression = self.collect_suppressions()
        # 绩效同源：窗口净值 + 交易交给引擎 calc_metrics，不另算一份
        metrics = self._period_metrics(nav, trades)

        report = {
            "kind": "period",
            "period": period, "start": start.isoformat(), "end": end.isoformat(),
            "data_asof": self._data_asof_str(),
            "trades": trades, "trade_count": len(trades),
            "suppressions": suppression, "suppression_total": suppression["total"],
            "metrics": metrics,
            "zero_trade_text": self.zero_trade_text(len(trades), suppression),
        }
        report.update(self._period_view(report, nav, trades))
        report["charts"] = {
            "equity": self._chart_equity(nav, "区间权益曲线", first=True),
            "heatmap": self._chart_heatmap(nav, "月度收益热力图", first=False),
            "pnl_hist": self._chart_pnl_hist(trades, "逐笔盈亏分布", first=False),
        }
        report["traps"] = self._traps()
        report["trap_rows"] = _trap_rows(report["traps"])

        title = f"{'周报' if period == 'weekly' else '月报'} " \
                f"{start.isoformat()} ~ {end.isoformat()}"
        path = self.report_dir / f"{period}_{end.isoformat()}.html"
        path.write_text(self.render_html(report, title=title), encoding="utf-8")
        report["html_path"] = str(path)
        report["pdf_path"] = self._export_pdf(path) if pdf else None
        if auto_send:
            report["sent"] = self._auto_send(title, self._summary_text(report), end)
        return report

    def _nav_window(self, start: _date, end: _date) -> pd.DataFrame:
        nav = self._nav_frame()
        if not len(nav) or "date" not in nav.columns:
            return nav
        nav = nav.copy()
        nav["_d"] = pd.to_datetime(nav["date"]).dt.date
        return nav[(nav["_d"] >= start) & (nav["_d"] <= end)].drop(columns=["_d"])

    def _period_metrics(self, nav: pd.DataFrame, trades: List[dict]) -> Dict:
        result = self._last_result()
        if result is not None and getattr(result, "metrics", None):
            return dict(result.metrics)
        if not len(nav) or not trades:
            return {}
        return dict(calc_metrics(nav, pd.DataFrame(trades),
                                 initial_capital=getattr(self.account,
                                                         "initial_capital", None)))

    def _period_view(self, report: Dict, nav: pd.DataFrame,
                     trades: List[dict]) -> Dict:
        metrics = report["metrics"]
        stats = _trade_stats(trades)
        extremes = _extreme_trades(trades)
        first_equity, last_equity = _nav_ends(nav)
        return {
            "perf_rows": _perf_rows(metrics),
            "overview_rows": [
                ("期初权益", _fmt(first_equity)),
                ("期末权益", _fmt(last_equity)),
                ("区间收益", _pct(metrics.get("total_return"))),
                ("最大回撤", _pct(metrics.get("max_drawdown"))),
                ("交易笔数", str(report["trade_count"])),
                ("拦截笔数", str(report["suppression_total"])),
            ],
            "trade_stats_rows": [
                ("盈利笔数", str(stats["wins"])),
                ("亏损笔数", str(stats["losses"])),
                ("胜率（引擎口径）", _pct(metrics.get("win_rate"))),
                ("平均盈利", _signed(stats["avg_win"])),
                ("平均亏损", _signed(stats["avg_loss"])),
                ("盈亏比（引擎口径）", _num(metrics.get("profit_factor"))),
                ("最大单笔盈利", _signed(stats["best_pnl"])),
                ("最大单笔亏损", _signed(stats["worst_pnl"])),
            ],
            "extreme_rows": [
                [kind, _when(t.get("timestamp")), t.get("symbol", ""),
                 _dir_text(t.get("direction")), _num(t.get("price")),
                 f"{_to_float(t.get('volume')) or 0:g}", _signed(t.get("pnl"))]
                for kind, t in extremes],
            "param_review": _param_review(metrics, report["trade_count"]),
            "suppression_count_rows": [
                [k, v] for k, v in report["suppressions"]["counts"].items()],
            "suppression_detail_rows": [
                [i["symbol"], _dir_text(i["direction"]), i["code"],
                 i["reason"], i["source"]]
                for i in report["suppressions"]["items"]],
        }

    # ------------------------------------------------------------------
    # 回测专项报告
    # ------------------------------------------------------------------
    def generate_backtest_report(self, result=None, auto_send: bool = False,
                                 pdf: bool = False) -> Dict:
        """回测专项报告：绩效数字直接取 result.metrics（同源）。"""
        result = result or self._last_result()
        if result is None:
            raise ValueError("缺少回测结果 result")
        trades = getattr(result, "trades", None)
        trade_list = (trades.to_dict("records") if hasattr(trades, "to_dict")
                      else list(trades or []))
        metrics = dict(getattr(result, "metrics", {}) or {})
        nav = getattr(result, "nav", None)
        if nav is None or not len(nav):
            nav = pd.DataFrame()

        report = {
            "kind": "backtest",
            "title": f"回测报告 {getattr(result, 'strategy_name', '')}",
            "strategy_name": getattr(result, "strategy_name", ""),
            "metrics": metrics,
            "trade_count": len(trade_list),
            "trades": trade_list,
            "traps": list(getattr(result, "traps", []) or []),
            "data_asof": _nav_asof(nav),
        }
        report.update(self._backtest_view(report, nav, trade_list))
        report["trap_rows"] = _trap_rows(report["traps"]) + _metric_suggestions(metrics)
        report["charts"] = {
            "equity": self._chart_equity(nav, "净值曲线", first=True),
            "drawdown": self._chart_drawdown(nav, "回撤曲线", first=False),
            "heatmap": self._chart_heatmap(nav, "月度收益热力图", first=False),
            "pnl_hist": self._chart_pnl_hist(trade_list, "逐笔盈亏分布", first=False),
        }

        title = report["title"]
        html_text = self.render_html(report, title=title)
        stem = (f"backtest_{getattr(result, 'strategy_name', 'strategy')}_"
                f"{datetime.now():%Y%m%d_%H%M%S}")
        path = self.report_dir / f"{stem}.html"
        path.write_text(html_text, encoding="utf-8")
        report["html_path"] = str(path)
        report["pdf_path"] = self._export_pdf(path) if pdf else None
        if auto_send:
            report["sent"] = self._auto_send(
                title,
                f"交易 {len(trade_list)} 笔 | 胜率 {_pct(metrics.get('win_rate'))}"
                f" | 最大回撤 {_pct(metrics.get('max_drawdown'))}",
                _date.today())
        return report

    def _backtest_view(self, report: Dict, nav: pd.DataFrame,
                       trades: List[dict]) -> Dict:
        metrics = report["metrics"]
        params = self._strategy_params()
        csv_name = None
        if trades:
            csv_name = f"{_safe_name(report['strategy_name'])}_trades.csv"
            try:
                pd.DataFrame(trades).to_csv(self.report_dir / csv_name, index=False,
                                            encoding="utf-8-sig")
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 交易明细 CSV 导出失败：%s", exc)
                csv_name = None
        strategy_rows = [
            ("策略名称", report["strategy_name"] or "-"),
            ("回测区间", _nav_range(nav)),
            ("初始资金", _fmt(metrics.get("initial_capital")
                          or getattr(self.account, "initial_capital", None))),
            ("期末权益", _fmt(metrics.get("final_equity"))),
            ("交易笔数", str(report["trade_count"])),
        ]
        strategy_rows += [(f"参数 {k}", str(v)) for k, v in params.items()]
        return {
            "strategy_rows": strategy_rows,
            "perf_rows": _perf_rows(metrics, all_fields=True),
            "yearly_rows": _yearly_returns(nav),
            "trade_rows": [
                [_when(t.get("timestamp")), t.get("symbol", ""),
                 _dir_text(t.get("direction")), _num(t.get("price")),
                 f"{_to_float(t.get('volume')) or 0:g}", _signed(t.get("pnl")),
                 _num(t.get("commission"))] for t in trades],
            "trade_csv": csv_name,
        }

    def _strategy_params(self) -> Dict:
        strategy = getattr(self.backtester, "strategy", None)
        params = getattr(strategy, "params", None)
        if isinstance(params, dict):
            return {k: v for k, v in params.items()
                    if not str(k).startswith("_")}
        result = self._last_result()
        meta = dict(getattr(result, "meta", {}) or {}) if result else {}
        params = meta.get("params")
        return dict(params) if isinstance(params, dict) else {}

    # ------------------------------------------------------------------
    # G4：对外披露（第四个信号出口 investor_disclosure）
    # ------------------------------------------------------------------
    def generate_investor_disclosure(self, nav_result=None, decision_date=None,
                                     title: str = None, auto_send: bool = False,
                                     qi_checker=None, period: Dict = None,
                                     pdf: bool = False) -> Dict:
        """生成对外净值披露材料（固定 investor_net，禁止毛净值/选择性区间）。

        ``config.DISCLOSURE_CONFORMANCE`` 的每一条都是硬约束：与引擎同源、
        费用五类齐全、披露被抑制信号、标注回测/模拟/实盘、附风险揭示、
        禁止「保本/保收益/零风险」字样、禁止只报最有利区间。
        """
        nav_result = nav_result or getattr(self, "nav_result", None)
        if nav_result is None:
            raise ValueError("对外披露必须传入 NavResult（与引擎同源，禁止另算一套）")
        cfg = dict(config.NAV_PRODUCT_CONFIG)
        conf = dict(config.DISCLOSURE_CONFORMANCE)
        decision = _to_date(decision_date)
        view = nav_result.disclosure(decision)          # 内含披露滞后校验
        asof = _to_date(view["data_asof_date"])
        layer = str(view["layer"])
        if layer != str(cfg.get("disclosure_layer")):
            raise DisclosureConformanceError(
                f"对外披露层必须是 {cfg.get('disclosure_layer')}，实际 {layer}"
                "（禁止用产品毛净值充当组合净值曲线）")
        run_mode = str(getattr(config, "RUN_MODE", "backtest"))
        if run_mode not in conf.get("must_label_type", []):
            raise DisclosureConformanceError(f"未知运行模式 {run_mode!r}，无法标注回测/模拟/实盘")

        full = nav_result.layers.get(layer)
        self._assert_full_period(full, period, conf)

        metrics = dict(nav_result.metrics())
        fee = dict(nav_result.fee_breakdown)
        fee_rows = [[_DISCLOSURE_FEE_LABELS[k], _fmt(fee.get(k, 0.0))]
                    for k in conf["must_include_fee_breakdown"]]
        fee_total = sum(float(fee.get(k, 0.0) or 0.0)
                        for k in conf["must_include_fee_breakdown"])
        fee_rows.append(["费用合计", _fmt(fee_total)])

        perf = nav_result.performance_fees
        perf_rows = []
        if len(perf):
            for _, row in perf.tail(20).iterrows():
                perf_rows.append([_when(row.get("date")), row.get("investor_id", ""),
                                  row.get("kind", ""), _fmt(row.get("fee", 0.0)),
                                  _num(row.get("hwm")), _num(row.get("nav"))])
        recon = nav_result.reconcile()
        recon_rows = [("对账结论", "通过" if recon.get("ok") else "不通过"),
                      ("投资者总份额", _num(recon.get("units"))),
                      ("投资者层权益", _fmt(recon.get("equity"))),
                      ("净值×份额", _fmt(recon.get("nav_times_units"))),
                      ("差异", _fmt(recon.get("diff"))),
                      ("业绩报酬计提累计", _fmt(recon.get("performance_fee_ledger"))),
                      ("业绩报酬账载金额", _fmt(recon.get("performance_fee_booked")))]

        supp = self.collect_suppressions()
        qi_rows, qi_ok = _qi_audit_rows(qi_checker)
        risk_rows = _disclosure_risk_rows()
        policy_rows = _policy_status_rows()

        report = {
            "kind": "disclosure",
            "product_type": nav_result.product_type,
            "run_mode": run_mode,
            "run_mode_label": {"backtest": "回测", "paper": "模拟盘", "live": "实盘"}[run_mode],
            "layer": layer,
            "data_asof": asof.isoformat(),
            "decision_date": decision.isoformat(),
            "disclosure_frequency": view.get("disclosure_frequency"),
            "disclosure_lag_days": view.get("disclosure_lag_days"),
            "period_rows": [("净值区间起点", str(full.index[0].date())),
                            ("净值区间终点", str(full.index[-1].date())),
                            ("已披露截至", asof.isoformat()),
                            ("披露层", layer)],
            "layer_rows": [("产品毛净值", _num(nav_result.layers.product_gross.iloc[-1])),
                           ("产品费后净值", _num(nav_result.layers.product_net.iloc[-1])),
                           ("投资者费后净值", _num(nav_result.layers.investor_net.iloc[-1]))],
            "perf_rows": _perf_rows(metrics, all_fields=True),
            "metrics": metrics,
            "fee_rows": fee_rows,
            "fee_total": fee_total,
            "performance_fee_rows": perf_rows,
            "reconcile_rows": recon_rows,
            "reconcile_ok": bool(recon.get("ok")),
            "suppressions": supp,
            "suppression_total": supp["total"],
            "suppression_count_rows": [[k, v] for k, v in supp["counts"].items()],
            "suppression_detail_rows": [
                [i["symbol"], _dir_text(i["direction"]), i["code"], i["reason"], i["source"]]
                for i in supp["items"]],
            "qi_audit_rows": qi_rows,
            "qi_audit_ok": qi_ok,
            "risk_rows": risk_rows,
            "policy_rows": policy_rows,
            "disclosure_notice": (
                "本材料与引擎同源，净值口径为投资者费后净值（已扣申购费、赎回费、管理费、"
                "托管费与按投资者高水位计提的业绩报酬）。净值披露存在滞后，历史业绩不代表未来，"
                "不承诺本金与收益。"),
            "charts": {"equity": self._chart_nav_layers(nav_result, layer)},
            "html_path": None,
            "pdf_path": None,
        }
        name = f"disclosure_{run_mode}_{asof:%Y%m%d}"
        html_text = self.render_html(report, title or f"{name} · 投资者净值披露")
        self._assert_disclosure(html_text, report, conf)
        html_path = self.report_dir / f"{_safe_name(name)}.html"
        html_path.write_text(html_text, encoding="utf-8")
        report["html_path"] = str(html_path)
        if pdf:
            report["pdf_path"] = self._export_pdf(html_path)
        if auto_send:
            report["sent"] = self._auto_send_disclosure(report, title or name)
        return report

    # ------------------------------------------------------------------
    # 第 10 步 10.5：合格投资者层综合报告（FOF/REITs/新三板/衍生品模拟）
    # ------------------------------------------------------------------
    def generate_qi_report(self, nav_result=None, fof_result=None,
                           reits_rows=None, neeq_rows=None, derivatives=None,
                           decision_date=None, qi_checker=None, period: Dict = None,
                           title: str = None, pdf: bool = False) -> Dict:
        """合格投资者层报告：第四个出口（investor_disclosure）的同源材料。

        * 净值组合页固定 ``investor_net``，并给业绩报酬计提明细与锁定期分布；
        * REITs / 新三板 / 衍生品模拟页只做展示，不下单、不产生交易信号；
        * 与 ``DISCLOSURE_CONFORMANCE`` 同规：费用五类、被抑信号、类型标注、
          风险揭示、完整区间、禁保本措辞。
        """
        engine_result = fof_result or nav_result or getattr(self, "nav_result", None)
        if engine_result is None:
            raise ValueError("合格投资者层报告必须传入 FOFResult / NavResult（与引擎同源）")
        cfg = dict(config.NAV_PRODUCT_CONFIG)
        conf = dict(config.DISCLOSURE_CONFORMANCE)
        decision = _to_date(decision_date)
        view = engine_result.disclosure(decision)
        asof = _to_date(view["data_asof_date"])
        layer = str(view["layer"])
        if layer != str(cfg.get("disclosure_layer")):
            raise DisclosureConformanceError(
                f"对外披露层必须是 {cfg.get('disclosure_layer')}，实际 {layer}")
        run_mode = str(getattr(config, "RUN_MODE", "backtest"))
        if run_mode not in conf.get("must_label_type", []):
            raise DisclosureConformanceError(f"未知运行模式 {run_mode!r}")
        full = engine_result.layers.get(layer)
        self._assert_full_period(full, period, conf)

        fee = dict(engine_result.fee_breakdown)
        fee_rows = [[_DISCLOSURE_FEE_LABELS[k], _fmt(fee.get(k, 0.0))]
                    for k in conf["must_include_fee_breakdown"]]
        fee_rows.append(["费用合计", _fmt(sum(float(fee.get(k, 0.0) or 0.0)
                                          for k in conf["must_include_fee_breakdown"]))])

        perf = getattr(engine_result, "performance_fees", pd.DataFrame())
        perf_rows = []
        if isinstance(perf, pd.DataFrame) and len(perf) and "kind" in perf.columns:
            kept = perf[perf["kind"] == "accrued"].tail(20)
            for _, row in kept.iterrows():
                perf_rows.append([_when(row.get("date")), row.get("investor_id", ""),
                                  _fmt(row.get("fee", 0.0)), _num(row.get("hwm")),
                                  _num(row.get("nav"))])
        weights_rows, lockup_rows = [], []
        if fof_result is not None:
            wh = fof_result.weights_history
            if isinstance(wh, pd.DataFrame) and len(wh):
                for _, row in wh.tail(12).iterrows():
                    weights = ", ".join(f"{k}={v:.1%}" for k, v in
                                        dict(row.get("weights") or {}).items()) or "空仓"
                    weights_rows.append([_when(row.get("decision_date")),
                                         _when(row.get("execute_date")), weights])
            trades = fof_result.trades
            if isinstance(trades, pd.DataFrame) and len(trades) and "code" in trades.columns:
                buys = trades[trades.get("action") == "buy"]
                for code, group in buys.groupby("code"):
                    first = pd.Timestamp(group["date"].iloc[-1])
                    held = (full.index[-1] - first).days
                    lockup_rows.append([code, str(first.date()), held,
                                        f"{held} 天"])
        else:
            lock_days = dict(cfg.get("lockup_days") or {})
            investors = getattr(getattr(engine_result, "engine", None), "_investors", {})
            for pos in investors.values():
                first = getattr(pos, "first_date", None)
                if first is None or pos.units <= 0:
                    continue
                held = (full.index[-1] - pd.Timestamp(first)).days
                lockup_rows.append([pos.investor_id, str(pd.Timestamp(first).date()), held,
                                    f"锁定 {lock_days.get(engine_result.product_type, 0)} 天"])

        supp = self.collect_suppressions()
        qi_rows, qi_ok = _qi_audit_rows(qi_checker)
        risk_rows = _disclosure_risk_rows()
        policy_rows = _policy_status_rows()
        report = {
            "kind": "qi",
            "product_type": getattr(engine_result, "product_type", "fof"),
            "run_mode": run_mode,
            "run_mode_label": {"backtest": "回测", "paper": "模拟盘", "live": "实盘"}[run_mode],
            "layer": layer,
            "data_asof": asof.isoformat(),
            "decision_date": decision.isoformat(),
            "disclosure_frequency": view.get("disclosure_frequency"),
            "disclosure_lag_days": view.get("disclosure_lag_days"),
            "period_rows": [("净值区间起点", str(full.index[0].date())),
                            ("净值区间终点", str(full.index[-1].date())),
                            ("已披露截至", asof.isoformat()), ("披露层", layer)],
            "nav_rows": [("投资者费后净值（最新）", _num(full.iloc[-1])),
                         ("产品费后净值（最新）", _num(engine_result.layers.product_net.iloc[-1])),
                         ("产品毛净值（最新）", _num(engine_result.layers.product_gross.iloc[-1])),
                         ("组合/产品类型", getattr(engine_result, "product_type", "fof"))],
            "perf_rows": _perf_rows(dict(engine_result.metrics()), all_fields=True),
            "fee_rows": fee_rows,
            "performance_fee_rows": perf_rows,
            "weights_rows": weights_rows,
            "lockup_rows": lockup_rows,
            "reits_rows": list(reits_rows or []),
            "neeq_rows": list(neeq_rows or []),
            "deriv_rows": list((derivatives or {}).get("rows") or []),
            "scenario_rows": list((derivatives or {}).get("scenario_rows") or []),
            "suppressions": supp,
            "suppression_total": supp["total"],
            "suppression_count_rows": [[k, v] for k, v in supp["counts"].items()],
            "qi_audit_rows": qi_rows,
            "qi_audit_ok": qi_ok,
            "risk_rows": risk_rows,
            "policy_rows": policy_rows,
            "disclosure_notice": (
                "本材料与引擎同源，净值口径为投资者费后净值。合格投资者层产品流动性差、"
                "锁定期长、净值披露滞后，历史业绩不代表未来，不承诺本金与收益。"
                "衍生品页仅为定价学习与蒙特卡洛模拟，个人禁止参与场外衍生品实盘。"),
            "charts": {"equity": self._chart_nav_layers(engine_result, layer)},
            "html_path": None, "pdf_path": None,
        }
        name = f"qi_{run_mode}_{asof:%Y%m%d}"
        html_text = self.render_html(report, title or f"{name} · 合格投资者层报告")
        self._assert_disclosure(html_text, report, conf)
        html_path = self.report_dir / f"{_safe_name(name)}.html"
        html_path.write_text(html_text, encoding="utf-8")
        report["html_path"] = str(html_path)
        if pdf:
            report["pdf_path"] = self._export_pdf(html_path)
        return report

    def _assert_full_period(self, full, period: Dict, conf: Dict) -> None:
        if not conf.get("forbid_selective_period") or not period:
            return
        start = _to_date(period.get("start")) if period.get("start") else full.index[0].date()
        end = _to_date(period.get("end")) if period.get("end") else full.index[-1].date()
        first, last = full.index[0].date(), full.index[-1].date()
        if start > first or end < last:
            raise DisclosureConformanceError(
                f"禁止只报最有利区间：请求区间 {start}~{end} 未覆盖全量 {first}~{last}；"
                "对外披露必须给完整区间并同时披露回撤")

    def _assert_disclosure(self, text: str, report: Dict, conf: Dict) -> None:
        labels = [_DISCLOSURE_FEE_LABELS[k] for k in conf.get("must_include_fee_breakdown", [])
                  if k in _DISCLOSURE_FEE_LABELS]
        have = [row[0] for row in report.get("fee_rows", [])]
        missing = [lab for lab in labels if lab not in have]
        if missing:
            raise DisclosureConformanceError(f"披露缺少费用明细：{missing}")
        if conf.get("must_include_suppression") and "suppressions" not in report:
            raise DisclosureConformanceError("披露必须包含被抑制信号")
        if conf.get("require_risk_disclosure") and not report.get("risk_rows"):
            raise DisclosureConformanceError("披露必须附风险揭示")
        if not report.get("data_asof"):
            raise DisclosureConformanceError("披露必须标注数据截至日期")
        if conf.get("forbid_guarantee_wording"):
            _assert_no_guarantee(text)

    def _auto_send_disclosure(self, report: Dict, title: str) -> bool:
        """对外披露发送前过时效闸门：超出一个披露周期只发数据告警。"""
        asof = _to_date(report["data_asof"])
        decision = _to_date(report["decision_date"])
        lag = int(report.get("disclosure_lag_days") or 0)
        freq_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(
            str(report.get("disclosure_frequency") or "weekly"), 7)
        stale_days = (decision - asof).days
        if stale_days > lag + freq_days:
            self._notify("披露未发送：净值停更/超限",
                         f"{title}\n数据截至 {asof}，距 {decision} 已 {stale_days} 天"
                         f"（滞后上限 {lag + freq_days} 天），仅发数据告警", "error")
            return False
        text = report.get("disclosure_notice", "") + "\n" + \
            f"投资者费后净值 {report['layer_rows'][-1][1]} · 数据截至 {report['data_asof']}"
        return self._notify(title, text, "info")

    def _chart_nav_layers(self, nav_result, layer: str) -> Optional[str]:
        series = nav_result.layers.get(layer).dropna()
        if not len(series):
            return None
        if HAS_PLOTLY:
            try:
                fig = go.Figure(go.Scatter(
                    x=list(series.index), y=list(series.values), mode="lines",
                    name="投资者费后净值", line={"color": "#2f6feb", "width": 2}))
                fig.update_layout(title="投资者费后净值曲线", height=340,
                                  margin={"l": 40, "r": 20, "t": 50, "b": 30})
                return self._fig_html(fig, first=True)
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[披露] plotly 渲染失败，降级 matplotlib：%s", exc)
        if HAS_MPL:
            return self._mpl_line(list(series.index), list(series.values),
                                  "投资者费后净值曲线", "investor_net")
        return None

    # ------------------------------------------------------------------
    # 自动发送（先过时效闸门）
    # ------------------------------------------------------------------
    def _data_asof(self) -> Optional[_date]:
        result = self._last_result()
        meta = dict(getattr(result, "meta", {}) or {}) if result else {}
        for key in ("data_asof_date", "last_date", "end_date"):
            if meta.get(key):
                try:
                    return _to_date(meta[key])
                except Exception:               # noqa: BLE001
                    continue
        bills = list(getattr(self.paper_trader, "bills", []) or [])
        if bills:
            return _to_date(bills[-1].get("date"))
        account = self.account
        rows = list(getattr(account, "daily_equity", []) or []) if account else []
        if rows:
            return _to_date(rows[-1].get("date"))
        return None

    def _data_asof_str(self) -> str:
        asof = self._data_asof()
        return asof.isoformat() if asof else ""

    def _auto_send(self, title: str, content: str, ref: _date) -> bool:
        if not config.REPORT_CONFORMANCE.get("auto_send_requires_fresh", True):
            return self._notify(title, content, "info")
        asof = self._data_asof()
        if asof is None:
            self._notify("报告未发送：数据截至日期未知", title, "error")
            return False
        limit = int(config.STALE_LIMIT.get("daily", 5))
        days = _trading_days_between(asof, ref, "cn_stock")
        if days > limit:
            self._notify("报告未发送：数据停更/超限",
                         f"{title}\n数据截至 {asof}，距 {ref} 已 {days} 个交易日"
                         f"（上限 {limit}），仅发数据告警，不发送交易内容", "error")
            return False
        return self._notify(title, content, "info")

    def _notify(self, title: str, content: str, level: str) -> bool:
        delivered = False
        for n in self.notifiers:
            try:
                delivered = bool(n.send(title, content, level=level)) or delivered
            except Exception as exc:            # noqa: BLE001 —— 通知是旁路
                self.logger.error("[报告] 渠道 %s 发送异常：%s",
                                  getattr(n, "name", "?"), exc)
        return delivered

    @staticmethod
    def _summary_text(report: Dict) -> str:
        m = report.get("metrics") or {}
        lines = [f"交易 {report.get('trade_count', 0)} 笔",
                 f"权益 {_fmt(report.get('equity'))}",
                 f"胜率 {_pct(m.get('win_rate'))}",
                 f"最大回撤 {_pct(m.get('max_drawdown'))}"]
        if report.get("zero_trade_text"):
            lines.append(report["zero_trade_text"])
        supp = report.get("suppressions") or {}
        if supp.get("total"):
            lines.append(f"闸门拦截 {supp['total']} 笔")
        if report.get("plan") is not None:
            lines.append(f"明日候选 {len(report.get('plan') or [])} 个")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 图表（plotly → matplotlib 降级）
    # ------------------------------------------------------------------
    def _fig_html(self, fig, first: bool) -> Optional[str]:
        if not HAS_PLOTLY:
            return None
        try:
            if self.embed_plotly_js:
                include = True if first else False
            else:
                include = "cdn"
            return str(Markup(fig.to_html(
                full_html=False, include_plotlyjs=include,
                config={"displayModeBar": True, "responsive": True})))
        except Exception as exc:                # noqa: BLE001
            self.logger.warning("[报告] plotly 渲染失败，降级 matplotlib：%s", exc)
            return None

    def _chart_equity(self, nav: pd.DataFrame, title: str,
                      first: bool = True) -> Optional[str]:
        nav = _nav_clean(nav)
        if not len(nav):
            return None
        if HAS_PLOTLY:
            try:
                fig = go.Figure(go.Scatter(
                    x=nav["date"], y=nav["equity"], mode="lines", name="权益",
                    line={"color": "#2f6feb", "width": 2}))
                fig.update_layout(title=title, height=340,
                                  margin={"l": 50, "r": 20, "t": 44, "b": 36},
                                  yaxis_title="权益")
                out = self._fig_html(fig, first)
                if out:
                    return out
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 权益图失败：%s", exc)
        return self._mpl_line(nav["date"], nav["equity"], title, "权益")

    def _chart_drawdown(self, nav: pd.DataFrame, title: str,
                        first: bool = False) -> Optional[str]:
        nav = _nav_clean(nav)
        if not len(nav):
            return None
        drawdown = nav["equity"] / nav["equity"].cummax() - 1.0
        if HAS_PLOTLY:
            try:
                fig = go.Figure(go.Scatter(
                    x=nav["date"], y=drawdown, mode="lines", fill="tozeroy",
                    name="回撤", line={"color": "#d64545", "width": 1.5}))
                fig.update_layout(title=title, height=300,
                                  margin={"l": 50, "r": 20, "t": 44, "b": 36},
                                  yaxis_tickformat=".1%")
                out = self._fig_html(fig, first)
                if out:
                    return out
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 回撤图失败：%s", exc)
        return self._mpl_line(nav["date"], drawdown, title, "回撤")

    def _chart_heatmap(self, nav: pd.DataFrame, title: str,
                       first: bool = False) -> Optional[str]:
        matrix = _monthly_matrix(nav)
        if matrix is None:
            return None
        years, months, values = matrix
        if HAS_PLOTLY:
            try:
                fig = go.Figure(go.Heatmap(
                    z=values, x=[f"{m}月" for m in months], y=[str(y) for y in years],
                    colorscale="RdYlGn", zmid=0, texttemplate="%{z:.1%}",
                    hovertemplate="%{y}年%{x}: %{z:.2%}<extra></extra>",
                    colorbar={"tickformat": ".0%"}))
                fig.update_layout(title=title, height=260,
                                  margin={"l": 50, "r": 20, "t": 44, "b": 36})
                out = self._fig_html(fig, first)
                if out:
                    return out
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 热力图失败：%s", exc)
        if not HAS_MPL:
            return None
        try:
            fig, ax = plt.subplots(figsize=(8, max(1.8, 0.45 * len(years) + 1)))
            im = ax.imshow([[float("nan") if v is None else v for v in row]
                            for row in values], cmap="RdYlGn", vmin=-0.2, vmax=0.2,
                           aspect="auto")
            ax.set_xticks(range(len(months)))
            ax.set_xticklabels([f"{m}月" for m in months], fontsize=8)
            ax.set_yticks(range(len(years)))
            ax.set_yticklabels([str(y) for y in years], fontsize=8)
            ax.set_title(title)
            fig.colorbar(im, ax=ax, format="%.0f%%")
            return self._mpl_png(fig)
        except Exception as exc:                # noqa: BLE001
            self.logger.warning("[报告] matplotlib 热力图失败：%s", exc)
            return None

    def _chart_pnl_hist(self, trades: List[dict], title: str,
                        first: bool = False) -> Optional[str]:
        pnls = [_to_float(t.get("pnl")) for t in trades]
        pnls = [p for p in pnls if p is not None]
        if not pnls:
            return None
        if HAS_PLOTLY:
            try:
                fig = go.Figure(go.Histogram(x=pnls, nbinsx=min(30, max(5, len(pnls))),
                                             marker={"color": "#2f6feb"}))
                fig.update_layout(title=title, height=300,
                                  margin={"l": 50, "r": 20, "t": 44, "b": 36},
                                  xaxis_title="单笔盈亏", yaxis_title="笔数")
                out = self._fig_html(fig, first)
                if out:
                    return out
            except Exception as exc:            # noqa: BLE001
                self.logger.warning("[报告] 盈亏分布图失败：%s", exc)
        if not HAS_MPL:
            return None
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            ax.hist(pnls, bins=min(30, max(5, len(pnls))), color="#2f6feb")
            ax.set_title(title)
            ax.set_xlabel("单笔盈亏")
            ax.set_ylabel("笔数")
            return self._mpl_png(fig)
        except Exception as exc:                # noqa: BLE001
            self.logger.warning("[报告] matplotlib 盈亏分布图失败：%s", exc)
            return None

    def _mpl_line(self, x, y, title: str, label: str) -> Optional[str]:
        if not HAS_MPL:
            return None
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            ax.plot(list(x), list(y), color="#2f6feb", linewidth=1.6)
            ax.set_title(title)
            ax.set_ylabel(label)
            ax.grid(alpha=0.25)
            return self._mpl_png(fig)
        except Exception as exc:                # noqa: BLE001
            self.logger.warning("[报告] matplotlib 折线图失败：%s", exc)
            return None

    @staticmethod
    def _mpl_png(fig) -> str:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        data = base64.b64encode(buf.getvalue()).decode("ascii")
        return str(Markup(f"<img alt='chart' "
                          f"src='data:image/png;base64,{data}' "
                          f"style='max-width:100%'/>"))

    # ------------------------------------------------------------------
    # PDF（可选，缺依赖时跳过）
    # ------------------------------------------------------------------
    def _export_pdf(self, html_path: Path) -> Optional[str]:
        if not shutil.which("wkhtmltopdf"):
            self.logger.warning("[报告] 未安装 wkhtmltopdf，跳过 PDF 导出（HTML 正常）")
            return None
        try:
            import pdfkit
            out = html_path.with_suffix(".pdf")
            pdfkit.from_file(str(html_path), str(out),
                             options={"enable-local-file-access": ""})
            return str(out)
        except Exception as exc:                # noqa: BLE001
            self.logger.warning("[报告] PDF 导出失败（不影响 HTML）：%s", exc)
            return None

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def render_html(self, report: Dict, title: str) -> str:
        kind = report.get("kind") or "daily"
        template_name = f"{kind}.html"
        if self._env is not None:
            try:
                template = self._env.get_template(template_name)
                return template.render(title=title, report=report, css=_CSS,
                                       generated_at=f"{datetime.now():%Y-%m-%d %H:%M:%S}")
            except Exception as exc:            # noqa: BLE001 —— 模板异常降级
                self.logger.error("[报告] Jinja2 渲染失败（%s），降级内置模板：%s",
                                  template_name, exc)
        return self._render_fallback(title, report)

    def _render_fallback(self, title: str, report: Dict) -> str:
        """无 Jinja2 / 模板异常时的简化版（内容不打折：拦截与候选仍然可见）。"""
        e = html.escape
        parts = [f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
                 f"<title>{e(title)}</title><style>{_CSS}</style></head><body>"
                 f"<div class='wrap'><h1>{e(title)}</h1>"]
        if report.get("zero_trade_text"):
            parts.append(f"<div class='banner warn'>{e(report['zero_trade_text'])}</div>")
        sections = (
            ("绩效指标（引擎同源）", report.get("perf_rows")),
            ("账户概览", report.get("account_rows")),
            ("区间概览", report.get("overview_rows")),
            ("市场情绪", report.get("sentiment_rows")),
            ("风控检查", report.get("risk_rows")),
            ("交易盈亏分布", report.get("trade_stats_rows")),
        )
        for heading, rows in sections:
            if rows:
                body = "".join(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>"
                               for k, v in rows)
                parts.append(f"<h2>{heading}</h2><table>{body}</table>")
        for section_title, headers, rows in (
                ("持仓明细", ["标的", "方向", "数量", "成本", "现价", "浮动盈亏", "当日涨跌"],
                 report.get("position_rows")),
                ("当日交易", ["时间", "标的", "市场", "方向", "价格", "数量", "盈亏"],
                 report.get("trade_rows")),
                ("分市场盈亏", ["市场", "已实现盈亏", "成交笔数"],
                 report.get("market_pnl_rows")),
                ("信号汇总与被拦截信号", ["拦截原因", "笔数"],
                 report.get("suppression_count_rows")),
                ("被拦截信号明细", ["标的", "方向", "原因码", "说明", "来源"],
                 report.get("suppression_detail_rows")),
                ("明日候选（report_plan）", ["标的", "市场", "收盘", "数据截至日期", "标注"],
                 report.get("plan_rows")),
                ("已排除（不得进入候选）", ["标的", "市场", "原因码", "标注", "数据截至日期"],
                 report.get("excluded_rows")),
                ("分年度收益", ["年度", "收益率", "年末权益"], report.get("yearly_rows"))):
            if rows:
                head = "".join(f"<th>{e(h)}</th>" for h in headers)
                body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row)
                               + "</tr>" for row in rows)
                parts.append(f"<h2>{section_title}</h2><table><tr>{head}</tr>{body}</table>")
        for chart in (report.get("charts") or {}).values():
            if chart:
                parts.append(f"<section>{chart}</section>")
        review = report.get("param_review") or []
        if review:
            parts.append("<h2>策略参数评估</h2><ul>"
                         + "".join(f"<li>{e(str(x))}</li>" for x in review) + "</ul>")
        tips = report.get("trap_rows") or []
        if tips:
            parts.append("<h2>风险提示与改进建议</h2><ul>"
                         + "".join(f"<li>{e(str(x))}</li>" for x in tips) + "</ul>")
        parts.append("</div></body></html>")
        return "\n".join(parts)

    def _traps(self) -> List[dict]:
        result = self._last_result()
        return list(getattr(result, "traps", []) or [])


# ==================== 对外披露（G4）====================

class DisclosureConformanceError(RuntimeError):
    """对外披露违反 DISCLOSURE_CONFORMANCE（同源/费用/区间/字样等硬约束）。"""


_DISCLOSURE_FEE_LABELS = {
    "subscription": "申购费", "redemption": "赎回费", "management": "管理费",
    "performance": "业绩报酬", "custodian": "托管费",
}

# 信托办法第八条明文禁止的措辞；命中即拒绝出报告
_GUARANTEE_WORDS = ("保本", "保收益", "保证收益", "零风险", "稳赚不赔", "保底收益")


def _assert_no_guarantee(text: str) -> None:
    found = [word for word in _GUARANTEE_WORDS if word in (text or "")]
    if found:
        raise DisclosureConformanceError(
            f"对外披露出现禁止措辞 {found}（禁止承诺本金/收益、宣称零风险）")


def _qi_audit_rows(qi_checker) -> tuple:
    """合格投资者审计留痕（G4 require_qi_audit_trail）。"""
    if qi_checker is None:
        return [["-", "未接入合格投资者审计", "-", "-", "披露不得声称已完成适当性核查"]], False
    try:
        rows = qi_checker.audit_trail(limit=20)
    except Exception as exc:                    # noqa: BLE001
        return [["-", "审计读取失败", "-", "-", str(exc)]], False
    if not rows:
        return [["-", "暂无合格投资者动作记录", "-", "-", "-"]], False
    out = []
    for row in rows:
        out.append([row.get("checked_at", ""), row.get("action", ""),
                    "通过" if row.get("ok") else "拒绝",
                    row.get("rule", ""), "；".join(row.get("reasons") or []) or "-"])
    return out, True


def _disclosure_risk_rows() -> List[tuple]:
    """风险揭示（措辞不得命中 _GUARANTEE_WORDS）。"""
    return [
        ("市场风险", "净值随底层资产波动，可能出现本金损失，历史业绩不代表未来表现。"),
        ("流动性风险", "私募/资管/信托产品流动性差、存在锁定期，赎回可能延迟到账。"),
        ("净值披露滞后", "净值按周/月披露并存在滞后，披露日之前的决策不得使用未公开净值。"),
        ("业绩报酬", "按投资者高水位计提，不同申购时点的高水位不同，实际费后净值存在差异。"),
        ("适当性风险", "仅向符合合格投资者标准的投资者开放，人数与单只投资额均受法规限制。"),
        ("回撤风险", "组合可能出现显著回撤，报告已列示全区间最大回撤，禁止只看上涨区间。"),
    ]


def _policy_status_rows() -> List[List[str]]:
    """2026 规则口径：区分「已发布待施行」与「征求意见稿」。"""
    published = (config.QUALIFIED_INVESTOR_RULES or {}).get("published_2026") or {}
    rows = []
    for name, meta in published.items():
        note = meta.get("note") or ""
        if meta.get("status") == "已发布待施行":
            note = (f"{meta.get('issue_date')} 已发布，{meta.get('effective_date')} 施行"
                    "（不得笼统称为未生效）")
        rows.append([name, meta.get("status", ""), meta.get("issue_date", ""),
                     meta.get("effective_date", ""), note])
    return rows


# ==================== 视图辅助 ====================

def _perf_rows(metrics: Dict, all_fields: bool = False) -> List[tuple]:
    keys = list(PERF_FIELDS)
    if all_fields:
        keys += [k for k in metrics if k not in keys]
    return [(METRIC_LABELS.get(k, k), _metric_value(k, metrics.get(k)))
            for k in keys if k in metrics]


def _risk_check(equity, exposure, positions, account, daily_pnl) -> Dict:
    risk_cfg = (config.RISK or {}).get("account", {})
    single_limit = float(risk_cfg.get("max_single_symbol_pct", 0.2) or 0.2)
    loss_limit = float(risk_cfg.get("daily_loss_pct_stop", 0.05) or 0.05)
    max_symbol_pct = 0.0
    if equity:
        for p in positions:
            max_symbol_pct = max(max_symbol_pct,
                                 abs(p["volume"] * p["price"]) / equity)
    daily_loss_pct = (float(daily_pnl) / equity) if equity and daily_pnl is not None else None
    return {
        "exposure": exposure,
        "exposure_ok": exposure <= 1.0,
        "max_symbol_pct": max_symbol_pct,
        "single_ok": max_symbol_pct <= single_limit,
        "single_limit": single_limit,
        "margin_used": _account_value(account, "margin_used"),
        "daily_loss_pct": daily_loss_pct,
        "daily_loss_ok": daily_loss_pct is None or daily_loss_pct >= -loss_limit,
        "daily_loss_limit": loss_limit,
    }


def _risk_rows(risk: Dict) -> List[tuple]:
    exposure = _to_float(risk.get("exposure"))
    rows = [("仓位比例", f"{_pct(exposure)}（{'合规' if risk.get('exposure_ok') else '超限'}）"),
            ("最大单标的占比",
             f"{_pct(risk.get('max_symbol_pct'))}（上限 {_pct(risk.get('single_limit'))}，"
             f"{'合规' if risk.get('single_ok') else '超限'}）"),
            ("保证金占用", _fmt(risk.get("margin_used")))]
    loss = _to_float(risk.get("daily_loss_pct"))
    if loss is not None:
        rows.append(("当日亏损比例",
                     f"{_pct(loss)}（止损线 {-float(risk.get('daily_loss_limit') or 0):.0%}，"
                     f"{'合规' if risk.get('daily_loss_ok') else '已触发止损线'}）"))
    return rows


def _sentiment_rows(sent: Dict) -> List[tuple]:
    if not sent or not sent.get("available"):
        return []
    rows = [("指数", sent.get("index_name") or "-"),
            ("当日涨跌", _pct_signed(sent.get("index_change"))),
            ("上涨家数", _plain(sent.get("up_count"))),
            ("下跌家数", _plain(sent.get("down_count"))),
            ("涨停家数", _plain(sent.get("limit_up"))),
            ("跌停家数", _plain(sent.get("limit_down"))),
            ("两市成交额", _fmt(sent.get("turnover"))),
            ("北向资金", _fmt(sent.get("northbound")))]
    return [(k, v if v not in ("", "-") else "未接入") for k, v in rows]


def _normalize_sentiment(raw: Optional[dict]) -> Dict:
    raw = dict(raw or {})
    return {
        "index_name": raw.get("index_name") or raw.get("index"),
        "index_change": _to_float(raw.get("index_change", raw.get("change_pct"))),
        "up_count": _to_float(raw.get("up_count")),
        "down_count": _to_float(raw.get("down_count")),
        "limit_up": _to_float(raw.get("limit_up")),
        "limit_down": _to_float(raw.get("limit_down")),
        "turnover": _to_float(raw.get("turnover")),
        "northbound": _to_float(raw.get("northbound")),
        "source": raw.get("source"),
        "available": False,
    }


def _event_rows(events) -> List[list]:
    rows = []
    for item in list(events or []):
        if isinstance(item, dict):
            rows.append([item.get("name") or item.get("event", ""),
                         item.get("symbol", ""), str(item.get("date", "")),
                         item.get("note", item.get("description", ""))])
        else:
            rows.append([str(item), "", "", ""])
    return rows


def _trade_stats(trades: List[dict]) -> Dict:
    pnls = [(_to_float(t.get("pnl")) or 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {"wins": len(wins), "losses": len(losses),
            "avg_win": (sum(wins) / len(wins)) if wins else None,
            "avg_loss": (sum(losses) / len(losses)) if losses else None,
            "best_pnl": max(pnls) if pnls else None,
            "worst_pnl": min(pnls) if pnls else None}


def _extreme_trades(trades: List[dict]) -> List[tuple]:
    if not trades:
        return []
    ordered = sorted(trades, key=lambda t: _to_float(t.get("pnl")) or 0.0)
    rows = [("最大亏损", ordered[0])]
    if len(ordered) > 1:
        rows.append(("最大盈利", ordered[-1]))
    return rows


def _param_review(metrics: Dict, trade_count: int) -> List[str]:
    out = []
    if trade_count < 10:
        out.append(f"样本量偏小（{trade_count} 笔）：统计显著性不足，暂不建议据此调参。")
    win = _to_float(metrics.get("win_rate"))
    pf = _to_float(metrics.get("profit_factor"))
    dd = _to_float(metrics.get("max_drawdown"))
    sharpe = _to_float(metrics.get("sharpe"))
    if win is not None and win < 0.4:
        out.append(f"胜率 {win:.1%} 偏低：优先检查入场过滤条件，而非单纯放宽止损。")
    if pf is not None and pf < 1.0:
        out.append(f"盈亏比 {pf:.2f} < 1：单笔盈利不足以覆盖亏损，需优化出场规则。")
    if dd is not None and dd < -0.2:
        out.append(f"最大回撤 {dd:.1%} 超过 20%：建议降低单笔仓位或增加风控阈值。")
    if sharpe is not None and sharpe < 1.0:
        out.append(f"夏普 {sharpe:.2f} < 1：风险调整后收益偏低，谨慎放大资金。")
    if not out:
        out.append("当前绩效指标未触发明显调参信号；继续观察样本外表现。")
    return out


def _metric_suggestions(metrics: Dict) -> List[str]:
    out = []
    for key, threshold, message in (
            ("max_drawdown", -0.2, "最大回撤超过 20%，实盘前需降低仓位或加风控。"),
            ("sharpe", 1.0, "夏普低于 1，风险调整后收益不足。"),
            ("profit_factor", 1.0, "盈亏比低于 1，出场规则需优化。")):
        value = _to_float(metrics.get(key))
        if value is None:
            continue
        if (key == "max_drawdown" and value < threshold) or \
                (key != "max_drawdown" and value < threshold):
            out.append(message)
    return out


def _trap_rows(traps: List[dict]) -> List[str]:
    return [f"[{t.get('level', '提示')}] {t.get('message', '')}" for t in traps or []]


def _nav_clean(nav) -> pd.DataFrame:
    if nav is None:
        return pd.DataFrame()
    if not isinstance(nav, pd.DataFrame):
        nav = pd.DataFrame(nav)
    if not len(nav) or "equity" not in nav.columns:
        return pd.DataFrame()
    out = nav.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"]).sort_values("date")
    out["equity"] = pd.to_numeric(out["equity"], errors="coerce")
    out = out.dropna(subset=["equity"])
    return out.reset_index(drop=True)


def _monthly_matrix(nav):
    nav = _nav_clean(nav)
    if len(nav) < 2:
        return None
    try:
        grouped = nav.set_index("date")["equity"].resample("ME").last().dropna()
        rets = grouped.pct_change()
        rets.iloc[0] = grouped.iloc[0] / float(nav["equity"].iloc[0]) - 1.0
        frame = pd.DataFrame({"ret": rets})
        frame["year"] = frame.index.year
        frame["month"] = frame.index.month
        years = sorted(frame["year"].unique())
        months = list(range(1, 13))
        values = []
        for year in years:
            row = []
            for month in months:
                hit = frame[(frame["year"] == year) & (frame["month"] == month)]
                row.append(None if hit.empty else float(hit["ret"].iloc[0]))
            values.append(row)
        return years, months, values
    except Exception:                           # noqa: BLE001
        return None


def _yearly_returns(nav) -> List[list]:
    nav = _nav_clean(nav)
    if not len(nav):
        return []
    rows = []
    for year, part in nav.groupby(nav["date"].dt.year):
        first, last = float(part["equity"].iloc[0]), float(part["equity"].iloc[-1])
        ret = (last / first - 1.0) if first else None
        rows.append([str(year), _pct(ret), _fmt(last)])
    return rows


def _nav_ends(nav) -> tuple:
    nav = _nav_clean(nav)
    if not len(nav):
        return None, None
    return float(nav["equity"].iloc[0]), float(nav["equity"].iloc[-1])


def _nav_range(nav) -> str:
    nav = _nav_clean(nav)
    if not len(nav):
        return "-"
    return f"{nav['date'].iloc[0].date()} ~ {nav['date'].iloc[-1].date()}"


def _nav_asof(nav) -> str:
    nav = _nav_clean(nav)
    return nav["date"].iloc[-1].date().isoformat() if len(nav) else ""


def _first_col(df: pd.DataFrame, candidates) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


# ==================== 基础辅助 ====================

def _default_in_session(market: str, now: datetime) -> bool:
    """逐市场时段（与 monitor 同口径：交易日历 + tz 会话）。"""
    try:
        if not is_trading_day(now.date(), market=market):
            return False
        for start, end in get_trading_sessions(market, now.date()):
            ref = now
            if ref.tzinfo is None and getattr(start, "tzinfo", None) is not None:
                ref = ref.replace(tzinfo=start.tzinfo)
            if getattr(end, "tzinfo", None) is None and ref.tzinfo is not None:
                end = end.replace(tzinfo=ref.tzinfo)
            if start <= ref < end:
                return True
        return False
    except Exception:                           # noqa: BLE001
        return now.weekday() < 5


def _trading_days_between(start: _date, end: _date, market: str = "cn_stock") -> int:
    """start（含次日）到 end 的交易日数，用于 stale 判定（自然日禁用）。"""
    if start is None or end is None or start >= end:
        return 0
    days, cur = 0, start
    guard = 0
    while cur < end and guard < 400:
        cur += timedelta(days=1)
        guard += 1
        try:
            if is_trading_day(cur, market=market):
                days += 1
        except Exception:                       # noqa: BLE001
            days += 1 if cur.weekday() < 5 else 0
    return days


def _to_date(value) -> _date:
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    try:
        return pd.Timestamp(value).date()
    except Exception:                           # noqa: BLE001
        return datetime.now().date()


def _same_day(value, day: _date) -> bool:
    try:
        return _to_date(value) == day
    except Exception:                           # noqa: BLE001
        return False


def _end_of_day(day: _date) -> datetime:
    return datetime(day.year, day.month, day.day, 23, 59, 59)


def _asof_date(bar) -> Optional[_date]:
    value = (bar or {}).get(config.STALE_INFO_COLUMN)
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return pd.Timestamp(value).date()
    except Exception:                           # noqa: BLE001
        return None


def _asof_str(bar) -> str:
    asof = _asof_date(bar)
    return asof.isoformat() if asof else "未知"


def _observation_tag(code: str) -> str:
    return {"warmup": "预热期，仅供观察",
            "stale": "数据存疑，仅供观察",
            "off_session": "非交易时段，已排除"}.get(code, "未过闸门，已排除")


def _account_value(account, name: str):
    value = getattr(account, name, None)
    return float(value) if isinstance(value, (int, float)) else value


def _to_float(value) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _when(value) -> str:
    if value is None:
        return ""
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M") \
            if hasattr(value, "hour") or " " in str(value) \
            else str(pd.Timestamp(value).date())
    except Exception:                           # noqa: BLE001
        return str(value)


def _dir_text(direction) -> str:
    return {"buy": "买入", "sell": "卖出", "short": "做空",
            "cover": "平空", "long": "多", "open": "开仓"}.get(
                str(direction or ""), str(direction or ""))


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))


def _fmt(value) -> str:
    num = _to_float(value)
    return "-" if num is None else f"{num:,.2f}"


def _num(value) -> str:
    num = _to_float(value)
    return "-" if num is None else f"{num:,.4g}"


def _plain(value) -> str:
    num = _to_float(value)
    return "-" if num is None else f"{num:,.0f}"


def _signed(value) -> str:
    num = _to_float(value)
    return "-" if num is None else f"{num:+,.2f}"


def _pct(value) -> str:
    num = _to_float(value)
    return "-" if num is None else f"{num:.2%}"


def _pct_signed(value) -> str:
    num = _to_float(value)
    if num is None:
        return "-"
    return f"{num:+.2%}" if abs(num) < 1 else f"{num:+.2f}"


def _metric_value(key: str, value) -> str:
    if key in ("win_rate", "total_return", "annual_return", "max_drawdown",
               "benchmark_return", "excess_return", "volatility",
               "avg_margin_utilization"):
        return _pct(value)
    if key in ("trade_count", "days", "max_drawdown_days", "margin_call_count"):
        return "0" if value is None else str(int(value))
    return _fmt(value)


_CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
margin:0;padding:0;color:#243043;background:#f4f7fb}
.wrap{max-width:1080px;margin:0 auto;padding:26px 22px 48px}
h1{font-size:24px;border-bottom:3px solid #2f6feb;padding-bottom:10px;margin-bottom:4px}
.meta{color:#6b7a90;font-size:12px;margin:0 0 12px}
h2{font-size:18px;margin-top:30px;color:#1f4fb8}
h3{font-size:15px;margin-top:20px;color:#33445c}
table{border-collapse:collapse;width:100%;background:#fff;margin-top:8px;
box-shadow:0 1px 3px rgba(0,0,0,.07);border-radius:8px;overflow:hidden}
th,td{border:1px solid #e3e8f0;padding:8px 10px;text-align:left;font-size:13px}
th{background:#eef3ff;color:#1f4fb8;font-weight:600}
table.kv th{width:220px;background:#f7f9fc;color:#33445c}
tr:nth-child(even) td{background:#fbfcfe}
td.empty{color:#93a1b5;text-align:center}
.banner{padding:12px 14px;border-radius:8px;margin:16px 0;font-weight:600}
.banner.warn{background:#fff4e5;border:1px solid #f0b429;color:#8a5a00}
.note{color:#6b7a90;font-size:12px;line-height:1.7}
.tips{background:#fff;border-radius:8px;padding:14px 18px 14px 34px;
box-shadow:0 1px 3px rgba(0,0,0,.07);line-height:1.8;font-size:13px}
.chart{background:#fff;border-radius:8px;margin-top:14px;padding:6px;
box-shadow:0 1px 3px rgba(0,0,0,.07);overflow-x:auto}
.footer{margin-top:36px;color:#93a1b5;font-size:12px;text-align:center}
a{color:#2f6feb}
"""
