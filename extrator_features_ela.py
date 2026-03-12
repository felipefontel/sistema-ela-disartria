import os
import django
import pandas as pd
import numpy as np
import tempfile

# =====================================================================
# MÓDULO 1: CONFIGURAÇÃO INICIAL DO AMBIENTE DJANGO
# =====================================================================
# Por que fazer isso? 
# Este arquivo (extrator_features_ela.py) é um script executado "por fora" do servidor (stand-alone).
# Para que ele consiga ler o banco de dados (SQLite/PostgreSQL) e puxar a lista de pacientes 
# que nós salvamos no painel web, precisamos forçar o Python a inicializar o "cérebro" do Django primeiro.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app_ela.settings')
django.setup()

# =====================================================================
# MÓDULO 2: IMPORTAÇÃO DAS BIBLIOTECAS CIENTÍFICAS
# =====================================================================
# Librosa: Uma das bibliotecas mais poderosas do mundo para análise de música e áudio no Python.
# Usamos o Librosa principalmente para matemática de ritmo (descobrir onde ocorrem sílabas) e 
# para extrair os MFCCs (Filtros que descobrem o formato interno "Timbre" do tubo vocal).
import librosa

# Parselmouth: É o motor do famoso "Praat" (o software usado por 9 dentre 10 fonoaudiólogos e linguistas).
# O Praat foi escrito em C/C++ na Holanda. O Parselmouth é uma ponte que nos permite rodar os 
# exatos mesmos algoritmos padrão-ouro do Praat diretamente aqui pelo Python, sem precisar abrir o programa.
import parselmouth

# Importamos a "Entidade" Paciente do nosso banco de dados. 
# Dela, podemos facilmente acessar as gravações vinculadas (.recordings.all())
from core.models import Patient

# =====================================================================
# MÓDULO 3: INFRAESTRUTURA DE PROCESSAMENTO DE ARQUIVOS (HELPERS)
# =====================================================================

def get_audio_path(recording):
    """
    Função Helper Principal: Como o Parselmouth e o Librosa são ferramentas que exigem
    ler um arquivo FÍSICO (em disco, terminando em .wav, com caminho c:/pasta/som.wav), 
    nós precisamos garantir que o áudio do banco de dados possa ser lido.

    Se o sistema estiver hospedado na Nuvem (como Azure ou AWS S3), o áudio é apenas 
    uma URL online e não um arquivo local. Essa função resolve isso bajando o áudio 
    da nuvem e salvando temporariamente num arquivo escondido no HD do servidor.
    """
    # Se o paciente "pulou" essa gravação e não deitou dado no banco, retorna Vazio.
    if not recording or not recording.audio_file:
        return None
        
    try:
        # TENTATIVA 1: Ambiente Local (Ex: Rodando no seu próprio PC no C:\...)
        # Se funcionar, maravilhoso! Ele acha e devolve de cara o caminho absoluto.
        path = recording.audio_file.path
        if os.path.exists(path):
            return path
    except NotImplementedError:
        # Se o sistema responder "Não sei pegar o path local! Está na nuvem!" (NotImplementedError),
        # nós engolimos o erro (pass) e partimos pro Plano B abaixo.
        pass
        
    try:
        # TENTATIVA 2 (PLANO B): Nuvem (Azure Blob, S3, etc)
        # 1. Fazemos download de todo o streaming bruto (os bytes da música)
        file_content = recording.audio_file.read()
        
        # 2. Descobrimos se é um .wav, .mp3, etc.
        suffix = os.path.splitext(recording.audio_file.name)[-1]
        
        # 3. Mandamos o Windows/Linux criar um arquivo falso/temporário (ex: Temp/som_92837.wav)
        # O delete=False significa que nós vamos avisar quando pode deletar manualmente, 
        # para a librosa ter tempo de abrir antes que o Windows apague sozinho.
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.write(file_content)
        temp_file.close() # Fecha a "caneta" (modo de edição) para a librosa poder "ler".
        
        # 4. Retorna para o cálculo a rota desse arquivo temporário recém-criado.
        return temp_file.name 
    except Exception as e:
        print(f"Erro ao carregar ou baixar arquivo de áudio: {e}")
        return None

