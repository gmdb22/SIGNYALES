"""
Signyales Training — Artifact Export

Produces the exact three files pi-side/signyales_hub/model_runtime.py
expects to find together in a model directory: model.tflite, labels.json,
scaler.json. Keeping this export logic in one place is what keeps the
training pipeline and the hub's loading code from drifting apart.
"""

import json
from pathlib import Path

import numpy as np
import tensorflow as tf


def export_artifacts(model, labels, mean, std, output_dir: str,
                      quantize: bool = False, representative_data=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)

    if quantize:
        if representative_data is None:
            raise ValueError("representative_data is required for int8 quantization")
        converter.optimizations = [tf.lite.Optimize.DEFAULT]

        def rep_gen():
            for sample in representative_data:
                yield [sample[np.newaxis, ...].astype(np.float32)]

        converter.representative_dataset = rep_gen
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.int8
        converter.inference_output_type = tf.int8

    tflite_model = converter.convert()
    (output_dir / "model.tflite").write_bytes(tflite_model)

    with open(output_dir / "labels.json", "w") as f:
        json.dump(labels, f, indent=2)

    with open(output_dir / "scaler.json", "w") as f:
        json.dump({"mean": mean.tolist(), "std": std.tolist()}, f, indent=2)

    print(f"Exported model.tflite, labels.json, scaler.json to {output_dir}")
    print(f"Quantized (int8): {quantize}")
