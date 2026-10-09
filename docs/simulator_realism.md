# Simulator realism

The simulator (`apps/server/vibesensor/simulator/`) stands in for real drives
until real recordings exist. To be an honest stand-in it must not share the
analysis's assumptions: every realism parameter below comes from a cited
source (datasheet, standard, textbook or paper) with a one-line reason, never
from the analysis code and never tuned to make a test pass. Simulator physics
lives in simulator modules; it shares only pure unit conversions and hardware
constants (the ADXL345 scale) with the server.

Each realism area has its own section. Numbers marked *assumption* have no
direct measurement behind them yet; real-drive recordings should calibrate them.

## Road and sensor front end

`SimClient.road` (a `RoadSurface`) switches a simulated sensor from the
idealised one (white Gaussian noise, random bumps, an int16-wide output) to
this model. The road's vibration replaces the profile's white noise, floor
noise and random bumps; the profile's tones and a scenario's explicit pulses
stay, and so do the road resonances (`RoadResonance`), now scaled with the
road's class.

### Road profile (`simulator/road_surface.py`)

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Displacement PSD | `Gd(n) = Gd(n0) (n/n0)^-2`, `n0 = 0.1` cycles/m | ISO 8608:2016, the standard road roughness model (waviness 2) |
| Class A / B / C / D `Gd(n0)` | 16 / 64 / 256 / 1024 × 10⁻⁶ m³ | ISO 8608 class geometric means; each class doubles the amplitude |
| Sections | 200-800 m each, class drawn A 60 %, B 30 %, C 10 % | *assumption*: road surveys rate motorways very good to good and other paved roads very good to poor (Dodds & Robson, *J. Sound Vib.* 31(2), 1973), i.e. mostly A-B with some C |
| Expansion joints | 1.5 per km, 3-8 mm deep, 0.05-0.15 m long | *assumption*: bridge joints come about every kilometre on motorways; a joint gap plus its edge steps is a few mm |
| Potholes, manholes, patches | per km: A 0, B 0.3, C 2, D 5; 1-4 cm deep, 0.2-0.6 m long | *assumption*: none on a smooth road, several per km on a poor one |

Impacts sit at fixed positions along the road. Every sensor of a drive shares
one road; the rear axle meets each position one wheelbase (2.7 m) after the
front, so a joint jolts the front corners `wheelbase / speed` before the rear.
Left and right wheels get independent random roughness (a simplification: real
left and right tracks are coherent only at long wavelengths).

### Quarter car (`simulator/road_vibration.py`)

At speed `v` the road's vertical velocity under a wheel is white with one-sided
PSD `4 π² n0² Gd(n0) v`, fed sample by sample (zero-order hold).

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Sprung mass per corner | 330 kg | a 1.5 t mid-size car |
| Unsprung mass | 40 kg | unsprung/sprung ratio 0.1-0.15 (Gillespie, *Fundamentals of Vehicle Dynamics*, 1992, ch. 5) |
| Tyre stiffness | 200 kN/m | passenger-car radial tyres 150-250 kN/m (Wong, *Theory of Ground Vehicles*, 4th ed., ch. 1) |
| Suspension stiffness | 20.7 kN/m | a 1.2 Hz body (ride) mode, inside the 1-1.5 Hz passenger-car range (Gillespie ch. 5) |
| Damper | 1570 N·s/m | 0.3 of critical on the body mode, 0.26 on wheel hop (Gillespie ch. 5: 0.2-0.4) |
| Wheel hop | 11.8 Hz (from the above) | Gillespie ch. 5: 10-15 Hz |
| Tyre contact length | 0.15 m; first-order low-pass at `0.44 v / length` | the contact patch averages road wavelengths shorter than itself (tyre enveloping; Pacejka, *Tire and Vehicle Dynamics*, 3rd ed., ch. 10); 0.44 / length is the moving average's -3 dB point |

