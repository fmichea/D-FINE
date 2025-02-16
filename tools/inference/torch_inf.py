"""
Copyright (c) 2024 The D-FINE Authors. All Rights Reserved.
"""

import os
import sys

import cv2  # Added for video processing
import numpy as np
import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image, ImageDraw

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from src.core import YAMLConfig


labels = ["bowser", "cam_lakitu", "cam_mario", "cam_xcam", "castle_door", "coin_count", "counter_0", "counter_1", "counter_2", "counter_3", "counter_4", "counter_5", "counter_6", "counter_7", "counter_8", "counter_9", "course_number", "intro_jp_text", "intro_us_text", "key", "life_count", "logo", "mips", "save_menu", "star", "star_count", "wii_classic_controller"]
labels_mapping = dict(enumerate(labels))


def draw(output_path, images, labels, boxes, scores, thrh=0.4):
    for i, im in enumerate(images):
        draw = ImageDraw.Draw(im)

        scr = scores[i]
        lab = labels[i][scr > thrh]
        box = boxes[i][scr > thrh]
        scrs = scr[scr > thrh]

        for j, b in enumerate(box):
            draw.rectangle(list(b), outline="red")

            txt = f"{labels_mapping[lab[j].item()]} {round(scrs[j].item(), 2)}"

            print(txt, b)
            draw.text(
                (b[0], b[1]),
                text=txt,
                fill="blue",
            )

        im.save(output_path)


import time
from datetime import timedelta
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def time_block(name):
    start_time = time.time()
    yield
    duration = timedelta(seconds=time.time() - start_time)
    print('>>>> block {} ran in {} <<<<<'.format(name, duration))


def process_image(model, device, file_path):
    with time_block('process_image'):
        im_pil = Image.open(file_path).convert("RGB")
        w, h = im_pil.size
        orig_size = torch.tensor([[w, h]]).to(device)

        transforms = T.Compose(
            [
                T.Resize((640, 640)),
                T.ToTensor(),
            ]
        )
        im_data = transforms(im_pil).unsqueeze(0).to(device)

        with time_block('model_call'):
            output = model(im_data, orig_size)
        labels, boxes, scores = output

    with time_block('draw'):
        output_path = str(Path(file_path).name.replace('.jpg', '.preds.jpg'))
        draw(output_path, [im_pil], labels, boxes, scores)


def process_video(model, device, file_path):
    cap = cv2.VideoCapture(file_path)

    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Define the codec and create VideoWriter object
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter("torch_results.mp4", fourcc, fps, (orig_w, orig_h))

    transforms = T.Compose(
        [
            T.Resize((640, 640)),
            T.ToTensor(),
        ]
    )

    frame_count = 0
    print("Processing video frames...")
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Convert frame to PIL image
        frame_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        w, h = frame_pil.size
        orig_size = torch.tensor([[w, h]]).to(device)

        im_data = transforms(frame_pil).unsqueeze(0).to(device)

        output = model(im_data, orig_size)
        labels, boxes, scores = output

        # Draw detections on the frame
        draw([frame_pil], labels, boxes, scores)

        # Convert back to OpenCV image
        frame = cv2.cvtColor(np.array(frame_pil), cv2.COLOR_RGB2BGR)

        # Write the frame
        out.write(frame)
        frame_count += 1

        if frame_count % 10 == 0:
            print(f"Processed {frame_count} frames...")

    cap.release()
    out.release()
    print("Video processing complete. Result saved as 'results_video.mp4'.")


def main(args):
    """Main function"""
    cfg = YAMLConfig(args.config, resume=args.resume)

    if "HGNetv2" in cfg.yaml_cfg:
        cfg.yaml_cfg["HGNetv2"]["pretrained"] = False

    if args.resume:
        checkpoint = torch.load(args.resume, map_location="cpu")
        if "ema" in checkpoint:
            state = checkpoint["ema"]["module"]
        else:
            state = checkpoint["model"]
    else:
        raise AttributeError("Only support resume to load model.state_dict by now.")

    # Load train mode state and convert to deploy mode
    cfg.model.load_state_dict(state)

    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.model = cfg.model.deploy()
            self.postprocessor = cfg.postprocessor.deploy()

        def forward(self, images, orig_target_sizes):
            outputs = self.model(images)
            outputs = self.postprocessor(outputs, orig_target_sizes)
            return outputs

    device = args.device
    model = Model().to(device)

    # Check if the input file is an image or a video
    for file_path in args.input:
        if os.path.splitext(file_path)[-1].lower() in [".jpg", ".jpeg", ".png", ".bmp"]:
            # Process as image
            process_image(model, device, file_path)
            print("Image processing complete.")
        else:
            # Process as video
            process_video(model, device, file_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str, required=True)
    parser.add_argument("-r", "--resume", type=str, required=True)
    parser.add_argument("-d", "--device", type=str, default="cpu")
    parser.add_argument("input", nargs='+', type=str)
    args = parser.parse_args()
    main(args)
