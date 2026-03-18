from django.db import models
from django.contrib.auth.models import User

class Patient(models.Model):
    GENDER_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Feminino'),
    ]

    DIAGNOSIS_CHOICES = [
        ('SAUDAVEL', 'Saudável'),
        ('ELA_INICIO_BULBAR', 'ELA início bulbar'),
        ('ELA_INICIO_ESPINHAL', 'ELA início espinhal'),
        ('ELA_ESPINHAL_BULBAR', 'ELA espinhal e bulbar'),
        ('OUTRO', 'Outro'),
    ]

    name = models.CharField("Nome Completo", max_length=255)
    birth_date = models.DateField("Data de Nascimento")
    gender = models.CharField("Sexo Biológico", max_length=1, choices=GENDER_CHOICES)
    diagnosis = models.CharField("Diagnóstico", max_length=20, choices=DIAGNOSIS_CHOICES)
    diagnosis_other = models.CharField("Outro Diagnóstico", max_length=255, blank=True, null=True, help_text="Preencher apenas se o diagnóstico for 'Outro'")
    alsfrs_bulbar = models.IntegerField("Escore Bulbar ALSFRS-R (0 a 12)", null=True, blank=True, help_text="Soma das perguntas 1 a 3 (0 a 12)")
    alsfrs_total = models.IntegerField("Escore Total ALSFRS-R (0 a 48)", null=True, blank=True, help_text="Soma de todas as perguntas (0 a 48)")
    phone = models.CharField("Telefone", max_length=20, blank=True, null=True)
    city = models.CharField("Cidade", max_length=100, blank=True, null=True)
    state = models.CharField("Estado (UF)", max_length=2, blank=True, null=True)
    has_escort = models.BooleanField("Está com acompanhante?", default=False)
    escort_name = models.CharField("Nome do Acompanhante", max_length=255, blank=True, null=True, help_text="Preencher apenas se estiver com acompanhante")

    consent_signed = models.BooleanField("Concordou com o TCLE", default=False)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="patients")

    def __str__(self):
        return f"{self.name} - {self.get_diagnosis_display()}"


def patient_directory_path(instance, filename):
    # O arquivo será salvo para: recordings/paciente_<id>/<nome_do_arquivo>
    return f'recordings/paciente_{instance.patient.id}/{filename}'

class PatientRecording(models.Model):
    TASK_CHOICES = [
        ('FONACAO_A', 'Fonação Sustentada (Vogal A)'),
        ('FONACAO_I', 'Fonação Sustentada (Vogal I)'),
        ('FONACAO_U', 'Fonação Sustentada (Vogal U)'),
        ('DIADOCOCINESIA', 'Diadococinesia'),
        ('LEITURA', 'Leitura Padronizada'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="recordings")
    task_type = models.CharField("Tipo de Tarefa", max_length=20, choices=TASK_CHOICES)
    audio_file = models.FileField("Arquivo de Áudio", upload_to=patient_directory_path)
    created_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.patient.name} - {self.get_task_type_display()} - {self.created_at.strftime('%d/%m/%Y')}"
