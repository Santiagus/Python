import pandas as pd
import numpy as np
import uuid
import json
from pathlib import Path
from trader import Trader

# from strategy import strategyßß
# from strategy2 import strategy
# from strategy3 import strategy
# from strategy4 import strategy

from strategy9 import strategy


def run_backtest(
    combined_data: pd.DataFrame, fee: float, balances: dict[str, float]
) -> pd.DataFrame:
    """Run a backtest with multiple trading pairs.

    Args:
        submission_dir: Path to the strategy directory
        combined_data: DataFrame containing market data for multiple pairs
        fee: Trading fee (in basis points, e.g., 2 = 0.02%)
        balances: Dictionary of {pair: amount} containing initial balances
    """
    # Record initial balances for display
    trader = Trader(balances, fee)

    initial_balances = balances.copy()

    # Initialize prices with first data point for each pair
    combined_data.sort_values("timestamp", inplace=True)
    first_prices = {k: df.iloc[0]["close"] for k, df in combined_data.groupby("symbol")}

    # Calculate true initial portfolio value including all assets
    initial_portfolio_value = initial_balances["fiat"]
    if "token_1/fiat" in first_prices and initial_balances["token_1"] > 0:
        initial_portfolio_value += (
            initial_balances["token_1"] * first_prices["token_1/fiat"]
        )
    if "token_2/fiat" in first_prices and initial_balances["token_2"] > 0:
        initial_portfolio_value += (
            initial_balances["token_2"] * first_prices["token_2/fiat"]
        )

    trader.equity_history = [initial_portfolio_value]
    # Combine all dataframes and sort by timestamp
    result = pd.DataFrame(
        columns=["id", "timestamp", "pair", "side", "qty"],
    )

    # Process data timestamp by timestamp
    for timestamp, group in combined_data.groupby("timestamp"):
        # Update prices for each pair in this timestamp
        market_data = {
            "fee": fee,
        }
        for _, row in group.iterrows():
            pair = row["symbol"]
            data_dict = row.to_dict()
            # Add fee information to market data so strategies can access it
            market_data[pair] = data_dict
            trader.update_market(pair, data_dict)

        # Get strategy decision based on all available market data and current balances
        orders = strategy.on_data(market_data, balances)

        # Handle list of orders
        for order in orders:
            trader.execute(order)
            order["timestamp"] = timestamp
            order["id"] = str(uuid.uuid4())
            result = pd.concat([result, pd.DataFrame([order])], ignore_index=True)

    return result
