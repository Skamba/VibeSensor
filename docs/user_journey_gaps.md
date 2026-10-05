# User-journey gaps and work packages

Living tracker for the gaps between [user_journeys.md](user_journeys.md) (the
target state) and the code.

**How to maintain it:**

- Each work-package PR removes the gaps it fixes from this file, deletes the
  package from §2 when it is complete, and rewrites the matching **Today:**
  notes in [user_journeys.md](user_journeys.md).
- Evidence names files and functions, not line numbers.
- Delete this file (and its links) when the last gap is gone.

WP0 (diagnosis queued fixes: J16, J30, J31, J32, J33, J34) shipped in #4109.
J09 (variant tire options) shipped in #4110. WP1a (references may be missing:
J02, J03, J06, J18, J25, the backend half of J01 and the measured-RPM bands of
J24) shipped in #4115. WP1b (provenance-aware source checks: J27, the
analysis half of J15, the report half of J24, and the provenance data for J35)
shipped in #4117. WP3 (speed source, readiness and dashboard UI: J14, J15,
J17, J19, J20, J21, J24 and most of J13) shipped in #4125. WP4 (report and
History wording: J28, J29, J35) shipped in #4127. WP2 (settings and car wizard
UI: J01, J04, J05, J07, J08) shipped in #4128. The rest of J13 (a paired
OBD-II adapter is the speed source until the user picks one) shipped with the
Pi-verification server fixes. WP7 (EV and PHEV handling: J12) shipped in
#4138. Its remaining EV wording (the car row's reduction ratio, the estimate
note, the one-sensor hints and the speed-variation check) shipped with the
second round of Pi-verification UI fixes. WP6 (the printable hotspot QR card:
J23) shipped in #4139. The picker half of J10 (one picker model per
generation, the model year resolved in the variant step) shipped in #4153.

Owner decisions that bound the fixes (settled):

- Estimated engine RPM keeps assuming top gear for the whole drive. No
  gear-shift analysis; the limitation is stated clearly in the UI and report.
- Final drive and top gear are optional; the tire size is the minimum.
- A missing reference gives "couldn't test", never a silent default.

Severity scale:

- **blocks**: the user cannot complete the journey, or would have to invent
  data.
- **misleads**: the user or mechanic is told something untrue or over-confident.
- **friction**: the journey works but is harder than it needs to be.

Ids from earlier reviews are given in brackets (F1–F4, B2).

---

## 1. Gap list (by severity)

### Blocks

None open.

### Misleads

None open.

### Friction

**J10 — Launch-year-only rows (data gap).**

Evidence:

- Generations with launch-year rows only: F20 2011–2012, G11 2016,
  F15 2014–2015. The picker shows a generation's years from its rows, so a
  2015 F20 owner sees "1 Series (F20, 2011-2012)". F10 (2011–2016) and G30
  (2017–2023) are extended.

Fix: **Data:** extend the year ranges where the drivetrain did not change
(WP5).

**J11 — Coverage breadth and weak data (data gap).**

Evidence ([user_journeys.md](user_journeys.md) §4):

- Audi and BMW only.
- No 3 Series Touring (5 Series Touring F11/G31/G61 exists), and no Avant
  except RS 4/RS 6.
- No generation before about 2011.
- 44% of rows have a weak final drive and 41% a weak top gear.

Fix: see WP5.

---

## 2. Work packages (one PR each)

Dependency order:

- WP5 is the only package left.

### WP5 — Car-library data

- **Covers:** J10, J11.
- **Changes:**
  - Extend year ranges where the drivetrain did not change.
  - Add Touring and Avant bodies for the 3/5 Series and A4/A6.
  - Upgrade the weak final drives by transmission code from official
    catalogues.
  - Never invent values. Leave a field null with an `unresolved` note when it
    is unverifiable, as was done for the 8S TT rows.
- **Validation:** the car-library schema tests and
  `tools/car_library/car_library_stats.py` before and after; update the table
  in [user_journeys.md](user_journeys.md) §4.
- **Depends on:** nothing. Gearboxes with a null final drive are served.

---

## 3. Suggested order

WP5 at any time.
