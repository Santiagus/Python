import os


def create_project_structure(base_path="."):
    folders = [
        "pip",
        "data",
        "data/raw",
        "data/processed",
        "notebooks",
        "scripts",
        "strategies",
        "backtest",
        "results",
        "utils",
        "tests",
    ]

    files = {
        "requirements.txt": "\n".join(
            [
                "setuptools",
                "pandas",
                "numpy",
                "pandas-ta",
                "matplotlib",
                "seaborn",
                "scikit-learn",
                "kagglehub",
            ]
        ),
        ".gitignore": "\n".join(
            ["__pycache__/", "*.py[cod]", "*.ipynb_checkpoints", ".env", ".DS_Store"]
        ),
        ".env.example": "KAGGLE_USERNAME=your_kaggle_username\nKAGGLE_KEY=your_kaggle_key\nAPI_KEY=your_api_key_here\n",
        "scripts/add_indicators.py": "# Placeholder for indicator generation script\n",
        "scripts/download_data.py": "# Placeholder for data download script\n",
        "strategies/template_strategy.py": "class TemplateStrategy:\n    def __init__(self, config=None):\n        pass\n\n    def on_tick(self, market_snapshot):\n        # TODO: Make a decision: buy/sell/hold\n        return {}\n",
        "backtest/engine.py": "def run_backtest(strategy, data):\n    # TODO: implement simulation loop\n    pass\n",
        "results/.gitkeep": "",
        "utils/helpers.py": "def calculate_sharpe(returns, freq=252):\n    return (returns.mean() / returns.std()) * (freq ** 0.5)\n",
        "utils/__init__.py": "",
        "tests/test_backtest.py": "# Placeholder for backtest unit tests\n",
    }

    for folder in folders:
        folder_path = os.path.join(base_path, folder)
        os.makedirs(folder_path, exist_ok=True)
        print(f"Created folder: {folder_path}")

    for file_name, content in files.items():
        file_path = os.path.join(base_path, file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        print(f"Created file: {file_path}")


if __name__ == "__main__":
    create_project_structure()
