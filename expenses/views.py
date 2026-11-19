from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from .models import Group, GroupMembership, Expense, ExpenseSplit
from .forms import GroupForm, JoinGroupForm, ExpenseForm, parse_splits_from_post


def _get_accepted_membership(user, group):
    return GroupMembership.objects.filter(user=user, group=group, is_accepted=True).first()


def _is_group_admin_or_superuser(user, group, membership=None):
    if user.is_superuser:
        return True
    if membership is None:
        membership = _get_accepted_membership(user, group)
    return bool(membership and membership.is_group_admin)


def _is_last_group_admin(membership):
    return (
        membership.is_accepted
        and membership.is_group_admin
        and not GroupMembership.objects.filter(
            group=membership.group, is_accepted=True, is_group_admin=True,
        ).exclude(pk=membership.pk).exists()
    )


def _can_manage_expense(user, expense, group, membership=None):
    if user.is_superuser:
        return True
    if membership is None:
        membership = _get_accepted_membership(user, group)
    if not membership or not membership.is_accepted:
        return False
    if expense.created_by_id == user.pk or expense.paid_by_id == user.pk:
        return True
    return _is_group_admin_or_superuser(user, group, membership)


def _can_toggle_split(user, split, membership):
    return _can_manage_expense(user, split.expense, split.expense.group, membership) or bool(
        membership and membership.is_accepted and split.user_id == user.pk
    )


def _user_participation_status(user, expense):
    split = next((s for s in expense.splits.all() if s.user_id == user.pk), None)
    if split is None:
        return 'Não participa', None
    if split.is_paid:
        return 'Paga', split
    return 'A pagar', split


def _extract_post_total_amount(post_data, form):
    if form.is_valid():
        return form.cleaned_data.get('amount')
    raw_amount = (post_data.get('amount') or '').strip().replace(',', '.')
    if not raw_amount:
        return None
    try:
        return Decimal(raw_amount).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None


@login_required
def group_list(request):
    user_groups = Group.objects.filter(
        groupmembership__user=request.user,
        groupmembership__is_accepted=True,
        is_active=True
    )
    join_form = JoinGroupForm()
    return render(request, 'expenses/group_list.html', {'groups': user_groups, 'join_form': join_form})


@login_required
def group_create(request):
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            group = form.save(commit=False)
            group.created_by = request.user
            group.save()
            messages.success(request, 'Grupo criado com sucesso!')
            return redirect('group_detail', pk=group.pk)
    else:
        form = GroupForm()
    return render(request, 'expenses/group_form.html', {'form': form})


@login_required
def group_join(request):
    if request.method == 'POST':
        form = JoinGroupForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['invite_code'].upper().strip()
            try:
                group = Group.objects.get(invite_code=code, is_active=True)
                existing_membership = GroupMembership.objects.filter(
                    user=request.user,
                    group=group
                ).first()

                if existing_membership:
                    if existing_membership.is_accepted:
                        messages.info(request, f'Você já faz parte do grupo "{group.name}".')
                        return redirect('group_detail', pk=group.pk)
                    else:
                        messages.info(
                            request,
                            f'Seu pedido para entrar no grupo "{group.name}" (código {group.invite_code}) já foi enviado e aguarda aprovação.'
                        )
                else:
                    GroupMembership.objects.create(
                        user=request.user,
                        group=group,
                        is_accepted=False,
                        is_group_admin=False
                    )
                    messages.success(
                        request,
                        f'Pedido de entrada enviado para o grupo "{group.name}" (código {group.invite_code})! Aguarde a aprovação de um administrador.'
                    )

                return redirect('group_list')
            except Group.DoesNotExist:
                messages.error(request, 'Código de convite inválido ou grupo desativado.')
    return redirect('group_list')


