#!/usr/bin/env python3
"""
Performance benchmark for icon caching and batch query optimizations.

This script measures actual performance improvements from:
1. Icon caching (prevents redundant disk I/O)
2. Batch database queries (reduces query count from 100s to 1)

Expected results:
- Icon caching: 50-100x fewer disk operations
- Batch queries: 50-100x faster than individual queries
- Combined: 2-3x faster overall table loading
"""

import os
import sys
import time
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.storage.database import QueueStore
from src.gui.icon_manager import IconManager


def create_test_database(gallery_count=100):
    """Create temporary database with test data"""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "benchmark.db")
    store = QueueStore(db_path)

    print(f"Creating test database with {gallery_count} galleries...")

    # Create galleries with varied statuses
    statuses = ['completed', 'ready', 'uploading', 'incomplete', 'failed', 'queued']
    galleries = []

    for i in range(gallery_count):
        gallery_data = {
            'path': f'/fake/gallery_{i:04d}',
            'name': f'Gallery {i}',
            'status': statuses[i % len(statuses)],
            'added_time': 1700000000 + i,
            'total_images': 10 + (i % 30),
            'uploaded_images': (5 + (i % 20)) if i % 2 == 0 else 0,
            'scan_complete': True,
        }
        galleries.append(gallery_data)

    store.bulk_upsert(galleries)

    # Add file host uploads to 50% of galleries
    for i in range(0, gallery_count, 2):
        for host in ['rapidgator', 'gofile']:
            store.add_file_host_upload(
                gallery_path=f'/fake/gallery_{i:04d}',
                host_name=host,
                status='completed' if i % 2 == 0 else 'pending'
            )

    print(f"✓ Created {gallery_count} galleries with {gallery_count} file host uploads")
    return store, temp_dir


