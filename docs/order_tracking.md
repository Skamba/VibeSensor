# Order Tracking

Scope: shared order-reference math and the post-stop order-analysis flow.

VibeSensor uses the same vehicle-order reference model in two places:

- live telemetry, where the server precomputes order bands for spectrum views
- post-stop diagnostics, where the summary analysis matches each run's sample
  peaks (recomputed from raw capture when it is available) against the
  predicted wheel / driveshaft / engine order bands

The shared physics lives in `apps/server/vibesensor/domain/order_reference.py`
and `apps/server/vibesensor/dsp/order_bands.py`. The post-stop finding flow
lives in `apps/server/vibesensor/analysis/orders/`.

## Core concepts

| Concept | Owner | Purpose |
|---------|-------|---------|
| `OrderReferenceSpec` | `domain/order_reference.py` | Tire geometry, final-drive ratio, gear ratio, and uncertainty settings for order analysis. |
| `vehicle_orders_hz()` | `dsp/order_bands.py` | Resolve wheel / driveshaft / engine reference frequencies for one speed sample. |
| `build_order_bands()` | `dsp/order_bands.py` | Precompute live order-band payloads so the frontend does not duplicate tolerance math. |
| `OrderHypothesis` | `analysis/orders/physics.py` | One named order candidate such as `wheel_1x` or `engine_2x`. |
| `OrderAnalysisSession` | `analysis/orders/pipeline.py` | Sample-peak order pass used by the summary analysis. |

## From speed to reference frequencies

`OrderReferenceSpec` turns vehicle speed plus car-reference data into rotational
frequencies:

```text
wheel_hz      = speed_mps / tire_circumference_m
driveshaft_hz = wheel_hz * final_drive_ratio
engine_hz     = driveshaft_hz * current_gear_ratio
```

The spec exposes capability checks before any of that math is used:

- `supports_wheel_reference`
- `supports_driveshaft_reference`
- `supports_engine_reference`

If the required tire or driveline data is missing, VibeSensor omits the order
reference instead of inventing one.

## Engine orders

An engine order `E<m>` is a vibration at *m* times the crankshaft speed (for a
rotary, the eccentric shaft). Which orders an engine excites follows from its
profile, layout and cylinder (rotor) count, plus a V or W engine's bank angle
when known (`EngineProfile` in `apps/server/vibesensor/domain/engine_profile.py`).
Library cars read the profile from their engine text (`B58 3.0L I6 Turbo` is
an inline-6); a custom car's owner can pick it. `engine_orders(profile)` maps
the profile through one rules table, `ENGINE_ORDER_RULES`, to its orders, each
with its roles:

| Rule (role) | Engines | Order |
|---|---|---|
| rotating | every engine | E1: the crank's own rotation (unbalanced rotating parts, crank pulley, flywheel) |
| firing | four-stroke piston (inline, V, flat, W) | E(n/2) for *n* evenly firing cylinders: twin E1, inline-3 E1.5, four E2, five E2.5, six E3, V8 E4, V10 E5, V12/W12 E6 |
| firing | rotary | E1 per rotor: each rotor fires once per eccentric-shaft turn (three faces, rotor at a third of shaft speed) |
| imbalance | inline-3 | E1: primary rocking couple |
| imbalance | inline-4 | E2: secondary free force (same order as its firing rhythm) |
| imbalance | V6, 90° bank angle | E1: primary rocking couple (cancelled where a balance shaft is fitted; VibeSensor does not record balance shafts) |
| imbalance | flat-4 | E2: secondary rocking couple |

Inline-6, flat-6, V12 and cross-plane V8 engines are inherently balanced (no
free primary or secondary forces or couples) and add no imbalance row. Not
modelled: flat-plane V8s (secondary force at E2; the profile does not record
the crank type), uneven-firing engines (odd-fire V6/V-twins, which add half
orders) and two-strokes (which fire every turn). Without a profile (not given,
or an EV) the orders stay E1 and E2, the ones tested before engines had a
profile, without claiming what E2 is. A PHEV has its combustion engine's
profile.

A new engine type, or a new order such as the half-order misfire (E0.5, one
cylinder's missing pulse per two turns), is a row in the table (with its role
name), not new code. Half orders get keys and codes of their own
(`engine_1_5x`, `E1.5`).

The profile's orders are what every stage uses:

- The analysis tests one hypothesis per order
  (`analysis/orders/physics.py::_order_hypotheses(profile)`): an inline-6 is
  tested at E1 and E3, not E2. An EV has none.
- The run metadata snapshots the profile (`RunCarMetadata.engine_profile`), so
  a run is analysed with the engine the car had when it was recorded.
- The diagnosis's `conditions.engine_profile` and `conditions.engine_orders`
  (code and roles per order) carry them to the report: the spectrum marks each
  order, with the firing order labelled "firing"; the conditions list the
  engine ("Inline-6, fires at E3"); the advice follows the role (firing: the
  mounts plus a misfire/ignition read-out; imbalance: the mounts); and the
  "never analysed" list drops the six's firing rhythm once the engine is known.
- Live, `build_order_bands()` draws a band per order (`engine_3x`), the firing
  one flagged `firing: true` for the spectrum legend.

### Engine order on a road-speed order (the hedge)

Without measured RPM the engine is placed in top gear. There an engine order
can sit within the order tolerance of a wheel or propshaft order. A six's E3
is 1.5 × top gear × P2: with an 8-speed's top gear of 0.64 it is 0.96 × P2
(and with a final drive near 3.1, E1 sits on T2 too). The two are the
same peaks, and nothing in the spectrum tells them apart. The diagnosis then:

- keeps the found order and names the other in `alternative` (`source`,
  `order_code`); the report's headline reads "the engine …, or the propshaft
  (P2)", the description says why, the owner gets the other cause's step as the
  fallback, and the workshop is told to confirm before replacing parts;
- is never Strong;
- names the road-speed order first when the shake is strongest away from the
  engine (rear wheels, the propshaft tunnel, the rear seats or the boot);
- marks the other source's check `not_testable` / `same_rhythm_as_candidate`.

