# deploy/

How the server runs, kept in the repository rather than on the server.

Everything here is applied automatically on every push to `main`. A commit
that changes `nginx.conf` or `vinzor.service` changes the running machine the
same way a commit that changes `server.py` does, and needs nothing done by
hand.

| File | What it is |
| --- | --- |
| `vinzor.service` | The systemd unit. How the workspace is launched: which interpreter, which user, which workspace file, what happens when it crashes. |
| `nginx.conf` | The reverse proxy. The only thing listening on the outside; the app itself stays bound to `127.0.0.1`. It also decides whether the session cookie may carry `Secure`, by choosing which header it believes about the reader's protocol. |
| `apply.sh` | Puts both into service and proves the result answers. If it does not, it puts the previous versions back. |

## Why these are here and not on the machine

A proxy that rewrites request headers is part of how the application behaves.
`nginx.conf` is what makes the `Secure` flag possible at all: it decides which
header is trusted to say the reader used TLS, and getting that wrong means the
session token is willing to travel in the clear. That is not a detail of how a
box happens to be set up, and reviewing it should not require logging into
anything.

`apply.sh` snapshots what is currently serving before it changes anything, and
restores it if the new version does not come up on both hops -- the app on
`:8000` and nginx on `:80`. That matters more than it looks: the instance has
no inbound SSH, so a deploy that leaves nginx refusing to start is a deploy
that needs the machine rebuilt to recover from.

## What is deliberately not here

- **Passwords and the workspace.** `/var/lib/vinzor/live.db` is a compliance
  record and survives every deploy. Putting either in version control is the
  mistake this project's `.gitignore` opens by warning about.
- **The CloudFront distribution and the security group.** AWS-side
  configuration, changed through the API rather than by a file landing on a
  disk. Notably the origin request policy: it must be one that forwards
  `CloudFront-Forwarded-Proto`, or the proxy below has nothing to read and the
  cookie quietly loses its `Secure` flag.
- **`/usr/local/bin/vinzor-deploy`**, the few lines that fetch this repository
  and then hand over to `apply.sh`. It stays on the machine because
  `git reset --hard` replacing a script while bash is still reading it is a
  bad way to fail halfway through a deployment.
