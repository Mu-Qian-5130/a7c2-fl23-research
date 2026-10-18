"""Slot ownership and explicit ST-only import contracts."""
import json
from pathlib import Path

from .references import Cube, DcpLook
from .calibration import validate, inverse_st


def load(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != "a7c2-look-project/1" or data.get("model") != "ILCE-7CM2" or data.get("firmware") != "2.01":
        raise ValueError("Only ILCE-7CM2 2.01 project schema 1 is supported")
    slots = data.get("slots")
    if not isinstance(slots,list) or not 1 <= len(slots) <= 6:
        raise ValueError("Assign one to six custom slots")
    seen = set()
    for entry in slots:
        slot, name = entry.get("slot"), entry.get("name")
        if type(slot) is not int or slot not in range(1,7) or slot in seen:
            raise ValueError("Slot IDs must be distinct integers 1..6")
        seen.add(slot)
        if not isinstance(name,str) or not name.strip() or len(name.encode("utf-8")) > 63 or any(ord(c) < 32 for c in name):
            raise ValueError("Names need 1..63 UTF-8 bytes and no control characters")
        if entry.get("base") != "ST":
            raise ValueError("Every imported slot must explicitly require base ST")
        source = entry.get("source",{})
        if source.get("type") not in ("dcp","cube") or not source.get("path"):
            raise ValueError("Each slot needs a DCP or cube source path")
        if not source.get("attribution"):
            raise ValueError("Record source attribution/license or user provenance")
        if source["type"] == "cube" and source.get("input_space") != "sony-st-srgb" and not source.get("bridge"):
            raise ValueError("A non-ST cube needs an explicit Sony-ST-to-LUT-input bridge cube")
        if source["type"] == "cube" and source.get("output_space") != "srgb":
            raise ValueError("Normalize cube output to sRGB before fitting")
    data["slots"] = sorted(slots,key=lambda item:item["slot"])
    return data, path.parent


def slot_plan(data):
    selected = [x["slot"] for x in data["slots"]]
    return {"schema":"a7c2-slot-plan/1","model":data["model"],"firmware":data["firmware"],
            "selected_slots":selected,"preserve_slots":[x for x in range(1,7) if x not in selected],
            "assignments":[{"slot":x["slot"],"name":x["name"],"required_base":"ST","selector":x["slot"]+9} for x in data["slots"]],
            "binding_policy":"provision and verify ST for every imported slot; reject a mismatched binding",
            "camera_menu_base_picker_locked":False,
            "adapter_capacities":{"three-preview-v2":3,"full7-v4":6},
            "camera_source_fingerprints_required":True,"plan_is_not_live_installation_evidence":True,
            "FL_FL2_FL3":"preserve"}


def check_bindings(plan, bindings):
    bad = []
    for slot in plan["selected_slots"]:
        value = bindings.get(str(slot))
        if value != "ST":
            bad.append({"slot":slot,"actual":value,"required":"ST"})
    if bad:
        raise ValueError("Imported slots must use ST: "+json.dumps(bad))
    return True


def reference(entry, base, calibration):
    source = entry["source"]
    path = base/source["path"]
    if source["type"] == "dcp":
        validate(calibration,True)
        profile = DcpLook(path)
        stops = float(source.get("exposure_stops",0))
        if not -8 <= stops <= 8:
            raise ValueError("Invalid DCP exposure convention")
        return lambda rgb:profile.render(inverse_st(rgb,calibration),stops),profile.inventory()
    cube = Cube(path)
    if source.get("input_space") == "sony-st-srgb":
        if source.get("bridge"):
            raise ValueError("Direct ST cube must not also specify a bridge")
        return cube.sample,{"sha256":cube.sha256,"input_space":"sony-st-srgb","output_space":"srgb"}
    bridge = source.get("bridge",{})
    if bridge.get("input_space") != "sony-st-srgb" or bridge.get("output_space") != source.get("input_space") or not bridge.get("evidence"):
        raise ValueError("Bridge spaces and evidence must match the target LUT contract")
    transform = Cube(base/bridge["path"])
    return lambda rgb:cube.sample(transform.sample(rgb)),{"sha256":cube.sha256,"bridge_sha256":transform.sha256,"bridge_evidence":bridge["evidence"]}
