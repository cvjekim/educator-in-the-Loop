"""Serverless Python dependencies may live outside the standard site-packages."""
from apps.api.normalized import worker,service


def test_child_processes_can_import_vendored_dependencies(tmp_path,monkeypatch):
    root=tmp_path/'runtime';api=root/'apps'/'api';api.mkdir(parents=True)
    vendor=tmp_path/'vendor';vendor.mkdir()
    (vendor/'synthetic_dependency.py').write_text('VALUE="available"')
    monkeypatch.syspath_prepend(str(vendor))
    monkeypatch.setattr(worker,'ROOT',root);monkeypatch.setattr(service,'ROOT',root)
    (api/'legacy_runner.py').write_text('import json\nfrom synthetic_dependency import VALUE\nprint(json.dumps({"draft":{"dependency":VALUE}}))')
    (api/'parse_document.py').write_text('import json\nfrom synthetic_dependency import VALUE\nprint(json.dumps({"pages":[VALUE]}))')
    assert worker.invoke({})['draft']['dependency']=='available'
    assert service.parse_file('synthetic.txt',b'content')['pages']==['available']
