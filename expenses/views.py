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
                # Cria o vínculo como pendente (is_accepted=False)
                membership, created = GroupMembership.objects.get_or_create(
                    user=request.user,
                    group=group,
                    defaults={'is_accepted': False, 'is_group_admin': False}
                )
                if created:
                    messages.success(request, 'Solicitação de entrada enviada ao administrador do grupo!')
                else:
                    messages.info(request, 'Você já possui um vínculo ou solicitação pendente para este grupo.')
                return redirect('group_detail', pk=group.pk)
            except Group.DoesNotExist:
                messages.error(request, 'Código de convite inválido ou grupo desativado.')
    return redirect('group_list')

@login_required
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk, is_active=True)
    
    # Garante que o usuário logado faz parte do grupo (aceito) ou é superuser
    membership = GroupMembership.objects.filter(user=request.user, group=group, is_accepted=True).first()
    if not membership and not request.user.is_superuser:
        messages.error(request, 'Você não tem permissão para acessar este grupo.')
        return redirect('group_list')

    # Trata alteração da descrição ou do código de convite pelo Admin do Grupo (com blindagem para superuser sem membership)
    if request.method == 'POST' and ((membership and membership.is_group_admin) or request.user.is_superuser):
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
        'is_admin': membership.is_group_admin if membership else True
    })

@login_required
def member_action(request, group_id, membership_id):
    group = get_object_or_404(Group, pk=group_id)
    user_membership = GroupMembership.objects.filter(user=request.user, group=group, is_accepted=True).first()
    
    # Valida se quem está requisitando é admin do grupo ou superuser
    is_group_admin = user_membership.is_group_admin if user_membership else False
    if not is_group_admin and not request.user.is_superuser:
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