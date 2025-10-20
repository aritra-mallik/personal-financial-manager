# utils.py
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dateutil import parser
import logging

logger = logging.getLogger(__name__)

def get_next_due_date(current_date, frequency):
    if frequency == "daily":
        return current_date + timedelta(days=1)
    elif frequency == "weekly":
        return current_date + timedelta(weeks=1)
    elif frequency == "monthly":
        return current_date + relativedelta(months=1)
    elif frequency == "quarterly":
        return current_date + relativedelta(months=3)
    elif frequency == "biannually":
        return current_date + relativedelta(months=6)
    elif frequency == "yearly":
        return current_date + relativedelta(years=1)
    return current_date

HEADER_MAPPING = {
    "date": ["date", "transaction_date", "income_date", "expense_date","day","day_of_transaction","posted date"],
    "source": ["source", "income_source", "from", "source_name","source_title","source_label","name","description","transaction details","memo"],
    "name": ["name", "expense_name", "item","source_name","source_title","source_label","source","item_name","description","transaction details","memo"],
    "amount": ["amount", "value", "price", "cost","amount_paid","amount_received","money"],
    "category": ["category", "type", "group","category_name","category_title","category_label"]
}


def normalize_headers(fieldnames):
    normalized = {}
    lowercase_map = {f.strip().lower().replace(" ", ""): f for f in fieldnames}

    for key, variations in HEADER_MAPPING.items():
        for variation in variations:
            normalized_var = variation.strip().lower().replace(" ", "")
            if normalized_var in lowercase_map:
                normalized[key] = lowercase_map[normalized_var]
                break
    return normalized

def normalize_date(date_str):
    if not date_str:
        return None
    date_str = str(date_str).strip()
    
    # Try fixed known formats first (fast path)
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return parser.parse(datetime.strptime(date_str, fmt).date().isoformat())
        except Exception:
            continue
    
    # Fallback to flexible parser
    try:
        return parser.parse(date_str, dayfirst=True).date()
    except Exception as e:
        logger.warning(f"DATE PARSE ERROR: {date_str} -> {e}")
        return None

        
def clean_value(value, default=None, cast_type=str):

    if value is None:
        return default
    value = str(value).strip()
    if value == "":
        return default
    try:
        return cast_type(value)
    except Exception:
        return default

INCOME_CATEGORY_MAPPING = {
    "Salary": [
        "salary", "salaries", "wages", "paycheck", "monthly pay", "stipend", "SALARY", "PAYCHECK", "Monthly Payment"
    ],
    "Business": [
        "business", "self-employed", "trade", "sales", "company income", "BUSINESS"
    ],
    "Freelance": [
        "freelance", "freelancer", "contract work", "gig", "side hustle", "consulting", "FREELANCE", "CONTRACT", "Side Hustle"
    ],
    "Rental Income": [
        "rental income", "rent", "lease", "property income", "RENTAL", "RENT"
    ],
    "Dividends": [
        "dividends", "shares", "stocks", "equity return", "DIVIDENDS", "stock income", "Investment"
    ],
    "Interest Income": [
        "interest income", "bank interest", "deposit interest", "fd interest", "rd interest", "INTEREST"
    ],
    "Gifts & Donations": [
        "gifts", "gift", "donation", "donations", "present", "charity received", "GIFTS"
    ],
    "Refunds": [
        "refunds", "rebate", "cashback", "reimbursement", "REFUND"
    ],
    "Retirement Income": [
        "retirement income", "pension", "provident fund", "pf", "annuity", "RETIREMENT"
    ],
    "Bonus & Incentives": [
        "bonus", "incentive", "performance pay", "commission", "perks", "BONUS"
    ],
    "Other Income": [
        "other income", "miscellaneous", "misc", "unknown", "extra income", "OTHER"
    ]
}
def normalize_income_category(raw_category):
    raw_category = str(raw_category).strip().lower()
    for standard, synonyms in INCOME_CATEGORY_MAPPING.items():
        if raw_category in [s.lower() for s in synonyms]:
            return standard
    return "Other Income"  # fallback

EXPENSE_CATEGORY_MAPPING = {
    "Housing & Utilities": [
        "housing", "rent", "mortgage", "utilities", "electricity", "water bill", "family", "childcare", "kids", "baby", "gifts", "parents", "friends", 
        "celebration", "festivals", "FAMILY", "gas bill", "internet", "wifi", "maintenance", "household", "bills", "HOUSING"
    ],
    "Transportation": [
        "transportation", "transport", "commute", "bus", "train", "metro", "cab", "uber", "bike",
        "taxi", "car", "fuel", "petrol", "diesel", "parking", "vehicle", "TRAVEL LOCAL"
    ],
    "Food & Dining": [
        "food", "foods", "dining", "restaurant", "meal", "meals", "groceries", 
        "supermarket", "snacks", "coffee", "lunch", "dinner", "breakfast", "takeaway", "FOOD"
    ],
    "Personal & Shopping": [
        "personal", "shopping", "clothes", "apparel", "fashion", "cosmetics", 
        "beauty", "grooming", "electronics", "gadgets", "online shopping", "mall", "SHOPPING"
    ],
    "Health & Fitness": [
        "health", "fitness", "gym", "workout", "exercise", "doctor", "hospital", 
        "medicine", "pharmacy", "drugs", "clinic", "checkup", "yoga", "HEALTH"
    ],
    "Entertainment & Leisure": [
        "entertainment", "movies", "cinema", "concert", "theatre", "music", 
        "games", "gaming", "subscriptions", "netflix", "spotify", "party", "leisure", "ENTERTAINMENT"
    ],
    "Education": [
        "education", "school", "college", "tuition", "books", "courses", 
        "online courses", "training", "fees", "exam", "EDUCATION"
    ],
    "Financial": [
        "financial", "insurance", "loan", "emi", "investment", "bank charges", "stock-market", "share-market",
        "interest paid", "credit card", "tax", "fees", "finance", "FINANCIAL"
    ],
    "Travel & Vacation": [
        "travel", "vacation", "trip", "holiday", "tourism", "flight", 
        "hotel", "resort", "tickets", "visa", "tour", "TRAVEL"
    ],
    "Miscellaneous": [
        "miscellaneous", "misc", "other", "unknown", "extra", "donation", "others", "uncategorized", "MISC"
    ]
}

def normalize_expense_category(raw_category):
    raw_category = str(raw_category).strip().lower()
    for standard, synonyms in EXPENSE_CATEGORY_MAPPING.items():
        if raw_category in [s.lower() for s in synonyms]:
            return standard
    return "Miscellaneous"  # fallback


