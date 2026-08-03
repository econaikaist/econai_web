#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi

repository_dir=${ECONAI_REPOSITORY_DIR:-/srv/econai_web}
publisher_user=econai-publisher
publisher_home=/var/lib/${publisher_user}
deploy_root=/srv/econai-site
unit_dir=/etc/systemd/system
libexec_dir=/usr/local/libexec

if [[ ! -d ${repository_dir}/.git || ! -f ${repository_dir}/scripts/sync_server_site.py ]]; then
    echo "Expected a deployed EconAI repository at ${repository_dir}." >&2
    exit 1
fi
if [[ ${deploy_root} == / || ${deploy_root} == /srv ]]; then
    echo "Refusing unsafe deployment root: ${deploy_root}" >&2
    exit 1
fi

if ! id -u "${publisher_user}" >/dev/null 2>&1; then
    useradd \
        --system \
        --home-dir "${publisher_home}" \
        --create-home \
        --shell /usr/sbin/nologin \
        "${publisher_user}"
fi
publisher_group=$(id -gn "${publisher_user}")

install -d -o "${publisher_user}" -g "${publisher_group}" -m 0755 "${publisher_home}"
install -d -o "${publisher_user}" -g "${publisher_group}" -m 0755 "${deploy_root}"
install -d -o "${publisher_user}" -g "${publisher_group}" -m 0755 "${deploy_root}/releases"
install -d -o "${publisher_user}" -g "${publisher_group}" -m 0755 "${deploy_root}/state"
install -d -o root -g root -m 0755 "${libexec_dir}"

install -o root -g root -m 0755 \
    "${repository_dir}/scripts/sync_server_site.py" \
    "${libexec_dir}/econai-sheet-publish"
install -o root -g root -m 0644 \
    "${repository_dir}/deploy/systemd/econai-sheet-publisher.service" \
    "${unit_dir}/econai-sheet-publisher.service"
install -o root -g root -m 0644 \
    "${repository_dir}/deploy/systemd/econai-sheet-publisher.timer" \
    "${unit_dir}/econai-sheet-publisher.timer"

systemctl daemon-reload
systemctl start econai-sheet-publisher.service
if [[ ! -L ${deploy_root}/current ]]; then
    echo "The first validated release was not created; leaving the current container unchanged." >&2
    exit 1
fi

cd "${repository_dir}"
docker compose config --quiet
docker compose up -d --force-recreate web_server
docker exec econai_web nginx -t

systemctl enable --now econai-sheet-publisher.timer
curl \
    --fail \
    --silent \
    --show-error \
    --resolve econai.kaist.ac.kr:443:127.0.0.1 \
    https://econai.kaist.ac.kr/ \
    >/dev/null

echo "EconAI Sheet publisher installed."
echo "Status: systemctl status econai-sheet-publisher.timer"
echo "Manual refresh: systemctl start econai-sheet-publisher.service"
echo "Logs: journalctl -u econai-sheet-publisher.service"
