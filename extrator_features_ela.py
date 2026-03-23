import os
import django
import pandas as pd
import numpy as np
import tempfile
import librosa
import parselmouth
import whisper
import jiwer
import warnings

# [MODIFICAÇÃO 1]: Importação do soundfile. 
# O Librosa é excelente para ler áudio, mas o PySoundFile (soundfile) 
# é mais rápido e confiável para exportar (gravar) os recortes em .wav 
# sem perdas de qualidade na taxa de amostragem.
import soundfile as sf

# Suprime os avisos do Whisper sobre uso de CPU/FP16 no terminal
warnings.filterwarnings("ignore", category=UserWarning)

# =====================================================================
# MÓDULO 1: CONFIGURAÇÃO INICIAL DO AMBIENTE DJANGO
# =====================================================================
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app_ela.settings')
django.setup()

from core.models import Patient

# =====================================================================
# MÓDULO 2: INFRAESTRUTURA DE PROCESSAMENTO DE ARQUIVOS (HELPERS)
# =====================================================================

def get_audio_path(recording):
    if not recording or not recording.audio_file:
        return None
        
    try:
        try:
            path = recording.audio_file.path
            if os.path.exists(path):
                snd = parselmouth.Sound(path)
            else:
                raise NotImplementedError
        except (NotImplementedError, AttributeError):
            file_content = recording.audio_file.read()
            suffix = os.path.splitext(recording.audio_file.name)[-1]
            
            temp_raw = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            temp_raw.write(file_content)
            temp_raw.close()
            
            snd = parselmouth.Sound(temp_raw.name)
            os.remove(temp_raw.name)
            
        snd.scale_peak(0.99)
        
        temp_norm = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        snd.save(temp_norm.name, "WAV")
        temp_norm.close()
        
        return temp_norm.name 

    except Exception as e:
        print(f"Erro ao normalizar/carregar arquivo de áudio: {e}")
        return None

# [MODIFICAÇÃO 2]: Implementação da função de isolamento acústico.
def isolar_trecho_estavel(audio_path, margem_corte_seg=0.5):
    """
    Carrega o arquivo .wav temporário, remove os silêncios absolutos nas pontas,
    e descarta o ataque vocal (início) e o decaimento/exaustão (final).
    Retorna o mesmo caminho do arquivo, agora sobrescrito apenas com o "miolo" da voz.
    """
    # Se o caminho for nulo ou o arquivo não existir, retorna a entrada sem quebrar o código
    if not audio_path or not os.path.exists(audio_path):
        return audio_path
        
    try:
        # Carrega o áudio preservando a taxa de amostragem original (sr=None)
        y, sr = librosa.load(audio_path, sr=None)
        
        # 1. Identifica onde a voz realmente começa e termina.
        # top_db=30 recorta qualquer ruído de fundo inferior a 30 decibéis do pico.
        intervalos_voz = librosa.effects.split(y, top_db=30)
        
        if len(intervalos_voz) == 0:
            print(f"Aviso: Nenhuma voz detectada em {audio_path}.")
            return audio_path 
            
        # Pega o índice inicial do primeiro som e o final do último som
        inicio_voz = intervalos_voz[0][0]
        fim_voz = intervalos_voz[-1][1]
        y_voz = y[inicio_voz:fim_voz]
        
        # 2. Transforma a margem de tempo (0.5s) em número de amostras (frames)
        amostras_corte = int(margem_corte_seg * sr)
        duracao_voz_amostras = len(y_voz)
        
        # 3. Lógica de segurança para o corte:
        # Verifica se o áudio é longo o suficiente para cortar as margens com segurança.
        if duracao_voz_amostras > (2 * amostras_corte):
            # Recorta exatamente 0.5s do início e 0.5s do final
            y_estavel = y_voz[amostras_corte : -amostras_corte]
        else:
            # Caso de exceção: Se o paciente falou muito pouco (ex: < 1 segundo),
            # o corte de 0.5s apagaria o áudio todo. Então, pegamos apenas o 1/3 central.
            terco = duracao_voz_amostras // 3
            if terco > 0:
                y_estavel = y_voz[terco : 2 * terco]
            else:
                y_estavel = y_voz
                
        # 4. Sobrescreve o arquivo temporário original com o trecho estabilizado.
        # Assim, o Parselmouth no Módulo 3 lerá os dados já limpos automaticamente.
        sf.write(audio_path, y_estavel, sr)
        
        return audio_path
        
    except Exception as e:
        print(f"Erro ao isolar trecho estável de {audio_path}. Mantendo original. Erro: {e}")
        return audio_path

