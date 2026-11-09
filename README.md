# Dograh chart publisher

Packages the upstream Dograh Helm chart from a fixed Git commit and publishes it to public GHCR. This repository is not a full Dograh fork and contains no deployment settings or credentials.

The upstream chart is alpha. Packaging and rendering do not establish production readiness.

## What gets published

- OCI chart: `oci://ghcr.io/hyperfocus1337/dograh-chart/dograh`.
- Source: [dograh-hq/dograh/deploy/helm/dograh](https://github.com/dograh-hq/dograh/tree/51e5be074cb7cb1cfa91300864fe407799d438d4/deploy/helm/dograh).
- Source pin and package version: `upstream.env`.
- Initial version: `0.1.0-upstream.51e5be074cb7`.

Chart templates are not changed. Packaging replaces the chart version, includes the upstream BSD-2-Clause license, and adds `UPSTREAM.txt` with the source commit. The version suffix identifies that commit. Application image versions remain a separate deployment choice: upstream defaults can still use `latest`.

Archives are build outputs under `dist/`, not committed files. Hostnames, access policies, Kubernetes Secrets, and k3s deployment configuration remain in the separate GitLab workload repository.

## First publication

1. Commit and push this repository to its `main` branch.
2. Check that the **Validate and publish chart** workflow passes. Pushes and pull requests only validate; they do not publish.
3. In GitHub Actions, select **Validate and publish chart**, then **Run workflow** on the default branch. The publishing job uses GitHub's built-in workflow token with `packages: write`; no personal access token is needed.
4. Open the newly created package under the owner's GitHub **Packages** page. In package settings, change its visibility to **Public**. A public source repository does not make a newly created GHCR package public automatically. Confirm the package is connected to this repository and its Actions access is enabled.
5. Check an anonymous pull before updating the GitLab deployment.

Use an isolated environment for the anonymous check. An empty Helm configuration alone is not sufficient: Helm can fall back to Docker credentials or credential helpers. This command gives Helm an empty home, separate registry configurations, and a PATH without credential helpers; it requires a standalone Helm binary:

```sh
check_dir="$(mktemp -d)"
ln -s "$(command -v helm)" "$check_dir/helm"
env -i HOME="$check_dir" PATH="$check_dir" \
  DOCKER_CONFIG="$check_dir/docker" \
  HELM_REGISTRY_CONFIG="$check_dir/registry.json" \
  "$check_dir/helm" show chart \
  oci://ghcr.io/hyperfocus1337/dograh-chart/dograh \
  --version 0.1.0-upstream.51e5be074cb7
```

If publishing returns 403, check the package's repository connection and Actions access. If anonymous access fails, check package visibility before adding credentials to the cluster.

The validation job uploads the exact rendered archive and its SHA-256 checksum as a workflow artifact. The publishing job downloads and checks that artifact instead of rebuilding it. It checks GHCR with authentication and refuses to push when the version exists; only an explicit OCI unknown-name or unknown-manifest response permits publication. Authentication errors, transport failures, unexpected responses, checksum errors, and failed Helm pushes stop the job without a published summary.

The workflow summary records the upstream commit, chart reference, version, and registry digest. Retain that digest when approving a deployment. Workflow concurrency serializes manual publications from the default branch, but the existence check is not an atomic registry lock against other publishers. GHCR tags remain mutable outside this workflow; digest references are the immutable option.

## Consume from k3s

The GitLab workload repository references this OCI chart and version directly, without a committed chart archive. Complete publication and the anonymous check before deploying it:

```yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: dograh
  namespace: kube-system
spec:
  chart: oci://ghcr.io/hyperfocus1337/dograh-chart/dograh
  version: 0.1.0-upstream.51e5be074cb7
  targetNamespace: dograh
  createNamespace: true
  failurePolicy: abort
```

Keep the existing deployment-specific `valuesContent`, timeout, retry settings, and Secret handling. Do not deploy the example alone: it omits the values that configure Traefik, TURN, image pins, and access control. No GitHub credentials are required to pull a public GHCR package.

The consumer configuration can be committed before publication, but installation will fail until the package exists and is publicly readable. After publication, record the OCI digest and use it for an immutable consumer reference.

## Upgrade

Review the upstream chart and application compatibility first. Update `UPSTREAM_COMMIT` to a full 40-character commit SHA and set `CHART_VERSION` to `<upstream-chart-version>-upstream.<first-12-commit-characters>`. Do not use a moving branch or `latest` reference.

Run the checks, push the pin change, and manually publish from the default branch. Check anonymous access, then update the consumer's version or digest through a separate reviewed change. If template changes become necessary, maintain them explicitly rather than silently patching them during packaging.

## Local checks

Requires Bash, curl, tar, Helm 3 with OCI support, Python 3, and ShellCheck. The publishing script also requires jq. CI pins Helm to `v3.17.3` and third-party actions to full commit SHAs. Offline tests use the installed Helm CLI and a local source fixture. Packaging downloads upstream source but does not run upstream application scripts, build images, or contact a Kubernetes cluster.

```sh
shellcheck scripts/*.sh
python3 -B -m unittest discover -s tests -v
bash scripts/package.sh
```

`bash scripts/package.sh` downloads the source archive for the pinned commit, retains its license, runs `helm lint`, packages it, renders the package, and writes `dist/SHA256SUMS`. It does not publish. Pushes and pull requests run the same checks in CI. Offline publishing tests use fake HTTP and Helm commands to check existing versions, registry failures, checksum mismatches, and login/push failures without contacting GHCR.

## References

- [Helm OCI registries](https://helm.sh/docs/topics/registries/)
- [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [k3s Helm controller](https://docs.k3s.io/add-ons/helm)
