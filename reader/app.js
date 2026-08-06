const FADE_IN_MS = 250;
const FADE_OUT_MS = 250;
const PARAGRAPH_PAUSE_MS = 600;

const state = {
  manifest: null,
  page: 24,
  paragraphIndex: 0,
  fullPageMode: false,
  playing: false,
  fadeOutAtEnd: false,
  fadingOut: false,
  volumeRaf: null,
  transitionTimer: null,
  generationCancelled: false,
  autoNarration: false,
  immersive: false,
  wakeLock: null,
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
  immersiveToggle: document.getElementById("immersive-toggle"),
  immersiveExit: document.getElementById("immersive-exit"),
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
  const firstPage = getPageList()[0] || 1;
  if (lastPage && state.manifest.pages[String(lastPage)]) {
    state.page = lastPage;
  } else {
    state.page = firstPage;
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
    els.generatePage.addEventListener("click", () => {
      const items = getPageItems(state.page);
      const hasAudio = items.some((it) => !it.heading && isPlayable(it));
      startBookNarration(state.page, hasAudio);
    });
  }

  els.seek.addEventListener("input", () => {
    if (!Number.isFinite(els.audio.duration)) return;
    cancelVolumeRamp();
    els.audio.volume = 1;
    state.fadingOut = false;
    const target = (els.seek.value / 1000) * els.audio.duration;
    els.audio.currentTime = target;
  });

  els.audio.addEventListener("timeupdate", () => {
    updateSeek();
    handleFadeOut();
  });
  els.audio.addEventListener("ended", onAudioEnded);
  els.audio.addEventListener("play", () => {
    setPlaying(true);
    rampVolume(1, FADE_IN_MS);
    if (state.immersive) requestWakeLock();
  });
  els.audio.addEventListener("pause", () => {
    setPlaying(false);
    cancelVolumeRamp();
    releaseWakeLock();
  });

  if (els.immersiveToggle) {
    els.immersiveToggle.addEventListener("click", () => setImmersive(!state.immersive));
  }
  if (els.immersiveExit) {
    els.immersiveExit.addEventListener("click", () => setImmersive(false));
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.playing) {
      requestWakeLock();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT") return;
    if (event.code === "Space") {
      event.preventDefault();
      togglePlayPause();
    }
    if (event.code === "Escape" && state.immersive) {
      setImmersive(false);
    }
    if (event.code === "ArrowRight") changePage(1);
    if (event.code === "ArrowLeft") changePage(-1);
  });

  let touchStartX = null;
  els.reader.addEventListener(
    "touchstart",
    (event) => {
      touchStartX = event.touches[0].clientX;
    },
    { passive: true }
  );
  els.reader.addEventListener(
    "touchend",
    (event) => {
      if (touchStartX === null) return;
      const dx = event.changedTouches[0].clientX - touchStartX;
      if (Math.abs(dx) > 60) {
        changePage(dx < 0 ? 1 : -1);
      }
      touchStartX = null;
    },
    { passive: true }
  );
}

function getPageItems(page) {
  return state.manifest.pages[String(page)] || [];
}

function isPlayable(item) {
  return item && !item.heading && (item.available || item.generatedAudio);
}

function nextPlayableIndex(page, fromIndex, delta) {
  const items = getPageItems(page);
  let i = fromIndex + delta;
  while (i >= 0 && i < items.length) {
    if (items[i] && !items[i].heading) return i;
    i += delta;
  }
  return null;
}

function firstPlayableIndex(page) {
  return nextPlayableIndex(page, -1, 1);
}

