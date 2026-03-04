from django.db import models
from django.contrib.auth.models import User

class Patient(models.Model):
    GENDER_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Feminino'),
        ('O', 'Outro'),
    ]

    DIAGNOSIS_CHOICES = [
        ('SAUDAVEL', 'Saudável'),
        ('PARKINSON', 'Doença de Parkinson'),
        ('ELA', 'Esclerose Lateral Amiotrófica - ELA'),
        ('AVC', 'Acidente Vascular Cerebral - AVC'),
        ('OUTRO', 'Outro'),
    ]

    name = models.CharField("Nome Completo", max_length=255)
    birth_date = models.DateField("Data de Nascimento")
    gender = models.CharField("Sexo Biológico", max_length=1, choices=GENDER_CHOICES)
    diagnosis = models.CharField("Diagnóstico", max_length=20, choices=DIAGNOSIS_CHOICES)
    diagnosis_other = models.CharField("Outro Diagnóstico", max_length=255, blank=True, null=True, help_text="Preencher apenas se o diagnóstico for 'Outro'")
    disease_duration = models.IntegerField("Duração da Doença (meses)", blank=True, null=True)
    consent_signed = models.BooleanField("Concordou com o TCLE", default=False)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="patients")

    def __str__(self):
        return f"{self.name} - {self.get_diagnosis_display()}"


class PatientRecording(models.Model):
    TASK_CHOICES = [
        ('FONACAO', 'Fonação Sustentada'),
        ('DIADOCOCINESIA', 'Diadococinesia'),
        ('PALAVRAS', 'Palavras Complexas'),
        ('LEITURA', 'Leitura Padronizada'),
        ('ESPONTANEA', 'Fala Espontânea'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="recordings")
    task_type = models.CharField("Tipo de Tarefa", max_length=20, choices=TASK_CHOICES)
    audio_file = models.FileField("Arquivo de Áudio", upload_to="recordings/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.patient.name} - {self.get_task_type_display()} - {self.created_at.strftime('%d/%m/%Y')}"
