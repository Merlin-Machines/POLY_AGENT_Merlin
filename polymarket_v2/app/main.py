from polymarket_v2.app.settings import load_settings
from polymarket_v2.connectors.price_feeds import analyze_candles, get_5m_candles, get_spot_price
from polymarket_v2.connectors.binance_account import BinanceAccountClient
from polymarket_v2.connectors.polymarket_gamma import PolymarketGammaProvider
from polymarket_v2.execution.dry_run_broker import DryRunBroker
from polymarket_v2.strategies.legacy_hybrid import LegacyHybridStrategy


def run_once() -> None:
    settings = load_settings()
    market_provider = PolymarketGammaProvider()
    strategy = LegacyHybridStrategy(
        edge_threshold=settings.edge_threshold,
        max_trade_usd=settings.max_trade_usd,
    )
    broker = DryRunBroker()
    binance = BinanceAccountClient(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
    )

    print(f"[{settings.app_name}] dry_run={settings.dry_run} env={settings.env}")
    print(f"[execution] enabled={settings.execution_enabled} live_trading_enabled={settings.live_trading_enabled}")
    print(f"[binance] {binance.status().reason}")
    print("[markets] fetching...")
    markets = list(market_provider.fetch_markets())
    print(f"[markets] loaded={len(markets)}")

    prices: dict[str, float] = {}
    for symbol in ("BTC", "ETH"):
        price = get_spot_price(symbol)
        if price:
            prices[symbol] = price

    candle_analysis: dict[str, dict] = {}
    for symbol in ("BTC", "ETH"):
        candles = get_5m_candles(symbol)
        if candles:
            candle_analysis[symbol] = analyze_candles(candles)

    opportunities = strategy.find_opportunities(markets, prices, candle_analysis)
    print(f"[strategy] opportunities={len(opportunities)}")
    for item in opportunities[:5]:
        if settings.execution_enabled and not settings.dry_run and settings.live_trading_enabled:
            order_id = broker.place(item)
            print(
                f"[order] {order_id} market={item.market_id} side={item.side.value} "
                f"edge={item.edge:.2%} size=${item.size_usd:.2f}"
            )
        else:
            print(
                f"[monitor-only] market={item.market_id} side={item.side.value} "
                f"edge={item.edge:.2%} size=${item.size_usd:.2f}"
            )


if __name__ == "__main__":
    run_once()
