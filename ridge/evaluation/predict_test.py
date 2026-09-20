import os
os.environ["LOKY_MAX_CPU_COUNT"] = "8"
import csv
import glob
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


# ============================================================
# 基本設定
# ============================================================

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "train"
MODEL_DIR = ROOT / "models" / "final"

TARGETS = {
    1: "100_Main.sensor1#CP",
    2: "120_Main.sensor2#DS0",
    3: "140_Main.sensor3#IO4",
    4: "160_Main.sensor4#IO1",
    5: "180_Main.sensor5#IO2",
    6: "200_Main.sensor6#IO3",
}


# ============================================================
# 工具函式
# ============================================================

def safe_float(value):
    value = value.strip()

    if value == "":
        return np.nan

    try:
        return float(value)
    except ValueError:
        return np.nan


def find_default_csv():
    files = sorted(
        glob.glob(
            os.path.join(
                DATA_DIR,
                "*_RawResult.csv"
            )
        )
    )

    if not files:
        raise FileNotFoundError(
            "data/ 裡找不到 *_RawResult.csv"
        )

    return files[0]


def read_one_device(filepath, device_number):
    """
    讀一顆 device。

    CSV 結構：
      row 0 = header
      row 1 = Pin
      row 2 = Test Num
      row 3 = High Limit
      row 4 = Low Limit
      row 5 開始 = 真正 device

    device_number 使用 1-based：
      1 = 第一顆 device
      2 = 第二顆 device
      ...
    """

    if device_number < 1:
        raise ValueError(
            "device_number 必須 >= 1"
        )

    with open(
        filepath,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.reader(f)

        header = next(reader)

        # 跳過 4 行 metadata
        for _ in range(4):
            next(reader)

        selected_row = None

        for current_device, row in enumerate(
            reader,
            start=1
        ):
            if current_device == device_number:
                selected_row = row
                break

    if selected_row is None:
        raise ValueError(
            f"找不到第 {device_number} 顆 device"
        )

    if len(selected_row) != len(header):
        raise ValueError(
            "CSV header 欄位數和 device row 欄位數不一致："
            f"{len(header)} vs {len(selected_row)}"
        )

    values = {
        column: safe_float(value)
        for column, value
        in zip(header, selected_row)
    }

    return header, values


def load_final_models():
    models = {}

    for sensor_number in range(1, 7):

        path = os.path.join(
            MODEL_DIR,
            f"sensor{sensor_number}.joblib"
        )

        if not os.path.exists(path):
            raise FileNotFoundError(
                f"找不到模型：{path}"
            )

        bundle = joblib.load(path)

        required_keys = [
            "sensor_number",
            "target",
            "model_name",
            "feature_count",
            "features",
            "model",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in bundle
        ]

        if missing_keys:
            raise KeyError(
                f"Sensor {sensor_number} bundle 缺少："
                f"{missing_keys}"
            )

        models[sensor_number] = bundle

    return models


# ============================================================
# 驗證「時間順序」
# ============================================================

def verify_timing(
    sensor_number,
    bundle,
    header
):
    """
    確認 model 使用的每個 feature，
    在 target sensor 真正執行之前就已經出現。

    這是題目最重要的規則之一：
    不能偷用 future data。
    """

    target = bundle["target"]
    features = bundle["features"]

    if target not in header:
        raise ValueError(
            f"Target 不在 CSV header：{target}"
        )

    target_index = header.index(target)

    illegal_features = []
    missing_features = []

    for feature in features:

        if feature not in header:
            missing_features.append(
                feature
            )
            continue

        feature_index = header.index(
            feature
        )

        if feature_index >= target_index:
            illegal_features.append(
                (
                    feature,
                    feature_index
                )
            )

    if missing_features:
        print(
            f"  ❌ 找不到 {len(missing_features)} 個 feature"
        )

        for feature in missing_features[:10]:
            print(
                f"     missing: {feature}"
            )

        if len(missing_features) > 10:
            print(
                "     ..."
            )

        return False

    if illegal_features:
        print(
            f"  ❌ 發現 {len(illegal_features)} 個 future feature"
        )

        for feature, feature_index in illegal_features[:10]:
            print(
                f"     {feature}"
                f"  index={feature_index}"
                f" >= target index={target_index}"
            )

        if len(illegal_features) > 10:
            print(
                "     ..."
            )

        return False

    max_feature_index = max(
        header.index(feature)
        for feature in features
    )

    print(
        "  ✅ Timing check passed"
    )

    print(
        f"     target index = {target_index}"
    )

    print(
        f"     latest feature index = "
        f"{max_feature_index}"
    )

    return True


# ============================================================
# 模擬 realtime prediction
# ============================================================

def predict_sensor(
    sensor_number,
    bundle,
    header,
    device_values
):
    target = bundle["target"]
    features = bundle["features"]
    model = bundle["model"]

    target_index = header.index(
        target
    )

    # --------------------------------------------------------
    # 模擬「此刻真正已經測完的資料」
    #
    # 只允許使用 target 前面的欄位。
    # --------------------------------------------------------

    available_columns = set(
        header[10:target_index]
    )

    missing_at_prediction_time = [
        feature
        for feature in features
        if feature not in available_columns
    ]

    if missing_at_prediction_time:
        print(
            "  ❌ Prediction time 有 feature 尚未出現"
        )

        for feature in (
            missing_at_prediction_time[:10]
        ):
            print(
                f"     {feature}"
            )

        return None

    # --------------------------------------------------------
    # 取得 model 所需 features
    # --------------------------------------------------------

    feature_values = []

    nan_features = []

    for feature in features:

        value = device_values[
            feature
        ]

        if np.isnan(value):
            nan_features.append(
                feature
            )

        feature_values.append(
            value
        )

    if nan_features:
        print(
            f"  ⚠️ 有 {len(nan_features)} 個 feature 是 NaN"
        )

    # 一定照 bundle 裡 features 的順序建立 DataFrame
    X = pd.DataFrame(
        [feature_values],
        columns=features
    )

    prediction = float(model.predict(X)[0])
    if bundle.get("prediction_mode") == "delta_from_sensor4":
        reference = bundle["reference_sensor"]
        if reference not in available_columns:
            raise ValueError(f"Reference sensor 尚未測量：{reference}")
        sensor4_actual = device_values[reference]
        if np.isnan(sensor4_actual):
            raise ValueError("Sensor 4 actual value 是 NaN")
        prediction += sensor4_actual

    actual = device_values[
        target
    ]

    if np.isnan(actual):
        error = np.nan
    else:
        error = abs(
            prediction - actual
        )

    return {
        "sensor": sensor_number,
        "model_name": bundle["model_name"],
        "feature_count": len(features),
        "target": target,
        "prediction": prediction,
        "actual": actual,
        "absolute_error": error,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Test the six final sensor models "
            "on one real device while enforcing "
            "the no-future-data rule."
        )
    )

    parser.add_argument(
        "--file",
        default=None,
        help=(
            "要測試的 RawResult CSV。"
            "預設使用 data/ 裡第一個 CSV。"
        )
    )

    parser.add_argument(
        "--device",
        type=int,
        default=1,
        help=(
            "要測試第幾顆 device，1-based。"
            "預設 = 1"
        )
    )

    args = parser.parse_args()

    filepath = (
        args.file
        if args.file is not None
        else find_default_csv()
    )

    print()
    print(
        "======================================="
    )
    print(
        " FINAL MODEL REALTIME SIMULATION TEST "
    )
    print(
        "======================================="
    )
    print()

    print(
        "CSV:",
        filepath
    )

    print(
        "Device:",
        args.device
    )

    print()

    # --------------------------------------------------------
    # 讀取一顆 IC
    # --------------------------------------------------------

    header, device_values = (
        read_one_device(
            filepath,
            args.device
        )
    )

    print(
        f"CSV columns: {len(header)}"
    )

    print()

    # 顯示這顆 device 的基本資訊
    metadata_names = [
        "PID",
        "Lot",
        "Wafer",
        "Site",
        "X",
        "Y",
        "PF",
        "SBin",
        "HBin",
        "Test Time",
    ]

    print(
        "Device metadata:"
    )

    for name in metadata_names:

        if name in device_values:
            print(
                f"  {name}: "
                f"{device_values[name]}"
            )

    print()

    # --------------------------------------------------------
    # 載入正式模型
    # --------------------------------------------------------

    models = load_final_models()

    print(
        "✅ 6 models loaded successfully"
    )

    print()

    # --------------------------------------------------------
    # Timing check
    # --------------------------------------------------------

    print(
        "======================================="
    )
    print(
        " STEP 1 - FEATURE TIMING CHECK "
    )
    print(
        "======================================="
    )

    all_timing_ok = True

    for sensor_number in range(1, 7):

        bundle = models[
            sensor_number
        ]

        print()
        print(
            f"Sensor {sensor_number}"
            f" | {bundle['target']}"
        )

        ok = verify_timing(
            sensor_number,
            bundle,
            header
        )

        if not ok:
            all_timing_ok = False

    print()

    if not all_timing_ok:
        print(
            "❌ Timing check failed."
        )

        print(
            "先不要進行 prediction。"
        )

        return

    print(
        "✅ All six models obey the "
        "no-future-data rule."
    )

    print()

    # --------------------------------------------------------
    # 真正 prediction
    # --------------------------------------------------------

    print(
        "======================================="
    )
    print(
        " STEP 2 - PREDICTION "
    )
    print(
        "======================================="
    )

    results = []

    for sensor_number in range(1, 7):

        bundle = models[
            sensor_number
        ]

        print()
        print(
            f"Sensor {sensor_number}"
            f" | {bundle['model_name']}"
            f" | {bundle['feature_count']} features"
        )

        result = predict_sensor(
            sensor_number,
            bundle,
            header,
            device_values
        )

        if result is None:
            print(
                "  ❌ Prediction failed"
            )
            continue

        results.append(
            result
        )

        print(
            f"  Predicted = "
            f"{result['prediction']:.6f}"
        )

        print(
            f"  Actual    = "
            f"{result['actual']:.6f}"
        )

        print(
            f"  Abs Error = "
            f"{result['absolute_error']:.6f}"
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print()
    print(
        "======================================="
    )
    print(
        " PREDICTION SUMMARY "
    )
    print(
        "======================================="
    )

    if not results:
        print(
            "沒有成功的 prediction。"
        )
        return

    result_df = pd.DataFrame(
        results
    )

    print(
        result_df[
            [
                "sensor",
                "model_name",
                "feature_count",
                "prediction",
                "actual",
                "absolute_error",
            ]
        ].to_string(
            index=False
        )
    )

    print()
    print(
        "✅ predict_test.py finished successfully"
    )


if __name__ == "__main__":
    main()
