# Multi-Asset Crypto Trading Strategy

This project simulates a multi-asset crypto trading strategy using OHLCV data and technical indicators. It includes tools for preprocessing data, building and testing strategies, and evaluating performance with realistic metrics.

## 📁 Project Structure

| Folder | Purpose |
|--------|---------|
| `data/raw` | Unmodified downloaded data |
| `data/processed` | Cleaned/enriched data |
| `notebooks` | Interactive exploration and EDA |
| `scripts` | Task automation (download, preprocessing) |
| `strategies` | Trading logic implementations |
| `backtest` | Simulation and evaluation framework |
| `results` | Output logs, plots, and metrics |
| `utils` | Shared helper functions (e.g., Sharpe ratio) |
| `tests` | Unit tests for core logic |
| `.env.example` | Template for required environment variables |

## 🧰 Features

- Clean and enrich historical OHLCV data
- Compute technical indicators like RSI, MACD, Bollinger Bands, ATR, etc.
- Simulate trading strategies in a realistic environment
- Track portfolio performance, returns, and risk metrics (like Sharpe ratio)
- Easily extend with new strategies or timeframes

## 🛠️ Utility Functions

Place evaluation metrics and shared logic (e.g., `calculate_sharpe()`) in `utils/helpers.py`. This keeps them modular and reusable.

## 🚀 Getting Started

1. Clone this repository
2. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3. Download a dataset using:
    ```bash
    python scripts/download_data.py andyjava/crypto-trading-dataset-ohlcv-and-indicators
    ```
4. Add indicators:
    ```bash
    python scripts/add_indicators.py data/raw/BTC.csv data/processed/BTC_enriched.csv
    ```
5. Build and backtest your strategies under `strategies/` and `backtest/`

## 🔧 Requirements

See `requirements.txt` for a list of Python packages needed.

## 📄 License

Apache License 2.0