function buildSheet(items) {
  const sheet = document.createElement("div");
  sheet.className = "page-sheet";

  if (state.manifest.cover && state.page === getPageList()[0]) {
    const figure = document.createElement("figure");
    figure.className = "cover-figure";
    const img = document.createElement("img");
    img.className = "cover-image";
    img.src = state.manifest.cover;
    img.alt = state.manifest.title.replace(/-/g, " ");
    figure.appendChild(img);
    sheet.appendChild(figure);
  }

  items.forEach((item, index) => {
    if (item.heading) {
      const heading = document.createElement("h2");
      heading.className = "paragraph chapter-heading";
      heading.textContent = item.text;
      sheet.appendChild(heading);
      return;
    }

    const para = document.createElement("p");
    para.className = "paragraph";
    para.dataset.index = String(index);
    para.textContent = item.text;

    if (!item.available && !item.generatedAudio) {
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

  return sheet;
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
  if (items[state.paragraphIndex]?.heading) {
    const first = firstPlayableIndex(state.page);
    if (first !== null) state.paragraphIndex = first;
  }

  els.reader.innerHTML = "";
  els.reader.appendChild(buildSheet(items));

  const pageKey = String(state.page);
  const pageHasAudio =
    Boolean(state.manifest.pageAudio?.[pageKey]) ||
    items.some((it) => it.available || it.generatedAudio);

  if (els.generatePage) {
    els.generatePage.style.display = "inline-block";
    els.generatePage.innerHTML = pageHasAudio
      ? "🔁 Sayfayı Yeniden Seslendir (sonra devam)"
      : "📚 Sayfayı Seslendir (sonra devam)";
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
  const playable = items.filter((it) => !it.heading);
  let current = 0;
  for (let i = 0; i <= state.paragraphIndex; i++) {
    if (items[i] && !items[i].heading) current++;
  }
  els.progressLabel.textContent = playable.length
    ? `Paragraf ${current}/${playable.length}`
    : "Paragraf —";
}

function getPageList() {
  return Object.keys(state.manifest.pages)
    .map(Number)
    .sort((a, b) => a - b);
}

function getNextAudioPage(fromPage) {
  const pages = getPageList();
  const idx = pages.indexOf(fromPage);
  for (let i = idx + 1; i < pages.length; i++) {
    const items = getPageItems(pages[i]);
    if (items.some((it) => it.available || it.generatedAudio)) {
      return pages[i];
    }
  }
  return null;
}

function getSequentialNextPage(fromPage) {
  const pages = getPageList();
  const idx = pages.indexOf(fromPage);
  return idx + 1 < pages.length ? pages[idx + 1] : null;
}

async function advanceToNextPage() {
  const next = getNextAudioPage(state.page);
  if (next !== null) {
    navigateToPage(next, 1, { autoplay: true });
    return;
  }
  setPlaying(false);
  updateStatus("Sonraki sayfanın sesi hazır değil. 'Sayfayı Seslendir' butonuyla üretin.");
}

function animatePageFlip(oldItems, newItems, delta, onDone) {
  const reader = els.reader;
  const oldSheet = buildSheet(oldItems);
  const newSheet = buildSheet(newItems);

  reader.classList.add("book");
  reader.innerHTML = "";

  const still = document.createElement("div");
  still.className = "sheet-layer still";
  still.appendChild(newSheet);

  const flip = document.createElement("div");
  flip.className = "sheet-layer flip";
  flip.appendChild(oldSheet);

  reader.appendChild(still);
  reader.appendChild(flip);

  requestAnimationFrame(() => {
    requestAnimationFrame(() =>
      flip.classList.add(delta > 0 ? "turning-forward" : "turning-backward")
    );
  });

  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    reader.classList.remove("book");
    renderPage();
    if (onDone) onDone();
  };
  const inner = flip.querySelector(".page-sheet");
  inner.addEventListener("animationend", finish);
  setTimeout(finish, 1100);
}

function navigateToPage(targetPage, delta, { autoplay = false } = {}) {
  if (targetPage === state.page) return;
  const oldItems = getPageItems(state.page);

  state.page = targetPage;
  saveLastPage();
  const first = firstPlayableIndex(targetPage);
  state.paragraphIndex = first !== null ? first : 0;
  stopPlayback();

  animatePageFlip(oldItems, getPageItems(targetPage), delta, () => {
    if (autoplay) playCurrent();
  });
}

function changePage(delta) {
  const pages = getPageList();
  const currentIndex = pages.indexOf(state.page);
  const nextIndex = currentIndex + delta;
  if (nextIndex < 0 || nextIndex >= pages.length) return;
  navigateToPage(pages[nextIndex], delta);
}

function changeParagraph(delta, autoplay = false) {
  const next = nextPlayableIndex(state.page, state.paragraphIndex, delta);
  if (next === null) return;

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
    if (state.transitionTimer) {
      clearTimeout(state.transitionTimer);
      state.transitionTimer = null;
      setPlaying(false);
      updateStatus("Durduruldu");
      return;
    }
    els.audio.pause();
    return;
  }
  playCurrent();
}

function setImmersive(on) {
  state.immersive = on;
  document.body.classList.toggle("immersive", on);
  if (on) {
    if (state.playing) requestWakeLock();
    if (document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  } else {
    releaseWakeLock();
    if (document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    }
  }
}

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator && document.visibilityState === "visible") {
      state.wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch (error) {
    console.warn("Wake lock alinamadi:", error);
  }
}

function releaseWakeLock() {
  if (state.wakeLock) {
    state.wakeLock.release().catch(() => {});
    state.wakeLock = null;
  }
}

function playCurrent() {
  if (state.fullPageMode) {
    const src = state.manifest.pageAudio[String(state.page)];
    if (!src) {
      updateStatus("Bu sayfa icin birlesik ses yok");
      return;
    }
    state.fadeOutAtEnd = willAutoAdvanceAfterCurrent();
    loadAndPlay(src, `Sayfa ${state.page} (tam)`);
    return;
  }

  const items = getPageItems(state.page);
  let idx = state.paragraphIndex;
  if (items[idx]?.heading) {
    const next = nextPlayableIndex(state.page, idx, 1);
    if (next === null) {
      updateStatus("Bu sayfada seslendirilecek metin yok");
      return;
    }
    state.paragraphIndex = next;
    highlightParagraph();
    idx = next;
  }

  const current = items[idx];
  if (!isPlayable(current)) {
    updateStatus("Bu paragraf icin ses yok");
    return;
  }

  const audioSrc = current.generatedAudio || current.audio;
  if (!audioSrc) {
    updateStatus("Bu paragraf icin ses yok");
    return;
  }

  state.fadeOutAtEnd = willAutoAdvanceAfterCurrent();
  loadAndPlay(audioSrc, `Sayfa ${state.page}, paragraf ${idx + 1}`);
}

function willAutoAdvanceAfterCurrent() {
  if (state.fullPageMode) {
    return getNextAudioPage(state.page) !== null;
  }
  if (nextPlayableIndex(state.page, state.paragraphIndex, 1) !== null) {
    return true;
  }
  return getNextAudioPage(state.page) !== null;
}

function cancelVolumeRamp() {
  if (state.volumeRaf) {
    cancelAnimationFrame(state.volumeRaf);
    state.volumeRaf = null;
  }
  state.fadingOut = false;
}

function easeStep(t) {
  return t * t * (3 - 2 * t);
}

function rampVolume(target, ms) {
  cancelVolumeRamp();
  const start = els.audio.volume;
  if (ms <= 0) {
    els.audio.volume = target;
    return;
  }
  const startTime = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - startTime) / ms);
    els.audio.volume = start + (target - start) * easeStep(t);
    if (t < 1) {
      state.volumeRaf = requestAnimationFrame(step);
    } else {
      state.volumeRaf = null;
    }
  };
  state.volumeRaf = requestAnimationFrame(step);
}