@login_required
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk, is_active=True)
    membership = _get_accepted_membership(request.user, group)

    if not membership and not request.user.is_superuser:
        messages.error(request, 'Você não tem permissão para acessar este grupo.')
        return redirect('group_list')

    user_is_group_admin = bool(membership and membership.is_accepted and membership.is_group_admin)

    if request.method == 'POST' and user_is_group_admin:
        action = request.POST.get('action')
        if action == 'update_info':
            group.description = request.POST.get('description', group.description)
            new_code = request.POST.get('invite_code', '').upper().strip()
            if new_code and new_code != group.invite_code:
                if Group.objects.filter(invite_code=new_code).exists():
                    messages.error(request, 'Este código de convite já está em uso por outro grupo.')
                else:
                    group.invite_code = new_code
                    messages.success(request, 'Código de convite alterado com sucesso!')
            group.save()
            return redirect('group_detail', pk=group.pk)

    members = GroupMembership.objects.filter(group=group).select_related('user')
    is_only_member = bool(membership and not members.exclude(pk=membership.pk).exists())
    leave_blocked = bool(membership and not is_only_member and _is_last_group_admin(membership))

    expenses_qs = (
        group.expenses
        .select_related('paid_by', 'created_by')
        .prefetch_related('splits__user')
    )

    expense_items = []
    total_group_amount = Decimal('0.00')
    total_to_pay_by_user = Decimal('0.00')

    for exp in expenses_qs:
        status_label, user_split = _user_participation_status(request.user, exp)
        paid_splits_count = sum(1 for s in exp.splits.all() if s.is_paid)
        total_splits_count = len(exp.splits.all())
        can_manage = _can_manage_expense(request.user, exp, group, membership)

        total_group_amount += exp.amount
        if status_label == 'A pagar' and user_split is not None:
            total_to_pay_by_user += user_split.amount_owed

        expense_items.append({
            'expense': exp,
            'user_status': status_label,
            'user_split': user_split,
            'paid_splits_count': paid_splits_count,
            'total_splits_count': total_splits_count,
            'can_manage': can_manage,
        })

    return render(request, 'expenses/group_detail.html', {
        'group': group,
        'members': members,
        'is_admin': user_is_group_admin,
        'is_only_member': is_only_member,
        'leave_blocked': leave_blocked,
        'expense_items': expense_items,
        'total_group_amount': total_group_amount,
        'total_to_pay_by_user': total_to_pay_by_user,
    })


@login_required
@require_POST
def member_action(request, group_id, membership_id):
    group = get_object_or_404(Group, pk=group_id)
    user_membership = _get_accepted_membership(request.user, group)

    if not (user_membership and user_membership.is_accepted and user_membership.is_group_admin):
        messages.error(request, 'Ação restrita aos administradores do grupo.')
        return redirect('group_detail', pk=group.pk)

    target_membership = get_object_or_404(GroupMembership, pk=membership_id, group=group)
    action = request.POST.get('action')

    if action == 'accept':
        target_membership.is_accepted = True
        target_membership.save()
        messages.success(request, f'Membro {target_membership.user.username} aceito no grupo.')
    elif action == 'promote':
        target_membership.is_group_admin = True
        target_membership.save()
        messages.success(request, f'Membro {target_membership.user.username} promovido a administrador.')
    elif action == 'demote':
        if _is_last_group_admin(target_membership):
            messages.error(request, 'O último administrador não pode perder o cargo.')
        else:
            target_membership.is_group_admin = False
            target_membership.save()
            messages.success(request, f'Membro {target_membership.user.username} rebaixado a usuário comum.')
    elif action == 'kick':
        if _is_last_group_admin(target_membership):
            messages.error(request, 'O último administrador não pode ser removido.')
        else:
            target_membership.delete()
            messages.success(request, 'Membro removido do grupo.')

    return redirect('group_detail', pk=group.pk)


@login_required
@require_POST
@transaction.atomic
def group_leave(request, pk):
    group = get_object_or_404(Group.objects.select_for_update(), pk=pk)
    membership = get_object_or_404(GroupMembership, user=request.user, group=group)

    if not GroupMembership.objects.filter(group=group).exclude(pk=membership.pk).exists():
        if request.POST.get('confirm_delete') != 'yes':
            messages.warning(request, 'Confirme a exclusão permanente do grupo e de todas as despesas para sair.')
            return redirect('group_detail', pk=group.pk)
        group.delete()
        messages.success(request, 'Você saiu do grupo. O grupo e todos os dados associados foram excluídos permanentemente.')
        return redirect('group_list')

    if _is_last_group_admin(membership):
        messages.warning(request, 'Você é o último administrador deste grupo. Promova outro participante a administrador antes de sair.')
        return redirect('group_detail', pk=group.pk)
    else:
        membership.delete()
        messages.success(request, 'Você saiu do grupo com sucesso.')
    return redirect('group_list')