Resulting levels on a class A road at 100 km/h (vertical): knuckle about 0.5 g
rms, a 12 Hz wheel-hop hump, about 15 dB down by 50 Hz and 35 dB down by
200 Hz; body about 40 mg rms, mostly at 1-2 Hz. Each rougher class doubles
them; they grow with speed (the input as `√v`, plus what the contact patch
lets through).

### Where the sensor sits

`mount_for_name()` reads the mount from the sensor's name or location code.

| Mount | Locations | Signal | Reason |
|-------|-----------|--------|--------|
| Knuckle | the four wheel locations | unsprung-mass acceleration | the mounting guide asks for the knuckle or strut base (`docs/user_journeys.md` §3.2) |
| Body | seats, trunk, tunnel, subframe, anything unnamed | sprung-mass acceleration | seat rails, trunk floor and tunnel are body structure; a subframe is modelled as body (a simplification) |
| Powertrain | engine bay, transmission/gearbox | body acceleration through a 10 Hz, 10 %-damped mount | engine/gearbox bounce on rubber mounts at 6-12 Hz with 5-15 % damping (Yu, Naganathan & Dukkipati, *Mech. Mach. Theory* 36, 2001) |

Axes: fore-aft and lateral carry 0.5 and 0.35 of the vertical road input, on
their own random streams (*assumption*, in line with the horizontal/vertical
ratios Paddan & Griffin, *J. Sound Vib.* 253(1), 2002, measured at car seats).
Front corners, engine, gearbox and front subframe meet the road at the front
axle; seats and tunnel mid-car; rear corners and trunk at the rear axle.

### ADXL345 front end (`simulator/adxl345_front_end.py`)

As `firmware/esp/lib/adxl345` configures it: full resolution, ±16 g, output
data rate = sample rate (800 Hz).

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Scale | 3.9 mg/LSB (1/256 g) | ADXL345 datasheet Rev. G, Table 1 (full resolution) |
| Range | -4096..4095 counts (±16 g), clips | 13-bit full-resolution output |
| Noise | 0.75 / 0.75 / 1.1 LSB rms (x/y/z) at 100 Hz ODR, × √(bandwidth / 50 Hz): 2.1 / 2.1 / 3.1 LSB at 800 Hz | datasheet Table 1; noise density times the √bandwidth |
| 0 g offset | per sensor, normal with the datasheet's ±150 mg (x/y) and ±250 mg (z) at 3 σ | datasheet Table 1 |
| Gravity | none here: the 0 Hz reading comes from the body attitude model | see "Body attitude" below |
| Bandwidth | first-order roll-off, -3 dB at ODR/2 | datasheet Table 7 gives bandwidth = ODR/2 and no order; first order is the gentlest reading. No analog anti-alias filter: content above 400 Hz folds back into the band |
| Rounding | to the nearest count | |

A tone above 400 Hz (gear whine, high engine orders) is sampled at the sample
instants, so it folds to `|f - k · 800|` exactly as on the real sensor, scaled
by the front end's roll-off at its true frequency (see
`docs/anti_alias_characterization.md`). The road model itself carries almost
nothing above 400 Hz (the contact patch removes it); texture-excited tyre belt
vibration around 1 kHz is not modelled yet (no source gives its level at a
knuckle), so real drives may show a higher in-band floor from folded
broadband content than the simulator does.

### Benchmark on the realistic road

Every benchmark case drives on `generated_road(seed)`, as every real car has a
road under it, unless it names why it stays on the idealised floor
(`Case.idealised_floor`, an `IdealisedFloor`): 96 of the 122 cases CI runs
(174 of the 224 case and car runs) drive on the road and pass the CI seed and
the matrix rule there. The other 26 are expectations the analysis does not
meet on the road yet (seeds 1-6 with every case on the road, 1344 runs;
failing runs of each group's, main's in brackets):

