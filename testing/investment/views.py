# investment/views.py
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, getcontext
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from django.contrib import messages
from django.core.paginator import Paginator
from .models import Investment
from .forms import InvestmentForm
from finance.models import Income  # make sure finance app is in INSTALLED_APPS
from .utils import get_expected_return_by_type
from .utils_refresh import refresh_if_stale
from django.http import JsonResponse
from django.core.cache import cache
from django.utils import timezone
from budget.utils import check_budget_warnings
from finance.models import Expense


@login_required
def get_expected_return(request):
    inv_type = request.GET.get("type")
    if not inv_type:
        return JsonResponse({"expected_return": None})
    rate = get_expected_return_by_type(inv_type)
    return JsonResponse({"expected_return": rate})

def _to_decimal(value):
    """Helper to ensure value is Decimal."""
    if value is None:
        return Decimal('0')
    return value if isinstance(value, Decimal) else Decimal(str(value))


@login_required
def investment_list(request):
    filter_type = request.GET.get('filter', 'all')

    # Base queryset
    investments = Investment.objects.filter(user=request.user).order_by('-id')

    # Apply filters
    if filter_type == 'active':
        investments = investments.filter(status__iexact='Active')
    elif filter_type == 'completed':
        investments = investments.filter(status__iexact='Completed')        
    
    # Pagination
    paginator = Paginator(investments, 30)  # Show 30 investments per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'filter_type': filter_type,
    }
    return render(request, 'investment/investment_list.html', context)

@login_required
def add_investment(request):
    if request.method == 'POST':
        form = InvestmentForm(request.POST)
        if form.is_valid():
            inv = form.save(commit=False)
            inv.user = request.user
            today = timezone.now().date()

            # Auto-manage status
            if inv.end_date and inv.end_date <= today:
                inv.status = "Completed"
            else:
                inv.status = "Active"

            inv.save()
            messages.success(request, 'Investment added successfully.')
            # 🔹 Trigger budget check with actual user request (enables popup)
            try:
                expense = Expense.objects.filter(user=request.user, investment=inv).first()
                if expense:
                    check_budget_warnings(request, expense)
            except Exception as e:
                import logging
                logging.warning(f"Budget check skipped: {e}")
            return redirect('investment_list')
        else:
            # Display a clean message if invalid date range
            if 'end_date' in form.errors and "End date must be after start date." in form.errors['end_date']:
                messages.error(request, "⚠️ Please ensure the end date is after the start date.")
            else:
                messages.error(request, "⚠️ Please correct the highlighted errors below.")
                
    else:
        form = InvestmentForm()
    return render(request, 'investment/investment_form.html', {'form': form})


@login_required
def edit_investment(request, id):
    investment = get_object_or_404(Investment, id=id, user=request.user)
    if request.method == 'POST':
        form = InvestmentForm(request.POST, instance=investment)
        if form.is_valid():
            inv = form.save(commit=False)
            today = timezone.now().date()

            # ✅ Auto-update status based on date
            if inv.end_date and inv.end_date <= today:
                inv.status = "Completed"
            else:
                inv.status = "Active"

            inv.save()
            messages.success(request, 'Investment updated successfully.')
            # 🔹 Trigger budget check with actual user request (enables popup)
            try:
                expense = Expense.objects.filter(user=request.user, investment=inv).first()
                if expense:
                    check_budget_warnings(request, expense)
            except Exception as e:
                import logging
                logging.warning(f"Budget check skipped: {e}")
            return redirect('investment_list')
        
        else:
            # Display a clean message if invalid date range
            if 'end_date' in form.errors and "End date must be after start date." in form.errors['end_date']:
                messages.error(request, "⚠️ Please ensure the end date is after the start date.")
            else:
                messages.error(request, "⚠️ Please correct the highlighted errors below.")
    else:
        form = InvestmentForm(instance=investment)
    return render(request, 'investment/investment_form.html', {'form': form})

