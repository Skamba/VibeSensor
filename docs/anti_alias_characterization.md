# Anti-Alias Characterization

VibeSensor's current anti-alias characterization starts with the **digital
chain**:

- firmware sample rate / ODR
- FFT size
- analysis band
- observed FFT peak location after sampling

Use the characterization tool to see which out-of-band tones fold back into the
current analysis band:

```bash
.venv/bin/python tools/dev/characterize_aliasing.py
.venv/bin/python tools/dev/characterize_aliasing.py --sample-rate-hz 400 --fft-n 1024
```

It is a developer tool in `tools/dev/`, not part of the server package; run it
from the repo root with the repo venv. `--help` lists the sample-rate, FFT-size,
analysis-band and scan-range options (defaults are the current runtime values).

The tool reports:

- the current Nyquist limit and FFT bin spacing
- out-of-band input-frequency intervals that alias into the configured analysis
  band
- representative pure-tone examples run through the current FFT path

Important limitation: this is **not** a full hardware anti-alias certification.
It assumes the current sampled data reaches the server as-is. Real anti-alias
performance still depends on the sensor and any analog / sensor-side bandwidth
limiting ahead of sampling.
