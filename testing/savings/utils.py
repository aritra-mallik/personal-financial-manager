from datetime import date
from decimal import Decimal
from django.db.models import Sum, F, Case, When
from dateutil.relativedelta import relativedelta
from finance.models import Income, Expense
from .models import SavingsGoal, SurplusTracker

# -------------------------
# Goal Probability
# -------------------------
def get_goal_probability(user, goal):
    """
    Returns a dict:
      - probability: numeric or message
      - suggested_deadline: date, '--', or '>30 years'
    Handles special cases:
      - goal completed
      - deadline this month
      - deadline passed
      - extreme future years
    """
    today = date.today()

    # Goal completed → override progress and probability
    if goal.is_completed():
        return {"probability": "--", "suggested_deadline": "--"}

    # No deadline → fallback
    if not goal.deadline:
        return {"probability": 100, "suggested_deadline": "--"}

    # Deadline passed
    if goal.deadline < today:
        return {"probability": "Deadline passed, extend it", "suggested_deadline": "--"}

    # Deadline in current month
    if goal.deadline.year == today.year and goal.deadline.month == today.month:
        return {"probability": "Unavailable this month", "suggested_deadline": "--"}

    # Use ML model for probability & suggested deadline
    from ml.probability import predict_goal_probability
    prob_data = predict_goal_probability(user, goal)

    # If probability ≥ 100% → hide suggested deadline
    if isinstance(prob_data.get("probability", 0), (int, float)) and prob_data["probability"] >= 100:
        prob_data["suggested_deadline"] = "--"

    # Ensure suggested_deadline is safe for template
    sd = prob_data.get("suggested_deadline", "--")
    if isinstance(sd, date):
        try:
            # cap any year >9999 or >30 years ahead
            max_allowed_date = today + relativedelta(years=30)
            if sd.year > 9999 or sd > max_allowed_date:
                prob_data["suggested_deadline"] = ">30 years"
        except Exception:
            prob_data["suggested_deadline"] = ">30 years"
    elif isinstance(sd, str):
        # already a string like '>30 years' or '--'
        pass
    else:
        prob_data["suggested_deadline"] = "--"

    return prob_data


# -------------------------
# Monthly Surplus
# -------------------------
def calculate_monthly_surplus(user, year, month):
    total_income = Income.objects.filter(
        user=user, date__year=year, date__month=month
    ).aggregate(Sum("amount"))["amount__sum"] or 0
    total_expense = Expense.objects.filter(
        user=user, date__year=year, date__month=month
    ).aggregate(Sum("amount"))["amount__sum"] or 0
    return max(Decimal(total_income) - Decimal(total_expense), Decimal(0))


def calculate_current_month_balance(user):
    today = date.today()
    total_income = Income.objects.filter(
        user=user, date__year=today.year, date__month=today.month
    ).aggregate(Sum("amount"))["amount__sum"] or 0
    total_expense = Expense.objects.filter(
        user=user, date__year=today.year, date__month=today.month
    ).aggregate(Sum("amount"))["amount__sum"] or 0
    return max(Decimal(total_income) - Decimal(total_expense), Decimal(0))


# -------------------------
# Auto Allocate Surplus
# -------------------------

def auto_allocate_savings(user):
    """
    Allocates only the accumulated balance (previous months' surplus) to goals.
    Current month balance is NOT included.
    """
    tracker, _ = SurplusTracker.objects.get_or_create(user=user)
    
    
    surplus_to_allocate = tracker.last_surplus

    today = date.today()
    goals = SavingsGoal.objects.filter(
        user=user,
        current_amount__lt=F("target_amount"),
        deadline__gte=today
    ).order_by(
        "deadline",
        Case(
            When(priority="High", then=0),
            When(priority="Medium", then=1),
            When(priority="Low", then=2),
            default=3
        ),
        "created_at",
        "id"
    )

    # Allocate surplus fully to one goal at a time
    while surplus_to_allocate > 0 and goals.exists():
        goal = goals.first()
        needed = goal.target_amount - goal.current_amount
        allocation = min(surplus_to_allocate, needed)

        if allocation > 0:
            goal.current_amount += allocation
            goal.save()
            surplus_to_allocate -= allocation

        goals = goals.filter(current_amount__lt=F("target_amount")).order_by(
            "deadline",
            Case(
                When(priority="High", then=0),
                When(priority="Medium", then=1),
                When(priority="Low", then=2),
                default=3
            ),
            "created_at",
            "id"
        )

    # Update accumulated balance only with leftover from previous months
    tracker.last_surplus = surplus_to_allocate
    tracker.save()

    return {
        "accumulated_balance": tracker.last_surplus,
        "current_balance": calculate_current_month_balance(user)  # for display only
    }

