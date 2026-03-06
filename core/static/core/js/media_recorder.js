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
