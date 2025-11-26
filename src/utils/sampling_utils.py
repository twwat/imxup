#!/usr/bin/env python3
"""
Image sampling utilities for dimension calculations.
Single source of truth for sampling logic used by both queue_manager and engine.
"""

import os
import fnmatch
from typing import List, Dict, Any, Tuple
from PIL import Image


def get_sample_indices(files: List[str], config: Dict[str, Any], folder_path: str | None = None) -> List[int]:
    """
    Get indices of files to sample based on configuration.

    Args:
        files: List of image filenames
        config: Sampling configuration dictionary
        folder_path: Optional folder path for size-based exclusions

    Returns:
        List of indices to sample
    """
    if not files:
        return []

    total = len(files)
    available_indices = list(range(total))

    # Apply exclusions first
    excluded_indices = set()

    # 1. Exclude first image
    if config.get('exclude_first', False) and total > 1:
        excluded_indices.add(0)

    # 2. Exclude last image
    if config.get('exclude_last', False) and total > 1:
        excluded_indices.add(total - 1)

    # 3. Exclude by filename patterns
    if config.get('exclude_patterns', False):
        patterns_text = config.get('exclude_patterns_text', '')
        if patterns_text:
            patterns = [p.strip() for p in patterns_text.split(',') if p.strip()]
            for i, filename in enumerate(files):
                if any(fnmatch.fnmatch(filename.lower(), pattern.lower()) for pattern in patterns):
                    excluded_indices.add(i)

    # 4. Exclude small images (requires PIL check if folder_path provided)
    if config.get('exclude_small_images', False) and folder_path:
        threshold_percent = config.get('exclude_small_threshold', 50) / 100.0
        # First pass: find the largest image dimensions
        max_size = 0
        sizes = []
        for filename in files:
            try:
                filepath = os.path.join(folder_path, filename)
                with Image.open(filepath) as img:
                    size = img.size[0] * img.size[1]  # area
                    sizes.append(size)
                    max_size = max(max_size, size)
            except:
                sizes.append(0)

        # Exclude images smaller than threshold
        if max_size > 0:
            min_size = max_size * threshold_percent
            for i, size in enumerate(sizes):
                if size < min_size:
                    excluded_indices.add(i)

    # Get available indices after exclusions
    available_indices = [i for i in available_indices if i not in excluded_indices]

    if not available_indices:
        # If all excluded, return at least the middle image
        return [total // 2]

    # Apply sampling method
    sampling_method = config.get('sampling_method', 0)  # 0=fixed, 1=percentage

    if sampling_method == 0:  # Fixed count
        count = config.get('sampling_fixed_count', 25)
        count = min(count, len(available_indices))
    else:  # Percentage
        percentage = config.get('sampling_percentage', 10) / 100.0
        count = max(1, int(len(available_indices) * percentage))
        count = min(count, len(available_indices))

    # Distribute samples evenly across available indices
    if count >= len(available_indices):
        return available_indices

    # Strategic sampling: include first, last, and distribute the rest
    sampled = []
    if len(available_indices) <= count:
        sampled = available_indices
    else:
        # Always include first and last of available
        sampled = [available_indices[0], available_indices[-1]]
        count -= 2

        if count > 0:
            # Distribute remaining samples evenly
            step = (len(available_indices) - 2) / (count + 1)
            for i in range(count):
                idx = int((i + 1) * step)
                if available_indices[idx] not in sampled:
                    sampled.append(available_indices[idx])

    return sorted(set(sampled))


def calculate_dimensions_with_outlier_exclusion(
    dimensions: List[Tuple[int, int]],
    exclude_outliers: bool = False,
    use_median: bool = False
) -> Dict[str, float]:
    """
    Calculate dimension statistics, optionally excluding outliers.

    Args:
        dimensions: List of (width, height) tuples
        exclude_outliers: Whether to exclude outliers using IQR method
        use_median: Whether to use median instead of mean for averages

    Returns:
        Dictionary with avg_width, avg_height, min_width, min_height, max_width, max_height
    """
    if not dimensions:
        return {
            'avg_width': 0.0, 'avg_height': 0.0,
            'min_width': 0.0, 'min_height': 0.0,
            'max_width': 0.0, 'max_height': 0.0
        }

    widths = [w for w, h in dimensions]
    heights = [h for w, h in dimensions]

    if exclude_outliers and len(dimensions) > 4:
        # Calculate IQR for both dimensions
        def remove_outliers(values):
            sorted_vals = sorted(values)
            q1_idx = len(sorted_vals) // 4
            q3_idx = 3 * len(sorted_vals) // 4
            q1 = sorted_vals[q1_idx]
            q3 = sorted_vals[q3_idx]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            return [v for v in values if lower_bound <= v <= upper_bound]

        filtered_widths = remove_outliers(widths)
        filtered_heights = remove_outliers(heights)

        # Calculate average based on method
        if use_median:
            sorted_w = sorted(filtered_widths)
            sorted_h = sorted(filtered_heights)
            avg_width = sorted_w[len(sorted_w) // 2] if sorted_w else 0
            avg_height = sorted_h[len(sorted_h) // 2] if sorted_h else 0
        else:
            avg_width = sum(filtered_widths) / len(filtered_widths) if filtered_widths else 0
            avg_height = sum(filtered_heights) / len(filtered_heights) if filtered_heights else 0
    else:
        # Calculate average based on method
        if use_median:
            sorted_w = sorted(widths)
            sorted_h = sorted(heights)
            avg_width = sorted_w[len(sorted_w) // 2] if sorted_w else 0
            avg_height = sorted_h[len(sorted_h) // 2] if sorted_h else 0
        else:
            avg_width = sum(widths) / len(widths)
            avg_height = sum(heights) / len(heights)

    return {
        'avg_width': float(avg_width),
        'avg_height': float(avg_height),
        'min_width': float(min(widths)),
        'min_height': float(min(heights)),
        'max_width': float(max(widths)),
        'max_height': float(max(heights))
    }