@login_required
def delete_investment(request, id):
    investment = get_object_or_404(Investment, id=id, user=request.user)
    if request.method == "POST":
        investment.delete()
        messages.success(request, "Investment deleted successfully. Investment amount has been returned to your account.")
    else:
        messages.warning(request, "Please confirm deletion.")
    return redirect("investment_list")

@login_required
def delete_all_investments(request):
    if request.method == "POST":
        investments = Investment.objects.filter(user=request.user)
        count = investments.count()
        investments.delete()
        messages.success(request, f"All ({count}) investments deleted successfully. Investment amount has been returned to your account.")
    else:
        messages.warning(request, "Please confirm deletion of all investments.")
    return redirect("investment_list")

@login_required
@transaction.atomic
def investment_portfolio(request):
    investments = Investment.objects.filter(user=request.user)
    today = date.today()

    total_invested = Decimal('0')
    total_estimated_value = Decimal('0')
    total_profit = Decimal('0')
    total_return_rate = Decimal('0')
    valid_returns = 0
    total_overall_estimated = Decimal('0')
    total_overall_profit = Decimal('0')

    # -------------------------------
    # Compound Interest Calculation
    # -------------------------------
    def calculate_compound_value(principal, annual_rate, start, end, investment_type, frequency=None):
        if not start or not end or annual_rate is None:
            return principal

        days = (end - start).days
        if days <= 0 or annual_rate == 0:
            return principal

        years = Decimal(days) / Decimal('365')

        # --- Default frequency by type ---
        type_based_freq = {
            'fd': 'Quarterly',
            'bond': 'Biannual',
            'rd': 'Monthly',
            'stock': 'Yearly',
            'mutual fund': 'Yearly',
            'etf': 'Yearly',
            'crypto': 'Yearly',
            'pension': 'Yearly',
            'real estate': 'Yearly',
            'gold': 'Yearly',
            'other': 'Yearly',
        }

        # --- Frequency mapping ---
        freq_map = {
            # 'Daily': Decimal('365'),
            # 'Weekly': Decimal('52'),
            'Monthly': Decimal('12'),
            'Quarterly': Decimal('4'),
            'Biannual': Decimal('2'),
            'Yearly': Decimal('1'),
            #'Once': Decimal('1'),
        }

        # --- Determine frequency ---
        investment_type_lower = investment_type.lower()
        auto_freq = type_based_freq.get(investment_type_lower, 'Yearly')
        final_frequency = frequency or auto_freq
        comp_per_year = freq_map.get(final_frequency, Decimal('1'))

        rate_per_period = (annual_rate / Decimal('100')) / comp_per_year
        periods = comp_per_year * years

        # --- Calculation by type ---
        if 'fd' in investment_type_lower:
            # Fixed Deposit: compound, but allow flexible frequency
            value = principal * ((Decimal('1') + rate_per_period) ** periods)

        elif 'rd' in investment_type_lower:
            # Recurring Deposit: monthly contributions compounded monthly
            months = int(years * 12)
            monthly_rate = (annual_rate / Decimal('100')) / Decimal('12')
            value = principal * (((Decimal('1') + monthly_rate) ** months - Decimal('1')) / monthly_rate)

        elif investment_type_lower in ['stock', 'mutual fund', 'etf', 'crypto']:
            # Market-linked: annual compounding approximation
            value = principal * ((Decimal('1') + (annual_rate / Decimal('100'))) ** years)

        elif 'bond' in investment_type_lower:
            # Bond: flexible coupon compounding
            coupon_freq = freq_map.get(final_frequency, Decimal('2'))
            coupon_rate = (annual_rate / Decimal('100')) / coupon_freq
            value = principal * ((Decimal('1') + coupon_rate) ** (years * coupon_freq))

        elif 'pension' in investment_type_lower or 'other' in investment_type_lower:
            # Pension/Other: simple if yearly, compound otherwise
            if final_frequency.lower() == 'yearly':
                value = principal * (Decimal('1') + (annual_rate / Decimal('100')) * years)
            else:
                value = principal * ((Decimal('1') + rate_per_period) ** periods)

        elif 'real estate' in investment_type_lower or 'gold' in investment_type_lower:
            # Real estate & gold usually appreciate linearly
            value = principal * (Decimal('1') + (annual_rate / Decimal('100')) * years)

        else:
            # Fallback: general compounding
            value = principal * ((Decimal('1') + rate_per_period) ** periods)

        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # -------------------------------
    # Main portfolio loop
    # -------------------------------
    REFRESH_INTERVAL_SECONDS = 3600  # 1 hour or 10s for testing
    updated_any = False  # track if any investment was refreshed
    for inv in investments:
        # 🔄 Auto-refresh if stale (10s for testing)
        if not inv.last_updated or (timezone.now() - inv.last_updated).total_seconds() >= REFRESH_INTERVAL_SECONDS:  
            if refresh_if_stale(inv):  
                updated_any = True

        
        amount = _to_decimal(inv.amount)
        expected_return = _to_decimal(inv.expected_return or Decimal('0'))
        
        end_date = inv.end_date or today
        estimated_value = calculate_compound_value(
            amount, expected_return, inv.start_date, end_date, inv.investment_type, inv.frequency
        )

        estimated_value_rounded = estimated_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        profit_estimate = (estimated_value_rounded - amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        inv.estimated_value_display = estimated_value_rounded
        inv.profit_display = profit_estimate

        total_invested += amount
        total_overall_estimated += estimated_value_rounded
        total_overall_profit += profit_estimate
        
        if inv.status == "Completed":
            total_estimated_value += estimated_value_rounded
            total_profit += profit_estimate
            
        if expected_return != 0:
            total_return_rate += expected_return
            valid_returns += 1

        # ✅ Auto-complete investment (signals handle income creation)
        if inv.end_date and inv.end_date <= today and inv.status != "Completed":
            inv.status = "Completed"
            inv.save(update_fields=["status"])
            
    # ✅ Single message after all refreshes
    if updated_any:
        messages.info(request, "📊 Live market values have been refreshed for your investments.")
    # -------------------------------
    # Averages and chart data
    # -------------------------------
    avg_return = (total_return_rate / valid_returns).quantize(Decimal('0.01')) if valid_returns else Decimal('0')

    monthly_data_invested = {}
    monthly_data_estimated = {}
    for inv in investments:
        if inv.start_date:
            label = inv.start_date.strftime('%b %Y')
            monthly_data_invested[label] = monthly_data_invested.get(label, 0) + float(inv.amount)
            monthly_data_estimated[label] = monthly_data_estimated.get(label, 0) + float(inv.estimated_value_display)

    months = list(monthly_data_invested.keys())
    invested_amounts = list(monthly_data_invested.values())
    estimated_amounts = [monthly_data_estimated.get(m, 0) for m in months]

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
        "months": json.dumps(months),
        "invested_amounts": json.dumps(invested_amounts),
        "estimated_amounts": json.dumps(estimated_amounts),
        "category_labels": json.dumps(category_labels),
        "category_values": json.dumps(category_values),
        "total_overall_estimated": total_overall_estimated.quantize(Decimal('0.01')),
        "total_overall_profit": total_overall_profit.quantize(Decimal('0.01')),
    }

    return render(request, "investment/investment_portfolio.html", context)

