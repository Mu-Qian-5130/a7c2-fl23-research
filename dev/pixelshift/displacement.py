"""Read-only measurement of displacement in four original, grouped RAWs.

Checks image displacement against a one-pixel square. It cannot distinguish
sensor motion from movement of the whole camera/scene, or prove motor settling.
No images, RAW data, metadata or firmware are changed.
"""
import argparse
from itertools import permutations
import json
from pathlib import Path

import numpy as np

from raw_group import inspect, validate


def translation(reference, moving):
    """Return the subpixel (y,x) translation that aligns moving to reference."""
    a, b = np.asarray(reference, dtype=float), np.asarray(moving, dtype=float)
    if a.shape != b.shape or a.ndim != 2 or min(a.shape) < 32:
        raise ValueError('Need equal, textured two-dimensional samples at least 32 pixels wide')
    if not np.isfinite(a).all() or not np.isfinite(b).all() or min(a.std(), b.std()) == 0:
        raise ValueError('Displacement needs finite image texture')
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa = np.fft.fft2((a - a.mean()) * window)
    fb = np.fft.fft2((b - b.mean()) * window)
    cross = fa * fb.conj()
    magnitude = abs(cross)
    # Exclude frequencies dominated by numerical/flat-region noise.
    cross /= np.maximum(magnitude, magnitude.max() * 1e-4)
    coarse = np.unravel_index(np.argmax(abs(np.fft.ifft2(cross))), a.shape)
    coarse = np.asarray(coarse, dtype=float)
    coarse = np.where(coarse > np.asarray(a.shape) / 2, coarse - np.asarray(a.shape), coarse)
    ys = coarse[0] + np.arange(-50, 51) / 50
    xs = coarse[1] + np.arange(-50, 51) / 50
    ey = np.exp(2j * np.pi * np.outer(ys, np.fft.fftfreq(a.shape[0])))
    ex = np.exp(2j * np.pi * np.outer(xs, np.fft.fftfreq(a.shape[1])))
    correlation = abs(ey @ cross @ ex.T)
    row, column = np.unravel_index(correlation.argmax(), correlation.shape)
    return np.array([ys[row], xs[column]])


def square_evidence(positions, tolerance=0.15):
    """Compare four measured RAW-pixel positions to the native four-shot grid."""
    measured = np.asarray(positions, dtype=float)
    if measured.shape != (4, 2) or not np.isfinite(measured).all():
        raise ValueError('Need four finite two-dimensional positions')
    best = None
    for grid in permutations([(0, 0), (0, 1), (1, 0), (1, 1)]):
        grid = np.asarray(grid, dtype=float)
        offset = (measured - grid).mean(axis=0)
        residual = measured - grid - offset
        error = float(np.sqrt(np.mean(np.sum(residual * residual, axis=1))))
        if best is None or error < best['rms_pixels']:
            best = {'rms_pixels': error, 'assigned_grid_yx': grid.tolist(),
                    'max_error_pixels': float(np.linalg.norm(residual, axis=1).max())}
    best.update(consistent_with_one_pixel_square=best['max_error_pixels'] <= tolerance,
                tolerance_raw_pixels=tolerance, physical_actuator_verified=False,
                settling_verified=False, composition_verified=False)
    return best


def green_samples(path, crop):
    import rawpy
    with rawpy.imread(str(path)) as raw:
        mosaic = raw.raw_image_visible
        pattern = raw.raw_pattern
        if pattern is None or pattern.shape != (2, 2):
            raise ValueError('Expected the original two-by-two Bayer pattern')
        if crop % 2 or crop < 64 or crop > min(mosaic.shape):
            raise ValueError('Crop must be even, at least 64, and fit the visible RAW')
        y, x = [((n - crop) // 2) & ~1 for n in mosaic.shape]
        patch = mosaic[y:y + crop, x:x + crop]
        channels = []
        for yy, xx in np.ndindex(2, 2):
            if raw.color_desc[int(pattern[yy, xx])] == ord('G'):
                channels.append(patch[yy::2, xx::2].astype(float))
        if len(channels) != 2:
            raise ValueError('Expected both green Bayer sublattices')
        return channels, list(mosaic.shape)


def measure(paths, *, crop=1024):
    metadata = [inspect(p) for p in paths]
    group = validate(metadata)
    ordered = [Path(p) for p in group['ordered_files']]
    samples = [green_samples(p, crop) for p in ordered]
    if len({tuple(size) for _, size in samples}) != 1:
        raise ValueError('Source RAW dimensions differ')
    sublattices = []
    for channel in range(2):
        reference = samples[0][0][channel]
        shifts = [np.zeros(2)]
        shifts += [2 * translation(reference, item[0][channel]) for item in samples[1:]]
        sublattices.append(np.asarray(shifts))
    disagreement = float(np.linalg.norm(sublattices[0] - sublattices[1], axis=1).max())
    positions = np.mean(sublattices, axis=0)
    evidence = square_evidence(positions)
    return {'schema': 'a7c2-pixelshift-displacement/1', 'camera_io': False,
            'sources_unchanged': True, 'ordered_files': group['ordered_files'],
            'visible_raw_shape': samples[0][1], 'crop_raw_pixels': crop,
            'alignment_shifts_raw_yx': positions.tolist(),
            'green_sublattice_disagreement_pixels': disagreement,
            'image_evidence_consistent': evidence['consistent_with_one_pixel_square'] and disagreement <= 0.15,
            'grid': evidence,
            'limit': 'Static tripod scene required. Image translation cannot establish actuator identity, calibration or settling.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raws', nargs=4, type=Path)
    parser.add_argument('--crop', default=1024, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    result = measure(args.raws, crop=args.crop)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'ordered_files'}, indent=2))


if __name__ == '__main__':
    main()