# -------------------------
# Goal Deletion / Refund
# -------------------------
def delete_goals_with_refund(user, goals_queryset):
    tracker, _ = SurplusTracker.objects.get_or_create(user=user)
    refund = goals_queryset.aggregate(total=Sum("current_amount"))["total"] or 0
    tracker.last_surplus += Decimal(refund)
    tracker.save()
    count = goals_queryset.count()
    goals_queryset.delete()
    return count, refund
def surplus_rollover(user, excess_amount=0):
    """
    Lazy rollover:
    - Calculates accumulated balance (AB) from all previous months.
    - Allocates surplus to goals directly by updating goal.current_amount.
    - Keeps current month balance (CB) separate.
    """
    tracker, _ = SurplusTracker.objects.get_or_create(user=user)
    today = date.today()
    first_day_current_month = date(today.year, today.month, 1)

    # 1️⃣ Calculate accumulated balance from previous months
    total_income_prev = Income.objects.filter(user=user, date__lt=first_day_current_month).aggregate(
        total=Sum("amount")
    )["total"] or 0
    total_expense_prev = Expense.objects.filter(user=user, date__lt=first_day_current_month).aggregate(
        total=Sum("amount")
    )["total"] or 0
    previous_surplus = Decimal(total_income_prev) - Decimal(total_expense_prev)

    # 2️⃣ Subtract any already allocated amounts (sum of goal.current_amount for incomplete goals)
    total_allocated = SavingsGoal.objects.filter(user=user).aggregate(
        total=Sum("current_amount")
    )["total"] or 0

    # 3️⃣ Set the tracker with leftover from previous months + excess
    tracker.last_surplus = max(previous_surplus - Decimal(total_allocated), Decimal(0)) + Decimal(excess_amount)
    tracker.save()

    surplus_to_allocate = tracker.last_surplus

    # 4️⃣ Fetch active goals ordered by deadline → priority → creation
    goals = SavingsGoal.objects.filter(
        user=user,
        current_amount__lt=F("target_amount"),
        deadline__gte=today
    ).order_by(
        "deadline",
        Case(
            When(priority="High", then=0),
            When(priority="Medium", then=1),
            When(priority="Low", then=2),
            default=3
        ),
        "created_at",
        "id"
    )

    # 5️⃣ Allocate surplus to goals directly
    for goal in goals:
        if surplus_to_allocate <= 0:
            break
        needed = goal.target_amount - goal.current_amount
        allocation = min(surplus_to_allocate, needed)
        goal.current_amount += allocation
        goal.save()
        surplus_to_allocate -= allocation

    # 6️⃣ Update remaining accumulated balance
    tracker.last_surplus = surplus_to_allocate
    tracker.save()

    # 7️⃣ Return both accumulated and current month balances
    current_month_income = Income.objects.filter(user=user, date__year=today.year, date__month=today.month).aggregate(
        total=Sum("amount")
    )["total"] or 0
    current_month_expense = Expense.objects.filter(user=user, date__year=today.year, date__month=today.month).aggregate(
        total=Sum("amount")
    )["total"] or 0
    current_balance = max(Decimal(current_month_income) - Decimal(current_month_expense), Decimal(0))

    return {
        "accumulated_balance": tracker.last_surplus,
        "current_balance": current_balance
    }