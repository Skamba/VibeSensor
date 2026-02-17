"""Static library of BMW and Audi cars with realistic drivetrain data."""

from __future__ import annotations

CAR_LIBRARY: list[dict] = [
    # ── BMW ───────────────────────────────────────────────────────────────
    # 1 Series
    {
        "brand": "BMW",
        "type": "Hatchback",
        "model": "1 Series (F20, 2011-2019)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 17.0,
    },
    {
        "brand": "BMW",
        "type": "Hatchback",
        "model": "1 Series (F40, 2019-2025)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "7-speed dual-clutch (DKG)",
                "final_drive_ratio": 3.636,
                "default_gear_ratio": 0.710,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    # 2 Series Coupe
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "2 Series Coupe (F22, 2014-2021)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "2 Series Coupe (G42, 2022-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    # 2 Series Active Tourer
    {
        "brand": "BMW",
        "type": "Hatchback",
        "model": "2 Series Active Tourer (F45, 2014-2021)",
        "gearboxes": [
            {
                "name": "8-speed automatic (Aisin)",
                "final_drive_ratio": 3.294,
                "default_gear_ratio": 0.674,
            },
            {
                "name": "6-speed automatic (Aisin)",
                "final_drive_ratio": 3.416,
                "default_gear_ratio": 0.825,
            },
        ],
        "tire_width_mm": 205.0,
        "tire_aspect_pct": 55.0,
        "rim_in": 17.0,
    },
    # 3 Series
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "3 Series (F30, 2012-2019)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "3 Series (G20, 2019-2025)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    # 4 Series
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "4 Series (F32, 2014-2020)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "4 Series (G22, 2021-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    # 5 Series
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "5 Series (F10, 2011-2017)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "5 Series (G30, 2017-2023)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "5 Series (G60, 2024-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.640,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    # 6 Series
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "6 Series Gran Coupe (F06, 2013-2018)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "6 Series Gran Turismo (G32, 2018-2024)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    # 7 Series
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "7 Series (F01, 2011-2015)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "7 Series (G11, 2016-2022)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 20.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "7 Series (G70, 2023-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.640,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 20.0,
    },
    # 8 Series
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "8 Series Coupe (G15, 2019-2025)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    {
        "brand": "BMW",
        "type": "Convertible",
        "model": "8 Series Convertible (G14, 2019-2025)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "8 Series Gran Coupe (G16, 2020-2025)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    # X1
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X1 (F48, 2016-2022)",
        "gearboxes": [
            {
                "name": "8-speed automatic (Aisin)",
                "final_drive_ratio": 3.294,
                "default_gear_ratio": 0.674,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.385,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 17.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X1 (U11, 2023-2026)",
        "gearboxes": [
            {
                "name": "7-speed dual-clutch (DKG)",
                "final_drive_ratio": 3.636,
                "default_gear_ratio": 0.710,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
    },
    # X2
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X2 (F39, 2018-2023)",
        "gearboxes": [
            {
                "name": "8-speed automatic (Aisin)",
                "final_drive_ratio": 3.294,
                "default_gear_ratio": 0.674,
            },
            {
                "name": "7-speed dual-clutch (DKG)",
                "final_drive_ratio": 3.636,
                "default_gear_ratio": 0.710,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X2 (U10, 2024-2026)",
        "gearboxes": [
            {
                "name": "7-speed dual-clutch (DKG)",
                "final_drive_ratio": 3.636,
                "default_gear_ratio": 0.710,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
    },
    # X3
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X3 (F25, 2011-2017)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.385,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 18.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X3 (G01, 2018-2024)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X3 (G45, 2025-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.640,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    # X4
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X4 (F26, 2015-2018)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X4 (G02, 2019-2025)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 19.0,
    },
    # X5
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X5 (F15, 2014-2018)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.154,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X5 (G05, 2019-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 20.0,
    },
    # X6
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X6 (F16, 2015-2019)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.154,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X6 (G06, 2020-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 20.0,
    },
    # X7
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "X7 (G07, 2019-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.154,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 21.0,
    },
    # Z4
    {
        "brand": "BMW",
        "type": "Convertible",
        "model": "Z4 (G29, 2019-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.231,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 19.0,
    },
    # M3
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "M3 (F80, 2014-2018)",
        "gearboxes": [
            {
                "name": "7-speed dual-clutch (M-DCT)",
                "final_drive_ratio": 3.154,
                "default_gear_ratio": 0.714,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.793,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "M3 (G80, 2021-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 19.0,
    },
    # M4
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "M4 (F82, 2014-2020)",
        "gearboxes": [
            {
                "name": "7-speed dual-clutch (M-DCT)",
                "final_drive_ratio": 3.154,
                "default_gear_ratio": 0.714,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.793,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 19.0,
    },
    {
        "brand": "BMW",
        "type": "Coupe",
        "model": "M4 (G82, 2021-2026)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 2.813,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.812,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 19.0,
    },
    # M5
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "M5 (F90, 2018-2024)",
        "gearboxes": [
            {
                "name": "8-speed automatic (ZF 8HP)",
                "final_drive_ratio": 3.154,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    # iX
    {
        "brand": "BMW",
        "type": "SUV",
        "model": "iX (I20, 2022-2026)",
        "gearboxes": [
            {
                "name": "Single-speed fixed gear (EV)",
                "final_drive_ratio": 9.079,
                "default_gear_ratio": 1.0,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 20.0,
    },
    # i4
    {
        "brand": "BMW",
        "type": "Sedan",
        "model": "i4 (G26, 2022-2026)",
        "gearboxes": [
            {
                "name": "Single-speed fixed gear (EV)",
                "final_drive_ratio": 8.698,
                "default_gear_ratio": 1.0,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    # ── Audi ──────────────────────────────────────────────────────────────
    # A1
    {
        "brand": "Audi",
        "type": "Hatchback",
        "model": "A1 (8X, 2011-2018)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ200)",
                "final_drive_ratio": 3.786,
                "default_gear_ratio": 0.680,
            },
            {
                "name": "5-speed manual",
                "final_drive_ratio": 3.652,
                "default_gear_ratio": 0.854,
            },
        ],
        "tire_width_mm": 215.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 17.0,
    },
    {
        "brand": "Audi",
        "type": "Hatchback",
        "model": "A1 (GB, 2019-2024)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ200)",
                "final_drive_ratio": 3.786,
                "default_gear_ratio": 0.680,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 215.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 17.0,
    },
    # A3
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A3 (8V, 2013-2020)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ381)",
                "final_drive_ratio": 4.769,
                "default_gear_ratio": 0.725,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 17.0,
    },
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A3 (8Y, 2021-2026)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ381)",
                "final_drive_ratio": 4.769,
                "default_gear_ratio": 0.725,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    # A4/A5
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A4 (B8, 2011-2016)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "7-speed S tronic (DL501)",
                "final_drive_ratio": 3.444,
                "default_gear_ratio": 0.680,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 18.0,
    },
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A4 (B9, 2016-2024)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL382)",
                "final_drive_ratio": 3.564,
                "default_gear_ratio": 0.725,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    {
        "brand": "Audi",
        "type": "Coupe",
        "model": "A5 (B8, 2012-2016)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "7-speed S tronic (DL501)",
                "final_drive_ratio": 3.444,
                "default_gear_ratio": 0.680,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    {
        "brand": "Audi",
        "type": "Coupe",
        "model": "A5 (B9, 2017-2024)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL382)",
                "final_drive_ratio": 3.564,
                "default_gear_ratio": 0.725,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    # A6
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A6 (C7, 2011-2018)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "7-speed S tronic (DL501)",
                "final_drive_ratio": 3.444,
                "default_gear_ratio": 0.680,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A6 (C8, 2019-2026)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL382)",
                "final_drive_ratio": 3.564,
                "default_gear_ratio": 0.725,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
    },
    # A7
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A7 Sportback (C7, 2011-2018)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL501)",
                "final_drive_ratio": 3.444,
                "default_gear_ratio": 0.680,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A7 Sportback (C8, 2019-2026)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL382)",
                "final_drive_ratio": 3.564,
                "default_gear_ratio": 0.725,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    # A8
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A8 (D4, 2011-2017)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 2.848,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 20.0,
    },
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "A8 (D5, 2018-2026)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 2.848,
                "default_gear_ratio": 0.640,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 20.0,
    },
    # Q2
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q2 (GA, 2017-2024)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ381)",
                "final_drive_ratio": 4.769,
                "default_gear_ratio": 0.725,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 215.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 17.0,
    },
    # Q3
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q3 (8U, 2012-2018)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ500)",
                "final_drive_ratio": 4.077,
                "default_gear_ratio": 0.725,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 235.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 18.0,
    },
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q3 (F3, 2019-2026)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ381)",
                "final_drive_ratio": 4.769,
                "default_gear_ratio": 0.725,
            },
        ],
        "tire_width_mm": 235.0,
        "tire_aspect_pct": 45.0,
        "rim_in": 19.0,
    },
    # Q5
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q5 (8R, 2011-2017)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
            {
                "name": "7-speed S tronic (DL501)",
                "final_drive_ratio": 3.444,
                "default_gear_ratio": 0.680,
            },
        ],
        "tire_width_mm": 235.0,
        "tire_aspect_pct": 55.0,
        "rim_in": 18.0,
    },
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q5 (FY, 2017-2026)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL382)",
                "final_drive_ratio": 3.564,
                "default_gear_ratio": 0.725,
            },
        ],
        "tire_width_mm": 235.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 19.0,
    },
    # Q7
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q7 (4M, 2016-2026)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.333,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 20.0,
    },
    # Q8
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q8 (4M8, 2019-2026)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.333,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 21.0,
    },
    # TT
    {
        "brand": "Audi",
        "type": "Coupe",
        "model": "TT (8J, 2011-2014)",
        "gearboxes": [
            {
                "name": "6-speed S tronic (DQ250)",
                "final_drive_ratio": 3.444,
                "default_gear_ratio": 0.742,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
    },
    {
        "brand": "Audi",
        "type": "Coupe",
        "model": "TT (8S, 2015-2023)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ381)",
                "final_drive_ratio": 4.769,
                "default_gear_ratio": 0.725,
            },
            {
                "name": "6-speed manual",
                "final_drive_ratio": 3.462,
                "default_gear_ratio": 0.840,
            },
        ],
        "tire_width_mm": 245.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 19.0,
    },
    # R8
    {
        "brand": "Audi",
        "type": "Coupe",
        "model": "R8 (4S, 2015-2024)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DL800)",
                "final_drive_ratio": 3.538,
                "default_gear_ratio": 0.714,
            },
        ],
        "tire_width_mm": 295.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 20.0,
    },
    # RS3
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "RS 3 (8V/8Y, 2017-2026)",
        "gearboxes": [
            {
                "name": "7-speed S tronic (DQ500)",
                "final_drive_ratio": 4.077,
                "default_gear_ratio": 0.725,
            },
        ],
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 19.0,
    },
    # RS4/RS5
    {
        "brand": "Audi",
        "type": "Wagon",
        "model": "RS 4 Avant (B9, 2018-2024)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 20.0,
    },
    {
        "brand": "Audi",
        "type": "Coupe",
        "model": "RS 5 (B9, 2018-2024)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 275.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 20.0,
    },
    # RS6 Avant
    {
        "brand": "Audi",
        "type": "Wagon",
        "model": "RS 6 Avant (C8, 2020-2026)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
    },
    # RS7
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "RS 7 Sportback (C8, 2020-2026)",
        "gearboxes": [
            {
                "name": "8-speed tiptronic (ZF 8HP)",
                "final_drive_ratio": 3.077,
                "default_gear_ratio": 0.667,
            },
        ],
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
    },
    # e-tron GT
    {
        "brand": "Audi",
        "type": "Sedan",
        "model": "e-tron GT (J1, 2022-2026)",
        "gearboxes": [
            {
                "name": "2-speed automatic (rear) / single-speed (front)",
                "final_drive_ratio": 8.057,
                "default_gear_ratio": 1.0,
            },
        ],
        "tire_width_mm": 265.0,
        "tire_aspect_pct": 35.0,
        "rim_in": 20.0,
    },
    # Q4 e-tron
    {
        "brand": "Audi",
        "type": "SUV",
        "model": "Q4 e-tron (FZ, 2022-2026)",
        "gearboxes": [
            {
                "name": "Single-speed fixed gear (EV)",
                "final_drive_ratio": 9.756,
                "default_gear_ratio": 1.0,
            },
        ],
        "tire_width_mm": 235.0,
        "tire_aspect_pct": 50.0,
        "rim_in": 19.0,
    },
]


def get_brands() -> list[str]:
    """Return sorted list of unique brands in the library."""
    return sorted({e["brand"] for e in CAR_LIBRARY})


def get_types_for_brand(brand: str) -> list[str]:
    """Return sorted body types available for *brand*."""
    return sorted({e["type"] for e in CAR_LIBRARY if e["brand"] == brand})


def get_models_for_brand_type(brand: str, car_type: str) -> list[dict]:
    """Return all library entries matching *brand* and *car_type*."""
    return [e for e in CAR_LIBRARY if e["brand"] == brand and e["type"] == car_type]


def find_model(brand: str, car_type: str, model: str) -> dict | None:
    """Look up a single model entry by brand, type, and model name."""
    for e in CAR_LIBRARY:
        if e["brand"] == brand and e["type"] == car_type and e["model"] == model:
            return e
    return None
