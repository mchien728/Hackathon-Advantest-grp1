from pathlib import Path
import os
import re
import json
import time
import joblib
import warnings

import numpy as np
import pandas as pd

from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.linear_model import Ridge
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

warnings.filterwarnings("ignore")


# ============================================================
# 1. 基本設定
# ============================================================

DATA_DIR = str(Path(__file__).resolve().parents[2] / "data" / "train")
MODEL_DIR = str(Path(__file__).resolve().parents[2] / "models")
RESULT_DIR = str(Path(__file__).resolve().parents[2] / "archive" / "old_reports")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)


# 六個官方要求預測的 sensor
TARGETS = [
    "100_Main.sensor1#CP",
    "120_Main.sensor2#DS0",
    "140_Main.sensor3#IO4",
    "160_Main.sensor4#IO1",
    "180_Main.sensor5#IO2",
    "200_Main.sensor6#IO3",
]


# CSV 前 10 欄不是 measurement feature
META_COLUMNS = [
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


# 為了讓沒有 GPU 的普通電腦也能跑
# 每個 sensor 最多先選 80 個最有關係的 feature
TOP_K_FEATURES = 80

# Wafer-level Cross Validation
N_SPLITS = 5

RANDOM_STATE = 42


# ============================================================
# 2. 找出 25 個 CSV
# ============================================================

def find_csv_files():
    files = []

    for filename in os.listdir(DATA_DIR):
        if filename.endswith("_RawResult.csv"):
            files.append(os.path.join(DATA_DIR, filename))

    files.sort()

    if len(files) != 25:
        print(f"⚠️ 找到 {len(files)} 個 CSV，不是預期的 25 個")
    else:
        print("✅ 找到完整 25 個 CSV")

    return files


# ============================================================
# 3. 從檔名取得 Wafer 編號
#
# A12345_W01_RawResult.csv
#          ↓
#         W01
# ============================================================

def get_wafer_name(filepath):
    filename = os.path.basename(filepath)

    match = re.search(r"_W(\d+)_", filename)

    if not match:
        raise ValueError(f"無法從檔名取得 wafer number: {filename}")

    number = int(match.group(1))

    return f"W{number:02d}"


# ============================================================
# 4. 讀取所有 Wafer
# ============================================================

def load_all_data(files):

    all_frames = []

    reference_columns = None

    for filepath in files:

        wafer_name = get_wafer_name(filepath)

        print(f"讀取 {wafer_name}: {os.path.basename(filepath)}")

        df = pd.read_csv(filepath)

        # ----------------------------------------------------
        # CSV 的前 4 列不是 IC
        #
        # row 0 = Pin
        # row 1 = Test Num
        # row 2 = High Limit
        # row 3 = Low Limit
        #
        # 真正 device 從第 5 row 開始
        # ----------------------------------------------------

        if len(df) < 84:
            raise ValueError(
                f"{wafer_name} row 數量異常: {len(df)}"
            )

        # 確認 25 份 CSV 欄位一致
        if reference_columns is None:
            reference_columns = list(df.columns)
        else:
            if list(df.columns) != reference_columns:
                raise ValueError(
                    f"{wafer_name} 的 column 與其他 wafer 不一致"
                )

        # 刪除 Pin / Test Num / High Limit / Low Limit
        device_df = df.iloc[4:].copy()

        device_df.reset_index(drop=True, inplace=True)

        # 加一個欄位標記這顆 IC 屬於哪片 wafer
        device_df["__wafer__"] = wafer_name

        all_frames.append(device_df)

    all_data = pd.concat(
        all_frames,
        ignore_index=True
    )

    print()
    print("==============================")
    print("Dataset Summary")
    print("==============================")

    print(f"Wafer 數量: {all_data['__wafer__'].nunique()}")
    print(f"Device 數量: {len(all_data)}")
    print(f"Column 數量: {len(all_data.columns)}")

    return all_data, reference_columns


# ============================================================
# 5. 準備某一個 Sensor 的合法 feature
#
# 非常重要：
#
# 只能使用 target 左邊已經執行的 test result
#
# 例如：
#
# Test A
# Test B
# Test C
# Sensor1
# Test D
#
# 預測 Sensor1：
#
# A B C 可以用
# D 不可以用
#
# ============================================================

def prepare_sensor_data(
    all_data,
    all_columns,
    target
):

    if target not in all_columns:
        raise ValueError(
            f"找不到 target: {target}"
        )

    target_index = all_columns.index(target)

    print()
    print("---------------------------------------")
    print(f"Target: {target}")
    print(f"Target column index: {target_index}")

    # 第一個 measurement 在 index 10
    first_test_index = 10

    # 只拿 target 左邊
    candidate_columns = all_columns[
        first_test_index:target_index
    ]

    print(
        f"原始可使用 feature 數量: "
        f"{len(candidate_columns)}"
    )

    # 全部轉 numeric
    X = all_data[
        candidate_columns
    ].apply(
        pd.to_numeric,
        errors="coerce"
    )

    y = pd.to_numeric(
        all_data[target],
        errors="coerce"
    )

    groups = all_data["__wafer__"]

    # ---------------------------------------
    # 移除完全沒有數值的 column
    # 或所有值都完全一樣的 column
    # ---------------------------------------

    valid_columns = []

    for column in X.columns:

        series = X[column]

        if series.notna().sum() == 0:
            continue

        if series.nunique(dropna=True) <= 1:
            continue

        valid_columns.append(column)

    X = X[valid_columns]

    print(
        f"清理後 feature 數量: "
        f"{len(valid_columns)}"
    )

    # target 不應該有 missing
    valid_rows = y.notna()

    X = X.loc[valid_rows].reset_index(drop=True)
    y = y.loc[valid_rows].reset_index(drop=True)
    groups = groups.loc[valid_rows].reset_index(drop=True)

    return X, y, groups


# ============================================================
# 6. 建立候選模型
# ============================================================

def make_models(k):

    models = {

        # -----------------------------------
        # Model 1
        # Ridge Regression
        #
        # 很快、很穩定、非常適合 baseline
        # -----------------------------------

        "Ridge": Pipeline([
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                )
            ),

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
                Ridge(
                    alpha=10.0
                )
            )
        ]),


        # -----------------------------------
        # Model 2
        # Extra Trees
        #
        # 可以學非線性關係
        # 不需要 GPU
        # -----------------------------------

        "ExtraTrees": Pipeline([
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                )
            ),

            (
                "feature_selection",
                SelectKBest(
                    score_func=f_regression,
                    k=k
                )
            ),

            (
                "model",
                ExtraTreesRegressor(
                    n_estimators=100,

                    min_samples_leaf=2,

                    random_state=RANDOM_STATE,

                    n_jobs=-1
                )
            )
        ])

    }

    return models


