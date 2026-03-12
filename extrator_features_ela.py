import os
import django
import pandas as pd
import numpy as np
import tempfile

# =====================================================================
# CONFIGURAÇÃO INICIAL DO DJANGO
# =====================================================================
# Antes de importar os modelos, precisamos configurar o ambiente Django.
# Isso permite que este script avulso acesse o banco de dados e use o 
# ORM (Object-Relational Mapping - o sistema de banco de dados do Django).
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app_ela.settings')
django.setup()

# =====================================================================
# IMPORTAÇÃO DAS BIBLIOTECAS DE PROCESSAMENTO DE ÁUDIO E MODELOS
# =====================================================================
# librosa: excelente pacote de áudio (usado para detecção de silêncio, ritmo e MFCCs).
import librosa
# parselmouth: interface Python para o Praat (software de bio-acústica padrão-ouro em Fonoaudiologia).
import parselmouth
# Importa o modelo Patient para buscar os dados diretamente do banco de dados do aplicativo.
from core.models import Patient

# =====================================================================
# FUNÇÕES AUXILIARES
# =====================================================================

def get_audio_path(recording):
    """
    Função Helper: Obtém o caminho do áudio no sistema ou baixa temporariamente se estiver na nuvem (Azure Blob).
    """
    # Se a gravação não existir ou não possuir um arquivo associado, retorna Vazio (None).
    if not recording or not recording.audio_file:
        return None
        
    try:
        # Primeiro, tentamos acessá-lo como se fosse um arquivo salvo no HD do computador/servidor web.
        path = recording.audio_file.path
        if os.path.exists(path):
            return path
    except NotImplementedError:
        # Quando usamos nuvem (Azure Blob), o arquivo não tem um caminho físico no Windows/Linux, 
        # então o Django dispara esse 'NotImplementedError'. Se acontecer, sabemos que é nuvem.
        pass
        
    try:
        # Fase Nuvem: Extrai o conteúdo em bytes (binário) através do link online.
        file_content = recording.audio_file.read()
        # Descobre a extensão do arquivo (ex: .wav, .m4a, .mp3)
        suffix = os.path.splitext(recording.audio_file.name)[-1]
        
        # Cria um arquivo temporário físico no computador. 
        # (As bibliotecas Praat e Librosa exigem ler um arquivo real salvo no disco para funcionar rápido 
        # sem sobrecarregar a memória RAM, por isso forçamos esse download provisório).
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.write(file_content)
        temp_file.close() # Libera o arquivo para que outras ferramentas possam abri-lo e ler.
        
        # Retorna a localização de onde salvamos esse áudio (ex: C:/Temp/som_abc.wav)
        return temp_file.name 
    except Exception as e:
        print(f"Erro ao carregar ou baixar arquivo de áudio: {e}")
        return None

def cleanup_temp_files(paths):
    """
    Função Helper: Remove os arquivos temporários criados pela função acima (get_audio_path).
    Extremamente vital para não lotar o Servidor quando extrairmos features de milhares de pacientes.
    """
    for path in paths:
        # Verifica se o arquivo existe e garante de novo que ele está apenas na pasta "Temp" de fato.
        if path and os.path.exists(path) and tempfile.gettempdir() in path:
            try:
                os.remove(path) # Aciona a exclusão do Sistema Operacional.
            except:
                pass # Se der falha (por uso ou negação), apenas ignora para não parar a execução geral.

# =====================================================================
# FUNÇÕES DE EXTRAÇÃO DE FEATURES ACÚSTICAS (PARÂMETROS DE ELA)
# =====================================================================