def cleanup_temp_files(paths):
    """
    Função do Lixeiro: Depois que a máquina calcular o paciente, ela DEVE ser limpa.
    Imagina processar 5.000 pacientes: criaríamos 25.000 áudios "falsos" no servidor
    até estourar todo o HD. Essa função deleta os arquivos pós-processados.
    """
    for path in paths:
        # Se o caminho existir E tiver "Temp" (ou /tmp) na string (garantia de não deletar coisa errada do C:\)
        if path and os.path.exists(path) and tempfile.gettempdir() in path:
            try:
                os.remove(path) # Avisa ao SO para formatar/excluir o arquivo.
            except:
                pass


# =====================================================================
# MÓDULO 4: CIÊNCIA FONOAUDIOLÓGICA (EXTRAÇÃO DE FEATURES / PARÂMETROS)
# =====================================================================

def extract_jitter_shimmer_hnr(audio_path):
    """
    FEATURE 1: Instabilidade Fonatória e Ruído Vocal. (Fonação da Vogal /A/)
    
    Contexto da ELA: A ELA bulbar gera hipertonia/espasticidade ou flacidez na musculatura da laringe. 
    Isso faz as pregas vocais não fecharem bem e vibrarem em caos. O Praat consegue medir 
    isso microscopicamente a cada milissegundo de vibração.
    
    1. Jitter: Avalia apenas a FREQUÊNCIA (Pitch). Se o ciclo de onda tem 100Hz e 
       logo em seguida ele treme e cai pra 95Hz, e sobe pra 102Hz. Essa "tremidinha" é o Jitter (Aspereza).
    2. Shimmer: Avalia apenas a AMPLITUDE (Volume/Força). Se a força do sopro for caindo 
       logo em seguida ao longo de milissegundos sem sustentação.
    3. HNR: Harmonics-to-Noise Ratio. Razão Harmônico-Ruído. Uma voz saudável é como uma 
       viola limpa afinada (alta harmonia). Vozes doentes "vazam ar", gerando um som sujo que o 
       computador lê como ruído estático em cima da onda musical. Pacientes de ELA têm HNR muito baixo.
    """
    if not audio_path:
        return None, None, None
        
    try:
        # Carrega o áudio no kernel do Praat
        snd = parselmouth.Sound(audio_path)
        
        # 1. PASSO FUNDAMENTAL: "PointProcess" (Marcação de Pulso Glótico).
        # Pra medir mudança de vibração, o Praat precisa primeiro achar o exato momento que a prega vocal 
        # bateu palma (abriu/fechou). Os valores de 75 até 600 Hz informados na funçao
        # são basicamente os "limites humanos". Um homem grave dá ~100Hz. Uma criança dá ~300Hz. 
        # Estamos mandando o programa focar só no intervalo que a biologia produz.
        point_process = parselmouth.praat.call(snd, "To PointProcess (periodic, cc)", 75.0, 600.0)
        
        # 2. Get Jitter: Com todos os "Pulsos Cardíacos" mapeados, aplicamos um algoritmo 
        # do tipo "local" (Jitter Absoluto), que é e mais clássico entre médicos 
        # (varrendo distâncias absolutas de ciclo a ciclo).
        jitter = parselmouth.praat.call(point_process, "Get jitter (local)", 0.0, 0.0, 0.0001, 0.02, 1.3)
        
        # 3. Get Shimmer: Funciona igual o Jitter, mas pra Força da onda. Precisamos passar DUAS coisas aqui 
        # num array: O som em si [snd] para medir tamanho da onda + [point_process] para saber onde as ondas começam.
        shimmer = parselmouth.praat.call([snd, point_process], "Get shimmer (local)", 0.0, 0.0, 0.0001, 0.02, 1.3, 1.6)
        
        # 4. Get HNR: Separa a pureza sonora total da "chiadeira" e gera uma razão.
        harmonicity = parselmouth.praat.call(snd, "To Harmonicity (cc)", 0.01, 75.0, 0.1, 1.0)
        hnr = parselmouth.praat.call(harmonicity, "Get mean", 0.0, 0.0)
        
        return jitter, shimmer, hnr
    except Exception as e:
        print(f"Erro ao calcular Instabilidade de {audio_path}: {e}")
        return None, None, None


