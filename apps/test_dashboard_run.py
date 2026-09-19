from dashboard import start_dashboard
import requests
import time
import threading

url = "http://localhost:5000/api/state"

# Temporary wafer coordinates for frontend testing
x_coords = [
    6, 9, 3, 3, 4, 5, 5, 8, 1, 6,
    8, 4, 8, 11, 1, 4, 10, 0, 11, 8,
    3, 6, 6, 5, 7, 6, 1, 9, 6, 7,
    4, 8, 2, 10, 7, 4, 3, 7, 9, 0,
    7, 8, 8, 9, 5, 2, 2, 2, 10, 6,
    3, 5, 7, 3, 5, 4, 7, 9, 2, 2,
    7, 2, 7, 1, 1, 4, 5, 6, 9, 10,
    3, 10, 5, 3, 5, 6, 8, 4, 9, 4
]

y_coords = [
    0, 4, 3, 5, 1, 2, 4, 5, 5, 3,
    1, 5, 4, 4, 6, 2, 3, 3, 3, 6,
    0, 7, 2, 8, 4, 6, 3, 1, 5, 6,
    3, 7, 5, 5, 7, 8, 7, 8, 5, 4,
    0, 0, 3, 6, 1, 7, 1, 2, 2, 4,
    6, 3, 1, 2, 6, 0, 5, 2, 4, 3,
    2, 6, 3, 4, 2, 4, 0, 8, 3, 4,
    1, 6, 5, 4, 7, 1, 2, 6, 7, 7
]


# Build 20 touchdowns, 4 dies per touchdown
records = []

for td in range(1, 21):

    dies = []

    for site in range(1, 5):
        index = (td - 1) * 4 + (site - 1)

        dies.append({
            "site": site,
            "x": x_coords[index],
            "y": y_coords[index],
            "part_id": index + 1,
            "sbin": 1
        })

    # Temporary anomaly for wafer map testing
    is_anomaly = (td == 10)

    if is_anomaly:
        top_alerts = [
            {
                "kind": "mean_trend",
                "test": "Main.subflow2",
                "site": 2,
                "score": 3.82,
                "seq": 10
            }
        ]
    else:
        top_alerts = []

    records.append({
        "td": td,
        "time": time.time(),
        "anomaly": is_anomaly,
        "onset": is_anomaly,
        "cleared": False,
        "score": 3.82 if is_anomaly else 0.4,
        "n_alerts": len(top_alerts),
        "top_alerts": top_alerts,
        "message": (
            "Mean Trend Up"
            if is_anomaly
            else "Normal"
        ),
        "dies": dies
    })


def fake_get_state():
    return {
        "lot": "LOT001",
        "wafer": "W01",
        "touchdown": 20,

        "label": "Mean Trend Up",
        "confidence": 0.786,
        "error": None,

        "indicators": [
            {
                "id": 1,
                "key": "wafer_offset",
                "name": "wafer common offset (sigma)",
                "value": -0.629,
                "threshold": None,
                "triggered": False,
                "detail": {
                    "locked": True
                }
            },
            {
                "id": 2,
                "key": "mean_trend",
                "name": "tests with same-direction mean alarm (one subflow)",
                "value": 110,
                "threshold": 30,
                "triggered": True,
                "detail": {
                    "direction": "up",
                    "group": "Main.subflow2",
                    "onset_td": 3
                }
            },
            {
                "id": 3,
                "key": "stdev_up",
                "name": "tests with rising variance (one subflow)",
                "value": 0,
                "threshold": 30,
                "triggered": False,
                "detail": {
                    "group": "Main.subflow2",
                    "onset_td": None
                }
            },
            {
                "id": 4,
                "key": "site_unbalance",
                "name": "tests with a persistently deviating site",
                "value": 0,
                "threshold": 20,
                "triggered": False,
                "detail": {
                    "worst_site": None,
                    "group": "Main.subflow2",
                    "onset_td": None
                }
            },
            {
                "id": 5,
                "key": "yield",
                "name": "yield (systematic bins excluded)",
                "value": 0.8375,
                "threshold": 0.8,
                "triggered": False,
                "detail": {
                    "raw_yield": 0.8375,
                    "devices": 80,
                    "onset_td": 5
                }
            },
            {
                "id": 6,
                "key": "die_fail",
                "name": "dies with >=3 simultaneous 6-sigma tests in one group",
                "value": 5,
                "threshold": None,
                "triggered": False,
                "detail": {
                    "rate": 0.0625
                }
            },
            {
                "id": 7,
                "key": "ramp_shape",
                "name": "temporary ramp (onset touchdown)",
                "value": 3,
                "threshold": None,
                "triggered": True,
                "detail": {
                    "onset_td": 3,
                    "duration_td": 4,
                    "peak_frac": 0.22,
                    "snapped_back": True,
                    "group": "Main.subflow2",
                    "direction": "up"
                }
            },
            {
                "id": 8,
                "key": "systematic_fail",
                "name": "devices failing in systematic bins",
                "value": 0,
                "threshold": None,
                "triggered": False,
                "detail": {
                    "bins": [3]
                }
            }
        ],


        "totals": {
            "touchdowns": 20,
            "anomaly_touchdowns": 1
        },

        "wafer_map": {
            "wafer": "W01",
            "columns": [
                "td",
                "site",
                "x",
                "y",
                "sbin",
                "passed",
                "suspect"
            ],
            "rows": [
                [1, 1, 6, 0, 1, True, False],
                [1, 2, 9, 4, 1, True, False],
                [1, 3, 3, 3, 1, True, False],
                [1, 4, 3, 5, 1, True, False],

                [2, 1, 4, 1, 1, True, False],
                [2, 2, 5, 2, 1, True, False],
                [2, 3, 5, 4, 1, True, True],
                [2, 4, 8, 5, 1, True, False],

                [3, 1, 1, 5, 1, True, False],
                [3, 2, 6, 3, 2, False, False],
                [3, 3, 8, 1, 1, True, False],
                [3, 4, 4, 5, 1, True, False]
            ],
            "extent": {
                "x": [0, 11],
                "y": [0, 8]
            }
        }
    }


thread = threading.Thread(target=start_dashboard, daemon=True)
thread.start()

print("Dashboard started at http://localhost:5000")

while True:
    response = requests.post(url, json=fake_get_state())
    print(response.status_code, response.json())
    time.sleep(1)