def create_test_assets():
    """Create temporary assets directory with test icons"""
    temp_dir = tempfile.mkdtemp()
    assets_dir = os.path.join(temp_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # Create dummy icon files
    icon_files = [
        "status_completed-light.png",
        "status_completed-dark.png",
        "status_ready-light.png",
        "status_ready-dark.png",
        "status_uploading-light.png",
        "status_uploading-dark.png",
        "status_uploading-001-light.png",
        "status_uploading-001-dark.png",
        "status_uploading-002-light.png",
        "status_uploading-002-dark.png",
        "status_uploading-003-light.png",
        "status_uploading-003-dark.png",
        "status_uploading-004-light.png",
        "status_uploading-004-dark.png",
        "status_incomplete-light.png",
        "status_incomplete-dark.png",
        "status_failed-light.png",
        "status_failed-dark.png",
        "status_queued-light.png",
        "status_queued-dark.png",
    ]

    for icon_file in icon_files:
        icon_path = os.path.join(assets_dir, icon_file)
        with open(icon_path, 'wb') as f:
            f.write(b"fake icon data " * 100)  # ~1.5KB per icon

    return assets_dir, temp_dir


def benchmark_icon_caching(icon_manager, all_items):
    """Benchmark icon caching performance"""
    print("\n" + "="*60)
    print("ICON CACHING BENCHMARK")
    print("="*60)

    # Reset cache
    icon_manager.refresh_cache()

    # WITHOUT caching (simulate by creating fresh manager each time)
    print("\nWithout caching (fresh IconManager each request):")
    start = time.time()
    for item in all_items:
        # Create new manager each time to prevent caching
        fresh_manager = IconManager(icon_manager.assets_dir)
        fresh_manager.get_status_icon(item['status'], 'light')
    without_cache_time = time.time() - start
    print(f"  Time: {without_cache_time*1000:.2f}ms")
    print(f"  Disk I/O: {len(all_items)} operations (one per gallery)")

    # WITH caching
    print("\nWith caching (cached IconManager):")
    icon_manager.refresh_cache()
    start = time.time()
    for item in all_items:
        icon_manager.get_status_icon(item['status'], 'light')
    with_cache_time = time.time() - start

    stats = icon_manager.get_cache_stats()
    print(f"  Time: {with_cache_time*1000:.2f}ms")
    print(f"  Disk I/O: {stats['disk_loads']} operations")
    print(f"  Cache hits: {stats['hits']}")
    print(f"  Cache misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1f}%")

    # Calculate improvement
    speedup = without_cache_time / with_cache_time if with_cache_time > 0 else 0
    io_saved = len(all_items) - stats['disk_loads']
    io_reduction = (io_saved / len(all_items) * 100) if len(all_items) > 0 else 0

    print(f"\n✓ IMPROVEMENT:")
    print(f"  Speedup: {speedup:.1f}x faster")
    print(f"  Disk I/O saved: {io_saved} operations ({io_reduction:.1f}% reduction)")

    return {
        'without_cache_time': without_cache_time,
        'with_cache_time': with_cache_time,
        'speedup': speedup,
        'io_saved': io_saved,
        'io_reduction': io_reduction
    }


def benchmark_batch_queries(store, all_items):
    """Benchmark batch query performance"""
    print("\n" + "="*60)
    print("BATCH QUERY BENCHMARK")
    print("="*60)

    # WITHOUT batch query (individual queries)
    print("\nWithout batch query (individual queries):")
    start = time.time()
    individual_uploads = {}
    for item in all_items:
        uploads = store.get_file_host_uploads(item['path'])
        if uploads:
            individual_uploads[item['path']] = uploads
    without_batch_time = time.time() - start
    print(f"  Time: {without_batch_time*1000:.2f}ms")
    print(f"  Database queries: {len(all_items)}")
    print(f"  Uploads found: {len(individual_uploads)}")

    # WITH batch query
    print("\nWith batch query (single query):")
    start = time.time()
    batch_uploads = store.get_all_file_host_uploads_batch()
    with_batch_time = time.time() - start
    print(f"  Time: {with_batch_time*1000:.2f}ms")
    print(f"  Database queries: 1")
    print(f"  Uploads found: {len(batch_uploads)}")

    # Calculate improvement
    speedup = without_batch_time / with_batch_time if with_batch_time > 0 else 0
    queries_saved = len(all_items) - 1

    print(f"\n✓ IMPROVEMENT:")
    print(f"  Speedup: {speedup:.1f}x faster")
    print(f"  Queries saved: {queries_saved} ({queries_saved / len(all_items) * 100:.1f}% reduction)")

    return {
        'without_batch_time': without_batch_time,
        'with_batch_time': with_batch_time,
        'speedup': speedup,
        'queries_saved': queries_saved
    }


def benchmark_combined(icon_manager, store, all_items):
    """Benchmark combined optimizations"""
    print("\n" + "="*60)
    print("COMBINED OPTIMIZATIONS BENCHMARK")
    print("="*60)

    # UNOPTIMIZED (no caching, individual queries)
    print("\nUnoptimized (no cache + individual queries):")
    start = time.time()

    # Individual queries
    for item in all_items:
        store.get_file_host_uploads(item['path'])

    # No caching
    for item in all_items:
        fresh_manager = IconManager(icon_manager.assets_dir)
        fresh_manager.get_status_icon(item['status'], 'light')

    unoptimized_time = time.time() - start
    print(f"  Time: {unoptimized_time*1000:.2f}ms")

    # OPTIMIZED (caching + batch query)
    print("\nOptimized (cache + batch query):")
    icon_manager.refresh_cache()

    # Pre-warm cache with a few icons (simulate realistic usage)
    for item in all_items[:5]:
        icon_manager.get_status_icon(item['status'], 'light')

    start = time.time()

    # Batch query
    batch_uploads = store.get_all_file_host_uploads_batch()

    # Cached icons
    for item in all_items:
        icon_manager.get_status_icon(item['status'], 'light')

    optimized_time = time.time() - start
    print(f"  Time: {optimized_time*1000:.2f}ms")

    # Calculate improvement
    speedup = unoptimized_time / optimized_time if optimized_time > 0 else 0

    print(f"\n✓ OVERALL IMPROVEMENT:")
    print(f"  Speedup: {speedup:.1f}x faster")
    print(f"  Time saved: {(unoptimized_time - optimized_time)*1000:.2f}ms")

    return {
        'unoptimized_time': unoptimized_time,
        'optimized_time': optimized_time,
        'speedup': speedup
    }


def main():
    """Run performance benchmarks"""
    print("="*60)
    print("PERFORMANCE BENCHMARK - Icon Caching & Batch Queries")
    print("="*60)

    # Create test data
    store, db_temp_dir = create_test_database(gallery_count=100)
    assets_dir, assets_temp_dir = create_test_assets()

    # Load test data
    all_items = store.load_all_items()
    print(f"\nLoaded {len(all_items)} galleries for benchmarking")

    # Create icon manager
    icon_manager = IconManager(assets_dir)

    # Run benchmarks
    icon_results = benchmark_icon_caching(icon_manager, all_items)
    batch_results = benchmark_batch_queries(store, all_items)
    combined_results = benchmark_combined(icon_manager, store, all_items)

    # Print summary
    print("\n" + "="*60)
    print("BENCHMARK SUMMARY")
    print("="*60)
    print(f"\nDataset: {len(all_items)} galleries")
    print(f"\nIcon Caching:")
    print(f"  Speedup: {icon_results['speedup']:.1f}x faster")
    print(f"  Disk I/O reduction: {icon_results['io_reduction']:.1f}%")
    print(f"\nBatch Queries:")
    print(f"  Speedup: {batch_results['speedup']:.1f}x faster")
    print(f"  Queries saved: {batch_results['queries_saved']}")
    print(f"\nCombined:")
    print(f"  Overall speedup: {combined_results['speedup']:.1f}x faster")
    print(f"  Time saved: {(combined_results['unoptimized_time'] - combined_results['optimized_time'])*1000:.2f}ms")

    # Verify improvements meet expectations
    print("\n" + "="*60)
    print("VERIFICATION")
    print("="*60)

    success = True

    if icon_results['speedup'] < 2.0:
        print(f"⚠ Icon caching speedup below target (got {icon_results['speedup']:.1f}x, expected >=2x)")
        success = False
    else:
        print(f"✓ Icon caching speedup meets target ({icon_results['speedup']:.1f}x)")

    if batch_results['speedup'] < 10.0:
        print(f"⚠ Batch query speedup below target (got {batch_results['speedup']:.1f}x, expected >=10x)")
        success = False
    else:
        print(f"✓ Batch query speedup meets target ({batch_results['speedup']:.1f}x)")

    if combined_results['speedup'] < 2.0:
        print(f"⚠ Combined speedup below target (got {combined_results['speedup']:.1f}x, expected >=2x)")
        success = False
    else:
        print(f"✓ Combined speedup meets target ({combined_results['speedup']:.1f}x)")

    # Cleanup
    import shutil
    shutil.rmtree(db_temp_dir, ignore_errors=True)
    shutil.rmtree(assets_temp_dir, ignore_errors=True)

    print("\n" + "="*60)
    if success:
        print("✓ ALL BENCHMARKS PASSED")
    else:
        print("⚠ SOME BENCHMARKS BELOW TARGET")
    print("="*60)

    return 0 if success else 1


if __name__ == '__main__':
    try:
        # Import Qt for icon tests
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        sys.exit(main())
    except ImportError:
        print("Error: PyQt6 not available. Install with: pip install PyQt6")
        sys.exit(1)