A neutral coast-down decides it: the shake stopping names the engine (a
road-speed candidate is relabelled to the engine order), the shake going on
names the road-speed order (an engine candidate is relabelled to it). Measured
RPM through gear changes decides it too (see "Engine tone through a
near-1:1 gear").

#### Lower-gear comparison (design note, not built)

Status: **not built; pending an owner decision.** No guided lower-gear step
exists in the code. Building it would change the settled "assume top gear"
decision below, so it waits for the owner to decide.

A third way to split the pair needs no adapter and no neutral: drive a stretch
of the same speeds one gear lower. A road-speed order keeps its
frequency-to-speed ratio in every gear; an engine order's ratio grows by the
gear step. On an 8-speed whose 7th is 0.84 and 8th 0.67, the six's E3 moves
from 1.005 × P2 to 1.26 × P2 (×1.25), far outside the 8 % order tolerance;
an 8-speed's top two gears are typically 1.2–1.3 apart. So the tone either
stays on P2 (propshaft) or jumps by the gear step (engine).

Not built, because it does not fit cleanly today:

- The owner decision in `docs/user_journey_gaps.md` keeps estimated RPM in top
  gear for the whole drive, with no gear-shift analysis. The comparison is
  gear-shift analysis: the analysis must know which window was driven in which
  gear.
- That needs a new guided step (`GuidedPhaseName` gains, say, `lower_gear`,
  with its wizard text, contracts and EN/NL report wording) and the gear's
  ratio. A saved car carries the final drive and top gear only; the library
  rows' `gear_ratios` are not copied to the car or the run snapshot. Without
  the ratio the analysis could still look for the candidate's tone moving by a
  plausible step (1.1–1.6 ×), but a tone that merely fades in the lower gear
  (load changes the level) would read as "engine".
- The neutral coast-down already decides the same pair, with no ratio and no
  new step, and the guided drive already asks for it.

**The direct-drive trap.** Many automatics have a gear of exactly 1.000 (6th
on an 8-speed). In it the crank turns at propshaft speed, so E1 is P1 and E2
is P2 exactly, for every engine; a six's E3 is 1.5 × P2. A lower-gear step
must therefore never land in a direct-drive gear: there the engine's E1 (and
a four's E2) is the propshaft order again, and the step would "confirm" the
road order it was meant to rule out. With measured RPM the same gear is what
`_rides_on_another_order()` handles (see "Engine tone through a near-1:1
gear").

If the owner decides to build it: one guided step "hold 70–100 km/h one gear
below top (not a 1:1 gear)", phase-tagged like the coast-down; the analysis
compares the candidate's ratio in that window with the top-gear windows and
relabels as the coast-down does; the library's `gear_ratios` go into the car
snapshot so the step can name the gear and skip a 1.000 one.

Sources: J. B. Heywood, *Internal Combustion Engine Fundamentals*, 2nd ed.
(McGraw-Hill, 2018), ch. 2 (four-stroke cycle: one power stroke per cylinder
per two crank turns); C. F. Taylor, *The Internal-Combustion Engine in Theory
and Practice*, vol. 2, rev. ed. (MIT Press, 1985), ch. 8 "Engine balance"
(primary/secondary forces and couples by layout: inline-3 and 90° V6 primary
couples, inline-4 secondary force, flat-4 secondary couple, balanced inline-6,
flat-6, V12 and cross-plane V8); K. Yamamoto, *Rotary Engine* (Toyo Kogyo,
1981), ch. 2 (one power impulse per rotor per eccentric-shaft revolution);
summary: "Engine balance", Wikipedia.

## Uncertainty and tolerance bands

Order matching is not based on a single exact frequency bin. Post-run
diagnostics and the live spectrum use one tolerance model,
`order_peak_tolerance_hz()` in `dsp/order_bands.py`, so a peak drawn inside a
live band is a peak the report counts as an order match:

```text
tolerance_hz = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL * sqrt(path_compliance))
             = max(0.5 Hz, predicted_hz * 8% * sqrt(path_compliance))
```

`path_compliance` is 1.5 for wheel orders (tire, hub and bushings broaden the
peak, about ±9.8%) and 1.0 for driveshaft and engine orders (±8%).

Each order family needs only its own references: wheel orders need speed and
the tire size, driveshaft orders add the final drive, and engine orders come
from fresh measured OBD-II RPM or, without it, from the final drive and top gear
(an estimate that assumes top gear). A car reference has no default: a missing
one blanks only its own family live and makes that source "not testable" in the
diagnosis.

`build_order_bands()` emits the live band payloads for the families present,
with `tolerance = tolerance_hz / center_hz`, so the UI draws
`[center_hz * (1 - tolerance), center_hz * (1 + tolerance)]`, and with
`code`, the report's workshop label for the order (`workshop_order_code` in
`domain/finding.py`: T1, P1, E2, `P1/E1` for the merged band), which the
spectrum shows before the band's name:

- `wheel_1x`
- `wheel_2x`
- `driveshaft_1x` or merged `driveshaft_engine_1x`
- `engine_1x` when it does not overlap driveshaft
- `engine_2x`

`OrderReferenceSpec` still combines reference uncertainty in stages (wheel =
speed + tire diameter; driveshaft adds final drive; engine adds gear). That
combined uncertainty decides when the driveshaft and engine 1x bands collapse
into `driveshaft_engine_1x`; it no longer widens the bands.

## Post-stop hypothesis testing

Diagnostics does not search an open-ended order space. It evaluates a fixed
catalog of hypotheses from `orders/physics.py`:

- wheel 1x / 2x
- driveshaft 1x / 2x
- engine 1x / 2x

Each `OrderHypothesis` carries:

- a stable `key`
- the suspected `VibrationSource`
- the base order family (`wheel`, `driveshaft`, or `engine`)
- harmonic multiplier (`1` or `2`)
- `path_compliance`, which widens tolerance for softer transmission paths such
  as wheel/tire vibration traveling through suspension and bushings

For the compact summary compatibility path, `OrderAnalysisSession.analyze()`
coordinates the evidence flow:

1. Skip hypotheses that do not have enough reference data (`_should_test()`).
2. Use `match_samples_for_hypothesis()` to compare predicted order bands against
   the stored sample peaks. Orders placed from the speed are matched without
   each sensor's fixed tones (see "Fixed tones" below); an engine order placed
   from measured RPM keeps every peak.
3. Use `_compute_effective_match_rate()` to rescue or focus the evidence around
   the best speed band or dominant location. It starts from the match rate at
   the sensors that hear the order (see "Heard matches" below). Below the
   minimum match rate (`order_min_match_rate()`: 0.25, rising to 0.55 as the
   speed stddev falls from 1.0 to 0.5 km/h) the hypothesis produces no
   finding. A rescued rate scores the evidence, but the presence cap reads
   the run-wide heard rate, so an order that exists only through the rescue
   is at most Weak (see "Confidence levels" in `docs/metrics.md`).
4. Reject matches that do not follow the prediction. As speed changes, an
   order's peaks move one-for-one with its predicted frequency; a fixed
   resonance (body mode, engine idle) that the prediction sweeps past stays
   at one frequency, yet falls inside the tolerance band over a speed range.
   `frequency_tracking_slope()` (`domain/order_match.py`) takes the robust
   (Theil–Sen) slope of matched vs predicted Hz over the heard matches; below
   `MIN_ORDER_TRACKING_SLOPE` (0.5) the hypothesis produces no finding. On
   the simulator real orders score 0.8–1.3 and a 13 Hz body resonance crossed
   by T1 scores 0.0. It is only judged when the run's speed really changed
   (`trend_moves()`: the 2 s-median speed trend moves by at least 10 % and by
   more than twice the spread inside a 2 s bin). At a steady speed an order
   and a fixed tone look the same, and speed-reading noise would flatten the
   slope.
5. Score the surviving evidence with `score_order_finding()`. The location
   comes from the 10 km/h speed bin whose matches carry the most order
   amplitude in total (mean amplitude × matches), so a short stretch at
   speeds the rest of the drive did not reach cannot outvote the bins that
   hold most of the evidence. Location terms are source-aware: an engine/driveline order with no dominant corner is
   not penalised for it as its own evidence becomes established, unless it
   shares most of its peaks with a wheel order (see "Confidence levels" in
   `docs/metrics.md`).
6. Assemble a domain `Finding` with `assemble_order_finding()`. A wheel or
   driveline finding that rides on a measured engine order, or a measured
   engine finding that rides on a wheel or driveline order, produces no finding
   (see "Engine tone through a near-1:1 gear" below).
7. Split multi-location wheel findings when two corners are both strong.
8. Apply `suppress_engine_aliases()` before returning the final ranked list.
   An engine order that ranks below the best wheel order and is not clearly
   more confident than it is demoted as a likely alias. An engine order placed
   by RPM estimated from speed and gear that mostly lands on a wheel order's
   peaks has no frequency of its own: it is a fixed multiple of the wheel's
   (on a car whose top gear puts E1 on T2). When a wheel order is at least
   6 dB louder than it at the wheel's corner (median over the windows both
   matched there), it is that wheel's harmonic and is demoted whatever its
   confidence. An engine fault does not excite the wheel's own orders, and the
   wheel order it coincides with is as loud as it is. Confidence cannot settle
   this case, because the wheel order is penalised for spreading into the
   cabin and the engine zone is not. With measured RPM the engine order keeps
   its own frequency track and that rule does not apply.
   The same holds for an engine order with no dominant location, at any
   frequency: it is spared the spread penalty a wheel order takes, so it is
   compared with each wheel order that has a dominant corner by level. When
   that wheel order is at least 9 dB louder than it at the wheel's corner,
   the engine tone the whole car shares is demoted. The margin is wider than the 6 dB above because peak
   levels read on a speed sweep favour the slower-moving lower order by a few
   dB.

