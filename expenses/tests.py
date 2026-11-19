from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
from django.test import Client, TestCase

from accounts.models import CustomUser
from .models import Group, GroupMembership, Expense, ExpenseSplit


class GroupModelTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='gustavo', password='senha-forte-123')

    def test_gera_codigo_de_convite_automaticamente(self):
        group = Group.objects.create(name='Viagem', created_by=self.user)
        self.assertEqual(len(group.invite_code), 6)
        self.assertTrue(group.invite_code.isalnum())
        membership = GroupMembership.objects.get(group=group, user=self.user)
        self.assertTrue(membership.is_accepted)
        self.assertTrue(membership.is_group_admin)

    def test_atualizar_criador_nao_cria_associacao_administrativa(self):
        new_creator = CustomUser.objects.create_user(username='novo_criador', password='senha-forte-123')
        group = Group.objects.create(name='Viagem', created_by=self.user)
        group.created_by = new_creator
        group.save()

        self.assertFalse(GroupMembership.objects.filter(group=group, user=new_creator).exists())
        self.assertTrue(GroupMembership.objects.filter(group=group, user=self.user).exists())

    def test_mantem_codigo_de_convite_informado(self):
        group = Group.objects.create(name='Viagem', created_by=self.user, invite_code='RJ2026')
        self.assertEqual(group.invite_code, 'RJ2026')

    def test_codigos_gerados_sao_unicos(self):
        codes = {Group.objects.create(name=f'Grupo {i}', created_by=self.user).invite_code for i in range(20)}
        self.assertEqual(len(codes), 20)


class GroupMembershipModelTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='gustavo', password='senha-forte-123')
        self.group = Group.objects.create(name='República', created_by=self.user)

    def test_impede_membro_duplicado_no_mesmo_grupo(self):
        invited_user = CustomUser.objects.create_user(username='convidado', password='senha-forte-123')
        GroupMembership.objects.create(user=invited_user, group=self.group)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GroupMembership.objects.create(user=invited_user, group=self.group)

    def test_membro_nao_aceito_por_padrao(self):
        user = CustomUser.objects.create_user(username='convidado', password='senha-forte-123')
        membership = GroupMembership.objects.create(user=user, group=self.group)
        self.assertFalse(membership.is_accepted)
        self.assertFalse(membership.is_group_admin)

    def test_membro_pendente_nao_pode_ser_administrador(self):
        user = CustomUser.objects.create_user(username='pendente', password='senha-forte-123')
        membership = GroupMembership(user=user, group=self.group, is_group_admin=True, is_accepted=False)
        with self.assertRaises(ValidationError):
            membership.full_clean()
        with self.assertRaises(ValidationError):
            membership.save()

    def test_criador_pode_deixar_de_ser_membro_aceito_e_administrador(self):
        membership = GroupMembership.objects.get(user=self.user, group=self.group)
        membership.is_accepted = False
        membership.is_group_admin = False
        membership.save()
        membership.refresh_from_db()
        self.assertFalse(membership.is_accepted)
        self.assertFalse(membership.is_group_admin)


