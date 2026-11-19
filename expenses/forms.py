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
    splits = {}
    errors = []
    mode = post_data.get('split_mode', 'value')
    if mode not in ('value', 'percentage'):
        return {}, ['Modo de divisão inválido.']
    selected = 0

    for membership in accepted_memberships:
        uid = membership.user_id
        participates = post_data.get(f'split_participates_{uid}') == 'on'
        raw_amount = (post_data.get(f'split_amount_{uid}') or '').strip().replace(',', '.')

        if participates:
            selected += 1
            if not raw_amount:
                errors.append(f'Informe o valor devido para {membership.user.username}.')
                continue
            try:
                val = Decimal(raw_amount)
            except InvalidOperation:
                errors.append(f'Valor inválido para {membership.user.username}.')
                continue
            if not val.is_finite() or val < Decimal('0.01') or val > Decimal('1000000000000') or val.as_tuple().exponent < -2:
                errors.append(f'Informe um valor positivo válido com até duas casas decimais para {membership.user.username}.')
                continue
            splits[uid] = val

    if not selected:
        errors.append('Selecione pelo menos um participante aceito no grupo para dividir a despesa.')
    if errors or total_amount is None or not total_amount.is_finite() or total_amount <= 0:
        return splits, errors

    target = Decimal('100') if mode == 'percentage' else total_amount
    if sum(splits.values(), Decimal('0')) != target:
        errors.append('A soma dos percentuais deve ser exatamente 100%.' if mode == 'percentage'
                      else 'A soma das divisões deve ser exatamente igual ao valor total da despesa.')
    elif mode == 'percentage':
        total_cents = int(total_amount * 100)
        shares = {uid: divmod(total_cents * int(value * 100), 10000) for uid, value in splits.items()}
        remaining = total_cents - sum(share[0] for share in shares.values())
        winners = sorted(shares, key=lambda uid: (-shares[uid][1], uid))[:remaining]
        splits = {uid: Decimal(cents + (uid in winners)) / 100 for uid, (cents, _) in shares.items()}
        if any(value < Decimal('0.01') for value in splits.values()):
            errors.append('Cada participante deve receber pelo menos R$ 0,01.')

    return splits, errors