- `MISSED_UNDER_WHEEL_HOP` (14 cases, 141 of 162 runs fail, main 151): mild
  and barely-there wheel imbalances, brake judder and faint engine tones are
  missed (`no_fault`). At 80-120 km/h a wheel order runs at 11-17 Hz, right on
  the knuckle's wheel-hop hump (about 1 g there at motorway speed on a class A
  road): a mild imbalance's 113 mg line carries about 1 % of the floor's power
  beside it, where a sweep's reads need about half to stand out
  ("Order-tracked reads" in `docs/order_tracking.md`).
- `HUMP_MATCHES_IN_TOWN` (3, 24 of 36, main 30): in town the wheel order runs
  at 5-7 Hz, at the bottom of the stored spectra and on the hump's flank. A
  front-left imbalance in town, alone or under a seat mode, is missed on 18 of
  24 runs (main: read spread over all four corners); a healthy car with worn
  accessories on every mount is given a weak wheel guess at the engine bay or
  gearbox on 3 of 12 (main: a moderate or weak wheel fault on 11).
- `LEVEL_UNDER_THE_HUMP` (1, 5 of 12, main 8): brake judder in the guided brake
  step is missed on 4 runs and called a wheel on 1 (main: a weak brake guess).
- `HUMP_SCATTER` (7, 38 of 84, main 33): on more than one seed in five the hump
  moves what the report names: the wheel order's second harmonic instead of
  the first (a flat-spotted tyre), one of two equal front corners alone,
  another corner (with a loose sensor at the next corner, a lane change), or
  a healthy car's seat mode matched as a wheel fault (a lossy sensor).
- `UNEXPLAINED_BAR` (1, 6 of 6): the case checks the unexplained-vibration
  wording, which needs a body mode over its 26 dB bar; on the road its
  fixed-amplitude 13 Hz mode stands 23 dB over the trunk's local floor.

13 cases left the idealised floor when the order-tracked reads began to decide
the matches ("What the reads decide" in `docs/order_tracking.md`): they pass
on the road for every car. Every case on the road, the CI rule passes 177 of
224 case and car runs against main's 158, and of 318 healthy runs 3 are given
a fault and 3 a weak guess, against 22 and 35.

Two expectations were not true of a road and changed with it:

- A single corner's fault may be described as "strongest at the corner" with
  no ratio: over a short stretch at the heard speeds on a rough road (a surge,
  a pull-away, an upshift, a lossy sensor) no sensor's level may stand out of
  the road's scatter, and the report places the corner by its matched peaks
  ("Order-tracked reads" in `docs/order_tracking.md`; 15 of 1362 runs).
- Two faulty corners whose imbalances differ by 1.7x (front-left and
  rear-right) may read "about as strong": that is close to the 1.5x the
  wording turns at, and the weaker corner's level carries its share of the
  road's scatter.

In the CI configuration the benchmark (seeds 1-6) passes 1305 of 1344 runs;
of 318 healthy runs one is given a fault (the pothole loop, on one seed in
six).

The unexplained-vibration check judges a peak against its local floor
(`docs/metrics.md`), so a healthy car on this road is no longer reported as
"Vibration found" (211 of those runs before).

## Body attitude (`simulator/body_attitude.py`)