function handleFadeOut() {
  if (!state.fadeOutAtEnd || state.fadingOut) return;
  if (els.audio.paused) return;
  if (!Number.isFinite(els.audio.duration) || els.audio.duration <= 0) return;
  const remainingMs = (els.audio.duration - els.audio.currentTime) * 1000;
  if (remainingMs <= FADE_OUT_MS) {
    state.fadingOut = true;
    rampVolume(0, Math.max(120, remainingMs));
  }
}

function loadAndPlay(src, label) {
  if (els.audio.getAttribute("src") !== src) {
    els.audio.setAttribute("src", src);
    els.audio.volume = 0;
  }
  updateStatus(label);
  els.audio.play().catch(() => {
    els.audio.volume = 1;
    updateStatus("Oynatma baslatilamadi");
    setPlaying(false);
  });
}

function stopPlayback() {
  cancelVolumeRamp();
  state.generationCancelled = true;
  if (state.transitionTimer) {
    clearTimeout(state.transitionTimer);
    state.transitionTimer = null;
  }
  releaseWakeLock();
  els.audio.volume = 1;
  els.audio.pause();
  els.audio.currentTime = 0;
  setPlaying(false);
  updateStatus("Durduruldu");
}

function onAudioEnded() {
  if (state.fullPageMode) {
    advanceToNextPage();
    return;
  }

  const nextPara = nextPlayableIndex(state.page, state.paragraphIndex, 1);
  if (nextPara !== null) {
    state.paragraphIndex = nextPara;
    highlightParagraph();
    setPlaying(true);
    updateStatus("Paragraf geçişi...");
    state.transitionTimer = setTimeout(() => {
      state.transitionTimer = null;
      playCurrent();
    }, PARAGRAPH_PAUSE_MS);
    return;
  }

  advanceToNextPage();
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

async function generateAudio(page, paraIndex, text, btnElement = null, autoPlay = true) {
  if (btnElement) {
    btnElement.innerHTML = "⏳ Uretiliyor...";
    btnElement.disabled = true;
  }
  if (page === state.page) {
    updateStatus("Dinamik ses uretiliyor (10-30 sn surebilir)...");
  }

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        page,
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
    const items = getPageItems(page);
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

async function generatePageAudio(page = state.page, force = false) {
  const isCurrent = page === state.page;
  const items = getPageItems(page);
  const playableItems = items.filter((it) => !it.heading);
  const fullyNarrated =
    playableItems.length > 0 && playableItems.every((it) => isPlayable(it));

  // Sayfa zaten tamamen sesliyse ve zorlamiyorsak atla
  if (fullyNarrated && !force) {
    if (isCurrent) {
      updateStatus("Sayfa zaten sesli");
    }
    return true;
  }

  if (isCurrent && els.generatePage) {
    els.generatePage.disabled = true;
    els.generatePage.innerHTML = "⏳ Sayfa Üretiliyor...";
  }
  state.fullPageMode = false;
  els.fullPageMode.checked = false;

  // 1) Eski sesleri Supabase'ten sil
  try {
    const clearResp = await fetch("/api/clear-page", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page }),
    });
    if (!clearResp.ok) {
      console.error("Eski sesler silinemedi:", await clearResp.text());
    }
  } catch (error) {
    console.error("Sayfa temizleme hatasi:", error);
  }

  // 2) Yerel durumu temizle
  items.forEach((item) => {
    if (item.generatedAudio && item.generatedAudio.startsWith("blob:")) {
      URL.revokeObjectURL(item.generatedAudio);
    }
    item.available = false;
    item.audio = null;
    item.generatedAudio = null;
  });
  if (state.manifest.pageAudio) {
    delete state.manifest.pageAudio[String(page)];
  }
  if (isCurrent) renderPage();

  // 3) Tum paragraflari sifirdan uret (basliklar haric)
  for (let i = 0; i < items.length; i++) {
    if (items[i].heading) continue;
    if (state.generationCancelled) break;
    let success = false;
    while (!success) {
      if (state.generationCancelled) break;
      success = await generateAudio(page, i, items[i].text, null, false);
      if (!success) {
        updateStatus(`Sayfa ${page} hata (paragraf ${i + 1}/${playableItems.length}), tekrar deneniyor...`);
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
  }

  if (isCurrent && els.generatePage) {
    els.generatePage.disabled = false;
    els.generatePage.innerHTML = "✅ Sayfa Üretildi";
  }
  if (isCurrent) renderPage();

  // 4) Birlesik sayfa sesini olustur (Supabase'teki paragraflardan)
  try {
    const mergeResponse = await fetch("/api/merge-page", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page }),
    });
    if (mergeResponse.ok) {
      const data = await mergeResponse.json();
      if (data.pageAudio) {
        state.manifest.pageAudio[String(page)] = data.pageAudio;
      }
      if (isCurrent) {
        state.fullPageMode = true;
        els.fullPageMode.checked = true;
        playCurrent();
      }
    } else if (isCurrent) {
      updateStatus("Sayfa seslendirildi");
    }
  } catch (error) {
    console.error("Sayfa birlestirme hatasi:", error);
    if (isCurrent) updateStatus("Sayfa seslendirildi");
  }
  return true;
}

async function startBookNarration(page = state.page, forceCurrent = false) {
  if (state.autoNarration) return;
  state.autoNarration = true;
  state.generationCancelled = false;
  let current = page;
  let force = forceCurrent;
  while (state.autoNarration && !state.generationCancelled) {
    updateStatus(`Sayfa ${current} seslendiriliyor...`);
    await generatePageAudio(current, force);
    if (state.generationCancelled) break;
    const next = getSequentialNextPage(current);
    if (next === null) break;
    current = next;
    force = false;
  }
  state.autoNarration = false;
  if (!state.generationCancelled) {
    updateStatus("Kitap seslendirmesi tamamlandı");
  }
}

init().catch((error) => {
  els.reader.innerHTML = `<div class="page-sheet"><p class="paragraph missing">Arayuz yuklenemedi: ${error.message}</p></div>`;
});
