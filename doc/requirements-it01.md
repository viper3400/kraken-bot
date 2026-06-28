Unten ist eine technische Spezifikation für V1.

Technische Spezifikation – Kraken Trading Bot V1

1. Ziel

Entwicklung eines modularen Python-Tools für automatisierten Spot-Handel auf Kraken.

V1 fokussiert auf:

* einfache regelbasierte Strategie
* eine offene Position pro Asset
* vollständige Historisierung
* reproduzierbare Entscheidungen
* saubere Trade-Zuordnung BUY → SELL
* SQLite-basierte Persistenz
* austauschbare Strategie- und Exchange-Schichten

Nicht enthalten:

* Grid Trading
* Martingale
* Nachkaufen bei Verlust
* Futures
* Hebelhandel
* mehrere parallele Positionen pro Asset

⸻

2. Architekturübersicht

Der Bot wird serviceorientiert aufgebaut.

CLI / BotRunner
   |
   +-- StrategyService
   +-- MarketDataService
   +-- OrderService
   +-- PortfolioService
   +-- PersistenceService
   +-- ReportingService
   |
   +-- ExchangeAdapter: Kraken

Prinzipien:

* Clean Architecture
* Dependency Injection
* keine Handelslogik im Kraken-Adapter
* Strategie unabhängig testbar
* Exchange austauschbar
* SQLite als append-only Historie
* Konfiguration ohne Codeänderung

⸻

3. Projektstruktur

kraken_bot/
  app/
    runner.py
    config.py
    container.py
  domain/
    models.py
    enums.py
    value_objects.py
  services/
    market_data_service.py
    strategy_service.py
    order_service.py
    portfolio_service.py
    persistence_service.py
    reporting_service.py
  exchange/
    base.py
    kraken_adapter.py
  strategies/
    base.py
    ema_pullback_strategy.py
  persistence/
    sqlite.py
    schema.sql
    repositories.py
  reporting/
    pnl.py
    csv_export.py
  tests/
    unit/
    integration/
  config.yaml
  main.py

⸻

4. Kernobjekte

Decision

