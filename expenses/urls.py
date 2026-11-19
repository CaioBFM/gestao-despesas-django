from django.urls import path
from . import views

urlpatterns = [
    # Grupos e membros
    path('', views.group_list, name='group_list'),
    path('new/', views.group_create, name='group_create'),
    path('<int:pk>/', views.group_detail, name='group_detail'),
    path('join/', views.group_join, name='group_join'),
    path('<int:pk>/leave/', views.group_leave, name='group_leave'),
    path('<int:group_id>/members/<int:membership_id>/action/', views.member_action, name='member_action'),

    # Despesas e divisões
    path('<int:group_id>/expenses/new/', views.expense_create, name='expense_create'),
    path('expenses/', views.expense_list_all, name='expense_list_all'),
    path('expenses/<int:pk>/', views.expense_detail, name='expense_detail'),
    path('expenses/<int:pk>/edit/', views.expense_update, name='expense_update'),
    path('expenses/<int:pk>/delete/', views.expense_delete, name='expense_delete'),
    path('splits/<int:split_id>/toggle-paid/', views.split_toggle_paid, name='split_toggle_paid'),
    path('history/', views.personal_history, name='personal_history'),

    path('<int:pk>/add-friend/', views.group_add_friend, name='group_add_friend'),
]