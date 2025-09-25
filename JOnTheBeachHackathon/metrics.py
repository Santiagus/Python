import pandas as pd


def calculate_metrics(backtest_result, market_data, fee, initial_balance):
    """Calculate all metrics"""
    # Rename symbol to pair in market_data
    market_data = market_data.rename(columns={"symbol": "pair"})

    # Merge backtest result with market data
    merged_data = pd.merge(
        backtest_result,
        market_data[["timestamp", "pair", "close"]],
        on=["timestamp", "pair"],
    )
    # Initialize balances
    fiat_balance = initial_balance["fiat"]
    token1_balance = initial_balance["token_1"]
    token2_balance = initial_balance["token_2"]

    # Initialize metrics
    pnl = 0
    turnover = 0
    trade_count = 0
    fees_paid = 0
    daily_returns = []

    # Iterate over trades
    for index, row in merged_data.iterrows():
        # Get trade details
        pair = row["pair"]
        side = row["side"]
        qty = row["qty"]
        price = row["close"]

        # Update balances and metrics
        if side == "buy":
            if pair == "token_1/fiat":
                fiat_balance -= qty * price * (1 + fee)
                token1_balance += qty
            elif pair == "token_2/fiat":
                fiat_balance -= qty * price * (1 + fee)
                token2_balance += qty
        elif side == "sell":
            if pair == "token_1/fiat":
                fiat_balance += qty * price * (1 - fee)
                token1_balance -= qty
            elif pair == "token_2/fiat":
                fiat_balance += qty * price * (1 - fee)
                token2_balance -= qty

        # Update metrics
        turnover += qty * price
        trade_count += 1
        fees_paid += qty * price * fee

        # Update PnL
        pnl = fiat_balance + token1_balance * price + token2_balance * price
        daily_returns.append(pnl)

    # Calculate Sharpe Ratio
    daily_returns_series = pd.Series(daily_returns)
    sharpe_ratio = (
        daily_returns_series.pct_change().mean()
        / daily_returns_series.pct_change().std()
        * (252**0.5)
    )

    # Calculate Max Drawdown
    cumulative_returns = (1 + daily_returns_series.pct_change()).cumprod()
    peak = cumulative_returns.expanding().max()
    drawdown = (cumulative_returns / peak) - 1
    max_drawdown = drawdown.min()

    # Calculate HODL Comparison
    hodl_return = (1 - 1) * initial_balance["fiat"]

    # Calculate Score
    score = 0.7 * sharpe_ratio - 0.2 * abs(max_drawdown) - 0.1 * (turnover / 1_000_000)

    # Return metrics and final balance
    DECIMAL_PLACES = 4

    return {
        "PnL": round(pnl, DECIMAL_PLACES),
        "Percentage Return": round(
            (pnl / initial_balance["fiat"] - 1) * 100, DECIMAL_PLACES
        ),
        "Sharpe Ratio": round(sharpe_ratio, DECIMAL_PLACES),
        "Max Drawdown": round(max_drawdown, DECIMAL_PLACES),
        "Turnover": round(turnover, DECIMAL_PLACES),
        "Trade Count": trade_count,
        "Fees Paid": round(fees_paid, DECIMAL_PLACES),
        "HODL Comparison": round(pnl - hodl_return, DECIMAL_PLACES),
        "Final Balance": {
            "fiat": round(fiat_balance, DECIMAL_PLACES),
            "token_1": round(token1_balance, DECIMAL_PLACES),
            "token_2": round(token2_balance, DECIMAL_PLACES),
        },
        "Score": round(score, DECIMAL_PLACES),
    }
