from __future__ import annotations

import io
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import rasterio
from affine import Affine
from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import rapskartan_pixel_reference_core as core
from rapskartan_s2_pilot_core import stat_evalscript


def frozen_contract():
    from rapskartan_model_core import load_model_contract
    return load_model_contract(ROOT)


def plan(count=5):
    cases = [{"case_id": f"case_{i:02d}", "acquisition_date": "2025-04-20"} for i in range(1,count+1)]
    geometries = {c["case_id"]: {"crs": "EPSG:32633", "geometry": mapping(box(10,10,30,30))} for c in cases}
    return core.build_plan(cases, geometries, frozen_contract())


def response(record):
    w,h=record["payload"]["output"]["width"],record["payload"]["output"]["height"]
    with rasterio.MemoryFile() as memory:
        with memory.open(driver="GTiff", width=w, height=h, count=len(record["bands"]), dtype="float32",
                         crs=32633, transform=Affine(*record["expected_transform"])) as image:
            image.write(np.zeros((len(record["bands"]),h,w),dtype="float32"))
        tiff=memory.read()
    parts={"default.tif":tiff,"userdata.json":json.dumps({"mode":record["mode"],"tiles":[]}).encode()}
    return tar_bytes(parts)


def tar_bytes(parts):
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode="w") as archive:
        for name,data in parts.items():
            info=tarfile.TarInfo(name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
    return buffer.getvalue()


class ReferenceTests(unittest.TestCase):
    def test_plan_is_ten_bounded_process_requests(self):
        requests=plan()
        self.assertEqual(len(requests),10)
        self.assertEqual(len(set(r["id"] for r in requests)),10)
        for record in requests:
            self.assertEqual(record["endpoint"],core.PROCESS_URL)
            self.assertEqual(record["payload"]["input"]["data"][0]["dataFilter"]["mosaickingOrder"],"leastCC")
            self.assertTrue(record["payload"]["input"]["data"][0]["processing"]["harmonizeValues"])
            self.assertEqual(record["payload"]["output"]["width"],2)
        self.assertEqual(len(requests[0]["bands"]),21)
        self.assertEqual(len(requests[1]["bands"]),104)
        with self.assertRaisesRegex(RuntimeError,"one to five"):
            plan(6)

    def test_primary_javascript_preserves_frozen_formula_results(self):
        frozen=frozen_contract();primary,tiles=core.scripts(frozen)
        original=stat_evalscript(frozen)
        data={"original":original,"primary":primary,"tiles":tiles}
        code=r'''
const vm=require('vm');let raw='';process.stdin.on('data',x=>raw+=x);
process.stdin.on('end',()=>{
const scripts=JSON.parse(raw);const contexts={};
for(const [key,value] of Object.entries(scripts)){contexts[key]=vm.createContext({});vm.runInContext(value,contexts[key]);}
for(const scl of [0,2,4,5,8,9]) for(const mask of [0,1]){
 const s={B02:.02,B03:.1,B04:.03,B05:.12,B06:.2,B07:.3,B08:.4,B8A:.45,B11:.25,B12:.2,CLD:30,SCL:scl,dataMask:mask};
 const a=contexts.original.evaluatePixel(s),b=contexts.primary.evaluatePixel(s);
 if(JSON.stringify(a.default)!==JSON.stringify(b.slice(0,18))) throw Error('spectral formulas changed');
 if(b[18]!==scl||b[19]!==mask||b[20]!==a.dataMask[0])throw Error('mask changed');
 const values=contexts.tiles.evaluatePixel([s,s]);if(values.length!==104||values[12]!==mask||values[25]!==mask)throw Error('tile layout');
}
if(contexts.primary.setup().mosaicking!=='SIMPLE')throw Error('wrong primary mosaicking');
if(contexts.tiles.setup().mosaicking!=='TILE')throw Error('wrong diagnostic mosaicking');
let rejected=false;try{contexts.tiles.preProcessScenes({scenes:{tiles:Array(9).fill({})}});}catch(e){rejected=true;}
if(!rejected)throw Error('tile cap missing');
});'''
        # Node is a developer test helper, not a Windows runtime requirement.
        import shutil
        node=shutil.which("node")
        if node is None:
            self.skipTest("Node not installed; JS-equivalence test runs in development")
        result=subprocess.run([node,"-e",code],input=json.dumps(data),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cache_reuses_all_ten_responses_without_transport(self):
        requests=plan()
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/"cache";cache=core.BudgetCache(folder,requests)
            transport=Mock(return_value=(b"saved response",{"content-type":"application/tar","authorization":"SECRET"}))
            for record in requests:cache.fetch(record,transport)
            self.assertEqual(transport.call_count,10)
            second=core.BudgetCache(folder,requests)
            self.assertEqual(second.pending(),[])
            for record in requests:second.fetch(record,transport)
            self.assertEqual(transport.call_count,10)
            self.assertEqual(len(second.state["attempts"]),10)
            self.assertEqual(second.hits,10)
            self.assertFalse(any(b"SECRET" in p.read_bytes() for p in folder.rglob("*") if p.is_file()))

    def test_failed_attempt_is_reserved_and_never_retried(self):
        requests=plan(1)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/"cache";cache=core.BudgetCache(folder,requests)
            def fail(endpoint,payload):
                state=json.loads((folder/"request_budget.json").read_text())
                self.assertEqual(len(state["attempts"]),1)
                raise TimeoutError()
            with self.assertRaises(TimeoutError):cache.fetch(requests[0],fail)
            resumed=core.BudgetCache(folder,requests)
            transport=Mock()
            with self.assertRaisesRegex(RuntimeError,"No automatic retry"):
                resumed.fetch(requests[0],transport)
            transport.assert_not_called()

    def test_changed_plan_or_lost_ledger_cannot_reset_budget(self):
        requests=plan(1)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/"cache";core.BudgetCache(folder,requests)
            changed=plan(2)
            with self.assertRaisesRegex(RuntimeError,"cannot be reset"):
                core.BudgetCache(folder,changed)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/"untracked_response").write_bytes(b"x")
            with self.assertRaisesRegex(RuntimeError,"without budget"):
                core.BudgetCache(folder,requests)

    def test_corrupt_cache_blocks_before_network(self):
        requests=plan(1)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/"cache";cache=core.BudgetCache(folder,requests)
            cache.fetch(requests[0],lambda *args:(b"original",{}))
            (folder/requests[0]["id"]/"response.tar").write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError,"checksum mismatch"):
                core.BudgetCache(folder,requests).pending()

    def test_lock_blocks_parallel_runs_without_deleting_other_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with core.run_lock(folder):
                with self.assertRaisesRegex(RuntimeError,"lock exists"):
                    with core.run_lock(folder):pass
                self.assertTrue((folder/"reference_run.lock").exists())
            self.assertFalse((folder/"reference_run.lock").exists())

    def test_transport_rejects_redirects_and_wrong_endpoints(self):
        with self.assertRaisesRegex(RuntimeError,"redirect blocked"):
            core.NoRedirect().redirect_request(None,None,302,None,None,"https://elsewhere.test")
        client=core.Transport();client.token="SECRET"
        client._post=Mock()
        with self.assertRaisesRegex(RuntimeError,"Unapproved"):
            client("https://elsewhere.test",{})
        client._post.assert_not_called()

    def test_http_failure_does_not_retry_or_log_secret_body(self):
        import urllib.error
        client=core.Transport();client.token="SECRET"
        client.opener=Mock()
        client.opener.open.side_effect=urllib.error.HTTPError(core.PROCESS_URL,429,"SECRET",{},io.BytesIO(b"SECRET"))
        with self.assertRaisesRegex(RuntimeError,"HTTP 429") as caught:
            client(core.PROCESS_URL,{})
        self.assertNotIn("SECRET",str(caught.exception))
        self.assertEqual(client.opener.open.call_count,1)

    def test_missing_credentials_prevent_login(self):
        client=core.Transport();client._post=Mock()
        with patch.dict(os.environ,{"CDSE_CLIENT_ID":"","CDSE_CLIENT_SECRET":""}):
            with self.assertRaisesRegex(RuntimeError,"locally"):
                client.authenticate()
        client._post.assert_not_called()

    def test_safe_unpack_checks_layout_and_rejects_traversal(self):
        record=plan(1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            report=core.unpack_response(response(record),folder/"good",record)
            self.assertTrue(report["grid_matches_local"])
            self.assertEqual(report["bands"],core.PRIMARY_BANDS)
            bad=tar_bytes({"../escape":b"x","userdata.json":b"{}"})
            with self.assertRaisesRegex(RuntimeError,"archive members"):
                core.unpack_response(bad,folder/"bad",record)
            self.assertFalse((folder/"escape").exists())
            wrong=plan(1)[1]
            with self.assertRaisesRegex(RuntimeError,"shape/bands"):
                core.unpack_response(response(record),folder/"wrong",wrong)

    def test_main_packages_hashed_outputs_without_lock_or_secrets(self):
        spec=importlib.util.spec_from_file_location("reference_main_test",ROOT/"src/104_fetch_rapskartan_reference_pixels.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);out=base/"output"
            def fake_run(args,folder):
                self.assertTrue((folder/"reference_run.lock").is_file())
                core.atomic_json(folder/"reference_summary.json",{"status":"REFERENCE_PIXELS_COMPLETE"})
                print("TEST REFERENCE COMPLETE")
            argv=["reference","--output-dir",str(out),"--pixel-dir",str(base/"pixels"),
                  "--stop-c-dir",str(base/"stop_c"),"--stop-d-dir",str(base/"stop_d")]
            with patch.object(sys,"argv",argv),patch.object(module,"run",side_effect=fake_run):
                self.assertEqual(module.main(),0)
            self.assertFalse((out/"reference_run.lock").exists())
            packages=list(out.glob("*.zip"));self.assertEqual(len(packages),1)
            with zipfile.ZipFile(packages[0]) as archive:
                self.assertIsNone(archive.testzip())
                self.assertFalse(any(name.endswith(".lock") for name in archive.namelist()))
                manifest=json.loads(archive.read("reference_manifest.json"))
                for record in manifest["artifacts"]:
                    self.assertEqual(core.sha256_bytes(archive.read(record["path"])),record["sha256"])
                log=next(name for name in archive.namelist() if name.endswith(".log"))
                self.assertIn(b"TEST REFERENCE COMPLETE",archive.read(log))


if __name__ == "__main__":
    unittest.main()
