from decimal import Decimal, InvalidOperation
from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Group, Expense, GroupMembership

User = get_user_model()


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ('name', 'description')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class JoinGroupForm(forms.Form):
    invite_code = forms.CharField(
        label="Código de Convite do Grupo",
        max_length=10,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: RJ2026'})
    )


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ('title', 'description', 'amount', 'date', 'paid_by')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Mercado do mês'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Detalhes opcionais...'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'paid_by': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        if group is not None:
            accepted_user_ids = GroupMembership.objects.filter(
                group=group,
                is_accepted=True
            ).values_list('user_id', flat=True)
            self.fields['paid_by'].queryset = User.objects.filter(pk__in=accepted_user_ids).order_by('username')

        if self.instance and self.instance.pk and self.instance.date:
            self.initial['date'] = self.instance.date.strftime('%Y-%m-%d')
        elif not self.instance.pk and not self.initial.get('date'):
            self.initial['date'] = timezone.localdate().strftime('%Y-%m-%d')


def parse_splits_from_post(post_data, accepted_memberships, total_amount=None):
    """
    Lê os checkboxes `split_participates_<user_id>` e campos `split_amount_<user_id>`.
    Se `total_amount` for informado (Decimal), valida se a soma das divisões não ultrapassa o valor total.
    Retorna `(splits_dict, errors_list)` onde `splits_dict` mapeia `user_id -> Decimal(amount_owed)`.
    """
    splits = {}
    errors = []

    for membership in accepted_memberships:
        uid = membership.user_id
        participates = post_data.get(f'split_participates_{uid}') == 'on'
        raw_amount = (post_data.get(f'split_amount_{uid}') or '').strip().replace(',', '.')

        if participates:
            if not raw_amount:
                errors.append(f'Informe o valor devido para {membership.user.username}.')
                continue
            try:
                val = Decimal(raw_amount)
            except InvalidOperation:
                errors.append(f'Valor inválido para {membership.user.username}.')
                continue
            if val < Decimal('0.01'):
                errors.append(f'O valor de {membership.user.username} deve ser de pelo menos R$ 0,01.')
                continue
            splits[uid] = val.quantize(Decimal('0.01'))

    if not splits:
        errors.append('Selecione pelo menos um participante aceito no grupo para dividir a despesa.')
    elif total_amount is not None:
        splits_sum = sum(splits.values(), Decimal('0.00'))
        if splits_sum > total_amount:
            errors.append(
                f'A soma das divisões (R$ {splits_sum:.2f}) não pode ser maior que o valor total da despesa (R$ {total_amount:.2f}).'
            )

    return splits, errors