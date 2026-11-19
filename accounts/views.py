
from django.shortcuts import render, redirect
from .forms import CadastroForm
from django.contrib.auth.decorators import login_required
from decimal import Decimal

from django.db.models import Sum
from expenses.models import Expense, ExpenseSplit, Group

@login_required

@login_required
def pagina_inicial(request):
    grupos = Group.objects.filter(
        groupmembership__user=request.user,
        groupmembership__is_accepted=True,
    )

    divisoes_pendentes = ExpenseSplit.objects.filter(
        expense__group__in=grupos,
        is_paid=False,
    )

    total_devido = (
        divisoes_pendentes
        .filter(user=request.user)
        .exclude(expense__paid_by=request.user)
        .aggregate(total=Sum("amount_owed", default=Decimal("0.00")))["total"]
    )

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



def cadastro(request):
    if request.user.is_authenticated:
        return redirect("inicio")

    if request.method == "POST":
        form = CadastroForm(request.POST)

        if form.is_valid():
            user = form.save(commit=False)
            user.role = "USER"
            user.is_staff = False
            user.is_superuser = False
            user.save()

            return redirect("login")
    else:
        form = CadastroForm()

    return render(request, "accounts/cadastro.html", {"form": form})
