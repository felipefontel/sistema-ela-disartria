from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from .models import Patient, PatientRecording

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('dashboard')
    else:
        form = AuthenticationForm()
        
    return render(request, 'core/login.html', {'form': form})

def logout_view(request):
    if request.method == 'POST':
        logout(request)
    return redirect('login')

@login_required
def dashboard_view(request):
    total_patients = Patient.objects.count()
    total_recordings = PatientRecording.objects.count()
    
    context = {
        'total_patients': total_patients,
        'total_recordings': total_recordings,
    }
    return render(request, 'core/dashboard.html', context)

# Placeholders para as próximas tarefas
@login_required
def patient_list(request):
    patients = Patient.objects.all().order_by('-created_at')
    return render(request, 'core/patient_list.html', {'patients': patients})

@login_required
def patient_create(request):
    from .forms import PatientForm
    if request.method == 'POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            patient = form.save(commit=False)
            patient.created_by = request.user
            patient.save()
            return redirect('recording_task', patient_id=patient.id, step=1)
    else:
        form = PatientForm()
    return render(request, 'core/patient_form.html', {'form': form})

from django.contrib.auth.models import User
@login_required
def user_list(request):
    users = User.objects.all()
    return render(request, 'core/user_list.html', {'users': users})

# Configuração das 5 Tarefas
RECORDING_TASKS = [
    {
        'id': 'FONACAO',
        'title': '1. Fonação Sustentada',
        'instruction': "Diga 'AAAAA' o mais longo que conseguir.",
        'next_step': 2
    },
    {
        'id': 'DIADOCOCINESIA',
        'title': '2. Diadococinesia',
        'instruction': "Repita 'PA-TA-KA' rápido por 10 segundos.",
        'next_step': 3
    },
    {
        'id': 'PALAVRAS',
        'title': '3. Palavras Complexas',
        'instruction': "Leia em voz alta: Prato, Trator, Plástico, Bicicleta.",
        'next_step': 4
    },
    {
        'id': 'LEITURA',
        'title': '4. Leitura Padronizada',
        'instruction': "Leia em voz alta: 'O rato roeu a roupa do rei de Roma'.",
        'next_step': 5
    },
    {
        'id': 'ESPONTANEA',
        'title': '5. Fala Espontânea',
        'instruction': "Descreva brevemente uma rotina do seu dia.",
        'next_step': None
    }
]

@login_required
def recording_task_view(request, patient_id, step):
    patient = get_object_or_404(Patient, id=patient_id)
    
    if step < 1 or step > 5:
        return redirect('dashboard')
        
    task_info = RECORDING_TASKS[step - 1]
    
    context = {
        'patient': patient,
        'step': step,
        'task': task_info,
    }
    return render(request, 'core/recording_task.html', context)

@login_required
@csrf_protect
def upload_audio_api(request):
    if request.method == 'POST':
        audio_file = request.FILES.get('audio_file')
        patient_id = request.POST.get('patient_id')
        task_type = request.POST.get('task_type')
        
        if not all([audio_file, patient_id, task_type]):
            return JsonResponse({'error': 'Parâmetros ausentes'}, status=400)
            
        patient = get_object_or_404(Patient, id=patient_id)
        
        # Save recording
        recording = PatientRecording.objects.create(
            patient=patient,
            task_type=task_type,
            audio_file=audio_file,
            recorded_by=request.user
        )
        
        return JsonResponse({'message': 'Áudio salvo com sucesso!', 'id': recording.id})
    return JsonResponse({'error': 'Método inválido'}, status=405)
