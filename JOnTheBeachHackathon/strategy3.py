import numpy as np

MOVING_AVERAGE_WINDOW = 25
VOLATILITY_THRESHOLD = 2.1

# Set risk control parameters
max_percentage_per_transaction = 0.01
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


def calculate_macd(prices, window1, window2):
    ema1 = calculate_ema(prices, window1)
    ema2 = calculate_ema(prices, window2)
    return ema1 - ema2


def calculate_bollinger_bands(prices, window, std_dev):
    sma = calculate_ema(prices, window)
    std = np.std(prices[-window:])
    upper_band = sma + std_dev * std
    lower_band = sma - std_dev * std
    return upper_band, lower_band


def calculate_momentum(prices, window):
    return prices[-1] - prices[-window - 1]


def calculate_stochastic_oscillator(prices, window):
    lowest_low = min(prices[-window:])
    highest_high = max(prices[-window:])
    return (prices[-1] - lowest_low) / (highest_high - lowest_low)


def calculate_force_index(prices, volumes, window):
    fi = [prices[i] * volumes[i] for i in range(len(prices))]
    return np.mean(fi[-window:])


def calculate_on_balance_volume(prices, volumes):
    obv = []
    for i in range(1, len(prices)):
        if prices[i] > prices[i - 1]:
            obv.append(volumes[i])
        elif prices[i] < prices[i - 1]:
            obv.append(-volumes[i])
        else:
            obv.append(0)
    return np.sum(obv)


def calculate_commodity_channel_index(prices, window):
    typical_price = [
        (high + low + close) / 3
        for high, low, close in zip(prices["High"], prices["Low"], prices["Close"])
    ]
    sma = np.mean(typical_price[-window:])
    md = np.mean([abs(typical_price[i] - sma) for i in range(-window, 0)])
    return (typical_price[-1] - sma) / (0.015 * md)


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
        self.window = MOVING_AVERAGE_WINDOW

        # Volatility threshold for signals
        self.threshold = VOLATILITY_THRESHOLD

        # Parameters for technical indicators
        self.ema_window = 10
        self.rsi_window = 14
        self.macd_window1 = 12
        self.macd_window2 = 26

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

        # Define the strategy for each pair
        def strategy(pair, prices, balances):
            price = prices[-1]
            ema = calculate_ema(prices, self.ema_window)
            rsi = calculate_rsi(prices, self.rsi_window)
            macd = calculate_macd(prices, self.macd_window1, self.macd_window2)

            if price < ema and rsi < 30 and macd < 0:
                # Buy with fiat if we have enough fiat
                max_qty = balances["fiat"] * max_percentage_per_transaction / price
                qty = max(min_qty, max_qty)
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_fiat = qty * price * (1 + fee)
                if balances["fiat"] >= required_fiat:
                    return {"pair": pair, "side": "buy", "qty": qty}
            elif price > ema and rsi > 70 and macd > 0:
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
            if token1_token2_price < implied_token1_token2 * 0.995:
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
                    return [{"pair": "token_1/token_2", "side": "buy", "qty": qty}]

            # If actual token_1/token_2 price is significantly higher than implied
            elif token1_token2_price > implied_token1_token2 * 1.005:
                # Sell token_1 for token_2 (if we have token_1)
                max_qty = balances["token_1"] * max_percentage_per_transaction
                qty = max(min_qty, max_qty)
                if qty > 0:
                    return [{"pair": "token_1/token_2", "side": "sell", "qty": qty}]

            # Check for trading opportunities in each pair
            for pair in ["token_1/fiat", "token_2/fiat"]:
                if pair in market_data:
                    prices = self.price_history[pair]
                    order = strategy(pair, prices, balances)
                    if order:
                        orders.append(order)

        return orders


strategy = DefaultStrategy()