A sensor reads specific force: gravity's reaction plus the car's own
acceleration. `SensorAttitude` adds it to every frame (idealised and road
path alike, before the sensor's own noise or front end), turned into the axes
of the part the sensor sits on and of the sensor on that part. Readings move
linearly across each frame from the last frame's end, so a phase change adds
no step.

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Mounting | any heading, tilted 0-30° off level, per sensor (seeded) | *assumption*: the owner sticks the sensor on wherever the knuckle, rail or floor offers a flat spot |
| Body roll | 6.6°/g of lateral acceleration, outward | measured 4.9 and 6.6°/g on two passenger cars (*J. Braz. Soc. Mech. Sci. & Eng.* 33(4), 2011, Table 1); the softer one |
| Body pitch | 3°/g, nose down under braking | the quarter car's ride rate (series spring and tyre, about 18.8 kN/m per corner) under the load transfer `m g h / L` with CG height 0.55 m (NHTSA static stability factor about 1.4 on a 1.55 m track) and wheelbase 2.7 m, no anti-dive geometry |
| Understeer | 4°/g extra front-wheel steer | understeer gradients 3.9 and 4.0°/g (same paper, Table 2) |
| Steer angle | `atan(L κ)` plus the understeer, front corners only | Ackermann geometry, wheelbase 2.7 m |
| Steering axis | kingpin inclination 13°, caster 6°, leaning inboard and rearward | *assumption*: typical strut values (Reimpell, *The Automotive Chassis*) |
| Wheel carrier | stays with the road (no roll or pitch), turns about the steering axis | the knuckle's own attitude follows the road; steering turns a carrier on an inclined axis |
| Powertrain | moves with the body | engine torque roll on the mounts is not modelled (no source gives it for a generic car) |
| Grade | the scenario phase's `grade_pct`, reached along a vertical curve of 50 m per % | AASHTO *Green Book* crest/sag curve rates (K about 50 m/% at 80-90 km/h) |
| Response | the car's acceleration and lateral acceleration follow the driver with a 0.3 s first-order lag | brake pressure builds in about 0.3 s (UN ECE R13-H allows up to 0.6 s); body pitch and roll modes settle within that |

With these, a firmly fixed sensor's reading of gravity turns with the car by
up to about 1.2° more or less than another one's (body against knuckle at
0.18 g) and a front knuckle's by about 1.5° when steered at road speed
(`docs/metrics.md`, "Loose-mount check").

## Wheel kinematics

`simulator/wheel_kinematics.py` gives the simulated car its own tires and
driveline (`SimCar`, `SimTire`): every order tone turns at the speed this model
gives for the car's state (`DriveState`: true speed, longitudinal
acceleration, path curvature), never at the analysis's predicted frequency.
The analysis predicts from the entered tire size, the reported speed and a
fixed deflection; the simulator's wheels roll as real ones do, so the injected
tones sit a little off that prediction, as on a real car.

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Rolling circumference of a new tire | 3.05 × the new overall diameter, at its reference load and pressure | ETRTO's dynamic rolling circumference rule for radial passenger tires (ETRTO *Standards Manual*, general section), about 3 % under the free circumference |
| Tire vertical stiffness | `0.00028 P √(W D) + 3.45` kgf/mm, `P` in kPa, footprint width `W` = 0.75 × section width, `D` the diameter (mm) | Rhyne, *Tire Science and Technology* 33(3), 2005 (about 290 kN/m for a 285/30 R21 at 240 kPa) |
| Load and pressure on the radius | `r = r_ETRTO − (δ − δ_ref) / 3`, `δ = load / stiffness` | effective rolling radius of a radial tire sits a third of the deflection below the free radius (Pacejka, *Tire and Vehicle Dynamics*, 3rd ed., ch. 7; Jazar, *Vehicle Dynamics*, ch. 3) |
| Reference pressure | 240 kPa | a typical door-placard pressure for a mid-size car |
| Tread wear | shortens the radius one for one (`SimTire.tread_worn_mm`) | new tread is about 8 mm, the legal minimum 1.6 mm (EU Directive 89/459/EEC): up to 6.4 mm, about 2 % of a 0.34 m radius |
| Tires in service (`SimCar.in_service`, the bench default) | each axle's pair worn 0-5 mm (uniform), its two tires ±0.5 mm apart; each pressure placard −10 ± 10 kPa (normal, clipped to −60..+20) | most tires are replaced with about 3 mm left; surveys find most cars run under the placard, a quarter of them with one tire 25 % under (NHTSA *Tire Pressure Special Study*, DOT HS 809 317, 2001). The four wheels then roll on radii 0.2-1.5 % apart (5th-95th percentile), all a little smaller than new |
| Car | 1600 kg, 55 % on the front axle, CG 0.55 m high, 2.85 m wheelbase, 1.6 m track, CdA 0.65 m², rolling-resistance coefficient 0.012, 70 % of braking on the front | a mid-size saloon (Gillespie, *Fundamentals of Vehicle Dynamics*, 1992, ch. 2 and 4) |
| Load transfer | longitudinal `m a h / L` per axle, lateral `m a_y h / t` split by axle weight | Gillespie ch. 2 (rigid body, no suspension geometry) |
| Longitudinal slip | `κ = F_x / (C F_z)`, `C` = 19, capped at 10 % | the slip stiffness `B C D` of the Magic Formula for a passenger tire on dry asphalt (B 10, C 1.9, D 1; Pacejka ch. 4; MathWorks *Tire (Magic Formula)* reference coefficients) |
| Drive force | `m a` + aero drag `½ ρ CdA v²` + rolling resistance, on the driven wheels (`SimCar.driven_axle`) | a car pulls what its acceleration and its resistances need; slowing faster than the resistances alone slow it is braking, on every wheel |
| Cornering | each wheel runs `v (1 ± k t / 2)` (`k` = 1 / turn radius, the outer wheel faster) | rigid-body kinematics of a car on a curve; `ScenarioPhase.turn_radius_m` sets a phase's curve (positive to the left) |
| Driveshaft and engine | the driven wheels' mean × final drive (× gear) | an open differential turns its input at its outputs' mean |

