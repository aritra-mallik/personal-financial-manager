from decimal import ROUND_HALF_UP, Decimal
from urllib import request
from django.shortcuts import render, redirect

from budget.models import Budget, BudgetCategory
from .models import Expense, Income, RecurringIncome, RecurringExpense
from django.utils import timezone
from django.db.models import Sum, F, Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.db.models.functions import TruncMonth, ExtractWeek, ExtractMonth
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .utils import (
get_next_due_date, normalize_headers, normalize_date, clean_value, normalize_expense_category, normalize_income_category, is_bank_statement_csv
)
from .forms import IncomeForm, ExpenseForm, RecurringIncomeForm, RecurringExpenseForm
import csv,re,logging
from budget.utils import check_budget_warnings
from django.http import JsonResponse
from ml.classifier import predict_category as ml_predict_expense_category
from ml.income_classifier import predict_category as ml_predict_income_category
from ml.forecasting import get_user_expense_forecast

@login_required
def predict_income_category(request):
    """
    AJAX endpoint for real-time income category prediction.
    """
    text = request.GET.get("text", "")
    if not text:
        return JsonResponse({"category": "Other Income"})

    try:
        prediction = ml_predict_income_category([text])[0]
        return JsonResponse({"category": prediction})
    except Exception as e:
        return JsonResponse({"category": "Other Income", "error": str(e)})
   
@login_required
def predict_expense_category(request):
    """
    AJAX endpoint for real-time category prediction.
    """
    text = request.GET.get("text", "")
    if not text:
        return JsonResponse({"category": "Miscellaneous"})

    try:
        prediction = ml_predict_expense_category([text])[0]
        return JsonResponse({"category": prediction})
    except Exception as e:
        return JsonResponse({"category": "Miscellaneous", "error": str(e)})