def extract_vsa(audio_a, audio_i, audio_u):
    """
    FEATURE 2: Vowel Space Area (VSA) / Área do Espaço Vocálico (A - I - U).
    
    Contexto Crítico na ELA: Todo fisioterapeuta/fonoaudiólogo sabe: o que faz a Letra A e a 
    Letra I soarem diferentes não é a Garganta, é o FORMATO DA BOCA.
    A ressonância que capta formato da boca se chama FORMANTES.
    - FORMANTES F1 controlam a Abertura de mandíbula (A boca abriu muito ou está quase fechada?)
    - FORMANTES F2 controlam a Língua (A língua está tocando os dentes na frente, ou retraída no céu da boca atrás?)
    
    Como na ELA ocorre a atrofia rápida da musculatura da Língua, as pessoas falam com os músculos "moles",
    isso é conhecido como HIPOCINESIA ARTICULATÓRIA (sem movimento). Como resultado, Saudáveis conseguem 
    esticar extremos nos números matemáticos do F1/F2 gerando um gráfico gigante. Já os Doentes de ELA 
    falam com as vogais se misturando e centralizadas ("Centralização Vocálica"), um gráfico pequeno esmagado!
    """
    
    # Esta é uma função aninhada (uma sub-ajudante). Só ela sabe extrair o F1 e F2 de uma vogal crua.
    def get_f1_f2(audio_path):
        if not audio_path:
            return None, None
        try:
            snd = parselmouth.Sound(audio_path)
            # O mundo científico da conversão de tubos acústicos quase não tem rivais à aproximação linear de 'Burg'.
            # Esse método converte o som gravado e descobre (em Hertz) onde é que reverberou o osso/laringe da pessoa.
            formants = snd.to_formant_burg()
            
            f1_list, f2_list = [], []
            
            # Percorremos a timeline do áudio da pessoa, analisando a musculatura a cada 0.05 milissegundos!
            for t in np.arange(0, snd.duration, 0.05): 
                # Retorna em Hertz a medida (ex: se F1 do João der 900 Hertz no /a/. Significa que aos t=0.05 segundos, João abriu as cordas e afundou bem a língua).
                f1 = formants.get_value_at_time(1, t) 
                f2 = formants.get_value_at_time(2, t)
                
                # O if garante que não puxamos um erro "Not A Number / Vazio / Mudo". Só puxamos dados válidos.
                if not np.isnan(f1): f1_list.append(f1)
                if not np.isnan(f2): f2_list.append(f2)
                
            # O formante muda durante o ar da gravação. Tiramos a "Média Geral" que vai representar o Paciente.
            f1_mean = np.mean(f1_list) if f1_list else None
            f2_mean = np.mean(f2_list) if f2_list else None
            return f1_mean, f2_mean
        except Exception as e:
            return None, None
            
    # Executamos as 3 vogais fundamentais "Cardeais" cruciais requeridas pra avaliação VSA global:
    # A = Vogal inferior de abertura forte
    f1_a, f2_a = get_f1_f2(audio_a) 
    # I = Vogal antero-superior (Fechada, alta e a língua explode nos dentes)
    f1_i, f2_i = get_f1_f2(audio_i)
    # U = Vogal póstero-superior (Fechada, altíssima, e a língua embola encolhida rasgando a úvula/fim da garganta)
    f1_u, f2_u = get_f1_f2(audio_u) 
    
    # Se todas as 6 informações vieram lidas com sucesso, é hora da fórmula de geometria escolar (Área de um Triângulo Bidimensional) 
    # Trocando X por F1 e Y por F2! Se estiver esmagado, a Inteligência Artificial vai reconhecer Doença nos números.
    if all(v is not None for v in [f1_a, f2_a, f1_i, f2_i, f1_u, f2_u]):
        vsa = 0.5 * abs(f2_a*(f1_i - f1_u) + f2_i*(f1_u - f1_a) + f2_u*(f1_a - f1_i))
        return vsa
    return None


