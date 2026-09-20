#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
train_sensor5_delta.py

Sensor 5 Delta Model
====================

核心想法
--------
原本直接預測：

    Sensor5

改成預測：

    Delta = Sensor5 - Sensor4

因為 Sensor4 在 Sensor5 之前已經完成測試，所以 runtime 時 Sensor4 是已知值。

最後：

    Sensor5_prediction = Sensor4_actual + Delta_prediction

這樣如果不同 lot 的所有溫度一起整體平移，
共同 offset 有機會在 Sensor5 - Sensor4 中被抵消，
因此可能比「直接預測 Sensor5 絕對值」更能泛化到 hidden lot。

重要原則
--------
1. 只使用 A12345 training CSV。
2. 完全不讀 B13456 / external test / hidden test。
3. 5-fold GroupKFold 以 wafer 分組。
4. 每個 fold 的 feature selection 只使用該 fold 的 training wafers。
5. model/K 選完後，才用全部 25 wafers重新 train final model。
6. 最後評估的是「重建後的 Sensor5 prediction」，不是只看 Delta R²。

輸出
----
sensor5_delta_results/
    sensor5_delta_search.csv
    sensor5_delta_fold_details.csv
    sensor5_delta_final_features.csv
    sensor5_delta_training_summary.json

sensor5_delta_model/
    sensor5_delta.joblib

Runtime 推論
------------
bundle = joblib.load("sensor5_delta.joblib")

x = [[feature_map[name] for name in bundle["features"]]]
delta_pred = bundle["model"].predict(x)[0]

