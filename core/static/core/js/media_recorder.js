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

            // Remove o player estilo WhatsApp
            const pbBubble = document.getElementById('waPlaybackBubble');
            if (pbBubble) pbBubble.remove();

            // Restaura o áudio de exemplo se existir
            const exampleAudio = document.getElementById('exampleAudioContainer');
            if (exampleAudio) exampleAudio.style.display = 'block';
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

        // UI Updates
        recordBtn.classList.add('recording');
        recordBtn.style.display = 'none';
        stopBtn.style.display = 'none';
        if (recordLabel) recordLabel.style.display = 'none';
        if (timerDisplay) timerDisplay.style.display = 'none';
        if (canvas) canvas.style.display = 'none';

        const isDDK = taskType === 'DIADOCOCINESIA';
        const isVowel = taskType.startsWith('FONACAO_');
        const isCountdown = isDDK || isVowel;
        const countdownDuration = isDDK ? 7 : 5;

        // ── BOLHA WHATSAPP UNIVERSAL ────────────────────────────────
        const waBubble = document.createElement('div');
        waBubble.id = 'dkkCountdownPanel'; // Mantendo ID para compatibilidade com o .remove()
        waBubble.style.cssText = `
            margin: 1.5rem auto 0;
            max-width: 340px;
            background: #1f2c34;
            border-radius: 20px;
            padding: 10px 14px 10px 10px;
            display: flex;
            align-items: center;
            gap: 10px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.35);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        `;

        // Coluna Esquerda: Botão/Dot
        const leftCol = document.createElement('div');
        leftCol.style.cssText = 'flex-shrink:0; position:relative;';

        const dot = document.createElement('div');
        dot.style.cssText = `
            width: 40px; height: 40px; border-radius: 50%;
            background: #ef4444; display: flex; align-items: center; justify-content: center;
            animation: waDotPulse 1s infinite;
        `;
        dot.innerHTML = '<i class="fa-solid fa-microphone" style="color:#fff; font-size:1rem;"></i>';
        leftCol.appendChild(dot);

        // Se NÃO for countdown (LEITURA), o dot é o botão de parar
        if (!isCountdown) {
            dot.style.cursor = 'pointer';
            dot.title = 'Clique para parar';
            dot.addEventListener('click', () => stopBtn.click());
            dot.innerHTML = '<i class="fa-solid fa-stop" style="color:#fff; font-size:1rem;"></i>';
        }

        // Centro: Waveform e (se countdown) Barra de Progresso
        const center = document.createElement('div');
        center.style.cssText = 'flex: 1; display: flex; flex-direction: column; gap: 6px; overflow: hidden;';

        const waCanvas = document.createElement('canvas');
        waCanvas.width = 220; waCanvas.height = 32;
        waCanvas.style.cssText = 'width:100%; height:32px; display:block;';
        const waCtx = waCanvas.getContext('2d');
        center.appendChild(waCanvas);

        let progressInner;
        if (isCountdown) {
            const progressOuter = document.createElement('div');
            progressOuter.style.cssText = 'width: 100%; height: 3px; background: rgba(255,255,255,0.12); border-radius: 99px; overflow: hidden;';
            progressInner = document.createElement('div');
            progressInner.style.cssText = `height: 100%; width: 0%; background: #25d366; border-radius: 99px; transition: width ${countdownDuration}s linear;`;
            progressOuter.appendChild(progressInner);
            center.appendChild(progressOuter);
        }

        // Direita: Timer
        const right = document.createElement('div');
        right.style.cssText = 'display: flex; flex-direction: column; align-items: flex-end; flex-shrink: 0; gap: 3px;';

        const timerNum = document.createElement('div');
        timerNum.style.cssText = `font-size: 1.6rem; font-weight: 800; font-family: monospace; color: #25d366; line-height: 1; transition: color 0.4s;`;
        timerNum.textContent = isCountdown ? countdownDuration : '0:00';

        const timerSub = document.createElement('div');
        timerSub.style.cssText = 'font-size: 0.6rem; color: rgba(255,255,255,0.4); text-transform: uppercase; letter-spacing: 0.8px;';
        if (isDDK) timerSub.textContent = 'PA-TA-KA';
        else if (isVowel) timerSub.textContent = 'VOGAL';
        else timerSub.textContent = 'LEITURA';

        right.appendChild(timerNum);
        right.appendChild(timerSub);

        waBubble.appendChild(leftCol);
        waBubble.appendChild(center);
        waBubble.appendChild(right);

        uploadStatus.innerHTML = '';
        uploadStatus.parentNode.insertBefore(waBubble, uploadStatus.nextSibling);

        // Estilos e Keyframes
        if (!document.getElementById('waStyles')) {
            const style = document.createElement('style');
            style.id = 'waStyles';
            style.textContent = `@keyframes waDotPulse { 0%,100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.45); } 50% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } }`;
            document.head.appendChild(style);
        }

        if (isCountdown) {
            requestAnimationFrame(() => { requestAnimationFrame(() => { progressInner.style.width = '100%'; }); });
        }

        let waDrawId;
        (function drawWA() {
            waDrawId = requestAnimationFrame(drawWA);
            if (!analyser) return;
            analyser.getByteFrequencyData(dataArray);
            waCtx.clearRect(0, 0, waCanvas.width, waCanvas.height);
            const barCount = 38, barW = 3;
            const gap = (waCanvas.width - barCount * barW) / (barCount - 1);
            const centerY = waCanvas.height / 2;
            for (let i = 0; i < barCount; i++) {
                const idx = Math.floor((i / barCount) * analyser.frequencyBinCount * 0.7);
                let h = Math.max(2, (dataArray[idx] / 255) * waCanvas.height * 0.85);
                waCtx.fillStyle = '#25d366';
                waCtx.beginPath();
                if (waCtx.roundRect) waCtx.roundRect(i * (barW + gap), centerY - h / 2, barW, h, 2);
                else waCtx.rect(i * (barW + gap), centerY - h / 2, barW, h);
                waCtx.fill();
            }
        })();

        // Lógica do Timer
        let elapsed = 0;
        let remaining = countdownDuration;
        const countInterval = setInterval(() => {
            if (isCountdown) {
                remaining--;
                timerNum.textContent = remaining;
                if (remaining <= 2) {
                    timerNum.style.color = '#ef4444';
                    progressInner.style.background = 'linear-gradient(90deg,#ef4444,#f87171)';
                    dot.style.background = '#b91c1c';
                }
                if (remaining <= 0) clearInterval(countInterval);
            } else {
                elapsed++;
                const mins = Math.floor(elapsed / 60);
                const secs = elapsed % 60;
                timerNum.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
            }
        }, 1000);

        if (isCountdown) {
            autoStopTimeout = setTimeout(() => {
                clearInterval(countInterval);
                cancelAnimationFrame(waDrawId);
                const panel = document.getElementById('dkkCountdownPanel');
                if (panel) panel.remove();
                if (mediaRecorder && mediaRecorder.state === 'recording') {
                    stopBtn.click();
                    uploadStatus.innerHTML = '<span style="color:#25d366;"><i class="fa-solid fa-check-circle fa-beat"></i> Captura concluída! Processando áudio...</span>';
                }
            }, countdownDuration * 1000);
        } else {
            // Para a leitura, limpamos ao parar
            const cleanupWA = () => {
                clearInterval(countInterval);
                cancelAnimationFrame(waDrawId);
                const panel = document.getElementById('dkkCountdownPanel');
                if (panel) panel.remove();
            };
            stopBtn.addEventListener('click', cleanupWA, { once: true });
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

                // ── Player estilo WhatsApp ───────────────────────────────────
                const blobUrl = URL.createObjectURL(audioBlob);

                // Remove bubble antiga se existir (ex: ao regravar)
                const oldBubble = document.getElementById('waPlaybackBubble');
                if (oldBubble) oldBubble.remove();

                const playBubble = document.createElement('div');
                playBubble.id = 'waPlaybackBubble';
                playBubble.style.cssText = `
                    margin: 1.2rem auto 0;
                    max-width: 340px;
                    background: #1f2c34;
                    border-radius: 20px;
                    padding: 10px 14px 10px 10px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    box-shadow: 0 4px 24px rgba(0,0,0,0.3);
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                `;

                // Botão play/pause
                const playBtn = document.createElement('button');
                playBtn.style.cssText = `
                    width: 40px; height: 40px; border-radius: 50%;
                    background: #25d366; border: none; cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    flex-shrink: 0; transition: background 0.2s;
                `;
                playBtn.innerHTML = '<i class="fa-solid fa-play" style="color:#fff; font-size:0.95rem; margin-left:2px;"></i>';

                // Área central: waveform estático + barra de progresso
                const pbCenter = document.createElement('div');
                pbCenter.style.cssText = 'flex:1; display:flex; flex-direction:column; gap:5px; overflow:hidden;';

                const pbCanvas = document.createElement('canvas');
                pbCanvas.width = 220;
                pbCanvas.height = 32;
                pbCanvas.style.cssText = 'width:100%; height:32px; display:block; cursor:pointer;';
                const pbCtx = pbCanvas.getContext('2d');

                // Barra de progresso de reprodução
                const pbBarOuter = document.createElement('div');
                pbBarOuter.style.cssText = `width:100%; height:3px; background:rgba(255,255,255,0.12); border-radius:99px; overflow:hidden; cursor:pointer;`;
                const pbBarInner = document.createElement('div');
                pbBarInner.style.cssText = `height:100%; width:0%; background:#25d366; border-radius:99px; transition:width 0.1s linear;`;
                pbBarOuter.appendChild(pbBarInner);

                pbCenter.appendChild(pbCanvas);
                pbCenter.appendChild(pbBarOuter);

                // Contador de tempo direito
                const pbTime = document.createElement('div');
                pbTime.style.cssText = `font-size:0.72rem; font-family:monospace; color:rgba(255,255,255,0.55); flex-shrink:0; min-width:36px; text-align:right;`;
                pbTime.textContent = '0:00';

                playBubble.appendChild(playBtn);
                playBubble.appendChild(pbCenter);
                playBubble.appendChild(pbTime);

                // Insere após o uploadStatus
                uploadStatus.parentNode.insertBefore(playBubble, uploadStatus.nextSibling);

                // ── Elemento de áudio oculto ──
                const hiddenAudio = new Audio(blobUrl);

                // ── Desenha waveform estático (analisa o blob WAV) ──
                (async () => {
                    try {
                        const arrBuf = await audioBlob.arrayBuffer();
                        const offCtx = new OfflineAudioContext(1, 1, 44100);
                        const decoded = await offCtx.decodeAudioData(arrBuf);
                        const raw = decoded.getChannelData(0);
                        const barCount = 38;
                        const step = Math.ceil(raw.length / barCount);
                        const centerY = pbCanvas.height / 2;
                        const barW = 3;
                        const gap = (pbCanvas.width - barCount * barW) / (barCount - 1);

                        pbCtx.clearRect(0, 0, pbCanvas.width, pbCanvas.height);
                        for (let i = 0; i < barCount; i++) {
                            let peak = 0;
                            for (let j = 0; j < step; j++) {
                                const s = Math.abs(raw[i * step + j] || 0);
                                if (s > peak) peak = s;
                            }
                            const h = Math.max(2, peak * pbCanvas.height * 0.9);
                            pbCtx.fillStyle = 'rgba(37,211,102,0.6)';
                            pbCtx.beginPath();
                            if (pbCtx.roundRect) pbCtx.roundRect(i * (barW + gap), centerY - h / 2, barW, h, 2);
                            else pbCtx.rect(i * (barW + gap), centerY - h / 2, barW, h);
                            pbCtx.fill();
                        }
                    } catch (e) { console.warn('Waveform decode:', e); }
                })();

                // ── Helpers de formatação ──
                const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

                // ── Progresso durante reprodução ──
                hiddenAudio.addEventListener('timeupdate', () => {
                    const pct = hiddenAudio.duration ? (hiddenAudio.currentTime / hiddenAudio.duration) * 100 : 0;
                    pbBarInner.style.width = pct + '%';
                    pbTime.textContent = fmt(hiddenAudio.currentTime);
                });
                hiddenAudio.addEventListener('ended', () => {
                    playBtn.innerHTML = '<i class="fa-solid fa-play" style="color:#fff; font-size:0.95rem; margin-left:2px;"></i>';
                    pbBarInner.style.width = '0%';
                    pbTime.textContent = '0:00';
                });
                hiddenAudio.addEventListener('loadedmetadata', () => {
                    pbTime.textContent = fmt(hiddenAudio.duration);
                });

                // ── AudioContext para animação ao vivo durante a reprodução ──
                let pbAudioCtx, pbAnalyser, pbDataArray, pbDrawId;
                let pbContextReady = false;

                function initPbContext() {
                    if (pbContextReady) return;
                    try {
                        pbAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
                        pbAnalyser = pbAudioCtx.createAnalyser();
                        pbAnalyser.fftSize = 2048;
                        pbDataArray = new Uint8Array(pbAnalyser.frequencyBinCount);

                        const src = pbAudioCtx.createMediaElementSource(hiddenAudio);
                        src.connect(pbAnalyser);
                        pbAnalyser.connect(pbAudioCtx.destination);
                        pbContextReady = true;
                    } catch (e) { console.warn('PB AudioContext:', e); }
                }

                function drawPbWave() {
                    pbDrawId = requestAnimationFrame(drawPbWave);
                    if (!pbAnalyser) return;
                    pbAnalyser.getByteFrequencyData(pbDataArray);
                    pbCtx.clearRect(0, 0, pbCanvas.width, pbCanvas.height);
                    const barCount = 38, barW = 3;
                    const gap = (pbCanvas.width - barCount * barW) / (barCount - 1);
                    const centerY = pbCanvas.height / 2;
                    for (let i = 0; i < barCount; i++) {
                        const idx = Math.floor((i / barCount) * pbAnalyser.frequencyBinCount * 0.7);
                        let h = Math.max(2, (pbDataArray[idx] / 255) * pbCanvas.height * 0.85);
                        pbCtx.fillStyle = '#25d366';
                        pbCtx.beginPath();
                        if (pbCtx.roundRect) pbCtx.roundRect(i * (barW + gap), centerY - h / 2, barW, h, 2);
                        else pbCtx.rect(i * (barW + gap), centerY - h / 2, barW, h);
                        pbCtx.fill();
                    }
                }

                function stopPbWave() {
                    if (pbDrawId) { cancelAnimationFrame(pbDrawId); pbDrawId = null; }
                }

                // ── Clique no play/pause ──
                playBtn.addEventListener('click', () => {
                    if (hiddenAudio.paused) {
                        initPbContext();
                        if (pbAudioCtx && pbAudioCtx.state === 'suspended') pbAudioCtx.resume();
                        hiddenAudio.play();
                        drawPbWave();
                        playBtn.innerHTML = '<i class="fa-solid fa-pause" style="color:#fff; font-size:0.95rem;"></i>';
                        playBtn.style.background = '#128c5e';
                    } else {
                        hiddenAudio.pause();
                        stopPbWave();
                        playBtn.innerHTML = '<i class="fa-solid fa-play" style="color:#fff; font-size:0.95rem; margin-left:2px;"></i>';
                        playBtn.style.background = '#25d366';
                    }
                });

                // Ao terminar, também para a animação
                hiddenAudio.addEventListener('ended', () => {
                    stopPbWave();
                });

                // Clique na barra para saltar
                pbBarOuter.addEventListener('click', e => {
                    if (!hiddenAudio.duration) return;
                    const rect = pbBarOuter.getBoundingClientRect();
                    hiddenAudio.currentTime = ((e.clientX - rect.left) / rect.width) * hiddenAudio.duration;
                });

                // Oculta o container genérico (não mais necessário)
                audioPlaybackContainer.style.display = 'none';

                // Oculta o áudio de exemplo e o visualizador
                const exampleAudio = document.getElementById('exampleAudioContainer');
                if (exampleAudio) exampleAudio.style.display = 'none';
                if (canvas) canvas.style.display = 'none';

                // ── Status de revisão (não "salvo" ainda, usuário deve confirmar) ──
                uploadStatus.innerHTML = '<span style="color:var(--text-secondary); font-size:0.85rem;  display:block;"><i class="fa-solid fa-headphones"></i> Revise o áudio — clique em <b>Concluir</b> para confirmar.</span>';
                nextBtn.style.display = 'inline-flex';
                discardBtn.style.display = 'inline-flex';

                // ── Intercepta o Concluir/Próxima Tarefa para mostrar feedback ──
                const originalHref = nextBtn.href;
                nextBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    hiddenAudio.pause();
                    stopPbWave();
                    uploadStatus.innerHTML = '<span style="color:#25d366;"><i class="fa-solid fa-spinner fa-spin"></i> Salvando definitivamente...</span>';
                    nextBtn.style.pointerEvents = 'none';
                    discardBtn.style.pointerEvents = 'none';
                    setTimeout(() => {
                        window.location.href = originalHref;
                    }, 700);
                }, { once: true });
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