# ============================================================
# 7. Wafer-level Cross Validation
#
# 非常重要：
#
# 不可以：
#
# W1 device 1 -> training
# W1 device 2 -> testing
#
# 因為兩個資料太像
#
# 我們要：
#
# W1 -> training
# W2 -> training
# ...
# W5 -> testing
#
# ============================================================

def cross_validate_model(
    model,
    model_name,
    X,
    y,
    groups
):

    group_kfold = GroupKFold(
        n_splits=N_SPLITS
    )

    fold_results = []

    fold_number = 1

    for train_index, val_index in group_kfold.split(
        X,
        y,
        groups
    ):

        X_train = X.iloc[train_index]
        y_train = y.iloc[train_index]

        X_val = X.iloc[val_index]
        y_val = y.iloc[val_index]

        train_groups = groups.iloc[
            train_index
        ].unique()

        val_groups = groups.iloc[
            val_index
        ].unique()

        print()
        print(
            f"    {model_name} - Fold "
            f"{fold_number}"
        )

        print(
            "    Validation wafers:",
            ", ".join(val_groups)
        )

        start_time = time.time()

        model.fit(
            X_train,
            y_train
        )

        prediction = model.predict(
            X_val
        )

        elapsed = time.time() - start_time

        mae = mean_absolute_error(
            y_val,
            prediction
        )

        rmse = np.sqrt(
            mean_squared_error(
                y_val,
                prediction
            )
        )

        r2 = r2_score(
            y_val,
            prediction
        )

        print(
            f"    MAE  = {mae:.6f}"
        )

        print(
            f"    RMSE = {rmse:.6f}"
        )

        print(
            f"    R2   = {r2:.6f}"
        )

        print(
            f"    Time = {elapsed:.2f} sec"
        )

        fold_results.append({
            "fold": fold_number,
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "validation_wafers":
                list(val_groups)
        })

        fold_number += 1

    mean_mae = np.mean([
        x["mae"]
        for x in fold_results
    ])

    mean_rmse = np.mean([
        x["rmse"]
        for x in fold_results
    ])

    mean_r2 = np.mean([
        x["r2"]
        for x in fold_results
    ])

    return {
        "model_name": model_name,

        "mean_mae": float(mean_mae),
        "mean_rmse": float(mean_rmse),
        "mean_r2": float(mean_r2),

        "folds": fold_results
    }


