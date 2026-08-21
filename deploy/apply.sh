#!/bin/bash
# Put the checked-out tree into service, and undo it if that fails.
#
# Run by /usr/local/bin/vinzor-deploy after it has fetched and reset the
# checkout -- so by the time this file is read, it is already the version
# being deployed. That split exists because `git reset --hard` was replacing
# the deploy script while bash was still reading it, which is a genuinely
# nasty way to fail halfway through a deployment.
#
# The shape here is: snapshot, apply, prove, and on any failure put back
# exactly what was working. This instance has no inbound SSH and no second
# way in; a deploy that leaves nginx refusing to start is a deploy that
# needs a rebuild to recover from.

set -uo pipefail        # deliberately NOT -e: a failure must reach the
                        # rollback rather than exit the script

REPO=/opt/vinzor
KEEP=/var/lib/vinzor/.last-good
NGINX_CONF=/etc/nginx/nginx.conf
UNIT=/etc/systemd/system/vinzor.service

mkdir -p "$KEEP"

say() { echo "== $*"; }

healthy() {
    # Both hops, because they fail differently: the app can be up while
    # nginx refuses to start, and nginx can serve while the app is dead.
    local i
    for i in $(seq 1 15); do
        if curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/ \
        && curl -fsS -o /dev/null --max-time 5 http://127.0.0.1/; then
            return 0
        fi
        sleep 2
    done
    return 1
}

rollback() {
    say "ROLLING BACK to the last configuration that served traffic"
    [ -f "$KEEP/nginx.conf" ]     && cp -f "$KEEP/nginx.conf" "$NGINX_CONF"
    [ -f "$KEEP/vinzor.service" ] && cp -f "$KEEP/vinzor.service" "$UNIT"
    systemctl daemon-reload
    systemctl restart vinzor
    nginx -t && systemctl reload nginx
    if healthy; then
        say "rolled back; the site is serving the previous version"
    else
        say "ROLLBACK DID NOT RECOVER -- the site is down and needs a person"
        journalctl -u vinzor -n 40 --no-pager
        systemctl status nginx --no-pager -l | tail -20
    fi
    exit 1
}

# -- snapshot what is currently working --------------------------------------
cp -f "$NGINX_CONF" "$KEEP/nginx.conf" 2>/dev/null
cp -f "$UNIT"       "$KEEP/vinzor.service" 2>/dev/null

# -- the proxy ---------------------------------------------------------------
# It decides whether the session cookie may carry Secure, so it is part of
# how the application behaves rather than how a box happens to be set up.
if [ -f "$REPO/deploy/nginx.conf" ]; then
    cp -f "$REPO/deploy/nginx.conf" "$NGINX_CONF"
    if ! nginx -t; then
        say "the nginx config in this commit does not parse"
        rollback
    fi
fi

# -- how the app is launched -------------------------------------------------
if [ -f "$REPO/deploy/vinzor.service" ]; then
    cp -f "$REPO/deploy/vinzor.service" "$UNIT"
    # Advisory only. systemd-analyze reports style warnings alongside real
    # errors and cannot be told apart by exit code, so the thing that
    # actually decides is whether the service comes up below.
    systemd-analyze verify "$UNIT" 2>&1 | sed 's/^/   systemd: /' || true
fi

systemctl daemon-reload || rollback

# -- put it into service -----------------------------------------------------
systemctl restart vinzor || { say "the service did not restart"; rollback; }
systemctl reload nginx   || { say "nginx did not reload"; rollback; }

if ! healthy; then
    say "the new version did not answer on either hop"
    journalctl -u vinzor -n 30 --no-pager
    rollback
fi

say "serving $(cd "$REPO" && git rev-parse --short HEAD)"
