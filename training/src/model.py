"""
Signyales Training — Model Architecture

A small 1D-CNN over the time axis of each window. Kept deliberately
compact (a few thousand parameters) so it quantizes cleanly to int8
and runs comfortably within the pipeline's real-time budget — this
is not the place to reach for a large model, since more capacity only
helps if there is enough labeled data to justify it, and gesture
datasets collected by hand rarely are large.

Input shape: (window_size, feature_count), e.g. (50, 24).
"""

import tensorflow as tf


def build_model(window_size: int, feature_count: int, num_classes: int) -> tf.keras.Model:
    inputs = tf.keras.Input(shape=(window_size, feature_count), name="window")

    x = tf.keras.layers.Conv1D(16, 5, activation="relu", padding="same")(inputs)
    x = tf.keras.layers.MaxPooling1D(2)(x)
    x = tf.keras.layers.Conv1D(32, 5, activation="relu", padding="same")(x)
    x = tf.keras.layers.GlobalAveragePooling1D()(x)
    x = tf.keras.layers.Dense(32, activation="relu")(x)
    x = tf.keras.layers.Dropout(0.3)(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax", name="gesture")(x)

    model = tf.keras.Model(inputs, outputs, name="signyales_gesture_cnn")
    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model
