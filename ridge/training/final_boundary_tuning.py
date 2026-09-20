from pathlib import Path
import os
import re
import csv
import gc
import json
import time
import warnings

import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

warnings.filterwarnings("ignore")

DATA_DIR = str(Path(__file__).resolve().parents[2] / "data" / "train")
MODEL_DIR = str(Path(__file__).resolve().parents[2] / "models")
RESULT_DIR = str(Path(__file__).resolve().parents[2] / "reports" / "final")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

RIDGE_ALPHA = 10.0
N_SPLITS = 5

TARGETS = {
    2: "120_Main.sensor2#DS0",
    4: "160_Main.sensor4#IO1",
    6: "200_Main.sensor6#IO3",
}

FEATURE_SEARCH = {
    2: [400, 450, 500, 530],
    4: [400, 600, 800, 1200],
    6: [400, 600, 800, 1200],
}


def find_csv_files():
    files = sorted(
        os.path.join(DATA_DIR, f)
        for f in os.listdir(DATA_DIR)
        if f.endswith("_RawResult.csv")
    )

    print(f"找到 {len(files)} 個 CSV")

    if len(files) != 25:
        print("⚠️ 預期應該有 25 個 training CSV")

    return files


def get_wafer_name(filepath):
    filename = os.path.basename(filepath)
    match = re.search(r"_W(\d+)_", filename)

    if not match:
        raise ValueError(f"無法解析 wafer 編號: {filename}")

    return f"W{int(match.group(1)):02d}"


def read_header(first_file):
    with open(first_file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return next(reader)


def safe_float(value):
    value = value.strip()

    if value == "":
        return np.nan

    try:
        return float(value)
    except ValueError:
        return np.nan


def load_sensor_data_streaming(files, all_columns, target):
    if target not in all_columns:
        raise ValueError(f"找不到 target: {target}")

    target_index = all_columns.index(target)
    first_test_index = 10

    candidate_indices = list(range(first_test_index, target_index))
    candidate_columns = all_columns[first_test_index:target_index]
    selected_indices = candidate_indices + [target_index]

    all_rows = []
    wafer_labels = []

    for filepath in files:
        wafer = get_wafer_name(filepath)
        print(f"  讀取 {wafer}")

        with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)

            next(reader)  # header

            for _ in range(4):  # Pin / Test Num / High Limit / Low Limit
                next(reader)

            device_count = 0

            for row in reader:
                if not row:
                    continue

                values = [safe_float(row[i]) for i in selected_indices]

                all_rows.append(values)
                wafer_labels.append(wafer)
                device_count += 1

            if device_count != 80:
                raise ValueError(
                    f"{wafer} device 數量 = {device_count}，預期 80"
                )

    data = np.asarray(all_rows, dtype=np.float32)

    X_arr = data[:, :-1]
    y_arr = data[:, -1]

    keep_mask = []

    for j in range(X_arr.shape[1]):
        col = X_arr[:, j]
        valid = col[~np.isnan(col)]

        if valid.size == 0:
            keep_mask.append(False)
            continue

        if np.unique(valid).size <= 1:
            keep_mask.append(False)
            continue

        keep_mask.append(True)

    keep_mask = np.asarray(keep_mask, dtype=bool)

    X_arr = X_arr[:, keep_mask]

    valid_columns = [
        column
        for column, keep in zip(candidate_columns, keep_mask)
        if keep
    ]

    valid_rows = ~np.isnan(y_arr)

    X_arr = X_arr[valid_rows]
    y_arr = y_arr[valid_rows]

    wafer_labels = np.asarray(wafer_labels, dtype=object)[valid_rows]

    if np.isnan(X_arr).any():
        raise ValueError(
            "偵測到 feature NaN。這版不自動補值，請先檢查資料。"
        )

    X = pd.DataFrame(X_arr, columns=valid_columns)
    y = pd.Series(y_arr, name=target)
    groups = pd.Series(wafer_labels, name="__wafer__")

    del data, X_arr, y_arr, all_rows, wafer_labels
    gc.collect()

    return X, y, groups, target_index


def make_ridge_pipeline(k):
    return Pipeline([
        (
            "feature_selection",
            SelectKBest(
                score_func=f_regression,
                k=k
            )
        ),
        (
            "scaler",
            StandardScaler()
        ),
        (
            "model",
            Ridge(alpha=RIDGE_ALPHA)
        )
    ])


def evaluate_configuration(X, y, groups, k):
    gkf = GroupKFold(n_splits=N_SPLITS)

    fold_results = []
    start_all = time.time()

    fold_number = 1

    for train_idx, val_idx in gkf.split(X, y, groups):
        X_train = X.iloc[train_idx]
        y_train = y.iloc[train_idx]

        X_val = X.iloc[val_idx]
        y_val = y.iloc[val_idx]

        val_wafers = list(groups.iloc[val_idx].unique())

        model = make_ridge_pipeline(k)

        start_fold = time.time()

        model.fit(X_train, y_train)
        prediction = model.predict(X_val)

        elapsed = time.time() - start_fold

        mae = mean_absolute_error(y_val, prediction)

        rmse = np.sqrt(
            mean_squared_error(y_val, prediction)
        )

        r2 = r2_score(y_val, prediction)

        print(
            f"    Fold {fold_number}: "
            f"MAE={mae:.6f} "
            f"RMSE={rmse:.6f} "
            f"R2={r2:.6f} "
            f"Time={elapsed:.2f}s"
        )

        print(
            "      Validation:",
            ", ".join(val_wafers)
        )

        fold_results.append({
            "fold": fold_number,
            "mae": float(mae),
            "rmse": float(rmse),
            "r2": float(r2),
            "time_sec": float(elapsed),
            "validation_wafers": val_wafers,
        })

        del model, X_train, y_train, X_val, y_val, prediction
        gc.collect()

        fold_number += 1

    return {
        "feature_count": int(k),
        "mean_mae": float(np.mean([x["mae"] for x in fold_results])),
        "std_mae": float(np.std([x["mae"] for x in fold_results])),
        "mean_rmse": float(np.mean([x["rmse"] for x in fold_results])),
        "mean_r2": float(np.mean([x["r2"] for x in fold_results])),
        "total_time_sec": float(time.time() - start_all),
        "folds": fold_results,
    }


