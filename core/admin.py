from django.contrib import admin
from .models import Patient, PatientRecording

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('name', 'birth_date', 'gender', 'diagnosis', 'consent_signed', 'created_at')
    list_filter = ('diagnosis', 'gender', 'consent_signed')
    search_fields = ('name', 'diagnosis_other')

@admin.register(PatientRecording)
class PatientRecordingAdmin(admin.ModelAdmin):
    list_display = ('patient', 'task_type', 'created_at')
    list_filter = ('task_type',)
    search_fields = ('patient__name',)
