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
        self.expense = Expense.objects.create(group=self.group, paid_by=self.admin, created_by=self.owner, title='Compra', amount=Decimal('10.00'), date=date(2026, 11, 19))
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
        data = {'title': 'Alterada', 'amount': '10.00', 'date': '2026-11-19', 'paid_by': self.admin.pk, f'split_participates_{self.owner.pk}': 'on', f'split_amount_{self.owner.pk}': '10.00'}
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


class GroupFinancialDepartureTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(username='financial_admin')
        self.member = CustomUser.objects.create_user(username='financial_member')
        self.group = Group.objects.create(name='Grupo financeiro', created_by=self.admin)
        self.membership = GroupMembership.objects.create(group=self.group, user=self.member, is_accepted=True)
        self.leave = reverse('group_leave', args=[self.group.pk])
        self.kick = reverse('member_action', args=[self.group.pk, self.membership.pk])

    def make_split(self, payer, debtor):
        expense = Expense.objects.create(group=self.group, paid_by=payer, created_by=payer, title='Despesa', amount=Decimal('10.00'), date=date(2026, 11, 19))
        return ExpenseSplit.objects.create(expense=expense, user=debtor, amount_owed=Decimal('10.00'))

    def test_saida_bloqueada_por_dividas_a_pagar_e_receber(self):
        self.client.force_login(self.member)
        for payer, debtor in ((self.admin, self.member), (self.member, self.admin)):
            with self.subTest(payer=payer):
                split = self.make_split(payer, debtor)
                response = self.client.post(self.leave, follow=True)
                self.assertContains(response, 'pendências financeiras')
                self.assertTrue(GroupMembership.objects.filter(pk=self.membership.pk).exists())
                split.is_paid = True
                split.save()
        self.make_split(self.member, self.member)
        self.client.post(self.leave)
        self.assertFalse(GroupMembership.objects.filter(pk=self.membership.pk).exists())

    def test_remocao_bloqueada_por_dividas_a_pagar_e_receber(self):
        self.client.force_login(self.admin)
        for payer, debtor in ((self.admin, self.member), (self.member, self.admin)):
            with self.subTest(payer=payer):
                split = self.make_split(payer, debtor)
                response = self.client.post(self.kick, {'action': 'kick'}, follow=True)
                self.assertContains(response, 'pendências financeiras')
                self.assertTrue(GroupMembership.objects.filter(pk=self.membership.pk).exists())
                split.is_paid = True
                split.save()
        self.make_split(self.member, self.member)
        self.client.post(self.kick, {'action': 'kick'})
        self.assertFalse(GroupMembership.objects.filter(pk=self.membership.pk).exists())

    def test_unico_membro_nao_exclui_grupo_com_divida_entre_ex_membros(self):
        other = CustomUser.objects.create_user(username='former_member')
        other_membership = GroupMembership.objects.create(group=self.group, user=other, is_accepted=True)
        split = self.make_split(self.member, other)
        self.membership.delete()
        other_membership.delete()
        self.client.force_login(self.admin)
        response = self.client.post(self.leave, {'confirm_delete': 'yes'}, follow=True)
        self.assertContains(response, 'pendências financeiras')
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())
        self.assertTrue(ExpenseSplit.objects.filter(pk=split.pk).exists())
        ExpenseSplit.objects.filter(pk=split.pk).update(is_paid=True)
        self.client.post(self.leave, {'confirm_delete': 'yes'})
        self.assertFalse(Group.objects.filter(pk=self.group.pk).exists())


