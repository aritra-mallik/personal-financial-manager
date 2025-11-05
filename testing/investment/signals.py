from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Investment
from finance.models import Expense

@receiver(post_save, sender=Investment)
def create_investment_expense(sender, instance, created, **kwargs):
    """
    When a new investment is created, record it as an expense.
    Do NOT record income here — it will be handled on maturity in views.
    """
    if created:
        Expense.objects.create(
            user=instance.user,
            name=f"Investment in {instance.name}",
            amount=instance.amount,
            date=instance.start_date if instance.start_date else timezone.now().date(),
            category="Financial"
        )