# Check if never updated or older than 1 minute
        # if not inv.last_updated or (timezone.now() - inv.last_updated).total_seconds() >= 60:
        #     print(f"🔄 Refreshing: {inv.name} ({inv.investment_type})")
        #     refreshed = refresh_if_stale(inv, days=1)
        #     if refreshed:
        #         print(f"✅ Updated {inv.name}: expected_return = {inv.expected_return}")
        #     else:
        #         print(f"⚠️ Skipped or failed to update {inv.name}")
        # else:
        #     print(f"⏸ Still fresh: {inv.name} ({inv.investment_type})")
        
        
# def calculate_compound_value(principal, annual_rate, start, end, frequency):
    #     if not start or not end:
    #         return principal

    #     if frequency == "Once":
    #         one_time_value = principal * (Decimal('1') + (annual_rate / Decimal('100')))
    #         return one_time_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    #     days = (end - start).days
    #     if days <= 0 or annual_rate == 0:
    #         return principal

    #     freq_map = {
    #         'Daily': Decimal('365'),
    #         'Weekly': Decimal('52'),
    #         'Monthly': Decimal('12'),
    #         'Quarterly': Decimal('4'),
    #         'Biannual': Decimal('2'),
    #         'Yearly': Decimal('1'),
    #     }

    #     comp_per_year = freq_map.get(frequency, Decimal('1'))
    #     years = Decimal(days) / Decimal('365')
    #     rate_per_period = (annual_rate / Decimal('100')) / comp_per_year
    #     periods = comp_per_year * years

    #     compound_value = principal * ((Decimal('1') + rate_per_period) ** periods)
    #     return compound_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
