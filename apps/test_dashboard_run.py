from dashboard import start_dashboard
import requests
import time
import threading

url = "http://localhost:5000/api/state"


def build_wafer_map(wafer):
    rows = [
        [1, 1, 6, 0, 1, True, False],
        [1, 2, 9, 4, 1, True, False],
        [1, 3, 3, 3, 1, True, False],
        [1, 4, 3, 5, 1, True, False],

        [2, 1, 4, 1, 1, True, False],
        [2, 2, 5, 2, 1, True, False],
        [2, 3, 5, 4, 1, True, False],
        [2, 4, 8, 5, 1, True, False],

        [3, 1, 1, 5, 1, True, False],
        [3, 2, 6, 3, 1, True, False],
        [3, 3, 8, 1, 1, True, False],
        [3, 4, 4, 5, 1, True, False],

        [4, 1, 2, 2, 1, True, False],
        [4, 2, 3, 2, 1, True, False],
        [4, 3, 4, 2, 1, True, False],
        [4, 4, 5, 3, 1, True, False],

        [5, 1, 6, 2, 1, True, False],
        [5, 2, 7, 2, 1, True, False],
        [5, 3, 8, 2, 1, True, False],
        [5, 4, 9, 2, 1, True, False],

        [6, 1, 2, 3, 1, True, False],
        [6, 2, 3, 4, 1, True, False],
        [6, 3, 4, 4, 1, True, False],
        [6, 4, 5, 5, 1, True, False],

        [7, 1, 6, 4, 1, True, False],
        [7, 2, 7, 4, 1, True, False],
        [7, 3, 8, 4, 1, True, False],
        [7, 4, 9, 4, 1, True, False],

        [8, 1, 4, 6, 1, True, False],
        [8, 2, 5, 6, 1, True, False],
        [8, 3, 6, 6, 1, True, False],
        [8, 4, 7, 6, 1, True, False]
    ]

    if wafer == "W14":
        # W14 只測到 TD4，而且全部正常
        rows = [row for row in rows if row[0] <= 4]

    elif wafer == "W15":
        # W15：
        # TD2 Site3 = suspect
        # TD3 Site2 = fail
        for row in rows:
            if row[0] == 2 and row[1] == 3:
                row[6] = True

            if row[0] == 3 and row[1] == 2:
                row[4] = 2
                row[5] = False

    return {
        "wafer": wafer,
        "columns": [
            "td",
            "site",
            "x",
            "y",
            "sbin",
            "passed",
            "suspect"
        ],
        "rows": rows,
        "extent": {
            "x": [0, 11],
            "y": [0, 8]
        }
    }


def build_sites(wafer_map):
    rows = wafer_map["rows"]
    columns = wafer_map["columns"]

    site_index = columns.index("site")
    passed_index = columns.index("passed")
    suspect_index = columns.index("suspect")

    result = []

    for site in range(1, 5):
        site_rows = [
            row for row in rows
            if row[site_index] == site
        ]

        fail_dies = sum(
            1 for row in site_rows
            if row[passed_index] is False
        )

        suspect_dies = sum(
            1 for row in site_rows
            if row[suspect_index] is True
        )

        result.append({
            "site": site,
            "dies": len(site_rows),
            "fail_dies": fail_dies,
            "suspect_dies": suspect_dies,

            # 假資料
            "imbalance_tests": 0,
            "worst": False
        })

    return result


def build_criteria(
    mean_value,
    mean_triggered,
    yield_value,
    yield_triggered,
    onset_td
):
    return [
        {
            "key": "site_unbalance",
            "label": "Site unbalance",
            "value": 8 if mean_triggered else 2,
            "threshold": 20,
            "triggered": False,
            "trigger_when": "at_least",
            "group": None,
            "direction": None,
            "worst_site": None,
            "onset_td": None,
            "enough_data": True,
            "by_site": {
                "1": 0,
                "2": 0,
                "3": 0,
                "4": 0
            }
        },
        {
            "key": "mean_trend",
            "label": "Mean Trend Up" if mean_triggered else "Mean Trend Up",
            "value": mean_value,
            "threshold": 30,
            "triggered": mean_triggered,
            "trigger_when": "at_least",
            "group": "Main.subflow2" if mean_triggered else None,
            "direction": "up" if mean_triggered else None,
            "worst_site": None,
            "onset_td": onset_td,
            "enough_data": True
        },
        {
            "key": "stdev_up",
            "label": "Stdev Trend Up",
            "value": 12 if mean_triggered else 2,
            "threshold": 20,
            "triggered": False,
            "trigger_when": "at_least",
            "group": None,
            "direction": None,
            "worst_site": None,
            "onset_td": None,
            "enough_data": True
        },
        {
            "key": "yield",
            "label": "Low yield",
            "value": yield_value,
            "threshold": 0.8,
            "triggered": yield_triggered,
            "trigger_when": "below",
            "group": None,
            "direction": None,
            "worst_site": None,
            "onset_td": onset_td if yield_triggered else None,
            "enough_data": True
        }
    ]


