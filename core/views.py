from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from .models import Patient, PatientRecording
from .forms import PatientForm, UserCreateForm, UserEditForm
import sys
import os
import csv
from django.conf import settings


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # Lógica de "Lembrar de Mim"
            remember_me = request.POST.get('remember_me')
            if not remember_me:
                # Navegadores modernos (Chrome/Safari) costumam reter cookies de sessão infinitamente
                # se a opção "Continuar de onde parei" estiver ativa.
                # Para garantir que caia, forçamos a expiração em 1 hora de inatividade.
                request.session.set_expiry(3600)
            else:
                # 2 semanas (padrão de 1209600s)
                request.session.set_expiry(1209600)
                
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
    from django.core.paginator import Paginator
    
    query = request.GET.get('q', '').strip()
    diagnosis_filter = request.GET.get('diagnosis', '')
    gender_filter = request.GET.get('gender', '')

    patients_qs = Patient.objects.all().order_by('-created_at')
    
    if query:
        patients_qs = patients_qs.filter(name__icontains=query)
    if diagnosis_filter:
        patients_qs = patients_qs.filter(diagnosis=diagnosis_filter)
    if gender_filter:
        patients_qs = patients_qs.filter(gender=gender_filter)
    
    try:
        per_page = int(request.GET.get('per_page', 10))
    except ValueError:
        per_page = 10

    paginator = Paginator(patients_qs, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'query': query,
        'diagnosis_filter': diagnosis_filter,
        'gender_filter': gender_filter,
        'per_page': per_page,
        'total_patients': Patient.objects.count(),
        'diagnosis_choices': Patient.DIAGNOSIS_CHOICES,
        'gender_choices': Patient.GENDER_CHOICES,
    }
    return render(request, 'core/dashboard.html', context)


# ── Pacientes ────────────────────────────────────────────────────────────────

@login_required
def patient_list(request):
    patients = Patient.objects.all().order_by('-created_at')
    return render(request, 'core/patient_list.html', {'patients': patients})

@login_required
def patient_create(request):
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


@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    recordings = patient.recordings.all().order_by('task_type', '-created_at')
    
    # Agrupa gravações por tipo de tarefa
    TASK_LABELS = {
        'FONACAO_A': '1. Fonação Sustentada (Vogal A)',
        'FONACAO_I': '2. Fonação Sustentada (Vogal I)',
        'FONACAO_U': '3. Fonação Sustentada (Vogal U)',
        'DIADOCOCINESIA': '4. Diadococinesia',
        'LEITURA': '5. Leitura Padronizada',
    }
    TASK_ORDER = ['FONACAO_A', 'FONACAO_I', 'FONACAO_U', 'DIADOCOCINESIA', 'LEITURA']
    
    recordings_by_task = {}
    for task_id in TASK_ORDER:
        recs = [r for r in recordings if r.task_type == task_id]
        recordings_by_task[task_id] = {
            'label': TASK_LABELS[task_id],
            'step': TASK_ORDER.index(task_id) + 1,
            'recordings': recs,
        }

    return render(request, 'core/patient_detail.html', {
        'patient': patient,
        'recordings_by_task': recordings_by_task,
    })


@login_required
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == 'POST':
        form = PatientForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, f'Dados de <strong>{patient.name}</strong> atualizados com sucesso!')
            return redirect('dashboard')
    else:
        form = PatientForm(instance=patient)

    # Carregar gravações existentes por tarefa
    TASK_ORDER = ['FONACAO_A', 'FONACAO_I', 'FONACAO_U', 'DIADOCOCINESIA', 'LEITURA']
    TASK_LABELS = {
        'FONACAO_A': '1. Fonação Sustentada (Vogal A)',
        'FONACAO_I': '2. Fonação Sustentada (Vogal I)',
        'FONACAO_U': '3. Fonação Sustentada (Vogal U)',
        'DIADOCOCINESIA': '4. Diadococinesia',
        'LEITURA': '5. Leitura Padronizada',
    }
    recordings = list(patient.recordings.order_by('created_at'))
    recordings_by_task = {}
    for task_id in TASK_ORDER:
        recs = [r for r in recordings if r.task_type == task_id]
        recordings_by_task[task_id] = {
            'label': TASK_LABELS[task_id],
            'recordings': recs,
        }

    return render(request, 'core/patient_form.html', {
        'form': form,
        'patient': patient,
        'action': 'Editar Paciente',
        'recordings_by_task': recordings_by_task,
    })


