"""
Stage 3: Component Detection (Phase 2)

Runs a fine-tuned YOLO model over sampled frames (and/or the student's
required clear top-down photo) to detect breadboard components.

IMPORTANT: this module expects a trained model file at MODEL_PATH.
Until you've labeled a dataset and run training/train.py, there is no
model to load -- calling detect_components() will raise a clear error
telling you that, rather than silently returning nothing.

Component classes are defined here as the single source of truth --
this list must exactly match the class list used when labeling in
Roboflow and referenced in training/train.py's data.yaml.
"""

from pathlib import Path

from ultralytics import YOLO

MODEL_PATH = Path(__file__).resolve().parent.parent / "training" / "runs" / "detect" / "train" / "weights" / "best.pt"

# The label taxonomy. Keep this in sync with your Roboflow project's
# class list -- mismatches here are a common, hard-to-notice bug.
COMPONENT_CLASSES = [
    "breadboard",
    "ic_chip",
    "dip_switch_4pos",
    "push_button",
    "led",
    "seven_segment_display",
    "resistor",
    "jumper_wire_red",
    "jumper_wire_black",
    "jumper_wire_yellow",
    "jumper_wire_green",
    "jumper_wire_blue",
]

_MODEL = None


def _get_model() -> YOLO:
    global _MODEL
    if _MODEL is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"No trained model found at {MODEL_PATH}. "
                "You need to label a dataset and run training/train.py "
                "before component detection will work. See training/README.md."
            )
        _MODEL = YOLO(str(MODEL_PATH))
    return _MODEL


def detect_components(image_path: str, confidence_threshold: float = 0.4) -> list[dict]:
    """
    Runs detection on a single image and returns a list of detections:
      [{"label": "dip_switch_4pos", "confidence": 0.87, "box": [x1, y1, x2, y2]}, ...]

    confidence_threshold filters out low-confidence guesses -- start at
    0.4 and tune based on validation results once you have a real model;
    too low and you get false positives, too high and you miss real
    components in cluttered frames.
    """
    model = _get_model()
    results = model.predict(image_path, conf=confidence_threshold, verbose=False)

    detections = []
    for result in results:
        for box in result.boxes:
            class_id = int(box.cls[0])
            detections.append({
                "label": COMPONENT_CLASSES[class_id] if class_id < len(COMPONENT_CLASSES) else f"unknown_{class_id}",
                "confidence": float(box.conf[0]),
                "box": [float(x) for x in box.xyxy[0].tolist()],
            })
    return detections


def detect_components_multi_frame(image_paths: list[str], confidence_threshold: float = 0.4) -> dict:
    """
    Runs detection across multiple frames and aggregates results into a
    single summary -- this is what you actually want for a video
    submission, since any single frame might have occlusion/blur/bad
    angle. A component is more trustworthy if it shows up across several
    frames, not just once.

    Returns:
      {
        "per_frame": [...],              # raw detections per frame
        "component_counts": {label: max_count_seen_in_any_single_frame},
        "component_confidence": {label: highest_confidence_seen},
      }
    """
    per_frame = []
    component_counts: dict[str, int] = {}
    component_confidence: dict[str, float] = {}

    for path in image_paths:
        detections = detect_components(path, confidence_threshold)
        per_frame.append({"frame": path, "detections": detections})

        frame_counts: dict[str, int] = {}
        for det in detections:
            label = det["label"]
            frame_counts[label] = frame_counts.get(label, 0) + 1
            component_confidence[label] = max(component_confidence.get(label, 0.0), det["confidence"])

        for label, count in frame_counts.items():
            component_counts[label] = max(component_counts.get(label, 0), count)

    return {
        "per_frame": per_frame,
        "component_counts": component_counts,
        "component_confidence": component_confidence,
    }
