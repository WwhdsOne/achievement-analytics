"""报告接口、静态资源白名单与错误状态的HTTP测试。"""

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from dashboard import app


@pytest.fixture
def server():
    """启动临时HTTP服务，不连接云库。"""
    instance = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    thread.join()
    instance.server_close()


def test_missing_report_is_explained_without_database_access(server, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "REPORT_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(app, "get_engine", lambda: pytest.fail("不应连接数据库"))
    with pytest.raises(HTTPError) as exc:
        urlopen(server + "/api/analysis")
    assert exc.value.code == 503
    assert "尚未生成" in json.load(exc.value)["error"]


def test_report_and_assets_are_available_without_database(server, tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text('{"version":"test"}', encoding="utf-8")
    monkeypatch.setattr(app, "REPORT_PATH", path)
    monkeypatch.setattr(app, "get_engine", lambda: pytest.fail("不应连接数据库"))
    with urlopen(server + "/api/analysis") as response:
        assert json.load(response) == {"version": "test"}
    with urlopen(server + "/assets/analysis.js") as response:
        assert response.status == 200
        assert "javascript" in response.headers["Content-Type"]
    with pytest.raises(HTTPError) as exc:
        urlopen(server + "/assets/../../.env")
    assert exc.value.code == 404
