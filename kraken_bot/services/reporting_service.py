from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.reporting.csv_export import CsvExporter
from kraken_bot.reporting.pnl import PnLCalculator, ReportMetrics


class ReportingService(ABC):
    @abstractmethod
    def build_report(self) -> ReportMetrics: ...

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

    def export_csv(self, path: str | Path) -> None:
        self.csv_exporter.export(path, self.repositories.list_trades())