# @login_required
# @transaction.atomic
# def investment_portfolio(request):
#     investments = Investment.objects.filter(user=request.user)
#     today = date.today()

#     total_invested = Decimal('0')
#     total_estimated_value = Decimal('0')
#     total_profit = Decimal('0')
#     total_return_rate = Decimal('0')
#     valid_returns = 0
#     total_overall_estimated = Decimal('0')  # Includes all
#     total_overall_profit = Decimal('0')

#     def choose_income_category(inv_type):
#         t = (inv_type or "").lower()
#         if t in ['fd', 'fixed deposit', 'rd', 'recurring deposit', 'bond']:
#             return "Interest Income"
#         if t in ['stock', 'mutual fund', 'etf', 'crypto', 'share']:
#             return "Dividends"
#         if t in ['real estate', 'pension']:
#             return "Rental Income"
#         if t in ['gold']:
#             return "Other Income"
#         return "Other Income"

#     '''# Compound Interest Calculation Logic
#     def calculate_compound_value(principal, annual_rate, start, end, frequency):
#         if not start or not end:
#             return principal

#         if frequency == "Once":
#             # 🟢 Apply expected return only once
#             one_time_value = principal * (Decimal('1') + (annual_rate / Decimal('100')))
#             return one_time_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
#         days = (end - start).days
#         if days <= 0 or annual_rate == 0:
#             return principal

#         freq_map = {
#             'Daily': Decimal('365'),
#             'Weekly': Decimal('52'),
#             'Monthly': Decimal('12'),
#             'Quarterly': Decimal('4'),
#             'Biannual': Decimal('2'),
#             'Yearly': Decimal('1'),
#         }

#         comp_per_year = freq_map.get(frequency, Decimal('1'))
#         rate_per_period = annual_rate / (comp_per_year * 100)
#         years = Decimal(days) / Decimal('365')
#         periods = comp_per_year * years

#         compound_value = principal * ((Decimal('1') + rate_per_period) ** periods)
#         return compound_value'''
    

#     def calculate_compound_value(principal, annual_rate, start, end, frequency):
#         if not start or not end:
#             return principal

#         if frequency == "Once":
#             # 🟢 Apply expected return only once
#             one_time_value = principal * (Decimal('1') + (annual_rate / Decimal('100')))
#             return one_time_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

#         days = (end - start).days
#         if days <= 0 or annual_rate == 0:
#             return principal

#         # Mapping frequency to number of compounding periods per year
#         freq_map = {
#             'Daily': Decimal('365'),
#             'Weekly': Decimal('52'),
#             'Monthly': Decimal('12'),
#             'Quarterly': Decimal('4'),
#             'Biannual': Decimal('2'),
#             'Yearly': Decimal('1'),
#         }

