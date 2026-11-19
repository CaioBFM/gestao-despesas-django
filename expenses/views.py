from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Group, GroupMembership
from .forms import GroupForm, JoinGroupForm

@login_required
def group_list(request):
    # Lista apenas os grupos em que o usuário faz parte (e teve a entrada aceita)
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
    
    # Verifica se o usuário é membro aceito ou superuser
    membership = GroupMembership.objects.filter(user=request.user, group=group, is_accepted=True).first()
    if not membership and not request.user.is_superuser:
        messages.error(request, 'Você não tem permissão para acessar este grupo.')
        return redirect('group_list')

    # Define se o usuário é admin: se for superuser do sistema OU admin do grupo
    user_is_group_admin = True if request.user.is_superuser else (membership.is_group_admin if membership else False)

    # Trata alteração da descrição ou do código de convite
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

    members = GroupMembership.objects.filter(group=group)
    return render(request, 'expenses/group_detail.html', {
        'group': group,
        'members': members,
        'is_admin': user_is_group_admin
    })

@login_required
def member_action(request, group_id, membership_id):
    group = get_object_or_404(Group, pk=group_id)
    user_membership = GroupMembership.objects.filter(user=request.user, group=group, is_accepted=True).first()
    
    # Valida se quem está requisitando é admin do grupo ou superuser do sistema
    user_is_group_admin = True if request.user.is_superuser else (user_membership.is_group_admin if user_membership else False)
    if not user_is_group_admin:
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
        # Impede rebaixar o criador do grupo
        if target_membership.user == group.created_by:
            messages.error(request, 'O criador do grupo não pode deixar de ser administrador.')
        else:
            target_membership.is_group_admin = False
            target_membership.save()
            messages.success(request, f'Membro {target_membership.user.username} rebaixado a usuário comum.')
    elif action == 'kick':
        if target_membership.user == group.created_by:
            messages.error(request, 'O criador do grupo não pode ser removido.')
        else:
            target_membership.delete()
            messages.success(request, 'Membro removido do grupo.')

    return redirect('group_detail', pk=group.pk)

@login_required
def group_leave(request, pk):
    group = get_object_or_404(Group, pk=pk)
    membership = get_object_or_404(GroupMembership, user=request.user, group=group)
    
    if request.user == group.created_by:
        messages.error(request, 'O criador não pode sair do próprio grupo.')
    else:
        membership.delete()
        messages.success(request, 'Você saiu do grupo com sucesso.')
    return redirect('group_list')