def extract_f0_stats(audio_path):
    """
    FEATURE 3: Descritores Prosódicos F0. (Tarefa de Leitura da fábula "O Vento e o Sol")
    
    Contexto ELA: Frequência Fundamental (F0) é o tom "musical" principal que faz a voz ser aguda ou grossa.
    Na Disartria da Esclerose Lateral, a degeneração muscular causa "Monotonismo" ou Mono-Pitch.
    O paciente é incapaz de alterar os tons vocais numa entonação interrogativa ("?") ou animada ("!").  A fala sai reta, robotizada.
    Portanto, nós buscamos capturar a média musical dele, mas, principalmente o `f0_std` (Desvio Padrão).
    Um std que tende a zero diz-nos matematicamente que o F0 não "variou", indiciando severo empobrecimento de prosódia.
    """
    if not audio_path:
        return None, None
    try:
        snd = parselmouth.Sound(audio_path)
        # to_pitch extrai toda a variação principal musical ignorando ruídos do quarto/ecos ambientais
        pitch = snd.to_pitch()
        
        # O Praat retorna os valores, mas há um truque focado em silêncio: Nas respiradas e as pausas de fôlego 
        # e palavras, não existe voz, ali não há Hz, aí ele envia `0.0` Hertz. Se mantivermos Zeros no array, 
        # a média vai ficar errada e "abaixada", caindo drasticamente a pontuação dele.
        pitch_values = pitch.selected_array['frequency'] 
        
        # Super Filtro Pandas/Numpy: Varremos e mantemos em mãos somente quadros estritos maiores que Zero positivo (quando houve verdadeiramente fala expressa).
        pitch_values = pitch_values[pitch_values > 0]
        
        if len(pitch_values) > 0:
            return np.mean(pitch_values), np.std(pitch_values)
        return None, None
    except Exception as e:
        return None, None


def extract_mfcc_and_dynamics(audio_path):
    """
    FEATURE 4: Descritores Espectrais e Dinâmicos (MFCCs, Deltas e ZCR).
    
    Contexto ELA/Disartria: O MFCC puro tira uma "foto" do formato do trato vocal. 
    Para detectar a "fala arrastada" (slurring) e a lentidão da língua entre uma consoante 
    e outra, precisamos da cinemática:
    - Delta MFCC: Velocidade da mudança articulatória.
    - Delta-Delta MFCC: Aceleração da musculatura.
    - ZCR (Zero-Crossing Rate): Taxa de fricção/ruído das consoantes plosivas.
    """
    # Como passaremos a retornar 40 colunas em vez de 13 (13 MFCC + 13 Delta + 13 Delta-Delta + 1 ZCR)
    empty_return = [None] * 40 
    
    if not audio_path:
        return empty_return
        
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        # 1. MFCC Estático (13 coeficientes)
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        
        # 2. Delta MFCC (Velocidade)
        delta_mfccs = librosa.feature.delta(mfccs)
        
        # 3. Delta-Delta MFCC (Aceleração)
        delta2_mfccs = librosa.feature.delta(mfccs, order=2)
        
        # 4. Zero-Crossing Rate (Atrito das consoantes)
        zcr = librosa.feature.zero_crossing_rate(y)
        
        # Achata as matrizes tirando a média temporal
        mfccs_mean = np.mean(mfccs, axis=1).tolist()
        delta_mean = np.mean(delta_mfccs, axis=1).tolist()
        delta2_mean = np.mean(delta2_mfccs, axis=1).tolist()
        zcr_mean = [np.mean(zcr)]
        
        # Concatena em um vetor 1D de 40 posições
        super_vector = mfccs_mean + delta_mean + delta2_mean + zcr_mean
        return super_vector
        
    except Exception as e:
        print(f"Erro na extração espectral dinâmica de {audio_path}: {e}")
        return empty_return