class SplitAmountValidationTests(TestCase):
    def setUp(self):
        self.users = [CustomUser.objects.create_user(username=f'split_user_{i}') for i in range(3)]
        self.group = Group.objects.create(name='Divisões', created_by=self.users[0])
        for user in self.users[1:]:
            GroupMembership.objects.create(group=self.group, user=user, is_accepted=True)
        self.members = list(GroupMembership.objects.filter(group=self.group))

    def parse(self, values, mode='value', total='10.00'):
        from .forms import parse_splits_from_post
        data = {'split_mode': mode}
        for user, value in zip(self.users, values):
            data[f'split_participates_{user.pk}'] = 'on'
            data[f'split_amount_{user.pk}'] = value
        return parse_splits_from_post(data, self.members, Decimal(total))

    def test_soma_monetaria_inferior_e_superior(self):
        for value in ('9.99', '10.01'):
            with self.subTest(value=value):
                self.assertTrue(self.parse([value])[1])

    def test_percentuais_diferentes_de_cem(self):
        for value in ('99.99', '100.01'):
            with self.subTest(value=value):
                self.assertTrue(self.parse([value], 'percentage')[1])

    def test_percentuais_validos_e_maiores_restos(self):
        splits, errors = self.parse(['33.33', '33.33', '33.34'], 'percentage')
        self.assertFalse(errors)
        self.assertEqual([splits[u.pk] for u in self.users], [Decimal('3.33'), Decimal('3.33'), Decimal('3.34')])
        splits, errors = self.parse(['50', '50'], 'percentage', '0.03')
        self.assertFalse(errors)
        self.assertEqual([splits[u.pk] for u in self.users[:2]], [Decimal('0.02'), Decimal('0.01')])

    def test_entradas_invalidas_e_divisao_menor_que_um_centavo(self):
        for value in ('0', '-1', 'NaN', 'Infinity', 'abc', '0.001'):
            with self.subTest(value=value):
                self.assertTrue(self.parse([value])[1])
        self.assertTrue(self.parse(['50', '50'], 'percentage', '0.01')[1])

    def test_formulario_preserva_campos_invalidos(self):
        self.client.force_login(self.users[0])
        data = {'title': 'Teste', 'amount': '10.00', 'date': '2026-11-19', 'paid_by': self.users[0].pk, 'split_mode': 'percentage', f'split_participates_{self.users[0].pk}': 'on', f'split_amount_{self.users[0].pk}': 'inválido'}
        response = self.client.post(reverse('expense_create', args=[self.group.pk]), data)
        self.assertContains(response, 'value="inválido"')
        self.assertContains(response, 'value="percentage" selected')

    def test_cria_despesa_com_percentuais_em_reais(self):
        self.client.force_login(self.users[0])
        data = {'title': 'Percentual', 'amount': '0.03', 'date': '2026-11-19',
                'paid_by': self.users[0].pk, 'split_mode': 'percentage'}
        for user in self.users[:2]:
            data[f'split_participates_{user.pk}'] = 'on'
            data[f'split_amount_{user.pk}'] = '50'
        response = self.client.post(reverse('expense_create', args=[self.group.pk]), data)
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(group=self.group, title='Percentual')
        amounts = dict(expense.splits.values_list('user_id', 'amount_owed'))
        self.assertEqual(amounts, {self.users[0].pk: Decimal('0.02'), self.users[1].pk: Decimal('0.01')})


