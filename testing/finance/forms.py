from django import forms
from .models import Income, Expense, RecurringIncome, RecurringExpense #, Category
from django.utils import timezone

class BaseFinanceForm(forms.ModelForm):
    #Base form for Income and Expense to avoid duplication

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make all fields required
        for field in self.fields:
            if field not in [self._meta.model._meta.pk.name, "end_date"]:
                self.fields[field].required = True

        # Handle category dropdown (remove "---------" and default to first)
        if 'category' in self.fields:
            model = self._meta.model
            self.fields['category'].choices = model.CATEGORY_CHOICES
            
        if 'frequency' in self.fields:
            model = self._meta.model
            self.fields['frequency'].choices = model.FREQUENCY_CHOICES

class IncomeForm(BaseFinanceForm):
    class Meta:
        model = Income
        fields = ['source', 'amount', 'date', 'category']
        widgets = {
            'source': forms.TextInput(attrs={'placeholder': 'Enter source', 'class': 'input-field'}),
            'date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
        }

        
class ExpenseForm(BaseFinanceForm):
    class Meta:
        model = Expense
        fields = ['name', 'amount', 'date', 'category']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter name', 'class': 'input-field'}),
            'date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
        }
        
class RecurringIncomeForm(BaseFinanceForm):
    class Meta:
        model = RecurringIncome
        fields = ['source', 'amount', 'frequency', 'category', 'start_date', 'end_date']
        widgets = {
            'source': forms.TextInput(attrs={'placeholder': 'Enter source', 'class': 'input-field'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'end_date': 'End Date (optional)',
        }
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if end_date and start_date and end_date < start_date:
            self.add_error('end_date', 'End date cannot be earlier than start date.')

        return cleaned_data
        
class RecurringExpenseForm(BaseFinanceForm):
    class Meta:
        model = RecurringExpense
        fields = ['name', 'amount', 'frequency', 'category', 'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter name', 'class': 'input-field'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'end_date': 'End Date (optional)',
        }
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if end_date and start_date and end_date < start_date:
            self.add_error('end_date', 'End date cannot be earlier than start date.')

        return cleaned_data 
        
""" class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'type']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter category name', 'class': 'input-field'}),
            'type': forms.Select(attrs={'class': 'select-field'}),
        } """
        
""" from django import forms
from django.utils import timezone
from .models import Category, Income, Expense, RecurringIncome, RecurringExpense

class BaseFinanceForm(forms.ModelForm):
    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make all fields required except PK and optional end_date
        for field_name, field in self.fields.items():
            if field_name not in [self._meta.model._meta.pk.name, "end_date"]:
                field.required = True

        # Set category choices if applicable
        if 'category' in self.fields:
            model = self._meta.model
            self.fields['category'].choices = model.CATEGORY_CHOICES

        # Set frequency choices if applicable
        if 'frequency' in self.fields:
            model = self._meta.model
            self.fields['frequency'].choices = model.FREQUENCY_CHOICES

        # Optional: Client-side date restrictions for recurring transactions
        if self.instance.pk and hasattr(self.instance, 'start_date'):
            original_start = self.instance.start_date
            self.fields['start_date'].widget.attrs['max'] = str(original_start)

            original_end = getattr(self.instance, 'end_date', None)
            min_end = original_start
            if original_end:
                min_end = max(original_start, original_end)
            self.fields['end_date'].widget.attrs['min'] = str(min_end)

    def clean(self):
        cleaned_data = super().clean()

        # Validate basic date logic
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'End date cannot be earlier than start date.')

        # Editing restrictions for recurring transactions
        if self.instance.pk and hasattr(self.instance, 'start_date'):
            original_start = self.instance.start_date
            original_end = getattr(self.instance, 'end_date', None)

            if start_date and start_date > original_start:
                self.add_error('start_date', f'Start Date cannot be later than {original_start} because it was already registered.')

            if end_date and original_end and end_date < original_end:
                self.add_error('end_date', f'End Date cannot be earlier than {original_end} because it was already registered.')

        return cleaned_data


# ------------------------------
# Specific Forms
# ------------------------------

class IncomeForm(BaseFinanceForm):
    class Meta:
        model = Income
        fields = ['source', 'amount', 'date', 'category']
        widgets = {
            'source': forms.TextInput(attrs={'placeholder': 'Enter source', 'class': 'input-field'}),
            'date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
        }


class ExpenseForm(BaseFinanceForm):
    class Meta:
        model = Expense
        fields = ['name', 'amount', 'date', 'category']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter name', 'class': 'input-field'}),
            'date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
        }


class RecurringIncomeForm(BaseFinanceForm):
    class Meta:
        model = RecurringIncome
        fields = ['source', 'amount', 'frequency', 'category', 'start_date', 'end_date']
        widgets = {
            'source': forms.TextInput(attrs={'placeholder': 'Enter source', 'class': 'input-field'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {'end_date': 'End Date (optional)'}


class RecurringExpenseForm(BaseFinanceForm):
    class Meta:
        model = RecurringExpense
        fields = ['name', 'amount', 'frequency', 'category', 'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter name', 'class': 'input-field'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Enter amount'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'value': timezone.now().date()}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {'end_date': 'End Date (optional)'}


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'type']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter category name', 'class': 'input-field'}),
            'type': forms.Select(attrs={'class': 'select-field'}),
        } """