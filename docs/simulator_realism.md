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
| Gravity | +1 g on z | the sensor is mounted level, z up |
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