def cleanup_temp_files(paths):
    for path in paths:
        if path and os.path.exists(path) and tempfile.gettempdir() in path:
            try:
                os.remove(path)
            except:
                pass

# =====================================================================
# MÓDULO 3: CIÊNCIA FONOAUDIOLÓGICA (EXTRAÇÃO DE FEATURES)
# =====================================================================

def extract_perturbation_noise(audio_path):
    if not audio_path:
        return [None] * 5
        
    try:
        snd = parselmouth.Sound(audio_path)
        point_process = parselmouth.praat.call(snd, "To PointProcess (periodic, cc)", 75.0, 600.0)
        
        # Como o áudio já foi cortado no Módulo 4, p_inicio e p_fim em 0.0
        # farão o Praat analisar 100% do novo arquivo, que agora só contém o trecho estável.
        p_inicio, p_fim = 0.0, 0.0
        min_period, max_period = 0.0001, 0.02
        max_period_factor = 1.3
        max_amp_factor = 1.6
        
        jitter_loc = parselmouth.praat.call(point_process, "Get jitter (local)", p_inicio, p_fim, min_period, max_period, max_period_factor)
        ppq5 = parselmouth.praat.call(point_process, "Get jitter (ppq5)", p_inicio, p_fim, min_period, max_period, max_period_factor)
        
        shimmer_loc = parselmouth.praat.call([snd, point_process], "Get shimmer (local)", p_inicio, p_fim, min_period, max_period, max_period_factor, max_amp_factor)
        apq11 = parselmouth.praat.call([snd, point_process], "Get shimmer (apq11)", p_inicio, p_fim, min_period, max_period, max_period_factor, max_amp_factor)
        
        harmonicity = parselmouth.praat.call(snd, "To Harmonicity (cc)", 0.01, 75.0, 0.1, 1.0)
        hnr = parselmouth.praat.call(harmonicity, "Get mean", 0.0, 0.0)
        
        return [jitter_loc, ppq5, shimmer_loc, apq11, hnr]
    except Exception as e:
        print(f"Erro ao calcular Perturbação Acústica: {e}")
        return [None] * 5

def extract_cepstral_cpp(audio_path):
    if not audio_path:
        return None, None
    try:
        snd = parselmouth.Sound(audio_path)
        cepstrogram = parselmouth.praat.call(snd, "To PowerCepstrogram", 60.0, 0.002, 5000.0, 50.0)
        
        num_frames = parselmouth.praat.call(cepstrogram, "Get number of frames")
        cpp_values = []
        
        for i in range(1, num_frames + 1):
            val = parselmouth.praat.call(cepstrogram, "Get peak prominence", i, 60.0, 330.0, "Parabolic", 0.001, 0.05, "Straight", "Robust")
            if not np.isnan(val):
                cpp_values.append(val)
                
        if cpp_values:
            return np.mean(cpp_values), np.std(cpp_values)
        return None, None
    except Exception as e:
        print(f"Erro ao calcular CPP/CPP SD: {e}")
        return None, None

def extract_vsa(audio_a, audio_i, audio_u):
    def get_f1_f2(audio_path):
        if not audio_path:
            return None, None
        try:
            snd = parselmouth.Sound(audio_path)
            formants = snd.to_formant_burg()
            intensity = snd.to_intensity()
            
            f1_list, f2_list = [], []
            
            for t in np.arange(0, snd.duration, 0.05): 
                int_val = intensity.get_value(t)
                if int_val and int_val > 50.0:
                    f1 = formants.get_value_at_time(1, t) 
                    f2 = formants.get_value_at_time(2, t)
                    
                    if not np.isnan(f1): f1_list.append(f1)
                    if not np.isnan(f2): f2_list.append(f2)
                    
            f1_mean = np.mean(f1_list) if f1_list else None
            f2_mean = np.mean(f2_list) if f2_list else None
            return f1_mean, f2_mean
        except Exception:
            return None, None
            
    f1_a, f2_a = get_f1_f2(audio_a) 
    f1_i, f2_i = get_f1_f2(audio_i)
    f1_u, f2_u = get_f1_f2(audio_u) 
    
    if all(v is not None for v in [f1_a, f2_a, f1_i, f2_i, f1_u, f2_u]):
        vsa = 0.5 * abs(f2_a*(f1_i - f1_u) + f2_i*(f1_u - f1_a) + f2_u*(f1_a - f1_i))
        return vsa
    return None

