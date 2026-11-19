from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    # Atributos personalizados além dos nativos (username, email, password, first_name, last_name)
    role = models.CharField(
        "Perfil / Papel",
        max_length=20,
        choices=[('ADMIN', 'Administrador'), ('USER', 'Usuário Comum')],
        default='USER',
    )
    is_active = models.BooleanField("Ativo", default=True)  # Para exclusão lógica
    created_at = models.DateTimeField("Cadastrado em", auto_now_add=True)

    class Meta(AbstractUser.Meta):
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"
        ordering = ['username']

    def __str__(self):
        return f"{self.username} ({self.role})"


class Friendship(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_ACCEPTED = 'ACCEPTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendente'),
        (STATUS_ACCEPTED, 'Aceita'),
    ]

    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_friendships',
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_friendships',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Amizade'
        verbose_name_plural = 'Amizades'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['from_user', 'to_user'],
                name='unique_friendship_pair',
            ),
            models.CheckConstraint(
                condition=~models.Q(from_user=models.F('to_user')),
                name='prevent_self_friendship',
            ),
        ]

    def __str__(self):
        return f'{self.from_user.username} -> {self.to_user.username} ({self.status})'
