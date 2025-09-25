import numpy as np


# Set risk control parameters
max_percentage_per_transaction = 0.002
min_qty = 0.02


# Define the technical indicators
def calculate_ema(prices, window):
    return np.mean(prices[-window:])


def calculate_rsi(prices, window):
    gains = [max(0, prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    losses = [max(0, prices[i - 1] - prices[i]) for i in range(1, len(prices))]
    avg_gain = np.mean(gains[-window:])
    avg_loss = np.mean(losses[-window:])

    # Check for division by zero
    if avg_loss == 0:
        return 100  # RSI is 100 when there are no losses

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# Define the strategy parameters
BUY_THRESHOLD = 10
SELL_THRESHOLD = 90
EMA_WINDOW = 21
RSI_WINDOW = 14
STD_DEV = 2.1


class DefaultStrategy:
    def __init__(self):
        self.initialized = False

        # Price history for each pair - this maintains state between calls
        self.price_history = {
            "token_1/fiat": [],
            "token_2/fiat": [],
            "token_1/token_2": [],
        }

        # Window size for moving averages
        self.window = EMA_WINDOW

    def on_data(self, market_data, balances):

        orders = []

        # Update price history for each pair
        for pair, data in market_data.items():
            if pair in self.price_history:
                self.price_history[pair].append(data["close"])
                # Limit history length
                if len(self.price_history[pair]) > self.window:
                    self.price_history[pair] = self.price_history[pair][-self.window :]

        # Wait until we have enough data points
        for prices in self.price_history.values():
            if len(prices) < self.window:
                return orders

        def strategy(pair, prices, balances):
            price = prices[-1]
            sma = calculate_ema(prices, EMA_WINDOW)
            std = np.std(prices[-EMA_WINDOW:])
            upper_band = sma + STD_DEV * std
            lower_band = sma - STD_DEV * std
            rsi = calculate_rsi(prices, RSI_WINDOW)

            if price < lower_band and rsi < BUY_THRESHOLD:
                # Buy with fiat if we have enough fiat
                max_qty = balances["fiat"] * max_percentage_per_transaction / price
                qty = max(min_qty, max_qty)
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_fiat = qty * price * (1 + fee)
                if balances["fiat"] >= required_fiat:
                    return {"pair": pair, "side": "buy", "qty": qty}
            elif price > upper_band and rsi > SELL_THRESHOLD:
                # Sell for fiat if we have enough token
                token = pair.split("/")[0]
                available_balance = balances[token]
                max_qty = balances[token] * max_percentage_per_transaction
                qty = min(
                    max_qty, available_balance
                )  # Limit selling to available balance
                if qty > 0:
                    return {"pair": pair, "side": "sell", "qty": qty}
            return None

        # Check for arbitrage opportunities
        if all(
            pair in market_data
            for pair in ["token_1/fiat", "token_2/fiat", "token_1/token_2"]
        ):
            token1_price = market_data["token_1/fiat"]["close"]
            token2_price = market_data["token_2/fiat"]["close"]
            token1_token2_price = market_data["token_1/token_2"]["close"]

            # Calculate implied token_1/token_2 price
            implied_token1_token2 = token1_price / token2_price

            # If actual token_1/token_2 price is significantly lower than implied
            if token1_token2_price < implied_token1_token2 * 0.9925:
                # Buy token_1 with token_2 (if we have token_2)
                max_qty = (
                    balances["token_2"]
                    * max_percentage_per_transaction
                    / token1_token2_price
                )
                qty = max(min_qty, max_qty)
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_token2 = qty * token1_token2_price * (1 + fee)
                if balances["token_2"] >= required_token2:
                    # Place buy order
                    buy_order = {"pair": "token_1/token_2", "side": "buy", "qty": qty}
                    return [buy_order]

            # If actual token_1/token_2 price is significantly higher than implied
            elif token1_token2_price > implied_token1_token2 * 1.0025:
                # Sell token_1 for token_2 (if we have token_1)
                max_qty = balances["token_1"] * max_percentage_per_transaction
                qty = max(min_qty, max_qty)
                if qty > 0:
                    # Place sell order
                    sell_order = {"pair": "token_1/token_2", "side": "sell", "qty": qty}
                    return [sell_order]

        # Check for trading opportunities in each pair
        for pair in ["token_1/fiat", "token_2/fiat"]:
            if pair in market_data:
                prices = self.price_history[pair]
                order = strategy(pair, prices, balances)
                if order:
                    orders.append(order)

        return orders


strategy = DefaultStrategy()
