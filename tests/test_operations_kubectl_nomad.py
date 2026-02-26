from pyinfra.operations import kubectl, nomad


def test_kubectl_apply_command():
    commands = list(
        kubectl.apply._inner(
            "manifests/app.yaml",
            namespace="trading",
            context="prod",
            server_side=True,
        ),
    )

    assert len(commands) == 1
    assert (
        commands[0].get_raw_value()
        == "kubectl --context prod -n trading apply -f manifests/app.yaml --server-side"
    )


def test_kubectl_rollout_status_command():
    commands = list(
        kubectl.rollout_status._inner(
            "deployment/risk-server",
            timeout="300s",
            namespace="trading",
        ),
    )

    assert len(commands) == 1
    assert (
        commands[0].get_raw_value()
        == "kubectl -n trading rollout status deployment/risk-server --timeout 300s"
    )


def test_nomad_run_command():
    commands = list(nomad.run._inner("jobs/market.nomad", detach=True))

    assert len(commands) == 1
    assert commands[0].get_raw_value() == "nomad job run -detach jobs/market.nomad"


def test_nomad_scale_command():
    commands = list(nomad.scale._inner("market-server", "workers", 3))

    assert len(commands) == 1
    assert commands[0].get_raw_value() == "nomad job scale market-server[workers] 3"


def test_kubectl_get_command():
    commands = list(
        kubectl.get._inner(
            "pods",
            namespace="cattle-system",
            output="wide",
        ),
    )

    assert len(commands) == 1
    assert commands[0].get_raw_value() == "kubectl -n cattle-system get pods -o wide"