class ExpenseModelTests(TestCase):
    def setUp(self):
        self.payer = CustomUser.objects.create_user(username='gustavo', password='senha-forte-123')
        self.debtor = CustomUser.objects.create_user(username='diego', password='senha-forte-123')
        self.group = Group.objects.create(name='Churrasco', created_by=self.payer)
        GroupMembership.objects.create(user=self.debtor, group=self.group, is_accepted=True)
        self.expense = Expense.objects.create(
            group=self.group,
            paid_by=self.payer,
            created_by=self.payer,
            title='Carnes',
            amount=Decimal('150.00'),
            date=date(2026, 11, 1),
        )

    def test_representacao_textual(self):
        self.assertEqual(str(self.expense), 'Carnes - R$ 150.00')

    def test_rejeita_valor_nao_positivo(self):
        self.expense.amount = Decimal('0.00')
        with self.assertRaises(ValidationError):
            self.expense.save()

    def test_pagador_e_cadastrador_precisam_ser_membros_aceitos(self):
        outsider = CustomUser.objects.create_user(username='externo', password='senha-forte-123')
        for field in ('paid_by', 'created_by'):
            expense = Expense.objects.get(pk=self.expense.pk)
            setattr(expense, field, outsider)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                expense.save()

    def test_alteracao_do_grupo_nao_pode_manter_pagador_externo(self):
        other_group = Group.objects.create(name='Outro', created_by=self.debtor)
        self.expense.group = other_group
        with self.assertRaises(ValidationError):
            self.expense.save()

    def test_rejeita_divisao_para_membro_pendente_ou_externo(self):
        outsider = CustomUser.objects.create_user(username='externo', password='senha-forte-123')
        split = ExpenseSplit(expense=self.expense, user=outsider, amount_owed=Decimal('10.00'))
        with self.assertRaises(ValidationError):
            split.save()

        pending = CustomUser.objects.create_user(username='pendente', password='senha-forte-123')
        GroupMembership.objects.create(user=pending, group=self.group)
        split.user = pending
        with self.assertRaises(ValidationError):
            split.save()

    def test_rejeita_valor_de_divisao_nao_positivo(self):
        split = ExpenseSplit(expense=self.expense, user=self.debtor, amount_owed=Decimal('0.00'))
        with self.assertRaises(ValidationError):
            split.save()

    def test_admin_formulario_de_despesa_rejeita_pagador_externo(self):
        outsider = CustomUser.objects.create_user(username='externo', password='senha-forte-123')
        request = RequestFactory().get('/admin/expenses/expense/add/')
        request.user = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='admin'
        )
        model_admin = admin.site._registry[Expense]
        form_class = model_admin.get_form(request)
        form = form_class(data={
            'group': self.group.pk,
            'paid_by': outsider.pk,
            'created_by': self.payer.pk,
            'title': 'Compra',
            'description': '',
            'amount': '25.00',
            'date': '2026-11-01',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('paid_by', form.errors)

    def test_admin_inline_rejeita_divisao_de_participante_externo(self):
        from .admin import ExpenseSplitInline

        outsider = CustomUser.objects.create_user(username='externo', password='senha-forte-123')
        request = RequestFactory().get(f'/admin/expenses/expense/{self.expense.pk}/change/')
        request.user = CustomUser.objects.create_superuser(
            username='admin', email='admin@example.com', password='admin'
        )
        inline = ExpenseSplitInline(Expense, admin.site)
        formset_class = inline.get_formset(request, self.expense)
        formset = formset_class(data={
            'splits-TOTAL_FORMS': '1',
            'splits-INITIAL_FORMS': '0',
            'splits-MIN_NUM_FORMS': '0',
            'splits-MAX_NUM_FORMS': '1000',
            'splits-0-user': outsider.pk,
            'splits-0-amount_owed': '10.00',
            'splits-0-is_paid': '',
        }, instance=self.expense)
        self.assertFalse(formset.is_valid())
        self.assertIn('user', formset.forms[0].errors)

    def test_impede_divisao_duplicada_para_o_mesmo_usuario(self):
        ExpenseSplit.objects.create(expense=self.expense, user=self.debtor, amount_owed=Decimal('75.00'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExpenseSplit.objects.create(expense=self.expense, user=self.debtor, amount_owed=Decimal('75.00'))

    def test_exclusao_da_despesa_remove_divisoes(self):
        ExpenseSplit.objects.create(expense=self.expense, user=self.debtor, amount_owed=Decimal('75.00'))
        self.expense.delete()
        self.assertFalse(ExpenseSplit.objects.exists())


class AdminFiltersTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(username='admin', email='admin@split.com', password='admin', role='ADMIN')
        self.user = CustomUser.objects.create_user(username='gustavo', password='senha-forte-123')
        self.group = Group.objects.create(name='Supermercado', created_by=self.user)
        self.cheap = Expense.objects.create(group=self.group, paid_by=self.user, created_by=self.user, title='Pão', amount=Decimal('20.00'), date=date(2026, 11, 1))
        self.expensive = Expense.objects.create(group=self.group, paid_by=self.user, created_by=self.user, title='Compra do mês', amount=Decimal('450.00'), date=date(2026, 11, 2))
        ExpenseSplit.objects.create(expense=self.expensive, user=self.user, amount_owed=Decimal('450.00'), is_paid=True)
        self.client.force_login(self.admin)

    def results(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return list(response.context['cl'].result_list)

    def test_filtro_faixa_de_valor(self):
        self.assertEqual(self.results('/admin/expenses/expense/?faixa_valor=ate_50'), [self.cheap])
        self.assertEqual(self.results('/admin/expenses/expense/?faixa_valor=acima_200'), [self.expensive])

    def test_filtro_situacao_da_divisao(self):
        self.assertEqual(self.results('/admin/expenses/expense/?situacao=quitada'), [self.expensive])
        self.assertEqual(self.results('/admin/expenses/expense/?situacao=sem_divisao'), [self.cheap])
        self.assertEqual(self.results('/admin/expenses/expense/?situacao=pendente'), [])

    def test_filtro_grupo_possui_despesas(self):
        empty_group = Group.objects.create(name='Vazio', created_by=self.user)
        self.assertEqual(self.results('/admin/expenses/group/?possui_despesas=sim'), [self.group])
        self.assertEqual(self.results('/admin/expenses/group/?possui_despesas=nao'), [empty_group])

    def test_filtro_participacao_em_grupos(self):
        self.assertEqual(self.results('/admin/accounts/customuser/?participa_grupos=sim'), [self.user])
        self.assertEqual(self.results('/admin/accounts/customuser/?participa_grupos=nao'), [self.admin])

    def test_grafico_de_grupos_reflete_queryset_filtrado(self):
        Group.objects.create(name='Inativo', created_by=self.user, is_active=False)
        response = self.client.get('/admin/expenses/group/?is_active__exact=0')
        self.assertEqual(response.status_code, 200)
        chart_records = response.context['groups_json']
        self.assertEqual(len(chart_records), response.context['cl'].queryset.count())
        self.assertEqual(len(chart_records), 1)
        self.assertEqual(set(chart_records[0]), {'created_at'})
        self.assertRegex(chart_records[0]['created_at'], r'^\d{4}-\d{2}-\d{2}$')
        unfiltered = self.client.get('/admin/expenses/group/')
        self.assertEqual(len(unfiltered.context['groups_json']), unfiltered.context['cl'].queryset.count())
        self.assertEqual(len(unfiltered.context['groups_json']), 2)

    def test_grafico_de_despesas_reflete_queryset_filtrado(self):
        response = self.client.get('/admin/expenses/expense/?faixa_valor=ate_50')
        self.assertEqual(response.status_code, 200)
        chart_records = response.context['expenses_json']
        self.assertEqual(len(chart_records), response.context['cl'].queryset.count())
        self.assertEqual(len(chart_records), 1)
        self.assertEqual(set(chart_records[0]), {'created_at'})
        self.assertRegex(chart_records[0]['created_at'], r'^\d{4}-\d{2}-\d{2}$')
        unfiltered = self.client.get('/admin/expenses/expense/')
        self.assertEqual(len(unfiltered.context['expenses_json']), unfiltered.context['cl'].queryset.count())
        self.assertEqual(len(unfiltered.context['expenses_json']), 2)


class GroupAdministrationTests(TestCase):
    def setUp(self):
        self.creator = CustomUser.objects.create_user(username='criador')
        self.other = CustomUser.objects.create_user(username='outro')
        self.group = Group.objects.create(name='Grupo', created_by=self.creator)
        self.creator_membership = GroupMembership.objects.get(group=self.group, user=self.creator)
        self.other_membership = GroupMembership.objects.create(
            group=self.group, user=self.other, is_accepted=True,
        )
        self.client.force_login(self.creator)
        self.leave_url = reverse('group_leave', args=[self.group.pk])
        self.action_url = reverse(
            'member_action', args=[self.group.pk, self.creator_membership.pk],
        )

    def add_other_admin(self):
        self.other_membership.is_group_admin = True
        self.other_membership.save()

    def test_criador_pode_sair_com_outro_administrador(self):
        self.add_other_admin()
        response = self.client.post(self.leave_url)
        self.assertRedirects(response, reverse('group_list'))
        self.assertFalse(GroupMembership.objects.filter(pk=self.creator_membership.pk).exists())
        self.group.refresh_from_db()
        self.assertEqual(self.group.created_by, self.creator)

    def test_ultimo_administrador_nao_pode_sair(self):
        response = self.client.post(self.leave_url, {'confirm_delete': 'yes'}, follow=True)
        self.assertTrue(GroupMembership.objects.filter(pk=self.creator_membership.pk).exists())
        self.assertContains(response, 'alert alert-warning')
        self.assertContains(response, 'Você é o último administrador deste grupo. Promova outro participante a administrador antes de sair.')

    def test_unico_membro_precisa_confirmar_exclusao(self):
        self.other_membership.delete()
        response = self.client.post(self.leave_url, follow=True)
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())
        self.assertTrue(GroupMembership.objects.filter(pk=self.creator_membership.pk).exists())
        self.assertContains(response, 'name="confirm_delete"')
        self.assertContains(response, 'O grupo e todas as despesas serão excluídos permanentemente. Deseja confirmar?')
        self.assertNotContains(response, 'type="checkbox"')

    def test_unico_membro_pode_sair_excluindo_grupo_e_despesas(self):
        self.other_membership.delete()
        expense = Expense.objects.create(
            group=self.group, paid_by=self.creator, created_by=self.creator,
            title='Compra', amount=Decimal('10.00'), date=date(2026, 11, 19),
        )
        split = ExpenseSplit.objects.create(
            expense=expense, user=self.creator, amount_owed=Decimal('10.00'),
        )
        response = self.client.post(self.leave_url, {'confirm_delete': 'yes'})
        self.assertRedirects(response, reverse('group_list'))
        self.assertFalse(Group.objects.filter(pk=self.group.pk).exists())
        self.assertFalse(GroupMembership.objects.filter(group_id=self.group.pk).exists())
        self.assertFalse(Expense.objects.filter(pk=expense.pk).exists())
        self.assertFalse(ExpenseSplit.objects.filter(pk=split.pk).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.creator.pk).exists())

    def test_vinculo_pendente_impede_exclusao_do_grupo(self):
        self.other_membership.is_accepted = False
        self.other_membership.save()
        response = self.client.post(self.leave_url, {'confirm_delete': 'yes'}, follow=True)
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())
        self.assertEqual(GroupMembership.objects.filter(group=self.group).count(), 2)
        self.assertContains(response, 'alert alert-warning')
        self.assertNotContains(response, 'name="confirm_delete"')

    def test_get_nao_exclui_grupo_com_unico_membro(self):
        self.other_membership.delete()
        response = self.client.get(self.leave_url, {'confirm_delete': 'yes'})
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())

    def test_exclusao_exige_csrf(self):
        self.other_membership.delete()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.creator)
        response = client.post(self.leave_url, {'confirm_delete': 'yes'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())

    def test_ultimo_administrador_nao_pode_ser_removido_ou_rebaixado(self):
        for action in ('kick', 'demote'):
            with self.subTest(action=action):
                self.client.post(self.action_url, {'action': action})
                self.creator_membership.refresh_from_db()
                self.assertTrue(self.creator_membership.is_group_admin)
                self.assertTrue(self.creator_membership.is_accepted)

    def test_criador_pode_ser_rebaixado_com_outro_administrador(self):
        self.add_other_admin()
        self.client.force_login(self.other)
        self.client.post(self.action_url, {'action': 'demote'})
        self.creator_membership.refresh_from_db()
        self.assertFalse(self.creator_membership.is_group_admin)
        self.group.save()
        self.creator_membership.refresh_from_db()
        self.assertFalse(self.creator_membership.is_group_admin)

    def test_atualizar_grupo_nao_readiciona_criador_que_saiu(self):
        self.add_other_admin()
        self.client.post(self.leave_url)
        self.group.description = 'Descrição atualizada'
        self.group.save()
        self.assertFalse(GroupMembership.objects.filter(group=self.group, user=self.creator).exists())

    def test_get_nao_executa_operacoes(self):
        self.add_other_admin()
        response = self.client.get(self.leave_url)
        self.assertEqual(response.status_code, 405)
        for action in ('accept', 'promote', 'demote', 'kick'):
            with self.subTest(action=action):
                response = self.client.get(self.action_url, {'action': action})
                self.assertEqual(response.status_code, 405)
                self.creator_membership.refresh_from_db()
                self.assertTrue(self.creator_membership.is_group_admin)
                self.assertTrue(self.creator_membership.is_accepted)

    def test_criador_sem_cargo_nao_pode_administrar(self):
        self.add_other_admin()
        self.creator_membership.is_group_admin = False
        self.creator_membership.save()
        self.client.post(self.action_url, {'action': 'promote'})
        self.creator_membership.refresh_from_db()
        self.assertFalse(self.creator_membership.is_group_admin)

    def test_interface_permite_sair_e_alterar_cargo_do_criador(self):
        response = self.client.get(reverse('group_detail', args=[self.group.pk]))
        self.assertContains(response, 'Sair do Grupo')
        self.add_other_admin()
        self.client.force_login(self.other)
        response = self.client.get(reverse('group_detail', args=[self.group.pk]))
        self.assertContains(response, 'value="demote"')
        self.assertContains(response, 'value="kick"')


class ExpenseAccessTests(TestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(username='owner')
        self.admin = CustomUser.objects.create_user(username='admin2')
        self.group = Group.objects.create(name='Grupo', created_by=self.admin)
        self.membership = GroupMembership.objects.create(group=self.group, user=self.owner, is_accepted=True)
        self.expense = Expense.objects.create(group=self.group, paid_by=self.owner, created_by=self.owner, title='Compra', amount=Decimal('10.00'), date=date(2026, 11, 19))
        self.split = ExpenseSplit.objects.create(expense=self.expense, user=self.owner, amount_owed=Decimal('10.00'))
        self.client.force_login(self.owner)

    def test_ex_membro_e_pendente_nao_podem_alterar_despesa_ou_pagamento(self):
        self.membership.delete()
        for pending in (False, True):
            if pending:
                GroupMembership.objects.create(group=self.group, user=self.owner, is_accepted=False)
            for url in (reverse('expense_update', args=[self.expense.pk]), reverse('expense_delete', args=[self.expense.pk]), reverse('split_toggle_paid', args=[self.split.pk])):
                self.client.post(url, {})
            self.expense.refresh_from_db()
            self.split.refresh_from_db()
            self.assertFalse(self.split.is_paid)
            self.assertEqual(self.expense.title, 'Compra')

    def test_membro_autorizado_pode_editar_alterar_pagamento_e_excluir(self):
        data = {'title': 'Alterada', 'amount': '10.00', 'date': '2026-11-19', 'paid_by': self.owner.pk, f'split_participates_{self.owner.pk}': 'on', f'split_amount_{self.owner.pk}': '10.00'}
        self.client.post(reverse('expense_update', args=[self.expense.pk]), data)
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.title, 'Alterada')
        self.client.post(reverse('split_toggle_paid', args=[self.split.pk]))
        self.split.refresh_from_db()
        self.assertTrue(self.split.is_paid)
        self.client.post(reverse('expense_delete', args=[self.expense.pk]))
        self.assertFalse(Expense.objects.filter(pk=self.expense.pk).exists())

    def test_superusuario_sem_vinculo_pode_alterar_pagamento_e_excluir(self):
        user = CustomUser.objects.create_superuser(username='super', password='senha')
        self.client.force_login(user)
        self.client.post(reverse('split_toggle_paid', args=[self.split.pk]))
        self.split.refresh_from_db()
        self.assertTrue(self.split.is_paid)
        self.client.post(reverse('expense_delete', args=[self.expense.pk]))
        self.assertFalse(Expense.objects.filter(pk=self.expense.pk).exists())
