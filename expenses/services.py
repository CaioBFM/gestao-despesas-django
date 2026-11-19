from decimal import Decimal

from django.db.models import F, Q

from .models import ExpenseSplit


def calculate_participant_balances(group, user):
    """Return pending pairwise balances from the reference user's perspective.

    Each row contains the participant, gross amounts owed in both directions,
    the absolute net amount, and direction (DEVE, RECEBE or EM_DIA).
    """
    splits = (
        ExpenseSplit.objects.filter(expense__group=group, is_paid=False)
        .filter(Q(user=user) | Q(expense__paid_by=user))
        .exclude(user_id=F('expense__paid_by_id'))
        .select_related('user', 'expense__paid_by')
        .order_by()
    )
    balances = {}
    for split in splits:
        owes = split.user_id == user.pk
        participant = split.expense.paid_by if owes else split.user
        balance = balances.setdefault(participant.pk, {
            'participant': participant,
            'amount_owed': Decimal('0.00'),
            'amount_receivable': Decimal('0.00'),
        })
        balance['amount_owed' if owes else 'amount_receivable'] += split.amount_owed

    result = []
    for participant_id in sorted(balances):
        balance = balances[participant_id]
        net = balance['amount_receivable'] - balance['amount_owed']
        balance['net_amount'] = abs(net)
        balance['direction'] = 'RECEBE' if net > 0 else 'DEVE' if net < 0 else 'EM_DIA'
        result.append(balance)
    return result
