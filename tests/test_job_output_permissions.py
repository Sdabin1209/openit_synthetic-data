"""잡은 이미지 사용자로 실행하고 호스트 작업 그룹이 출력물을 관리할 수 있어야 한다."""
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from synthetic_data import __main__ as cli
from synthetic_data.config import ConfigError


@pytest.mark.parametrize("command,target", [("run", "build_from_config"), ("import", "import_from_config")])
def test_job_outputs_are_group_writable_and_private(tmp_path, command, target):
    directory = tmp_path / "output"
    def build(*args, **kwargs):
        directory.mkdir()
        (directory / "report.json").write_text("{}")
        return SimpleNamespace(status="PUBLISHED")
    old = os.umask(0o022)
    try:
        with patch.object(cli, target, side_effect=build), patch.object(cli, "_result_line", return_value="{}"):
            assert cli.main([command, "--config", str(tmp_path / "config.json")]) == 0
        actual = os.umask(0o022)
        assert actual == 0o022
        assert directory.stat().st_mode & 0o777 == 0o770
        assert (directory / "report.json").stat().st_mode & 0o777 == 0o660
    finally:
        os.umask(old)


def test_job_restores_umask_when_configuration_fails(tmp_path):
    old = os.umask(0o022)
    try:
        with patch.object(cli, "import_from_config", side_effect=ConfigError("invalid")):
            assert cli.main(["import", "--config", str(tmp_path / "config.json")]) == 2
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(old)
