from django.urls import path
from . import views

urlpatterns = [
    path('', views.group_list, name='group_list'),
    path('new/', views.group_create, name='group_create'),
    path('<int:pk>/', views.group_detail, name='group_detail'),
    path('join/', views.group_join, name='group_join'),
    path('<int:pk>/leave/', views.group_leave, name='group_leave'),
    path('<int:group_id>/members/<int:membership_id>/action/', views.member_action, name='member_action'),
]