from django.db.models import Q
from .models import CustomUser, Friendship


def are_friends(user_a, user_b):
    if not user_a or not user_b or user_a.pk == user_b.pk:
        return False
    return Friendship.objects.filter(
        status=Friendship.STATUS_ACCEPTED,
    ).filter(
        Q(from_user=user_a, to_user=user_b) | Q(from_user=user_b, to_user=user_a)
    ).exists()


def get_friends_queryset(user):
    accepted = Friendship.objects.filter(
        status=Friendship.STATUS_ACCEPTED,
    ).filter(Q(from_user=user) | Q(to_user=user))

    friend_ids = set()
    for f in accepted:
        friend_ids.add(f.to_user_id if f.from_user_id == user.pk else f.from_user_id)

    return CustomUser.objects.filter(pk__in=friend_ids, is_active=True).order_by('username')