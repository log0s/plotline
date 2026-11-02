# Extracted verbatim from deploy.yml's deploy-titiler install step (plus set -e, GitHub's default).
set -e
curl -fsSL --retry 3 -o "$RUNNER_TEMP/flyctl.tgz" \
  "https://github.com/superfly/flyctl/releases/download/v${FLYCTL_VERSION}/flyctl_${FLYCTL_VERSION}_Linux_x86_64.tar.gz"
echo "${FLYCTL_SHA256}  $RUNNER_TEMP/flyctl.tgz" | sha256sum -c -
mkdir -p "$RUNNER_TEMP/flyctl-bin"
tar -xzf "$RUNNER_TEMP/flyctl.tgz" -C "$RUNNER_TEMP/flyctl-bin" flyctl
echo "$RUNNER_TEMP/flyctl-bin" >> "$GITHUB_PATH"