def build_wafer_summary(
    wafer,
    wafer_id,
    current,
    label,
    confidence,
    yield_value,
    touchdowns,
    devices,
    mean_value=5,
    mean_triggered=False,
    yield_triggered=False,
    onset_td=None
):
    wafer_map = build_wafer_map(wafer)

    labels = []

    if mean_triggered:
        labels.append("Mean Trend Up")

    if yield_triggered:
        labels.append("Low yield")

    if label == "Site unbalance":
        labels.append("Site unbalance")

    headline = " + ".join(labels) if labels else "Normal"

    return {
        "id": wafer_id,
        "wafer": wafer,
        "current": current,

        "label": label,
        "labels": labels,
        "headline": headline,

        "onset_td": onset_td,
        "confidence": confidence,
        "yield": yield_value,

        "touchdowns": touchdowns,
        "devices": devices,

        "criteria": build_criteria(
            mean_value=mean_value,
            mean_triggered=mean_triggered,
            yield_value=yield_value,
            yield_triggered=yield_triggered,
            onset_td=onset_td
        ),

        "sites": build_sites(wafer_map)
    }


def fake_get_state(wafer):
    is_w14 = wafer == "W14"

    # =====================================================
    # Current wafer 狀態
    # =====================================================

    if is_w14:
        touchdown = 4
        label = "Normal"
        confidence = 0.95

        mean_value = 5
        mean_triggered = False

        yield_value = 0.95
        yield_triggered = False

        onset_td = None

        history = [
            {"td": 1, "label": "Normal"},
            {"td": 2, "label": "Normal"},
            {"td": 3, "label": "Normal"},
            {"td": 4, "label": "Normal"}
        ]

    else:
        touchdown = 8
        label = "Mean Trend Up"
        confidence = 0.786

        mean_value = 110
        mean_triggered = True

        yield_value = 0.75
        yield_triggered = True

        onset_td = 4

        history = [
            {"td": 1, "label": "Normal"},
            {"td": 2, "label": "Normal"},
            {"td": 3, "label": "Normal"},
            {"td": 4, "label": "Mean Trend Up"},
            {"td": 5, "label": "Mean Trend Up"},
            {"td": 6, "label": "Mean Trend Up"},
            {"td": 7, "label": "Mean Trend Up"},
            {"td": 8, "label": "Mean Trend Up"}
        ]

    wafer_map = build_wafer_map(wafer)

    # =====================================================
    # indicators
    # =====================================================

    indicators = [
        {
            "id": 1,
            "key": "wafer_offset",
            "name": "wafer offset",
            "value": 0,
            "threshold": None,
            "triggered": False,
            "detail": {}
        },
        {
            "id": 2,
            "key": "mean_trend",
            "name": "tests with same-direction mean alarm (one subflow)",
            "value": mean_value,
            "threshold": 30,
            "triggered": mean_triggered,
            "detail": {
                "direction": None if is_w14 else "up",

                # 新格式新增
                "up": 0 if is_w14 else 110,
                "down": 0,

                "group": None if is_w14 else "Main.subflow2",
                "onset_td": onset_td
            }
        },
        {
            "id": 3,
            "key": "stdev_up",
            "name": "tests with stdev alarm",
            "value": 2 if is_w14 else 12,
            "threshold": 20,
            "triggered": False,
            "detail": {
                "direction": "up",
                "group": None,
                "onset_td": None
            }
        },
        {
            "id": 4,
            "key": "site_unbalance",
            "name": "site unbalance",
            "value": 2 if is_w14 else 8,
            "threshold": 20,
            "triggered": False,
            "detail": {
                "worst_site": None,
                "onset_td": None
            }
        },
        {
            "id": 5,
            "key": "yield",
            "name": "low yield",
            "value": yield_value,
            "threshold": 0.8,
            "triggered": yield_triggered,
            "detail": {
                "onset_td": onset_td if yield_triggered else None
            }
        },
        {
            "id": 6,
            "key": "die_fail",
            "name": "die fail",
            "value": 0 if is_w14 else 1,
            "threshold": None,
            "triggered": False,
            "detail": {}
        },
        {
            "id": 7,
            "key": "ramp_shape",
            "name": "ramp shape",
            "value": 0,
            "threshold": None,
            "triggered": False,
            "detail": {}
        },
        {
            "id": 8,
            "key": "systematic_fail",
            "name": "systematic fail",
            "value": 0,
            "threshold": None,
            "triggered": False,
            "detail": {}
        }
    ]

    # =====================================================
    # finished + wafers
    # =====================================================

    if is_w14:

        finished = [
            {
                "wafer": "W12",
                "label": "Site unbalance",
                "onset_td": 13,
                "confidence": 0.824,
                "yield": 0.925,
                "n_devices": 80
            },
            {
                "wafer": "W13",
                "label": "Normal",
                "onset_td": None,
                "confidence": 0.912,
                "yield": 0.9375,
                "n_devices": 80
            }
        ]

        wafers = [
            build_wafer_summary(
                wafer="W12",
                wafer_id="012_W12",
                current=False,
                label="Site unbalance",
                confidence=0.824,
                yield_value=0.925,
                touchdowns=20,
                devices=80,
                onset_td=13
            ),

            build_wafer_summary(
                wafer="W13",
                wafer_id="013_W13",
                current=False,
                label="Normal",
                confidence=0.912,
                yield_value=0.9375,
                touchdowns=20,
                devices=80
            ),

            build_wafer_summary(
                wafer="W14",
                wafer_id="014_W14",
                current=True,
                label="Normal",
                confidence=0.95,
                yield_value=0.95,
                touchdowns=4,
                devices=16,
                mean_value=5,
                mean_triggered=False,
                yield_triggered=False
            )
        ]

    else:

        finished = [
            {
                "wafer": "W12",
                "label": "Site unbalance",
                "onset_td": 13,
                "confidence": 0.824,
                "yield": 0.925,
                "n_devices": 80
            },
            {
                "wafer": "W13",
                "label": "Normal",
                "onset_td": None,
                "confidence": 0.912,
                "yield": 0.9375,
                "n_devices": 80
            },
            {
                "wafer": "W14",
                "label": "Normal",
                "onset_td": None,
                "confidence": 0.95,
                "yield": 0.95,
                "n_devices": 16
            }
        ]

        wafers = [
            build_wafer_summary(
                wafer="W12",
                wafer_id="012_W12",
                current=False,
                label="Site unbalance",
                confidence=0.824,
                yield_value=0.925,
                touchdowns=20,
                devices=80,
                onset_td=13
            ),

            build_wafer_summary(
                wafer="W13",
                wafer_id="013_W13",
                current=False,
                label="Normal",
                confidence=0.912,
                yield_value=0.9375,
                touchdowns=20,
                devices=80
            ),

            build_wafer_summary(
                wafer="W14",
                wafer_id="014_W14",
                current=False,
                label="Normal",
                confidence=0.95,
                yield_value=0.95,
                touchdowns=4,
                devices=16
            ),

            build_wafer_summary(
                wafer="W15",
                wafer_id="015_W15",
                current=True,
                label="Mean Trend Up",
                confidence=0.786,
                yield_value=0.75,
                touchdowns=8,
                devices=32,
                mean_value=110,
                mean_triggered=True,
                yield_triggered=True,
                onset_td=4
            )
        ]

    # =====================================================
    # Scenario 2：Sensor Prediction
    # =====================================================

    if is_w14:
        predictions = [
            {
                "td": 4,
                "time": time.time(),
                "sensor": 5,
                "target": "Main#ICTemperature",
                "values": {
                    "1": 42.1,
                    "2": 42.4,
                    "3": 42.0,
                    "4": 42.3
                },
                "actual": None,
                "error": None,
                "ready": True,
                "missing": 0,
                "latency_ms": 11.84
            }
        ]

    else:
        predictions = [
            {
                "td": 7,
                "time": time.time() - 1,
                "sensor": 5,
                "target": "Main#ICTemperature",
                "values": {
                    "1": 43.1,
                    "2": 43.4,
                    "3": 43.2,
                    "4": 43.3
                },
                "actual": {
                    "1": 43.2,
                    "2": 43.5,
                    "3": 43.1,
                    "4": 43.4
                },
                "error": {
                    "1": 0.1,
                    "2": 0.1,
                    "3": -0.1,
                    "4": 0.1
                },
                "ready": True,
                "missing": 0,
                "latency_ms": 12.34
            },
            {
                "td": 8,
                "time": time.time(),
                "sensor": 5,
                "target": "Main#ICTemperature",
                "values": {
                    "1": 44.2,
                    "2": 44.5,
                    "3": 44.3,
                    "4": None
                },
                "actual": None,
                "error": None,
                "ready": False,
                "missing": 1,
                "latency_ms": 12.81
            }
        ]

    # =====================================================
    # 最終新版 state
    # =====================================================

    return {
        # Scenario 1
        "lot": "A12345",
        "wafer": wafer,
        "touchdown": touchdown,
        "label": label,
        "confidence": confidence,
        "error": None,

        "indicators": indicators,

        "wafer_map": wafer_map,

        "history": history,

        "finished": finished,

        # 新增
        "wafers": wafers,

        # Scenario 2
        "predictions": predictions,
        "predictor_error": None
    }


# =========================================================
# Start dashboard
# =========================================================

thread = threading.Thread(
    target=start_dashboard,
    daemon=True
)

thread.start()

print("Dashboard started at http://localhost:5000")
print("W14 will run for 5 seconds, then switch to W15.")

start_time = time.time()

while True:
    elapsed = time.time() - start_time

    if elapsed < 5:
        current_wafer = "W14"
    else:
        current_wafer = "W15"

    state = fake_get_state(current_wafer)

    response = requests.post(
        url,
        json=state
    )

    print(
        f"{current_wafer} | "
        f"TD {state['touchdown']} | "
        f"{state['label']} | "
        f"Wafers {len(state['wafers'])} | "
        f"Predictions {len(state['predictions'])} | "
        f"HTTP {response.status_code}"
    )

    time.sleep(1)