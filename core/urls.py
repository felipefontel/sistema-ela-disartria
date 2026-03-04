from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Placeholders
    path('patients/', views.patient_list, name='patient_list'),
    path('patients/add/', views.patient_create, name='patient_create'),
    path('users/', views.user_list, name='user_list'),
    
    # Gravação
    path('record/<int:patient_id>/step/<int:step>/', views.recording_task_view, name='recording_task'),
    path('api/upload-audio/', views.upload_audio_api, name='upload_audio_api'),
]