def extract_jitter_shimmer_hnr(audio_path):
    """
    1. Instabilidade Fonatória e Ruído
    Mede a instabilidade das pregas vocais, que pode apontar para fraqueza e rouquidão severa.
    - Jitter: micro-variações da Frequência de ciclo a ciclo (traduzido como aspereza/rouquidão).
    - Shimmer: micro-variações da Amplitude (Volume) de ciclo a ciclo (falha no sopro glótico).
    - HNR (Harmonic-to-Noise Ratio): mede quanto tem de som puro (harmônico) contra o "chiado" e ar vazando (ruído).
    """
    if not audio_path:
        return None, None, None
        
    try:
        # Carrega o áudio no algoritmo equivalente ao sistema "Praat"
        snd = parselmouth.Sound(audio_path)
        
        # PointProcess: é como rastrear o "batimento cardíaco" do áudio. O Praat marca cada pulsação vocal na linha do tempo.
        # Os valores de 75 Hz a 600 Hz são os tetos biológicos humanos de frequência fundamental onde a busca ocorre.
        point_process = parselmouth.praat.call(snd, "To PointProcess (periodic, cc)", 75.0, 600.0)
        
        # Mede o Jitter na modalidade "local" (a mais tradicional do protocolo médico).
        jitter = parselmouth.praat.call(point_process, "Get jitter (local)", 0.0, 0.0, 0.0001, 0.02, 1.3)
        
        # Mede o Shimmer. Ele exige comparar os pontos marcados (point_process) com as ondas originais (snd).
        shimmer = parselmouth.praat.call([snd, point_process], "Get shimmer (local)", 0.0, 0.0, 0.0001, 0.02, 1.3, 1.6)
        
        # Mede a Harmonia do Som (HNR). 
        # Valores baixos de HNR significam mais soprosidade/disfonia, indicando que a prega vocal não fecha direito (ELA Bulbar).
        harmonicity = parselmouth.praat.call(snd, "To Harmonicity (cc)", 0.01, 75.0, 0.1, 1.0)
        hnr = parselmouth.praat.call(harmonicity, "Get mean", 0.0, 0.0)
        
        return jitter, shimmer, hnr
    except Exception as e:
        print(f"Erro ao calcular Instabilidade de {audio_path}: {e}")
        return None, None, None


def extract_vsa(audio_a, audio_i, audio_u):
    """
    2. Vowel Space Area (VSA) / Área do Espaço Vocálico
    Calcula matematicamente o triângulo vocálico A-I-U. Na neurologia, isso mede indiretamente o
    grau de agilidade articulatória da pessoa (a capacidade de abrir a boca, mexer a língua rápido, etc).
    Indivíduos saudáveis geram uma área gigantesca. Disártricos têm "hipocinesia" e uma área achatada.
    """
    
    # Subfunção de ajuda para extrair os "Formantes" de uma vogal específica de forma fácil.
    def get_f1_f2(audio_path):
        if not audio_path:
            return None, None
        try:
            snd = parselmouth.Sound(audio_path)
            # Aciona o classificador de 'Burg' (muito usado pra estimar frequências de ressonância do trato oral).
            formants = snd.to_formant_burg()
            
            f1_list, f2_list = [], []
            # Percorre a linha temporal sonora analiticamente a cada 0.05 segundos
            for t in np.arange(0, snd.duration, 0.05): 
                # F1 captura o quão aberta está a boca. F2 captura o quão retraída pra trás está a base da língua.
                f1 = formants.get_value_at_time(1, t) 
                f2 = formants.get_value_at_time(2, t)
                
                # Se não retornar NotA-Number (NaN), ele empilha nas listas
                if not np.isnan(f1): f1_list.append(f1)
                if not np.isnan(f2): f2_list.append(f2)
                
            # Extrai o número representativo (a Média de Hz no corpo total do áudio) para os formantes
            f1_mean = np.mean(f1_list) if f1_list else None
            f2_mean = np.mean(f2_list) if f2_list else None
            return f1_mean, f2_mean
        except Exception as e:
            return None, None
            
    # Passo obrigatório, processamos a fonação prolongada de cada uma das 3 vogais "Cardeais"
    f1_a, f2_a = get_f1_f2(audio_a) # Ponto inferior do triângulo acústico
    f1_i, f2_i = get_f1_f2(audio_i) # Ponto frontal extremo esquerdo
    f1_u, f2_u = get_f1_f2(audio_u) # Ponto posterior extremo direito
    
    # Se obtivemos os "Coordenadas geográficas" (Hz) de X e Y das 3 vogais sem erros...
    if all(v is not None for v in [f1_a, f2_a, f1_i, f2_i, f1_u, f2_u]):
        # A fórmula matemática pura para achar a área bidimensional de um triângulo traçado num gráfico onde X é o F2 e Y é o F1:
        # 0.5 * | xA(yB - yC) + xB(yC - yA) + xC(yA - yB) |
        vsa = 0.5 * abs(f2_a*(f1_i - f1_u) + f2_i*(f1_u - f1_a) + f2_u*(f1_a - f1_i))
        return vsa
    return None


