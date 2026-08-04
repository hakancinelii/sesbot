const state = {
  manifest: null,
  page: 24,
  paragraphIndex: 0,
  fullPageMode: false,
  playing: false,
};

const els = {
  bookTitle: document.getElementById("book-title"),
  pageLabel: document.getElementById("page-label"),
  pageInput: document.getElementById("page-input"),
  reader: document.getElementById("reader"),
  nowPlaying: document.getElementById("now-playing"),
  progressLabel: document.getElementById("progress-label"),
  audio: document.getElementById("audio"),
  seek: document.getElementById("seek"),
  fullPageMode: document.getElementById("full-page-mode"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  prevPara: document.getElementById("prev-para"),
  nextPara: document.getElementById("next-para"),
  playPause: document.getElementById("play-pause"),
  stop: document.getElementById("stop"),
  generatePage: document.getElementById("generate-page"),
};

function loadLastPage() {
  const saved = Number(localStorage.getItem("sesbot-last-page"));
  if (Number.isFinite(saved) && saved > 0) {
    return saved;
  }
  return null;
}

function saveLastPage() {
  localStorage.setItem("sesbot-last-page", String(state.page));
}

async function init() {
  let response = await fetch("/api/manifest", { cache: "no-store" });
  if (!response.ok) {
    response = await fetch("/manifest.json", { cache: "no-store" });
  }
  if (!response.ok) {
    throw new Error(`Manifest yuklenemedi: ${response.status}`);
  }
  state.manifest = await response.json();

  els.bookTitle.textContent = state.manifest.title.replace(/-/g, " ");
  const lastPage = loadLastPage();
  if (lastPage && state.manifest.pages[String(lastPage)]) {
    state.page = lastPage;
  } else if (state.manifest.availablePages.length) {
    state.page = state.manifest.availablePages[0];
  }

  bindEvents();
  renderPage();
}

function bindEvents() {
  els.prevPage.addEventListener("click", () => changePage(-1));
  els.nextPage.addEventListener("click", () => changePage(1));
  els.pageInput.addEventListener("change", () => {
    const value = Number(els.pageInput.value);
    if (value && state.manifest.pages[String(value)]) {
      state.page = value;
      saveLastPage();
      state.paragraphIndex = 0;
      renderPage();
    }
  });

  els.fullPageMode.addEventListener("change", () => {
    state.fullPageMode = els.fullPageMode.checked;
    stopPlayback();
  });

  els.playPause.addEventListener("click", togglePlayPause);
  els.stop.addEventListener("click", stopPlayback);
  els.prevPara.addEventListener("click", () => changeParagraph(-1, true));
  els.nextPara.addEventListener("click", () => changeParagraph(1, true));
  
  if (els.generatePage) {
    els.generatePage.addEventListener("click", () => generatePageAudio());
  }

  els.seek.addEventListener("input", () => {
    if (!Number.isFinite(els.audio.duration)) return;
    const target = (els.seek.value / 1000) * els.audio.duration;
    els.audio.currentTime = target;
  });

  els.audio.addEventListener("timeupdate", updateSeek);
  els.audio.addEventListener("ended", onAudioEnded);
  els.audio.addEventListener("play", () => setPlaying(true));
  els.audio.addEventListener("pause", () => setPlaying(false));

  document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT") return;
    if (event.code === "Space") {
      event.preventDefault();
      togglePlayPause();
    }
    if (event.code === "ArrowRight") changeParagraph(1, true);
    if (event.code === "ArrowLeft") changeParagraph(-1, true);
  });
}

function getPageItems(page) {
  return state.manifest.pages[String(page)] || [];
}

