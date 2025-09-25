import numpy as np


MOVING_AVERAGE_WINDOW = 20
VOLATILITY_THRESHOLD = 2.1


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

    def on_data(self, market_data, balances):
        """Process market data and current balances to make trading decisions.

        Args:
            market_data: Dictionary of {pair: tick_data} containing market data for each pair
            balances: Dictionary of {currency: amount} containing current balances

        Returns:
            Trading signal dict {pair, side, qty} or None
        """
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

        # Initialize flag for trading
        if not self.initialized:
            self.initialized = True
            return orders

        # Check for trading opportunities in token_1/fiat
        if "token_1/fiat" in market_data:
            prices = self.price_history["token_1/fiat"]
            price = prices[-1]
            mu, sigma = np.mean(prices), np.std(prices)

            if price < mu - self.threshold * sigma:
                # Buy token_1 with fiat if we have enough fiat
                qty = 0.01
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_fiat = qty * price * (1 + fee)
                if balances["fiat"] >= required_fiat:
                    orders.append({"pair": "token_1/fiat", "side": "buy", "qty": qty})

            elif price > mu + self.threshold * sigma:
                # Sell token_1 for fiat if we have enough token_1
                qty = min(
                    0.01, balances["token_1"]
                )  # Adjust qty based on available balance
                if qty > 0:
                    orders.append({"pair": "token_1/fiat", "side": "sell", "qty": qty})

        # Check for trading opportunities in token_2/fiat
        if "token_2/fiat" in market_data:
            prices = self.price_history["token_2/fiat"]
            price = prices[-1]
            mu, sigma = np.mean(prices), np.std(prices)

            if price < mu - self.threshold * sigma:
                # Buy token_2 with fiat if we have enough fiat
                qty = 0.1
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_fiat = qty * price * (1 + fee)
                if balances["fiat"] >= required_fiat:
                    orders.append({"pair": "token_2/fiat", "side": "buy", "qty": qty})

            elif price > mu + self.threshold * sigma:
                # Sell token_2 for fiat if we have enough token_2
                qty = min(
                    0.1, balances["token_2"]
                )  # Adjust qty based on available balance
                if qty > 0:
                    orders.append({"pair": "token_2/fiat", "side": "sell", "qty": qty})

        # Check for arbitrage opportunities with token_1/token_2
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
                qty_token1 = 0.01
                # Get fee from market_data if available, otherwise use default
                fee = market_data["fee"]
                required_token2 = qty_token1 * token1_token2_price * (1 + fee)
                if balances["token_2"] >= required_token2:
                    orders.append(
                        {"pair": "token_1/token_2", "side": "buy", "qty": qty_token1}
                    )

            # If actual token_1/token_2 price is significantly higher than implied
            elif token1_token2_price > implied_token1_token2 * 1.005:
                # Sell token_1 for token_2 (if we have token_1)
                qty_token1 = min(
                    0.01, balances["token_1"]
                )  # Adjust qty based on available balance
                if qty_token1 > 0:
                    orders.append(
                        {"pair": "token_1/token_2", "side": "sell", "qty": qty_token1}
                    )

        return orders


strategy = DefaultStrategy()
