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
| `screening/` | The local watchlist: Elasticsearch and yente, and the manifest saying what to index. Brought up by `apply.sh`, but deliberately outside its rollback -- see below. |

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

## The watchlist is the one part that may fail

`screening/` is brought up on every deploy and **cannot fail one**. It is also
not part of the rollback.

That is deliberate. The product works without a watchlist: `screening.py`
answers with a named refusal and every party screen reads *"nobody has run a
watchlist check on this party -- that is not the same as a check that found
nothing"*. A firm is genuinely in that state on its first day. Taking the
whole site down because a search index would not start would be trading
something that works for something that does not.

Two consequences worth knowing. It runs four million entities on the same
machine as the application, so memory is shared and Elasticsearch is given
three gigabytes of eight. And both ports are bound to loopback, which is why
Elasticsearch runs with authentication off -- nothing outside the machine can
reach it, and a password stored beside the thing it protects is a password in
name only.

The data is CC-BY-NC. Evaluation and internal research only; selling on top of
it needs a licence from OpenSanctions.

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
