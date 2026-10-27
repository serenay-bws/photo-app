"""Zet het officiële Real-ESRGAN model `realesr-general-x4v3.pth` om naar ONNX.

Dit script is alleen nodig voor de ontwikkelaar; het resultaat
(app/models/realesr-general-x4v3.onnx) zit al in de repository.

Het werkt zonder PyTorch: de .pth-gewichten worden direct uit het
zip/pickle-formaat gelezen en het netwerk (SRVGGNetCompact) wordt met de
`onnx`-bibliotheek opgebouwd.

Gebruik:
    uv pip install onnx
    uv run python tools/convert_model.py realesr-general-x4v3.pth app/models/realesr-general-x4v3.onnx

Bron van het model:
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth
"""

import pickle
import sys
import zipfile

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

DTYPES = {
    "FloatStorage": np.float32,
    "HalfStorage": np.float16,
    "DoubleStorage": np.float64,
    "LongStorage": np.int64,
}


def load_pth(path):
    zf = zipfile.ZipFile(path)
    pkl_name = next(n for n in zf.namelist() if n.endswith("data.pkl"))
    prefix = pkl_name[: -len("data.pkl")]

    class StorageType:
        def __init__(self, name):
            self.dtype = DTYPES[name]

    def rebuild_tensor(storage, offset, size, stride, *_args):
        if not size:
            return storage[offset : offset + 1].reshape(())
        item = storage.itemsize
        return np.lib.stride_tricks.as_strided(
            storage[offset:], shape=size, strides=[s * item for s in stride]
        ).copy()

    class Unpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if module == "torch._utils" and name == "_rebuild_tensor_v2":
                return rebuild_tensor
            if module == "torch" and name.endswith("Storage"):
                return StorageType(name)
            if module == "collections" and name == "OrderedDict":
                import collections

                return collections.OrderedDict
            raise pickle.UnpicklingError(f"niet toegestaan: {module}.{name}")

        def persistent_load(self, pid):
            _, storage_type, key, _location, _numel = pid
            raw = zf.read(f"{prefix}data/{key}")
            return np.frombuffer(raw, dtype=storage_type.dtype)

    return Unpickler(zf.open(pkl_name)).load()


def build_onnx(params, scale=4):
    nodes, inits = [], []
    convs = sorted(
        {int(k.split(".")[1]) for k in params if k.endswith(".weight") and params[k].ndim == 4}
    )
    prev = "input"
    for i, idx in enumerate(convs):
        w, b = params[f"body.{idx}.weight"], params[f"body.{idx}.bias"]
        inits += [
            numpy_helper.from_array(w.astype(np.float32), f"w{idx}"),
            numpy_helper.from_array(b.astype(np.float32), f"b{idx}"),
        ]
        out = f"conv{idx}"
        nodes.append(
            helper.make_node(
                "Conv", [prev, f"w{idx}", f"b{idx}"], [out], pads=[1, 1, 1, 1],
                kernel_shape=[3, 3], strides=[1, 1], dilations=[1, 1], group=1,
            )
        )
        prev = out
        act_key = f"body.{idx + 1}.weight"
        if i < len(convs) - 1:
            slope = params[act_key].astype(np.float32).reshape(-1, 1, 1)
            inits.append(numpy_helper.from_array(slope, f"a{idx}"))
            nodes.append(helper.make_node("PRelu", [prev, f"a{idx}"], [f"act{idx}"]))
            prev = f"act{idx}"

    nodes.append(helper.make_node("DepthToSpace", [prev], ["up"], blocksize=scale, mode="CRD"))
    inits.append(numpy_helper.from_array(np.array([1, 1, scale, scale], np.float32), "scales"))
    nodes.append(
        helper.make_node("Resize", ["input", "", "scales"], ["base"], mode="nearest")
    )
    nodes.append(helper.make_node("Add", ["up", "base"], ["output"]))

    graph = helper.make_graph(
        nodes,
        "realesr-general-x4v3",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, "h", "w"])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, "H", "W"])],
        inits,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def main():
    src, dst = sys.argv[1], sys.argv[2]
    ckpt = load_pth(src)
    params = ckpt.get("params_ema") or ckpt.get("params") or ckpt
    model = build_onnx(params)
    onnx.save(model, dst)
    print(f"Opgeslagen: {dst}")


if __name__ == "__main__":
    main()
