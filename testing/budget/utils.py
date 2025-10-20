# budget/utils.py
from decimal import Decimal
from django.contrib import messages
from django.utils import timezone
from .models import Budget, BudgetCategory

def check_budget_warnings(request, expense):
    """
    Check budget warnings for the given expense's category.
    Uses percentage-based BudgetCategory limits.
    """
    user = request.user
    category_name = expense.category
    today = timezone.now().date()

    # Find active budgets that include this category
    active_budgets = Budget.objects.filter(
        user=user,
        start_date__lte=today,
        end_date__gte=today,
        categories__category=category_name
    ).distinct()

    for budget in active_budgets:
        # Get the category object in this budget
        cat_obj = budget.categories.filter(category=category_name).first()
        if not cat_obj:
            continue  # Category not part of this budget

        spent = cat_obj.spent()
        limit = cat_obj.limit_amount()  # compute based on percentage of budget

        # Category-level warning
        if spent > limit:
            messages.warning(
                request,
                f"⚠️ You have exceeded the limit for category '{category_name}' "
                f"in budget '{budget.name}'. Spent: {spent}, Limit: {limit}"
            )

        # Total budget warning
        total_spent = sum(c.spent() for c in budget.categories.all())
        total_limit = budget.total_amount
        if total_spent > total_limit:
            messages.error(
                request,
                f"🚨 Your total spending ({total_spent}) exceeded the budget '{budget.name}' limit ({total_limit})!"
            )
