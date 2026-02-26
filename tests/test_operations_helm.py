from pyinfra.operations import helm


def test_helm_repo_command():
    commands = list(
        helm.repo._inner(
            "rancher-latest",
            "https://releases.rancher.com/server-charts/latest",
            kubeconfig="/etc/kubernetes/admin.conf",
        ),
    )

    assert len(commands) == 1
    assert (
        commands[0].get_raw_value()
        == "helm --kubeconfig /etc/kubernetes/admin.conf repo add rancher-latest https://releases.rancher.com/server-charts/latest"
    )


def test_helm_upgrade_release_command():
    commands = list(
        helm.upgrade_release._inner(
            "rancher",
            "rancher-latest/rancher",
            namespace="cattle-system",
            kubeconfig="/etc/kubernetes/admin.conf",
            timeout="15m",
            set_values={
                "hostname": "rancher.example.com",
                "replicas": 1,
            },
        ),
    )

    assert len(commands) == 1
    assert (
        commands[0].get_raw_value()
        == "helm --kubeconfig /etc/kubernetes/admin.conf upgrade --install rancher rancher-latest/rancher --namespace cattle-system --create-namespace --wait --timeout 15m --set hostname=rancher.example.com --set replicas=1"
    )