function renderPage() {
  const items = getPageItems(state.page);
  els.pageInput.value = state.page;
  els.pageLabel.textContent = `Sayfa ${state.page}`;

  if (!items.length) {
    els.reader.innerHTML = `<div class="page-sheet"><p class="paragraph missing">Bu sayfa icin metin bulunamadi.</p></div>`;
    updateStatus("Metin yok");
    return;
  }

  if (state.paragraphIndex >= items.length) {
    state.paragraphIndex = 0;
  }

  const sheet = document.createElement("div");
  sheet.className = "page-sheet";
  
  let hasMissing = false;

  items.forEach((item, index) => {
    const para = document.createElement("p");
    para.className = "paragraph";
    para.dataset.index = String(index);
    para.textContent = item.text;

    if (!item.available && !item.generatedAudio) {
      hasMissing = true;
      para.classList.add("missing");
    } else {
      para.classList.add("available");
    }

    para.addEventListener("click", () => {
      state.paragraphIndex = index;
      state.fullPageMode = false;
      els.fullPageMode.checked = false;
      highlightParagraph();
      if (item.available || item.generatedAudio) {
        playCurrent();
      } else {
        updateStatus("Bu paragraf icin ses yok");
      }
    });

    if (index === state.paragraphIndex) {
      para.classList.add("active");
    }

    sheet.appendChild(para);
  });

  els.reader.innerHTML = "";
  els.reader.appendChild(sheet);
  
  const pageKey = String(state.page);
  const pageHasAudio = Boolean(state.manifest.pageAudio?.[pageKey]);
  const shouldShowGenerate = hasMissing || !pageHasAudio;

  if (els.generatePage) {
    els.generatePage.style.display = shouldShowGenerate ? "inline-block" : "none";
    els.generatePage.innerHTML = pageHasAudio ? "🔊 Tam Sayfa Sesini Oynat" : "📑 Sayfayı Seslendir";
  }
  
  highlightParagraph(false);
  updateStatus("Hazir");
}