# Create your views here.
@login_required
def add_expense(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user

            """ # Calculate totals
            total_income = Income.objects.filter(user=request.user).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            total_expense = Expense.objects.filter(user=request.user).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Check if this expense surpasses income
            if (Decimal(total_expense) + Decimal(expense.amount)) > Decimal(total_income):
                messages.error(request, "Expense cannot surpass total income!")
            else:
                expense.save()
                messages.success(request, "Expense added successfully!")
                check_budget_warnings(request, expense)  # Check budgets after adding expense
                return redirect('add_expense') """
            expense.save()
            messages.success(request, "Expense added successfully!")
            check_budget_warnings(request, expense)  # Check budgets after adding expense
            return redirect('add_expense')
    else:
        form = ExpenseForm()

    categories = [choice[0] for choice in Expense.CATEGORY_CHOICES]
    chart_data=[]
    for cat in categories:
        total = Expense.objects.filter(category=cat, user=request.user).aggregate(Sum('amount'))['amount__sum'] or 0
        chart_data.append(float(total))

    context={
        'form': form,
        'categories': categories,
        'chart_data': chart_data,
        'timezone': timezone.now()
    }
    return render(request, 'finance/add_expense.html', context)

@login_required
def add_income(request):
    if request.method == 'POST':
        form = IncomeForm(request.POST)
        if form.is_valid():
            income = form.save(commit=False)
            income.user = request.user
            income.save()

            messages.success(request, "Income added successfully!")
            return redirect('add_income')
    else:
        form = IncomeForm()

    categories = [choice[0] for choice in Income.CATEGORY_CHOICES]
    chart_data = []
    for cat in categories:
        total = Income.objects.filter(category=cat, user=request.user).aggregate(Sum('amount'))['amount__sum'] or 0
        chart_data.append(float(total))

    context = {
        'form': form,
        'categories': categories,
        'chart_data': chart_data,
        'timezone': timezone.now()
    }
    return render(request, 'finance/add_income.html', context)

@login_required
def edit_income(request, id):
    income = get_object_or_404(Income, id=id, user=request.user)

    if request.method == "POST":
        form = IncomeForm(request.POST, instance=income)
        if form.is_valid():
            form.save()
            messages.success(request, "Income updated successfully!")
        else:
            messages.error(request, "Please correct the errors below.")
    return redirect("income_history")
  
@login_required
def delete_income(request, id):
    income = get_object_or_404(Income, id=id, user=request.user)
    if request.method == "POST":
        income.delete()
        messages.success(request, "Income deleted successfully!")
    return redirect("income_history")

@login_required
def edit_expense(request, id):
    expense = get_object_or_404(Expense, id=id, user=request.user)
    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense updated successfully!")
            check_budget_warnings(request, expense)  # Check budgets after editing expense
        else:
            messages.error(request, "Please correct the errors below.")
    return redirect("expense_log")

@login_required
def delete_expense(request, id):
    expense = get_object_or_404(Expense, id=id, user=request.user)
    if request.method == "POST":
        expense.delete()
        messages.success(request, "Expense deleted successfully!")
    return redirect("expense_log")

@login_required
def upload_income_csv(request):
    if request.method != "POST":
        return redirect("add_income")

    csv_file = request.FILES.get("csv_file")

    # File size limit (1MB)
    if csv_file.size > 1048576:
        messages.error(request, "File too large! Please upload a CSV under 1 MB.")
        return redirect("add_income")

    if not csv_file.name.endswith(".csv"):
        messages.error(request, "Only CSV files are allowed!")
        return redirect("add_income")

    try:
        file_data = csv_file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(file_data)
        
        # ===== Dashboard Hint Feature =====
        # 🏦 Detect real bank statement
        if is_bank_statement_csv(reader.fieldnames):
            messages.info(request, "🏦 This appears to be a real bank statement. Please upload it using the Bank Statement Upload section on your dashboard.")
            return redirect("dashboard")
        # ==================================

        # Normalize headers
        field_map = normalize_headers(reader.fieldnames)

        required_fields = ["date", "source", "amount"]
        missing_fields = [f for f in required_fields if f not in field_map]
        if missing_fields:
            messages.error(request, f"CSV missing required fields: {', '.join(missing_fields)}")
            return redirect("add_income")

        imported_count = 0
        skipped_count = 0
        affected_categories = set()  # track categories if needed later

        for row in reader:
            # 1️⃣ Date
            date_str = normalize_date(row.get(field_map.get("date")))

            # 2️⃣ Source (e.g., Salary, Interest)
            source = clean_value(row.get(field_map.get("source")), default="Unknown Income")

            # 3️⃣ Amount (clean ₹, commas, spaces)
            amount_raw = row.get(field_map.get("amount"))
            amount = Decimal("0")
            if amount_raw:
                amount_clean = re.sub(r"[^\d\.\-]", "", str(amount_raw))
                try:
                    amount = Decimal(amount_clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                except:
                    amount = Decimal("0")

            # 4️⃣ Category (optional)
            raw_category = clean_value(row.get(field_map.get("category")), default="")
            category = normalize_income_category(raw_category) if raw_category else ml_predict_income_category([source])[0]

            # Skip invalid rows
            if not date_str or not source or amount == 0:
                skipped_count += 1
                continue

            # Save to DB
            Income.objects.create(
                date=date_str,
                source=source,
                amount=amount,
                category=category,
                user=request.user
            )
            imported_count += 1
            affected_categories.add(category)
            
        #all rows skipped
        if imported_count == 0:
            # Forcefully clear all queued messages
            list(messages.get_messages(request))  # consumes all messages
            messages.warning(request, "⚠️ No incomes were imported. All rows were skipped due to validation.") 
            return redirect("income_history")   

        #✅ Summary message
        summary_msg = (
            f"✅ CSV Upload Complete! Imported: {imported_count}, "
            f"Skipped: {skipped_count}, "
            f"Categories: {len(affected_categories)}"
        )
        messages.success(request, summary_msg)

    except Exception as e:
        messages.error(request, f"Error processing CSV: {str(e)}")
        return redirect("add_income")

    return redirect("income_history")

@login_required
def upload_expense_csv(request):
    if request.method != "POST":
        return redirect("add_expense")

    csv_file = request.FILES.get("csv_file")

    # File size limit: 1MB
    if csv_file.size > 1048576:
        messages.error(request, "File too large! Please upload a CSV under 1 MB.")
        return redirect("add_expense")

    if not csv_file.name.endswith(".csv"):
        messages.error(request, "Only CSV files are allowed!")
        return redirect("add_expense")

    try:
        file_data = csv_file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(file_data)
        
        # ===== Dashboard Hint Feature =====
        # 🏦 Detect real bank statement
        if is_bank_statement_csv(reader.fieldnames):
            messages.info(request, "🏦 This appears to be a real bank statement. Please upload it using the Bank Statement Upload section on your dashboard.")
            return redirect("dashboard")
        # ==================================

        field_map = normalize_headers(reader.fieldnames)

        required_fields = ["date", "name", "amount"]
        missing_fields = [f for f in required_fields if f not in field_map]
        if missing_fields:
            messages.error(request, f"CSV missing required fields: {', '.join(missing_fields)}")
            return redirect("add_expense")

        # Track processing summary
        imported_count = 0
        skipped_count = 0
        warning_count = 0
        affected_categories = set()

        # Pre-calculate income and expense totals
        total_income = Income.objects.filter(user=request.user).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        total_expense = Expense.objects.filter(user=request.user).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        for row in reader:
            date_str = normalize_date(row.get(field_map.get("date")))
            name = clean_value(row.get(field_map.get("name")), default="Unknown Expense")

            # Parse amount safely
            amount_raw = row.get(field_map.get("amount"))
            amount = Decimal("0")
            if amount_raw:
                amount_clean = re.sub(r"[^\d\.\-]", "", str(amount_raw))
                try:
                    amount = Decimal(amount_clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                except:
                    amount = Decimal("0")

            raw_category = clean_value(row.get(field_map.get("category")), default="")
            category = normalize_expense_category(raw_category) if raw_category else ml_predict_expense_category([name])[0]

            # Skip invalid rows
            if not date_str or not name or amount == 0:
                skipped_count += 1
                continue

            # Prevent overspending
            if (total_expense + amount) > total_income:
                skipped_count += 1
                messages.warning(request, f"Skipping '{name}' - exceeds total income!")
                continue

            # Create Expense
            Expense.objects.create(
                date=date_str,
                name=name,
                amount=amount,
                category=category,
                user=request.user
            )

            total_expense += amount
            imported_count += 1
            affected_categories.add(category)
            
        #all rows skipped
        if imported_count == 0:
            # Forcefully clear all queued messages
            list(messages.get_messages(request))  # consumes all messages
            messages.warning(request, "⚠️ No expenses were imported. All rows were skipped due to validation.")
            return redirect("expense_log")

        # ✅ Check budgets for all affected categories
        for category in affected_categories:
            dummy_expense = Expense(user=request.user, category=category)
            prev_msg_count = len(messages.get_messages(request))  # Track before
            check_budget_warnings(request, dummy_expense)
            new_msg_count = len(messages.get_messages(request))  # Track after
            if new_msg_count > prev_msg_count:
                warning_count += 1

        # ✅ Summary message
        summary_msg = (
            f"✅ CSV Upload Complete! Imported: {imported_count}, "
            f"Skipped: {skipped_count}, "
            f"Categories Checked: {len(affected_categories)}, "
            f"Budget Warnings: {warning_count}"
        )
        messages.success(request, summary_msg)

    except Exception as e:
        messages.error(request, f"Error processing CSV: {str(e)}")
        return redirect("add_expense")

    return redirect("expense_log")

logger = logging.getLogger(__name__)


@login_required
def upload_bank_statement(request):
    """
    🌍 Universal AI-Powered Bank Statement Upload

    ✅ Accepts any bank CSV format (Indian or international)
    ✅ Detects income vs expense automatically
    ✅ Normalizes any date format (via normalize_date)
    ✅ Predicts income & expense categories using AI
    ✅ Checks if expenses exceed income
    ✅ Skips malformed rows gracefully
    """
    if request.method != "POST":
        return redirect("dashboard")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, "Please upload a CSV file.")
        return redirect("dashboard")

    if csv_file.size > 1572864:  # 1.5 MB
        messages.error(request, "CSV file too large (max 1.5 MB).")
        return redirect("dashboard")

    if not csv_file.name.lower().endswith(".csv"):
        messages.error(request, "Only CSV files are allowed.")
        return redirect("dashboard")

    try:
        # 🧾 Read CSV
        file_data = csv_file.read().decode("utf-8", errors="ignore").splitlines()
        reader = csv.DictReader(file_data)

        if not reader.fieldnames:
            messages.error(request, "CSV has no headers.")
            return redirect("dashboard")

        # 🧠 Normalize headers
        field_map = normalize_headers(reader.fieldnames)
        lower_fields = [f.lower() for f in reader.fieldnames]

        # 🔍 Detect columns dynamically
        date_field = field_map.get("date") or next((f for f in reader.fieldnames if "date" in f.lower()), None)
        debit_field = next((f for f in reader.fieldnames if "debit" in f.lower() or "(dr" in f.lower()), None)
        credit_field = next((f for f in reader.fieldnames if "credit" in f.lower() or "(cr" in f.lower()), None)
        withdrawal_field = next((f for f in reader.fieldnames if "withdrawal" in f.lower()), None)
        deposit_field = next((f for f in reader.fieldnames if "deposit" in f.lower()), None)
        amount_field = next((f for f in reader.fieldnames if "amount" in f.lower()), None)
        type_field = next((f for f in reader.fieldnames if "type" in f.lower()), None)
        desc_field = next(
            (f for f in reader.fieldnames if any(k in f.lower() for k in ["description", "details", "narration", "memo", "remarks"])),
            None
        )

        if not date_field:
            messages.error(request, "Date column not found — invalid bank statement.")
            return redirect("dashboard")

        if not any([debit_field, credit_field, withdrawal_field, deposit_field, amount_field]):
            messages.error(request, "No recognizable amount columns found.")
            return redirect("dashboard")

        # 💰 Fetch current totals
        total_income = Income.objects.filter(user=request.user).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        total_expense = Expense.objects.filter(user=request.user).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        imported_income = imported_expense = skipped = 0

        def clean_amt(val):
            val = re.sub(r"[^\d.\-]", "", str(val))
            return Decimal(val) if val else Decimal("0")

        # 📝 Buffer rows
        income_rows = []
        expense_rows = []

        for row in reader:
            try:
                date_str = normalize_date(row.get(date_field))
                if not date_str:
                    skipped += 1
                    continue

                description = str(row.get(desc_field) or "").strip()
                if not description:
                    description = next((str(v).strip() for v in row.values() if v), "")

                amount = Decimal("0")
                txn_type = "unknown"

                # Debit / Credit
                if debit_field and row.get(debit_field):
                    amount = clean_amt(row[debit_field])
                    if amount < 0:
                        amount = abs(amount)
                        txn_type = "income"
                    else:
                        txn_type = "expense"
                elif credit_field and row.get(credit_field):
                    amount = clean_amt(row[credit_field])
                    if amount < 0:
                        amount = abs(amount)
                        txn_type = "expense"
                    else:
                        txn_type = "income"
                elif withdrawal_field and row.get(withdrawal_field):
                    amount = clean_amt(row[withdrawal_field])
                    txn_type = "expense"
                elif deposit_field and row.get(deposit_field):
                    amount = clean_amt(row[deposit_field])
                    txn_type = "income"
                elif type_field and amount_field:
                    raw_type = str(row.get(type_field, "")).strip().upper()
                    amount = clean_amt(row.get(amount_field))
                    if raw_type in ("CREDIT", "CR", "INCOME"):
                        txn_type = "income"
                    elif raw_type in ("DEBIT", "DR", "EXPENSE"):
                        txn_type = "expense"

                # Fallback — detect from description
                desc_lower = description.lower()
                if txn_type == "unknown" and amount > 0:
                    if any(w in desc_lower for w in ["salary", "interest", "refund", "bonus", "deposit", "credit"]):
                        txn_type = "income"
                    elif any(w in desc_lower for w in ["upi", "payment", "transfer", "withdrawal", "atm", "rent", "emi", "bill", "debit"]):
                        txn_type = "expense"

                if amount == 0 or txn_type == "unknown":
                    #skipped += 1
                    continue

                # Buffer row
                if txn_type == "income":
                    income_rows.append((date_str, description, amount))
                else:
                    expense_rows.append((date_str, description, amount))

            except Exception as e:
                logger.warning(f"⚠️ Skipped row: {e}")
                #skipped += 1
                continue

        # 🔄 Import all income first
        for date_str, description, amount in income_rows:
            try:
                category = ml_predict_income_category([description])[0]
                Income.objects.create(
                    user=request.user,
                    date=date_str,
                    source=description[:100],
                    amount=amount,
                    category=category,
                )
                total_income += amount
                imported_income += 1
            except Exception as e:
                logger.warning(f"⚠️ Skipped income row: {e}")
                skipped += 1
                continue
            
        shown_warnings = set()

        # 🔄 Then import expense rows
        for date_str, description, amount in expense_rows:
            try:
                if amount <= 0:
                    logger.warning(f"⚠️ Skipped non-positive expense: {description} ({amount})")
                    skipped += 1
                    continue

                # Only skip if total still insufficient
                if (total_expense + amount) > total_income:
                    logger.warning(f"⚠️ Skipped expense that would exceed income: {description} ({amount}) please enter the income first.")
                    skipped += 1
                    continue

                category = ml_predict_expense_category([description])[0]
                exp_obj = Expense.objects.create(
                    user=request.user,
                    date=date_str,
                    name=description[:100],
                    amount=amount,
                    category=category,
                )
                warnings_before = len(messages.get_messages(request))
                check_budget_warnings(request, exp_obj)
                warnings_after = list(messages.get_messages(request))

                # Prevent duplicate messages by tracking text
                for msg in warnings_after:
                    if msg.message not in shown_warnings:
                        shown_warnings.add(msg.message)
                        messages.add_message(request, msg.level, msg.message)
                total_expense += amount
                imported_expense += 1

            except Exception as e:
                logger.warning(f"⚠️ Skipped expense row: {e}")
                skipped += 1
                continue
            
        # ✅ If everything was skipped
        if imported_income == 0 and imported_expense == 0:
            # Forcefully clear all queued messages
            list(messages.get_messages(request))  # consumes all messages
            messages.warning(request, "⚠️ No transactions were imported. All rows were skipped due to validation or parsing rules.")

        # ✅ After processing all rows
        if total_expense > total_income:
            messages.warning(
                request,
                f"⚠️ Warning: Total expenses ({total_expense}) exceed total income ({total_income})."
            )

        messages.success(
            request,
            f"✅ Upload complete! Income: {imported_income}, Expense: {imported_expense}, Skipped: {skipped}"
        )
        return redirect("dashboard")

    except Exception as e:
        logger.error(f"❌ Error processing bank statement: {e}")
        messages.error(request, f"Error processing statement: {e}")
        return redirect("dashboard")

@login_required
def expense_log(request):
    process_recurring_transactions(request.user)
    expenses = Expense.objects.filter(user=request.user).order_by('-date')
    categories = [choice[0] for choice in Expense.CATEGORY_CHOICES]

    labels = [expense.date.strftime('%Y-%m-%d') for expense in expenses]
    data = [float(expense.amount) for expense in expenses]

    paginator = Paginator(expenses, 20)  # Show 20 expenses per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Sliding window of 5 pages
    total_pages = paginator.num_pages
    current_page = page_obj.number
    window_size = 5
    start_page = max(current_page - 2, 1)
    end_page = min(start_page + window_size - 1, total_pages)
    if end_page - start_page < window_size - 1:
        start_page = max(end_page - window_size + 1, 1)
    page_range = range(start_page, end_page + 1)
    
    #prediction
    forecast = get_user_expense_forecast(request.user)

    context={
        'expenses': page_obj,
        'labels': labels,
        'data': data,
        'categories': categories,
        'page_obj': page_obj,
        'page_range': page_range,
        #pass raw values for easy checks in template
        'spent_so_far': forecast['spent_so_far'],
        'current_month_expected': forecast['this_month_expected'],
        'next_month_expected': forecast['next_month_expected'],
        # Flags for template
        'spent_so_far_numeric': isinstance(forecast['spent_so_far'], (int, float, Decimal)),
        'current_month_expected_numeric': isinstance(forecast['this_month_expected'], (int, float, Decimal)),
        'next_month_expected_numeric': isinstance(forecast['next_month_expected'], (int, float, Decimal))
    }
    return render(request, 'finance/expense_log.html', context)

@login_required
@require_POST
def delete_selected_expenses(request):
    ids = request.POST.get("selected_ids", "")
    if ids:
        id_list = [int(i) for i in ids.split(",") if i.isdigit()]
        Expense.objects.filter(id__in=id_list, user=request.user).delete()
    messages.success(request, "Selected expenses deleted successfully!")
    return redirect("expense_log")  # 👈 make sure this is the correct name of your expense list page

@login_required
def bulk_delete_expense(request):
    if request.method == "POST":
        Expense.objects.filter(user=request.user).delete()
    messages.success(request, "All expenses deleted successfully!")
    return redirect("expense_log")

@login_required
def income_history(request):
    process_recurring_transactions(request.user)
    incomes = Income.objects.filter(user=request.user).order_by('-date')
    categories = [choice[0] for choice in Income.CATEGORY_CHOICES]

    labels=[income.date.strftime('%Y-%m-%d') for income in incomes]
    data=[float(income.amount) for income in incomes]

    paginator = Paginator(incomes, 20)  # Show 20 incomes per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    #sliding window of 5 pages
    total_pages = paginator.num_pages
    current_page = page_obj.number
    window_size = 5
    start_page = max(current_page - 2, 1)
    end_page = min(start_page + window_size - 1, total_pages)
    if end_page - start_page < window_size - 1:
        start_page = max(end_page - window_size + 1, 1)
    page_range = range(start_page, end_page + 1)
    
    context={
        'incomes': page_obj,
        'labels': labels,
        'data': data,
        'categories': categories,
        'page_obj': page_obj,
        'page_range': page_range,
    }
    return render(request, 'finance/income_history.html', context)

@login_required
@require_POST
def delete_selected_incomes(request):
    ids = request.POST.get("selected_ids", "")
    if ids:
        id_list = [int(i) for i in ids.split(",") if i.isdigit()]
        Income.objects.filter(id__in=id_list, user=request.user).delete()
    messages.success(request, "Selected incomes deleted successfully!")
    return redirect("income_history")

@login_required
def bulk_delete_income(request):
    if request.method == "POST":
        Income.objects.filter(user=request.user).delete()
    messages.success(request, "All incomes deleted successfully!")
    return redirect("income_history")

def process_recurring_transactions(user):
    today = timezone.now().date()

    # Current totals
    total_income = Income.objects.filter(user=user).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    total_expense = Expense.objects.filter(user=user).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    changed = True
    while changed:
        changed = False

        # ---- Process Recurring Incomes ----
        incomes = RecurringIncome.objects.filter(user=user, next_due_date__lte=today, status="active")
        for rec in incomes:
            # Stop if beyond end date
            if rec.end_date and rec.next_due_date > rec.end_date:
                rec.status = "inactive"
                rec.save()
                continue

            # ✅ Prevent duplicates
            if not Income.objects.filter(
                user=user,
                source=rec.source,
                amount=rec.amount,
                date=rec.next_due_date,
                category=rec.category,
                recurring=rec
            ).exists():
                Income.objects.create(
                    source=rec.source,
                    amount=rec.amount,
                    date=rec.next_due_date,
                    category=rec.category,
                    user=user,
                    recurring=rec   # Link transaction to recurring record
                )
                total_income += Decimal(rec.amount)

            rec.next_due_date = get_next_due_date(rec.next_due_date, rec.frequency)

            if rec.end_date and rec.next_due_date > rec.end_date:
                rec.status = "inactive"

            rec.save()
            changed = True

        # ---- Process Recurring Expenses ----
        expenses = RecurringExpense.objects.filter(user=user, next_due_date__lte=today).exclude(status="inactive")
        for rec in expenses:
            if rec.end_date and rec.next_due_date > rec.end_date:
                rec.status = "inactive"
                rec.save()
                continue

            if (total_expense + Decimal(rec.amount)) <= total_income:
                # ✅ Prevent duplicates
                if not Expense.objects.filter(
                    user=user,
                    name=rec.name,
                    amount=rec.amount,
                    date=rec.next_due_date,
                    category=rec.category,
                    recurring=rec
                ).exists():
                    Expense.objects.create(
                        name=rec.name,
                        amount=rec.amount,
                        date=rec.next_due_date,
                        category=rec.category,
                        user=user,
                        recurring=rec  # Link transaction to recurring record
                    )
                    total_expense += Decimal(rec.amount)

                rec.next_due_date = get_next_due_date(rec.next_due_date, rec.frequency)

                if rec.end_date and rec.next_due_date > rec.end_date:
                    rec.status = "inactive"
                else:
                    rec.status = "active"

                rec.save()
                changed = True
            else:
                rec.status = "pending"
                rec.save()

        # ---- Retry pending expenses ----
        pendings = RecurringExpense.objects.filter(user=user, status="pending")
        for rec in pendings:
            if rec.end_date and rec.next_due_date > rec.end_date:
                rec.status = "inactive"
                rec.save()
                continue

            if (total_expense + Decimal(rec.amount)) <= total_income:
                # ✅ Prevent duplicates
                if not Expense.objects.filter(
                    user=user,
                    name=rec.name,
                    amount=rec.amount,
                    date=rec.next_due_date,
                    category=rec.category,
                    recurring=rec
                ).exists():
                    Expense.objects.create(
                        name=rec.name,
                        amount=rec.amount,
                        date=rec.next_due_date,
                        category=rec.category,
                        user=user,
                        recurring=rec
                    )
                    total_expense += Decimal(rec.amount)

                rec.next_due_date = get_next_due_date(rec.next_due_date, rec.frequency)

                if rec.end_date and rec.next_due_date > rec.end_date:
                    rec.status = "inactive"
                else:
                    rec.status = "active"

                rec.save()
                changed = True
                

def retry_pending_expenses(user, total_income, total_expense):
    pending = RecurringExpense.objects.filter(user=user, status="pending").order_by("next_due_date")
    for rec in pending:
        if (total_expense + Decimal(rec.amount)) <= total_income:
            Expense.objects.create(
                name=rec.name,
                amount=rec.amount,
                date=rec.next_due_date,
                category=rec.category,
                user=user,
            )
            total_expense += Decimal(rec.amount)
            rec.next_due_date = get_next_due_date(rec.next_due_date, rec.frequency)
            rec.status = "active"
            rec.save()
           
@login_required
def recurring_expense(request):
    if request.method == 'POST':
        form = RecurringExpenseForm(request.POST)
        if form.is_valid():
            rec_exp = form.save(commit=False)
            rec_exp.user = request.user
            rec_exp.next_due_date = rec_exp.start_date  # ensure proper Date object
            rec_exp.save()
            messages.success(request, "Recurring expense added successfully!")
            check_budget_warnings(request, rec_exp)
            return redirect('recurring_expense')
        else:
            messages.error(request, "Please correct the errors below.")
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = RecurringExpenseForm()
    
    process_recurring_transactions(request.user)
    expenses = RecurringExpense.objects.filter(user=request.user)

    category_totals = expenses.values('category').annotate(total=Sum('amount'))
    categories = [item['category'] for item in category_totals]
    chart_data = [float(item['total']) for item in category_totals]

    context = {
        'form': form,
        'expenses': expenses,
        'categories': categories,
        'chart_data': chart_data,
        'timezone': timezone.now(),
    }
    return render(request, 'finance/recurring_expense.html', context)

@login_required
def recurring_income(request):
    if request.method == 'POST':
        form = RecurringIncomeForm(request.POST)
        if form.is_valid():
            rec_inc = form.save(commit=False)
            rec_inc.user = request.user
            rec_inc.next_due_date = rec_inc.start_date  # ensure proper Date object
            rec_inc.save()
            messages.success(request, "Recurring income added successfully!")
            return redirect('recurring_income')
        else:
            messages.error(request, "Please correct the errors below.")
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = RecurringIncomeForm()

    process_recurring_transactions(request.user)
    incomes = RecurringIncome.objects.filter(user=request.user)

    category_totals = incomes.values('category').annotate(total=Sum('amount'))
    categories = [item['category'] for item in category_totals]
    chart_data = [float(item['total']) for item in category_totals]

    context = {
        'form': form,
        'incomes': incomes,
        'categories': categories,
        'chart_data': chart_data,
        'timezone': timezone.now()
    }
    return render(request, 'finance/recurring_income.html', context)

@login_required
def edit_recurring_expense(request, id):
    expense = get_object_or_404(RecurringExpense, id=id, user=request.user)

    if request.method == "POST":
        form = RecurringExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            rec = form.save(commit=False)

            changed_fields = form.changed_data
            # Core fields that should trigger regeneration
            reset_fields = {"start_date", "end_date", "amount", "category", "frequency", "name"}

            if reset_fields.intersection(changed_fields):
                # Delete all previously generated transactions linked to this recurring record
                Expense.objects.filter(user=request.user, recurring=expense).delete()

                # Reset next_due_date and reactivate
                rec.next_due_date = rec.start_date
                rec.status = "active"

            # Handle new end_date logic
            if rec.end_date and rec.next_due_date > rec.end_date:
                rec.status = "inactive"
            else:
                rec.status = "active"

            rec.save()
            
            messages.success(request, "Recurring expense updated successfully! Transactions regenerated.")
            return redirect("recurring_expense")
        else:
            messages.error(request, "Please correct the errors below.")
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = RecurringExpenseForm(instance=expense)

    return redirect("recurring_expense")

@login_required
def edit_recurring_income(request, id):
    income = get_object_or_404(RecurringIncome, id=id, user=request.user)

    if request.method != "POST":
        return redirect("recurring_income")

    form = RecurringIncomeForm(request.POST, instance=income)
    if not form.is_valid():
        messages.error(request, "Please correct the errors below.")
        for error in form.errors.values():
            messages.error(request, error)
        return redirect("recurring_income")

    rec = form.save(commit=False)
    old_amount = income.amount or Decimal("0")
    new_amount = rec.amount or Decimal("0")

    # --- Compute totals excluding this recurring income ---
    total_income_excl = Income.objects.filter(user=request.user).exclude(recurring=income).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    total_expense = Expense.objects.filter(user=request.user).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # --- Get how many incomes were previously generated by this recurring income ---
    generated_qs = Income.objects.filter(user=request.user, recurring=income)
    generated_count = generated_qs.count()

    # --- Predict new total income after edit ---
    hypothetical_total_income = total_income_excl + (generated_count * new_amount)

    # --- Validation Rule ---
    # ❌ Block only if rule breaks: total_income < total_expense
    if hypothetical_total_income < total_expense:
        messages.error(
            request,
            f"Cannot update recurring income! Total income ({hypothetical_total_income}) "
            f"would become less than total expenses ({total_expense})."
        )
        return redirect("recurring_income")

    # --- Regenerate transactions if key fields changed ---
    changed_fields = form.changed_data
    reset_fields = {"start_date", "end_date", "amount", "category", "frequency", "source"}

    if reset_fields.intersection(changed_fields):
        Income.objects.filter(user=request.user, recurring=income).delete()
        rec.next_due_date = rec.start_date
        rec.status = "active"

    # --- Handle end_date logic ---
    if rec.end_date and rec.next_due_date > rec.end_date:
        rec.status = "inactive"
    else:
        rec.status = "active"

    rec.save()
    messages.success(request, "Recurring income updated successfully! Transactions regenerated.")
    return redirect("recurring_income")


@login_required    
def delete_recurring_expense(request, id):
    expense = get_object_or_404(RecurringExpense, id=id, user=request.user)
    if request.method == 'POST':
        expense.delete()
        messages.success(request, "Recurring expense deleted successfully!")
        return redirect('recurring_expense')
    
@login_required
def delete_recurring_income(request, id):
    income = get_object_or_404(RecurringIncome, id=id, user=request.user)
    if request.method == 'POST':
        income.delete()
        messages.success(request, "Recurring income deleted successfully!")
        return redirect('recurring_income')

@login_required
def dashboard(request):
    
    # Before loading dashboard, process any due recurring transactions
    process_recurring_transactions(request.user)

    # Now dashboard works with normal Income & Expense only
    income_total = Income.objects.filter(user=request.user).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    expense_total = Expense.objects.filter(user=request.user).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Ensure values are Decimal
    income_total = Decimal(income_total)
    expense_total = Decimal(expense_total)

    # Calculate balance as Decimal
    balance = income_total - expense_total

    # Optionally, round to 2 decimal places for display
    balance = balance.quantize(Decimal('0.01'))
    income_total = income_total.quantize(Decimal('0.01'))
    expense_total = expense_total.quantize(Decimal('0.01'))

    last_income = Income.objects.filter(user=request.user).order_by('-date').first()
    last_expense = Expense.objects.filter(user=request.user).order_by('-date').first()

    if last_income and last_expense:
        last_transaction = last_income if last_income.date > last_expense.date else last_expense
    elif last_income:
        last_transaction = last_income
    elif last_expense:
        last_transaction = last_expense
    else:
        last_transaction = None
        
    today = timezone.now().date()
    # Get due recurring expenses (pending)
    due_expenses = RecurringExpense.objects.filter(user=request.user, next_due_date__lte=today, status__in=["active", "pending"]).order_by('next_due_date')

    # Monthly trends
    monthly_income = (
        Income.objects.filter(user=request.user).annotate(month=ExtractMonth('date')).values('month').annotate(total=Sum('amount')).order_by('month')
    )
    monthly_expense = (
        Expense.objects.filter(user=request.user).annotate(month=ExtractMonth('date')).values('month').annotate(total=Sum('amount')).order_by('month')
    )

    income_dict = {item['month']: float(item['total']) for item in monthly_income}
    expense_dict = {item['month']: float(item['total']) for item in monthly_expense}

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    income_data = [income_dict.get(i+1, 0) for i in range(12)]
    expense_data = [expense_dict.get(i+1, 0) for i in range(12)]

    # Weekly trends
    weekly_income = (
        Income.objects.filter(user=request.user).annotate(week=ExtractWeek('date')).values('week').annotate(total=Sum('amount')).order_by('week')
    )
    weekly_expense = (
        Expense.objects.filter(user=request.user).annotate(week=ExtractWeek('date')).values('week').annotate(total=Sum('amount')).order_by('week')
    )

    week_income_dict = {w['week']: float(w['total']) for w in weekly_income}
    week_expense_dict = {w['week']: float(w['total']) for w in weekly_expense}

    weeks = [f"Week {i}" for i in range(1, 53)]
    weekly_income_data = [week_income_dict.get(i, 0) for i in range(1, 53)]
    weekly_expense_data = [week_expense_dict.get(i, 0) for i in range(1, 53)]

    # Category-wise
    category_expenses = (
        Expense.objects.filter(user=request.user).values('category').annotate(total=Sum('amount')).order_by('-total')
    )
    category_labels = [c['category'] for c in category_expenses]
    category_values = [float(c['total']) for c in category_expenses]

    context = {
        "total_income": income_total,
        "total_expense": expense_total,
        "balance": balance,
        "months": months,
        "income_data": income_data,
        "expense_data": expense_data,
        "weeks": weeks,
        "weekly_income_data": weekly_income_data,
        "weekly_expense_data": weekly_expense_data,
        "category_labels": category_labels,
        "category_values": category_values,
        "last_transaction": last_transaction,
        "last_income": last_income,
        "last_expense": last_expense,
        "due_expenses": due_expenses
    }
    return render(request, "finance/dashboard.html", context)



                
