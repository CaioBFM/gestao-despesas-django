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
    path("amigos/", views.friends_list, name="friends_list"),
    path("amigos/solicitacao/<int:friendship_id>/acao/", views.friend_request_action, name="friend_request_action"),
    path("amigos/<int:user_id>/remover/", views.friend_remove, name="friend_remove"),
    
    # Relatórios gerais (somente admin geral)
    path("relatorios/", views.relatorios, name="relatorios"),
]