function highlightParagraph(scroll = true) {
  document.querySelectorAll(".paragraph").forEach((node) => {
    node.classList.toggle("active", Number(node.dataset.index) === state.paragraphIndex);
  });

  const active = document.querySelector(".paragraph.active");
  if (active && scroll) {
    active.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const items = getPageItems(state.page);
  const total = items.length;
  els.progressLabel.textContent = total
    ? `Paragraf ${state.paragraphIndex + 1}/${total}`
    : "Paragraf —";
}

function getPageList() {
  return Object.keys(state.manifest.pages)
    .map(Number)
    .sort((a, b) => a - b);
}

function changePage(delta) {
  const pages = getPageList();
  const currentIndex = pages.indexOf(state.page);
  const nextIndex = currentIndex + delta;
  if (nextIndex < 0 || nextIndex >= pages.length) return;

  state.page = pages[nextIndex];
  saveLastPage();
  state.paragraphIndex = 0;
  stopPlayback();
  renderPage();
}

function changeParagraph(delta, autoplay = false) {
  const items = getPageItems(state.page);
  const next = state.paragraphIndex + delta;
  if (next < 0 || next >= items.length) return;

  state.paragraphIndex = next;
  highlightParagraph();
  if (autoplay) {
    playCurrent();
  } else {
    updateStatus("Hazir");
  }
}

function togglePlayPause() {
  if (state.playing) {
    els.audio.pause();
    return;
  }
  playCurrent();
}

function playCurrent() {
  if (state.fullPageMode) {
    const src = state.manifest.pageAudio[String(state.page)];
    if (!src) {
      updateStatus("Bu sayfa icin birlesik ses yok");
      return;
    }
    loadAndPlay(src, `Sayfa ${state.page} (tam)`);
    return;
  }

  const items = getPageItems(state.page);
  const current = items[state.paragraphIndex];
  if (!current?.available && !current?.generatedAudio) {
    updateStatus("Bu paragraf icin ses yok");
    return;
  }

  const audioSrc = current.generatedAudio || current.audio;
  if (!audioSrc) {
    updateStatus("Bu paragraf icin ses yok");
    return;
  }

  loadAndPlay(audioSrc, `Sayfa ${state.page}, paragraf ${state.paragraphIndex + 1}`);
}

function loadAndPlay(src, label) {
  if (els.audio.getAttribute("src") !== src) {
    els.audio.setAttribute("src", src);
  }
  updateStatus(label);
  els.audio.play().catch(() => {
    updateStatus("Oynatma baslatilamadi");
    setPlaying(false);
  });
}

function stopPlayback() {
  els.audio.pause();
  els.audio.currentTime = 0;
  setPlaying(false);
  updateStatus("Durduruldu");
}

function onAudioEnded() {
  if (state.fullPageMode) {
    setPlaying(false);
    updateStatus(`Sayfa ${state.page} tamamlandi`);
    return;
  }

  const items = getPageItems(state.page);
  if (state.paragraphIndex < items.length - 1) {
    state.paragraphIndex += 1;
    highlightParagraph();
    playCurrent();
    return;
  }

  setPlaying(false);
  updateStatus(`Sayfa ${state.page} tamamlandi`);
}

function setPlaying(value) {
  state.playing = value;
  els.playPause.textContent = value ? "⏸" : "▶";
}

function updateStatus(text) {
  els.nowPlaying.textContent = text;
}

function updateSeek() {
  if (!Number.isFinite(els.audio.duration) || els.audio.duration <= 0) {
    els.seek.value = 0;
    return;
  }
  els.seek.value = Math.round((els.audio.currentTime / els.audio.duration) * 1000);
}

async function generateAudio(paraIndex, text, btnElement = null, autoPlay = true) {
  if (btnElement) {
    btnElement.innerHTML = "⏳ Uretiliyor...";
    btnElement.disabled = true;
  }
  updateStatus("Dinamik ses uretiliyor (10-30 sn surebilir)...");

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        page: state.page,
        paragraphIndex: paraIndex,
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Sunucu hatasi: ${response.status} ${err}`);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const generatedPath = response.headers.get("X-Generated-Audio-Path");
    const supabaseUrl = response.headers.get("X-Supabase-Audio-Url");

    // Store generated audio path and blob URL in state
    const items = getPageItems(state.page);
    if (items[paraIndex]) {
      if (supabaseUrl) {
        items[paraIndex].audio = supabaseUrl;
        items[paraIndex].available = true;
      } else if (generatedPath) {
        items[paraIndex].audio = generatedPath;
        items[paraIndex].available = true;
      }
      items[paraIndex].generatedAudio = url;
    }

    if (btnElement) {
      btnElement.innerHTML = "✅ Dinle";
      btnElement.disabled = false;
      btnElement.onclick = (e) => {
        e.stopPropagation();
        state.paragraphIndex = paraIndex;
        highlightParagraph();
        loadAndPlay(url, "Dinamik Uretilen Ses");
      };
    }
    
    if (autoPlay) {
      state.paragraphIndex = paraIndex;
      highlightParagraph();
      loadAndPlay(url, "Dinamik Uretilen Ses");
    }
    return true;
  } catch (error) {
    console.error("Ses uretme hatasi:", error);
    updateStatus("Uretim hatasi: " + error.message);
    if (btnElement) {
      btnElement.innerHTML = "❌ Hata (Tekrar dene)";
      btnElement.disabled = false;
    }
    return false;
  }
}

async function generatePageAudio() {
  if (els.generatePage) {
    els.generatePage.disabled = true;
    els.generatePage.innerHTML = "⏳ Sayfa Üretiliyor...";
  }

  state.fullPageMode = false;
  els.fullPageMode.checked = false;

  const items = getPageItems(state.page);
  const pageKey = String(state.page);
  const existingPageAudio = state.manifest.pageAudio?.[pageKey];

  if (existingPageAudio) {
    state.fullPageMode = true;
    els.fullPageMode.checked = true;
    renderPage();
    playCurrent();
    if (els.generatePage) {
      els.generatePage.disabled = false;
      els.generatePage.innerHTML = "🔊 Tam Sayfa Sesini Oynat";
    }
    return;
  }

  let missingParagraphs = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (!item.available && !item.generatedAudio) {
      missingParagraphs.push({ index: i, text: item.text });
    }
  }

  for (const paragraph of missingParagraphs) {
    let success = false;
    while (!success) {
      success = await generateAudio(paragraph.index, paragraph.text, null, false);
      if (!success) {
        updateStatus("Hata alindi, tekrar deneniyor...");
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
  }

  if (els.generatePage) {
    els.generatePage.disabled = false;
    els.generatePage.innerHTML = "✅ Sayfa Üretildi";
    els.generatePage.style.display = "none";
  }

  renderPage();

  const mergeResponse = await fetch("/api/merge-page", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: state.page }),
  });

  if (mergeResponse.ok) {
    const data = await mergeResponse.json();
    state.manifest.pageAudio[String(state.page)] = data.pageAudio;
    state.fullPageMode = true;
    els.fullPageMode.checked = true;
    playCurrent();
  } else {
    const errorText = await mergeResponse.text();
    console.error("Sayfa birlestirme hatasi:", errorText);
    updateStatus("Sayfa ses birlestirilemedi");
  }
}

init().catch((error) => {
  els.reader.innerHTML = `<div class="page-sheet"><p class="paragraph missing">Arayuz yuklenemedi: ${error.message}</p></div>`;
});