If the effective match rate stays below the current threshold, the hypothesis
does not produce a finding.

Ranking decides the diagnosed source; it does not decide which of that
source's orders the diagnosis names. `TestRun.diagnosis_order_finding` labels
the source's louder order, comparing its lower and higher order (1x and 2x,
or E1 and the firing order) by amplitude in the windows both matched (see
"Diagnosed order" in `docs/metrics.md`).

## Fixed tones

A body or seat resonance, a mirror buzz or an idle tone rings at one frequency
whatever the speed. The matcher takes the nearest peak in an order's
tolerance window, so while a road-speed order sweeps past such a tone it lands
on it: the order borrows the tone's level at every sensor that feels it, and a
crossing at a speed the drive lingers at (a city drive's 45 km/h) reads as an
order of its own. The tracking slope (step 4) catches a crossing only when
the crossing is most of the order's evidence.

`orders/fixed_tones.py:without_fixed_tones()` finds each sensor's fixed tones
on the moving spectra and drops the peaks within a tone's width (0.5 Hz or
2 %, whichever is wider) from that sensor's spectra before the speed-following
orders are matched:

- Speeds are grouped in bins one order tolerance wide (8 %, on a log scale),
  so lingering at one speed weighs no more than sweeping past it. A bin is
  judged when it holds at least 2 spectra.
- Only peaks at least 6 dB over their spectrum's floor
  (`heard_peak_over_floor`) count: road noise at the floor is no tone.
- A tone is held in a bin when it is in at least 75 % of the bin's spectra.
- It is fixed when the bins that hold it span at least 1.5× in speed (an
  order's frequency would have left its window several times over) and it is
  held in at least 80 % of the judged bins between the lowest and highest, so
  an order and its harmonic meeting one frequency at two speeds is not a
  tone.

The order-tracked reads skip only the fixed tones that **ring as a line**
(`ringing_tones()`): each run of the car's fixed tones within a tone's width
of each other is read as a line over its span in every spectrum of each
sensor, and judged as an order is (three standard errors, "Order-tracked
reads" below). A broad resonance the peak picker also holds fixed (the
wheel-hop hump) reads no level over the floor that follows its curve, so an
order crossing it is still read. A ringing tone reaches past its span by its
main lobe (two bins), or as far as a Hann window's sidelobes leak its power
within 10 dB of the floor beside it (`_leak_reach_hz()`: `k` bins away a
tone passes `1 / (pi k (k² − 1))` of its level; Harris 1978), up to 40 bins.
A 12 Hz pure-tone resonance 30 dB over the floor otherwise read 95 mg of the
wheel order at the trunk through its sidelobes. A window whose read reaches
a ringing tone keeps its ranked peak's match instead ("What the reads
decide" below).

An engine order placed from measured RPM is matched on every peak: the
engine's revs cycle through the same range on each gear while the speed
climbs, so a real engine order can look fixed against the speed. With RPM
estimated from speed the engine order moves with the speed and uses the
filtered peaks like the road orders.

## Order lines

The road rings the car's structural modes (wheel hop, a seat or subframe, the
body) as broad humps of noise, the same frequency at every speed. A hump wider
than an order's tolerance window puts a local-maximum peak somewhere in that
window in nearly every spectrum, clear of the floor, at every sensor. The
matcher takes the nearest one, so an order whose frequency sits on the hump
(a wheel order at motorway speed, a driveline or engine order in town) is
"matched" and heard in most windows, with a mean frequency error near 0, and
the tracking slope cannot tell: the matches are censored to the window around
the prediction, so they follow it. A fixed-tone filter needs a narrow tone
held over a wide speed range and misses both a broad hump and a drive that
stays at one speed.

