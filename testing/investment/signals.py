from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import Investment
from finance.models import Expense, Income
from decimal import Decimal, ROUND_HALF_UP

# -------------------------------------------------
# Helper: Choose income category based on investment type
# -------------------------------------------------
def choose_income_category(inv_type):
    t = (inv_type or "").lower()
    if t in ["fd", "fixed deposit", "rd", "recurring deposit", "bond"]:
        return "Interest Income"
    if t in ["stock", "mutual fund", "etf", "crypto", "share"]:
        return "Dividends"
    if t in ["real estate", "pension"]:
        return "Rental Income"
    if t in ["gold"]:
        return "Other Income"
    return "Other Income"


# -------------------------------------------------
# Helper: Compact compound value calculator (same as portfolio logic)
# -------------------------------------------------
def _calculate_estimated_value(amount, expected_return, start_date, end_date):
    if not start_date or not end_date or expected_return is None:
        return amount
    days = (end_date - start_date).days
    if days <= 0:
        return amount
    years = Decimal(days) / Decimal("365")
    value = amount * ((Decimal("1") + (expected_return / Decimal("100"))) ** years)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# -------------------------------------------------
# Track old name before saving (for rename detection)
# -------------------------------------------------
@receiver(pre_save, sender=Investment)
def track_old_name(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = Investment.objects.get(pk=instance.pk)
            instance._old_name = old.name
        except Investment.DoesNotExist:
            instance._old_name = None
    else:
        instance._old_name = None


# -------------------------------------------------
# Sync Expense and Income after create or edit
# -------------------------------------------------
@receiver(post_save, sender=Investment)
def sync_investment_records(sender, instance, created, **kwargs):
    old_name = getattr(instance, "_old_name", None)
    name_changed = old_name and old_name != instance.name

    # -------- EXPENSE handling --------
    expense_name = f"Investment in {instance.name}"

    expense, _ = Expense.objects.get_or_create(
        user=instance.user,
        investment=instance,  # ✅ unique link
        defaults={
            "name": expense_name,
            "amount": instance.amount,
            "date": instance.start_date or timezone.now().date(),
            "category": "Financial",
        },
    )

    updated_fields = []
    if expense.amount != instance.amount:
        expense.amount = instance.amount
        updated_fields.append("amount")
    if expense.date != (instance.start_date or timezone.now().date()):
        expense.date = instance.start_date or timezone.now().date()
        updated_fields.append("date")
    if name_changed:
        expense.name = expense_name
        updated_fields.append("name")
    if updated_fields:
        expense.save(update_fields=updated_fields)

    # -------- INCOME handling --------
    income_name = f"Investment Maturity - {instance.name}"
    income = Income.objects.filter(user=instance.user, investment=instance).first()  # ✅ unique link

    if instance.status == "Completed" and instance.end_date:
        amount = Decimal(instance.amount)
        expected_return = Decimal(instance.expected_return or 0)
        est_value = _calculate_estimated_value(amount, expected_return, instance.start_date, instance.end_date)
        category = choose_income_category(getattr(instance, "investment_type", ""))

        if income:
            updated = False
            if income.amount != est_value:
                income.amount = est_value
                updated = True
            if income.date != instance.end_date:
                income.date = instance.end_date
                updated = True
            if income.source != income_name:
                income.source = income_name
                updated = True
            if updated:
                income.save(update_fields=["amount", "date", "source"])
        else:
            Income.objects.create(
                user=instance.user,
                investment=instance,  # ✅ unique link
                source=income_name,
                amount=est_value,
                date=instance.end_date,
                category=category,
            )

    elif income and instance.status != "Completed":
        income.delete()


# -------------------------------------------------
# Clean up linked Expense and Income on delete
# -------------------------------------------------
@receiver(post_delete, sender=Investment)
def delete_linked_records(sender, instance, **kwargs):
    Expense.objects.filter(investment=instance).delete()  # ✅ clean by link
    Income.objects.filter(investment=instance).delete()   # ✅ clean by link

#latest_version
# from django.db.models.signals import post_save, pre_save, post_delete
# from django.dispatch import receiver
# from django.utils import timezone
# from .models import Investment
# from finance.models import Expense, Income
# from decimal import Decimal, ROUND_HALF_UP

# # -------------------------------------------------
# # Helper: Choose income category based on investment type
# # -------------------------------------------------
# def choose_income_category(inv_type):
#     t = (inv_type or "").lower()
#     if t in ["fd", "fixed deposit", "rd", "recurring deposit", "bond"]:
#         return "Interest Income"
#     if t in ["stock", "mutual fund", "etf", "crypto", "share"]:
#         return "Dividends"
#     if t in ["real estate", "pension"]:
#         return "Rental Income"
#     if t in ["gold"]:
#         return "Other Income"
#     return "Other Income"


# # -------------------------------------------------
# # Helper: Compact compound value calculator (same as portfolio logic)
# # -------------------------------------------------
# def _calculate_estimated_value(amount, expected_return, start_date, end_date):
#     if not start_date or not end_date or expected_return is None:
#         return amount
#     days = (end_date - start_date).days
#     if days <= 0:
#         return amount
#     years = Decimal(days) / Decimal("365")
#     value = amount * ((Decimal("1") + (expected_return / Decimal("100"))) ** years)
#     return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# # -------------------------------------------------
# # Track old name before saving (for rename detection)
# # -------------------------------------------------
# @receiver(pre_save, sender=Investment)
# def track_old_name(sender, instance, **kwargs):
#     if instance.pk:
#         try:
#             old = Investment.objects.get(pk=instance.pk)
#             instance._old_name = old.name
#         except Investment.DoesNotExist:
#             instance._old_name = None
#     else:
#         instance._old_name = None


# # -------------------------------------------------
# # Sync Expense and Income after create or edit
# # -------------------------------------------------
# @receiver(post_save, sender=Investment)
# def sync_investment_records(sender, instance, created, **kwargs):
#     old_name = getattr(instance, "_old_name", None)
#     name_changed = old_name and old_name != instance.name

#     # -------- EXPENSE handling --------
#     expense_name = f"Investment in {instance.name}"
#     old_expense_name = f"Investment in {old_name}" if name_changed else expense_name

#     expense, _ = Expense.objects.get_or_create(
#         user=instance.user,
#         name=old_expense_name,
#         defaults={
#             "amount": instance.amount,
#             "date": instance.start_date or timezone.now().date(),
#             "category": "Financial",
#         },
#     )

#     updated_fields = []
#     if expense.amount != instance.amount:
#         expense.amount = instance.amount
#         updated_fields.append("amount")
#     if expense.date != (instance.start_date or timezone.now().date()):
#         expense.date = instance.start_date or timezone.now().date()
#         updated_fields.append("date")
#     if name_changed:
#         expense.name = expense_name
#         updated_fields.append("name")
#     if updated_fields:
#         expense.save(update_fields=updated_fields)

#     # -------- INCOME handling --------
#     income_name = f"Investment Maturity - {instance.name}"
#     old_income_name = f"Investment Maturity - {old_name}" if name_changed else income_name
#     existing_income = Income.objects.filter(user=instance.user, source=old_income_name).first()

#     if instance.status == "Completed" and instance.end_date:
#         amount = Decimal(instance.amount)
#         expected_return = Decimal(instance.expected_return or 0)
#         est_value = _calculate_estimated_value(amount, expected_return, instance.start_date, instance.end_date)
#         category = choose_income_category(getattr(instance, "investment_type", ""))

#         if existing_income:
#             updated = False
#             if existing_income.amount != est_value:
#                 existing_income.amount = est_value
#                 updated = True
#             if existing_income.date != instance.end_date:
#                 existing_income.date = instance.end_date
#                 updated = True
#             if name_changed:
#                 existing_income.source = income_name
#                 updated = True
#             if updated:
#                 existing_income.save(update_fields=["amount", "date", "source"])
#         else:
#             Income.objects.create(
#                 user=instance.user,
#                 source=income_name,
#                 amount=est_value,
#                 date=instance.end_date,
#                 category=category,
#             )

#     elif existing_income and instance.status != "Completed":
#         existing_income.delete()


# # -------------------------------------------------
# # Clean up linked Expense and Income on delete
# # -------------------------------------------------
# @receiver(post_delete, sender=Investment)
# def delete_linked_records(sender, instance, **kwargs):
#     expense_name = f"Investment in {instance.name}"
#     income_name = f"Investment Maturity - {instance.name}"

#     Expense.objects.filter(user=instance.user, name=expense_name).delete()
#     Income.objects.filter(user=instance.user, source=income_name).delete()

# from django.db.models.signals import post_save, pre_save, post_delete
# from django.dispatch import receiver
# from django.utils import timezone
# from .models import Investment
# from finance.models import Expense, Income
# from decimal import Decimal, ROUND_HALF_UP

# # -------------------------------------------------
# # Helper: Choose income category based on investment type
# # -------------------------------------------------
# def choose_income_category(inv_type):
#     t = (inv_type or "").lower()
#     if t in ["fd", "fixed deposit", "rd", "recurring deposit", "bond"]:
#         return "Interest Income"
#     if t in ["stock", "mutual fund", "etf", "crypto", "share"]:
#         return "Dividends"
#     if t in ["real estate", "pension"]:
#         return "Rental Income"
#     if t in ["gold"]:
#         return "Other Income"
#     return "Other Income"



# # -------------------------------------------------
# # Track old name before saving (for rename detection)
# # -------------------------------------------------
# @receiver(pre_save, sender=Investment)
# def track_old_name(sender, instance, **kwargs):
#     if instance.pk:
#         try:
#             old = Investment.objects.get(pk=instance.pk)
#             instance._old_name = old.name
#         except Investment.DoesNotExist:
#             instance._old_name = None
#     else:
#         instance._old_name = None


# # -------------------------------------------------
# # Sync Expense and Income after create or edit
# # -------------------------------------------------
# @receiver(post_save, sender=Investment)
# def sync_investment_records(sender, instance, created, **kwargs):
#     old_name = getattr(instance, "_old_name", None)
#     name_changed = old_name and old_name != instance.name

#     # -------- EXPENSE handling --------
#     expense_name = f"Investment in {instance.name}"
#     old_expense_name = f"Investment in {old_name}" if name_changed else expense_name

#     expense, _ = Expense.objects.get_or_create(
#         user=instance.user,
#         name=old_expense_name,
#         defaults={
#             "amount": instance.amount,
#             "date": instance.start_date or timezone.now().date(),
#             "category": "Financial",
#         },
#     )

#     updated_fields = []
#     if expense.amount != instance.amount:
#         expense.amount = instance.amount
#         updated_fields.append("amount")
#     if expense.date != (instance.start_date or timezone.now().date()):
#         expense.date = instance.start_date or timezone.now().date()
#         updated_fields.append("date")
#     if name_changed:
#         expense.name = expense_name
#         updated_fields.append("name")

#     if updated_fields:
#         expense.save(update_fields=updated_fields)

#     # -------- INCOME handling --------
#     income_name = f"Investment Maturity - {instance.name}"
#     old_income_name = f"Investment Maturity - {old_name}" if name_changed else income_name
#     existing_income = Income.objects.filter(user=instance.user, source=old_income_name).first()

#     if instance.status == "Completed" and instance.end_date:
#         est_value = getattr(instance, "estimated_value", instance.amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
#         category = choose_income_category(getattr(instance, "investment_type", ""))
#         if existing_income:
#             updated = False
#             if existing_income.amount != est_value:
#                 existing_income.amount = est_value
#                 updated = True
#             if existing_income.date != instance.end_date:
#                 existing_income.date = instance.end_date
#                 updated = True
#             if name_changed:
#                 existing_income.source = income_name
#                 updated = True
#             if updated:
#                 existing_income.save(update_fields=["amount", "date", "source"])
#         else:
#             Income.objects.create(
#                 user=instance.user,
#                 source=income_name,
#                 amount=est_value,
#                 date=instance.end_date,
#                 category=category,
#             )

#     elif existing_income and instance.status != "Completed":
#         # Reverted back from completed → active
#         existing_income.delete()


# # -------------------------------------------------
# # Clean up linked Expense and Income on delete
# # -------------------------------------------------
# @receiver(post_delete, sender=Investment)
# def delete_linked_records(sender, instance, **kwargs):
#     expense_name = f"Investment in {instance.name}"
#     income_name = f"Investment Maturity - {instance.name}"

#     Expense.objects.filter(user=instance.user, name=expense_name).delete()
#     Income.objects.filter(user=instance.user, source=income_name).delete()
    
    
# from decimal import Decimal
# from django.core.exceptions import ValidationError
# from django.db.models import Sum

# @receiver(pre_save, sender=Investment)
# def enforce_income_vs_expense_rule(sender, instance, **kwargs):
#     """Prevent creating/updating investment if total expenses exceed total income."""
#     user = instance.user

#     total_income = Income.objects.filter(user=user).aggregate(total=Sum('amount'))['total'] or Decimal('0')
#     total_expense = Expense.objects.filter(user=user).aggregate(total=Sum('amount'))['total'] or Decimal('0')

#     # Predict what total expense would become after this investment
#     projected_expense = total_expense + instance.amount

#     if projected_expense > total_income:
#         raise ValidationError("Total income must be greater than or equal to total expenses before saving this investment.")

