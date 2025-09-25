def calculate_sharpe(returns, freq=252):
    return (returns.mean() / returns.std()) * (freq ** 0.5)