class Decision(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

OrderType

class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"

TradeStatus

class TradeStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"

OrderStatus

class OrderStatus(Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

⸻

5. Services

5.1 MarketDataService

Verantwortung:

* aktuelle Preise abrufen
* historische Kerzen abrufen
* Volumeninformationen abrufen
* technische Indikatoren vorbereiten
* optional Orderbuch abrufen

Keine Verantwortung:

* keine Kaufentscheidung
* keine Verkaufsentscheidung
* keine Orderplatzierung

Interface:

class MarketDataService:
    def get_current_price(self, asset: str) -> Decimal: ...
    def get_candles(
        self,
        asset: str,
        interval: str,
        limit: int
    ) -> list[Candle]: ...
    def get_market_snapshot(self, asset: str) -> MarketSnapshot: ...

⸻

5.2 StrategyService

Verantwortung:

* reine Entscheidungslogik
* BUY / SELL / HOLD erzeugen
* Entscheidungsgrund liefern
* vollständig ohne Exchange-Abhängigkeit testbar

Interface:

class StrategyService:
    def decide(
        self,
        market: MarketSnapshot,
        history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig
    ) -> StrategyDecision:
        ...

V1-Strategie:

EmaPullbackStrategy

Regeln für BUY:

* keine offene Position
* EMA20 > EMA50
* aktueller Kurs > EMA20
* Rücksetzer zwischen 0,5 % und 1,5 %
* erste Erholungskerze erkannt

Regeln für SELL:

* Take Profit erreicht
* Stop Loss erreicht
* maximale Haltedauer erreicht
* Gewinnziel nach definierter Zeit reduzieren

Sonst:

* HOLD

⸻

5.3 OrderService

Verantwortung:

* Post Only Limit Orders platzieren
* Orderstatus abrufen
* Orders stornieren
* Orders ersetzen

Keine Verantwortung:

* keine Strategie
* keine Portfolioentscheidung
* keine PnL-Berechnung

Interface:

class OrderService:
    def place_post_only_limit_order(
        self,
        asset: str,
        side: OrderType,
        price: Decimal,
        quantity: Decimal,
        trade_id: str | None
    ) -> Order:
        ...
    def get_order_status(self, exchange_order_id: str) -> OrderStatus: ...
    def cancel_order(self, exchange_order_id: str) -> None: ...
    def replace_order(
        self,
        exchange_order_id: str,
        new_price: Decimal,
        new_quantity: Decimal
    ) -> Order:
        ...

⸻

5.4 PortfolioService

Verantwortung:

* aktuelle Position je Asset bestimmen
* verfügbares Kapital prüfen
* offene Orders prüfen
* Regel „maximal eine offene Position pro Asset“ erzwingen

Interface:

class PortfolioService:
    def get_state(self, asset: str) -> PortfolioState: ...
    def has_open_position(self, asset: str) -> bool: ...
    def has_open_order(self, asset: str) -> bool: ...
    def can_open_trade(self, asset: str, required_capital: Decimal) -> bool: ...

⸻

5.5 PersistenceService

Verantwortung:

* SQLite-Zugriff
* append-only Speicherung
* Trades speichern
* Orders speichern
* Marktdaten speichern
* Strategieentscheidungen speichern
* Logs speichern
* Konfiguration historisieren

Wichtig:

* keine Daten werden überschrieben
* Statusänderungen werden als neue Events oder neue Statuszeilen gespeichert
* Berechnete PnL-Werte werden beim Tradeabschluss persistiert

⸻

5.6 ReportingService

Verantwortung:

* Gewinn- und Verlustrechnung
* Trade-Statistiken
* CSV Export
* spätere Dashboard-Schnittstelle

Kennzahlen V1:

* Bruttogewinn
* Gebühren
* Nettogewinn
* Trefferquote
* durchschnittlicher Gewinn
* durchschnittlicher Verlust
* durchschnittliche Haltedauer
* Anzahl Trades
* offene Trades
* geschlossene Trades

⸻

6. Datenbankmodell

SQLite wird als lokale relationale Historie verwendet.

trades

CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    quantity TEXT NOT NULL,
    buy_order_id TEXT,
    sell_order_id TEXT,
    buy_time TEXT,
    sell_time TEXT,
    buy_price TEXT,
    sell_price TEXT,
    buy_fee TEXT DEFAULT '0',
    sell_fee TEXT DEFAULT '0',
    gross_profit TEXT,
    total_fees TEXT,
    net_profit TEXT,
    holding_duration_seconds INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

orders

CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    trade_id TEXT,
    time TEXT NOT NULL,
    type TEXT NOT NULL,
    price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    status TEXT NOT NULL,
    post_only INTEGER NOT NULL,
    exchange_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

order_events

CREATE TABLE order_events (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    time TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_payload TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

market_snapshots

CREATE TABLE market_snapshots (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    asset TEXT NOT NULL,
    price TEXT NOT NULL,
    ema20 TEXT,
    ema50 TEXT,
    volatility TEXT,
    volume TEXT,
    trend_status TEXT,
    created_at TEXT NOT NULL
);

strategy_decisions

CREATE TABLE strategy_decisions (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    asset TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    ema20 TEXT,
    ema50 TEXT,
    price TEXT,
    pullback TEXT,
    comment TEXT,
    config_snapshot TEXT,
    created_at TEXT NOT NULL
);

bot_config_history

CREATE TABLE bot_config_history (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL
);

logs

CREATE TABLE logs (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    level TEXT NOT NULL,
    service TEXT NOT NULL,
    message TEXT NOT NULL,
    context_json TEXT
);

⸻

7. Konfiguration

Datei: config.yaml

bot:
  asset: "XBT/EUR"
  polling_interval_seconds: 30
  mode: "live"
strategy:
  name: "ema_pullback"
  ema_fast: 20
  ema_slow: 50
  pullback_min_pct: 0.5
  pullback_max_pct: 1.5
  take_profit_pct: 0.8
  stop_loss_pct: 0.6
  max_holding_minutes: 120
  reduce_target_after_minutes: 60
  reduced_take_profit_pct: 0.3
trade:
  quote_amount: "50.00"
  post_only: true
kraken:
  api_key_env: "KRAKEN_API_KEY"
  api_secret_env: "KRAKEN_API_SECRET"
database:
  path: "data/bot.sqlite"
logging:
  level: "INFO"

API-Schlüssel werden niemals direkt in der Konfigurationsdatei gespeichert.

⸻

8. Entscheidungsfluss

Hauptloop

1. Konfiguration laden
2. Portfoliozustand laden
3. Marktdaten abrufen
4. EMA20 / EMA50 / Pullback berechnen
5. MarketSnapshot speichern
6. StrategyDecision erzeugen
7. StrategyDecision speichern
8. Bei HOLD: Ende des Zyklus
9. Bei BUY:
   - Kapital prüfen
   - offene Position prüfen
   - offene Order prüfen
   - Trade erstellen
   - Post Only Limit Buy platzieren
   - Order speichern
10. Bei gefülltem BUY:
   - Buy-Daten im Trade ergänzen
   - sofort Post Only Limit Sell platzieren
11. Bei SELL:
   - offene Verkaufsorder prüfen
   - ggf. Order ersetzen oder neue Sell-Order platzieren
12. Bei gefülltem SELL:
   - Trade schließen
   - PnL berechnen
   - Reportingdaten verfügbar machen

⸻

9. Trade-Lifecycle

NEW
 |
BUY_ORDER_CREATED
 |
BUY_FILLED
 |
SELL_ORDER_CREATED
 |
SELL_FILLED
 |
CLOSED

Fehlerfälle:

BUY_ORDER_REJECTED
BUY_ORDER_CANCELLED
SELL_ORDER_CANCELLED
STOP_LOSS_TRIGGERED
MAX_HOLDING_REACHED

Wichtige Regel:

Ein Trade hat genau einen BUY und genau einen SELL.

Es gibt keine Durchschnittspreise und kein Zusammenfassen mehrerer Käufe.

⸻

10. PnL-Berechnung

Formel:

Bruttogewinn = (SELL Preis - BUY Preis) * Menge
Gebühren = BUY Gebühren + SELL Gebühren
Nettogewinn = Bruttogewinn - Gebühren

Beispiel:

BUY:  1.000000 Asset @ 100.00 EUR
SELL: 1.000000 Asset @ 100.80 EUR
Bruttogewinn: 0.80 EUR
BUY Fee:       0.16 EUR
SELL Fee:      0.16 EUR
Nettogewinn:  0.48 EUR

Alle Geldwerte werden mit Decimal verarbeitet, niemals mit float.

⸻

11. Kraken Exchange Adapter

Interface:

class ExchangeAdapter:
    def get_ticker(self, asset: str) -> Ticker: ...
    def get_ohlc(
        self,
        asset: str,
        interval: str,
        limit: int
    ) -> list[Candle]: ...
    def place_limit_order(
        self,
        asset: str,
        side: OrderType,
        price: Decimal,
        quantity: Decimal,
        post_only: bool
    ) -> ExchangeOrderResult:
        ...
    def get_order(self, exchange_order_id: str) -> ExchangeOrder: ...
    def cancel_order(self, exchange_order_id: str) -> None: ...

Regel:

Der Adapter enthält nur technische API-Anbindung.

Keine Strategie.

Keine PnL.

Keine Portfolioentscheidung.

⸻

12. Logging

Jede Entscheidung wird strukturiert geloggt.

Beispiel:

2026-06-27T10:14:12Z INFO StrategyService
asset=XBT/EUR
ema20=65000
ema50=64200
price=65120
pullback=0.63
decision=BUY
reason="EMA20 > EMA50, price > EMA20, pullback ended"

Zusätzlich wird jede Entscheidung in strategy_decisions gespeichert.

⸻

13. Fehlerbehandlung

V1 muss robust umgehen mit:

* Kraken API nicht erreichbar
* Rate Limits
* Order abgelehnt
* Post Only Order nicht angenommen
* teilweise gefüllte Orders
* SQLite Lock
* ungültiger Konfiguration
* inkonsistentem Portfoliozustand

Grundregeln:

* keine ungeprüfte Orderwiederholung
* jeder Fehler wird persistiert
* Bot darf bei unklarem Zustand keine neue Position eröffnen
* Recovery erfolgt aus Datenbank und Exchange-Status

⸻

14. Teststrategie

Unit Tests

Pflichttests:

* EMA-Berechnung
* Pullback-Erkennung
* BUY-Entscheidung
* SELL-Entscheidung
* HOLD-Entscheidung
* Stop Loss
* maximale Haltedauer
* PnL-Berechnung
* keine zweite Position pro Asset
* keine Kaufentscheidung bei offener Order

Integration Tests

* SQLite Repository
* Trade-Lifecycle
* Orderstatus-Updates
* Kraken Adapter mit Mock API
* vollständiger Bot-Zyklus im Paper-Modus

Strategie-Tests

Strategien müssen ohne Kraken, SQLite oder Netzwerk testbar sein.

⸻

15. Erweiterbarkeit

V1 wird so aufgebaut, dass spätere Erweiterungen ohne Änderung bestehender Services möglich sind.

Vorgesehene Erweiterungspunkte:

* ExchangeAdapter für weitere Börsen
* StrategyService für mehrere Strategien
* ExecutionMode für Live, Paper, Backtest
* ReportingService für Dashboard API
* Notification-Service für Telegram
* Backtesting-Service
* Portfolioverwaltung über mehrere Assets

⸻

16. MVP-Umfang V1

Enthalten:

* Kraken Spot
* ein Asset
* eine Strategie
* Post Only Limit Buy
* Post Only Limit Sell
* eine offene Position pro Asset
* SQLite Persistenz
* CSV Reporting
* strukturierte Logs
* Konfiguration via YAML
* Unit Tests

Nicht enthalten:

* Web Dashboard
* Telegram
* Backtesting
* mehrere Assets gleichzeitig
* mehrere Strategien gleichzeitig
* KI / ML
* Futures
* Margin Trading

⸻

17. Akzeptanzkriterien

V1 gilt als fertig, wenn:

1. Der Bot Marktdaten von Kraken abrufen kann.
2. Jede Marktsituation als Snapshot gespeichert wird.
3. Jede Strategieentscheidung gespeichert wird.
4. BUY nur bei erfüllten Regeln ausgelöst wird.
5. Es nie mehr als eine offene Position pro Asset gibt.
6. Nach einem gefüllten BUY automatisch eine SELL-Order erzeugt wird.
7. Jeder Trade exakt einem BUY und einem SELL zugeordnet ist.
8. PnL korrekt mit Gebühren berechnet wird.
9. Alle Parameter über Konfiguration änderbar sind.
10. Der Bot nach Neustart seinen Zustand aus SQLite rekonstruieren kann.
11. Strategie-Tests ohne Exchange und Datenbank laufen.
12. Keine Geschäftslogik im Kraken Adapter liegt.

⸻

18. Empfohlene technische Basis

* Python 3.12+
* SQLite
* pydantic für Konfiguration und Datenmodelle
* pyyaml für YAML-Konfiguration
* httpx für API Calls
* pytest für Tests
* decimal.Decimal für Geldwerte
* structlog oder Standard-Logging mit JSON Formatter
* dependency-injector optional, alternativ einfache Factory in container.py

⸻

19. Designentscheidung für V1

V1 soll bewusst einfach bleiben.

Keine Optimierung auf maximale Rendite.

Priorität:

1. korrekte Daten
2. reproduzierbare Entscheidungen
3. stabile Ausführung
4. klare Modulgrenzen
5. testbare Strategie
6. saubere PnL
7. Erweiterbarkeit

Die Plattform ist wichtiger als die erste Strategie.