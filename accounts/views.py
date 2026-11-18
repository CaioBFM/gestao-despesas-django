
from django.shortcuts import render, redirect
from .forms import CadastroForm
from django.contrib.auth.decorators import login_required


@login_required
def pagina_inicial(request):
    return render(request, "index.html")


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
