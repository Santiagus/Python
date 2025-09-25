import pandas as pd
import json
from pathlib import Path
from backtest import run_backtest
from metrics import calculate_metrics

DATA_PATH = Path("./kaggle/input")

HYPERPARAMETERS = json.loads(
    list(DATA_PATH.glob("*/hyperparameters.json"))[0].read_text()
)
FEE = HYPERPARAMETERS.get("fee", 3.0) / 10000
BALANCE_FIAT = HYPERPARAMETERS.get("fiat_balance", 10000.0)
BALANCE_TOKEN1 = HYPERPARAMETERS.get("token1_balance", 0.0)
BALANCE_TOKEN2 = HYPERPARAMETERS.get("token2_balance", 0.0)
# INPUT = list(DATA_PATH.glob("*/test.csv"))[0]
INPUT = list(DATA_PATH.glob("*/dataset02.csv"))[0]

OUTPUT = "submission.csv"

combined_data = pd.read_csv(INPUT)

# Run the backtest on the provided test data with a fee of 0.02% and initial balances of 10,000 fiat, and 0 token_1 and token_2
result = run_backtest(
    combined_data,
    FEE,
    {
        "fiat": BALANCE_FIAT,
        "token_1": BALANCE_TOKEN1,
        "token_2": BALANCE_TOKEN2,
    },
)

# Calculate metrics
metrics = calculate_metrics(
    result,
    combined_data,
    FEE,
    {
        "fiat": BALANCE_FIAT,
        "token_1": BALANCE_TOKEN1,
        "token_2": BALANCE_TOKEN2,
    },
)
print(json.dumps(metrics, indent=4))

# Output the backtest result to a CSV file for submission
result.to_csv(OUTPUT, index=False)
