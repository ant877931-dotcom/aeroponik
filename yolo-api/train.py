from pathlib import Path
from ultralytics import YOLO

HERE       = Path(__file__).parent
DATA_YAML  = HERE.parent / 'dataset' / 'data.yaml'
OUTPUT_DIR = HERE / 'runs' / 'detect'
MODEL_BASE = 'yolov8n.pt'
EPOCHS     = 100
IMG_SIZE   = 640
BATCH      = 16
PROJECT    = str(OUTPUT_DIR)
NAME       = 'pakcoy-v2'
PATIENCE   = 20

def main():
    if not DATA_YAML.exists():
        raise FileNotFoundError(f'data.yaml not found at {DATA_YAML}')
    print(f'[train] data: {DATA_YAML}')
    model = YOLO(MODEL_BASE)
    model.train(data=str(DATA_YAML), epochs=EPOCHS, imgsz=IMG_SIZE, batch=BATCH,
                project=PROJECT, name=NAME, patience=PATIENCE, exist_ok=True, verbose=True)
    best   = Path(PROJECT) / NAME / 'weights' / 'best.pt'
    deploy = HERE / 'models' / 'best.pt'
    print(f'[train] Done! Copy {best} -> {deploy} then restart the API.')

if __name__ == '__main__':
    main()
