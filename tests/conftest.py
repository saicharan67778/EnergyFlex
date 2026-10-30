import pytest

from energyflex.analytics import pipeline
from energyflex.export import write_dataset
from energyflex.generate import generate


@pytest.fixture(scope="session")
def starter(tmp_path_factory):
    root = tmp_path_factory.mktemp("starter")
    tables, gt, meta = generate("starter")
    manifest = write_dataset(tables, gt, meta, root / "data")
    res = pipeline.run(root / "data", root / "out")
    return {"root": root, "data": root / "data", "out": root / "out", "manifest": manifest, "res": res,
            "tables": tables, "gt": gt}
