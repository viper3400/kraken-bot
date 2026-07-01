from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.reporting.csv_export import CsvExporter
from kraken_bot.reporting.pnl import PnLCalculator, ReportMetrics


class ReportingService(ABC):
    @abstractmethod
    def build_report(self) -> ReportMetrics: ...

    @abstractmethod
    def build_report_for_day(self, day: date) -> ReportMetrics: ...

    @abstractmethod
    def build_report_by_strategy(self) -> dict[str, ReportMetrics]: ...

    @abstractmethod
    def build_report_for_day_by_strategy(self, day: date) -> dict[str, ReportMetrics]: ...

    @abstractmethod
    def export_csv(self, path: str | Path) -> None: ...


class DefaultReportingService(ReportingService):
    def __init__(
        self,
        repositories: SqliteRepositories,
        pnl_calculator: PnLCalculator,
        csv_exporter: CsvExporter,
    ) -> None:
        self.repositories = repositories
        self.pnl_calculator = pnl_calculator
        self.csv_exporter = csv_exporter

    def build_report(self) -> ReportMetrics:
        trades = self.repositories.list_trades()
        return self.pnl_calculator.report(trades)

    def build_report_for_day(self, day: date) -> ReportMetrics:
        trades = self._trades_for_day(day)
        return self.pnl_calculator.report(trades)

    def build_report_by_strategy(self) -> dict[str, ReportMetrics]:
        return self._group_reports_by_strategy(self.repositories.list_trades())

    def build_report_for_day_by_strategy(self, day: date) -> dict[str, ReportMetrics]:
        return self._group_reports_by_strategy(self._trades_for_day(day))

    def export_csv(self, path: str | Path) -> None:
        self.csv_exporter.export(path, self.repositories.list_trades())

    def _trades_for_day(self, day: date):
        return [
            trade
            for trade in self.repositories.list_trades()
            if ((trade.sell_time or trade.created_at).astimezone().date() == day)
        ]

    def _group_reports_by_strategy(self, trades) -> dict[str, ReportMetrics]:
        grouped: dict[str, list] = {}
        for trade in trades:
            strategy_name = trade.strategy_name or "unknown"
            grouped.setdefault(strategy_name, []).append(trade)
        return {
            strategy_name: self.pnl_calculator.report(strategy_trades)
            for strategy_name, strategy_trades in sorted(grouped.items())
        }
