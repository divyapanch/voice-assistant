// static/script.js
const recordBtn = document.getElementById("recordBtn");
const status = document.getElementById("status");
const chat = document.getElementById("chat");
const responseAudio = document.getElementById("responseAudio");
const avatarList = document.getElementById("avatarList");

let audioContext;
let recorder;
let input;
let audioData = { size: 0, buffer: [] };

const sessionId = window.sessionId || ("sess_" + Date.now());
let selectedPersona = window.selectedPersona || "narwhal";

// Avatar selection handling
avatarList.addEventListener("click", (e) => {
  const btn = e.target.closest(".avatar-btn");
  if (!btn) return;
  avatarList.querySelectorAll(".avatar-btn").forEach(b => b.setAttribute("aria-pressed", "false"));
  btn.setAttribute("aria-pressed", "true");
  selectedPersona = btn.getAttribute("data-persona") || "narwhal";
  window.selectedPersona = selectedPersona;
});

// helper: map persona -> exact avatar filename path
function personaImagePath(persona) {
  if (persona === "cat") return "/static/avatarimgs/catavatar.gif";
  if (persona === "winnie") return "/static/avatarimgs/winnieavatar.png";
  return "/static/avatarimgs/narwhaleavatar.gif";
}

recordBtn.onclick = async () => {
  if (!recorder) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      input = audioContext.createMediaStreamSource(stream);

      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      input.connect(processor);
      processor.connect(audioContext.destination);

      processor.onaudioprocess = (e) => {
        const channelData = e.inputBuffer.getChannelData(0);
        audioData.buffer.push(new Float32Array(channelData));
        audioData.size += channelData.length;
      };

      recorder = { processor, stream };
      recordBtn.textContent = "Stop Recording";
      status.textContent = "Recording…";
    } catch (e) {
      console.error("Microphone access error", e);
      status.textContent = "Microphone access denied";
    }
  } else {
    // stop
    recorder.processor.disconnect();
    input.disconnect();
    recorder.stream.getTracks().forEach(t => t.stop());
    recorder = null;
    recordBtn.textContent = "Start Recording";
    status.textContent = "Processing…";

    const merged = mergeBuffers(audioData.buffer, audioData.size);
    const wavBlob = encodeWAV(merged, audioContext.sampleRate);
    audioData = { size: 0, buffer: [] };

    // add placeholder bubbles
    const userBubbleId = addBubble("…", "user");
    const assistantBubbleId = addBubble("Thinking…", "assistant", personaImagePath(selectedPersona));

    try {
      const formData = new FormData();
      formData.append("audio", wavBlob, "recording.wav");
      formData.append("session_id", sessionId);
      formData.append("persona", selectedPersona);

      const res = await fetch("/process_voice", { method: "POST", body: formData });
      if (!res.ok) {
        const txt = await res.text();
        updateBubble(userBubbleId, "(error)");
        updateBubble(assistantBubbleId, "Error: " + txt);
        status.textContent = "Error";
        return;
      }

      const data = await res.json();
      updateBubble(userBubbleId, data.user_text || "(no speech detected)");
      updateBubble(assistantBubbleId, data.assistant_text || "(no reply)");

      // update assistant avatar if persona returned
      if (data.persona) {
        const imgEl = document.querySelector(`#${assistantBubbleId} .avatar-small img`);
        if (imgEl) imgEl.src = personaImagePath(data.persona);
      }

      if (data.audio) {
        responseAudio.src = data.audio + "?t=" + Date.now();
        try { await responseAudio.play(); } catch (e) { /* autoplay blocked */ }
      }
      status.textContent = "Idle";
    } catch (err) {
      console.error(err);
      updateBubble(assistantBubbleId, "Server error.");
      status.textContent = "Server error";
    }
  }
};

// UI helpers
function addBubble(text, role, avatarSrc=null) {
  const id = "b_" + Date.now() + "_" + Math.floor(Math.random()*1000);
  const el = document.createElement("div");
  el.id = id;
  el.className = `bubble ${role}`;

  if (role === "assistant") {
    const av = document.createElement("div");
    av.className = "avatar-small";
    const img = document.createElement("img");
    img.className = "avatar-small-img";
    img.src = avatarSrc || personaImagePath(selectedPersona);
    av.appendChild(img);

    const txt = document.createElement("div");
    txt.className = "text";
    txt.textContent = text;

    el.appendChild(av);
    el.appendChild(txt);
  } else {
    const txt = document.createElement("div");
    txt.className = "text";
    txt.textContent = text;
    el.appendChild(txt);
  }

  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return id;
}
function updateBubble(id, text) {
  const el = document.getElementById(id);
  if (el) {
    const txt = el.querySelector(".text");
    if (txt) txt.textContent = text;
    chat.scrollTop = chat.scrollHeight;
  }
}

// Audio encoding helpers (WAV)
function mergeBuffers(bufferArray, totalLength) {
  if (!bufferArray || bufferArray.length === 0) return new Float32Array(0);
  const result = new Float32Array(totalLength);
  let offset = 0;
  for (let i = 0; i < bufferArray.length; i++) {
    result.set(bufferArray[i], offset);
    offset += bufferArray[i].length;
  }
  return result;
}
function floatTo16BitPCM(output, offset, input) {
  for (let i = 0; i < input.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, input[i]));
    s = s < 0 ? s * 0x8000 : s * 0x7fff;
    output.setInt16(offset, s, true);
  }
}
function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++){
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}
function encodeWAV(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, 'data');
  view.setUint32(40, samples.length * 2, true);
  floatTo16BitPCM(view, 44, samples);
  return new Blob([view], { type: 'audio/wav' });
}
