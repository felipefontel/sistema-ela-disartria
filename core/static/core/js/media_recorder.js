document.addEventListener('DOMContentLoaded', () => {
    const recordBtn = document.getElementById('recordBtn');
    const stopBtn = document.getElementById('stopBtn');
    const uploadStatus = document.getElementById('uploadStatus');
    const nextBtn = document.getElementById('nextBtn');

    const discardBtn = document.getElementById('discardBtn');
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

            recordBtn.classList.remove('recording');
            recordBtn.style.display = 'none';
            stopBtn.style.display = 'none';
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
            uploadStatus.innerHTML = '';

            recordBtn.style.display = 'flex';
        } catch (error) {
            console.error(error);
            uploadStatus.innerHTML = '<span style="color:red;"><i class="fa-solid fa-triangle-exclamation"></i> Erro ao excluir áudio. Tente novamente ou atualize.</span>';
            discardBtn.disabled = false;
            discardBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i> Descartar e Regravar';
            nextBtn.style.pointerEvents = 'auto';
            nextBtn.style.opacity = '1';
        }
    });

    function visualize() {
        if (!canvas) return;
        drawVisual = requestAnimationFrame(visualize);

        analyser.getByteTimeDomainData(dataArray);

        canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

        canvasCtx.lineWidth = 3;

        // Gradiente bonito
        let gradient = canvasCtx.createLinearGradient(0, 0, canvas.width, 0);
        gradient.addColorStop(0, '#0b6fb8');     // primary
        gradient.addColorStop(0.5, '#1bbca0');   // secondary
        gradient.addColorStop(1, '#0b6fb8');     // primary
        canvasCtx.strokeStyle = gradient;

        canvasCtx.beginPath();

        const sliceWidth = canvas.width * 1.0 / analyser.frequencyBinCount;
        let x = 0;

        for (let i = 0; i < analyser.frequencyBinCount; i++) {
            const v = dataArray[i] / 128.0; // valor central é 128
            const y = v * (canvas.height / 2);

            if (i === 0) {
                canvasCtx.moveTo(x, y);
            } else {
                canvasCtx.lineTo(x, y);
            }

            x += sliceWidth;
        }

        canvasCtx.lineTo(canvas.width, canvas.height / 2);
        canvasCtx.stroke();
    }

    function startRecording(stream) {
        audioChunks = [];

        // Setup Visualizer
        if (canvas) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioContext.createAnalyser();
            source = audioContext.createMediaStreamSource(stream);
            source.connect(analyser);
            analyser.fftSize = 2048;
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);
            canvas.style.display = 'block';
            visualize();
        }

        // MIME Type de WebM (maior suporte web, sem re-encode pra não perder specs acústicos)
        let options = { mimeType: 'audio/webm' };
        if (!MediaRecorder.isTypeSupported('audio/webm')) {
            options = { mimeType: 'audio/mp4' };
        }

        mediaRecorder = new MediaRecorder(stream, options);

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = uploadRecording;

        mediaRecorder.start(200); // chunking

        // UI Updates
        recordBtn.classList.add('recording');
        recordBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';

        recordBtn.style.display = 'none';
        stopBtn.style.display = 'flex';
        uploadStatus.innerHTML = '<span style="color:var(--secondary-color);"><i class="fa-solid fa-circle-dot fa-fade"></i> Gravando modo RAW...</span>';
    }

    async function uploadRecording() {
        uploadStatus.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Enviando áudio com segurança...';

        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio_file', audioBlob, `${taskType}_${patientId}_${Date.now()}.webm`);
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
                uploadStatus.innerHTML = '<span style="color:var(--secondary-color);"><i class="fa-solid fa-check"></i> Áudio salvo com sucesso!</span>';
                nextBtn.style.display = 'inline-flex';
                discardBtn.style.display = 'inline-flex';
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
        }
    }
});