#         comp_per_year = freq_map.get(frequency, Decimal('1'))
#         years = Decimal(days) / Decimal('365')

#         # ✅ Corrected interest rate per compounding period
#         rate_per_period = (annual_rate / Decimal('100')) / comp_per_year

#         # ✅ Total number of compounding periods
#         periods = comp_per_year * years

#         # ✅ Compound interest formula
#         compound_value = principal * ((Decimal('1') + rate_per_period) ** periods)

#         # Round off to 2 decimal places
#         return compound_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

#     for inv in investments:
#         refresh_if_stale(inv, days=1)
#         amount = _to_decimal(inv.amount)
#         expected_return = _to_decimal(inv.expected_return or Decimal('0'))

#         # --- Use clean compound logic
#         estimated_value = calculate_compound_value(
#             amount, expected_return, inv.start_date, inv.end_date, inv.frequency
#         )

#         estimated_value_rounded = estimated_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
#         profit_estimate = (estimated_value_rounded - amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

#         # Always show in table
#         inv.estimated_value_display = estimated_value_rounded
#         inv.profit_display = profit_estimate

#         # Totals
#         total_invested += amount

#         # ✅ Add to overall totals (active + completed)
#         total_overall_estimated += estimated_value_rounded
#         total_overall_profit += profit_estimate

#         # ✅ Add to finished totals only if investment completed
#         if inv.status == "Completed":
#             total_estimated_value += estimated_value_rounded
#             total_profit += profit_estimate

#         #total_estimated_value += estimated_value_rounded

#         # ✅ Add profit only if investment is finished
#         # if inv.end_date and inv.end_date <= today and inv.status == "Completed":
#         #     total_profit += profit_estimate

#         if expected_return != 0:
#             total_return_rate += expected_return
#             valid_returns += 1

#         # --- Auto-create income on maturity ---
#         if inv.end_date and inv.end_date <= today and inv.status != "Completed":
#             existing_income = Income.objects.filter(
#                 user=request.user,
#                 source=f"Investment Maturity - {inv.name}",
#                 date=inv.end_date
#             ).exists()

#             if not existing_income:
#                 category = choose_income_category(inv.investment_type)
#                 income_amount = estimated_value_rounded  # total value (principal + profit/loss)
#                 Income.objects.create(
#                     user=request.user,
#                     source=f"Investment Maturity - {inv.name}",
#                     amount=income_amount,
#                     date=inv.end_date,
#                     category=category
#                 )

#             inv.status = "Completed"
#             inv.save(update_fields=["status"])


#     avg_return = (total_return_rate / valid_returns).quantize(Decimal('0.01')) if valid_returns else Decimal('0')

#     # -------------------------
#     # Chart Data (Frequency-consistent)
#     # -------------------------
#     monthly_data_invested = {}
#     monthly_data_estimated = {}
#     for inv in investments:
#         if inv.start_date:
#             label = inv.start_date.strftime('%b %Y')
#             monthly_data_invested[label] = monthly_data_invested.get(label, 0) + float(inv.amount)
#             monthly_data_estimated[label] = monthly_data_estimated.get(label, 0) + float(inv.estimated_value_display)

#     months = list(monthly_data_invested.keys())
#     invested_amounts = list(monthly_data_invested.values())
#     estimated_amounts = [monthly_data_estimated.get(m, 0) for m in months]

#     # Category Comparison
#     category_investments = (
#         investments.values('investment_type')
#         .annotate(total=Sum('amount'))
#         .order_by('-total')
#     )
#     category_labels = [c['investment_type'] for c in category_investments]
#     category_values = [float(c['total']) for c in category_investments]