Resulting deviations from a no-slip car on new tires: at 100 km/h cruise the
driven wheels slip about +0.4 %; on the bench sweep (1.5 m/s²) about +2 %;
at 3 m/s² about +3.5 %; braking at 0.38 g the front wheels −2 % and the rear
−1.5 %; on a 300 m curve at 100 km/h the inner and outer wheels −0.6 % and
+0.7 %.

Not modelled: tire growth at speed (under 0.5 % below 130 km/h for a
passenger radial), a locked or limited-slip differential, the tire's
relaxation length (slip follows the force at once), and engine braking on the
driven axle only (any slowing beyond the resistances is shared like
braking).

### Speed sources

| Source | Model | Source / reason |
|--------|-------|-----------------|
| GPS | the true speed, reported once a second and late (`Case.speed_lag_s`, `Case.speed_report_period_s`), with dropouts (`Case.speed_dropout_s`) | a receiver's Doppler speed is accurate to about 0.05 m/s (u-blox M8 datasheet), well under one FFT bin of a wheel order, so no speed noise is added |
| OBD-II | the true speed × (1 + `Case.obd_speed_over_read`), rounded to whole km/h | PID 0x0D comes from the wheel-speed sensors and the nominal tire circumference; a speedometer may read high but never low, up to 10 % + 4 km/h (UN ECE Regulation 39), and worn tires read high too. 3-5 % is typical |

## Confounders

`simulator/confounders.py` adds what a real first drive brings that can fool
the diagnosis or hide a fault. A `SimClient` gets them through
`SimClient.confounders` (`SensorConfounders`); the accuracy bench sets them
per sensor location (`Case.fixings`, `Case.slips`, `Case.flat_spots`, `Case.accessories`).
They act on the sensor's motion before its own noise (idealised path) or
before the ADXL345 front end (road path). Their tones skip the front end's
first-order roll-off, which is under 1 dB below 150 Hz.

### Sensor fixing (`SensorFixing`)

| Parameter | Value in the bench | Source / reason |
|-----------|--------------------|-----------------|
| Transmissibility | `(2ζωs + ω²) / (s² + 2ζωs + ω²)`, bilinear, pre-warped at the resonance | base-excited single-degree-of-freedom system, absolute acceleration (Rao, *Mechanical Vibrations*, ch. 3.6) |
| Firm fixing | no filter | a bolted or glued accelerometer rings far above the band (ISO 5348) |
| Springy bracket | 60 Hz, ζ 0.05 (×10 at resonance) | *assumption*: a sheet-metal bracket or foam pad brings the mount's ring into the band; ζ 0.02-0.1 for bolted steel structures (Rao ch. 3) |
| Loose (cable ties) | 35 Hz, ζ 0.06, hold-down 0.1 g along z | *assumption*: loosened ties hold the housing down only to a fraction of a g |
| Rattle | beyond the hold-down the reading clips at it; on landing, an impulse equal to the excess velocity gained rings the housing at 250 Hz, ζ 0.1 | rattle starts where the excitation exceeds the preload (Trapp & Chen, *Automotive Buzz, Squeak and Rattle*, 2012); impacts excite the housing's own high modes |