def extract_f0_stats(audio_path):
    """
    3. Descritores Prosódicos
    Extrai informações sobre a melodia básica de locução do paciente durante a Tarefa de Leitura.
    Pessoas com neurodegeneração tendem ao "Monotonismo" (voz robótica de único tom), resultando num desvio padrão mínimo.
    """
    if not audio_path:
        return None, None
    try:
        snd = parselmouth.Sound(audio_path)
        # Pitch = Linha do tempo monitorando a Frequência Fundamental unicamente.
        pitch = snd.to_pitch()
        
        # A API liberta uma matriz com toda a "trilha de notas" vocais. Valores em Zero representam silêncio absoluto.
        pitch_values = pitch.selected_array['frequency'] 
        
        # Aqui, filtramos a lista cortando forçadamente os zeros (falsos amigos que afundariam a média total)
        pitch_values = pitch_values[pitch_values > 0]
        
        if len(pitch_values) > 0:
            # np.mean(média globais) e np.std (desvio padrão: quantidade de sobes e desces da entonação melódica)
            return np.mean(pitch_values), np.std(pitch_values)
        return None, None
    except Exception as e:
        return None, None


def extract_mfcc(audio_path):
    """
    4. Descritores Espectrais e Timbrais (MFCCs)
    Extrai as informações profundas psico-físicas do formato celular da garganta condensadas em 13 bandas.
    Muito poderoso para Machine Learning captar as nuances sutis (distorções das ressonâncias faciais) da ELA.
    """
    if not audio_path:
        # Retorna 13 campos "vazios" (None) propositadamente pra preencher o DataFrame tabular e não quebrar as colunas do CSV final
        return [None]*13 
    try:
        # Aqui trocamos as abordagens para usar o Librosa do C++ acoplado no Python que é mais performático nisso (FFT).
        y, sr = librosa.load(audio_path, sr=None)
        
        # Corta a onda em dezenas de frames mínimos por segundo e tira os Coeficientes Ceptrom de 1 a 13.
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        
        # Pega a média por linha. Isso colapsa um vídeo longo num único "Frame Representante" (vetor achatado numérico de tamanho 13) 
        # que representa como é a "Cor" do som vocal desse paciente especificamente (O formato do tubo).
        mfccs_mean = np.mean(mfccs, axis=1)
        return mfccs_mean.tolist()
    except Exception as e:
        return [None]*13


def extract_speech_rate(audio_path):
    """
    5. Parâmetros Temporais Corridos - Velocidade de Leitura
    Extrai:
    - Taxa de elocução: Velocidade (sílabas/palavras por minuto, indicando bradicinesia/lentidão).
    - Contagem de Pausas: Quantas vezes quebrou a frase pra exalar ar.
    """
    if not audio_path:
        return None, None, None
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        # 'Onset' é qualquer inicio forçado e pontiagudo num som. Num áudio limpo falado, 95% dos onsets marcam a explosão de uma nova sílaba falada.
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        
        # Identifica e separa o que é voz do que é o "ruído do ar-condicionado da sala" usando 20 Decibéis do pico mestre como linha de corte e teto.
        non_mute_intervals = librosa.effects.split(y, top_db=20)
        
        # Quantos segundos de gravação rodaram na fita:
        duration = librosa.get_duration(y=y, sr=sr)
        
        # Subtrai apenas as partes das vozes (fim do sinal sonoro - inicio do sinal sonoro e converte base de samples para Segundos)
        speaking_duration = sum([(end - start)/sr for start, end in non_mute_intervals])
        
        # Base matemática clássica: para existirem N blocos de som, há que se cortar o filme N-1 vezes em silêncios (pausas).
        pauses_count = max(0, len(non_mute_intervals) - 1)
        
        # Volume bruto de impulsões fônicas silabares deduzidas onsets.
        syllables_count = len(onsets)
        
        # Taxa simples = Quantidade gerada / pelo Tatal de Minutos Expresso na fita inteira incluindo os tempos mudos pra respirar.
        speech_rate = syllables_count / (duration / 60.0) if duration > 0 else 0
        
        return speech_rate, pauses_count, speaking_duration
    except Exception:
        return None, None, None


