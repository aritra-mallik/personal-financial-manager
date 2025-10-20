from datetime import date
from dateutil.relativedelta import relativedelta
import numpy as np
from sklearn.linear_model import LinearRegression
from savings.models import SavingsGoal
from savings.utils import calculate_monthly_surplus

MAX_DISPLAY_YEARS = 30
MAX_DJANGO_YEAR = 9999

def get_last_n_months_surplus(user, n=12):
    today = date.today()
    surplus_list = []
    for i in range(n, 0, -1):
        month = today - relativedelta(months=i)
        surplus = float(calculate_monthly_surplus(user, month.year, month.month))
        surplus_list.append(surplus)
    return surplus_list

def predict_goal_probability(user, goal: SavingsGoal):
    today = date.today()
    probability = None
    suggested_deadline = "--"

    # --- Past deadline ---
    if goal.deadline and goal.deadline < today:
        return {"probability": "Deadline has passed. Please extend.", "suggested_deadline": "--"}

    # --- Current month deadline ---
    if goal.deadline and goal.deadline.year == today.year and goal.deadline.month == today.month:
        probability = "Not available for current month"

    # --- Goal already reached or no deadline ---
    if not goal.deadline or goal.remaining_amount() <= 0:
        return {"probability": 100.0, "suggested_deadline": "--"}

    # --- Surplus & regression ---
    last_surplus = get_last_n_months_surplus(user)
    n_months = len(last_surplus)
    avg_surplus = np.mean(last_surplus) if last_surplus else 0.0
    remaining_amount = float(goal.remaining_amount())

    if n_months >= 3:
        X = np.arange(n_months).reshape(-1, 1)
        y = np.cumsum(last_surplus)
        model = LinearRegression().fit(X, y)
        slope = max(model.coef_[0], avg_surplus)
    else:
        slope = avg_surplus

    # --- Probability ---
    months_left = max((goal.deadline.year - today.year) * 12 + goal.deadline.month - today.month, 1)
    projected_total = float(goal.current_amount) + slope * months_left

    if probability is None:
        probability = min(projected_total / float(goal.target_amount), 1) * 100
        probability = round(probability, 2)

    # --- Suggested deadline ---
    if slope > 0:
        months_needed = remaining_amount / slope
        months_needed *= 1.05  # 5% leeway

        # Cap suggested deadline at today + MAX_DISPLAY_YEARS
        max_allowed_date = today + relativedelta(years=MAX_DISPLAY_YEARS)
        try:
            temp_date = today + relativedelta(months=int(np.ceil(months_needed)))
            if temp_date.year > MAX_DJANGO_YEAR or temp_date > max_allowed_date:
                suggested_deadline = f">{MAX_DISPLAY_YEARS} years"
            else:
                suggested_deadline = temp_date
        except Exception:
            suggested_deadline = f">{MAX_DISPLAY_YEARS} years"

    # Hide suggested deadline if probability >= 100%
    if isinstance(probability, (int, float)) and probability >= 100:
        suggested_deadline = "--"

    return {"probability": probability, "suggested_deadline": suggested_deadline}