# ============================================================
# 8. 使用完整資料選出最重要的 feature
#
# CV 結束之後才做
#
# 最終 deployment 不需要吃幾千個 feature
# 我們只保留 top K
# ============================================================

def select_final_features(
    X,
    y,
    k
):

    imputer = SimpleImputer(
        strategy="median"
    )

    X_imputed = imputer.fit_transform(X)

    selector = SelectKBest(
        score_func=f_regression,
        k=k
    )

    selector.fit(
        X_imputed,
        y
    )

    mask = selector.get_support()

    selected_features = list(
        X.columns[mask]
    )

    return selected_features


# ============================================================
# 9. 建立最後真正要存下來的 model
# ============================================================

def train_final_model(
    model_name,
    X,
    y,
    selected_features
):

    X_selected = X[
        selected_features
    ]

    if model_name == "Ridge":

        final_model = Pipeline([
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                )
            ),

            (
                "scaler",
                StandardScaler()
            ),

            (
                "model",
                Ridge(
                    alpha=10.0
                )
            )
        ])

    elif model_name == "ExtraTrees":

        final_model = Pipeline([
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                )
            ),

            (
                "model",
                ExtraTreesRegressor(
                    n_estimators=200,

                    min_samples_leaf=2,

                    random_state=RANDOM_STATE,

                    n_jobs=-1
                )
            )
        ])

    else:
        raise ValueError(
            f"Unknown model: {model_name}"
        )

    final_model.fit(
        X_selected,
        y
    )

    return final_model


# ============================================================
# 10. Train 一個 Sensor
# ============================================================