#     context = {
#         "investments": investments,
#         "total_invested": total_invested.quantize(Decimal('0.01')),
#         "total_estimated_value": total_estimated_value.quantize(Decimal('0.01')),
#         "total_profit": total_profit.quantize(Decimal('0.01')),
#         "avg_return": avg_return,
#         "year": today.year,
#         "months": json.dumps(months),
#         "invested_amounts": json.dumps(invested_amounts),
#         "estimated_amounts": json.dumps(estimated_amounts),
#         "category_labels": json.dumps(category_labels),
#         "category_values": json.dumps(category_values),
#         "total_overall_estimated": total_overall_estimated.quantize(Decimal('0.01')),
#         "total_overall_profit": total_overall_profit.quantize(Decimal('0.01')),
#     }
#     return render(request, "investment/investment_portfolio.html", context)




''' @login_required
@transaction.atomic
def investment_portfolio(request):
    """
    Display investments and compute totals using COMPOUND INTEREST.
    Frequency affects compounding period (Daily, Weekly, Monthly, Quarterly, Yearly).
    Ensures consistent values across table, totals, charts, and income records.
    """

    getcontext().prec = 28  # ensure high precision

    investments = Investment.objects.filter(user=request.user)
    today = date.today()

    total_invested = Decimal('0')
    total_estimated_value = Decimal('0')
    total_profit = Decimal('0')
    total_return_rate = Decimal('0')
    valid_returns = 0

    # -------------------------------------
    # Helper: choose income category
    # -------------------------------------
    def choose_income_category(inv_type):
        t = (inv_type or "").lower()
        if t in ['fd', 'fixed deposit', 'rd', 'recurring deposit', 'bond']:
            return "Interest Income"
        if t in ['stock', 'mutual fund', 'etf', 'crypto', 'share']:
            return "Dividends"
        if t in ['real estate', 'pension']:
            return "Rental Income"
        if t in ['gold']:
            return "Other Income"
        return "Other Income"

    # -------------------------------------
    # Compound interest logic
    # -------------------------------------
    def calculate_estimated_value_compound(inv):
        """
        Compound interest formula:
        A = P * (1 + r/n)^(n*t)
        where:
          r = annual rate (decimal)
          n = compounding frequency per year
          t = time in years (exact days / 365)
        """
        amount = _to_decimal(inv.amount)
        annual_rate = _to_decimal(inv.expected_return or Decimal('0'))
        start_date, end_date = inv.start_date, inv.end_date

        if not start_date or not end_date or end_date <= start_date:
            return amount.quantize(Decimal('0.01')), Decimal('0.00')

        days = (end_date - start_date).days
        t = Decimal(days) / Decimal('365')

        # determine n based on frequency
        freq = (inv.frequency or "").lower()
        if freq == 'daily':
            n = Decimal('365')
        elif freq == 'weekly':
            n = Decimal('52')
        elif freq == 'monthly':
            n = Decimal('12')
        elif freq == 'quarterly':
            n = Decimal('4')
        elif freq == 'yearly':
            n = Decimal('1')
        else:
            n = Decimal('1')  # default yearly

        r = annual_rate / Decimal('100')

        # Compound interest formula
        estimated_value = amount * (Decimal('1') + (r / n)) ** (n * t)
        estimated_value = estimated_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        profit = (estimated_value - amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return estimated_value, profit

    # -------------------------------------
    # Main calculation loop
    # -------------------------------------
    for inv in investments:
        refresh_if_stale(inv, days=1)

        est_value, profit = calculate_estimated_value_compound(inv)
        inv._estimated_value = est_value
        inv._profit_estimate = profit

        total_invested += _to_decimal(inv.amount)
        total_estimated_value += est_value
        total_profit += profit

        if inv.expected_return:
            total_return_rate += _to_decimal(inv.expected_return)
            valid_returns += 1

        # Auto-create Income once when matured
        if inv.end_date and inv.end_date <= today and inv.status != "Completed":
            exists = Income.objects.filter(
                user=request.user,
                source=f"Investment Maturity - {inv.name}",
                date=inv.end_date
            ).exists()

            if not exists:
                category = choose_income_category(inv.investment_type)
                Income.objects.create(
                    user=request.user,
                    source=f"Investment Maturity - {inv.name}",
                    amount=est_value,
                    date=inv.end_date,
                    category=category
                )

            inv.status = "Completed"
            inv.save(update_fields=["status"])

    avg_return = (total_return_rate / valid_returns).quantize(Decimal('0.01')) if valid_returns else Decimal('0.00')

    # -------------------------------------
    # Chart data
    # -------------------------------------
    monthly_data_invested = {}
    monthly_data_estimated = {}

    for inv in investments:
        if inv.start_date:
            label = inv.start_date.strftime('%b %Y')
            monthly_data_invested[label] = monthly_data_invested.get(label, 0) + float(_to_decimal(inv.amount))
            est_val = getattr(inv, "_estimated_value", None)
            if est_val is None:
                est_val, _ = calculate_estimated_value_compound(inv)
            monthly_data_estimated[label] = monthly_data_estimated.get(label, 0) + float(est_val)

    months = list(monthly_data_invested.keys())
    invested_amounts = list(monthly_data_invested.values())
    estimated_amounts = [monthly_data_estimated.get(m, 0) for m in months]

    # category comparison
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
        "months": json.dumps(months),
        "invested_amounts": json.dumps(invested_amounts),
        "estimated_amounts": json.dumps(estimated_amounts),
        "category_labels": json.dumps(category_labels),
        "category_values": json.dumps(category_values),
    }
    return render(request, "investment/investment_portfolio.html", context) '''







