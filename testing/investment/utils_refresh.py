from django.utils import timezone
from datetime import timedelta
from .utils import get_expected_return_by_type

def refresh_if_stale(investment, days=7):
    """Update expected return if data is older than given days."""
    if not investment.last_updated or investment.last_updated < timezone.now() - timedelta(days=days):
        new_return = get_expected_return_by_type(investment.investment_type)
        if new_return is not None:
            investment.expected_return = new_return
            investment.last_updated = timezone.now()
            investment.save(update_fields=["expected_return", "last_updated"])