### Mount slip (`MountSlip`)

A fixing that comes loose lets the housing turn on it, so its whole reading
(gravity included) turns about an axis through its contact edge.

| Parameter | Value in the bench | Source / reason |
|-----------|--------------------|-----------------|
| Step | 14° at once, 20 s into the drive, on a broken stretch | an adhesive pad letting go at one corner tips a 40 mm housing onto its 10 mm edge: atan(10/40) = 14° |
| Sag | not used in the bench; the housing sags by a set rate for every second it floats off a rattling fixing, up to `max_deg` | friction holds a joint only while it is loaded; once transverse slip relieves it, any steady moment turns it bit by bit (Junker, SAE 690055, 1969). The rate has no measurement behind it (*assumption*) |

### Parking flat spots (`FlatSpot`)

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Level at the start | T1 about 85 mg at a wheel sensor (25, 15, 80 mg on x, y, z) | about 60 N of radial force variation over a 40 kg wheel corner: flat-spotted tyres measure tens of lbf (US 7,377,155 B2) |
| Flat length | 8 % of the circumference (about one contact patch) | a flat forms where the tyre stood on its contact patch |
| Harmonics | T1-T4 at 1, 0.99, 0.97, 0.94 | Fourier series of a raised-cosine dip one contact patch long |
| Recovery | half over 2 km, half over 8 km (two exponentials) | US 7,377,155 B2: rubber recovers fast, the cords slowly; Tire Rack: flat-spot vibration is gone after about 15 miles (24 km) |
| Phase | each tyre its own | the four tyres turn at slightly different rates through corners |

### Accessories (`AccessoryTone`)

| Accessory | Rhythm | Bench level (worst sensor) | Source / reason |
|-----------|--------|----------------------------|-----------------|
| HVAC blower | 45 Hz (2700 rpm) | 10 mg at the seats | fixed-speed motor |
| Alternator | 2.8 × crank | 8 mg in the engine bay | belt ratio 2.2-3 (Bosch *Automotive Handbook*) |

Levels are those of worn rotors, about five times ISO 21940-11 balance
grade G6.3 (new rotors give 1-3 mg at these mounts, which no analysis would
see).

### Driving patterns

The bench's `_wobbly_cruise` holds a cruise within ±2 km/h over about 10 s
(cruise control and a steady foot), `_real_traffic` adds a short stop, and
`_town_only` never passes 80 km/h. Two faults at once are layered on one
road (`_road_with`); a non-uniform tyre carries T1-T4 falling as 1/n
(Gent & Walter, *The Pneumatic Tire*, NHTSA 2006, ch. 9).

## Fault amplitudes

A bench fault comes in two sizes. **Tuned** (the default, and what CI gates
on): order tones at levels set per sensor, sized so the analysis finds what a
real car with that fault shows. **Physical**
(`VIBESENSOR_BENCH_FAULT_AMPLITUDES=physical`): the fault as a force in the
car, in grams or newtons, which every sensor reads through the car to its own
mount (`simulator/fault_forces.py`, `Profile.order_forces`). The physical
sizes are a measured yardstick, not a gate: `tools/dev/physical_fault_tally.py`
runs the bench with them and prints how much of it the analysis meets (see
"Physical yardstick" below). Every case has both sizes (`_sized` in the bench)
except `bench-weak-front-left-wheel-motorway`, a 10 g wheel that runs only
with physical sizes (`Case.physical_only`: tuned levels have no gram scale).