sensor4_actual = feature_map[bundle["reference_sensor"]]
sensor5_pred = sensor4_actual + delta_pred
"""

import os
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

import csv
import gc
import json
import math
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.cross_decomposition import PLSRegression
from sklearn.ensemble import HistGradientBoostingRegressor, ExtraTreesRegressor
from sklearn.feature_selection import f_regression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

warnings.filterwarnings("ignore")

# ============================================================
# 0. 基本設定
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "train"

OUT_DIR = BASE_DIR / "reports" / "final"
MODEL_DIR = BASE_DIR / "sensor5_delta_model"

OUT_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

RANDOM_STATE = 42
N_SPLITS = 5

SENSOR4_NAME = "160_Main.sensor4#IO1"
SENSOR5_NAME = "180_Main.sensor5#IO2"

# 已確認的 CSV 0-based column index
SENSOR4_INDEX = 1543
SENSOR5_INDEX = 2044

# Sensor5 之前所有合法 test columns：
# metadata 0~9 不使用
# test features = 10 : SENSOR5_INDEX
#
# 注意：
# SENSOR4 本身位於這些合法 features 裡面，這是允許的，
# 因為預測 Sensor5 時 Sensor4 已經測完。
K_VALUES = [20, 40, 80, 120, 200, 400, 600]

# 選模型時不只看平均 MAE，也稍微懲罰 fold 間不穩定
ROBUST_STD_WEIGHT = 0.50


# ============================================================
# 1. Model candidates
# ============================================================

def build_model_candidates(k):
    """
    只使用 sklearn 內建模型，不需要 xgboost/lightgbm 額外套件。

    回傳：
        model_name -> sklearn estimator/pipeline
    """

    models = {}

    # --------------------------------------------------------
    # Ridge：簡單、穩定、泛化通常好
    # --------------------------------------------------------
    for alpha in [0.01, 0.1, 1.0, 10.0, 100.0]:
        models[f"Ridge_a={alpha}"] = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=alpha)),
        ])

    # --------------------------------------------------------
    # ElasticNet：線性 + 稀疏化
    # --------------------------------------------------------
    for alpha, l1 in [
        (0.0001, 0.1),
        (0.001, 0.1),
        (0.001, 0.5),
        (0.01, 0.1),
        (0.01, 0.5),
    ]:
        models[f"ElasticNet_a={alpha}_l1={l1}"] = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", ElasticNet(
                alpha=alpha,
                l1_ratio=l1,
                max_iter=30000,
                random_state=RANDOM_STATE,
            )),
        ])

    # --------------------------------------------------------
    # SVR RBF：小資料 + 非線性，值得試
    # --------------------------------------------------------
    for C, epsilon in [
        (1.0, 0.01),
        (10.0, 0.01),
        (100.0, 0.01),
        (10.0, 0.03),
        (100.0, 0.03),
    ]:
        models[f"SVR_C={C}_eps={epsilon}"] = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", SVR(
                kernel="rbf",
                C=C,
                epsilon=epsilon,
                gamma="scale",
            )),
        ])

    # --------------------------------------------------------
    # HistGradientBoosting：目前 absolute Sensor5 最強模型
    # --------------------------------------------------------
    hgb_configs = [
        ("HGB_base", dict(
            learning_rate=0.05,
            max_iter=250,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=0.0,
            random_state=RANDOM_STATE,
        )),
        ("HGB_reg1", dict(
            learning_rate=0.05,
            max_iter=300,
            max_leaf_nodes=15,
            min_samples_leaf=40,
            l2_regularization=1.0,
            random_state=RANDOM_STATE,
        )),
        ("HGB_reg2", dict(
            learning_rate=0.03,
            max_iter=350,
            max_leaf_nodes=7,
            min_samples_leaf=40,
            l2_regularization=3.0,
            random_state=RANDOM_STATE,
        )),
    ]

    for name, params in hgb_configs:
        models[name] = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(**params)),
        ])

    # --------------------------------------------------------
    # ExtraTrees：另一種非線性樹模型
    # --------------------------------------------------------
    models["ExtraTrees"] = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", ExtraTreesRegressor(
            n_estimators=300,
            max_depth=14,
            min_samples_leaf=2,
            max_features="sqrt",
            n_jobs=-1,
            random_state=RANDOM_STATE,
        )),
    ])

    # --------------------------------------------------------
    # PLSRegression：
    # 高維 + features 互相相關時很值得測。
    #
    # n_components 必須 <= k。
    # --------------------------------------------------------
    for n_comp in [5, 10, 20, 30]:
        if n_comp <= k:
            models[f"PLS_n={n_comp}"] = Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", PLSRegression(
                    n_components=n_comp,
                    scale=False,
                    max_iter=1000,
                )),
            ])

    return models


# ============================================================
# 2. 低記憶體 CSV loader
# ============================================================

def safe_float(value):
    try:
        s = str(value).strip()
        if s == "" or s.lower() in {"nan", "na", "none"}:
            return np.nan
        return float(s)
    except Exception:
        return np.nan


def load_dataset(csv_files):
    """
    讀取：
      X = Sensor5 之前的合法 features
      y4 = Sensor4 actual
      y5 = Sensor5 actual
      delta = y5 - y4
      groups = wafer group

    CSV：
      line0 = header
      line1 = Pin
      line2 = Test Num
      line3 = High Limit
      line4 = Low Limit
      line5+ = device rows
    """

    all_X = []
    all_y4 = []
    all_y5 = []
    all_groups = []
    all_meta = []

    feature_names = None

    for group_id, path in enumerate(csv_files):
        print(f"Loading {path.name} ...")

        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)

            if len(header) <= SENSOR5_INDEX:
                raise ValueError(
                    f"{path.name}: column count {len(header)} "
                    f"is not enough for Sensor5 index {SENSOR5_INDEX}"
                )

            if header[SENSOR4_INDEX] != SENSOR4_NAME:
                print(
                    f"WARNING: Sensor4 name at index {SENSOR4_INDEX} is "
                    f"{header[SENSOR4_INDEX]!r}, expected {SENSOR4_NAME!r}"
                )

            if header[SENSOR5_INDEX] != SENSOR5_NAME:
                print(
                    f"WARNING: Sensor5 name at index {SENSOR5_INDEX} is "
                    f"{header[SENSOR5_INDEX]!r}, expected {SENSOR5_NAME!r}"
                )

            current_features = header[10:SENSOR5_INDEX]

            if feature_names is None:
                feature_names = current_features
            elif current_features != feature_names:
                raise ValueError(f"Header mismatch: {path.name}")

            # skip Pin / Test Num / High Limit / Low Limit
            for _ in range(4):
                next(reader)

            count = 0

            for row in reader:
                if not row or len(row) <= SENSOR5_INDEX:
                    continue

                y4 = safe_float(row[SENSOR4_INDEX])
                y5 = safe_float(row[SENSOR5_INDEX])

                # Delta 需要 Sensor4 與 Sensor5 都有 actual
                if not (np.isfinite(y4) and np.isfinite(y5)):
                    continue

                x = [safe_float(v) for v in row[10:SENSOR5_INDEX]]

                all_X.append(x)
                all_y4.append(y4)
                all_y5.append(y5)
                all_groups.append(group_id)

                all_meta.append({
                    "file": path.name,
                    "PID": row[0] if len(row) > 0 else "",
                    "Lot": row[1] if len(row) > 1 else "",
                    "Wafer": row[2] if len(row) > 2 else "",
                    "Site": row[3] if len(row) > 3 else "",
                    "X": row[4] if len(row) > 4 else "",
                    "Y": row[5] if len(row) > 5 else "",
                })

                count += 1

        print(f"  -> {count} device rows")

    X = np.asarray(all_X, dtype=np.float32)
    y4 = np.asarray(all_y4, dtype=np.float64)
    y5 = np.asarray(all_y5, dtype=np.float64)
    delta = y5 - y4
    groups = np.asarray(all_groups, dtype=np.int32)

    print()
    print(f"X shape              : {X.shape}")
    print(f"Sensor4 shape        : {y4.shape}")
    print(f"Sensor5 shape        : {y5.shape}")
    print(f"Delta shape          : {delta.shape}")
    print(f"Wafer groups         : {len(np.unique(groups))}")
    print(f"Candidate features   : {len(feature_names)}")
    print(f"Delta mean/std       : {delta.mean():.6f} / {delta.std():.6f}")
    print(f"Sensor5 mean/std     : {y5.mean():.6f} / {y5.std():.6f}")

    return X, y4, y5, delta, groups, feature_names, all_meta


# ============================================================
# 3. Fold-safe feature selection
# ============================================================

def select_top_k_indices(X_train, y_delta_train, k):
    """
    只用 training fold：
      median imputation
      remove all-NaN / constant
      f_regression(delta)
      select Top K

    回傳原始 candidate X 的 global column indices。
    """

    Xw = X_train.astype(np.float32, copy=True)

    medians = np.nanmedian(Xw, axis=0)
    valid = np.isfinite(medians)

    valid_idx = np.where(valid)[0]

    if len(valid_idx) == 0:
        raise RuntimeError("No valid features.")

    Xv = Xw[:, valid_idx]
    medv = medians[valid_idx]

    bad_r, bad_c = np.where(~np.isfinite(Xv))
    if len(bad_r):
        Xv[bad_r, bad_c] = medv[bad_c]

    variances = np.var(Xv, axis=0)
    nonconst_mask = np.isfinite(variances) & (variances > 1e-15)
    nonconst_local = np.where(nonconst_mask)[0]

    if len(nonconst_local) == 0:
        raise RuntimeError("No non-constant features.")

    global_idx = valid_idx[nonconst_local]
    Xnc = Xv[:, nonconst_local]

    scores, _ = f_regression(Xnc, y_delta_train)
    scores = np.nan_to_num(
        scores,
        nan=-np.inf,
        posinf=np.finfo(np.float64).max,
        neginf=-np.inf,
    )

    order = np.argsort(scores)[::-1]
    k_eff = min(int(k), len(order))

    selected_global = global_idx[order[:k_eff]]

    del Xw, Xv, Xnc
    gc.collect()

    return selected_global


# ============================================================
# 4. Metrics
# ============================================================

def metrics(y_true, pred):
    return {
        "mae": float(mean_absolute_error(y_true, pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_true, pred))),
        "r2": float(r2_score(y_true, pred)),
        "bias": float(np.mean(pred - y_true)),
    }


# ============================================================
# 5. Cross-validation search
# ============================================================

def run_search(X, y4, y5, delta, groups):
    gkf = GroupKFold(n_splits=N_SPLITS)
    folds = list(gkf.split(X, delta, groups))

    summary_rows = []
    fold_rows = []

    # 先按 K 建好每 fold 的 feature selection，
    # 避免每個 model 都重新算一次 f_regression。
    prepared_by_k = {}

    print()
    print("=" * 76)
    print("PREPARING FOLD-SAFE FEATURE SELECTION")
    print("=" * 76)

    for k in K_VALUES:
        prepared = []

        print(f"\nK = {k}")

        for fold_id, (train_idx, val_idx) in enumerate(folds, start=1):
            selected_idx = select_top_k_indices(
                X[train_idx],
                delta[train_idx],
                k,
            )

            prepared.append({
                "fold": fold_id,
                "train_idx": train_idx,
                "val_idx": val_idx,
                "selected_idx": selected_idx,
            })

            print(
                f"  Fold {fold_id}: selected {len(selected_idx)} features"
            )

        prepared_by_k[k] = prepared

    print()
    print("=" * 76)
    print("MODEL SEARCH")
    print("=" * 76)

    total_configs = sum(
        len(build_model_candidates(k))
        for k in K_VALUES
    )

    config_no = 0

    for k in K_VALUES:
        models = build_model_candidates(k)

        for model_name, model_template in models.items():
            config_no += 1

            print()
            print(
                f"[{config_no}/{total_configs}] "
                f"K={k} | {model_name}"
            )

            fold_mae = []
            fold_rmse = []
            fold_r2 = []
            fold_abs_bias = []

            for item in prepared_by_k[k]:
                fold_id = item["fold"]
                train_idx = item["train_idx"]
                val_idx = item["val_idx"]
                selected_idx = item["selected_idx"]

                X_train = X[train_idx][:, selected_idx]
                X_val = X[val_idx][:, selected_idx]

                y_delta_train = delta[train_idx]
                y_delta_val = delta[val_idx]

                model = clone(model_template)
                model.fit(X_train, y_delta_train)

                delta_pred = np.asarray(model.predict(X_val)).reshape(-1)

                # 這才是最後真正的 Sensor5 prediction
                sensor5_pred = y4[val_idx] + delta_pred

                m5 = metrics(y5[val_idx], sensor5_pred)
                md = metrics(y_delta_val, delta_pred)

                fold_mae.append(m5["mae"])
                fold_rmse.append(m5["rmse"])
                fold_r2.append(m5["r2"])
                fold_abs_bias.append(abs(m5["bias"]))

                fold_rows.append({
                    "k": k,
                    "model": model_name,
                    "fold": fold_id,
                    "feature_count": len(selected_idx),

                    # Final Sensor5 metrics
                    "sensor5_mae": m5["mae"],
                    "sensor5_rmse": m5["rmse"],
                    "sensor5_r2": m5["r2"],
                    "sensor5_bias": m5["bias"],

                    # Delta metrics
                    "delta_mae": md["mae"],
                    "delta_rmse": md["rmse"],
                    "delta_r2": md["r2"],
                    "delta_bias": md["bias"],
                })

                print(
                    f"  Fold {fold_id}: "
                    f"S5 MAE={m5['mae']:.6f}, "
                    f"RMSE={m5['rmse']:.6f}, "
                    f"R2={m5['r2']:.6f}, "
                    f"bias={m5['bias']:+.6f}"
                )

                del X_train, X_val, model, delta_pred, sensor5_pred
                gc.collect()

            mean_mae = float(np.mean(fold_mae))
            std_mae = float(np.std(fold_mae, ddof=1))

            summary = {
                "k": k,
                "model": model_name,
                "mean_mae": mean_mae,
                "std_mae": std_mae,
                "mean_rmse": float(np.mean(fold_rmse)),
                "std_rmse": float(np.std(fold_rmse, ddof=1)),
                "mean_r2": float(np.mean(fold_r2)),
                "std_r2": float(np.std(fold_r2, ddof=1)),
                "mean_abs_bias": float(np.mean(fold_abs_bias)),
                "robust_score": (
                    mean_mae + ROBUST_STD_WEIGHT * std_mae
                ),
            }

            summary_rows.append(summary)

            print(
                f"  => mean MAE={summary['mean_mae']:.6f}, "
                f"std={summary['std_mae']:.6f}, "
                f"robust={summary['robust_score']:.6f}"
            )

    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["robust_score", "mean_mae", "std_mae"],
        ascending=[True, True, True],
    ).reset_index(drop=True)

    fold_df = pd.DataFrame(fold_rows)

    return summary_df, fold_df


# ============================================================
# 6. Baseline：不訓練，直接 Sensor5 = Sensor4
# ============================================================

def print_zero_delta_baseline(y4, y5, groups):
    """
    如果完全不預測 delta，假設：
        delta_pred = 0
        Sensor5_pred = Sensor4_actual

    可以幫我們知道 ML 到底有沒有真的學到東西。
    """

    gkf = GroupKFold(n_splits=N_SPLITS)
    maes = []

    print()
    print("=" * 76)
    print("ZERO-DELTA BASELINE: Sensor5_prediction = Sensor4_actual")
    print("=" * 76)

    dummy_X = np.zeros((len(y5), 1), dtype=np.float32)

    for fold_id, (_, val_idx) in enumerate(
        gkf.split(dummy_X, y5, groups),
        start=1
    ):
        pred = y4[val_idx]
        mae = mean_absolute_error(y5[val_idx], pred)
        maes.append(mae)

        print(f"Fold {fold_id}: MAE={mae:.6f}")

    print(f"Mean baseline MAE = {np.mean(maes):.6f}")
    print()


# ============================================================
# 7. Final train on all 25 wafers
# ============================================================

def train_final(
    X,
    y4,
    y5,
    delta,
    feature_names,
    best_row,
):
    best_k = int(best_row["k"])
    best_model_name = str(best_row["model"])

    print()
    print("=" * 76)
    print("FINAL TRAINING ON ALL TRAINING WAFERS")
    print("=" * 76)
    print(f"Best K     : {best_k}")
    print(f"Best model : {best_model_name}")

    selected_idx = select_top_k_indices(
        X,
        delta,
        best_k,
    )

    selected_names = [feature_names[i] for i in selected_idx]

    # 確認 Sensor4 是否在 selected features 中
    sensor4_in_features = SENSOR4_NAME in selected_names

    print(f"Selected features : {len(selected_names)}")
    print(f"Sensor4 selected  : {sensor4_in_features}")

    models = build_model_candidates(best_k)

    if best_model_name not in models:
        raise KeyError(f"Model not found: {best_model_name}")

    final_model = clone(models[best_model_name])

    X_final = X[:, selected_idx]
    final_model.fit(X_final, delta)

    # Training fit 只做 sanity check，不當 performance estimate
    delta_fit = np.asarray(final_model.predict(X_final)).reshape(-1)
    sensor5_fit = y4 + delta_fit

    train_mae = mean_absolute_error(y5, sensor5_fit)

    print(f"Training-fit S5 MAE (sanity only): {train_mae:.6f}")

    feature_report = pd.DataFrame({
        "rank": np.arange(1, len(selected_names) + 1),
        "feature": selected_names,
        "global_candidate_index": selected_idx,
    })

    feature_report.to_csv(
        OUT_DIR / "sensor5_delta_final_features.csv",
        index=False,
    )

    bundle = {
        "sensor_number": 5,
        "target": SENSOR5_NAME,

        # 這是 Delta model 最重要的 metadata
        "prediction_mode": "delta_from_sensor4",
        "reference_sensor": SENSOR4_NAME,
        "delta_definition": f"{SENSOR5_NAME} - {SENSOR4_NAME}",

        "model_name": best_model_name,
        "feature_count": len(selected_names),
        "features": selected_names,

        # model.predict(X) 的輸出是 delta，不是 Sensor5 絕對值
        "model": final_model,

        "cv_mean_mae": float(best_row["mean_mae"]),
        "cv_std_mae": float(best_row["std_mae"]),
        "cv_mean_rmse": float(best_row["mean_rmse"]),
        "cv_mean_r2": float(best_row["mean_r2"]),
        "cv_robust_score": float(best_row["robust_score"]),

        "training_policy": (
            "Predict delta = Sensor5 - Sensor4. "
            "Only A12345 training wafers were used. "
            "B13456/external/hidden labels were not used for tuning. "
            "5-fold GroupKFold by wafer. "
            "Feature selection was fitted independently inside each "
            "training fold."
        ),

        "runtime_formula": (
            "sensor5_prediction = "
            "actual_value['160_Main.sensor4#IO1'] + model.predict(X)"
        ),
    }

    model_path = MODEL_DIR / "sensor5_delta.joblib"
    joblib.dump(bundle, model_path)

    del X_final, delta_fit, sensor5_fit
    gc.collect()

    return bundle, model_path


# ============================================================
# 8. Main
# ============================================================

def main():
    csv_files = sorted(DATA_DIR.glob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(
            f"No CSV found in {DATA_DIR}\n"
            "Put A12345_W01...W25 RawResult CSV files in data/."
        )

    print("=" * 76)
    print("SENSOR 5 DELTA MODEL TRAINING")
    print("=" * 76)
    print(f"Training CSV count : {len(csv_files)}")
    print(f"Reference sensor   : {SENSOR4_NAME}")
    print(f"Target sensor      : {SENSOR5_NAME}")
    print("Training target    : Sensor5 - Sensor4")
    print("External data used : NO")
    print()

    X, y4, y5, delta, groups, feature_names, meta = load_dataset(
        csv_files
    )

    if len(np.unique(groups)) < N_SPLITS:
        raise ValueError(
            f"Need at least {N_SPLITS} wafer groups."
        )

    # --------------------------------------------------------
    # Baseline
    # --------------------------------------------------------
    print_zero_delta_baseline(y4, y5, groups)

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------
    summary_df, fold_df = run_search(
        X=X,
        y4=y4,
        y5=y5,
        delta=delta,
        groups=groups,
    )

    summary_df.to_csv(
        OUT_DIR / "sensor5_delta_search.csv",
        index=False,
    )

    fold_df.to_csv(
        OUT_DIR / "sensor5_delta_fold_details.csv",
        index=False,
    )

    print()
    print("=" * 76)
    print("TOP 15 CONFIGS")
    print("=" * 76)

    print(
        summary_df[
            [
                "k",
                "model",
                "mean_mae",
                "std_mae",
                "mean_rmse",
                "mean_r2",
                "mean_abs_bias",
                "robust_score",
            ]
        ].head(15).to_string(index=False)
    )

    best = summary_df.iloc[0]

    print()
    print("=" * 76)
    print("SELECTED FINAL CONFIG")
    print("=" * 76)
    print(f"K            = {int(best['k'])}")
    print(f"model        = {best['model']}")
    print(f"CV mean MAE  = {best['mean_mae']:.6f}")
    print(f"CV std MAE   = {best['std_mae']:.6f}")
    print(f"CV mean RMSE = {best['mean_rmse']:.6f}")
    print(f"CV mean R2   = {best['mean_r2']:.6f}")
    print(f"mean |bias|  = {best['mean_abs_bias']:.6f}")
    print(f"robust score = {best['robust_score']:.6f}")

    # --------------------------------------------------------
    # Final fit
    # --------------------------------------------------------
    bundle, model_path = train_final(
        X=X,
        y4=y4,
        y5=y5,
        delta=delta,
        feature_names=feature_names,
        best_row=best,
    )

    summary = {
        "target": SENSOR5_NAME,
        "reference_sensor": SENSOR4_NAME,
        "prediction_mode": "delta_from_sensor4",
        "best_k": int(best["k"]),
        "best_model": str(best["model"]),
        "cv_mean_mae": float(best["mean_mae"]),
        "cv_std_mae": float(best["std_mae"]),
        "cv_mean_rmse": float(best["mean_rmse"]),
        "cv_mean_r2": float(best["mean_r2"]),
        "cv_robust_score": float(best["robust_score"]),
        "external_test_used_for_tuning": False,
        "saved_model": str(model_path),
    }

    with open(
        OUT_DIR / "sensor5_delta_training_summary.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 76)
    print("DONE")
    print("=" * 76)
    print(f"Final model:")
    print(f"  {model_path}")
    print()
    print("Reports:")
    print(f"  {OUT_DIR / 'sensor5_delta_search.csv'}")
    print(f"  {OUT_DIR / 'sensor5_delta_fold_details.csv'}")
    print(f"  {OUT_DIR / 'sensor5_delta_final_features.csv'}")
    print(f"  {OUT_DIR / 'sensor5_delta_training_summary.json'}")
    print()
    print("IMPORTANT:")
    print(
        "This model predicts DELTA, not Sensor5 directly.\n"
        "Runtime formula:\n"
        "  Sensor5_pred = Sensor4_actual + delta_model.predict(X)"
    )


if __name__ == "__main__":
    main()

