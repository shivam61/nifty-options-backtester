"""
Analysis and reporting module. Generates detailed reports,
charts, and learnings from backtest results.
"""

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

from backtester.engine import BacktestResult, TradeResult


class BacktestReporter:
    """Generates comprehensive reports from backtest results."""

    def __init__(self, result: BacktestResult, market_data: pd.DataFrame):
        self.result = result
        self.market_data = market_data

    def print_summary(self):
        print(self.result.summary())
        self._print_yearly_breakdown()
        self._print_monthly_heatmap()
        self._print_strategy_breakdown()

    def _print_yearly_breakdown(self):
        """Year-by-year performance table."""
        trades = self.result.trades
        if not trades:
            return
        years = {}
        for t in trades:
            y = t.exit_date.year if hasattr(t.exit_date, "year") else t.exit_date[:4]
            if y not in years:
                years[y] = {"trades": 0, "wins": 0, "pnl": 0, "best": 0, "worst": 0}
            years[y]["trades"] += 1
            years[y]["pnl"] += t.total_pnl
            if t.total_pnl > 0:
                years[y]["wins"] += 1
            years[y]["best"] = max(years[y]["best"], t.total_pnl)
            years[y]["worst"] = min(years[y]["worst"], t.total_pnl)

        print(f"\n  ── YEARLY BREAKDOWN ──")
        print(f"  {'Year':<7} {'Trades':>7} {'Win%':>7} {'P&L':>12} {'Avg/Trade':>12} {'Best':>10} {'Worst':>10}")
        print(f"  {'─' * 70}")
        for y in sorted(years.keys()):
            d = years[y]
            wr = d["wins"] / d["trades"] * 100 if d["trades"] > 0 else 0
            avg = d["pnl"] / d["trades"] if d["trades"] > 0 else 0
            bar = "█" * max(1, int(d["pnl"] / max(abs(d["pnl"]), 1) * 10)) if d["pnl"] > 0 else ""
            print(f"  {y:<7} {d['trades']:>7} {wr:>6.0f}% ₹{d['pnl']:>+10,.0f} ₹{avg:>+10,.0f} "
                  f"₹{d['best']:>+8,.0f} ₹{d['worst']:>+8,.0f}  {bar}")
        total_pnl = sum(d["pnl"] for d in years.values())
        total_trades = sum(d["trades"] for d in years.values())
        print(f"  {'─' * 70}")
        print(f"  {'TOTAL':<7} {total_trades:>7} {self.result.win_rate:>6.1f}% ₹{total_pnl:>+10,.0f}")

    def _print_monthly_heatmap(self):
        """Monthly P&L heatmap (text-based)."""
        trades = self.result.trades
        if not trades:
            return
        months = {}
        for t in trades:
            ed = t.exit_date
            key = f"{ed.year}-{ed.month:02d}" if hasattr(ed, "year") else str(ed)[:7]
            months[key] = months.get(key, 0) + t.total_pnl

        if len(months) < 3:
            return

        print(f"\n  ── MONTHLY P&L ──")
        sorted_months = sorted(months.items())
        for key, pnl in sorted_months:
            bar_len = min(30, max(1, int(abs(pnl) / 5000)))
            bar = ("+" * bar_len) if pnl > 0 else ("-" * bar_len)
            color_marker = "▓" if pnl > 0 else "░"
            print(f"  {key}  ₹{pnl:>+10,.0f}  {color_marker}{bar}")

    def _print_strategy_breakdown(self):
        """Per-strategy sub-breakdown if multiple strategies used."""
        trades = self.result.trades
        if not trades:
            return
        strategies = {}
        for t in trades:
            s = t.strategy or "unknown"
            if s not in strategies:
                strategies[s] = {"trades": 0, "wins": 0, "pnl": 0, "pnls": []}
            strategies[s]["trades"] += 1
            strategies[s]["pnl"] += t.total_pnl
            strategies[s]["pnls"].append(t.total_pnl)
            if t.total_pnl > 0:
                strategies[s]["wins"] += 1

        if len(strategies) <= 1:
            return

        print(f"\n  ── STRATEGY BREAKDOWN ──")
        print(f"  {'Strategy':<30} {'Trades':>7} {'Win%':>7} {'Total P&L':>12} {'Avg P&L':>10} {'Sharpe':>8}")
        print(f"  {'─' * 78}")
        for s in sorted(strategies.keys(), key=lambda x: strategies[x]["pnl"], reverse=True):
            d = strategies[s]
            wr = d["wins"] / d["trades"] * 100 if d["trades"] > 0 else 0
            avg = d["pnl"] / d["trades"] if d["trades"] > 0 else 0
            pnls = np.array(d["pnls"])
            sharpe = (pnls.mean() / pnls.std()) * (12 ** 0.5) if len(pnls) > 1 and pnls.std() > 0 else 0
            print(f"  {s:<30} {d['trades']:>7} {wr:>6.0f}% ₹{d['pnl']:>+10,.0f} ₹{avg:>+8,.0f} {sharpe:>7.2f}")

    def print_trade_log(self):
        """Print detailed trade-by-trade log."""
        print(f"\n{'='*100}")
        print(f"  TRADE LOG")
        print(f"{'='*100}")

        for i, t in enumerate(self.result.trades, 1):
            profit_loss = "PROFIT" if t.total_pnl > 0 else "LOSS"
            print(f"\n  Trade #{i} [{profit_loss}]")
            print(f"  Entry: {t.entry_date} | Exit: {t.exit_date} | Days: {t.holding_days}")
            print(f"  Spot: {t.entry_spot:.0f} → {t.exit_spot:.0f} ({(t.exit_spot/t.entry_spot-1)*100:+.2f}%)")
            print(f"  VIX:  {t.entry_vix:.1f} → {t.exit_vix:.1f} ({(t.exit_vix/t.entry_vix-1)*100:+.1f}%)")
            print(f"  Credit: ₹{t.net_credit:.1f}/unit | P&L: ₹{t.total_pnl:,.0f} ({t.pnl_pct:+.1f}%)")
            print(f"  Exit Reason: {t.exit_reason}")
            print(f"  Legs: {t.legs_detail}")
            print(f"  Max DD During Trade: ₹{t.max_drawdown_during:,.0f}")

    def generate_learnings(self) -> list[str]:
        """Extract actionable learnings from backtest results."""
        learnings = []
        trades = self.result.trades
        if not trades:
            return ["No trades were executed in the backtest period."]

        # Learning 1: Win rate by VIX regime
        high_vix_trades = [t for t in trades if t.entry_vix > 22]
        low_vix_trades = [t for t in trades if t.entry_vix <= 18]
        med_vix_trades = [t for t in trades if 18 < t.entry_vix <= 22]

        if high_vix_trades:
            hv_wr = len([t for t in high_vix_trades if t.total_pnl > 0]) / len(high_vix_trades) * 100
            hv_avg = np.mean([t.total_pnl for t in high_vix_trades])
            learnings.append(
                f"HIGH VIX (>22): {len(high_vix_trades)} trades, {hv_wr:.0f}% win rate, "
                f"avg P&L ₹{hv_avg:,.0f}"
            )

        if med_vix_trades:
            mv_wr = len([t for t in med_vix_trades if t.total_pnl > 0]) / len(med_vix_trades) * 100
            mv_avg = np.mean([t.total_pnl for t in med_vix_trades])
            learnings.append(
                f"MEDIUM VIX (18-22): {len(med_vix_trades)} trades, {mv_wr:.0f}% win rate, "
                f"avg P&L ₹{mv_avg:,.0f}"
            )

        if low_vix_trades:
            lv_wr = len([t for t in low_vix_trades if t.total_pnl > 0]) / len(low_vix_trades) * 100
            lv_avg = np.mean([t.total_pnl for t in low_vix_trades])
            learnings.append(
                f"LOW VIX (<18): {len(low_vix_trades)} trades, {lv_wr:.0f}% win rate, "
                f"avg P&L ₹{lv_avg:,.0f}"
            )

        # Learning 2: VIX direction at entry
        vix_declining = [t for t in trades if t.exit_vix < t.entry_vix]
        vix_rising = [t for t in trades if t.exit_vix >= t.entry_vix]

        if vix_declining:
            dec_avg = np.mean([t.total_pnl for t in vix_declining])
            learnings.append(
                f"When VIX DECLINED during trade: avg P&L ₹{dec_avg:,.0f} "
                f"({len(vix_declining)} trades)"
            )

        if vix_rising:
            rise_avg = np.mean([t.total_pnl for t in vix_rising])
            learnings.append(
                f"When VIX ROSE during trade: avg P&L ₹{rise_avg:,.0f} "
                f"({len(vix_rising)} trades)"
            )

        # Learning 3: Exit reason analysis
        exit_reasons = {}
        for t in trades:
            reason = t.exit_reason
            if reason not in exit_reasons:
                exit_reasons[reason] = {"count": 0, "total_pnl": 0}
            exit_reasons[reason]["count"] += 1
            exit_reasons[reason]["total_pnl"] += t.total_pnl

        for reason, stats in exit_reasons.items():
            avg = stats["total_pnl"] / stats["count"]
            learnings.append(
                f"Exit reason '{reason}': {stats['count']} trades, avg P&L ₹{avg:,.0f}"
            )

        # Learning 4: Best/worst trades
        best = max(trades, key=lambda t: t.total_pnl)
        worst = min(trades, key=lambda t: t.total_pnl)
        learnings.append(
            f"BEST trade: {best.entry_date} → {best.exit_date}, "
            f"P&L ₹{best.total_pnl:,.0f}, VIX {best.entry_vix:.1f}→{best.exit_vix:.1f}"
        )
        learnings.append(
            f"WORST trade: {worst.entry_date} → {worst.exit_date}, "
            f"P&L ₹{worst.total_pnl:,.0f}, VIX {worst.entry_vix:.1f}→{worst.exit_vix:.1f}"
        )

        # Learning 5: Spot movement vs P&L
        small_moves = [t for t in trades if abs(t.exit_spot / t.entry_spot - 1) < 0.03]
        big_moves = [t for t in trades if abs(t.exit_spot / t.entry_spot - 1) >= 0.03]

        if small_moves:
            sm_wr = len([t for t in small_moves if t.total_pnl > 0]) / len(small_moves) * 100
            learnings.append(
                f"When Nifty moved <3%: {sm_wr:.0f}% win rate ({len(small_moves)} trades)"
            )

        if big_moves:
            bm_wr = len([t for t in big_moves if t.total_pnl > 0]) / len(big_moves) * 100
            learnings.append(
                f"When Nifty moved >3%: {bm_wr:.0f}% win rate ({len(big_moves)} trades)"
            )

        # Learning 6: Optimal holding period
        winning = [t for t in trades if t.total_pnl > 0]
        if winning:
            avg_hold = np.mean([t.holding_days for t in winning])
            learnings.append(f"Average holding period for winners: {avg_hold:.0f} days")

        return learnings

    def plot_equity_curve(self, save_path: Optional[str] = None):
        """Generate comprehensive HTML dashboard with all metrics."""
        if not HAS_PLOTLY:
            print("plotly not installed. Run: pip install plotly")
            return

        r = self.result

        fig = make_subplots(
            rows=5, cols=2,
            subplot_titles=(
                "Equity Curve", "Drawdown",
                "Nifty 50", "India VIX",
                "Monthly P&L", "Trade P&L Distribution",
                "Cumulative P&L by Trade #", "Trade P&L vs VIX at Entry",
            ),
            vertical_spacing=0.06,
            horizontal_spacing=0.08,
            row_heights=[0.25, 0.2, 0.2, 0.2, 0.15],
            specs=[
                [{"colspan": 1}, {"colspan": 1}],
                [{"colspan": 1}, {"colspan": 1}],
                [{"colspan": 1}, {"colspan": 1}],
                [{"colspan": 1}, {"colspan": 1}],
                [{"colspan": 2}, None],
            ],
        )

        # 1. Equity Curve
        if r.equity_curve is not None and len(r.equity_curve) > 0:
            fig.add_trace(
                go.Scatter(
                    x=self.market_data.index, y=r.equity_curve.values,
                    mode="lines", name="Equity",
                    line=dict(color="#00d4aa", width=2),
                    fill="tozeroy", fillcolor="rgba(0,212,170,0.1)",
                ),
                row=1, col=1,
            )
            fig.add_hline(
                y=r.initial_capital, line_dash="dash",
                line_color="gray", opacity=0.5, row=1, col=1,
            )

        # 2. Drawdown
        if r.equity_curve is not None and len(r.equity_curve) > 0:
            peak = r.equity_curve.cummax()
            dd_pct = ((r.equity_curve - peak) / peak * 100).fillna(0)
            fig.add_trace(
                go.Scatter(
                    x=self.market_data.index, y=dd_pct.values,
                    mode="lines", name="Drawdown %",
                    line=dict(color="#ff4444", width=1.5),
                    fill="tozeroy", fillcolor="rgba(255,68,68,0.2)",
                ),
                row=1, col=2,
            )

        # 3. Nifty
        if "nifty_close" in self.market_data.columns:
            fig.add_trace(
                go.Scatter(
                    x=self.market_data.index,
                    y=self.market_data["nifty_close"],
                    mode="lines", name="Nifty",
                    line=dict(color="#4488ff", width=1.5),
                ),
                row=2, col=1,
            )
            for trade in r.trades:
                clr = "rgba(0,200,0,0.12)" if trade.total_pnl > 0 else "rgba(255,0,0,0.15)"
                fig.add_vrect(
                    x0=trade.entry_date, x1=trade.exit_date,
                    fillcolor=clr, layer="below", line_width=0,
                    row=2, col=1,
                )

        # 4. VIX
        if "vix" in self.market_data.columns:
            fig.add_trace(
                go.Scatter(
                    x=self.market_data.index,
                    y=self.market_data["vix"],
                    mode="lines", name="VIX",
                    line=dict(color="#ff8800", width=1.5),
                ),
                row=2, col=2,
            )
            fig.add_hline(y=20, line_dash="dash", line_color="yellow", opacity=0.4, row=2, col=2)

        # 5. Monthly P&L bars
        if r.monthly_pnl is not None and len(r.monthly_pnl) > 0:
            colors = ["#00d4aa" if v >= 0 else "#ff4444" for v in r.monthly_pnl.values]
            fig.add_trace(
                go.Bar(
                    x=r.monthly_pnl.index, y=r.monthly_pnl.values,
                    name="Monthly P&L", marker_color=colors,
                ),
                row=3, col=1,
            )

        # 6. Trade P&L distribution
        if r.trades:
            pnls = [t.total_pnl for t in r.trades]
            fig.add_trace(
                go.Histogram(
                    x=pnls, nbinsx=30, name="Trade P&L Dist",
                    marker_color="#4488ff", opacity=0.7,
                ),
                row=3, col=2,
            )
            fig.add_vline(x=0, line_dash="dash", line_color="white", row=3, col=2)

        # 7. Cumulative P&L by trade #
        if r.trades:
            cum_pnl = np.cumsum([t.total_pnl for t in r.trades])
            fig.add_trace(
                go.Scatter(
                    x=list(range(1, len(cum_pnl) + 1)), y=cum_pnl,
                    mode="lines+markers", name="Cumulative P&L",
                    line=dict(color="#00d4aa", width=2),
                    marker=dict(
                        size=5,
                        color=["#00d4aa" if p > 0 else "#ff4444" for p in [t.total_pnl for t in r.trades]],
                    ),
                ),
                row=4, col=1,
            )

        # 8. Trade P&L vs VIX at entry
        if r.trades:
            fig.add_trace(
                go.Scatter(
                    x=[t.entry_vix for t in r.trades],
                    y=[t.total_pnl for t in r.trades],
                    mode="markers", name="P&L vs VIX",
                    marker=dict(
                        size=8,
                        color=[t.total_pnl for t in r.trades],
                        colorscale="RdYlGn", cmin=-30000, cmax=30000,
                        showscale=True, colorbar=dict(title="P&L"),
                    ),
                    text=[f"{t.entry_date}<br>{t.strategy}<br>₹{t.total_pnl:,.0f}" for t in r.trades],
                    hovertemplate="%{text}<extra></extra>",
                ),
                row=4, col=2,
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray", row=4, col=2)

        # 9. KPI summary table at bottom
        years = max((r.end_date - r.start_date).days / 365.25, 0.1)
        kpi_text = (
            f"<b>Strategy:</b> {r.strategy_name} &nbsp;|&nbsp; "
            f"<b>Period:</b> {r.start_date} to {r.end_date} ({years:.1f}y) &nbsp;|&nbsp; "
            f"<b>Capital:</b> ₹{r.initial_capital:,.0f}<br>"
            f"<b>Total P&L:</b> ₹{r.total_pnl:,.0f} &nbsp;|&nbsp; "
            f"<b>Return:</b> {r.total_return_pct:.1f}% &nbsp;|&nbsp; "
            f"<b>CAGR:</b> {r.cagr_pct:.1f}% &nbsp;|&nbsp; "
            f"<b>Sharpe:</b> {r.sharpe_ratio:.2f} &nbsp;|&nbsp; "
            f"<b>Sortino:</b> {r.sortino_ratio:.2f}<br>"
            f"<b>Trades:</b> {r.total_trades} &nbsp;|&nbsp; "
            f"<b>Win Rate:</b> {r.win_rate:.0f}% &nbsp;|&nbsp; "
            f"<b>Max DD:</b> ₹{r.max_drawdown:,.0f} ({r.max_drawdown_pct:.1f}%) &nbsp;|&nbsp; "
            f"<b>Calmar:</b> {r.calmar_ratio:.2f} &nbsp;|&nbsp; "
            f"<b>PF:</b> {r.profit_factor:.2f}<br>"
            f"<b>Avg Win:</b> ₹{r.avg_win:,.0f} ({r.avg_win_holding_days:.0f}d) &nbsp;|&nbsp; "
            f"<b>Avg Loss:</b> ₹{r.avg_loss:,.0f} ({r.avg_loss_holding_days:.0f}d) &nbsp;|&nbsp; "
            f"<b>Payoff:</b> {r.payoff_ratio:.2f}x &nbsp;|&nbsp; "
            f"<b>Expectancy:</b> ₹{r.expectancy:,.0f} &nbsp;|&nbsp; "
            f"<b>Vol:</b> {r.volatility_annual_pct:.1f}%<br>"
            f"<b>Max Consec Wins:</b> {r.max_consecutive_wins} &nbsp;|&nbsp; "
            f"<b>Max Consec Losses:</b> {r.max_consecutive_losses} &nbsp;|&nbsp; "
            f"<b>Best Trade:</b> ₹{r.best_trade_pnl:,.0f} &nbsp;|&nbsp; "
            f"<b>Worst Trade:</b> ₹{r.worst_trade_pnl:,.0f} &nbsp;|&nbsp; "
            f"<b>Best Month:</b> ₹{r.best_month_pnl:,.0f} &nbsp;|&nbsp; "
            f"<b>Worst Month:</b> ₹{r.worst_month_pnl:,.0f}"
        )
        fig.add_trace(
            go.Scatter(
                x=[0.5], y=[0.5], mode="text",
                text=[kpi_text],
                textfont=dict(size=11, color="white"),
                showlegend=False,
            ),
            row=5, col=1,
        )
        fig.update_xaxes(visible=False, row=5, col=1)
        fig.update_yaxes(visible=False, row=5, col=1)

        fig.update_layout(
            title=dict(
                text=(f"<b>{r.strategy_name}</b> — "
                      f"₹{r.total_pnl:,.0f} ({r.total_return_pct:+.1f}%) | "
                      f"CAGR {r.cagr_pct:.1f}% | Sharpe {r.sharpe_ratio:.2f} | "
                      f"Win {r.win_rate:.0f}%"),
                font=dict(size=16),
            ),
            height=1600,
            showlegend=True,
            template="plotly_dark",
            font=dict(family="Menlo, monospace", size=11),
        )

        if save_path:
            fig.write_html(save_path)
            print(f"\n  Dashboard saved to {save_path}")
            print(f"  Open: file://{save_path}")
        else:
            fig.show()

    def generate_regime_report(self) -> str:
        """Summarize what each VIX regime means for trading."""
        report = []
        report.append("\n" + "=" * 60)
        report.append("  MARKET REGIME LEARNINGS")
        report.append("=" * 60)

        trades = self.result.trades
        if not trades:
            report.append("  No trades to analyze.")
            return "\n".join(report)

        regimes = {
            "Low VIX (<18)": lambda t: t.entry_vix < 18,
            "Medium VIX (18-22)": lambda t: 18 <= t.entry_vix < 22,
            "High VIX (22-28)": lambda t: 22 <= t.entry_vix < 28,
            "Extreme VIX (>28)": lambda t: t.entry_vix >= 28,
        }

        for regime_name, filter_fn in regimes.items():
            regime_trades = [t for t in trades if filter_fn(t)]
            if not regime_trades:
                continue

            wins = [t for t in regime_trades if t.total_pnl > 0]
            total_pnl = sum(t.total_pnl for t in regime_trades)
            avg_pnl = total_pnl / len(regime_trades)
            wr = len(wins) / len(regime_trades) * 100

            report.append(f"\n  {regime_name}:")
            report.append(f"    Trades: {len(regime_trades)} | Win Rate: {wr:.0f}%")
            report.append(f"    Total P&L: ₹{total_pnl:,.0f} | Avg: ₹{avg_pnl:,.0f}")

            if wr > 60 and avg_pnl > 0:
                report.append("    → FAVORABLE for premium selling")
            elif wr < 40:
                report.append("    → AVOID premium selling in this regime")
            else:
                report.append("    → NEUTRAL — tighten risk management")

        return "\n".join(report)