### Tuned

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Rotating unbalance (`wheel_imbalance`, `wheel_mild_imbalance`, `driveshaft_imbalance`) | the order tones grow with the square of the speed (`UNBALANCE_SPEED_EXPONENT` 2, `Profile.order_speed_exponent`), at their listed level at 100 km/h | a mass `m` at radius `r` turning at `ω` pulls with `F = m r ω²` (ISO 21940-11, the balance-quality standard that replaced ISO 1940-1), and `ω` follows the road speed. A healthy car's residual is then faint in town, as on a real car, instead of as strong as at motorway speed |
| Level at each sensor | set per sensor by the case (`_ov`, `_road_with` layers) | a wheel that lost a weight plays 0.85 of `wheel_imbalance` at its corner: about 650 mg (3-axis vector) at 80 km/h, 1 g at 100 km/h; the other sensors hear none of it, or a tenth to a third of it where a case layers it there |

### Physical

The fault is a force turning with its order (`OrderForce`): an unbalance
`m r ω²`, or a force its shape or load fixes, the same at every speed. A
sensor reads it through the structure between them:

| Parameter | Value | Source / reason |
|-----------|-------|-----------------|
| Own knuckle under its wheel's force | the quarter car's unsprung mass on tyre and suspension (`QuarterCar`: 40 kg, 200 kN/m tyre, wheel hop near 12 Hz) vertically, the wheel's fore-aft mode (17 Hz, 15 % damping) fore-aft | the same quarter car the road drives (`simulator/road_vibration.py`); fore-aft modes of 15-20 Hz in a rolling car (bushing rubber and tyre slip damp them) |
| The body under a wheel's force | rigid at these rates: fore-aft the whole sprung body (4 × 330 kg) moves; vertically the wheel's own corner moves three times as much as any other point | heave, pitch and roll add at the loaded corner and largely cancel elsewhere with a dynamic index near one (Gillespie, *Fundamentals of Vehicle Dynamics*, ch. 5) |
| Another corner's knuckle | the body's motion through its control arms (stiff fore-aft and sideways) and its suspension (vertically) | the knuckle hangs on the arms and rides on the tyre |
| Propshaft and engine | through rubber mounts (200 kg powertrain on 10 Hz mounts, 10 % damping) into a stiff body point that moves like 50 kg below 100 Hz; a sensor on the engine or gearbox rides on the shaking powertrain | mounts ring at 6-12 Hz with 5-15 % damping |
| Sensor alignment | a fifth of the strongest axis on the other two | a sensor fixed about 10° off square |

| Fault (bench) | Size | Source / reason |
|---------------|------|-----------------|
| Wheel that lost a balancing weight | 40 g at the rim | *assumption*: one mid-size clip-on or stick-on weight (they come in 5 g steps) |
| Mild, weak, barely-there wheel | 15 g, 10 g, 5 g | a balancer shows under 5 g (a quarter ounce) as zero |
| Healthy car's residual | 2-3.5 g per wheel | under the balancing tolerance |
| Propshaft | 15 g on its 40 mm tube | a lost balance weight |
| Inline-4 second order (E2) | 150 g at 45 mm, over a 20 g flywheel residual at E1 | 0.5 kg reciprocating per cylinder, 0.3 crank-to-rod ratio, no balance shafts; the crank four times worse than ISO 21940-11 G6.3 |
| Engine first order (crank pulley, flywheel) | 50 g at 0.1 m | 25 times G6.3 |
| Firing rhythm (six, three, V8) | 500 N | about 150 N·m at the firing order reacted by mounts about 0.3 m apart |
| Tyre radial force variation | 150 N at T2, 50 N at T1 (out of round); 150/n N at Tn (non-uniform) | OEM uniformity grading passes under about 100 N at the first harmonic (Gent & Walter, *The Pneumatic Tire*, NHTSA 2006, ch. 9) |
| Brake judder | 150 N fore-aft at the tyre | about 50 N·m of brake torque variation (Jacobsson, *Proc. IMechE D* 217, 2003) |
| Propshaft joint at an angle | 30 N at P2 over 5 g at P1 | the joint pulses the shaft's torque twice per turn |