An order is a line: a rotating part shakes at its turning frequency, so its
peak sits on the prediction times one constant factor (a slightly-off tyre
size or ratio) to within the speed reading's error. A hard pull moves it: the
drive torque makes the driven wheels slip a few percent faster than the road
(about 3 % at 3 m/s²), and a lagging speed reading lags the prediction the
same way. Peaks borrowed from a hump scatter across the window. `match_samples_for_hypothesis()` therefore tests
each sensor's clear matches (6 dB over their window's floor), split into
braking and other windows (a brake order is a line only while braking, and
firm braking smears every line; `_masked()`, `_off_the_line()`). Sensors with
fewer than 12 clear matches (`ORDER_LINE_MIN_POINTS`) are tested together, per
braking side: the line is at the same frequency at every sensor.

- Only some matches are judged, and they place the line: those whose
  tolerance window is at least 4 line widths
  (`ORDER_LINE_MIN_TOLERANCE_WIDTHS`; above about 8 Hz for a wheel order,
  10 Hz for the others). A
  spectrum over lost frames is judged like any other: the lost frames keep
  their time in it and its speed is read where its samples weigh in
  ([time_alignment.md](time_alignment.md)).
- `k` is the median of matched / predicted over the judged matches; a
  match is on the line when it is within `ORDER_LINE_WIDTH_REL` (1.5 %) of
  `k ×` its prediction, or half an FFT bin where that is wider (a tone
  sweeping through the spectrum, or noise beside it, moves its peak's
  frequency by a fraction of a bin). The matches
  under a pull (the acceleration phase) have their own `k` when 12 or more of
  them are judged (`_line_scale()`); the share below still counts the whole
  group. A peak's frequency is placed between bins (see `top_peaks` in
  [metrics.md](metrics.md)): read on the bin centre it would be up to half a
  bin off, 3.7 % of a wheel order at 10 Hz, and a tone between two bins would
  jump between them, off a line placed on either.
- The line, once placed, holds every clear match, judged or not: a window
  too narrow to place the line in still shows a peak off it, while an
  order's own peak is on its line in any window. Below about 8 Hz (a wheel
  order at town speeds) the rough road's bumps leave peaks that the
  overlapping spectra hold at one frequency for a second or two while the
  prediction sweeps past; they are off the line.
- With under half of the group's clear matches on the line
  (`ORDER_LINE_MIN_SHARE`) the group has no line and every match is off it.
  Otherwise the matches off the line are off it.
- A group with fewer than 12 judged matches is not judged.