@login_required
def expense_list_all(request):
    user_groups = Group.objects.filter(
        groupmembership__user=request.user,
        groupmembership__is_accepted=True,
        is_active=True
    )
    expenses_qs = (
        Expense.objects.filter(group__in=user_groups)
        .select_related('group', 'paid_by', 'created_by')
        .prefetch_related('splits__user')
    )
    items = []
    for exp in expenses_qs:
        status_label, user_split = _user_participation_status(request.user, exp)
        items.append({
            'expense': exp,
            'user_status': status_label,
            'user_split': user_split,
        })
    return render(request, 'expenses/expense_list_all.html', {'expense_items': items})


@login_required
def expense_create(request, group_id):
    group = get_object_or_404(Group, pk=group_id, is_active=True)
    membership = _get_accepted_membership(request.user, group)

    if not membership and not request.user.is_superuser:
        messages.error(request, 'Apenas membros aceitos do grupo podem criar despesas.')
        return redirect('group_list')

    accepted_memberships = list(
        GroupMembership.objects.filter(group=group, is_accepted=True).select_related('user')
    )

    if request.method == 'POST':
        form = ExpenseForm(request.POST, group=group)
        total_amount = _extract_post_total_amount(request.POST, form)
        splits_data, split_errors = parse_splits_from_post(
            request.POST, accepted_memberships, total_amount=total_amount
        )

        if form.is_valid() and not split_errors:
            try:
                with transaction.atomic():
                    expense = form.save(commit=False)
                    expense.group = group
                    expense.created_by = request.user
                    expense.save()

                    for uid, amount_owed in splits_data.items():
                        ExpenseSplit.objects.create(
                            expense=expense,
                            user_id=uid,
                            amount_owed=amount_owed,
                            is_paid=False,
                        )
                messages.success(request, f'Despesa "{expense.title}" criada com sucesso!')
                return redirect('expense_detail', pk=expense.pk)
            except Exception as exc:
                messages.error(request, f'Erro ao salvar despesa: {exc}')
        else:
            for err in split_errors:
                messages.error(request, err)
    else:
        initial = {'paid_by': request.user.pk} if membership else {}
        form = ExpenseForm(group=group, initial=initial)
        splits_data = {}

    participant_rows = []
    for m in accepted_memberships:
        uid = m.user_id
        is_checked = (uid in splits_data) if request.method == 'POST' else True
        amount_val = splits_data.get(uid)
        amount_str = f'{amount_val:.2f}' if amount_val is not None else ''
        participant_rows.append({
            'user': m.user,
            'checked': is_checked,
            'amount': amount_str,
        })

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'group': group,
        'participant_rows': participant_rows,
        'is_edit': False,
    })


@login_required
def expense_detail(request, pk):
    expense = get_object_or_404(
        Expense.objects.select_related('group', 'paid_by', 'created_by').prefetch_related('splits__user'),
        pk=pk
    )
    group = expense.group
    membership = _get_accepted_membership(request.user, group)

    if not membership and not request.user.is_superuser:
        messages.error(request, 'Você não tem permissão para visualizar esta despesa.')
        return redirect('group_list')

    can_manage = _can_manage_expense(request.user, expense, group, membership)
    user_status, user_split = _user_participation_status(request.user, expense)

    splits_with_perms = []
    for s in expense.splits.all():
        can_toggle = _can_toggle_split(request.user, s, membership)
        splits_with_perms.append({
            'split': s,
            'can_toggle': can_toggle,
        })

    total_splits = sum((s.amount_owed for s in expense.splits.all()), Decimal('0.00'))
    paid_total = sum((s.amount_owed for s in expense.splits.all() if s.is_paid), Decimal('0.00'))
    remaining_total = total_splits - paid_total

    return render(request, 'expenses/expense_detail.html', {
        'expense': expense,
        'group': group,
        'can_manage': can_manage,
        'user_status': user_status,
        'user_split': user_split,
        'splits_with_perms': splits_with_perms,
        'total_splits': total_splits,
        'paid_total': paid_total,
        'remaining_total': remaining_total,
    })