def select_final_features(X, y, k):
    selector = SelectKBest(
        score_func=f_regression,
        k=k
    )

    selector.fit(X, y)
    mask = selector.get_support()

    selected_features = list(X.columns[mask])

    del selector
    gc.collect()

    return selected_features


def train_final_ridge(X, y, selected_features):
    X_selected = X[selected_features]

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("model", Ridge(alpha=RIDGE_ALPHA))
    ])

    model.fit(X_selected, y)
    return model


def tune_sensor(sensor_number, target, search_counts, files, all_columns):
    print()
    print()
    print("=======================================")
    print(f"SENSOR {sensor_number}: {target}")
    print("=======================================")

    X, y, groups, target_index = load_sensor_data_streaming(
        files,
        all_columns,
        target
    )

    print("Target column index:", target_index)
    print("Candidate features:", X.shape[1])

    memory_mb = X.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"X memory usage: {memory_mb:.2f} MB")

    valid_counts = [
        k for k in search_counts
        if k <= X.shape[1]
    ]

    results = []

    for idx, k in enumerate(valid_counts, start=1):
        print()
        print(
            f"[{idx}/{len(valid_counts)}] "
            f"Ridge | Top {k}"
        )

        result = evaluate_configuration(
            X,
            y,
            groups,
            k
        )

        results.append(result)

        print(
            f"    Average: "
            f"MAE={result['mean_mae']:.6f} "
            f"RMSE={result['mean_rmse']:.6f} "
            f"R2={result['mean_r2']:.6f}"
        )

    results = sorted(
        results,
        key=lambda x: (
            x["mean_mae"],
            x["mean_rmse"]
        )
    )

    best = results[0]
    best_k = int(best["feature_count"])

    print()
    print("---------------------------------------")
    print(f"BEST SENSOR {sensor_number}")
    print("---------------------------------------")
    print("Feature count:", best_k)
    print("CV MAE:", f"{best['mean_mae']:.6f}")
    print("CV RMSE:", f"{best['mean_rmse']:.6f}")
    print("CV R2:", f"{best['mean_r2']:.6f}")

    selected_features = select_final_features(
        X,
        y,
        best_k
    )

    final_model = train_final_ridge(
        X,
        y,
        selected_features
    )

    bundle = {
        "sensor_number": sensor_number,
        "target": target,
        "model_name": "Ridge",
        "ridge_alpha": RIDGE_ALPHA,
        "feature_count": best_k,
        "features": selected_features,
        "model": final_model,
        "cv_mae": best["mean_mae"],
        "cv_rmse": best["mean_rmse"],
        "cv_r2": best["mean_r2"],
    }

    model_path = os.path.join(
        MODEL_DIR,
        f"sensor{sensor_number}_final_model.joblib"
    )

    joblib.dump(bundle, model_path)

    report = {
        "sensor": sensor_number,
        "target": target,
        "candidate_features": int(X.shape[1]),
        "searched_feature_counts": valid_counts,
        "best_feature_count": best_k,
        "best_mae": best["mean_mae"],
        "best_rmse": best["mean_rmse"],
        "best_r2": best["mean_r2"],
        "selected_features": selected_features,
        "all_results": results,
    }

    report_path = os.path.join(
        RESULT_DIR,
        f"sensor{sensor_number}_boundary_search.json"
    )

    with open(
        report_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False
        )

    summary = {
        "sensor": sensor_number,
        "target": target,
        "best_feature_count": best_k,
        "mae": best["mean_mae"],
        "rmse": best["mean_rmse"],
        "r2": best["mean_r2"],
        "model_path": model_path,
    }

    del X, y, groups, final_model, bundle
    gc.collect()

    return summary


def main():
    print()
    print("=======================================")
    print(" FINAL RIDGE BOUNDARY TUNING ")
    print(" Sensor 2 / 4 / 6 ")
    print("=======================================")
    print()

    files = find_csv_files()

    if len(files) == 0:
        print("❌ data/ 裡沒有找到 CSV")
        return

    all_columns = read_header(files[0])

    print(f"CSV columns: {len(all_columns)}")

    summary = []

    for sensor_number, target in TARGETS.items():
        result = tune_sensor(
            sensor_number,
            target,
            FEATURE_SEARCH[sensor_number],
            files,
            all_columns
        )

        summary.append(result)

    summary_df = pd.DataFrame(summary)

    summary_path = os.path.join(
        RESULT_DIR,
        "final_boundary_summary.csv"
    )

    summary_df.to_csv(
        summary_path,
        index=False
    )

    print()
    print()
    print("=======================================")
    print(" FINAL BOUNDARY TUNING RESULT ")
    print("=======================================")

    print(
        summary_df[
            [
                "sensor",
                "target",
                "best_feature_count",
                "mae",
                "rmse",
                "r2"
            ]
        ].to_string(index=False)
    )

    print()
    print("Summary saved to:", summary_path)

    print()
    print("Final models:")

    for row in summary:
        print(" ", row["model_path"])

    print()
    print("Sensor 1：維持原本 Ridge baseline")
    print("Sensor 3：維持 Ridge + Top 20")
    print("Sensor 5：維持 HistGradientBoosting + Top 400")


if __name__ == "__main__":
    main()

