from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, F, Q, Sum

from expenses.models import Expense, ExpenseSplit, Group
from .forms import CadastroForm, UserProfileForm, AddFriendForm
from .models import CustomUser, Friendship
from .services import get_friends_queryset


# GET: página inicial com o resumo financeiro do usuário
@login_required
@require_GET
def pagina_inicial(request):
    grupos = Group.objects.filter(
        groupmembership__user=request.user,
        groupmembership__is_accepted=True,
    )

    divisoes_pendentes = ExpenseSplit.objects.filter(
        expense__group__in=grupos,
        is_paid=False,
    )

    # Soma o que o usuário deve aos outros (exclui a cota do próprio pagador)
    total_devido = (
        divisoes_pendentes
        .filter(user=request.user)
        .exclude(expense__paid_by=request.user)
        .aggregate(total=Sum("amount_owed", default=Decimal("0.00")))["total"]
    )

    # Soma o que os outros devem ao usuário
    total_receber = (
        divisoes_pendentes
        .filter(expense__paid_by=request.user)
        .exclude(user=request.user)
        .aggregate(total=Sum("amount_owed", default=Decimal("0.00")))["total"]
    )

    contexto = {
        "resumo_disponivel": True,
        "total_devido": total_devido,
        "total_receber": total_receber,
        "grupos_recentes": grupos.order_by("-created_at")[:4],
        "despesas_recentes": (
            Expense.objects
            .filter(group__in=grupos)
            .select_related("group")[:5]
        ),
    }

    return render(request, "index.html", contexto)


# GET: exibe o formulário | POST: cria uma conta de usuário comum
@require_http_methods(['GET', 'POST'])
def cadastro(request):
    if request.user.is_authenticated:
        return redirect("inicio")

    if request.method == "POST":
        form = CadastroForm(request.POST)

        if form.is_valid():
            user = form.save(commit=False)
            # Cadastro público nunca cria administradores
            user.role = "USER"
            user.is_staff = False
            user.is_superuser = False
            user.save()

            return redirect("login")
    else:
        form = CadastroForm()

    return render(request, "accounts/cadastro.html", {"form": form})


# GET: exibe o perfil | POST: atualiza nome, sobrenome e e-mail
@login_required
@require_http_methods(['GET', 'POST'])
def perfil_usuario(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil atualizado com sucesso.')
            return redirect('perfil')
    else:
        form = UserProfileForm(instance=request.user)
    return render(request, 'accounts/perfil.html', {'form': form})


# GET: lista amigos e solicitações | POST: envia uma solicitação de amizade pelo username
@login_required
@require_http_methods(['GET', 'POST'])
def friends_list(request):
    if request.method == 'POST':
        form = AddFriendForm(request.POST)
        if form.is_valid():
            target_username = form.cleaned_data['username'].strip()
            if target_username.lower() == request.user.username.lower():
                messages.error(request, 'Você não pode adicionar a si mesmo como amigo.')
                return redirect('friends_list')

            target_user = CustomUser.objects.filter(
                username__iexact=target_username,
                is_active=True,
            ).first()
            if not target_user:
                messages.error(request, f'Usuário "{target_username}" não encontrado.')
                return redirect('friends_list')

            # Procura qualquer solicitação já existente entre os dois (em qualquer direção)
            existing = Friendship.objects.filter(
                Q(from_user=request.user, to_user=target_user)
                | Q(from_user=target_user, to_user=request.user)
            ).first()

            if existing:
                if existing.status == Friendship.STATUS_ACCEPTED:
                    messages.info(request, f'Você e {target_user.username} já são amigos.')
                elif existing.to_user_id == request.user.pk:
                    # Solicitação recíproca: aceita a que já estava pendente
                    existing.status = Friendship.STATUS_ACCEPTED
                    existing.save(update_fields=['status', 'updated_at'])
                    messages.success(request, f'Você agora é amigo de {target_user.username}!')
                else:
                    messages.info(request, f'Solicitação de amizade para {target_user.username} já está pendente.')
            else:
                Friendship.objects.create(
                    from_user=request.user,
                    to_user=target_user,
                    status=Friendship.STATUS_PENDING,
                )
                messages.success(request, f'Solicitação de amizade enviada para {target_user.username}.')

            return redirect('friends_list')
    else:
        form = AddFriendForm()

    incoming_requests = Friendship.objects.filter(
        to_user=request.user,
        status=Friendship.STATUS_PENDING,
    ).select_related('from_user')

    outgoing_requests = Friendship.objects.filter(
        from_user=request.user,
        status=Friendship.STATUS_PENDING,
    ).select_related('to_user')

    friends = get_friends_queryset(request.user)

    return render(request, 'accounts/friends.html', {
        'form': form,
        'incoming_requests': incoming_requests,
        'outgoing_requests': outgoing_requests,
        'friends': friends,
    })


# POST: destinatário aceita/recusa a solicitação | remetente cancela
@login_required
@require_POST
def friend_request_action(request, friendship_id):
    friendship = get_object_or_404(
        Friendship.objects.select_related('from_user', 'to_user'),
        pk=friendship_id,
        status=Friendship.STATUS_PENDING,
    )
    is_receiver = friendship.to_user_id == request.user.pk
    is_sender = friendship.from_user_id == request.user.pk

    action = request.POST.get('action')
    if action == 'accept':
        # Só quem recebeu pode aceitar
        if is_receiver:
            friendship.status = Friendship.STATUS_ACCEPTED
            friendship.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'Agora você e {friendship.from_user.username} são amigos!')
        else:
            messages.error(request, 'Apenas quem recebeu a solicitação pode aceitá-la.')
    elif action in ('reject', 'cancel'):
        # O papel do usuário define se é recusa (destinatário) ou cancelamento (remetente)
        if is_receiver:
            friendship.delete()
            messages.info(request, f'Solicitação de {friendship.from_user.username} recusada.')
        elif is_sender:
            friendship.delete()
            messages.info(request, f'Solicitação para {friendship.to_user.username} cancelada.')
        else:
            messages.error(request, 'Você não tem permissão para alterar esta solicitação.')
    else:
        messages.error(request, 'Ação inválida para esta solicitação.')

    return redirect('friends_list')