def extract_f0_stats(audio_path):
    if not audio_path:
        return None, None
    try:
        snd = parselmouth.Sound(audio_path)
        pitch = snd.to_pitch()
        pitch_values = pitch.selected_array['frequency'] 
        pitch_values = pitch_values[pitch_values > 0]
        
        if len(pitch_values) > 0:
            return np.mean(pitch_values), np.std(pitch_values)
        return None, None
    except Exception:
        return None, None

def extract_mfcc_and_dynamics(audio_path):
    empty_return = [None] * 80 
    
    if not audio_path:
        return empty_return
        
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        delta_mfccs = librosa.feature.delta(mfccs)
        delta2_mfccs = librosa.feature.delta(mfccs, order=2)
        zcr = librosa.feature.zero_crossing_rate(y)
        
        mfccs_mean = np.mean(mfccs, axis=1).tolist()
        mfccs_std = np.std(mfccs, axis=1).tolist()
        
        delta_mean = np.mean(delta_mfccs, axis=1).tolist()
        delta_std = np.std(delta_mfccs, axis=1).tolist()
        
        delta2_mean = np.mean(delta2_mfccs, axis=1).tolist()
        delta2_std = np.std(delta2_mfccs, axis=1).tolist()
        
        zcr_mean = [np.mean(zcr)]
        zcr_std = [np.std(zcr)]
        
        super_vector = mfccs_mean + mfccs_std + delta_mean + delta_std + delta2_mean + delta2_std + zcr_mean + zcr_std
        return super_vector
        
    except Exception as e:
        print(f"Erro na extração espectral: {e}")
        return empty_return

def extract_speech_rate(audio_path):
    if not audio_path:
        return None, None, None
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=256, backtrack=True)
        
        non_mute_intervals = librosa.effects.split(y, top_db=25)
        duration = librosa.get_duration(y=y, sr=sr)
        speaking_duration = sum([(end - start)/sr for start, end in non_mute_intervals])
        pauses_count = max(0, len(non_mute_intervals) - 1)
        syllables_count = len(onsets)
        
        speech_rate = syllables_count / (duration / 60.0) if duration > 0 else 0
        return speech_rate, pauses_count, speaking_duration
    except Exception:
        return None, None, None

def extract_temporal_rhythm(audio_path):
    if not audio_path:
        return None, None
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=256, units='time', backtrack=True)
        
        if len(onsets) > 1:
            intervals = np.diff(onsets)
            return len(onsets), np.std(intervals)
            
        return len(onsets), None
    except Exception:
        return None, None

def extract_intelligibility_wer(audio_path, whisper_model, texto_referencia):
    if not audio_path:
        return None
        
    try:
        result = whisper_model.transcribe(audio_path, language="pt")
        texto_transcrito = result["text"]
        
        referencia_clean = texto_referencia.lower().strip()
        transcrito_clean = texto_transcrito.lower().strip()
        
        error_rate = jiwer.wer(referencia_clean, transcrito_clean)
        
        wer_percent = error_rate * 100
        return wer_percent
    except Exception as e:
        print(f"Erro na análise de Inteligibilidade (Whisper): {e}")
        return None

# =====================================================================
# MÓDULO 4: ORQUESTRADOR DB (CRIAÇÃO DO DATASET)
# =====================================================================