def train_one_sensor(
    sensor_number,
    target,
    all_data,
    all_columns
):

    print()
    print()
    print("=======================================")
    print(
        f"SENSOR {sensor_number}: {target}"
    )
    print("=======================================")

    X, y, groups = prepare_sensor_data(
        all_data,
        all_columns,
        target
    )

    k = min(
        TOP_K_FEATURES,
        X.shape[1]
    )

    print(
        f"SelectKBest K = {k}"
    )

    models = make_models(k)

    model_results = []

    # --------------------------------------
    # Cross Validation
    # --------------------------------------

    for model_name, model in models.items():

        print()
        print(
            f"Testing model: {model_name}"
        )

        result = cross_validate_model(
            model,
            model_name,
            X,
            y,
            groups
        )

        model_results.append(result)

        print()
        print(
            f"{model_name} Average:"
        )

        print(
            f"MAE  = "
            f"{result['mean_mae']:.6f}"
        )

        print(
            f"RMSE = "
            f"{result['mean_rmse']:.6f}"
        )

        print(
            f"R2   = "
            f"{result['mean_r2']:.6f}"
        )

    # --------------------------------------
    # 選 MAE 最低的 model
    # --------------------------------------

    best_result = min(
        model_results,
        key=lambda x:
            x["mean_mae"]
    )

    best_model_name = (
        best_result["model_name"]
    )

    print()
    print(
        f"🏆 Best Model = "
        f"{best_model_name}"
    )

    # --------------------------------------
    # 使用完整 training data
    # 選 top features
    # --------------------------------------

    selected_features = (
        select_final_features(
            X,
            y,
            k
        )
    )

    print()
    print(
        f"Selected "
        f"{len(selected_features)} "
        f"features"
    )

    print("Top 10 selected features:")

    for feature in selected_features[:10]:
        print(
            "   ",
            feature
        )

    # --------------------------------------
    # Train final model
    # --------------------------------------

    final_model = train_final_model(
        best_model_name,
        X,
        y,
        selected_features
    )

    # --------------------------------------
    # 建立 bundle
    #
    # 之後 sample.py 只要讀這個檔案
    # --------------------------------------

    bundle = {

        "sensor_number":
            sensor_number,

        "target":
            target,

        "model_name":
            best_model_name,

        "features":
            selected_features,

        "model":
            final_model,

        "cv_mae":
            best_result["mean_mae"],

        "cv_rmse":
            best_result["mean_rmse"],

        "cv_r2":
            best_result["mean_r2"]
    }

    model_path = os.path.join(
        MODEL_DIR,
        f"sensor{sensor_number}_model.joblib"
    )

    joblib.dump(
        bundle,
        model_path
    )

    print()
    print(
        f"✅ Saved model: {model_path}"
    )

    # --------------------------------------
    # 儲存 report
    # --------------------------------------

    report = {

        "sensor":
            sensor_number,

        "target":
            target,

        "total_devices":
            len(y),

        "candidate_features":
            X.shape[1],

        "selected_features":
            selected_features,

        "best_model":
            best_model_name,

        "all_model_results":
            model_results
    }

    report_path = os.path.join(
        RESULT_DIR,
        f"sensor{sensor_number}_report.json"
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

    return {
        "sensor":
            sensor_number,

        "target":
            target,

        "model":
            best_model_name,

        "mae":
            best_result["mean_mae"],

        "rmse":
            best_result["mean_rmse"],

        "r2":
            best_result["mean_r2"]
    }


# ============================================================
# 11. MAIN
# ============================================================

def main():

    print()
    print("=======================================")
    print(" Advantest Temperature Sensor Training ")
    print("=======================================")
    print()

    files = find_csv_files()

    if len(files) == 0:
        print(
            "❌ data/ 裡沒有找到 CSV"
        )
        return

    all_data, all_columns = (
        load_all_data(files)
    )

    # --------------------------------------
    # 確認六個 target 都真的存在
    # --------------------------------------

    print()
    print("==============================")
    print("Checking Sensor Targets")
    print("==============================")

    for target in TARGETS:

        if target in all_columns:
            position = (
                all_columns.index(target)
            )

            print(
                f"✅ {target}"
                f"  column={position}"
            )

        else:

            print(
                f"❌ 找不到 {target}"
            )

            return

    summary = []

    # --------------------------------------
    # Sensor 1 ~ Sensor 6
    # --------------------------------------

    for i, target in enumerate(
        TARGETS,
        start=1
    ):

        result = train_one_sensor(
            i,
            target,
            all_data,
            all_columns
        )

        summary.append(result)

    # --------------------------------------
    # 最後 summary
    # --------------------------------------

    summary_df = pd.DataFrame(
        summary
    )

    summary_path = os.path.join(
        RESULT_DIR,
        "summary.csv"
    )

    summary_df.to_csv(
        summary_path,
        index=False
    )

    print()
    print()
    print("=======================================")
    print(" FINAL RESULT ")
    print("=======================================")

    print(
        summary_df.to_string(
            index=False
        )
    )

    print()
    print(
        f"Summary saved to: "
        f"{summary_path}"
    )

    print()
    print("Models:")

    for i in range(1, 7):

        print(
            f"  models/"
            f"sensor{i}_model.joblib"
        )


if __name__ == "__main__":
    main()