# POST: desfaz uma amizade aceita entre o usuário logado e o usuário informado
@login_required
@require_POST
def friend_remove(request, user_id):
    friend_user = get_object_or_404(CustomUser, pk=user_id)
    deleted_count, _ = Friendship.objects.filter(
        status=Friendship.STATUS_ACCEPTED,
    ).filter(
        Q(from_user=request.user, to_user=friend_user) | Q(from_user=friend_user, to_user=request.user)
    ).delete()

    if deleted_count:
        messages.success(request, f'{friend_user.username} foi removido da sua lista de amigos.')
    else:
        messages.info(request, 'Amizade não encontrada.')
    return redirect('friends_list')


# GET: relatórios gerais do sistema, restritos ao admin geral (superusuário)
@login_required
@require_GET
def relatorios(request):
    if not request.user.is_superuser:
        messages.error(request, 'Apenas o administrador geral pode acessar os relatórios.')
        return redirect('inicio')

    zero = Decimal('0.00')
    # Dívidas em aberto: divisões não pagas, sem contar a cota do próprio pagador
    pending_splits = ExpenseSplit.objects.filter(is_paid=False).exclude(user_id=F('expense__paid_by_id'))
    paid_splits = ExpenseSplit.objects.filter(is_paid=True).exclude(user_id=F('expense__paid_by_id'))

    totals = {
        'users': CustomUser.objects.filter(is_active=True).count(),
        'groups': Group.objects.filter(is_active=True).count(),
        'expenses': Expense.objects.count(),
        'amount': Expense.objects.aggregate(t=Sum('amount', default=zero))['t'],
        'pending': pending_splits.aggregate(t=Sum('amount_owed', default=zero))['t'],
        'paid': paid_splits.aggregate(t=Sum('amount_owed', default=zero))['t'],
    }

    # Totais por grupo calculados em consultas separadas para evitar soma duplicada por JOIN
    amount_by_group = {
        row['group_id']: row['t']
        for row in Expense.objects.values('group_id').annotate(t=Sum('amount'))
    }
    pending_by_group = {
        row['expense__group_id']: row['t']
        for row in pending_splits.values('expense__group_id').annotate(t=Sum('amount_owed'))
    }
    groups = Group.objects.filter(is_active=True).annotate(
        member_count=Count('groupmembership', filter=Q(groupmembership__is_accepted=True), distinct=True),
        expense_count=Count('expenses', distinct=True),
    ).order_by('name')
    group_rows = [
        {
            'group': group,
            'members': group.member_count,
            'expenses': group.expense_count,
            'amount': amount_by_group.get(group.pk, zero),
            'pending': pending_by_group.get(group.pk, zero),
        }
        for group in groups
    ]

    # Usuários com maior valor pendente a pagar
    top_debtors = (
        pending_splits.values('user__username')
        .annotate(total=Sum('amount_owed'), splits=Count('pk'))
        .order_by('-total')[:10]
    )

    return render(request, 'accounts/relatorios.html', {
        'totals': totals,
        'group_rows': group_rows,
        'top_debtors': top_debtors,
    })