'''@login_required
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
        if t in ['stock', 'mutual fund', 'etf', 'crypto', 'share']:
            return "Dividends"
        if t in ['real estate', 'pension']:
            return "Rental Income"
        if t in ['gold']:
            return "Other Income"
        return "Other Income"

    for inv in investments:
        refresh_if_stale(inv, days=1)
        amount = _to_decimal(inv.amount)
        expected_return = _to_decimal(inv.expected_return or Decimal('0'))

        years = Decimal('1')
        if inv.start_date and inv.end_date:
            days = (inv.end_date - inv.start_date).days
            years_float = max(1, days / 365)
            years = Decimal(str(years_float))

        # --- Compute estimated value (based on frequency)
        estimated_value = amount
        if expected_return != 0:
            if inv.frequency == 'Daily':
                periods = Decimal((inv.end_date - inv.start_date).days)
                rate_per_period = expected_return / Decimal('36500')  # annual rate / 365
            elif inv.frequency == 'Weekly':
                periods = Decimal((inv.end_date - inv.start_date).days / 7)
                rate_per_period = expected_return / Decimal('5200')  # annual rate / 52
            elif inv.frequency == 'Monthly':
                periods = Decimal((inv.end_date - inv.start_date).days / 30)
                rate_per_period = expected_return / Decimal('1200')  # annual rate / 12
            elif inv.frequency == 'Quarterly':
                periods = Decimal((inv.end_date - inv.start_date).days / 91)
                rate_per_period = expected_return / Decimal('400')  # annual rate / 4
            elif inv.frequency == 'Biannual':
                periods = Decimal((inv.end_date - inv.start_date).days / 182)
                rate_per_period = expected_return / Decimal('200')  # annual rate / 2
            else:  # Yearly
                periods = Decimal(max(1, (inv.end_date - inv.start_date).days / 365))
                rate_per_period = expected_return / Decimal('100')

            # Compound interest style calculation
            estimated_value = amount * ((Decimal('1') + rate_per_period) ** periods)


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
        "months": json.dumps(months),
        "invested_amounts": json.dumps(invested_amounts),
        "estimated_amounts": json.dumps(estimated_amounts),
        "category_labels": json.dumps(category_labels),
        "category_values": json.dumps(category_values),
    }
    return render(request, "investment/investment_portfolio.html", context)'''