class ExpenseBalanceDisplayTests(TestCase):
    def setUp(self):
        self.payer = CustomUser.objects.create_user(username='balance_payer')
        self.debtor = CustomUser.objects.create_user(username='balance_debtor')
        self.other = CustomUser.objects.create_user(username='balance_other')
        self.group = Group.objects.create(name='Saldos', created_by=self.payer)
        for user in (self.debtor, self.other):
            GroupMembership.objects.create(group=self.group, user=user, is_accepted=True)
        self.expense = Expense.objects.create(group=self.group, paid_by=self.payer, created_by=self.payer, title='Conta', amount=Decimal('100.00'), date=date(2026, 11, 19))
        self.own = ExpenseSplit.objects.create(expense=self.expense, user=self.payer, amount_owed=Decimal('40.00'))
        self.pending = ExpenseSplit.objects.create(expense=self.expense, user=self.debtor, amount_owed=Decimal('35.00'))
        self.paid = ExpenseSplit.objects.create(expense=self.expense, user=self.other, amount_owed=Decimal('25.00'), is_paid=True)

    def test_saldos_e_status_do_pagador_ignoram_cota_propria(self):
        self.client.force_login(self.payer)
        for paid in (False, True):
            with self.subTest(own_paid=paid):
                self.own.is_paid = paid
                self.own.save()
                detail = self.client.get(reverse('expense_detail', args=[self.expense.pk]))
                self.assertEqual(detail.context['remaining_total'], Decimal('35.00'))
                self.assertEqual(detail.context['paid_total'], Decimal('25.00'))
                self.assertEqual(detail.context['total_splits'], Decimal('100.00'))
                self.assertEqual(detail.context['user_status'], 'Cota própria')
                self.assertContains(detail, 'Cota própria')
                group = self.client.get(reverse('group_detail', args=[self.group.pk]))
                self.assertEqual(group.context['total_to_pay_by_user'], Decimal('0.00'))
                self.assertEqual(group.context['expense_items'][0]['paid_splits_count'], 1)
                self.assertEqual(group.context['expense_items'][0]['total_splits_count'], 2)
                self.assertContains(group, 'Cota própria')
                self.assertContains(self.client.get(reverse('expense_list_all')), 'Cota própria')

    def test_total_usuario_inclui_apenas_divisoes_pendentes_de_outras_pessoas(self):
        self.client.force_login(self.debtor)
        group = self.client.get(reverse('group_detail', args=[self.group.pk]))
        self.assertEqual(group.context['total_to_pay_by_user'], Decimal('35.00'))
        self.assertEqual(group.context['expense_items'][0]['user_status'], 'A pagar')
        self.pending.is_paid = True
        self.pending.save()
        group = self.client.get(reverse('group_detail', args=[self.group.pk]))
        self.assertEqual(group.context['total_to_pay_by_user'], Decimal('0.00'))
        detail = self.client.get(reverse('expense_detail', args=[self.expense.pk]))
        self.assertEqual(detail.context['remaining_total'], Decimal('0.00'))
        self.assertEqual(detail.context['paid_total'], Decimal('60.00'))
        self.assertEqual(detail.context['user_status'], 'Paga')

    def test_cota_propria_nao_pode_ser_alterada_por_nenhum_usuario(self):
        superuser = CustomUser.objects.create_superuser(username='balance_super', password='senha')
        for user in (self.payer, self.debtor, superuser):
            with self.subTest(user=user):
                self.client.force_login(user)
                detail = self.client.get(reverse('expense_detail', args=[self.expense.pk]))
                self.assertNotContains(detail, reverse('split_toggle_paid', args=[self.own.pk]))
                response = self.client.post(reverse('split_toggle_paid', args=[self.own.pk]))
                self.assertEqual(response.status_code, 302)
                self.own.refresh_from_db()
                self.assertFalse(self.own.is_paid)
        self.client.force_login(superuser)
        self.client.post(reverse('split_toggle_paid', args=[self.pending.pk]))
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_paid)

    def test_adiantamento_aparece_apenas_ao_pagador_com_saldo_pendente(self):
        self.client.force_login(self.payer)
        response = self.client.get(reverse('expense_detail', args=[self.expense.pk]))
        self.assertContains(response, 'Você adiantou R$ 35,00 aos demais')
        self.assertContains(response, 'Voltar ao grupo', count=1)
        self.client.force_login(self.debtor)
        self.assertNotContains(self.client.get(reverse('expense_detail', args=[self.expense.pk])), 'Você adiantou')
        self.pending.is_paid = True
        self.pending.save()
        self.client.force_login(self.payer)
        self.assertNotContains(self.client.get(reverse('expense_detail', args=[self.expense.pk])), 'Você adiantou')

    def test_formularios_mostram_somente_campos_obrigatorios(self):
        self.client.force_login(self.payer)
        for url in (reverse('expense_create', args=[self.group.pk]), reverse('expense_update', args=[self.expense.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'Título *')
                self.assertContains(response, 'Valor Total (R$) *')
                self.assertContains(response, 'Data do Gasto *')
                self.assertContains(response, 'Quem Pagou *')
                self.assertNotContains(response, 'Descrição *')


class ParticipantBalanceTests(TestCase):
    def setUp(self):
        self.me = CustomUser.objects.create_user(username='balance_me')
        self.alice = CustomUser.objects.create_user(username='balance_alice')
        self.bob = CustomUser.objects.create_user(username='balance_bob')
        self.carla = CustomUser.objects.create_user(username='balance_carla')
        self.group = Group.objects.create(name='Balanço', created_by=self.me)
        for user in (self.alice, self.bob, self.carla):
            GroupMembership.objects.create(group=self.group, user=user, is_accepted=True)

    def add_obligation(self, payer, debtor, amount, group=None, paid=False):
        group = group or self.group
        expense = Expense.objects.create(group=group, paid_by=payer, created_by=payer, title='Despesa', amount=Decimal(amount), date=date(2026, 1, 1))
        return ExpenseSplit.objects.create(expense=expense, user=debtor, amount_owed=Decimal(amount), is_paid=paid)

    def balances(self):
        from .services import calculate_participant_balances
        return {row['participant'].pk: row for row in calculate_participant_balances(self.group, self.me)}

    def test_unilaterais_reciprocos_e_saldo_zero(self):
        self.add_obligation(self.alice, self.me, '250.00')
        self.add_obligation(self.me, self.alice, '100.00')
        self.add_obligation(self.me, self.bob, '200.00')
        self.add_obligation(self.bob, self.me, '50.00')
        self.add_obligation(self.carla, self.me, '100.00')
        self.add_obligation(self.me, self.carla, '100.00')
        with self.assertNumQueries(1):
            balances = self.balances()
        for user, owed, receivable, net, direction in (
            (self.alice, '250.00', '100.00', '150.00', 'DEVE'),
            (self.bob, '50.00', '200.00', '150.00', 'RECEBE'),
            (self.carla, '100.00', '100.00', '0.00', 'EM_DIA'),
        ):
            with self.subTest(user=user):
                row = balances[user.pk]
                self.assertEqual((row['amount_owed'], row['amount_receivable'], row['net_amount'], row['direction']),
                                 (Decimal(owed), Decimal(receivable), Decimal(net), direction))

    def test_pagas_cota_propria_outros_grupos_e_terceiros_sao_ignorados(self):
        other_group = Group.objects.create(name='Outro', created_by=self.me)
        GroupMembership.objects.create(group=other_group, user=self.alice, is_accepted=True)
        self.add_obligation(self.alice, self.me, '99.00', group=other_group)
        self.add_obligation(self.alice, self.me, '10.00', paid=True)
        self.add_obligation(self.me, self.me, '20.00')
        self.add_obligation(self.alice, self.bob, '30.00')
        self.assertEqual(self.balances(), {})

    def test_todas_despesas_e_vinculo_removido(self):
        for _ in range(8):
            self.add_obligation(self.me, self.alice, '1.25')
        GroupMembership.objects.filter(group=self.group, user=self.alice).delete()
        balance = self.balances()[self.alice.pk]
        self.assertEqual(balance['amount_receivable'], Decimal('10.00'))
        self.assertEqual(balance['direction'], 'RECEBE')

    def test_recalcula_ao_criar_editar_excluir_e_alternar_pagamento(self):
        split = self.add_obligation(self.alice, self.me, '10.00')
        self.assertEqual(self.balances()[self.alice.pk]['net_amount'], Decimal('10.00'))
        second = self.add_obligation(self.me, self.alice, '4.00')
        self.assertEqual(self.balances()[self.alice.pk]['net_amount'], Decimal('6.00'))
        second.amount_owed = Decimal('7.00')
        second.save()
        self.assertEqual(self.balances()[self.alice.pk]['net_amount'], Decimal('3.00'))
        split.is_paid = True
        split.save()
        self.assertEqual(self.balances()[self.alice.pk]['direction'], 'RECEBE')
        split.is_paid = False
        split.save()
        self.assertEqual(self.balances()[self.alice.pk]['direction'], 'DEVE')
        split.expense.delete()
        self.assertEqual(self.balances()[self.alice.pk]['net_amount'], Decimal('7.00'))

    def test_balanco_na_pagina_das_duas_perspectivas_e_atualizacao(self):
        from django.utils.html import strip_tags
        first = self.add_obligation(self.alice, self.me, '1666.00')
        self.add_obligation(self.me, self.alice, '300.00')
        self.add_obligation(self.bob, self.carla, '55.00')
        self.client.force_login(self.me)
        response = self.client.get(reverse('group_detail', args=[self.group.pk]))
        self.assertEqual(len(response.context['participant_balances']), 1)
        text = ' '.join(strip_tags(response.content.decode()).split())
        self.assertIn('Você deve R$ 1.366,00 a balance_alice', text)
        self.client.force_login(self.alice)
        response = self.client.get(reverse('group_detail', args=[self.group.pk]))
        text = ' '.join(strip_tags(response.content.decode()).split())
        self.assertIn('balance_me te deve R$ 1.366,00', text)
        first.is_paid = True
        first.save()
        response = self.client.get(reverse('group_detail', args=[self.group.pk]))
        self.assertEqual(response.context['participant_balances'][0]['direction'], 'DEVE')
        self.assertEqual(response.context['participant_balances'][0]['net_amount'], Decimal('300.00'))

    def test_balanco_zero_e_vazio_na_pagina(self):
        self.client.force_login(self.me)
        url = reverse('group_detail', args=[self.group.pk])
        self.assertContains(self.client.get(url), 'Você não possui pendências neste grupo.')
        self.add_obligation(self.alice, self.me, '10.00')
        self.add_obligation(self.me, self.alice, '10.00')
        response = self.client.get(url)
        self.assertContains(response, 'estão em dia')
        self.assertEqual(response.context['participant_balances'][0]['direction'], 'EM_DIA')

    def test_card_do_grupo_e_link_unico(self):
        from django.utils.html import escape
        self.client.force_login(self.me)
        response = self.client.get(reverse('group_list'))
        url = reverse('group_detail', args=[self.group.pk])
        self.assertContains(response, f'href="{url}" class="se-groups-panel se-group-card"', html=False)
        self.assertContains(response, f'href="{url}"', count=1)
        self.assertContains(response, escape(self.group.name))
        self.assertContains(response, 'Acessar grupo')