def extract_temporal_rhythm(audio_path):
    """
    6. Parâmetros Temporais Rítmicos - Prova de Diadococinesia
    Testa a alternânica muscular acelerada "pa-ta-ka" "pa-ta-ka".
    Avalia em precisão de milésimos neurológico a regularidade automatizada ritmica da produção (se tropeça no caminho da fala).
    """
    if not audio_path:
        return None, None
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        # Aqui usamos o parâmetro especial 'units=time', para que ele libere timestamps absolutos (Em x Segundos a pessoa emitiu y).
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units='time')
        
        if len(onsets) > 1:
            # np.diff é excelente pra variação. Tem o vetor de tempo: [0.5, 1.2, 1.9, 2.7]. Ele subtrai um do adjacente e traz a distância: [0.7, 0.7, 0.8] de espaçamento de ar.
            intervals = np.diff(onsets)
            
            # Contabiliza quantos onsets rolou, e o STD (desvio das distâncias).
            # -  STD perto de zero indica Metrônomo preciso rítmico.
            # -  STD altíssimo indica gagueira/falha/assimetria no arrasto articulatório.
            return len(onsets), np.std(intervals)
            
        return len(onsets), None
    except Exception:
        return None, None

# =====================================================================
# FUNÇÃO MESTRA (CONTROLADOR E GERADOR)
# =====================================================================