def criar_dataset_pacientes():
    print("Iniciando varredura geral de extração de features...")

    TEXTO_FABULA = "O Vento Norte e o Sol discutiam qual dos dois era o mais forte, quando surgiu um viajante envolto em uma capa. Eles concordaram que aquele que fizesse o viajante tirar a capa primeiro seria considerado o mais forte."
    
    print("[IA] Carregando o modelo Whisper 'base' na memória... (Pode demorar na 1ª vez)")
    try:
        modelo_whisper = whisper.load_model("base")
    except Exception as e:
        print(f"Falha ao carregar Whisper. Verifique se o FFmpeg está instalado. Erro: {e}")
        return

    data = [] 
    patients = Patient.objects.all()
    print(f"Total de pacientes identificados no Banco ORM Principal: {patients.count()}")
    
    for patient in patients:
        print(f"-> Processando áudio do paciente: {patient.name}")
        recordings = patient.recordings.all()
        recs_dict = {rec.task_type: rec for rec in recordings}
        
        audio_a = get_audio_path(recs_dict.get('FONACAO_A'))
        audio_i = get_audio_path(recs_dict.get('FONACAO_I'))
        audio_u = get_audio_path(recs_dict.get('FONACAO_U'))
        audio_ddk = get_audio_path(recs_dict.get('DIADOCOCINESIA'))
        audio_leitura = get_audio_path(recs_dict.get('LEITURA'))
        
        # [MODIFICAÇÃO 3]: Aplicação do isolamento estrito de fonação.
        # Atenção Metodológica: O filtro é aplicado EXCLUSIVAMENTE nas vogais.
        # Aplicar isso na leitura ou DDK cortaria as primeiras e últimas palavras do texto.
        audio_a = isolar_trecho_estavel(audio_a)
        audio_i = isolar_trecho_estavel(audio_i)
        audio_u = isolar_trecho_estavel(audio_u)
        
        # CÁLCULOS
        perturbacao = extract_perturbation_noise(audio_a)
        
        cpp_vogal_mean, cpp_vogal_std = extract_cepstral_cpp(audio_a)
        cpp_leitura_mean, cpp_leitura_std = extract_cepstral_cpp(audio_leitura)
        
        # O cálculo do VSA agora usará as três vogais purificadas
        vsa = extract_vsa(audio_a, audio_i, audio_u)
        
        f0_mean, f0_std = extract_f0_stats(audio_leitura)
        speech_rate, pauses_count, speaking_duration = extract_speech_rate(audio_leitura)
        ddk_count, ddk_regularity = extract_temporal_rhythm(audio_ddk)
        features_espectrais = extract_mfcc_and_dynamics(audio_leitura) 
        intelligibility = extract_intelligibility_wer(audio_leitura, modelo_whisper, TEXTO_FABULA)
        
        idade = ""
        if patient.birth_date:
            from datetime import date
            today = date.today()
            idade = today.year - patient.birth_date.year - ((today.month, today.day) < (patient.birth_date.month, patient.birth_date.day))
            
        row = {
            'paciente_id': patient.id,
            'nome': patient.name,
            'idade': idade,
            'sexo': patient.get_gender_display(),
            'diagnostico': patient.get_diagnosis_display(),            
            
            'inteligibilidade_wer_percent': intelligibility,
            
            'jitter_local': perturbacao[0],
            'jitter_ppq5': perturbacao[1],
            'shimmer_local': perturbacao[2],
            'shimmer_apq11': perturbacao[3],
            'hnr': perturbacao[4],
            
            'cpp_vogal_mean': cpp_vogal_mean,
            'cpp_vogal_std': cpp_vogal_std,
            'cpp_leitura_mean': cpp_leitura_mean,
            'cpp_leitura_std': cpp_leitura_std,
            
            'vsa': vsa,
            'f0_mean': f0_mean,
            'f0_std': f0_std,
            'speech_rate': speech_rate,
            'pauses_count': pauses_count,
            'speaking_duration': speaking_duration,
            'ddk_syllables_count': ddk_count,
            'ddk_regularity_std': ddk_regularity
        }
        
        for i, val in enumerate(features_espectrais):
            if i < 13: row[f'mfcc_mean_{i+1}'] = val
            elif i < 26: row[f'mfcc_std_{i-12}'] = val
            elif i < 39: row[f'delta_mfcc_mean_{i-25}'] = val
            elif i < 52: row[f'delta_mfcc_std_{i-38}'] = val
            elif i < 65: row[f'delta2_mfcc_mean_{i-51}'] = val
            elif i < 78: row[f'delta2_mfcc_std_{i-64}'] = val
            elif i == 78: row['zcr_mean'] = val
            elif i == 79: row['zcr_std'] = val
            
        data.append(row)
        
        # O cleanup exclui tanto os arquivos brutos quanto os sobrescritos (limpos)
        cleanup_temp_files([audio_a, audio_i, audio_u, audio_ddk, audio_leitura])
        
    df = pd.DataFrame(data)
    df.to_csv('dataset_features_ela.csv', index=False)
    
    print("\n[+] Operação Bem Sucedida! Dataset salvo como 'dataset_features_ela.csv'.")

if __name__ == "__main__":
    criar_dataset_pacientes()