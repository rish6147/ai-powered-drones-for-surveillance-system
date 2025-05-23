#!/usr/bin/env python3

"""
Implementation of the prediction procedure of the deep learning models.

This procedure is used to test a model on one specific input.
"""

###########
# Imports #
###########

import cv2
import math
import matplotlib.pyplot as plt
import numpy as np
import os
import sys
import time
import torch
import torchvision.transforms as transforms

from functools import partial
from itertools import product
from PIL import Image

current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(os.path.dirname(current))
sys.path.append(parent)

from learning.datasets import to_edges  # noqa: E402
from learning.models import DenseNet, SmallConvNet, UNet, MiDaS  # noqa: E402


#############
# Functions #
#############

def _vanishing(input_pth: str, outpt: torch.tensor) -> np.array:
    """
    Draw grid on an image and color in green the cell that contains the
    vanishing point.
    """

    # Read image
    img = cv2.imread(input_pth)
    h, w, _ = img.shape

    # Cell with vanishing point
    vp = torch.argmax(outpt).item()

    # Dimensions of each cell
    n = int(math.sqrt(torch.numel(outpt)))
    cell = (w // n, h // n)

    # Draw each cell
    for idx, (j, i) in enumerate(product(range(n), range(n))):
        left = i * cell[0]
        right = (i + 1) * cell[0]
        bottom = j * cell[1]
        top = (j + 1) * cell[1]

        if idx == vp:
            vp_cell = [(left, bottom), (right, top)]

        cv2.rectangle(img, (left, bottom), (right, top), (0, 0, 255), 2)

    # Draw vanishing point cell
    cv2.rectangle(img, vp_cell[0], vp_cell[1], (0, 255, 0), 2)

    return img


########
# Main #
########

def main(
    input_pth: str = 'input.png',
    edges: bool = False,
    model_id: str = 'densenet161',
    out_channels: int = 2,
    weights_pth: str = 'weights.pth',
    output_pth: str = 'output.png',
    vanishing: bool = False
):
    # Device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    torch.backends.cudnn.enabled = True
    torch.backends.cudnn.benchmark = True

    print(f'Device: {device}')

    # Input
    inpt = Image.open(input_pth)

    if edges:
        inpt = to_edges(inpt)

    size = (224, 384) if model_id == 'midas' else (180, 320)

    process = transforms.Compose([
        transforms.Resize(size),
        transforms.ToTensor()
    ])

    inpt = process(inpt)
    inpt = inpt.unsqueeze(0)

    # Model
    models = {
        'densenet121': partial(DenseNet, densenet_id='121'),
        'densenet161': partial(DenseNet, densenet_id='161'),
        'small': SmallConvNet,
        'unet': UNet,
        'midas': MiDaS
    }

    in_channels = inpt.size()[1]

    model = models.get(model_id, 'densenet161')(in_channels, out_channels)
    model = model.to(device)

    if model_id != 'midas':
        model.load_state_dict(torch.load(weights_pth, map_location=device))

    model.eval()

    n_params = sum(p.numel() for p in model.parameters())

    print(f'Number of parameters: {n_params}')

    # Init logger
    if torch.cuda.is_available():
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)

        n_passes = 100
        times = np.zeros((n_passes, 1))

    # Prediction
    with torch.no_grad():
        inpt = inpt.to(device)

        if torch.cuda.is_available():
            # GPU warm-up
            for _ in range(10):
                _ = model(inpt)

            # Compute inference time
            for idx in range(n_passes):
                start.record()
                outpt = model(inpt)
                end.record()

                torch.cuda.synchronize()

                time = start.elapsed_time(end)
                times[idx] = time

            print(f'Inference time (mean): {np.mean(times) / n_passes}')
            print(f'Inference time (std): {np.std(times)}')
        else:
            outpt = model(inpt)

        # Exportation
        outpt = outpt.squeeze(0).cpu()

        if model_id == 'unet':
            outpt = torch.argmax(outpt, dim=0)
            outpt = outpt.to(dtype=torch.uint8).numpy()
            outpt = Image.fromarray(outpt)
            outpt.save(output_pth)
        elif model_id == 'midas':
            depth = outpt.numpy()
            plt.imsave(output_pth, depth, cmap='plasma')
        else:
            print(f'Output: {outpt}')

        # Vanishing point
        if vanishing:
            img = _vanishing(input_pth, outpt)
            cv2.imwrite(output_pth, img)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Predict an output using a deep learning model.'
    )

    parser.add_argument(
        '-i',
        '--input',
        type=str,
        default='input.png',
        help='path to input file'
    )

    parser.add_argument(
        '-e',
        '--edges',
        default=False,
        action='store_true',
        help='flag to work with edges'
    )

    parser.add_argument(
        '-m',
        '--model',
        type=str,
        default='densenet161',
        choices=['densenet121', 'densenet161', 'small', 'unet', 'midas'],
        help='model to use for prediction'
    )

    parser.add_argument(
        '-c',
        '--channels',
        type=int,
        default=2,
        help='number output channels'
    )

    parser.add_argument(
        '-w',
        '--weights',
        type=str,
        default='weights.pth',
        help='path to weights file'
    )

    parser.add_argument(
        '-o',
        '--output',
        type=str,
        default='output.png',
        help='path to output file'
    )

    parser.add_argument(
        '-v',
        '--vanishing',
        action='store_true',
        default=False,
        help='whether to export vanishing point visualization or not'
    )

    args = parser.parse_args()

    main(
        input_pth=args.input,
        edges=args.edges,
        model_id=args.model,
        out_channels=args.channels,
        weights_pth=args.weights,
        output_pth=args.output,
        vanishing=args.vanishing
    )