def criar_dataset_pacientes():
    """
    Controlador (Loop Central): Rastreia o banco do Django (Tabela de Pacientes), baixa os áudios 
    referentes para cada sujeito mapeado e varre toda as 6 rotinas pesadas de extração explicadas 
    ali pra cima de forma automatizada por Lote, cuspindo tudo num relatorial "dataset.csv".
    """
    print("Iniciando varredura geral de extração de features...")
    
    data = [] # Lista de acúmulo temporária que vai virar o Corpo Principal do Dataset do Pandas
    
    # Via ORM nativo Django, puxamos do Banco Postgree/SQLite todavia os Cadastros
    patients = Patient.objects.all()
    print(f"Total de pacientes identificados no Banco: {patients.count()}")
    
    # Percorre de um em um Patient
    for patient in patients:
        print(f"-> Processando áudio do paciente: {patient.name} | Doença: {patient.get_diagnosis_display()}")
        
        # Resgata todas as gravações vinculadas especificamente àquele paciente rodado
        recordings = patient.recordings.all()
        
        # Filtro de dicionário pra acelerar a busca no Python (O(1)). Transforma os models em dict key-based do tipo da Tarefa: recs_dict['LEITURA']..
        recs_dict = {rec.task_type: rec for rec in recordings}
        
        # Captura do AzureNuven/HD e passa pras variáveis (retornaram None se eles não fizeram essa gravação específica)
        audio_a = get_audio_path(recs_dict.get('FONACAO_A'))
        audio_i = get_audio_path(recs_dict.get('FONACAO_I'))
        audio_u = get_audio_path(recs_dict.get('FONACAO_U'))
        audio_leitura = get_audio_path(recs_dict.get('LEITURA'))
        audio_ddk = get_audio_path(recs_dict.get('DIADOCOCINESIA'))
        
        # ========= ENVIA OS AUDIOS PARA OS 'MATH LABS' ============
        
        # 1. Ruído e fonação da Vogal Isolada /A/.
        jitter_a, shimmer_a, hnr_a = extract_jitter_shimmer_hnr(audio_a)
        
        # 2. VSA que analisa o triângulo de 3 gravações silabares de vez só.
        vsa = extract_vsa(audio_a, audio_i, audio_u)
        
        # 3. Flutuação de curva F0 baseada inteiramente na trilha de áudio narrativo gravado (LEITURA).
        f0_mean, f0_std = extract_f0_stats(audio_leitura)
        
        # 4. Taxas respiratórias e pausas na Leitura da fábula longa
        speech_rate, pauses_count, speaking_duration = extract_speech_rate(audio_leitura)
        
        # 5. Avaliação métrica rítmica das batidas de "Ta-Ta-Ta-Ta".
        ddk_count, ddk_regularity = extract_temporal_rhythm(audio_ddk)
        
        # 6. Mappea os coefiecientes timbrais na ressonância longa
        mfccs = extract_mfcc(audio_leitura)
        
        # ==========================================================
        
        # Metadado Simples: Computar idade em momento real (anos rodados) para a estatística
        idade = ""
        if patient.birth_date:
            from datetime import date
            today = date.today()
            # Fórmula padrão em lógica: Elevação subtrai em -1 da diferença do Ano atual se ele ainda não fez o Nível de Mês de Nascimento Aniversariado
            idade = today.year - patient.birth_date.year - ((today.month, today.day) < (patient.birth_date.month, patient.birth_date.day))
            
        # Instancia o "Objeto Linha" (Dicionário numérico). Todas essas chaves virarão títulozinhos das barras verticais do Excel.
        row = {
            'paciente_id': patient.id,          # ID Chave primária do Banco
            'nome': patient.name,               # Nome Explicito
            'idade': idade,                     # Demografia clínica 1
            'sexo': patient.get_gender_display(),# Demografia biológica 2 textificada "Masculino/Feminino"
            'diagnostico': patient.get_diagnosis_display(), # Label target Classificatória (Saudavel X Doente)
            'jitter_local': jitter_a,           # Inicio das features Extraídas numéricas do Praat...
            'shimmer_local': shimmer_a,
            'hnr': hnr_a,
            'vsa': vsa,
            'f0_mean': f0_mean,
            'f0_std': f0_std,
            'speech_rate': speech_rate,
            'pauses_count': pauses_count,
            'speaking_duration': speaking_duration,
            'ddk_syllables_count': ddk_count,
            'ddk_regularity_std': ddk_regularity
        }
        
        # Empacota em 13 colunazinhas finais as 13 médias geradas na Lista Bruta dos mfccs via For loop numerado
        for i, m in enumerate(mfccs):
            row[f'mfcc_{i+1}'] = m
            
        # Transfere a linha do paciente com seus 25 resultados e aloca (append) em definitivo na super-lista data.
        data.append(row)
        
        # Tchau! Exclui do computador os wavs de voz deste paciente baixados da nuvem e dá espaço pros 10 milhões do próximo na esteira
        cleanup_temp_files([audio_a, audio_i, audio_u, audio_leitura, audio_ddk])
        
    # Quando o grande laço "for patient" acabar com todos eles.. invocamos Pandas para renderizar.
    df = pd.DataFrame(data)
    
    # Salva o renderizado Pandas como um relatorial físico ".csv" exportado (index é a barra de numeração crua chata da lib, colocamos False)
    df.to_csv('dataset_features_ela.csv', index=False)
    
    print("\n[+] Extração de todos os bancos finalizada em sucesso!")
    print("O seu agrupamento CSV de dados 'dataset_features_ela.csv' já está na raiz do seu projeto.")

# Porta de Entrada do Python Scripts isolados (Trava de Segurança). Significa: "Apenas dispare as funções se o arquivo for evocado cru pelo desenvolvedor usando RUN, não engatilhe se for só um Import no ambiente web"
if __name__ == "__main__":
    criar_dataset_pacientes()
