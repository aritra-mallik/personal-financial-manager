from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from datetime import date
from decimal import Decimal
from finance.models import Income, Expense
from .models import SavingsGoal, SurplusTracker
from .utils import calculate_monthly_surplus, auto_allocate_savings

def recalc_goal_allocations(user):
    """
    Recalculates goal allocations based on current income/expense data.
    Resets all goal.current_amount and updates accumulated balance (previous months only).
    """
    # 1️⃣ Reset all goal amounts
    goals = SavingsGoal.objects.filter(user=user)
    for goal in goals:
        goal.current_amount = Decimal(0)
        goal.save()

    # 2️⃣ Reset accumulated balance
    tracker, _ = SurplusTracker.objects.get_or_create(user=user)
    tracker.last_surplus = Decimal(0)
    tracker.save()

    # 3️⃣ Reapply allocations month by month (exclude current month)
    today = date.today()
    first_month = min(
        Income.objects.filter(user=user).values_list('date', flat=True).first() or today,
        Expense.objects.filter(user=user).values_list('date', flat=True).first() or today
    )

    month_cursor = date(first_month.year, first_month.month, 1)
    current_month_start = date(today.year, today.month, 1)

    while month_cursor < current_month_start:
        # Calculate surplus for this month
        surplus = calculate_monthly_surplus(user, month_cursor.year, month_cursor.month)
        tracker.last_surplus += surplus
        tracker.save()

        # Auto allocate surplus to goals
        auto_allocate_savings(user)

        # Move to next month
        if month_cursor.month == 12:
            month_cursor = date(month_cursor.year + 1, 1, 1)
        else:
            month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)


# -------------------------
# Income Signals
# -------------------------
@receiver(post_save, sender=Income)
def income_saved(sender, instance, created, **kwargs):
    recalc_goal_allocations(instance.user)


@receiver(post_delete, sender=Income)
def income_deleted(sender, instance, **kwargs):
    recalc_goal_allocations(instance.user)


# -------------------------
# Expense Signals
# -------------------------
@receiver(post_save, sender=Expense)
def expense_saved(sender, instance, created, **kwargs):
    recalc_goal_allocations(instance.user)


@receiver(post_delete, sender=Expense)
def expense_deleted(sender, instance, **kwargs):
    recalc_goal_allocations(instance.user)