from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "44_akerdrift_fast_v1.py"

try:
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import box
    HAS_GIS = True
except ImportError:
    HAS_GIS = False


@unittest.skipUnless(HAS_GIS, "GIS-testberoenden saknas")
class AkerdriftFastRunnerTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments], cwd=ROOT,
            text=True, capture_output=True, env=os.environ.copy(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return result

    def test_lomma_three_municipalities_resume_merge_and_cheap_qa(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            raw = work / "raw"
            derived = work / "derived"
            hydro = work / "hydro"
            raw.mkdir()
            derived.mkdir()
            hydro.mkdir()

            municipalities = [
                ("Lomma", "1262", "12620001", 100.0),
                ("Kävlinge", "1261", "12610001", 300.0),
                ("Eslöv", "1285", "12850001", 500.0),
            ]
            blocks = []
            fields = []
            geometry_rows = []
            for municipality, code, block_id, x0 in municipalities:
                block_geometry = box(x0, 100.0, x0 + 160.0, 260.0)
                field_geometry = box(x0 + 20.0, 120.0, x0 + 140.0, 240.0)
                blocks.append({"blockid": block_id, "region_kod": code, "geometry": block_geometry})
                fields.append({"blockid": block_id, "skiftesbeteckning": "A", "geometry": field_geometry})
                geometry_rows.append({
                    "kommun": municipality, "blockid": block_id, "skiftesbeteckning": "A",
                    "rectangularity": 1.0, "convexity": 1.0,
                    "compactness_4piA_P2": 0.785, "mbr_aspect_ratio": 1.0,
                    "erl_proxy_m": 120.0,
                })
            blocks_path = raw / "blocks.gpkg"
            fields_path = raw / "fields.gpkg"
            gpd.GeoDataFrame(blocks, crs=3006).to_file(blocks_path, driver="GPKG")
            gpd.GeoDataFrame(fields, crs=3006).to_file(fields_path, driver="GPKG")
            import pandas as pd
            pd.DataFrame(geometry_rows).to_csv(derived / "geometry_v1a_skiften.csv", index=False)

            transform = from_origin(0.0, 400.0, 10.0, 10.0)
            slope = np.full((40, 80), 4.0, dtype="float32")
            slope[:, 40:] = 10.0
            twi = np.full((40, 80), 10.0, dtype="float32")
            twi[15:20, :] = 16.0
            for path, values in ((hydro / "slope_10m_deg.tif", slope), (hydro / "twi_10m.tif", twi)):
                with rasterio.open(
                    path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
                    count=1, dtype="float32", crs="EPSG:3006", transform=transform, nodata=-9999.0,
                ) as dataset:
                    dataset.write(values, 1)

            config = work / "local_paths.json"
            config.write_text(json.dumps({
                "blocks": str(blocks_path), "skiften": str(fields_path),
                "whitebox_work_dir": str(hydro), "build_dir": str(derived),
            }), encoding="utf-8")
            common = ["--config", str(config)]

            first = self.run_cli("run", "--kommun", "Lomma", *common)
            self.assertIn("DONE Lomma", first.stdout)
            lomma_parquet = derived / "akerdrift_fast_v1" / "by_municipality" / "lomma.parquet"
            lomma_done = derived / "akerdrift_fast_v1" / "checkpoints" / "lomma.done.json"
            self.assertTrue(lomma_parquet.exists())
            self.assertTrue(lomma_done.exists())
            done = json.loads(lomma_done.read_text(encoding="utf-8"))
            self.assertEqual(done["n_input"], 1)
            self.assertEqual(done["n_scored"], 1)
            before = lomma_parquet.stat().st_mtime_ns

            second = self.run_cli(
                "run", "--kommun", "Lomma", "--kommun", "Kävlinge", "--kommun", "Eslöv", *common,
            )
            self.assertIn("SKIP Lomma: valid checkpoint", second.stdout)
            self.assertIn("DONE Kävlinge", second.stdout)
            self.assertIn("DONE Eslöv", second.stdout)
            self.assertEqual(before, lomma_parquet.stat().st_mtime_ns)

            third = self.run_cli(
                "run", "--kommun", "Lomma,Kävlinge,Eslöv", *common,
            )
            self.assertIn("3 återanvända checkpoints", third.stdout)
            self.assertEqual(before, lomma_parquet.stat().st_mtime_ns)

            self.run_cli("merge", "--allow-partial", *common)
            global_path = derived / "akerdrift_fast_v1" / "akerdrift_fast_v1_skane.parquet"
            merged = pd.read_parquet(global_path)
            self.assertEqual(len(merged), 3)
            self.assertTrue(merged["akerdrift_score"].between(0, 100).all())
            self.assertTrue((merged["drift_twi_status"] == "OK").all())

            self.run_cli("qa", *common)
            self.run_cli("sensitivity", *common)
            self.assertTrue((derived / "akerdrift_fast_v1" / "qa" / "qa_summary.json").exists())
            self.assertTrue((derived / "akerdrift_fast_v1" / "sensitivity" / "sensitivity_summary.csv").exists())


if __name__ == "__main__":
    unittest.main()
