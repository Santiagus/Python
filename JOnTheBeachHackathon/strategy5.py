import numpy as np


# Set risk control parameters
max_percentage_per_transaction = 0.004
min_qty = 0.05
stop_loss_percentage = 0.05
take_profit_percentage = 0.15

# Define the strategy parameters
rsi_buy_threshold = 15
rsi_sell_threshold = 90
macd_buy_threshold = -0.25
macd_sell_threshold = 0.25

# Parameters for technical indicators
ema_window = 21
rsi_window = 14
macd_window1 = 12
macd_window2 = 26


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


def moving_average_crossover(prices, short_term_ma_window, long_term_ma_window):
    short_term_ma = calculate_ema(prices, short_term_ma_window)
    long_term_ma = calculate_ema(prices, long_term_ma_window)
    if short_term_ma > long_term_ma and prices[-1] > long_term_ma:
        return True
    elif short_term_ma < long_term_ma and prices[-1] < long_term_ma:
        return False
    else:
        return None


def rsi_reversal(prices, rsi_window, oversold_threshold, overbought_threshold):
    rsi = calculate_rsi(prices, rsi_window)
    if rsi < oversold_threshold:
        return True
    elif rsi > overbought_threshold:
        return False
    else:
        return None


def calculate_atr(prices, window):
    highs = [price["high"] for price in prices[-window:]]
    lows = [price["low"] for price in prices[-window:]]
    closes = [price["close"] for price in prices[-window:]]
    atr_values = []
    for i in range(1, len(highs)):
        true_range = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        atr_values.append(true_range)
    atr = np.mean(atr_values)
    return atr


def bollinger_band_mean_reversion(prices, ma_window, std_dev):
    ma = calculate_ema(prices, ma_window)
    std = np.std(prices[-ma_window:])
    upper_band = ma + std_dev * std
    lower_band = ma - std_dev * std
    if prices[-1] < lower_band and calculate_rsi(prices, 14) < 30:
        return True
    elif prices[-1] > upper_band and calculate_rsi(prices, 14) > 70:
        return False
    else:
        return None


def macd_momentum(
    prices, short_term_ma_window, long_term_ma_window, signal_line_window
):
    macd = calculate_macd(prices, short_term_ma_window, long_term_ma_window)
    signal_line = calculate_ema(macd, signal_line_window)
    if macd > signal_line:
        return True
    elif macd < signal_line:
        return False
    else:
        return None


def volume_spike_confirmation(prices, volumes, average_volume_window):
    average_volume = np.mean(volumes[-average_volume_window:])
    if volumes[-1] > 2 * average_volume and prices[-1] > prices[-2]:
        return True
    elif volumes[-1] > 2 * average_volume and prices[-1] < prices[-2]:
        return False
    else:
        return None


def atr_based_stop_loss_and_take_profit(prices, atr_window):
    atr = calculate_atr(prices, atr_window)
    sl = prices[-1] - 1.5 * atr
    tp = prices[-1] + 2 * atr
    return sl, tp


def super_trend_following(prices, atr_window, multiplier):
    atr = calculate_atr(prices, atr_window)
    upper_band = prices[-1] + multiplier * atr
    lower_band = prices[-1] - multiplier * atr
    if prices[-1] > upper_band:
        return True
    elif prices[-1] < lower_band:
        return False
    else:
        return None


def calculate_vwap(prices, volumes, window):
    vwap_values = []
    for i in range(len(prices) - window + 1):
        vwap_value = np.sum(
            [prices[j] * volumes[j] for j in range(i, i + window)]
        ) / np.sum(volumes[i : i + window])
        vwap_values.append(vwap_value)
    return vwap_values[-1]


def vwap_pullback_buy(prices, volumes, vwap_window):
    vwap = calculate_vwap(prices, volumes, vwap_window)
    if prices[-1] < vwap and prices[-1] > prices[-2]:
        return True
    elif prices[-1] > vwap and prices[-1] < prices[-2]:
        return False
    else:
        return None


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
        self.window = ema_window

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
            ema = calculate_ema(prices, ema_window)
            rsi = calculate_rsi(prices, rsi_window)
            macd = calculate_macd(prices, macd_window1, macd_window2)

            if price < ema and rsi < rsi_buy_threshold and macd < macd_buy_threshold:
                # Buy with fiat if we have enough fiat
                max_qty = balances["fiat"] * max_percentage_per_transaction / price
                qty = max(min_qty, max_qty)
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_fiat = qty * price * (1 + fee)
                if balances["fiat"] >= required_fiat:
                    return {"pair": pair, "side": "buy", "qty": qty}
            elif (
                price > ema and rsi > rsi_sell_threshold and macd > macd_sell_threshold
            ):
                # Sell for fiat if we have enough token
                token = pair.split("/")[0]
                available_balance = balances[token]
                max_qty = balances[token] * max_percentage_per_transaction
                qty = min(
                    max_qty, available_balance
                )  # Limit selling to available balance
                if qty > 0:
                    return {"pair": pair, "side": "sell", "qty": qty}

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
                    # Place buy order
                    buy_order = {"pair": "token_1/token_2", "side": "buy", "qty": qty}
                    # Place sell order to cash out
                    sell_order = {"pair": "token_1/fiat", "side": "sell", "qty": qty}
                    return [buy_order, sell_order]

            # If actual token_1/token_2 price is significantly higher than implied
            elif token1_token2_price > implied_token1_token2 * 1.005:
                # Sell token_1 for token_2 (if we have token_1)
                max_qty = balances["token_1"] * max_percentage_per_transaction
                qty = max(min_qty, max_qty)
                if qty > 0:
                    # Place sell order
                    sell_order = {"pair": "token_1/token_2", "side": "sell", "qty": qty}
                    # Place buy order to cash out
                    buy_order = {"pair": "token_2/fiat", "side": "buy", "qty": qty}
                    return [sell_order, buy_order]

        # Check for trading opportunities in each pair
        for pair in ["token_1/fiat", "token_2/fiat"]:
            if pair in market_data:
                prices = self.price_history[pair]
                order = strategy(pair, prices, balances)
                if order:
                    orders.append(order)

        return orders


strategy = DefaultStrategy()
