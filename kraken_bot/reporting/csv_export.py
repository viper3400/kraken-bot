from __future__ import annotations

import csv
from pathlib import Path

from kraken_bot.domain.models import Trade


class CsvExporter:
    def export(self, path: str | Path, trades: list[Trade]) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "id",
                    "asset",
                    "quantity",
                    "buy_price",
                    "sell_price",
                    "gross_profit",
                    "total_fees",
                    "net_profit",
                    "status",
                ]
            )
            for trade in trades:
                writer.writerow(
                    [
                        trade.id,
                        trade.asset,
                        str(trade.quantity),
                        trade.buy_price,
                        trade.sell_price,
                        trade.gross_profit,
                        trade.total_fees,
                        trade.net_profit,
                        trade.status.value,
                    ]
                )
