document.querySelectorAll("[data-swatch-color]").forEach((el) => {
    el.style.backgroundColor = el.dataset.swatchColor;
});

const FORM = document.querySelector("form[data-method]");
const METHOD = FORM.dataset.method;
const swatch = document.getElementById("swatch");
const label = document.getElementById("swatch-label");
const mstValue = document.getElementById("mst-value");

function showColour(hex, text) {
    swatch.style.backgroundColor = hex;
    label.textContent = text || hex.toUpperCase();
}

function clearColour() {
    swatch.style.backgroundColor = "";
    label.textContent = "No colour chosen yet";
}

if (METHOD === "hex") {
    // ---- Pick directly from the MST dropdown ----
    const toggleSwatch = document.getElementById("mst-toggle-swatch");
    const toggleLabel = document.getElementById("mst-toggle-label");
    const items = document.querySelectorAll(".dropdown-item[data-mst-id]");

    items.forEach((item) => {
        item.addEventListener("click", () => {
            items.forEach((other) => {
                other.classList.remove("active");
                other.querySelector(".mst-check").hidden = true;
            });
            item.classList.add("active");
            item.querySelector(".mst-check").hidden = false;

            mstValue.value = item.dataset.mstId;
            toggleSwatch.style.backgroundColor = item.dataset.mstHex;
            toggleLabel.textContent = item.dataset.mstLabel;
            showColour(item.dataset.mstHex, item.dataset.mstLabel);
        });
    });
} else {
    // ---- Upload / selfie: capture a photo, then let the server analyze it ----
    const canvas = document.getElementById("canvas");
    const ctx = canvas.getContext("2d");
    const stage = document.getElementById("stage");
    const marker = document.getElementById("ref-marker");
    const hexValue = document.getElementById("hex-value");
    const confidenceValue = document.getElementById("confidence");
    const photoActions = document.getElementById("photo-actions");
    const pickRef = document.getElementById("pick-ref");
    const cardType = document.getElementById("card-type");
    const clearRef = document.getElementById("clear-ref");
    const refHint = document.getElementById("ref-hint");
    const analyzing = document.getElementById("analyzing");
    const analysisError = document.getElementById("analysis-error");
    const matchesBox = document.getElementById("matches");
    const matchList = document.getElementById("match-list");
    const MAX_WIDTH = 1280;

    let busy = false;
    let picking = false;
    let analysis = null;  // { mstId, confidence } of the latest photo analysis
    let reference = null; // {x, y} as 0–1 fractions of the photo

    function resetResult() {
        mstValue.value = "";
        hexValue.value = "";
        matchesBox.hidden = true;
        matchList.innerHTML = "";
        analysisError.hidden = true;
        reference = null;
        picking = false;
        updateReferenceUI();
        clearColour();
    }

    function updateReferenceUI() {
        canvas.classList.toggle("picking", picking);
        pickRef.textContent = picking ? "Cancel" : "Mark your card";
        refHint.hidden = !picking;
        clearRef.hidden = !reference;
        marker.hidden = !reference;
        if (reference) {
            marker.style.left = `${reference.x * 100}%`;
            marker.style.top = `${reference.y * 100}%`;
        }
    }

    function drawSource(source, width, height) {
        const scale = Math.min(1, MAX_WIDTH / width);
        canvas.width = Math.round(width * scale);
        canvas.height = Math.round(height * scale);
        ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
        stage.hidden = false;
        photoActions.hidden = false;
        resetResult();
        analyzePhoto();
    }

    function buildMatchButton(match) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-outline-secondary d-flex align-items-center gap-2";
        button.dataset.mstId = match.id;
        button.dataset.mstHex = match.hex;
        button.dataset.mstLabel = match.label;

        const dot = document.createElement("span");
        dot.className = "mst-swatch";
        dot.style.backgroundColor = match.hex;

        const text = document.createElement("span");
        text.textContent = match.label;

        const check = document.createElement("span");
        check.className = "mst-check";
        check.hidden = true;
        check.textContent = "✓";

        button.append(dot, text, check);
        button.addEventListener("click", () => selectMatch(button));
        return button;
    }

    // Choosing a tone only changes the MST value; hexValue keeps the measured colour
    function selectMatch(button) {
        matchList.querySelectorAll("[data-mst-id]").forEach((other) => {
            other.classList.remove("active");
            other.setAttribute("aria-pressed", "false");
            other.querySelector(".mst-check").hidden = true;
        });
        button.classList.add("active");
        button.setAttribute("aria-pressed", "true");
        button.querySelector(".mst-check").hidden = false;

        mstValue.value = button.dataset.mstId;
        showColour(button.dataset.mstHex, button.dataset.mstLabel);

        // The confidence describes the top match only; picking another tone overrides it
        const keptTopMatch = analysis && String(analysis.mstId) === button.dataset.mstId;
        confidenceValue.value = keptTopMatch ? analysis.confidence : "";
    }

    function canvasToBlob() {
        return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    }

    async function analyzePhoto() {
        if (busy) return;
        busy = true;
        analyzing.hidden = false;
        analysisError.hidden = true;
        pickRef.disabled = true;
        clearRef.disabled = true;
        cardType.disabled = true;

        try {
            const blob = await canvasToBlob();
            const formData = new FormData();
            formData.append("photo", blob, "photo.jpg");
            if (reference) {
                formData.append("ref_x", reference.x);
                formData.append("ref_y", reference.y);
                formData.append("card", cardType.value);
            }

            const response = await fetch("/setup/analyze", { method: "POST", body: formData });
            // A signed-out request is redirected to the login page, which comes back as HTML
            if (response.redirected && new URL(response.url).pathname === "/login") {
                throw new Error("You've been signed out. Log in again to analyze your photo.");
            }
            const isJson = (response.headers.get("Content-Type") || "").includes("application/json");
            const result = isJson ? await response.json() : {};
            if (!response.ok || !isJson) {
                throw new Error(result.error || `Couldn't analyze that photo (error ${response.status}). Try another one.`);
            }

            hexValue.value = result.measured_hex;
            analysis = { mstId: result.mst_id, confidence: result.confidence };
            matchList.innerHTML = "";
            result.matches.forEach((match) => matchList.appendChild(buildMatchButton(match)));
            matchesBox.hidden = false;

            const topMatch = matchList.querySelector(`[data-mst-id="${result.mst_id}"]`);
            if (topMatch) selectMatch(topMatch);
        } catch (err) {
            // Keep any earlier result on screen, so a badly marked card doesn't wipe it
            analysisError.textContent = err.message || "Couldn't analyze that photo. Try another one.";
            analysisError.hidden = false;
        } finally {
            busy = false;
            analyzing.hidden = true;
            pickRef.disabled = false;
            clearRef.disabled = false;
            cardType.disabled = false;
        }
    }

    // The card type only matters once a card has been marked
    cardType.addEventListener("change", () => {
        if (reference) analyzePhoto();
    });

    pickRef.addEventListener("click", () => {
        picking = !picking;
        updateReferenceUI();
    });

    clearRef.addEventListener("click", () => {
        reference = null;
        updateReferenceUI();
        analyzePhoto();
    });

    // Clicks on the photo only count while "Mark your card" is active
    canvas.addEventListener("click", (event) => {
        if (!picking || busy) return;
        const rect = canvas.getBoundingClientRect();
        reference = {
            x: (event.clientX - rect.left) / rect.width,
            y: (event.clientY - rect.top) / rect.height,
        };
        picking = false;
        updateReferenceUI();
        analyzePhoto();
    });

    if (METHOD === "upload") {
        document.getElementById("file-input").addEventListener("change", (event) => {
            const file = event.target.files[0];
            if (!file) return;
            const img = new Image();
            img.onload = () => {
                drawSource(img, img.naturalWidth, img.naturalHeight);
                URL.revokeObjectURL(img.src);
            };
            img.onerror = () => {
                analysisError.textContent = "That file isn't an image we can open. Choose a JPEG or PNG.";
                analysisError.hidden = false;
            };
            img.src = URL.createObjectURL(file);
        });
    } else {
        const video = document.getElementById("video");
        const capture = document.getElementById("capture");
        const retake = document.getElementById("retake");
        let stream = null;

        async function startCamera() {
            resetResult();
            stage.hidden = true;
            photoActions.hidden = true;
            try {
                stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
                video.srcObject = stream;
                video.hidden = false;
                capture.hidden = false;
                retake.hidden = true;
            } catch (err) {
                analysisError.textContent = "Camera unavailable. Allow camera access in your browser, or upload a photo instead.";
                analysisError.hidden = false;
            }
        }

        function stopCamera() {
            if (stream) stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }

        capture.addEventListener("click", () => {
            if (!video.videoWidth) return; // camera not ready yet
            drawSource(video, video.videoWidth, video.videoHeight);
            stopCamera();
            video.hidden = true;
            capture.hidden = true;
            retake.hidden = false;
        });
        retake.addEventListener("click", startCamera);
        window.addEventListener("pagehide", stopCamera);
        startCamera();
    }
}

// Don't submit until a tone has been chosen
FORM.addEventListener("submit", (event) => {
    if (!mstValue.value) {
        event.preventDefault();
        label.textContent = "Choose a tone first";
    }
});
