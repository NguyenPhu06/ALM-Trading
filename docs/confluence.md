# Bias, confluence, and NO_TRADE

Bias is structure-first and hierarchical. Default normalized weights are D1 0.35, H4 0.25, H1 0.20, M15 0.10, M5 0.06, and M1 0.04. Within each timeframe, confirmed trend contributes 80% of its weight and the latest BOS/CHoCH contributes up to 20%. The weighted score maps to strong bullish, bullish, neutral, bearish, or strong bearish. Lower timeframes therefore cannot blindly override aligned D1/H4/H1 structure.

`ConfluenceScore` is bounded 0–10 for explanation and ranking. It is not a probability. Components include hierarchical structure magnitude and deterministic trend confirmation. Reasons list aligned structure, BOS, sweeps, and ADX context; conflicts list timeframe states opposed to the hierarchical bias.

The output becomes `NO_TRADE` when any configured safety condition applies, including insufficient timeframe data, conflicting D1/H4 structure, extreme volatility, unclear structure, missing liquidity context, unsuitable session, abnormal real spread, or lack of structural/price-action confirmation. Otherwise the state is `OBSERVE`, never BUY or SELL.
