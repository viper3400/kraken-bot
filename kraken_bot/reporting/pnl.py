from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from kraken_bot.domain.enums import TradeStatus
from kraken_bot.domain.models import Trade
from kraken_bot.domain.value_objects import quantize_money


@dataclass(frozen=True)
class PnLResult:
    gross_profit: Decimal
    total_fees: Decimal
    net_profit: Decimal


@dataclass(frozen=True)
class ReportMetrics:
    gross_profit: Decimal
    fees: Decimal
    net_profit: Decimal
    win_rate: Decimal
    average_win: Decimal
    average_loss: Decimal
    average_holding_duration: timedelta
    total_trades: int
    open_trades: int
    closed_trades: int


class PnLCalculator:
    def calculate(self, trade: Trade) -> PnLResult:
        if trade.buy_price is None or trade.sell_price is None:
            raise ValueError("trade must be closed")
        gross = (trade.sell_price - trade.buy_price) * trade.quantity
        fees = trade.buy_fee + trade.sell_fee
        net = gross - fees
        return PnLResult(
            gross_profit=quantize_money(gross),
            total_fees=quantize_money(fees),
            net_profit=quantize_money(net),
        )

    def report(self, trades: list[Trade]) -> ReportMetrics:
        closed = [t for t in trades if t.status is TradeStatus.CLOSED and t.net_profit is not None]
        open_trades = [t for t in trades if t.status is TradeStatus.OPEN]
        wins = [t.net_profit for t in closed if t.net_profit and t.net_profit > 0]
        losses = [t.net_profit for t in closed if t.net_profit and t.net_profit <= 0]
        total_net = sum((t.net_profit for t in closed if t.net_profit is not None), start=Decimal("0"))
        total_gross = sum((t.gross_profit for t in closed if t.gross_profit is not None), start=Decimal("0"))
        total_fees = sum((t.total_fees for t in closed if t.total_fees is not None), start=Decimal("0"))
        durations = [t.holding_duration_seconds for t in closed if t.holding_duration_seconds is not None]
        win_rate = Decimal("0")
        if closed:
            win_rate = (Decimal(len(wins)) / Decimal(len(closed))) * Decimal("100")
        avg_duration = timedelta(seconds=int(sum(durations) / len(durations))) if durations else timedelta()
        return ReportMetrics(
            gross_profit=quantize_money(total_gross),
            fees=quantize_money(total_fees),
            net_profit=quantize_money(total_net),
            win_rate=quantize_money(win_rate),
            average_win=quantize_money(sum(wins, start=Decimal("0")) / Decimal(len(wins))) if wins else Decimal("0.00"),
            average_loss=quantize_money(sum(losses, start=Decimal("0")) / Decimal(len(losses))) if losses else Decimal("0.00"),
            average_holding_duration=avg_duration,
            total_trades=len(trades),
            open_trades=len(open_trades),
            closed_trades=len(closed),
        )
