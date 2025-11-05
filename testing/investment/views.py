# investment/views.py
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum

from .models import Investment
from .forms import InvestmentForm
from finance.models import Income  # make sure finance app is in INSTALLED_APPS


def _to_decimal(value):
    """Helper to ensure value is Decimal."""
    if value is None:
        return Decimal('0')
    return value if isinstance(value, Decimal) else Decimal(str(value))


@login_required
def investment_list(request):
    investments = Investment.objects.filter(user=request.user)
    return render(request, 'investment/investment_list.html', {'investments': investments})


@login_required
def add_investment(request):
    if request.method == 'POST':
        form = InvestmentForm(request.POST)
        if form.is_valid():
            inv = form.save(commit=False)
            inv.user = request.user
            inv.status = "Active"
            inv.save()
            return redirect('investment_list')
    else:
        form = InvestmentForm()
    return render(request, 'investment/investment_form.html', {'form': form})


@login_required
def edit_investment(request, id):
    investment = get_object_or_404(Investment, id=id, user=request.user)
    if request.method == 'POST':
        form = InvestmentForm(request.POST, instance=investment)
        if form.is_valid():
            form.save()
            return redirect('investment_list')
    else:
        form = InvestmentForm(instance=investment)
    return render(request, 'investment/investment_form.html', {'form': form})


@login_required
def delete_investment(request, id):
    investment = get_object_or_404(Investment, id=id, user=request.user)
    if request.method == 'POST':
        investment.delete()
        return redirect('investment_list')
    return render(request, 'investment/investment_confirm_delete.html', {'investment': investment})


@login_required
@transaction.atomic
def investment_portfolio(request):
    """
    Display all investments, compute totals, and create Income records for matured investments.
    """
    investments = Investment.objects.filter(user=request.user)
    today = date.today()

    total_invested = Decimal('0')
    total_estimated_value = Decimal('0')
    total_profit = Decimal('0')
    total_return_rate = Decimal('0')
    valid_returns = 0

    def choose_income_category(inv_type):
        t = (inv_type or "").lower()
        if t in ['fd', 'fixed deposit', 'rd', 'recurring deposit', 'bond']:
            return "Interest Income"
        if t in ['stock', 'mutual fund', 'etf', 'crypto']:
            return "Dividends"
        if t in ['real estate', 'pension']:
            return "Rental Income"
        if t in ['gold']:
            return "Other Income"
        return "Other Income"

    for inv in investments:
        amount = _to_decimal(inv.amount)
        expected_return = _to_decimal(inv.expected_return or Decimal('0'))

        years = Decimal('1')
        if inv.start_date and inv.end_date:
            days = (inv.end_date - inv.start_date).days
            years_float = max(1, days / 365)
            years = Decimal(str(years_float))

        # --- Compute estimated value (simple interest style)
        estimated_value = amount
        if expected_return != 0:
            estimated_value = amount + (amount * (expected_return / Decimal('100')) * years)

        estimated_value_rounded = estimated_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        profit_estimate = (estimated_value_rounded - amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        inv._estimated_value = estimated_value_rounded
        inv._profit_estimate = profit_estimate

        total_invested += amount
        total_estimated_value += estimated_value_rounded
        total_profit += profit_estimate

        if expected_return != 0:
            total_return_rate += expected_return
            valid_returns += 1

        # --- Auto-create income on maturity ---
        if inv.end_date and inv.end_date <= today and inv.status != "Completed":
            existing_income = Income.objects.filter(
                user=request.user,
                source=f"Investment Maturity - {inv.name}",
                date=inv.end_date
            ).exists()

            if not existing_income:
                category = choose_income_category(inv.investment_type)

                # ✅ Determine actual value to record in income history
                if profit_estimate > 0:
                    income_amount = estimated_value_rounded  # profit case (invested + profit)
                elif profit_estimate < 0:
                    income_amount = estimated_value_rounded  # loss case (invested - loss)
                else:
                    income_amount = amount  # neutral, no profit/loss

                # ✅ Always create income entry with calculated amount
                Income.objects.create(
                    user=request.user,
                    source=f"Investment Maturity - {inv.name}",
                    amount=income_amount,
                    date=inv.end_date,
                    category=category
                )

            inv.status = "Completed"
            inv.save(update_fields=["status"])

    avg_return = (total_return_rate / valid_returns).quantize(Decimal('0.01')) if valid_returns else Decimal('0')

    # -------------------------
    # Chart Data
    # -------------------------
    monthly_data_invested = {}
    monthly_data_estimated = {}
    for inv in investments:
        if inv.start_date:
            label = inv.start_date.strftime('%b %Y')
            monthly_data_invested[label] = monthly_data_invested.get(label, 0) + float(inv.amount)
            monthly_data_estimated[label] = monthly_data_estimated.get(label, 0) + float(inv._estimated_value)

    months = list(monthly_data_invested.keys())
    invested_amounts = list(monthly_data_invested.values())
    estimated_amounts = [monthly_data_estimated.get(m, 0) for m in months]

    # -------------------------
    # 📊 Category Comparison Data
    # -------------------------
    category_investments = (
        investments.values('investment_type')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    category_labels = [c['investment_type'] for c in category_investments]
    category_values = [float(c['total']) for c in category_investments]

    context = {
        "investments": investments,
        "total_invested": total_invested.quantize(Decimal('0.01')),
        "total_estimated_value": total_estimated_value.quantize(Decimal('0.01')),
        "total_profit": total_profit.quantize(Decimal('0.01')),
        "avg_return": avg_return,
        "year": today.year,
        "months": months,
        "invested_amounts": invested_amounts,
        "estimated_amounts": estimated_amounts,
        "category_labels": category_labels,
        "category_values": category_values,
    }
    return render(request, "investment/investment_portfolio.html", context)

