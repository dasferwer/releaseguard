import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.skipif(
    shutil.which("helm") is None, reason="Helm-render проверяется в CI с setup-helm"
)
@pytest.mark.parametrize("override", [None, "custom-control-plane"])
def test_rendered_controllers_service_and_hpa_select_only_their_api(override):
    chart = Path(__file__).resolve().parents[1] / "deploy/helm/releaseguard"
    command = ["helm", "template", "selector-test", str(chart), "--set", "autoscaling.enabled=true"]
    if override:
        command += ["--set", "fullnameOverride=" + override]
    output = subprocess.check_output(command, text=True)
    objects = list(yaml.safe_load_all(output))
    deployments = [obj for obj in objects if obj and obj["kind"] == "Deployment"]
    assert len(deployments) == 2
    api, reconciler = sorted(
        deployments, key=lambda obj: obj["metadata"]["name"].endswith("-reconciler")
    )
    api_selector = api["spec"]["selector"]["matchLabels"]
    reconciler_selector = reconciler["spec"]["selector"]["matchLabels"]
    api_labels = api["spec"]["template"]["metadata"]["labels"]
    reconciler_labels = reconciler["spec"]["template"]["metadata"]["labels"]

    def matches(selector, labels):
        return all(labels.get(key) == value for key, value in selector.items())

    assert matches(api_selector, api_labels)
    assert matches(reconciler_selector, reconciler_labels)
    assert not matches(api_selector, reconciler_labels)
    assert not matches(reconciler_selector, api_labels)
    service = next(obj for obj in objects if obj and obj["kind"] == "Service")
    assert matches(service["spec"]["selector"], api_labels)
    assert not matches(service["spec"]["selector"], reconciler_labels)
    hpa = next(obj for obj in objects if obj and obj["kind"] == "HorizontalPodAutoscaler")
    assert hpa["spec"]["scaleTargetRef"]["kind"] == "Deployment"
    assert hpa["spec"]["scaleTargetRef"]["name"] == api["metadata"]["name"]
