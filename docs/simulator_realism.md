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