A window whose clear match is off the line holds broadband content louder
than the order could be seen through: like a window whose order lies under
the analysis floor, it is not a chance to hear the order, and it leaves the
match and the possible counts before the heard sensors are chosen ("Heard
matches"). Dropping only the match would count the window against the order;
keeping it as an unheard match would let an order heard nowhere fall back to
the hump's level as its evidence.

On the benchmark's drives with a road-excited mode at an order, a real order's
groups sit at a median 85 % on the line (10th percentile about 60 %) and the
hump's at 24 % (95th percentile about 40 %). The groups the test drops among
real faults are noise ones: brake judder's matches outside braking, and firm
stops' braking windows on a wheel imbalance. Within a real order's group the
off-line windows are mostly a hump the order passes at other speeds. The line
width and share are set from simulated drives; real drives with a known mode
near an order are needed to confirm them.

## Order-tracked reads

A window keeps its 8 strongest peaks (`top_peaks`). On a real road the wheel
hop rings every wheel sensor as a broad hump around 12 Hz, 30-37 dB over the
band's floor (see `unexplained_vibration` in [metrics.md](metrics.md)), and
fills those 8 places with its own local maxima. A wheel or driveline order is
then ranked out of the window at a sensor that does feel it, or matched on a
hump peak at one that does not, and the median of the matched peaks at each
sensor tells the corners apart no better than the hump does. So each
order's level at each sensor is read at its own line instead, in every
window, whatever louder content the window holds elsewhere
(`analysis/orders/tracking.py`, `dsp/window_spectrum.py`; the significance
rule itself is `dsp/line_significance.py`, which the live view shares).

**Where the spectra come from.** The post-stop raw replay
([analysis_pipeline.md](analysis_pipeline.md)) keeps each window's combined
spectrum (`sqrt(mean(axis_amp²))`, 5-200 Hz, the one its peaks come from) in
memory beside its peaks (`SensorFrame.spectrum`, a `WindowSpectrum`). It is
never persisted. A run with no raw capture, or a window the replay could not
rebuild, has no spectrum and no reads.

**One read** (`WindowSpectrum.line_read()`), for each window the order could
be looked for in, the masked ones included (a window whose match is off the
line holds the order's line all the same; what hides its peak is subtracted
as floor):

- The line is at `k ×` the prediction, `k` placed by the clear matches as in
  "Order lines" above (`_tracked_line_scale()`, the median over the judged
  clear matches when 12 or more are judged, else 1).
- The band is the Hann window's main lobe about it, two bins (0.78 Hz)
  either side, which holds 99.95 % of a steady tone's power whatever its
  offset from a bin centre, widened by the band the line swept through in
  the window: `f·|dv/dt|·T / (2v)` either side (`line_half_width_hz()`),
  with `T` the window's length (2.56 s) and `dv/dt` from the same sensor's
  neighbouring samples up to 2 s apart (`speed_rates_kmh_per_s()`). Braking
  from 100 km/h at 5 m/s² sweeps a 45 Hz order ±10.4 Hz within one window:
  read at its centre it shows a quarter of its level, at 2 m/s² 70 %; read
  over its sweep, all of it.
- The floor is read in the 3 bins (1.2 Hz) either side, just past the band.
  Under the band it follows a parabola `a + c·x²` fitted through them
  (paired by their distance `x` from the centre), so the curve of a broad
  resonance the line sits on (the wheel-hop hump) is floor, not level: a body
  mode 6 Hz wide read over a flat floor would add 8 % of the floor's power
  to the order's read. `flanks` is the mean power per bin of those 6 bins. At
  the ends of the spectrum only the flank that exists is used, flat; with
  neither, or with the band outside the spectrum, there is no read. The
  stored spectra start at 5.08 Hz, so a line under about 5.9 Hz (a wheel
  order at about 40 km/h) has no read.
- The read is the band's power above that floor, per bin of a peak band
  (`excess`, g²): a steady tone's is its peak level squared over the floor, a
  swept one's adds up the same way. In a window the order is absent from, it
  is below zero about as often as above.
- A window whose read (band and flanks, `line_reach_hz()`) reaches one of
  its sensor's ringing tones or that tone's leak (see "Fixed tones" above)
  is not read: a body mode's level is no part of the order's. An engine
  order placed from measured RPM has no fixed tones, as in matching.
- Each read comes with two **control reads** the same width, twice its reach
  either side of the line (where neither tone nor order is): they place the
  floor's scatter the reads are judged by (below).
- The line's place (`_tracked_line_scale()`) is judged from the windows whose
  line held still within a peak's width: on a sweep a window's peak lands
  anywhere on the stretch its line swept.
- An order's reads and control reads over the whole drive are planned as
  arrays and taken together (`line_reads()`): the windows' bands of one width
  are stacked and read at once (gathered straight from the replay's spectra
  where it keeps them as rows of one array), each read bit for bit the one
  `line_read()` takes on its own, then filed by cell in window order.

**Whether a sensor hears the order** (`TrackedCells`). The reads are grouped
per sensor, 10 km/h speed bin and driving phase (the rest of the drive,
braking, and the guided test's coast-down in neutral), and each is divided by
its cell's median floor. Where the order is absent they scatter about 0 by the
floor's own randomness, so a sensor hears the order only where the **median**
of all its reads stands three standard errors over 0
(`_SENSOR_STANDARD_ERRORS`). The median, not the mean: a pothole's few wild
windows shift a mean far more than an order does.

- The standard error is `1.2533 · s / sqrt(n_ind)`: the median of normal reads
  scatters `sqrt(pi/2)` times more than their mean (Rousseeuw & Croux, JASA
  88(424), 1993).
- `s`, one read's scatter, is `1.4826 ×` the median distance of the
  **control reads** from their own cell's median (cells of 5 control reads or
  more; else from the median of all the sensor's control reads, when there
  are 5 or more), scaled to a standard deviation. A line's power beats with
  the floor under it, so the order's own reads scatter more the stronger it
  is; the controls scatter as the floor alone does. Without control reads
  (the line runs along the spectrum's lower edge) it is the reads' own
  distance from their cell's median, over the cells of 5 reads or more.
- `n_ind` counts the windows as independent reads by how much they overlap:
  two Hann windows `hop` apart read the same noise with a power correlation
  of `rho(hop)²`, `rho` their overlap correlation (16.7 % at half a window;
  Harris, *Proc. IEEE* 66(1), 1978), so `n` windows 0.25 s apart in a 2.56 s
  window weigh as `n / (1 + 2 Σ rho(k·hop)²)`, about `n / 5`, independent
  ones (Welch, *IEEE Trans. Audio Electroacoust.* 15(2), 1967).
- Three standard errors (one-sided 0.13 %): one drive asks this of about ten
  orders at each of about five sensors, so about one drive in fifteen has one
  absent sensor hear an order.
- A wheel order (`TrackedCells.braking_alone`: brake judder shakes at the
  wheel's order, only while braking) is also heard where its braking windows
  alone pass the same test, judged by their own scatter, and one of its
  braking cells stands clear (below). An engine or driveline order is not:
  there it was a gear's tone that happens to sit on a stop's speeds.

A driving phase **hears** the order at a sensor where the median of that
phase's reads stands two standard errors over 0 (`_PHASE_STANDARD_ERRORS`,
`heard_phases()`). A **cell hears the order** where its sensor does, its
sensor hears it in the cell's driving phase, and the cell's median read
stands `heard_peak_over_floor` (6 dB: three times the floor's power) over its
median floor, as a ranked peak must stand over its window's floor
(`heard_cells()`). A cell of a few windows stands clear by chance now and
then: at physical amplitudes, one 40–50 km/h driving cell of a front wheel
did on a brake-judder drive, and it made the judder look heard while driving
(below) until the phase had to hear it too.

**The level at each sensor** (`TrackedCells.sensor_levels()`), over the
cells at the speed bins of the heard matches ("Heard matches"; every cell when
there are none), the coast-down test left out:

- Each cell's median read **while the order is there**
  (`_Cell.present()`): its reads are split into blocks two windows long
  (5.12 s); a block of 5 reads or more whose median stands 6 dB clear is a
  stretch the order is there. The read-weighted mean of those blocks'
  medians, or the cell's median where no block is clear. A misfire there in
  half the drive reads its level while there, not half of it (the median over
  the whole cell would put it under the floor's).
- The level is the root of the read-weighted mean of those cells' reads
  where the sensor's reads over them stand three standard errors out, else 0
  (`level_g`). `read_g` keeps the root either way: it places the order at a
  sensor whose matches hear it but whose reads do not stand out (location
  scoring, below).
- A sensor with fewer than 2 independent reads over the whole drive
  (`_MIN_INDEPENDENT_READS`, a sensor that dropped out) has no level at all:
  a level of 0 there would place the order at another sensor.
- The floor is `sqrt(median flanks)`.

A finding put down to the brakes ("Brake judder" below) is read over the
braking cells alone (`braking_sensor_levels`): with the windows between
stops, a judder there in a quarter of the windows would read at half its
level.

**Where the levels are.** `Finding.sensor_levels` (domain,
`SensorOrderLevel`: `location`, `level_g`, `floor_g`, `windows`, strongest
first) for every order finding; in the persisted analysis, each order
finding's `sensor_levels[]` (`findings[]`, `top_causes[]`; g); and for the
diagnosed order, `diagnosis.location_amplitudes[].amplitude_mg` (the level
as the peak of a tone, about 3.7x the levels in mg on this page) and
`db_above_floor` (see "Diagnosis amplitude (mg)" in
[metrics.md](metrics.md)); every top cause's level at the sensor nearest the
occupants ranks the top causes and fills `diagnosis.felt` ("What the driver
feels" in [metrics.md](metrics.md)). The diagnosis falls back to the median of the
matched peaks when any sensor with matched peaks has no reads (its spectra
were not rebuilt), or when no sensor's level stands out (a short stretch at
the heard speeds on a rough road).

**What the reads decide** (`matching._tracked()`). Where the run kept its
spectra, each window's match comes from its read, and every metric under
"Heard matches" reads those matches as before:

- A window in a cell that hears the order **matches** it, clear and heard, at
  the cell's level on a ranked peak's scale, whether or not the order ranked
  among the window's 8 peaks. A peak's band holds the floor under it as well
  as the order, so the match's amplitude is the level and the window's floor
  added in power (`peak_scale_g()` in `dsp/window_spectrum.py`): the
  finding's strength (dB over its windows' floors) and its 8 dB negligible
  edge ("Confidence levels" in [metrics.md](metrics.md)) are on that scale.
  An order whose level is 2.3 times the floor stands 8 dB over it as a peak
  and 7.2 dB as its level alone; read as its level alone, an inline-4's E2 at
  20 g (physical limit drives, idealised floor) sat about 0.7 dB under its
  peaks, just over the edge, and was found on 7 of 20 runs (20 on its peak's
  scale). Its frequency is its ranked peak's where one sits within the
  line's tolerance and sweep, else the line's. An order under the wheel-hop hump is
  matched where its own line stands out, not where the hump's peaks let it
  rank.
- A window in a cell that does not hear it keeps its ranked peak's match only
  where some sensor hears the order in that driving phase (`heard_phases`);
  elsewhere it **does not match**. A hump peak near the wheel order in town
  matches a healthy car's wheel order at every corner in about a quarter of
  the windows; it no longer does at a sensor and phase the order's line is
  absent from.
- A window whose line could not be read keeps its ranked peak's match: on a
  ringing tone (the tone hides the order from the read, not from the peaks),
  and at the spectrum's lower edge only at a sensor that hears the order in
  some phase (a floor-level peak at the lowest bins says nothing elsewhere).
  A window off the order's line (`_masked`) keeps no match.
- A window in the guided coast-down is judged by its ranked peak alone, as
  the coast test judges it (`diagnosis._speed_dependence`): a cell there
  spans the shift into neutral, where an engine order still sounds for a
  window or two. On a loaded machine the live e2e drive's first coast-down
  windows at 90-100 km/h read an engine E2 clear, and the coast test no
  longer saw it vanish.

Three rules follow the reads into the existing scoring:

- **Location** (`scoring._at_tracked_levels()`): the matched points are placed
  by their sensor's tracked level (`level_g`) instead of their peaks'
  amplitudes, where some sensor's level stands out and every matched sensor
  has a level: the peaks are the order plus the hump under it.
  - A sensor whose matches hear the order (`heard_locations`, "Heard
    matches") but whose reads do not stand out is placed by its read
    (`read_g`): a front-left imbalance on the wheel-hop hump, 220 mg of floor
    beside its line, clear of its windows' floors but not of its reads'
    scatter.
  - A sensor that does not hear the order is **quiet**: its read is the
    floor's scatter, which under the hump at a wheel is louder than a faint
    order heard at the trunk. It ranks below every sensor that hears the
    order, whether or not it matched in that speed bin
    (`score_locations_in_bin(quiet_locations=...)`), so a sensor that hears
    the order alone is located there, clearly (dominance
    `QUIET_SECOND_DOMINANCE`, 10, over a quiet second). The sensors an
    order could be spread over (the weak-separation threshold and the
    localisation's location count) are those it matched in the bin, quiet
    or not, as before, and at least the two compared: a quiet sensor with
    no match there is only the quieter second.
  - A wheel order is put at a wheel only where a wheel sensor places it.
    Where none does it is located where it is heard and scored as one with
    no wheel sensor fitted (`no_wheel_sensors`: localisation at most 0.30,
    weakly separated, `apply_localization_override` does not pin it).
- **Heard match rate** (`OrderMatchAccumulator.heard_match_rate`): where the
  order is heard only in its braking cells, over the heard sensors' braking
  windows (`_phase_heard_rate()`) where that rate is the higher one; the
  windows between stops have no judder to match. A wheel order near the floor
  that stands clear in one braking cell alone still matches between the
  stops: its braking rate (0.08 at physical amplitudes on a firm-stops drive)
  would cap a finding heard in 0.79 of its windows at Weak.
- **Match-rate rescue** (`_compute_effective_match_rate()`): a phase label
  whose driving phase has cells that hear the order rescues the rate where
  its own matches reach the minimum rate, with the same minimum windows and
  matches as the speed-band rescue.

**Results.** The accuracy benchmark (seeds 1-6, CI rule: seed 1 passes and 4
of seeds 2-6), main before the reads decided the matches, the first design
(tracked), and the design above (quiet sensors, the peak scale):

| | main | tracked | now |
|---|---|---|---|
| CI configuration (cases on their `IdealisedFloor` stay there) | 222/224 | 222/224 | 222/224 |
| healthy runs there given a fault / a weak guess (of 318) | 2 / 0 | 1 / 0 | 1 / 0 |
| fault runs whose report text and amplitude table name different locations | 15 of 968 (8 on seed 1) | 3 of 964 (0) | 3 of 964 (0) |
| every case on the ISO 8608 road | 158/224 | 177/224 | 177/224 |
| healthy runs there given a fault / a weak guess (of 318) | 22 / 35 | 3 / 3 | 3 / 3 |
| fault runs there whose report text and amplitude table disagree | 24 of 820 (10 on seed 1) | 12 of 808 (0) | 12 of 809 (0) |
| physical fault amplitudes (`tools/dev/physical_fault_tally.py`), cases where main has them | 117/224 | 119/224 | not rerun |
| physical fault amplitudes, the 13 cases below on the road | 100/224 | 112/224 | 126/224 |

The physical-amplitude limit drives (`physical_fault_tally.py limits`,
steady speeds, 1200 runs): main finds the fault on 796 and names a wrong
source or corner on 37 as a fault and 35 as a weak guess; the tracked design
finds it on 765 and names a wrong one on 18 and 0, this one on 834 and 8 and
0. A front-left imbalance at a steady 50 km/h on the road (under the read
limit, below) was a wheel fault at all four wheels or the rear-left at every
size on main; it is no fault now.

The quiet sensors and the peak scale gain, at physical amplitudes, the engine
cases on the road (9 to 19 of 22: the engine sweeps, the inline-3 and
inline-4 firing sweeps, the guided engine tests, the engine coast-down) and
the faint-engine front-wheels sweep on the idealised floor (both cars), a
driveline and a wheel-and-propshaft case, and lose none. In the limit drives
an inline-4's E2 at 20 g on the idealised floor is found on 20 of 20 runs
(tracked 7, main 19), and at 130 km/h in top gear, where its E1 shares a line
with T2 heard at the trunk alone, no run names a wheel fault (tracked 12 of
25, main 3): the tracked design read the wheel sensors' floor scatter as the
order (two unheard wheels at 12-19 mg under a 30 mg floor, louder than the
trunk's 6 mg) and scored the lone heard trunk at dominance 1. The 8 wrong
sources left are an inline-4's E2 at 50 km/h, matched as T2 (a fault at the
trunk or the rear-right wheel).

13 cases moved off the idealised floor (they pass on the road for every
car): the healthy city, residual-imbalance, seat-mode, real-traffic,
flat-spot and brake-step drives, the pothole loop, the front-left wheel in
traffic, the guided brake stops, the rear-left oval, the very lossy
rear-right sensor, the launch flare and the guided engine test (see
"Benchmark on the realistic road" in `docs/simulator_realism.md`).

**Limits.**

- A line within its read's reach of a ringing tone's leak is not read there.
- Two orders whose lines share a band (an engine order on a wheel harmonic in
  one gear) read the same power.
- An order far under the floor beside its line is not heard, whatever the
  drive's length allows: a mild front-left imbalance (113 mg at the knuckle)
  under the wheel-hop hump (about 1 g there at motorway speed) reads a median
  of −0.005 of the floor at its knuckle (seed 1), where three standard errors
  over a sweep's 76 reads are about half the floor. These cases stay on the
  idealised floor (`MISSED_UNDER_WHEEL_HOP`).
- A sensor whose reads pass the test still carries their scatter: on the
  wheel-hop hump a second corner's level reads up to about a third high, so
  two faulty corners whose levels differ by under 2x can read "about as
  strong".
- The levels are for the speeds the order was heard at: an order heard
  nowhere is read over the whole drive.
- Which sensors hear an order is decided by their matches
  (`heard_locations`), not by their reads: a sensor whose matches do not
  reach half the clearest sensor's share is quiet whatever its read, and one
  that does is placed by its read even where the read is the hump's scatter.
- A line under about 5.9 Hz has no read (the spectra start at 5.08 Hz): a
  wheel order at town speeds keeps its ranked peaks there only at a sensor
  that hears it elsewhere.

**Cost.** On x86, the 30-minute benchmark drive (4 sensors, the drive of
`make benchmark-post-analysis-30min`): post-analysis 14.4 s on main and
17.2 s with the tracked verdicts, without memory tracing (each window is
read three times, at the line and at its two controls, about 6 µs a read);
peak traced memory 118 MB either way, the spectra kept (about 2 KB per
window). The live view keeps no spectra; it reads each sensor's latest one
once a second (see "Live vs post-stop reuse").

## Engine tone through a near-1:1 gear

With measured RPM, a gear near 1:1 puts E1/E2 on P1/P2 (and some gears put an
engine order on T2). While that gear is engaged the road-speed order's window
holds the engine's tone, so a pull through the gears gives the engine verdict
plus P1/P2 rows the drive never carried. The other way round, a propshaft
fault on a pull through a six-cylinder 8-speed's gears puts its P2 tone in
E3's window in 8th only. `pipeline.py::_rides_on_another_order()` drops a wheel or driveline
finding that rides on the measured engine orders, and a measured engine
finding that rides on the wheel and driveline orders. An order rides on others
when both hold:

- at least half (`wheel_alias_shared_peak_fraction`) of its matches have one of
  their peaks within 8 % of its own predicted frequency, and
- under half of their matches are in its window: they went on through gears
  where this order did not follow.

A real fault keeps its own peaks in every gear, so the first condition fails.
With estimated RPM the engine order cannot be told from the road order (see
"Engine order on a road-speed order (the hedge)" above, and "Engine alias" in
`docs/analysis_pipeline.md`).

## Heard matches

The matcher (`match_samples_for_hypothesis()`) takes the nearest peak in the
tolerance band whatever its level, so it also lands on floor-level road noise
at every sensor and in the windows an order is absent. It classifies each match
once, and every metric below reads that classification
(`OrderMatchObservation.heard`) instead of applying its own floor filter.

A match is **heard** when both hold:

- its peak is at least 6 dB (2×, `heard_peak_over_floor`) over the floor of
  the window it was read from (`strength_floor_amp_g`, the same spectrum), and
- it is at a sensor that hears the order: one where the order's peak clears
  that bar at least half as often (`heard_location_min_share`) as at the
  sensor where it clears it most often (`OrderMatchAccumulator.heard_locations`).
  A vibration fades with distance from its source, so an engine tone only the
  front sensors hear is not diluted by the rear ones.

An order heard nowhere keeps all its matches as evidence (`evidence`,
`heard_match_rate`), so a faint order is judged on what there is rather than
dropped. The persisted `matched_points[].heard` carries the flag to the
diagnosis.

| Consumer | Reads |
|----------|-------|
| Match rate the effective rate starts from (`pipeline.py`) | matches / possible windows at the heard sensors (`heard_match_rate`) |
| Score strength, frequency error, tracking correlation, sample count (`scoring.py`, `compute_amplitude_and_error_stats()`) | heard matches only (`evidence`) |
| Corroboration count for the zone credit and bonus (`OrderMatchAccumulator.corroboration`) | the heard sensors, each but the clearest counted in full only from 0.1 over the heard bar (a share of 0.6) |
| Zone evidence rate (`_zone_credit()`) | effective match rate × the share of matches at the heard sensors that are heard (`heard_share`) |
| Tracking slope (step 4) | heard matches |
| `presence_ratio`, per-location `presence` (`analysis/diagnosis.py`) | heard matches over the moving samples |
| Coast-down `speed_dependence`: the order's main location and the matches counted during and outside the coast-down | heard matches |
| Matched speed range (`speed_min_kmh` / `speed_max_kmh`) | heard matches (all, when none is heard) |
| Enough matches and matched time for a finding (`OrderMatchAccumulator.is_eligible()`) | the evidence: heard matches (all, when none is heard) |
| Level of one order over another (`Finding.level_over_db`: diagnosed order, engine alias suppression) | windows both matched where at least one of the two is heard |

Why 6 dB over the window's floor: on the full benchmark matrix (40 cases, both
cars, seeds 1–6, and the healthy cases on seeds 7–26) this one rule gives the
same verdicts as the per-metric filters it replaced, which were 6 dB over the
window floor for the score and 8 dB over the run's median floor for presence and
the coast-down. Raising the shared bar to 8 dB over the window floor turned the
every-mount healthy sweep into a Moderate wheel fault on two seeds. The window
floor is measured on the same spectrum as the peak, so it follows road and
speed changes the run median does not. The 8 dB negligible cap in
`docs/metrics.md` is a different role: it caps a finding whose heard level is
noise-like, not which matches count.

## Brake judder

After a wheel/tire hypothesis becomes a finding, `pipeline.py` asks
`brake_attribution.only_while_braking()` whether the order was there only while
the car braked (`BRAKING` phase; see "Braking" in `docs/analysis_pipeline.md`).
The matcher records every possible window with its sensor
(`OrderMatchAccumulator.possible_samples`), so the check compares, at the heard
sensors, the share of braking windows that heard the order with the share of
non-braking windows at the same speeds that heard it within 12 dB of its
braking level. Windows within half an analysis window of a braking sample are
left out, because their spectrum spans part of the stop. Only the stops that
show the order count: a stop where it is in under a quarter of the windows
within 12 dB of the loudest stop's level is left out, as an EV or PHEV may
have slowed on regeneration alone without touching the discs. Road noise near
the predicted frequency lands a floor-level peak in about a third of the
windows, so the level matters, not just the count. When the order
is in at least half of the braking windows of those stops and at most 10 % of
the others (at least 8 windows on each side), `as_brake_finding()` relabels the finding to the
`brakes` source and keeps only its braking matched points. An unbalanced wheel
stays a wheel/tire finding.

## Live vs post-stop reuse

The same reference math serves both runtime and diagnostics:

- live telemetry calls `vehicle_orders_hz()` and `build_order_bands()` so the
  UI can annotate the current spectrum without duplicating the formulas
- the post-stop summary analysis asks whether the run's sample peaks keep
  recurring in the predicted wheel/driveshaft/engine bands, and reads each
  order's level at its line inside the same band ("Order-tracked reads";
  the line's factor `k` comes from matches within the band's tolerance)
- the live view reads each sensor's latest spectrum at every band's line once
  a second and asks the report's question of the last 10 s of reads
  (`live/order_hearing.py`): the middle of the reads stands three standard
  errors out of the control reads' scatter, and the line stands 6 dB clear of
  the floor beside it in the current speed bin, by the same functions and
  thresholds (`dsp/line_significance.py`, which `tracking.py` imports). It
  places the line at the prediction (`k = 1`), has no ringing-tone exclusion
  and shows an order once two verdicts in a row hear it; each band's
  `heard_at` names the sensors (see "The live view and the report" in
  [metrics.md](metrics.md)). The report still decides.

The saved per-sample peak/floor inputs consumed by order matching come from the
same canonical live-processing FFT/strength pipeline
(`apps/server/vibesensor/live/compute.py`,
`apps/server/vibesensor/dsp/fft_analysis.py`, and
`apps/server/vibesensor/dsp/vibration_strength.py`), so order analysis does not
maintain a second independent DSP stack.

That shared ownership is why `dsp/order_bands.py` exists outside
`analysis/`.

## File map

| File | Responsibility |
|------|----------------|
| `apps/server/vibesensor/domain/order_reference.py` | Vehicle-physics reference model and frequency derivation helpers. |
| `apps/server/vibesensor/domain/engine_profile.py` | Engine profile and the rules table of the engine orders it excites. |
| `apps/server/vibesensor/dsp/order_bands.py` | Shared order-match tolerance and live band-payload helpers. |
| `apps/server/vibesensor/analysis/orders/physics.py` | Fixed hypothesis catalog and per-sample predicted-Hz helpers. |
| `apps/server/vibesensor/analysis/orders/matching.py` | Match predicted order bands against stored sample peaks, read each window at the order's line, and classify each window's match from its read (or its peak) as heard. |
| `apps/server/vibesensor/analysis/orders/tracking.py` | Order-tracked reads: speed rates, which sensors, cells and phases hear an order, and per-sensor order levels. |
| `apps/server/vibesensor/dsp/window_spectrum.py` | A window's combined spectrum, one read at an order's line, and the line's swept width. |
| `apps/server/vibesensor/dsp/line_significance.py` | Whether an order's line reads stand out of the floor: the rule the report and the live view share. |
| `apps/server/vibesensor/live/order_hearing.py` | Which orders the live spectra hear, by that rule over the last 10 s (`heard_at` on each live band). |
| `apps/server/vibesensor/analysis/orders/scoring.py` | Convert matched evidence into confidence and ranking score. |
| `apps/server/vibesensor/analysis/orders/finding_builder.py` | Project scored evidence into domain `Finding` objects. |
| `apps/server/vibesensor/analysis/orders/pipeline.py` | Coordinate the full order-analysis pass. |
| `apps/server/vibesensor/analysis/orders/fixed_tones.py` | Drop each sensor's fixed-frequency tones before speed-following orders are matched; find the ones that ring as a line, and how far they leak, for the order-tracked reads. |
| `apps/server/vibesensor/analysis/orders/brake_attribution.py` | Put a wheel order heard only while braking down to the brakes (brake judder). |
