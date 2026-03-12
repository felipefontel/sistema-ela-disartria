document.addEventListener('DOMContentLoaded', () => {
    const recordBtn = document.getElementById('recordBtn');
    const stopBtn = document.getElementById('stopBtn');
    const uploadStatus = document.getElementById('uploadStatus');
    const nextBtn = document.getElementById('nextBtn');
    const discardBtn = document.getElementById('discardBtn');
    const recordLabel = document.getElementById('recordLabel');
    const canvas = document.getElementById('audioVisualizer');
    const canvasCtx = canvas ? canvas.getContext('2d') : null;

    // Configurations passed from Django Template
    const audioConfig = document.getElementById('audioConfig');
    const patientId = audioConfig.dataset.patient;
    const taskType = audioConfig.dataset.task;
    const uploadUrl = audioConfig.dataset.uploadUrl;
    const deleteUrl = audioConfig.dataset.deleteUrl;
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    let mediaRecorder;
    let audioChunks = [];
    let currentRecordingId = null;

    // Audio animation vars
    let audioContext;
    let analyser;
    let dataArray;
    let source;
    let drawVisual;

    // Timer vars
    let recordingTimerInterval;
    let recordingSeconds = 0;
    let autoStopTimeout;
    const timerDisplay = document.getElementById('recordingTimer');
    const audioPlaybackContainer = document.getElementById('audioPlaybackContainer');
    const audioPlayback = document.getElementById('audioPlayback');
    let playbackNormalized = false;

    // CRITICAL: Constraints rigorosas para garantir áudio sem manipulação DSP
    const constraints = {
        audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            channelCount: 1,
            sampleRate: 44100
        }
    };

    recordBtn.addEventListener('click', async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            startRecording(stream);
        } catch (err) {
            console.error('Falha ao acessar o microfone:', err);
            uploadStatus.innerHTML = '<span style="color:red;"><i class="fa-solid fa-triangle-exclamation"></i> Erro ao acessar o microfone. Verifique as permissões.</span>';
        }
    });

    stopBtn.addEventListener('click', () => {
        if (autoStopTimeout) {
            clearTimeout(autoStopTimeout);
            autoStopTimeout = null;
        }

        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
            // Para as tracks do microfone para liberar o hardware
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
            if (drawVisual) cancelAnimationFrame(drawVisual);
            stopTimer();

            recordBtn.classList.remove('recording');
            recordBtn.style.display = 'none';
            stopBtn.style.display = 'none';
            if (recordLabel) recordLabel.style.display = 'none';
            uploadStatus.textContent = "Processando áudio...";
        }
    });

    discardBtn.addEventListener('click', async () => {
        if (!currentRecordingId) return;

        discardBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Descartando...';
        discardBtn.disabled = true;
        nextBtn.style.pointerEvents = 'none';
        nextBtn.style.opacity = '0.5';

        const formData = new FormData();
        formData.append('recording_id', currentRecordingId);

        try {
            await fetch(deleteUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: formData
            });

            // Reset UI for new recording
            currentRecordingId = null;
            nextBtn.style.display = 'none';
            nextBtn.style.pointerEvents = 'auto';
            nextBtn.style.opacity = '1';
            discardBtn.style.display = 'none';
            discardBtn.disabled = false;
            discardBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i> Descartar e Regravar';

            canvas.style.display = 'none';
            if (canvasCtx) canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

            // Esconde e zera o timer e player
            timerDisplay.style.display = 'none';
            timerDisplay.textContent = '00:00';
            audioPlaybackContainer.style.display = 'none';
            audioPlayback.src = '';

            uploadStatus.innerHTML = '';

            if (recordLabel) {
                recordLabel.style.display = 'block';
                recordLabel.textContent = 'Gravar';
                recordLabel.style.color = 'var(--primary-color)';
            }

            recordBtn.style.display = 'flex';

            // ── Reset total dos estilos customizados do modo PATAKA ──
            recordBtn.style.pointerEvents = 'auto';
            recordBtn.style.background = '';
            recordBtn.style.color = '';
            recordBtn.style.borderColor = '';
            recordBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
            recordBtn.classList.remove('recording');

            // Remove o painel de countdown caso ainda esteja presente
            const dkkPanel = document.getElementById('dkkCountdownPanel');
            if (dkkPanel) dkkPanel.remove();
        } catch (error) {
            console.error(error);
            uploadStatus.innerHTML = '<span style="color:red;"><i class="fa-solid fa-triangle-exclamation"></i> Erro ao excluir áudio. Tente novamente ou atualize.</span>';
            discardBtn.disabled = false;
            if (recordLabel) recordLabel.style.display = 'none';
            discardBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i> Descartar e Regravar';
            nextBtn.style.pointerEvents = 'auto';
            nextBtn.style.opacity = '1';
        }
    });

    function startTimer() {
        recordingSeconds = 0;
        timerDisplay.textContent = '00:00';
        timerDisplay.style.display = 'block';
        recordingTimerInterval = setInterval(() => {
            recordingSeconds++;
            const m = Math.floor(recordingSeconds / 60).toString().padStart(2, '0');
            const s = (recordingSeconds % 60).toString().padStart(2, '0');
            timerDisplay.textContent = `${m}:${s}`;
        }, 1000);
    }

    function stopTimer() {
        clearInterval(recordingTimerInterval);
    }

    function visualize() {
        if (!canvas) return;
        drawVisual = requestAnimationFrame(visualize);

        analyser.getByteFrequencyData(dataArray);

        canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

        // Largura baseada no número de frequências analisadas
        const barWidth = (canvas.width / analyser.frequencyBinCount) * 2.5;
        let barHeight;
        let x = 0;
        const centerY = canvas.height / 2;

        for (let i = 0; i < analyser.frequencyBinCount; i++) {
            barHeight = dataArray[i] / 2; // altura base

            // Amplifica agressivamente para dar mais "vida" aos audios comuns
            if (barHeight > 5) {
                barHeight = barHeight * 2.5;
            } else if (barHeight > 2) {
                barHeight = barHeight * 1.5;
            }

            // Impede a barra de vazar pra fora do canvas
            if (barHeight > centerY) barHeight = centerY - 2;

            // Mínimo pra criar aquela 'linha zerada' suave
            if (barHeight < 2) barHeight = 2;

            // Cores baseadas no tom e na altura da barra
            const r = barHeight + (25 * (i / analyser.frequencyBinCount));
            const g = 188 - (barHeight / 1.5);
            const b = 160;
            canvasCtx.fillStyle = `rgb(${r},${g},${b})`;

            // Simetria central: metade pra cima, metade pra baixo
            canvasCtx.fillRect(x, centerY - barHeight, barWidth, barHeight * 2);

            x += barWidth + 1;
        }
    }

    function startRecording(stream) {
        audioChunks = [];
        startTimer();

        // Um único AudioContext para visualizador + captura PCM
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const sampleRate = audioContext.sampleRate;

        analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        dataArray = new Uint8Array(analyser.frequencyBinCount);

        source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);

        if (canvas) {
            canvas.style.display = 'block';
            visualize();
        }

        // ScriptProcessor captura PCM bruto (Float32) para codificar como WAV
        const scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        const pcmChunks = [];
        scriptProcessor.onaudioprocess = (e) => {
            pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        };

        // Codifica Float32 PCM → WAV 16-bit
        function encodeWav(chunks, sr) {
            const numSamples = chunks.reduce((acc, c) => acc + c.length, 0);
            const buf = new ArrayBuffer(44 + numSamples * 2);
            const view = new DataView(buf);
            const str = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
            str(0, 'RIFF');
            view.setUint32(4, 36 + numSamples * 2, true);
            str(8, 'WAVE');
            str(12, 'fmt ');
            view.setUint32(16, 16, true);
            view.setUint16(20, 1, true);     // PCM
            view.setUint16(22, 1, true);     // mono
            view.setUint32(24, sr, true);
            view.setUint32(28, sr * 2, true);
            view.setUint16(32, 2, true);
            view.setUint16(34, 16, true);    // 16-bit
            str(36, 'data');
            view.setUint32(40, numSamples * 2, true);
            let offset = 44;
            for (const chunk of chunks) {
                for (let i = 0; i < chunk.length; i++) {
                    const s = Math.max(-1, Math.min(1, chunk[i]));
                    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
                    offset += 2;
                }
            }
            return buf;
        }

        // MediaRecorder apenas como gancho de stop (o áudio real vem do ScriptProcessor)
        let options = { mimeType: 'audio/webm' };
        if (!MediaRecorder.isTypeSupported('audio/webm')) options = { mimeType: 'audio/mp4' };
        mediaRecorder = new MediaRecorder(stream, options);
        mediaRecorder.ondataavailable = () => { };
        mediaRecorder.onstop = () => {
            scriptProcessor.onaudioprocess = null;
            scriptProcessor.disconnect();
            const wavBuffer = encodeWav(pcmChunks, sampleRate);
            const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });
            audioChunks = [wavBlob];
            uploadRecording();
        };

        mediaRecorder.start(200);

        // UI Updates
        recordBtn.classList.add('recording');

        if (taskType === 'DIADOCOCINESIA') {
            const DDK_DURATION = 7; // segundos

            // Ocultar btn de stop para forçar automação
            recordBtn.style.display = 'flex';
            recordBtn.style.pointerEvents = 'none';
            recordBtn.style.background = 'rgba(234, 179, 8, 0.1)';
            recordBtn.style.color = '#eab308';
            recordBtn.style.borderColor = '#eab308';
            recordBtn.innerHTML = '<i class="fa-solid fa-ear-listen fa-fade"></i>';
            stopBtn.style.display = 'none';

            if (recordLabel) {
                recordLabel.style.display = 'block';
                recordLabel.textContent = 'Ouvindo...';
                recordLabel.style.color = '#eab308';
            }

            // ── Cria o painel de contagem regressiva e barra de progresso ──
            const dkkPanel = document.createElement('div');
            dkkPanel.id = 'dkkCountdownPanel';
            dkkPanel.style.cssText = `
                margin: 1.2rem auto 0;
                max-width: 380px;
                background: rgba(234, 179, 8, 0.08);
                border: 1px solid rgba(234, 179, 8, 0.25);
                border-radius: 16px;
                padding: 1rem 1.4rem;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 0.7rem;
            `;

            // Número grande countdown
            const countdownNum = document.createElement('div');
            countdownNum.style.cssText = `
                font-size: 3.5rem;
                font-weight: 800;
                font-family: monospace;
                color: #eab308;
                line-height: 1;
                letter-spacing: -2px;
                transition: color 0.5s;
            `;
            countdownNum.textContent = DDK_DURATION;

            const countdownLabel = document.createElement('div');
            countdownLabel.style.cssText = `
                font-size: 0.75rem;
                font-weight: 600;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                color: #a16207;
                opacity: 0.8;
            `;
            countdownLabel.textContent = 'segundos restantes';

            // ── Barra de progresso estilo WhatsApp ──
            const barOuter = document.createElement('div');
            barOuter.style.cssText = `
                width: 100%;
                height: 6px;
                background: rgba(234, 179, 8, 0.15);
                border-radius: 99px;
                overflow: hidden;
                margin-top: 0.3rem;
            `;
            const barInner = document.createElement('div');
            barInner.id = 'dkkProgressBar';
            barInner.style.cssText = `
                height: 100%;
                width: 0%;
                background: linear-gradient(90deg, #eab308, #f59e0b);
                border-radius: 99px;
                transition: width ${DDK_DURATION}s linear;
            `;
            barOuter.appendChild(barInner);

            // Marcadores de tempo (tipo WhatsApp) – 0s … 7s
            const tickRow = document.createElement('div');
            tickRow.style.cssText = `
                width: 100%;
                display: flex;
                justify-content: space-between;
                font-size: 0.65rem;
                color: #a16207;
                font-weight: 600;
                margin-top: -0.2rem;
            `;
            for (let t = 0; t <= DDK_DURATION; t++) {
                const tick = document.createElement('span');
                tick.textContent = t + 's';
                tickRow.appendChild(tick);
            }

            dkkPanel.appendChild(countdownNum);
            dkkPanel.appendChild(countdownLabel);
            dkkPanel.appendChild(barOuter);
            dkkPanel.appendChild(tickRow);

            // Insere o painel logo após o uploadStatus
            uploadStatus.parentNode.insertBefore(dkkPanel, uploadStatus.nextSibling);


            // Kick-off da barra (força reflow antes de aplicar a transição)
            requestAnimationFrame(() => {
                requestAnimationFrame(() => { barInner.style.width = '100%'; });
            });

            // Contador regressivo a cada segundo
            let remaining = DDK_DURATION;
            const countInterval = setInterval(() => {
                remaining--;
                countdownNum.textContent = remaining;
                // Vira vermelho nos últimos 2 segundos
                if (remaining <= 2) {
                    countdownNum.style.color = '#ef4444';
                    barInner.style.background = 'linear-gradient(90deg, #ef4444, #f87171)';
                }
                if (remaining <= 0) clearInterval(countInterval);
            }, 1000);

            // Stop automático exatamente nos 7 segundos
            autoStopTimeout = setTimeout(() => {
                clearInterval(countInterval);
                const panel = document.getElementById('dkkCountdownPanel');
                if (panel) panel.remove();
                if (mediaRecorder && mediaRecorder.state === 'recording') {
                    stopBtn.click();
                    uploadStatus.innerHTML = '<span style="color:var(--secondary-color);"><i class="fa-solid fa-check-circle fa-beat"></i> Captura concluída! Processando áudio perfeito...</span>';
                }
            }, DDK_DURATION * 1000);

        } else {
            // Executa comportamento original de gravação aberta
            recordBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
            recordBtn.style.display = 'none';
            stopBtn.style.display = 'flex';

            if (recordLabel) {
                recordLabel.style.display = 'block';
                recordLabel.textContent = 'Parar';
                recordLabel.style.color = '#e74c3c';
            }

            uploadStatus.innerHTML = '<span style="color:var(--secondary-color);"><i class="fa-solid fa-circle-dot fa-fade"></i> Gravando modo RAW...</span>';
        }
    }

    async function uploadRecording() {
        uploadStatus.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Enviando áudio com segurança...';

        const audioBlob = audioChunks[0]; // já é um Blob WAV
        const formData = new FormData();
        formData.append('audio_file', audioBlob, `${taskType}_${patientId}_${Date.now()}.wav`);
        formData.append('patient_id', patientId);
        formData.append('task_type', taskType);

        try {
            const response = await fetch(uploadUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                },
                body: formData
            });

            if (response.ok) {
                const data = await response.json();
                currentRecordingId = data.id;

                // Exibe player e seta a URL blob local para ouvir imediato
                audioPlayback.src = URL.createObjectURL(audioBlob);
                audioPlaybackContainer.style.display = 'block';

                // Normaliza/Amplifica O PLAYER apenas uma vez (sem alterar o blob bruto enviado ao server)
                if (!playbackNormalized) {
                    try {
                        const playCtx = new (window.AudioContext || window.webkitAudioContext)();
                        const track = playCtx.createMediaElementSource(audioPlayback);

                        // Compressor e Compressor Dinâmico
                        const compressor = playCtx.createDynamicsCompressor();
                        compressor.threshold.value = -35;
                        compressor.knee.value = 30;
                        compressor.ratio.value = 10;
                        compressor.attack.value = 0.05;
                        compressor.release.value = 0.25;

                        // Ganho brutal para áudios muito fracos
                        const gainNode = playCtx.createGain();
                        gainNode.gain.value = 2.5;

                        track.connect(compressor);
                        compressor.connect(gainNode);
                        gainNode.connect(playCtx.destination);

                        playbackNormalized = true;
                    } catch (e) {
                        console.warn("AudioContext init failed para o preview:", e);
                    }
                }

                uploadStatus.innerHTML = '<span style="color:var(--secondary-color);"><i class="fa-solid fa-check"></i> Áudio salvo com sucesso!</span>';
                nextBtn.style.display = 'inline-flex';
                discardBtn.style.display = 'inline-flex';

                // Oculta o áudio de exemplo e o visualizador
                const exampleAudio = document.getElementById('exampleAudioContainer');
                if (exampleAudio) exampleAudio.style.display = 'none';
                if (canvas) canvas.style.display = 'none';
            } else {
                throw new Error('Falha no upload do servidor.');
            }
        } catch (error) {
            console.error(error);
            uploadStatus.innerHTML = '<span style="color:red;"><i class="fa-solid fa-triangle-exclamation"></i> Erro ao salvar arquivo. A gravação foi perdida. Tente novamente.</span>';
            // Allow retry
            recordBtn.style.display = 'flex';
            recordBtn.classList.remove('recording');
            stopBtn.style.display = 'none';

            if (recordLabel) {
                recordLabel.style.display = 'block';
                recordLabel.textContent = 'Gravar';
                recordLabel.style.color = 'var(--primary-color)';
            }
        }
    }
});