@login_required
def recording_single_view(request, patient_id, task_type):
    """Gravar apenas uma tarefa avulsa, retornando para patient_edit ao finalizar."""
    patient = get_object_or_404(Patient, id=patient_id)
    TASK_MAP = {task['id']: task for task in RECORDING_TASKS}
    if task_type not in TASK_MAP:
        return redirect('patient_edit', pk=patient_id)
    task_info = TASK_MAP[task_type]
    context = {
        'patient': patient,
        'task': task_info,
        'single_mode': True,  # sinaliza ao template que é regravação avulsa
        'return_url': f'/patients/{patient_id}/edit/',
    }
    return render(request, 'core/recording_single.html', context)


@login_required
def recording_single_complete_view(request, patient_id):
    """Chamada ao finalizar uma regravação individual."""
    messages.success(request, '✅ Regravação concluída com sucesso!')
    return redirect('patient_edit', pk=patient_id)


@login_required
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == 'POST':
        name = patient.name
        patient.delete()
        messages.success(request, f'Paciente "{name}" excluído com sucesso!')
        return redirect('dashboard')
    return redirect('patient_detail', pk=pk)


@login_required
def recording_complete_view(request, patient_id):
    """Chamada ao finalizar a última tarefa. Adiciona mensagem de sucesso e redireciona para patient_detail."""
    patient = get_object_or_404(Patient, id=patient_id)
    messages.success(
        request,
        f'Sessão de gravação de <strong>{patient.name}</strong> concluída com sucesso!'
    )
    return redirect('patient_detail', pk=patient_id)



# ── Usuários (apenas superusuários) ──────────────────────────────────────────