def extract_speech_rate(audio_path):
    """
    FEATURE 5: Parâmetros Temporais Corridos - Velocidade de Leitura & Respiradas. (Tarefa de Leitura da fábula longa)
    
    Contexto da Avaliação Bulbar em Fonoaudiologia: 
    A fraqueza muscular geral atinge o peito, laringe e faringe, causando Bradicinesia Articulatória (tudo em câmera lenta e arrastado) 
    e grave Incapacidade Vital (Capacidade do pulmão encher). Um paciente doente:
    1 - Vai demorar anos pra finalizar a frase (Fala arrastada, rate muito baixo e prolongado).
    2 - Vai interromper no meio de palavras pra respirar porque o ar escapuliu da laringe estendida (muitas pauses_counts).
    A matemática do array do `Librosa` usa Decibéis + Picos Agudos do envelope pra contar separadamente as sílabas soltas do sopro de ruído no fundo.
    """
    if not audio_path:
        return None, None, None
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        # 'Onset' Strength (Força Inicial/Ataque). A biblioteca detectará na música picos fortes 
        # seguidos de sons. Numa música falada sem bateria, todo ONSET em 99% das vezes é o começo "explodido" de uma nova Sílaba!
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        
        # Split! Muta intervals significa picotar o áudio com a regrégia dos "20 Decibéis Acima do Som Base de fundo". 
        # Tudo que a câmera não ver voz passante e decair do topo por -20 db, nós assumimos liminarmente que o Paciente PAROU pra respirar!
        non_mute_intervals = librosa.effects.split(y, top_db=20)
        
        # Descobre tamanho real da gravação crua pra cálculos puros em segundos de timeline
        duration = librosa.get_duration(y=y, sr=sr)
        
        # Transforma o vetor de intervalos cortados em fatias e soma ativamente quanto tempo real da fita contendo o som audível (Falando ativamente).
        speaking_duration = sum([(end - start)/sr for start, end in non_mute_intervals])
        
        # Contagem de Pausas (Se tivemos 5 ilhas ativas de fala num recorte total gráfico.. é porque no limite do meio existiram quebras mudas.. ou seja.. 4 pausas).
        pauses_count = max(0, len(non_mute_intervals) - 1)
        
        # Total contagem teórica estimada de Sílabas que explodiram o Onset na fita (Exemplo: Na frase 'trator' a onda terá dois grandes onsets no T e T)
        syllables_count = len(onsets)
        
        # Regra de Três Temporal: (Quantidade total feita dividido pelo Tempo do filme expresso em casas decimais dos "Minutos" rodados).
        speech_rate = syllables_count / (duration / 60.0) if duration > 0 else 0
        
        return speech_rate, pauses_count, speaking_duration
    except Exception:
        return None, None, None


