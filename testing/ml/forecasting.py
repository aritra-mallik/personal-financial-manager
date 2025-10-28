import pandas as pd
from django.utils.timezone import now
from finance.models import Expense
from sklearn.linear_model import LinearRegression
import numpy as np

def get_user_expense_forecast(user, forecast_date=None):
    """
    Expense forecast logic (clean + consistent):
    - < 20 total records AND < 2 entries/day → "Need more data for accurate prediction"
    - Otherwise → Linear regression forecast
    - "Nothing spent so far" if no spending this month
    """
    today = forecast_date or now().date()
    first_day_of_month = pd.Timestamp(today.replace(day=1))
    days_in_this_month = pd.Period(f"{today.year}-{today.month:02d}").days_in_month
    today_day = today.day
    progress_ratio = today_day / days_in_this_month

    # ---- 1. Fetch all user expenses ----
    expenses_qs = Expense.objects.filter(user=user).order_by("date")
    if not expenses_qs.exists():
        return {
            "this_month_expected": "Need more data for accurate prediction",
            "spent_so_far": "Nothing spent so far",
            "next_month_expected": "Need more data for accurate prediction",
        }

    df = pd.DataFrame(list(expenses_qs.values("date", "amount")))
    df = df.rename(columns={"date": "ds", "amount": "y"})
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = df["y"].astype(float)

    # ---- 2. Calculate spent so far ----
    this_month_df = df[(df["ds"].dt.year == today.year) & (df["ds"].dt.month == today.month)]
    if this_month_df.empty:
        spent_so_far = "Nothing spent so far"
    else:
        spent_so_far = round(this_month_df["y"].sum(), 2)

    # ---- 3. Data sufficiency check ----
    total_rows = len(df)
    daily_counts = df.groupby(df["ds"].dt.date)["y"].count()
    avg_entries_per_day = daily_counts.mean() if not daily_counts.empty else 0

    if total_rows < 20 and avg_entries_per_day < 2:
        return {
            "this_month_expected": "Need more data for accurate prediction",
            "spent_so_far": spent_so_far,
            "next_month_expected": "Need more data for accurate prediction",
        }

    # ---- 4. Helper: Linear regression forecast ----
    def daily_series(df_input):
        if df_input.empty:
            return pd.DataFrame(columns=["ds", "y"])
        df_daily = df_input.groupby("ds", as_index=False)["y"].sum()
        df_daily = df_daily.set_index("ds").resample("D").sum().reset_index()
        return df_daily

    def linear_regression_forecast(df_input, days_in_month):
        df_daily = daily_series(df_input)
        if df_daily.empty:
            return None
        df_daily["day_index"] = np.arange(len(df_daily))
        X = df_daily["day_index"].values.reshape(-1, 1)
        y = df_daily["y"].values
        model = LinearRegression()
        model.fit(X, y)
        future_days = np.arange(len(df_daily), len(df_daily) + days_in_month).reshape(-1, 1)
        y_pred = model.predict(future_days)
        return round(float(max(y_pred.sum(), 0.0)), 2)

    # ---- 5. Forecast calculations ----
    past_df = df[df["ds"] < first_day_of_month]
    this_month_forecast = linear_regression_forecast(past_df, days_in_this_month)

    # Slight smoothing if we're near month-end
    if isinstance(spent_so_far, (int, float)) and this_month_forecast is not None:
        if progress_ratio > 0.8:
            this_month_forecast = round(
                progress_ratio * spent_so_far + (1 - progress_ratio) * this_month_forecast, 2
            )

    # Next month forecast
    next_month = (today.month % 12) + 1
    next_year = today.year + (1 if next_month == 1 else 0)
    days_in_next_month = pd.Period(f"{next_year}-{next_month:02d}").days_in_month
    next_month_forecast = linear_regression_forecast(df, days_in_next_month)

    return {
        "this_month_expected": (
            this_month_forecast if this_month_forecast is not None else "Need more data for accurate prediction"
        ),
        "spent_so_far": spent_so_far,
        "next_month_expected": (
            next_month_forecast if next_month_forecast is not None else "Need more data for accurate prediction"
        ),
    }