A 40 g wheel at 30, 50, 80, 100 and 130 km/h shakes its own knuckle at 2,
20, 186, 409 and 1120 mg (3-axis vector) and every other sensor at 0.5, 1.7,
7, 14 and 34 mg: the wheel hop amplifies its own corner, and the 1.3 t body
barely moves.

### Physical yardstick

Measured 2026-10-09 with `tools/dev/physical_fault_tally.py`. A case and car
passes as CI counts it: seed 1 and at least four of seeds 2-6.

| Area | On the road | Idealised floor | All |
|------|-------------|-----------------|-----|
| Wheel and tyre | 16/80 | 34/43 | 50/123 |
| Driveline | 1/15 | - | 1/15 |
| Engine | 7/18 | 2/8 | 9/26 |
| Brakes | - | 7/7 | 7/7 |
| Healthy | 35/36 | 15/17 | 50/53 |
| Total | | | 117/224 |

Sized in grams, most faults the tuned bench gates on sit under what the
analysis finds on the road. The healthy cars stay healthy on the road (the one
road "healthy" miss is the electric car without its motor ratio, whose 15 g
propshaft the report calls vibration-free). On the idealised floor, with no
road hump to hide it, the residual case under a 13 Hz body mode
(`bench-healthy-residual-under-body-resonance-motorway`) names rear-right, the
3.5 g wheel on the most coupled mount: where residual ends and a fault begins.

Smallest fault found, by speed (`... limits`: a 14 s ramp over ±8 km/h, then
a wobbly 15 s cruise; found on 4 of seeds 1-5 at that size and every larger one
tried, as a fault or weak evidence naming the right source, and for a wheel at
its knuckle the right wheel; in brackets the smallest that is a fault verdict
where that differs; none: not even the largest size tried):

| Source (sizes tried) | Floor | 50 km/h | 80 km/h | 100 km/h | 130 km/h |
|----------------------|-------|---------|---------|----------|----------|
| Front-left wheel, every sensor (2-60 g) | road | none | none | 40 g | 10 g |
| | idealised | 20 g | 2 g | 2 g | 2 g |
| Front-left wheel, cabin sensors only (10-200 g) | road | none | 100 g (none) | 100 g (none) | 40 g (none) |
| | idealised | none | 200 g (none) | 100 g (none) | 40 g (none) |
| Propshaft (5-240 g at 40 mm) | road | 60 g | 30 g | 60 g | 60 g |
| | idealised | 30 g | 30 g | 30 g | 30 g |
| Inline-4 E2, every sensor (20-300 g at 45 mm) | road | 300 g | 50 g (100 g) | 50 g (100 g) | none |
| | idealised | 20 g | 20 g | 20 g | 20 g |
| Inline-4 E2, with an engine-bay sensor | road | 300 g | 20 g | 20 g | 20 g |
| | idealised | 20 g | 20 g | 20 g | 20 g |

At a steady 50 km/h the road alone reads as a wheel or tyre finding on all
wheels at every size (even 2 g, a fraction of a milli-g at the knuckle), so
that column measures the road, not the fault.

Why a 40 g wheel goes unfound at 80 km/h on the road: the analysis's combined
spectrum is the RMS over the three axes (the 3-axis vector over √3). At 80
km/h the knuckle's wheel-hop hump, which the road rings there, is 130-195 mg
per bin, about 150 mg at the wheel's first order (10.3 Hz). The 40 g line is
186 mg as a vector, about 107 mg combined: it lifts that bin only from about
156 to 197 mg, a bump inside the hump's own spread, and the run reads
no_fault. The tuned lost weight is about 650 mg (vector) at the same speed,
375 mg combined, well clear of the hump. A 40 g wheel stands out from 100 km/h
(409 mg) and a 10 g wheel at 130 km/h, where the force has grown with the
square of the speed.
