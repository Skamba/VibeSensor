(() => {
  const els = {
    speed: document.getElementById("speed"),
    clientSelect: document.getElementById("clientSelect"),
    renameInput: document.getElementById("renameInput"),
    renameBtn: document.getElementById("renameBtn"),
    identifyBtn: document.getElementById("identifyBtn"),
    waveAxis: document.getElementById("waveAxis"),
    specAxis: document.getElementById("specAxis"),
    lastSeen: document.getElementById("lastSeen"),
    dropped: document.getElementById("dropped"),
    framesTotal: document.getElementById("framesTotal"),
    linkState: document.getElementById("linkState"),
    metricX: document.getElementById("metric-x"),
    metricY: document.getElementById("metric-y"),
    metricZ: document.getElementById("metric-z"),
    waveChart: document.getElementById("waveChart"),
    specChart: document.getElementById("specChart"),
  };

  const state = {
    ws: null,
    clients: [],
    selectedClientId: null,
    lastSelectedPayload: null,
    waveformPlot: null,
    spectrumPlot: null,
  };

  const axisColor = (axis) => {
    if (axis === "x") return "#2a9d8f";
    if (axis === "y") return "#f4a261";
    return "#e63946";
  };

  const chartWidth = (el) => Math.max(280, Math.floor(el.getBoundingClientRect().width - 20));

  function mkPlot(target, title, xLabel, yLabel, axis) {
    return new uPlot(
      {
        title,
        width: chartWidth(target),
        height: 260,
        scales: { x: { time: false } },
        axes: [{ label: xLabel }, { label: yLabel }],
        series: [{}, { stroke: axisColor(axis), width: 2 }],
      },
      [[], []],
      target,
    );
  }

  function ensurePlots() {
    if (!state.waveformPlot) {
      state.waveformPlot = mkPlot(els.waveChart, "Waveform", "Seconds", "LSB", els.waveAxis.value);
    }
    if (!state.spectrumPlot) {
      state.spectrumPlot = mkPlot(els.specChart, "Spectrum", "Hz", "Amplitude", els.specAxis.value);
    }
  }

  function renderClientSelect() {
    const current = state.selectedClientId;
    els.clientSelect.innerHTML = "";
    for (const client of state.clients) {
      const option = document.createElement("option");
      option.value = client.id;
      option.textContent = `${client.name} (${client.id})`;
      els.clientSelect.appendChild(option);
    }
    if (!state.selectedClientId && state.clients.length > 0) {
      state.selectedClientId = state.clients[0].id;
    }
    if (current && state.clients.some((c) => c.id === current)) {
      state.selectedClientId = current;
    }
    if (state.selectedClientId) {
      els.clientSelect.value = state.selectedClientId;
    }
  }

  function fmt(n, digits = 2) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "--";
    return n.toFixed(digits);
  }

  function renderMetrics(metrics) {
    for (const axis of ["x", "y", "z"]) {
      const el = axis === "x" ? els.metricX : axis === "y" ? els.metricY : els.metricZ;
      const m = metrics?.[axis];
      if (!m) {
        el.innerHTML = `<h3 class="metric-title">${axis.toUpperCase()} Axis</h3><p class="metric-sub">No data</p>`;
        continue;
      }
      const peaks = (m.peaks || [])
        .map((p, i) => `P${i + 1}: ${fmt(p.hz, 1)} Hz @ ${fmt(p.amp, 1)}`)
        .join("<br/>");
      el.innerHTML = `
        <h3 class="metric-title">${axis.toUpperCase()} Axis</h3>
        <p class="metric-sub">RMS: ${fmt(m.rms, 3)} | P2P: ${fmt(m.p2p, 3)}</p>
        <p class="metric-sub">${peaks || "Peaks: --"}</p>
      `;
    }
  }

  function renderStatus(clientRow) {
    if (!clientRow) {
      els.lastSeen.textContent = "Last seen: --";
      els.dropped.textContent = "Dropped frames: --";
      els.framesTotal.textContent = "Frames total: --";
      return;
    }
    const age = clientRow.last_seen_age_ms ?? null;
    els.lastSeen.textContent = age === null ? "Last seen: --" : `Last seen: ${age} ms ago`;
    els.dropped.textContent = `Dropped frames: ${clientRow.dropped_frames ?? 0}`;
    els.framesTotal.textContent = `Frames total: ${clientRow.frames_total ?? 0}`;
  }

  function renderCharts() {
    ensurePlots();
    const selected = state.lastSelectedPayload;
    if (!selected) return;

    const waveAxis = els.waveAxis.value;
    const waveT = selected.waveform?.t || [];
    const waveY = selected.waveform?.[waveAxis] || [];
    state.waveformPlot.setData([waveT, waveY]);

    const specAxis = els.specAxis.value;
    const f = selected.spectrum?.freq || [];
    const a = selected.spectrum?.[specAxis] || [];
    state.spectrumPlot.setData([f, a]);
  }

  function sendSelection() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ client_id: state.selectedClientId }));
    }
  }

  function connectWS() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    state.ws = new WebSocket(`${proto}//${window.location.host}/ws`);

    state.ws.onopen = () => {
      els.linkState.textContent = "WS: connected";
      els.linkState.className = "panel status-ok";
      sendSelection();
    };

    state.ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      state.clients = payload.clients || [];
      renderClientSelect();

      if (typeof payload.speed_mps === "number") {
        els.speed.textContent = `Speed: ${fmt(payload.speed_mps, 2)} m/s`;
      } else {
        els.speed.textContent = "Speed: -- m/s";
      }

      state.lastSelectedPayload = payload.selected || null;
      renderCharts();
      renderMetrics(state.lastSelectedPayload?.metrics || {});
      const row = state.clients.find((c) => c.id === state.selectedClientId);
      renderStatus(row);
    };

    state.ws.onclose = () => {
      els.linkState.textContent = "WS: reconnecting...";
      els.linkState.className = "panel status-bad";
      window.setTimeout(connectWS, 1200);
    };
  }

  async function renameClient() {
    if (!state.selectedClientId) return;
    const name = els.renameInput.value.trim();
    if (!name) return;
    await fetch(`/api/clients/${state.selectedClientId}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    els.renameInput.value = "";
  }

  async function identifyClient() {
    if (!state.selectedClientId) return;
    await fetch(`/api/clients/${state.selectedClientId}/identify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration_ms: 1500 }),
    });
  }

  els.clientSelect.addEventListener("change", () => {
    state.selectedClientId = els.clientSelect.value;
    sendSelection();
  });
  els.waveAxis.addEventListener("change", renderCharts);
  els.specAxis.addEventListener("change", renderCharts);
  els.renameBtn.addEventListener("click", renameClient);
  els.identifyBtn.addEventListener("click", identifyClient);
  window.addEventListener("resize", () => {
    if (state.waveformPlot) {
      state.waveformPlot.setSize({ width: chartWidth(els.waveChart), height: 260 });
    }
    if (state.spectrumPlot) {
      state.spectrumPlot.setSize({ width: chartWidth(els.specChart), height: 260 });
    }
  });

  connectWS();
})();
