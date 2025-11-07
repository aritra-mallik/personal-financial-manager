import pandas as pd
import numpy as np
from django.utils.timezone import now
from sklearn.linear_model import LinearRegression
from finance.models import Expense

# ---- Forecast helper ----
def linear_regression_forecast(df_input, days_in_future):
    """
    Linear regression forecast.
    df_input: daily totals DataFrame with columns ['ds', 'y']
    days_in_future: number of days to forecast
    """
    if df_input.empty or len(df_input) < 20:
        return "Insufficient data"
    
    df_input = df_input.copy()
    df_input["day_index"] = np.arange(len(df_input))
    X = df_input[["day_index"]].values
    y = df_input["y"].values
    model = LinearRegression()
    model.fit(X, y)
    
    future_days = np.arange(len(df_input), len(df_input) + days_in_future).reshape(-1, 1)
    preds = model.predict(future_days)
    
    # Ensure forecast is realistic: at least the average daily expense
    avg_daily = max(y.mean(), 0)
    preds = np.maximum(preds, avg_daily)
    
    return round(float(preds.sum()), 2)


# ---- Load and preprocess expenses ----
def get_daily_expenses(user):
    expenses_qs = Expense.objects.filter(user=user).order_by("date")
    if not expenses_qs.exists():
        return pd.DataFrame(columns=["ds", "y"])
    
    df = pd.DataFrame(list(expenses_qs.values("date", "amount")))
    df.rename(columns={"date": "ds", "amount": "y"}, inplace=True)
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = df["y"].astype(float)
    
    # Aggregate daily totals and fill missing days with 0
    df_daily = (
        df.groupby("ds", as_index=False)["y"].sum()
        .set_index("ds")
        .resample("D")
        .sum()
        .fillna(0)
        .reset_index()
    )
    
    df_daily["ds"] = pd.to_datetime(df_daily["ds"])
    
    return df_daily


# ---- Forecast for This Month ----
def forecast_this_month(user, forecast_date=None):
    today = forecast_date or now().date()
    current_month = pd.Period(f"{today.year}-{today.month:02d}")
    days_in_this_month = current_month.days_in_month

    df_daily_all = get_daily_expenses(user)
    if df_daily_all.empty:
        return "Insufficient data"

    # Use all previous months combined
    prev_months_df = df_daily_all[df_daily_all["ds"].dt.to_period("M") < current_month]
    if len(prev_months_df) < 20:
        return "Insufficient data"
    
    return linear_regression_forecast(prev_months_df, days_in_this_month)


# ---- Forecast for Next Month ----
def forecast_next_month(user, forecast_date=None):
    today = forecast_date or now().date()
    current_month = pd.Period(f"{today.year}-{today.month:02d}")
    days_in_next_month = (current_month + 1).days_in_month

    df_daily_all = get_daily_expenses(user)
    if df_daily_all.empty:
        return "Insufficient data"

    # Use previous months + current month
    prev_months_df = df_daily_all[df_daily_all["ds"].dt.to_period("M") < current_month]
    current_month_df = df_daily_all[df_daily_all["ds"].dt.to_period("M") == current_month]
    
    combined_df = pd.concat([prev_months_df, current_month_df])
    
    if len(combined_df) < 20:
        return "Insufficient data"

    return linear_regression_forecast(combined_df, days_in_next_month)



# ---- Spent so far (Current Month) ----
def spent_so_far_this_month(user, forecast_date=None):
    today = forecast_date or now().date()
    current_month = pd.Period(f"{today.year}-{today.month:02d}")
    df_daily_all = get_daily_expenses(user)
    if df_daily_all.empty:
        return "Nothing spent so far"

    this_month_df = df_daily_all[df_daily_all["ds"].dt.to_period("M") == current_month]
    spent_sum = round(this_month_df["y"].sum(), 2)
    return spent_sum if spent_sum > 0 else "Nothing spent so far"


# ---- Wrapper ----
def get_user_expense_forecast(user, forecast_date=None):
    spent = spent_so_far_this_month(user, forecast_date)
    this_month = forecast_this_month(user, forecast_date)
    next_month = forecast_next_month(user, forecast_date)

    return {
        "spent_so_far": spent,
        "this_month_expected": this_month,
        "next_month_expected": next_month,
    }