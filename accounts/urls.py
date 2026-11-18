from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from . import views

urlpatterns = [
    path("", views.pagina_inicial, name="inicio"),
    path("cadastro/", views.cadastro, name="cadastro"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path(
        "login/", LoginView.as_view(
            template_name="accounts/login.html",
            redirect_authenticated_user=True,
            ),
        name="login",
        ),
    path("perfil/", views.perfil_usuario, name="perfil"),
]
