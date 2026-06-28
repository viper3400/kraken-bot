from datetime import datetime, timezone
from decimal import Decimal

from kraken_bot.domain.enums import TradeStatus
from kraken_bot.domain.models import Trade
from kraken_bot.reporting.pnl import PnLCalculator


def test_pnl_calculation_uses_fees() -> None:
    trade = Trade(
        id="trade-1",
        asset="XBT/EUR",
        quantity=Decimal("1"),
        buy_price=Decimal("100.00"),
        sell_price=Decimal("100.80"),
        buy_fee=Decimal("0.16"),
        sell_fee=Decimal("0.16"),
        status=TradeStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
    )
    pnl = PnLCalculator().calculate(trade)
    assert pnl.gross_profit == Decimal("0.80")
    assert pnl.total_fees == Decimal("0.32")
    assert pnl.net_profit == Decimal("0.48")