def extract_temporal_rhythm(audio_path):
    """
    FEATURE 6: Parâmetros Temporais Rítmicos - Prova de Diadococinesia Alternada (DDK)
    
    Contexto Analítico da DDK: Dizer repetições sequenciais PA-TA-KA o mais rápido que puder é o maior 
    desafio neurológico motor. Para o paciente acertar PA e cruzar perfeitamente pro TA, o cérebro tem 
    que fechar os lábios inteiros (Pa), soltá-los e subir a língua correndo no céu da boca atrás dos incisivos dentais (Ta) e arrastá-la no fundo.
    Em pacientes com degeneração do motoneurônio (ELA), há "Gagueiras" neurológicas imperceptíveis.
    O desvio padrão (STD do intervalo) revelará os "saltos" fora do ritmo base em milésimos de erro! Um STD perfeito tange no Zero.
    """
    if not audio_path:
        return None, None
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        # Detecta explosões iniciais silábicas exatamente assim como calculamos em Velocidade (Speech Rate)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        # DIFERENCIAL CHAVE DA CONFIGURAÇÃO (UNITS='TIME'). Quero que a biblioteca retorne não `frames/pixels` de dados e sim
        # retorne uma estendida Array crua contendo exata precisão dos Tempos Marcadores Físicos de Ataque no eixo cartesiano. (Exemplo:  Ataque a 0.12 segundos.. 0.44s.. 0.7s)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units='time')
        
        if len(onsets) > 1:
            # np.diff é a melhor engenharia em subtrações de array contínuas. 
            # Subtrai ativamente a distãncia temporal absoluta entre cada "Sílaba e sua sucessora futura" no array de Onsets.
            # O array resultante conteria: [tempo percorrido em segundos do P pro A, depois do A pro T...]
            intervals = np.diff(onsets)
            
            # length de Onsets informará no fim o Número de Ataque de Batidas Motoras que esse sujeito gerou em 10 segundos ininterruptos, 
            # E Acompanharemos da Variação STD Rítmica das Batidas de Tambor Alternantes (A disritmia patológica revelada num número flutuante).
            return len(onsets), np.std(intervals)
            
        return len(onsets), None
    except Exception:
        return None, None

# =====================================================================
# MÓDULO 5: O CÉREBRO CONTROLADOR MESTRE DO FLUXO (ORQUESTRADOR DB)
# =====================================================================