def _superuser_required(view_func):
    """Decorator que exige is_superuser, redireciona médicos para o dashboard."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_superuser:
            messages.error(request, 'Você não tem permissão para acessar esta página.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

@_superuser_required
def patient_features_view(request, pk):
    """View administrativa para visualizar features de áudio geradas sob-demanda"""
    patient = get_object_or_404(Patient, pk=pk)
    
    # Adicionamos dinamicamente de volta ao path para importar as funções que fizemos avulso no arquivo de extração do projeto
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from extrator_features_ela import (
        get_audio_path, 
        extract_jitter_shimmer_hnr, 
        extract_vsa, 
        extract_f0_stats, 
        extract_speech_rate, 
        extract_temporal_rhythm,
        extract_mfcc_and_dynamics,
        cleanup_temp_files
    )

    recordings = patient.recordings.all()
    recs_dict = {rec.task_type: rec for rec in recordings}
    
    # Download temporário
    audio_a = get_audio_path(recs_dict.get('FONACAO_A'))
    audio_i = get_audio_path(recs_dict.get('FONACAO_I'))
    audio_u = get_audio_path(recs_dict.get('FONACAO_U'))
    audio_leitura = get_audio_path(recs_dict.get('LEITURA'))
    audio_ddk = get_audio_path(recs_dict.get('DIADOCOCINESIA'))

    # Cálculos na hora para a Page Visual
    jitter_a, shimmer_a, hnr_a = extract_jitter_shimmer_hnr(audio_a)
    vsa = extract_vsa(audio_a, audio_i, audio_u)
    f0_mean, f0_std = extract_f0_stats(audio_leitura)
    speech_rate, pauses_count, speaking_duration = extract_speech_rate(audio_leitura)
    ddk_count, ddk_regularity = extract_temporal_rhythm(audio_ddk)
    mfccs_dyn = extract_mfcc_and_dynamics(audio_leitura)
    zcr_mean = mfccs_dyn[39] if mfccs_dyn and len(mfccs_dyn) == 40 else None

    # Limpeza Limpador RAM
    cleanup_temp_files([audio_a, audio_i, audio_u, audio_leitura, audio_ddk])

    context = {
        'patient': patient,
        'features': {
            'jitter': round(jitter_a, 5) if jitter_a is not None else None,
            'shimmer': round(shimmer_a, 5) if shimmer_a is not None else None,
            'hnr': round(hnr_a, 2) if hnr_a is not None else None,
            'vsa': round(vsa, 2) if vsa is not None else None,
            'f0_mean': round(f0_mean, 2) if f0_mean is not None else None,
            'f0_std': round(f0_std, 2) if f0_std is not None else None,
            'speech_rate': round(speech_rate, 2) if speech_rate is not None else None,
            'pauses_count': pauses_count if pauses_count is not None else None,
            'ddk_count': ddk_count if ddk_count is not None else None,
            'ddk_regularity': round(ddk_regularity, 4) if ddk_regularity is not None else None,
            'zcr_mean': round(zcr_mean, 5) if zcr_mean is not None else None,
            'has_mfcc': (mfccs_dyn[0] is not None) if mfccs_dyn and len(mfccs_dyn) > 0 else False,
        }
    }
    
    return render(request, 'core/patient_features.html', context)


@_superuser_required
def admin_features_dataset_view(request):
    """View administrativa que lê o dataset_features_ela.csv de forma hiper-otimizada"""
    
    # O arquivo extrator salva na raiz estrutural onde o manage.py é rodado
    csv_path = os.path.join(settings.BASE_DIR, 'dataset_features_ela.csv')
    dataset_rows = []
    has_dataset = False
    
    if os.path.exists(csv_path):
        has_dataset = True
        try:
            with open(csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    dataset_rows.append(row)
        except Exception as e:
            print(f"Erro lendo CSV: {e}")
            
    context = {
        'has_dataset': has_dataset,
        'dataset_rows': dataset_rows
    }
    return render(request, 'core/admin_features_table.html', context)


@_superuser_required
def admin_generate_dataset_view(request):
    """Executa o script avulso de Machine Learning que varre os perfis e regera o CSV offline."""
    try:
        # Importamos a função mestra do arquivo extrator raiz.
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from extrator_features_ela import criar_dataset_pacientes
        
        # Chama de forma síncrona o loop pesado (cálculos do parselmouth/librosa)
        criar_dataset_pacientes()
        
        messages.success(request, 'Sucesso Absoluto! A base de dados Acústica (CSV) foi integralmente recriada baseada nas últimas gravações.')
    except Exception as e:
        messages.error(request, f'Houve uma desestabilização computacional ao recriar o Dataset: {str(e)}')
        
    # Quando acabar todo o loading do Python pesado, ele estourará e devolverá o HTML relido:
    return redirect('admin_features_dataset_view')


def _get_user_papel(user):
    """Retorna 'admin' ou 'medico' conforme o papel do usuário."""
    if user.is_superuser:
        return 'admin'
    return 'medico'


@_superuser_required
def user_list(request):
    users = User.objects.all().order_by('first_name', 'username')
    return render(request, 'core/user_list.html', {'users': users})


@_superuser_required
def user_create(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            user = User.objects.create_user(
                username=data['username'],
                email=data.get('email', ''),
                password=data['password'],
                first_name=data['first_name'],
                last_name=data['last_name'],
            )
            if data['papel'] == 'admin':
                user.is_superuser = True
                user.is_staff = True
                user.save()
            else:
                medico_group, _ = Group.objects.get_or_create(name='Médico')
                user.groups.add(medico_group)

            messages.success(request, f'Usuário "{user.username}" criado com sucesso!')
            return redirect('user_list')
    else:
        form = UserCreateForm()
    return render(request, 'core/user_form.html', {'form': form, 'action': 'Novo Usuário'})


@_superuser_required
def user_edit(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    
    if request.method == 'POST':
        form = UserEditForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            target_user.first_name = data['first_name']
            target_user.last_name = data['last_name']
            target_user.email = data.get('email', '')
            
            if data['password']:
                target_user.set_password(data['password'])

            if data['papel'] == 'admin':
                target_user.is_superuser = True
                target_user.is_staff = True
                target_user.groups.clear()
            else:
                target_user.is_superuser = False
                target_user.is_staff = False
                target_user.groups.clear()
                medico_group, _ = Group.objects.get_or_create(name='Médico')
                target_user.groups.add(medico_group)

            target_user.save()
            messages.success(request, f'Usuário "{target_user.username}" atualizado com sucesso!')
            return redirect('user_list')
    else:
        initial = {
            'first_name': target_user.first_name,
            'last_name': target_user.last_name,
            'email': target_user.email,
            'papel': _get_user_papel(target_user),
        }
        form = UserEditForm(initial=initial)

    return render(request, 'core/user_form.html', {
        'form': form,
        'action': f'Editar Usuário: {target_user.username}',
        'target_user': target_user,
    })


@_superuser_required
def user_delete(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user == request.user:
        messages.error(request, 'Você não pode excluir seu próprio usuário.')
        return redirect('user_list')
    if request.method == 'POST':
        username = target_user.username
        target_user.delete()
        messages.success(request, f'Usuário "{username}" excluído com sucesso!')
    return redirect('user_list')


# ── Gravações ─────────────────────────────────────────────────────────────────

RECORDING_TASKS = [
    {
        'id': 'FONACAO_A',
        'title': '1. Fonação Sustentada (Vogal A)',
        'instruction': "Respire fundo e diga 'AAAAA' de forma firme e constante por cerca de 5 segundos.",
        'example_audio': 'core/audios/Tarefa 1.wav',
        'next_step': 2
    },
    {
        'id': 'FONACAO_I',
        'title': '2. Fonação Sustentada (Vogal I)',
        'instruction': "Respire fundo e diga 'IIIII' de forma firme e constante por cerca de 5 segundos.",
        'example_audio': 'core/audios/Tarefa 2.wav',
        'next_step': 3
    },
    {
        'id': 'FONACAO_U',
        'title': '3. Fonação Sustentada (Vogal U)',
        'instruction': "Respire fundo e diga 'UUUUU' de forma firme e constante por cerca de 5 segundos.",
        'example_audio': 'core/audios/Tarefa 3.wav',
        'next_step': 4
    },
    {
        'id': 'DIADOCOCINESIA',
        'title': '4. Diadococinesia',
        "instruction": "Respire fundo e repita 'PA-TA-KA' o mais rápido e nítido que conseguir, sem pausas, durante 7 segundos.",
        'example_audio': 'core/audios/Tarefa 4.wav',
        'next_step': 5
    },
    {
        'id': 'LEITURA',
        'title': '5. Leitura Padronizada',
        'instruction': "Respire fundo e leia o texto abaixo em voz alta no seu ritmo natural. Vá até o final sem interromper:\n\n\u201cO Vento Norte e o Sol discutiam qual dos dois era o mais forte, quando surgiu um viajante envolto em uma capa. Eles concordaram que aquele que fizesse o viajante tirar a capa primeiro seria considerado o mais forte.\u201d",
        'example_audio': 'core/audios/Tarefa 5.wav',
        'next_step': None
    }
]

@login_required
def recording_instructions_view(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)
    return render(request, 'core/recording_instructions.html', {
        'patient': patient,
    })

@login_required
def recording_task_view(request, patient_id, step):
    patient = get_object_or_404(Patient, id=patient_id)
    
    if step < 1 or step > len(RECORDING_TASKS):
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
        
        # Excluir gravações antigas desta mesma tarefa para que ao regravar não mantenha duplicatas
        old_recordings = PatientRecording.objects.filter(patient=patient, task_type=task_type)
        for old_rec in old_recordings:
            if old_rec.audio_file:
                old_rec.audio_file.delete(save=False)
            old_rec.delete()
        
        recording = PatientRecording.objects.create(
            patient=patient,
            task_type=task_type,
            audio_file=audio_file,
            recorded_by=request.user
        )
        
        return JsonResponse({'message': 'Áudio salvo com sucesso!', 'id': recording.id})
    return JsonResponse({'error': 'Método inválido'}, status=405)


@login_required
@csrf_protect
def delete_audio_api(request):
    if request.method == 'POST':
        recording_id = request.POST.get('recording_id')
        if not recording_id:
            return JsonResponse({'error': 'Parâmetro ausente'}, status=400)
            
        recording = get_object_or_404(PatientRecording, id=recording_id)
        
        # Opcional: só o user criador ou superuser pode apagar.
        # Mas como a intenção é descartar em tempo real logo apos gravar:
        if recording.audio_file:
            recording.audio_file.delete(save=False)
        recording.delete()
        
        return JsonResponse({'message': 'Áudio excluído com sucesso!'})
    return JsonResponse({'error': 'Método inválido'}, status=405)