@login_required
def expense_update(request, pk):
    expense = get_object_or_404(
        Expense.objects.select_related('group', 'paid_by', 'created_by').prefetch_related('splits__user'),
        pk=pk
    )
    group = expense.group
    membership = _get_accepted_membership(request.user, group)

    if not _can_manage_expense(request.user, expense, group, membership):
        messages.error(request, 'Apenas o criador da despesa, quem pagou ou administradores podem editá-la.')
        return redirect('expense_detail', pk=expense.pk)

    accepted_memberships = list(
        GroupMembership.objects.filter(group=group, is_accepted=True).select_related('user')
    )
    existing_splits_map = {s.user_id: s for s in expense.splits.all()}

    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense, group=group)
        total_amount = _extract_post_total_amount(request.POST, form)
        splits_data, split_errors = parse_splits_from_post(
            request.POST, accepted_memberships, total_amount=total_amount
        )

        if form.is_valid() and not split_errors:
            try:
                with transaction.atomic():
                    updated_expense = form.save(commit=False)
                    updated_expense.group = group
                    updated_expense.save()

                    for uid, existing_split in existing_splits_map.items():
                        if uid not in splits_data:
                            existing_split.delete()

                    for uid, amount_owed in splits_data.items():
                        if uid in existing_splits_map:
                            s = existing_splits_map[uid]
                            s.amount_owed = amount_owed
                            s.save()
                        else:
                            ExpenseSplit.objects.create(
                                expense=updated_expense,
                                user_id=uid,
                                amount_owed=amount_owed,
                                is_paid=False,
                            )

                messages.success(request, f'Despesa "{updated_expense.title}" atualizada com sucesso!')
                return redirect('expense_detail', pk=updated_expense.pk)
            except Exception as exc:
                messages.error(request, f'Erro ao atualizar despesa: {exc}')
        else:
            for err in split_errors:
                messages.error(request, err)
                
    else:
        form = ExpenseForm(instance=expense, group=group)
        splits_data = {uid: s.amount_owed for uid, s in existing_splits_map.items()}

    participant_rows = []
    for m in accepted_memberships:
        uid = m.user_id
        if request.method == 'POST':
            is_checked = uid in splits_data
            amount_val = splits_data.get(uid)
        else:
            is_checked = uid in existing_splits_map
            amount_val = existing_splits_map[uid].amount_owed if uid in existing_splits_map else None

        amount_str = f'{amount_val:.2f}' if amount_val is not None else ''
        participant_rows.append({
            'user': m.user,
            'checked': is_checked,
            'amount': amount_str,
        })

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'group': group,
        'expense': expense,
        'participant_rows': participant_rows,
        'is_edit': True,
    })


@login_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense.objects.select_related('group', 'paid_by', 'created_by'), pk=pk)
    group = expense.group
    membership = _get_accepted_membership(request.user, group)

    if not _can_manage_expense(request.user, expense, group, membership):
        messages.error(request, 'Apenas o criador da despesa, quem pagou ou administradores podem excluí-la.')
        return redirect('expense_detail', pk=expense.pk)

    if request.method == 'POST':
        title = expense.title
        expense.delete()
        messages.success(request, f'Despesa "{title}" excluída com sucesso.')
        return redirect('group_detail', pk=group.pk)

    return render(request, 'expenses/expense_confirm_delete.html', {
        'expense': expense,
        'group': group,
    })


@login_required
def split_toggle_paid(request, split_id):
    if request.method != 'POST':
        return redirect('group_list')

    split = get_object_or_404(
        ExpenseSplit.objects.select_related('expense__group', 'expense__paid_by', 'expense__created_by', 'user'),
        pk=split_id
    )
    expense = split.expense
    group = expense.group
    membership = _get_accepted_membership(request.user, group)

    if not _can_toggle_split(request.user, split, membership):
        messages.error(request, 'Você não tem permissão para alterar o pagamento desta divisão.')
        return redirect('expense_detail', pk=expense.pk)

    split.is_paid = not split.is_paid
    split.save()

    status_txt = 'Paga' if split.is_paid else 'A pagar'
    messages.success(request, f'Divisão de {split.user.username} marcada como "{status_txt}".')

    next_url = request.POST.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect('expense_detail', pk=expense.pk)