def criar_dataset_pacientes():
    """
    A FUNÇÃO PRINCIPAL. 
    1. Liga-se a conexão ORM via objetos do Banco.
    2. Encontra a listagem macro de todos os indivíduos internados no Database do Sistema Web.
    3. Passa cada uma das rotinas de Extrações Científicas em todos eles.
    4. Aglomera individualmente, concatena cada coluna/feature como Chaves para uma tabela geral bidimensional.
    5. Grava fisicamente na pasta base um 'arquivo relatorial numérico denso (.CSV) contendo o 'Ground Truth' preparado pra Redes Neurais/XGBoost.
    """
    print("Iniciando varredura geral de extração de features...")
    
    data = [] # O vetor "Tabela Infinita em Matriz" do Dataset.
    
    patients = Patient.objects.all()
    print(f"Total de pacientes identificados no Banco ORM Principal: {patients.count()}")
    
    # ITERAÇÃO GLOBAL DE VARREDURA DOS INDIVÍDUOS. O Loop Principal base da IA de extração.
    for patient in patients:
        print(f"-> Processando áudio do paciente: {patient.name} | Doença: {patient.get_diagnosis_display()}")
        
        # O banco grava o Paciente -> E Gravações separadamente linkadas numa FK (Foreign Key "recordings")
        recordings = patient.recordings.all()
        
        # Filtro em dicionário otimizador O(1). Em vez de rodar 5 varredouras for, converto os models rapidamente 
        # de forma associativa onde a key é o tipo (Ex: 'LEITURA' -> Objeto Model da Gravação e Caminho C:)
        recs_dict = {rec.task_type: rec for rec in recordings}
        
        # Preparamos variáveis baixando ativamente pro processador em RAM da máquina principal usando a Lógica de Resgate na Nuvem.
        audio_a = get_audio_path(recs_dict.get('FONACAO_A'))
        audio_i = get_audio_path(recs_dict.get('FONACAO_I'))
        audio_u = get_audio_path(recs_dict.get('FONACAO_U'))
        audio_ddk = get_audio_path(recs_dict.get('DIADOCOCINESIA'))
        audio_leitura = get_audio_path(recs_dict.get('LEITURA'))
        
        # ==========================================================
        # FASE MATEMÁTICA: EXECUÇÃO DOS SUB-CÁLCULOS 
        # ==========================================================
        jitter_a, shimmer_a, hnr_a = extract_jitter_shimmer_hnr(audio_a)
        vsa = extract_vsa(audio_a, audio_i, audio_u)
        f0_mean, f0_std = extract_f0_stats(audio_leitura)
        speech_rate, pauses_count, speaking_duration = extract_speech_rate(audio_leitura)
        ddk_count, ddk_regularity = extract_temporal_rhythm(audio_ddk)
        # 6. Mapeia os coeficientes timbrais e dinâmicos (40 variáveis)
        features_espectrais = extract_mfcc_and_dynamics(audio_leitura)
        # ==========================================================
        
        # CONSTRUÇÃO DO METADADO "RUNTIME LABEL"
        # Precisamos empacotar a idade do usuário para que o modelo preditor aprenda se é uma questão intrínseca de idoso ou da Patologia Base.
        idade = ""
        if patient.birth_date:
            from datetime import date
            today = date.today()
            # Fórmula avançada: Diferença simples bruta anual, reduzida de verdadeiro/falso matematicamente (subtrai 1 se o Mês base local ainda não tiver passado na linha do tempo comemorativa).
            idade = today.year - patient.birth_date.year - ((today.month, today.day) < (patient.birth_date.month, patient.birth_date.day))
            
        # O PACOTE DA LINHA PACIENTE
        row = {
            'paciente_id': patient.id,          # Feature Textual Identifier Principal
            'nome': patient.name,               
            'idade': idade,                     
            'sexo': patient.get_gender_display(),
            'diagnostico': patient.get_diagnosis_display(), # << Nossa TARGET CLASSIFICATION Y (O que a rede Neural Tentará Prever via Classificador Multi-classe ou Binário futuramente)
            
            # A seguir, os vetores extraídos no formato puro "Features Contínuas Float".
            'jitter_local': jitter_a,           
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
        
        # Desempacota as 40 variáveis em colunas nominais e atrela à row
        for i, val in enumerate(features_espectrais):
            if i < 13:
                row[f'mfcc_{i+1}'] = val
            elif i < 26:
                row[f'delta_mfcc_{i-12}'] = val
            elif i < 39:
                row[f'delta2_mfcc_{i-25}'] = val
            else:
                row['zcr_mean'] = val
            
        # Linha montada com 25 colunas preenchidas atada em definitivo na coleção geral primária.
        data.append(row)
        
        # ATENÇÃO TÉCNICA!
        # Sem essa linha 'cleanup', o Windows Server da infraestrutura Nuvem fatalmente acusará "Disk Storage Exceeded / Inodes" 
        # por arquivos pendurados acumulados num cache malígno a cada geração. Apague lixos físicos sempre.
        cleanup_temp_files([audio_a, audio_i, audio_u, audio_ddk, audio_leitura])
        
    # Renderização Dataframe via Pandas
    # A biblioteca transforma listas de dicionários heterogêneas numa estrutura Tabular perfeita mapeada pronta pra Serialização e limpeza.
    df = pd.DataFrame(data)
    
    # Serialização pra Arquivo em Formato .CSV Universal Exportável
    # Passamos `index=False` para evitar aquela coluna inútil intrínseca lateral 0, 1, 2... do pandas poluindo o Dataset na exportação do Python.
    df.to_csv('dataset_features_ela.csv', index=False)
    
    print("\n[+] Operação Bem Sucedida! Extração do Protocolo Analítico Fonoaudiológico Global finalizada.")
    print("O seu relacional tabular 'dataset_features_ela.csv' se encontra pronto e populado no disco host da Aplicação Django.")

# Gatilho Primário Padrão Python
# Interlock para evitar a ativação da sub-rotina bruta ao se "Importar" o pacote para outras areas no App. 
# Garante controle via linha de terminal explícita: "python extrator_features_ela.py".
if __name__ == "__main__":
    criar_dataset_pacientes()
