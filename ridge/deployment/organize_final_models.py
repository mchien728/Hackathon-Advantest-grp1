import os
import json
import shutil
import joblib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


SOURCE_MODELS = {
    1: "models/sensor1_model.joblib",
    2: "models/sensor2_final_model.joblib",
    3: "models/sensor3_optimized_ridge_model.joblib",
    4: "models/sensor4_final_model.joblib",
    5: "sensor5_delta_model/sensor5_delta.joblib",
    6: "models/sensor6_final_model.joblib",
}


EXPECTED = {
    1: {
        "target": "100_Main.sensor1#CP",
        "model_name": "Ridge",
        "feature_count": 29,
    },

    2: {
        "target": "120_Main.sensor2#DS0",
        "model_name": "Ridge",
        "feature_count": 400,
    },

    3: {
        "target": "140_Main.sensor3#IO4",
        "model_name": "Ridge",
        "feature_count": 20,
    },

    4: {
        "target": "160_Main.sensor4#IO1",
        "model_name": "Ridge",
        "feature_count": 600,
    },

    5: {
        "target": "180_Main.sensor5#IO2",
        "model_name": "Ridge",
        "feature_count": 200,
    },

    6: {
        "target": "200_Main.sensor6#IO3",
        "model_name": "Ridge",
        "feature_count": 800,
    },
}


OUTPUT_DIR = ROOT / "models" / "final"


def get_features(bundle):

    if "features" in bundle:
        return bundle["features"]

    if "selected_features" in bundle:
        return bundle["selected_features"]

    raise KeyError(
        "找不到 features 或 selected_features"
    )


def get_model_name(bundle, expected_name):

    if "model_name" in bundle:
        return bundle["model_name"]

    if "best_model" in bundle:
        return bundle["best_model"]

    return expected_name


def main():

    print()
    print("=======================================")
    print(" ORGANIZE FINAL 6 SENSOR MODELS ")
    print("=======================================")
    print()

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    manifest = {}

    for sensor_number in range(1, 7):

        source_path = ROOT / SOURCE_MODELS[
            sensor_number
        ]

        expected = EXPECTED[
            sensor_number
        ]

        print(
            f"Sensor {sensor_number}"
        )

        print(
            f"  Source: {source_path}"
        )

        # --------------------------------------------
        # 檢查來源檔案
        # --------------------------------------------

        if not os.path.exists(
            source_path
        ):
            raise FileNotFoundError(
                f"找不到模型：{source_path}"
            )

        # --------------------------------------------
        # 載入 bundle
        # --------------------------------------------

        bundle = joblib.load(
            source_path
        )

        print(
            "  Bundle keys:",
            list(bundle.keys())
        )

        # --------------------------------------------
        # 找 features
        # --------------------------------------------

        features = get_features(
            bundle
        )

        model = bundle.get(
            "model"
        )

        if model is None:
            raise KeyError(
                f"Sensor {sensor_number} "
                f"找不到 model"
            )

        target = bundle.get(
            "target",
            expected["target"]
        )

        model_name = get_model_name(
            bundle,
            expected["model_name"]
        )

        # --------------------------------------------
        # 驗證 target
        # --------------------------------------------

        if target != expected["target"]:

            raise ValueError(
                f"Sensor {sensor_number} "
                f"target 不一致：\n"
                f"實際 = {target}\n"
                f"預期 = {expected['target']}"
            )

        # --------------------------------------------
        # 驗證 feature 數量
        # --------------------------------------------

        actual_feature_count = len(
            features
        )

        if (
            actual_feature_count
            != expected["feature_count"]
        ):

            raise ValueError(
                f"Sensor {sensor_number} "
                f"feature 數量錯誤：\n"
                f"實際 = "
                f"{actual_feature_count}\n"
                f"預期 = "
                f"{expected['feature_count']}"
            )

        if not isinstance(model_name, str) or not model_name.startswith(expected["model_name"]):
            raise ValueError(f"Sensor {sensor_number} model 不符：{model_name}")
        if sensor_number == 5 and (
            bundle.get("prediction_mode") != "delta_from_sensor4"
            or bundle.get("reference_sensor") != EXPECTED[4]["target"]
        ):
            raise ValueError("Sensor 5 必須是以 Sensor 4 為基準的 delta model")

        # --------------------------------------------
        # 建立統一格式
        # --------------------------------------------

        final_bundle = {

            "sensor_number":
                sensor_number,

            "target":
                target,

            "model_name":
                expected["model_name"],

            "feature_count":
                actual_feature_count,

            "features":
                list(features),

            "model":
                model,
        }

        final_bundle["prediction_mode"] = bundle.get("prediction_mode", "absolute")
        if sensor_number == 5:
            final_bundle["reference_sensor"] = bundle["reference_sensor"]
            final_bundle["delta_definition"] = bundle["delta_definition"]

        # 如果原本有 CV 分數，也一起保存
        for key in [
            "cv_mae",
            "cv_rmse",
            "cv_r2",
            "mean_mae",
            "mean_rmse",
            "mean_r2",
        ]:

            if key in bundle:
                final_bundle[key] = (
                    bundle[key]
                )

        # --------------------------------------------
        # 儲存正式模型
        # --------------------------------------------

        output_path = os.path.join(
            OUTPUT_DIR,
            f"sensor{sensor_number}.joblib"
        )

        joblib.dump(
            final_bundle,
            output_path
        )

        manifest[
            str(sensor_number)
        ] = {

            "file":
                f"sensor{sensor_number}.joblib",

            "target":
                target,

            "model":
                expected["model_name"],

            "feature_count":
                actual_feature_count,
            "prediction_mode": final_bundle["prediction_mode"],
        }
        if sensor_number == 5:
            manifest[str(sensor_number)]["reference_sensor"] = bundle["reference_sensor"]
            manifest[str(sensor_number)]["ridge_alpha"] = 0.01

        print(
            f"  Model: "
            f"{expected['model_name']}"
        )

        print(
            f"  Features: "
            f"{actual_feature_count}"
        )

        print(
            f"  Target: "
            f"{target}"
        )

        print(
            f"  ✅ Saved: "
            f"{output_path}"
        )

        print()

    # --------------------------------------------
    # manifest.json
    # --------------------------------------------

    manifest_path = os.path.join(
        OUTPUT_DIR,
        "manifest.json"
    )

    with open(
        manifest_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            manifest,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(
        "======================================="
    )

    print(
        " FINAL MODEL SET READY "
    )

    print(
        "======================================="
    )

    print()

    for sensor_number in range(
        1,
        7
    ):

        info = manifest[
            str(sensor_number)
        ]

        print(
            f"Sensor {sensor_number}: "
            f"{info['model']}, "
            f"{info['feature_count']} features"
        )

    print()

    print(
        f"Manifest: {manifest_path}"
    )


if __name__ == "__main__":
    main()
