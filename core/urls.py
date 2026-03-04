from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Pacientes
    path('patients/', views.patient_list, name='patient_list'),
    path('patients/add/', views.patient_create, name='patient_create'),
    path('patients/<int:pk>/', views.patient_detail, name='patient_detail'),
    path('patients/<int:pk>/edit/', views.patient_edit, name='patient_edit'),
    path('patients/<int:pk>/delete/', views.patient_delete, name='patient_delete'),
    
    # Usuários (restrito a superusuários)
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),

    # Gravação
    path('record/<int:patient_id>/step/<int:step>/', views.recording_task_view, name='recording_task'),
    path('record/<int:patient_id>/single/<str:task_type>/', views.recording_single_view, name='recording_single'),
    path('api/upload-audio/', views.upload_audio_api, name='upload_audio_api'),
    path('api/delete-audio/', views.delete_audio_api, name='delete_audio_api'),
]
