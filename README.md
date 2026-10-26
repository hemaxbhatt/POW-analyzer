# Component Detection — Dataset & Training

## Step 1 — Create a Roboflow project

1. Sign up at https://roboflow.com (free tier is enough to start)
2. Create a new project: type = **Object Detection**
3. Name it something like `breadboard-components`

## Step 2 — Upload images

Upload breadboard photos/frames. For a first useful dataset, aim for
**100-200 images minimum**, covering:
- Different boards, different circuits (not just one repeated layout)
- Different lighting conditions
- Different angles (though bias toward top-down, since that's what
  you'll require from students)
- Both clean and cluttered/messy wiring

You can pull frames from the videos you already tested in Phase 1 --
they're sitting in `data/<job_id>/frames/` from earlier runs. Real
submission footage (once you start collecting it) will always beat
generic/found images, since it matches what the model will actually
see in production.

## Step 3 — Define your label classes

Use exactly this list (must match `COMPONENT_CLASSES` in
`app/detection.py`):

```
breadboard
ic_chip
dip_switch_4pos
push_button
led
seven_segment_display
resistor
jumper_wire_red
jumper_wire_black
jumper_wire_yellow
jumper_wire_green
jumper_wire_blue
```

If you add/rename/remove a class later, you MUST update
`COMPONENT_CLASSES` in `app/detection.py` to match, in the same order
Roboflow exports them (check `data.yaml` after export -- it lists the
class order used).

## Step 4 — Label

For each image, draw a bounding box around each visible component and
assign it the correct class. This is the slow part — budget real time
for it. Tips:
- Label every instance of a jumper wire by its color, not just "wire"
- If a component is partially occluded but still identifiable, label
  it anyway (helps the model learn to handle occlusion)
- Skip images where you genuinely can't tell what something is —
  don't guess

## Step 5 — Generate + export

1. In Roboflow, click "Generate" to create a dataset version
   (this is where you can add augmentation — flips, brightness
   variation, etc. — Roboflow's defaults are reasonable to start)
2. Export in **YOLOv8** format
3. Download the zip, extract it into `training/dataset/` so you end up
   with `training/dataset/data.yaml`

## Step 6 — Train

```bash
pip install ultralytics
python training/train.py
```

First run: use the defaults (`yolov8n.pt`, 50 epochs) to get a fast
baseline and confirm the whole pipeline works. Don't judge real
accuracy from this first run — it's a smoke test.

## Step 7 — Check results

After training finishes, look at:
```
training/runs/detect/train/results.png
```
This shows loss curves and accuracy metrics over training. Also check:
```
training/runs/detect/train/val_batch0_pred.jpg
```
This shows the model's actual predictions on validation images next
to the ground truth — a fast visual sanity check on whether it's
learning the right things at all.

## Step 8 — Use it

Once `training/runs/detect/train/weights/best.pt` exists,
`app/detection.py` will automatically find and load it — no extra
config needed. Test it against a frame:

```python
from app.detection import detect_components
print(detect_components("data/<some_job_id>/frames/frame_0001.jpg"))
```

## When accuracy is poor (it will be, at first)

This is normal for an early model. Common fixes, in order of what
usually helps most:
1. **More labeled images** — almost always the biggest lever
2. **More consistent labeling** — go back and check for boxes that
   are too loose/tight or mislabeled classes
3. **More epochs** — try 100-150 once your dataset is stable
4. **Bigger base model** — try `yolov8s.pt` instead of `yolov8n.pt`
5. **Class imbalance** — if you have 500 resistor examples and 10
   push button examples, the model will be much worse at detecting
   push buttons; try to balance your labeling effort across classes
