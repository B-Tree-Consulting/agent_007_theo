# TODO (AyDEO BFA host sample)

WIP scratch for the **current** increment only.

- `get_trade_intents` reports a broker-accepted order as `working`. A separate `filled` status is not stored yet, so filtering `filled` returns no rows until fill detection is added.
- `get_instruments.broker_last` is the Trading 212 position mark. A name that is not held has no broker last price on that row; order guards still use the market-data quote for the notional.
