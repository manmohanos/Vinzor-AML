/* Vinzor — the browser side.

   This file renders and posts. It contains no compliance wording of its own:
   every sentence on screen arrives from the server, out of briefing.py, so the
   screen and the file handed to a regulator cannot drift apart. If a sentence
   here reads wrong, it is fixed in briefing.py, once, for every surface.

   Rendering is done with the `h` tagged template below, and that choice is
   load-bearing rather than stylistic. This file previously built markup by
   concatenating strings and calling esc() by hand at every interpolation --
   seventy-four of them across ten sites. Every one was correct, and that is
   precisely the problem: safety was a thing an author had to remember, on a
   screen that renders watchlist captions, investor names and model-written
   prose. One forgotten call is a script-injection hole in a compliance
   record. With `h`, escaping is what happens by default and `raw()` is the
   explicit, greppable exception.                                            */

(function () {
  "use strict";

  var root = document.getElementById("root");
  var person = sessionStorage.getItem("vinzor.person") || "";
  var openGroups = {};
  /* Whether this workspace wants a password. Decides the door
     you get and whether the top-right button switches names or
     genuinely signs you out. */
  var guarded = false;
  /* Which surface the reader is on, so the rail can say so. */
  var here = "queue";
  /* What the officer did with each suggested wording, by file. Cleared on
     every reload: it describes this sitting at the screen, nothing more.   */
  var drafts = {};
  /* Every label on screen, from briefing.py. Both read routes carry it, so it
     is populated before anything renders. Never edited here: a sentence this
     file invented would be one the jargon sweep never walked and a second
     surface would have to duplicate.                                        */
  var ui = {};
  var lastQuery = "";

  /* ---------- rendering ---------- */

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Markup that is already safe because `h` produced it. The only way to get
     an unescaped value into the page, and the only thing to audit if this
     file is ever reviewed for injection.                                    */
  function raw(html) { return { __html: String(html) }; }

  function flatten(value) {
    if (value === null || value === undefined || value === false) { return ""; }
    if (Array.isArray(value)) { return value.map(flatten).join(""); }
    if (typeof value === "object" && typeof value.__html === "string") {
      return value.__html;
    }
    return esc(value);
  }

  /* h`<p>${untrusted}</p>` — every interpolation is escaped; nested h results
     and arrays of them pass through. Arrays join with no separator, so
     `${list.map(row)}` reads the way it should.                             */
  function h(strings) {
    var out = strings[0];
    for (var i = 1; i < arguments.length; i++) {
      out += flatten(arguments[i]) + strings[i];
    }
    return raw(out);
  }

  function mount(element, node) { element.innerHTML = flatten(node); }

  function get(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(read);
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(read);
  }

  function read(response) {
    return response.json()
      .catch(function () { return {}; })
      .then(function (data) {
        if (response.ok) { return data; }
        var error = new Error(data.message || "");
        error.handled = Boolean(data.message);
        throw error;
      });
  }

  /* ---------- sign in ---------- */

  /* Two doors, and which one you get is a property of the workspace rather
     than a setting. Where nobody has a password yet this is a demonstration
     and the old name picker stands, saying plainly what it is. The moment
     anybody is given one, everybody needs one -- there is no per-person
     exemption, because a system where some people need a password is a
     system where the rest are the way in. */
  function signIn() {
    get("/api/session").then(function (session) {
      ui = session.ui || ui;
      guarded = !!session.needs_password;
      if (session.signed_in_as) {
        person = session.signed_in_as;
        load();
        return;
      }
      if (guarded) { askForPassword(session); return; }
      pickAName(session);
    });
  }

  function pickAName(session) {
    hideRail();
    mount(root, h`
      <div class="signin">
        <h1>${ui.wordmark}</h1>
        <p class="lede">${session.workspace}</p>
        <div class="who">
          ${session.people.map(function (p) {
            return h`<button type="button" data-person="${p.name}">
                       <span>${p.name}</span>
                       <span class="role">${p.title}</span>
                     </button>`;
          })}
        </div>
        <p class="disclosure warn">${ui.no_password_yet}</p>
      </div>`);

    root.querySelectorAll("[data-person]").forEach(function (button) {
      button.addEventListener("click", function () {
        person = button.getAttribute("data-person");
        sessionStorage.setItem("vinzor.person", person);
        load();
      });
    });
  }

  function askForPassword(session) {
    hideRail();
    mount(root, h`
      <div class="signin">
        <h1>${ui.wordmark}</h1>
        <p class="lede">${session.workspace}</p>
        <form class="doorway" autocomplete="on">
          <h2>${ui.sign_in_heading}</h2>
          <label for="who">${ui.sign_in_name}</label>
          <input id="who" name="username" type="text" autocomplete="username"
                 autocapitalize="words" required>
          <label for="secret">${ui.sign_in_password}</label>
          <input id="secret" name="password" type="password"
                 autocomplete="current-password" required>
          <p class="problem" hidden></p>
          <button type="submit" class="record">${ui.sign_in_button}</button>
        </form>
      </div>`);

    var form = root.querySelector(".doorway");
    var problem = form.querySelector(".problem");
    var button = form.querySelector("button");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      problem.hidden = true;
      button.disabled = true;
      button.textContent = ui.sign_in_working;
      post("/api/sign-in", {
        person: form.querySelector("#who").value,
        password: form.querySelector("#secret").value
      }).then(function (result) {
        person = result.person;
        sessionStorage.setItem("vinzor.person", person);
        load();
      }).catch(function (error) {
        button.disabled = false;
        button.textContent = ui.sign_in_button;
        form.querySelector("#secret").value = "";
        problem.textContent = error.handled ? error.message : ui.load_failed;
        problem.hidden = false;
      });
    });
    form.querySelector("#who").focus();
  }

  function signOut() {
    post("/api/sign-out", {}).catch(function () {}).then(function () {
      person = "";
      sessionStorage.removeItem("vinzor.person");
      signIn();
    });
  }

  /* ---------- the morning ---------- */

  function load(expand) {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    var url = "/api/briefing?person=" + encodeURIComponent(person);
    if (expand) { url += "&expand=" + encodeURIComponent(expand); }
    get(url)
      .then(render)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  /* The stat tiles. Every label and number arrives from the server; the
     browser only lays them out.                                             */
  function statTiles(brief) {
    if (brief.dashboard && brief.dashboard.stats) {
      return brief.dashboard.stats.map(function (s) {
        return h`<li><span class="count" data-tone="${s.tone}">${s.value}</span>
                     <span>${s.label}</span></li>`;
      });
    }
    return brief.headlines.map(function (line) {
      var parts = line.match(/^(\d+)\s+([\s\S]*)$/);
      var tone = /stop/.test(line) ? "stop" : /today/.test(line) ? "today" : "week";
      if (!parts) { return h`<li><span>${line}</span></li>`; }
      return h`<li><span class="count" data-tone="${tone}">${parts[1]}</span>
                   <span>${parts[2]}</span></li>`;
    });
  }

  /* The two dashboard panels: what the open files are about, and what is
     coming due. Bar widths are arithmetic on server-supplied shares.        */
  function dashPanels(brief) {
    var d = brief.dashboard;
    if (!d) { return ""; }
    var panels = [];
    if (d.workload && d.workload.length) {
      panels.push(h`
        <div class="panel">
          <h2 class="panel-head">${d.workload_heading}</h2>
          ${d.workload.map(function (w) {
            /* Width is applied through the DOM after render, never as an
               inline style attribute in the markup: the page's
               Content-Security-Policy (style-src 'self', no unsafe-inline)
               blocks attribute styles, and a bar that silently renders at
               zero width is worse than no bar.                              */
            var width = Math.max(4, Math.round(w.share * 100));
            return h`<div class="load-row">
                       <span class="load-label">${w.label}</span>
                       <span class="load-count">${w.count}</span>
                       <span class="load-bar"><i data-share="${width}"></i></span>
                     </div>`;
          })}
        </div>`);
    }
    /* How long the open files have waited. A count of open files cannot
       answer the first question an inspector asks, so the answer sits
       beside the count rather than in a report nobody opened. */
    if (d.ageing && d.ageing.length) {
      panels.push(h`
        <div class="panel">
          <h2 class="panel-head">${d.ageing_heading}</h2>
          ${d.ageing.map(function (band) {
            var width = Math.max(band.count ? 4 : 0,
                                 Math.round(band.share * 100));
            return h`<div class="load-row" data-tone="${band.tone}">
                       <span class="load-label">${band.label}</span>
                       <span class="load-count">${band.count}</span>
                       <span class="load-bar"><i data-share="${width}"></i></span>
                     </div>`;
          })}
          ${d.ageing_note
            ? h`<p class="panel-note">${d.ageing_note}</p>` : ""}
        </div>`);
    }
    /* Letters from the regulator. Shown whether or not any is late,
       because the failure this answers is that nothing happens when one is
       ignored -- the only defence is that it stays in front of somebody. */
    if (d.waiting && d.waiting.length) {
      panels.push(h`
        <div class="panel">
          <h2 class="panel-head">${d.waiting_heading}</h2>
          ${d.waiting.map(function (letter) {
            return h`<div class="wait-row" data-tone="${letter.tone}">
                       <span class="wait-who">${letter.who}</span>
                       <span class="wait-body">
                         <span class="wait-about">${letter.about}</span>
                         <span class="wait-ref">${letter.reference}</span>
                       </span>
                       <span class="wait-clock">${letter.clock}</span>
                     </div>`;
          })}
          ${d.waiting_note
            ? h`<p class="panel-note">${d.waiting_note}</p>` : ""}
        </div>`);
    }
    if (brief.coming_up && brief.coming_up.length) {
      panels.push(h`
        <div class="panel">
          <h2 class="panel-head">${d.deadlines_heading}</h2>
          ${brief.coming_up.map(function (due) {
            return h`<div class="due-row${due.pressing ? " pressing" : ""}">
                       <span class="due-what">${due.what}</span>
                       <span class="due-when">${due.when}</span>
                     </div>`;
          })}
        </div>`);
    }
    return panels.length ? h`<section class="dash">${panels}</section>` : "";
  }

  function render(brief) {
    ui = brief.ui || ui;
    here = "queue";
    // Who this is comes from the server, never from what the browser
    // remembered. The two disagreed the moment somebody signed in as
    // somebody else in another tab: the screen showed one name over
    // another person's queue, which is the worst kind of wrong on a
    // record that carries names.
    if (brief.person) {
      person = brief.person;
      sessionStorage.setItem("vinzor.person", person);
    }
    role = brief.title || role;
    lastCounts = {
      queue: brief.groups.reduce(function (total, g) {
        return total + g.items.length;
      }, 0)
    };
    drawRail(lastCounts);
    mount(root, h`
      <header class="masthead has-nav">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${brief.person} · ${brief.title} · ${brief.workspace}
          <button type="button" id="switch">${
            guarded ? ui.sign_out : ui.switch_user}</button>
        </div>
        <nav class="nav">
          <button type="button" id="find">${ui.find_party}</button>
          <button type="button" id="import-sheet">${ui.import_button}</button>
          <button type="button" id="screening">${ui.open_screening}</button>
          <button type="button" id="agents">${ui.open_agents}</button>
          <button type="button" id="reports">${ui.open_reports}</button>
          <button type="button" id="regulatory">${ui.open_regulatory}</button>
        </nav>
      </header>

      <section class="brief">
        <h1 class="greeting">${brief.greeting}</h1>
      ${brief.ordered_for
        ? h`<p class="ordered-for">${brief.ordered_for}</p>` : ""}
        <ul class="tally">${statTiles(brief)}</ul>
        <p class="settled-note">${brief.nothing_needed}</p>
        ${brief.read_only_because
          ? h`<p class="readonly">${brief.read_only_because}</p>` : ""}
      </section>

      ${dashPanels(brief)}

      ${brief.groups.length
        ? h`<div class="groups">${brief.groups.map(group)}</div>`
        : h`<p class="all-clear">${brief.all_clear}</p>`}

      <section class="assurance">
        <div class="margin">${ui.record_heading}</div>
        <p>${brief.assurance}</p>
      </section>

      <section class="quality" id="quality"></section>`);

    widths(root);
    wire(brief);
    loadQuality();
  }

  /* ---------- how the assistant is doing ---------- */

  function loadQuality() {
    var host = document.getElementById("quality");
    if (!host) { return; }
    get("/api/quality").then(function (r) {
      mount(host, h`
        <details class="report">
          <summary>${r.heading}</summary>
          <p class="standing">${r.standing}</p>
          ${r.caution ? h`<p class="caution">${r.caution}</p>` : ""}
          <div class="scores">
            ${r.scores.map(function (s) {
              return h`<div class="score" data-tone="${s.tone}">
                         <div class="score-value">${s.value}</div>
                         <div class="score-label">${s.label}</div>
                         <p class="small">${s.meaning}</p>
                       </div>`;
            })}
          </div>
          <p>${r.spend}</p>
          <p>${r.prepared_where}</p>
          <p class="small">${r.gap}</p>
          <p class="small">${r.recorded_as}</p>
        </details>`);
    }).catch(function () {
      host.innerHTML = "";  /* a missing report is not worth an error */
    });
  }

  function group(g, index) {
    var clauses = {};
    g.rules.forEach(function (r) { clauses[r.clause] = true; });
    var open = openGroups[index] ? " open" : "";
    return h`
      <article class="group${open}" data-tone="${g.tone}" data-index="${index}">
        <div class="row">
          <div class="margin">
            <span class="when">${g.urgency.split("—")[0].trim()}</span>
          </div>
          <div class="main">
            <button class="head" type="button"
                    aria-expanded="${open ? "true" : "false"}">
              <span class="title">${g.title}</span>
              <span class="refs">${Object.keys(clauses).length
                ? ui.clause_prefix + " " + Object.keys(clauses).join(" · ")
                : ""}</span>
              <span class="chev">›</span>
            </button>
            <div class="detail">
              <div class="prose">
                ${g.because.map(function (p) { return h`<p>${p}</p>`; })}
              </div>
              <h3 class="sub">${ui.to_close_heading}</h3>
              <ul class="todo">
                ${g.to_close_this.map(function (a) { return h`<li>${a}</li>`; })}
              </ul>
              ${g.rules.length ? h`
                <h3 class="sub">${g.rules.length > 1
                  ? ui.rules_heading : ui.rule_heading}</h3>
                ${g.rules.map(rule)}` : ""}
              <div class="items">${g.items.map(item)}</div>
              ${g.more
                ? h`<p class="more">${g.more}
                      <button type="button" class="show-all"
                              data-ref="${g.ref}">${g.show_all}</button></p>`
                : ""}
            </div>
          </div>
        </div>
      </article>`;
  }

  function rule(r) {
    return h`
      <div class="rule-block">
        <p class="rule-plain">${r.says}</p>
        <p class="rule-quote">“${r.quote}”</p>
        <div class="rule-meta">
          <span>${ui.clause_prefix} ${r.clause} · ${r.document}</span>
          <a href="${r.link}" target="_blank" rel="noopener noreferrer">${
            r.link_text}</a>
        </div>
        ${r.caution ? h`<span class="caution">${r.caution}</span>` : ""}
      </div>`;
  }

  /* The computed comparison. Not a suggestion — arithmetic, and the part of
     a name check that is safe to lean on. Shown whether or not anything was
     drafted on top of it.                                                   */
  function comparison(i) {
    if (!i.side_by_side || !i.side_by_side.length) { return ""; }
    return h`
      <div class="compare">
        <div class="compare-row head">
          <span></span>
          <span>${i.ours_label}</span>
          <span>${i.theirs_label}</span>
          <span></span>
        </div>
        ${i.side_by_side.map(function (l) {
          return h`<div class="compare-row" data-tone="${l.tone}">
                     <span class="what">${l.what}</span>
                     <span>${l.ours}</span>
                     <span>${l.theirs}</span>
                     <span class="says">${l.says}</span>
                   </div>`;
        })}
      </div>`;
  }

  function suggestion(i) {
    return i.suggestion ? suggestionPanel(i.suggestion) : "";
  }

  function suggestionPanel(s) {
    return h`
      <div class="suggest">
        <div class="suggest-head">${s.heading}</div>
        <p class="caveat">${s.caveat}</p>
        <p class="verdict">${s.verdict}</p>
        <p>${s.reasoning}</p>
        ${s.checks.length
          ? h`<p class="sub">${s.checks_label}</p>
              <ul class="todo">
                ${s.checks.map(function (c) { return h`<li>${c}</li>`; })}
              </ul>`
          : ""}
        <p class="sub">${s.wording_label}</p>
        <blockquote class="wording">${s.wording}</blockquote>
        <div class="suggest-actions">
          <button type="button" class="use">${s.use_label}</button>
          <button type="button" class="own">${s.own_label}</button>
        </div>
        <p class="small">${s.recorded_as}</p>
      </div>`;
  }

  function item(i) {
    var parts = i.line.split(" — ");
    return h`
      <div class="item" data-file="${i.case_id}">
        <div class="item-line">
          <span class="item-who">${parts[0]}</span>
          <span class="item-fact">${parts.slice(1).join(" — ")}</span>
          ${i.waiting ? h`<span class="item-waited">${i.waiting}</span>` : ""}
        </div>
        ${comparison(i)}
        ${suggestion(i)}
        <div class="choices">
          <button type="button" class="open-file" data-file="${i.case_id}">${
            ui.open_file}</button>
          ${i.choices.map(function (c) {
            return h`<button class="choice" type="button" aria-pressed="false"
                             data-outcome="${c.outcome}" title="${c.means}">${
                       c.label}</button>`;
          })}
        </div>
        <div class="pending"></div>
      </div>`;
  }


  /* ---------- one file, in full ---------- */

  /* The queue answers "what needs me". This answers "why does this need me,
     and what has happened to it" -- the question the officer is accountable
     for, and the one an inspector asks first. Same Case, same server wording;
     what is new is the chronology.                                          */
  function openCase(caseId) {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/cases/" + encodeURIComponent(caseId) +
        "?person=" + encodeURIComponent(person))
      .then(renderCase)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function renderCase(f) {
    ui = f.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${f.person} · ${f.title} · ${f.workspace}
          <button type="button" id="switch">${
            guarded ? ui.sign_out : ui.switch_user}</button>
        </div>
      </header>

      <button type="button" class="back">${f.back}</button>

      <article class="casefile" data-tone="${f.tone}">
        <div class="case-head">
          <span class="when">${f.urgency.split("—")[0].trim()}</span>
          <span class="case-kind">${f.kind}</span>
        </div>
        <h1 class="case-headline">${f.headline}</h1>
        <p class="case-about">${
          f.subject
            ? h`<button type="button" class="as-link" data-party="${f.subject}">${
                  f.who}</button>`
            : f.who
        } · ${f.about}</p>

        <div class="prose">${f.because.map(function (p) {
          return h`<p>${p}</p>`;
        })}</div>

        ${f.corroboration
          ? h`<p class="corroborates">${f.corroboration}</p>` : ""}

        ${f.side_by_side.length ? h`
          <div class="compare">
            <div class="compare-row head">
              <span></span><span>${f.ours_label}</span>
              <span>${f.theirs_label}</span><span></span>
            </div>
            ${f.side_by_side.map(function (l) {
              return h`<div class="compare-row" data-tone="${l.tone}">
                         <span class="what">${l.what}</span>
                         <span>${l.ours}</span>
                         <span>${l.theirs}</span>
                         <span class="says">${l.says}</span>
                       </div>`;
            })}
          </div>` : ""}

        ${f.suggestion ? suggestionPanel(f.suggestion) : ""}

        <h3 class="sub">${f.to_close_heading}</h3>
        <ul class="todo">${f.to_close_this.map(function (a) {
          return h`<li>${a}</li>`;
        })}</ul>

        <h3 class="sub">${f.rules.length > 1
          ? ui.rules_heading : ui.rule_heading}</h3>
        ${f.rules.map(rule)}

        <h3 class="sub">${f.timeline_heading}</h3>
        <ol class="timeline">
          ${f.timeline.map(function (m) {
            return h`<li data-tone="${m.tone}">
                       <span class="moment-when">${m.when}</span>
                       <span class="moment-kind">${m.kind}</span>
                       <span class="moment-what">${m.what}</span>
                       <span class="moment-who">${m.who}</span>
                     </li>`;
          })}
        </ol>

        ${f.settled
          ? h`<h3 class="sub">${f.decided_heading}</h3>
              <p class="settled-line">${f.settled}</p>`
          : ""}

        ${f.escalated
          ? h`<p class="handover">${f.escalated}</p>` : ""}

        ${f.read_only_because
          ? h`<p class="readonly">${f.read_only_because}</p>` : ""}

        ${f.choices.length ? h`
          <div class="item" data-file="${f.case_id}">
            <div class="choices">
              ${f.choices.map(function (c) {
                return h`<button class="choice" type="button" aria-pressed="false"
                                 data-outcome="${c.outcome}" title="${c.means}">${
                           c.label}</button>`;
              })}
            </div>
            <div class="pending"></div>
          </div>` : ""}

        <p class="small">${f.recorded_as}</p>
      </article>`);

    var swap = document.getElementById("switch");
    if (swap) {
      swap.addEventListener("click", function () {
        openGroups = {};
        signOut();
      });
    }
    root.querySelector(".back").addEventListener("click", function () { load(); });

    var toParty = root.querySelector(".case-about .as-link");
    if (toParty) {
      toParty.addEventListener("click", function () {
        openParty(toParty.getAttribute("data-party"));
      });
    }

    /* The decision flow is the queue's, unchanged. A file settled here is
       settled by the same route, recorded the same way, and the shape the
       server needs is `groups[].items[]` -- so it is handed one.           */
    looking("file", f.case_id, f.reference + " \u2014 " + f.who);

    wirePanel(root.querySelector(".casefile .suggest"), f.case_id);

    var el = root.querySelector(".item");
    if (el) {
      wireItem(el, {
        person: f.person,
        can_decide: f.can_decide,
        groups: [{ items: [{ case_id: f.case_id, choices: f.choices,
                             reasons: f.reasons }] }]
      });
    }
  }


  /* ---------- where you stand with the regulator ---------- */

  /* Licence, required posts, what is owed, the rule register and the
     enforcement scorecard. Every figure here already existed and printed to a
     terminal during a demo; none of it was anywhere a Principal Officer could
     see. No new events, no new derivation.                                  */
  function openRegulatory() {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/regulatory?person=" + encodeURIComponent(person))
      .then(renderRegulatory)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function renderRegulatory(r) {
    ui = r.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${r.workspace}</div>
      </header>

      <button type="button" class="back">${r.back}</button>
      <h1 class="greeting">${r.heading}</h1>

      <section class="panel reg">
        <h2 class="panel-head">${r.licence_heading}</h2>
        ${r.unlicensed
          ? h`<p class="readonly">${r.unlicensed}</p>`
          : h`<p class="reg-lead">${r.licence_summary}</p>`}
        <h3 class="sub">${r.posts_heading}</h3>
        ${r.posts.map(function (p) {
          return h`<div class="post-row" data-tone="${p.tone}">
                     <span class="post-office">${p.office}</span>
                     <span class="post-holder">${p.holder}</span>
                   </div>`;
        })}
      </section>

      ${r.owed.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${r.owed_heading}</h2>
          <p class="reg-lead">${r.owed_summary}</p>
          ${r.owed.map(function (o) {
            return h`<div class="owed-row" data-tone="${o.tone}">
                       <span class="owed-what">${o.what}</span>
                       <span class="owed-when">${o.when}</span>
                       <span class="owed-status">${o.status}</span>
                       <span class="owed-charge">${o.charge}</span>
                     </div>`;
          })}
        </section>` : ""}

      ${r.capital_summary ? h`
        <section class="panel reg">
          <h2 class="panel-head">${r.capital_heading}</h2>
          <p class="reg-lead">${r.capital_summary}</p>
          ${r.capital_caveat
            ? h`<p class="panel-note warn">${r.capital_caveat}</p>` : ""}
        </section>` : ""}

      ${r.reported.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${r.reported_heading}</h2>
          <p class="reg-lead">${r.reported_summary}</p>
          ${r.reported.map(function (row) {
            return h`<div class="said-row" data-tone="${
                       row.unsupported ? "stop" : "plain"}">
                       <span class="said-what">${row.what}</span>
                       <span class="said-body">
                         <span class="said-pair">Reported ${row.reported}
                           · records show ${row.records_show}</span>
                         ${row.apart
                           ? h`<span class="said-apart">${row.apart}</span>` : ""}
                       </span>
                     </div>`;
          })}
        </section>` : ""}

      <section class="panel reg">
        <h2 class="panel-head">${r.scorecard_heading}</h2>
        <p class="reg-lead">${r.scorecard_summary}</p>
        ${r.grounds.map(function (g) {
          return h`<div class="ground-row" data-tone="${g.tone}">
                     <span class="ground-name">${g.ground}</span>
                     <span class="ground-actions">${g.actions}</span>
                     <span class="ground-cover">${g.coverage}</span>
                     <p class="ground-position">${g.position}</p>
                   </div>`;
        })}
      </section>

      <section class="panel reg">
        <h2 class="panel-head">${r.register_heading}</h2>
        <p class="reg-lead">${r.register_summary}</p>
        ${r.source_check ? h`<p class="small">${r.source_check}</p>` : ""}
        ${r.register_caveat
          ? h`<p class="readonly">${r.register_caveat}</p>` : ""}
        ${r.amendment ? h`<p class="readonly">${r.amendment}</p>` : ""}
        ${r.clauses.map(function (c) {
          return h`<div class="clause-row" data-tone="${c.tone}">
                     <span class="clause-id">${ui.clause_prefix} ${c.clause}</span>
                     <span class="clause-says">${c.says}</span>
                     <span class="clause-checked">${c.checked}${
                       c.where ? " · " + c.where : ""}</span>
                     <a class="clause-link" href="${c.link}" target="_blank"
                        rel="noopener noreferrer">${ui.read_clause}</a>
                     ${c.confirmed_by
                       ? h`<p class="clause-by">${c.confirmed_by}</p>`
                       : (r.may_confirm
                          ? h`<button type="button" class="confirm-open"
                                      data-clause="${c.clause}">${
                                ui.confirm_clause}</button>`
                          : "")}
                   </div>`;
        })}
      </section>`);

    root.querySelector(".back").addEventListener("click", function () { load(); });
    looking("regulator", "standing", ui.ask_here_regulator);
    wireConfirm(r);
  }

  /* ---------- the navigation rail ----------

     Lives outside the element every view replaces, so it survives a
     re-render and does not flicker on every screen change. It is also the
     only place that permanently shows who is signed in and what their role
     means for the order they are looking at -- which used to be a line in
     a corner nobody read. */

  var WHERE = [
    { key: "queue",     label: "Your work",  go: function () { load(); } },
    { key: "chat",      label: "Assistant",  go: function () { openChat(); } },
    { key: "agents",    label: "Agents",     go: function () { openAgents(); } },
    { key: "parties",   label: "Parties",    go: function () { searchParties(""); } },
    { key: "screening", label: "Screening",  go: function () { openScreening(); } },
    { key: "import",    label: "Import",     go: function () { openImport(); } },
    { key: "reports",   label: "Reports",    go: function () { openReports(""); } },
    { key: "standing",  label: "IFSCA",      go: function () { openRegulatory(); } }
  ];

  /* Every bar in the product gets its width the same way. It used to be
     done inline for one class only, which meant the task and activity
     bars added later rendered at zero -- a progress bar that never moves
     is worse than none, because it reads as work that never started. */
  function widths(where) {
    (where || document).querySelectorAll("[data-share]").forEach(function (bar) {
      bar.style.width = bar.getAttribute("data-share") + "%";
    });
  }

  function railHost() {
    var host = document.getElementById("rail");
    if (!host) {
      host = document.createElement("nav");
      host.id = "rail";
      host.className = "rail";
      document.body.insertBefore(host, document.body.firstChild);
    }
    return host;
  }

  function drawRail(counts) {
    document.body.classList.add("has-rail");
    var host = railHost();
    mount(host, h`
      <div class="rail-mark">
        <i></i>
        <span>${ui.wordmark || "Vinzor"}
          <small>${role || ""}</small>
        </span>
      </div>
      <div class="rail-nav">
        ${WHERE.map(function (spot) {
          return h`<button type="button" data-go="${spot.key}"
                           aria-current="${String(spot.key === here)}">
                     <span>${spot.label}</span>
                     ${counts && counts[spot.key]
                       ? h`<span class="rail-count">${counts[spot.key]}</span>`
                       : ""}
                   </button>`;
        })}
      </div>
      <div class="rail-who">
        <span class="rail-name">${person || ""}</span>
        <span class="rail-role">${role || ""}</span>
        <button type="button" class="rail-out">${
          guarded ? ui.sign_out : ui.switch_user}</button>
        <button type="button" class="rail-look">${
          look === "light" ? "Dark" : "Light"}</button>
      </div>`);

    host.querySelectorAll("[data-go]").forEach(function (button) {
      button.addEventListener("click", function () {
        var key = button.getAttribute("data-go");
        var spot = WHERE.filter(function (w) { return w.key === key; })[0];
        if (!spot) { return; }
        here = key;
        stopWatching();
        spot.go();
      });
    });
    host.querySelector(".rail-out").addEventListener("click", function () {
      hideRail();
      signOut();
    });
    host.querySelector(".rail-look").addEventListener("click", swapLook);
  }

  function hideRail() {
    document.body.classList.remove("has-rail");
    var host = document.getElementById("rail");
    if (host) { host.remove(); }
  }

  /* Dark or light, remembered. Stored rather than guessed from the system,
     because a reader who chose one meant it. */
  var look = localStorage.getItem("vinzor.look") || "dark";
  function applyLook() {
    document.documentElement.setAttribute("data-look", look);
  }
  function swapLook() {
    look = look === "light" ? "dark" : "light";
    localStorage.setItem("vinzor.look", look);
    applyLook();
    drawRail(lastCounts);
  }
  applyLook();

  var role = "";
  var lastCounts = null;

  /* ---------- the assistant: one place to ask or to delegate ----------

     Two panes on purpose, which is the pattern the whole category settled
     on: the conversation on the left, and a persistent activity panel on
     the right showing what is actually running. Mixing them makes a thread
     where the reader cannot tell a sentence from a machine doing work.

     Every turn here is read out of the permanent record -- questions are
     ASSISTANT_ASKED events and jobs are TASK_GIVEN events -- so the thread
     cannot drift from the work it commissioned, and an inspector asking
     what was asked and what was done gets one answer rather than two
     systems to reconcile. */

  function openChat() {
    here = "chat";
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/chat").then(function (page) {
      drawRail(lastCounts);
      renderChat(page);
    }).catch(function () {
      mount(root, h`<p class="note bad">${ui.load_failed}</p>`);
    });
  }

  function turnBlock(turn) {
    return h`
      <div class="turn">
        <p class="turn-asked">${turn.asked}</p>
        ${turn.said ? h`<div class="turn-said">${turn.said}</div>` : ""}
        ${turn.withheld
          ? h`<p class="panel-note warn">${turn.withheld}</p>` : ""}
        ${turn.looked_at && turn.looked_at.length ? h`
          <p class="turn-read">${ui.chat_read}:
            ${turn.looked_at.map(function (step) {
              // The server sends what a person calls it. This used to render
              // the internal name with its underscores swapped for spaces,
              // which is not a translation -- "open files" is still the
              // function, said slower.
              var said = (step && step.shown) || (step && step.tool) || step;
              return h`<span class="chip">${said}</span>`;
            })}
          </p>` : ""}
        ${turn.task ? taskCard(turn.task, true) : ""}
      </div>`;
  }

  function renderChat(page) {
    ui = page.ui || ui;
    var running = (page.turns || []).filter(function (t) {
      return t.task && t.task.running;
    });

    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${page.person} · ${page.workspace}</div>
      </header>

      <h1 class="greeting">${ui.chat_heading}</h1>
      <p class="reg-lead">${ui.chat_lead}</p>

      <div class="talk">
        <div class="thread">
          ${page.turns.length
            ? page.turns.map(turnBlock)
            : h`<div class="openers">
                  ${page.openers.map(function (group) {
                    return h`<div class="opener">
                               <h2 class="panel-head">${group.heading}</h2>
                               ${group.asks.map(function (ask) {
                                 return h`<button type="button" class="try"
                                                  data-ask="${ask}">${ask}</button>`;
                               })}
                             </div>`;
                  })}
                </div>`}

          <form class="askbar chat-ask">
            <input id="say" type="text" autocomplete="off"
                   placeholder="${ui.chat_placeholder}">
            <button type="submit" class="record">${ui.chat_send}</button>
            <p class="problem" hidden></p>
          </form>
        </div>

        <aside class="beside">
          <h2 class="panel-head">${ui.chat_activity}</h2>
          ${running.length
            ? running.map(function (t) {
                return h`<div class="doing">
                           <span class="doing-what">${t.task.now_doing}</span>
                           <span class="doing-bar"><i data-share="${t.task.how_far}"></i></span>
                           <span class="doing-count">${t.task.done_count} of ${t.task.step_count}</span>
                         </div>`;
              })
            : h`<p class="readonly">${ui.chat_quiet}</p>`}

          ${page.again && page.again.length ? h`
            <h2 class="panel-head">${ui.chat_again}</h2>
            ${page.again.map(function (ask) {
              return h`<button type="button" class="try" data-ask="${ask}">${ask}</button>`;
            })}` : ""}
        </aside>
      </div>`);

    var form = root.querySelector(".chat-ask");
    var box = form.querySelector("#say");
    var problem = form.querySelector(".problem");
    var button = form.querySelector("button");

    function send(text) {
      if (!text) { return; }
      problem.hidden = true;
      box.disabled = true;
      button.disabled = true;
      button.textContent = ui.chat_thinking;
      post("/api/chat", { asked: text }).then(function (result) {
        box.value = "";
        openChat();
        if (result.kind === "work") { keepChatWatching(); }
        if (result.kind === "refused") {
          problem.textContent = result.said;
          problem.hidden = false;
        }
      }).catch(function (error) {
        box.disabled = false;
        button.disabled = false;
        button.textContent = ui.chat_send;
        problem.textContent = error.handled ? error.message : ui.load_failed;
        problem.hidden = false;
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      send(box.value.trim());
    });
    root.querySelectorAll(".try").forEach(function (chip) {
      chip.addEventListener("click", function () {
        send(chip.getAttribute("data-ask"));
      });
    });

    widths(root);
    var last = root.querySelector(".thread .turn:last-of-type");
    if (last) { last.scrollIntoView({ block: "nearest" }); }
    box.focus();
    if (running.length) { keepChatWatching(); } else { stopWatching(); }
  }

  /* Polls only while a job in the thread is running, like the agents page,
     and stops itself the moment nothing is. */
  function keepChatWatching() {
    if (watching) { return; }
    watching = setInterval(function () {
      if (here !== "chat") { stopWatching(); return; }
      get("/api/chat").then(function (page) {
        var still = (page.turns || []).some(function (t) {
          return t.task && t.task.running;
        });
        if (document.querySelector(".talk")) { renderChat(page); }
        if (!still) { stopWatching(); }
      }).catch(stopWatching);
    }, 1500);
  }

  /* ---------- agents: work a person delegates ----------

     The panel is a reading of the permanent record, not an animation. A
     step appears as done because an event says it finished, so what
     somebody watched is what an inspector reads back a year later.

     The plan is shown in full before anything runs -- the dynamic
     checklist -- because somebody watching delegated work needs to know
     what was undertaken, not only what has finished. */

  var watching = null;

  function openAgents() {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/tasks").then(renderAgents).catch(function () {
      mount(root, h`<p class="note bad">${ui.load_failed}</p>`);
    });
  }

  function stepMark(step) {
    if (step.how === "found") { return "found"; }
    if (step.how === "failed") { return "failed"; }
    if (step.how === "skipped") { return "skipped"; }
    if (step.how) { return "done"; }
    return "waiting";
  }

  function taskCard(task, open) {
    return h`
      <article class="task" data-task="${task.task_id}"
               data-stopped="${String(!!task.stopped)}"
               data-running="${String(task.running)}">
        <header class="task-head">
          <span class="task-asked">${task.asked}</span>
          <span class="task-meta">${task.asked_by} · ${task.given_at}</span>
        </header>
        <div class="task-bar"><i data-share="${task.how_far}"></i></div>
        ${task.said ? h`<p class="task-said">${task.said}</p>` : ""}
        <p class="task-now">${
          task.running
            ? (task.now_doing || ui.agents_watching)
            : task.outcome}</p>
        ${open ? h`
          <ol class="steps">
            ${task.plan.map(function (step) {
              return h`<li class="step" data-mark="${stepMark(step)}">
                         <span class="step-dot"></span>
                         <span class="step-body">
                           <span class="step-says">
                             <span class="step-agent">${step.agent}</span>
                             ${step.says}
                           </span>
                           ${step.headline
                             ? h`<span class="step-found">${step.headline}</span>`
                             : ""}
                           ${step.details.length ? h`
                             <span class="step-detail">
                               ${step.details.map(function (line) {
                                 return h`<span>${line}</span>`;
                               })}
                             </span>` : ""}
                         </span>
                       </li>`;
            })}
          </ol>` : ""}
      </article>`;
  }

  function renderAgents(page) {
    ui = page.ui || ui;
    here = "agents";
    drawRail(lastCounts);
    var running = page.tasks.filter(function (t) { return t.running; });
    var done = page.tasks.filter(function (t) { return !t.running; });

    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${page.person} · ${page.workspace}</div>
      </header>

      <button type="button" class="back">${ui.back_to_queue}</button>

      <h1 class="greeting">${ui.agents_heading}</h1>
      <p class="reg-lead">${ui.agents_lead}</p>

      <form class="askbar">
        <input id="asked" type="text" autocomplete="off"
               placeholder="${ui.agents_placeholder}">
        <button type="submit" class="record">${ui.agents_send}</button>
        <p class="problem" hidden></p>
      </form>

      <section class="jobs">
        ${page.jobs.map(function (job) {
          return h`<div class="job">
                     <h2 class="job-name">${job.asked}</h2>
                     <p class="job-about">${job.about}</p>
                     <p class="job-steps">${job.steps.join(" → ")}</p>
                     <button type="button" class="record job-go"
                             data-job="${job.key}">${ui.agents_start}</button>
                   </div>`;
        })}
      </section>

      ${running.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${ui.agents_running}</h2>
          ${running.map(function (t) { return taskCard(t, true); })}
        </section>` : ""}

      ${done.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${ui.agents_recent}</h2>
          ${done.map(function (t) { return taskCard(t, true); })}
        </section>` : ""}

      ${!page.tasks.length
        ? h`<p class="readonly">${ui.agents_none}</p>` : ""}`);

    root.querySelector(".back").addEventListener("click", function () {
      stopWatching();
      load();
    });
    widths(root);
    var askbar = root.querySelector(".askbar");
    if (askbar) {
      var problem = askbar.querySelector(".problem");
      askbar.addEventListener("submit", function (event) {
        event.preventDefault();
        var box = askbar.querySelector("#asked");
        var asked = box.value.trim();
        if (!asked) { return; }
        problem.hidden = true;
        box.disabled = true;
        post("/api/tasks", { asked: asked }).then(function (result) {
          box.disabled = false;
          if (result.refused) {
            /* Refusing is an answer, not an error. Shown in the same
               place a plan would be, so the reply always lands where the
               eye already is. */
            problem.textContent = result.refused;
            problem.hidden = false;
            return;
          }
          box.value = "";
          openAgents();
          keepWatching();
        }).catch(function (error) {
          box.disabled = false;
          problem.textContent = error.handled ? error.message : ui.load_failed;
          problem.hidden = false;
        });
      });
    }

    root.querySelectorAll(".job-go").forEach(function (button) {
      button.addEventListener("click", function () {
        button.disabled = true;
        post("/api/tasks", { job: button.getAttribute("data-job") })
          .then(function () { openAgents(); keepWatching(); })
          .catch(function () { button.disabled = false; });
      });
    });
    if (running.length) { keepWatching(); } else { stopWatching(); }
  }

  /* Polls only while something is actually running, and stops itself the
     moment nothing is. A timer that keeps firing on a finished page is how
     a demonstration machine ends up warm. */
  function keepWatching() {
    if (watching) { return; }
    watching = setInterval(function () {
      if (!document.querySelector(".task[data-running=\"true\"]")) {
        stopWatching();
        return;
      }
      get("/api/tasks").then(function (page) {
        if (document.querySelector(".jobs")) { renderAgents(page); }
      }).catch(stopWatching);
    }, 1200);
  }

  /* A download rather than a fetch: the file is meant to leave. */
  function wireExport(where) {
    (where || root).querySelectorAll(".export").forEach(function (button) {
      button.addEventListener("click", function () {
        var party = button.getAttribute("data-export");
        window.location.href = "/api/export"
          + (party ? "?party=" + encodeURIComponent(party) : "");
      });
    });
  }

  function stopWatching() {
    if (watching) { clearInterval(watching); watching = null; }
  }

  /* ---------- one party, as a document that leaves the building ---------- */

  /* Every other screen is for somebody who already works here. This one is
     handed to an inspector, an auditor or a correspondent bank, so it is
     built to be printed and it says on its face who may read it. The
     warning is not decoration: the danger is not that the document holds
     secrets, it is that its existence discloses that a customer was
     examined, which is the thing clause 4.1(d) forbids revealing. */
  function openRecord(ref) {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/records/" + encodeURIComponent(ref))
      .then(function (d) { renderRecord(d, ref); })
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function recordPart(part) {
    return h`
      <section class="rep-section">
        <h2 class="rep-head">${part.heading}</h2>
        <p class="rep-lead">${part.lead}</p>
        ${part.facts.length ? h`
          <div class="rep-rows">
            ${part.facts.map(function (f) {
              return h`<div class="rep-row" data-tone="${f.tone}">
                         <span class="rep-what">${f.label}</span>
                         <span class="rep-count">${f.value}</span>
                         <span class="rep-note">${f.note}</span>
                       </div>`;
            })}
          </div>` : ""}
        ${part.entries.length ? h`
          <div class="doc-entries">
            ${part.entries.map(function (e) {
              return h`<div class="doc-entry" data-tone="${e.tone}">
                         <span class="doc-when">${e.when}</span>
                         <span class="doc-body">
                           <span class="doc-what">${e.what}</span>
                           ${e.why ? h`<q class="doc-why">${e.why}</q>` : ""}
                           ${e.who ? h`<span class="doc-who">${e.who}</span>` : ""}
                         </span>
                         <span class="doc-clause">${e.clause}</span>
                       </div>`;
            })}
          </div>` : ""}
        ${part.tail ? h`<p class="rep-tail">${part.tail}</p>` : ""}
      </section>`;
  }

  function renderRecord(d, ref) {
    ui = d.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${person} · ${d.workspace}</div>
      </header>

      <button type="button" class="back no-print">${d.back}</button>

      ${d.refusal ? h`<p class="note bad">${d.refusal}</p>` : h`
        <article class="report doc">
          <h1 class="rep-title">${d.title}</h1>
          <p class="rep-covering">${d.kind}${
            d.workspace ? " · " + d.workspace : ""}</p>

          <aside class="doc-confidential">
            <h2 class="doc-conf-head">${ui.record_confidential}</h2>
            <p>${d.confidential}</p>
          </aside>

          ${d.opening ? h`
            <div class="opening">
              <p>${d.opening}</p>
              <span class="opening-mark">Written by the assistant from the
                sections below. It states no conclusion — that is yours.</span>
            </div>` : ""}
          ${d.opening_withheld
            ? h`<p class="panel-note warn">${d.opening_withheld}</p>` : ""}

          <div class="rep-summary">
            ${d.summary.map(function (line) { return h`<p>${line}</p>`; })}
          </div>

          ${d.parts.map(recordPart)}

          <p class="rep-printed">${d.printed}</p>

          <div class="confirm no-print">
            <button type="button" class="record print">${d.print_label}</button>
            <button type="button" class="record ghost export"
                    data-export="${d.entity_id}">${ui.export_party}</button>
          </div>
        </article>`}`);

    root.querySelector(".back").addEventListener("click", function () {
      if (ref) { openParty(ref); } else { load(); }
    });
    var printer = root.querySelector(".print");
    if (printer) {
      printer.addEventListener("click", function () { window.print(); });
    }
    wireExport(root);
  }

  /* ---------- everything about one party ---------- */

  /* The queue answers "what needs me" and a file answers "why". Neither
     answers "what do we know about this investor", which is the question an
     officer is asked on the telephone. Same log, filtered to one subject.  */
  function openParty(ref) {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/parties/" + encodeURIComponent(ref)
        + "?person=" + encodeURIComponent(person))
      .then(renderParty)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function fileRows(rows) {
    return rows.map(function (f) {
      return h`<button type="button" class="file-row" data-tone="${f.tone}"
                       data-file="${f.case_id}">
                 <span class="file-ref">${f.reference}</span>
                 <span class="file-head">${f.headline}</span>
                 <span class="file-when">${f.urgency.split("\u2014")[0].trim()}</span>
               </button>`;
    });
  }

  function renderParty(p) {
    ui = p.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${p.workspace}</div>
      </header>

      <button type="button" class="back">${p.back}</button>

      <h1 class="greeting">${p.heading}</h1>
      <p class="reg-lead">${p.kind}${p.standing ? " \u00b7 " + p.standing : ""}
        <button type="button" id="check">${ui.check_party}</button>
        <button type="button" id="record">${ui.open_record}</button>
      </p>
      ${p.unknown ? h`<p class="readonly">${p.unknown}</p>` : ""}

      ${p.traits.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${p.traits_heading}</h2>
          ${p.traits.map(function (t) {
            return h`<div class="post-row" data-tone="${t.tone}">
                       <span class="post-office">${t.label}</span>
                       <span class="post-holder">${t.value}</span>
                     </div>`;
          })}
          <p class="small">${p.traits_caveat}</p>
        </section>` : ""}

      ${(p.papers.length || p.papers_none) ? h`
        <section class="panel reg">
          <h2 class="panel-head">${p.papers_heading}</h2>
          ${p.papers.map(function (d) {
            return h`<div class="paper-row" data-tone="${d.tone}">
                       <span class="paper-what">
                         <span class="paper-kind">${d.called}</span>
                         <span class="paper-file">${d.filename}</span>
                       </span>
                       <span class="paper-body">
                         <span class="paper-supports">${d.supports}</span>
                         <span class="paper-who">Filed ${d.when} by ${d.who}</span>
                       </span>
                       <span class="paper-when">${d.lapsed}</span>
                     </div>`;
          })}
          ${p.papers_none ? h`<p class="readonly">${p.papers_none}</p>` : ""}
          ${p.papers_note ? h`<p class="panel-note">${p.papers_note}</p>` : ""}
        </section>` : ""}

      ${p.risk_heading ? h`
        <section class="panel reg risk" data-band="${p.risk_category}">
          <h2 class="panel-head">${p.risk_heading}</h2>
          ${p.risk_screening
            ? h`<p class="risk-screening">${p.risk_screening}</p>` : ""}
          ${p.risk_guidance.map(function (line) {
            return h`<p class="risk-guidance">${line}</p>`;
          })}
          <p class="risk-summary">${p.risk_summary}</p>
          ${p.risk_due ? h`<p class="risk-due">${p.risk_due}</p>` : ""}
          ${p.risk_factors.length ? h`
            <div class="risk-factors">
              ${p.risk_factors.map(function (f) {
                return h`<div class="risk-row" data-present="${
                           String(f.present)}">
                           <span class="risk-mark"></span>
                           <span class="risk-what">
                             <span class="risk-wording">${f.wording}</span>
                             <span class="risk-why">${f.because}</span>
                           </span>
                           <span class="risk-ref">${f.ref}${
                             f.answered_by ? " · " + f.answered_by : ""
                           }</span>
                         </div>`;
              })}
            </div>` : ""}
          ${p.risk_unanswered
            ? h`<p class="readonly">${p.risk_unanswered}</p>` : ""}

          ${p.may_assess ? h`
            <div class="risk-set" data-party="${p.entity_id}">
              <h3 class="sub">${ui.risk_set}</h3>
              <div class="choices">
                <button type="button" class="choice band" data-band="HIGH"
                        aria-pressed="false">${ui.risk_high}</button>
                <button type="button" class="choice band" data-band="MEDIUM"
                        aria-pressed="false">${ui.risk_medium}</button>
                <button type="button" class="choice band" data-band="LOW"
                        aria-pressed="false">${ui.risk_low}</button>
              </div>

              ${p.risk_open.length ? h`
                <h3 class="sub">${ui.risk_open_heading}</h3>
                <div class="risk-open">
                  ${p.risk_open.map(function (f) {
                    return h`<div class="open-row" data-ref="${f.ref}">
                               <span class="open-wording">${f.wording}
                                 <span class="risk-ref">${f.ref}</span></span>
                               <select class="open-answer">
                                 <option value="">${ui.risk_unknown}</option>
                                 <option value="yes">${ui.risk_yes}</option>
                                 <option value="no">${ui.risk_no}</option>
                               </select>
                               <input type="text" class="open-note"
                                      placeholder="${ui.risk_note}">
                             </div>`;
                  })}
                </div>` : ""}

              <div class="reason">
                <label for="risk-why">${ui.risk_why}</label>
                <textarea id="risk-why" rows="3"></textarea>
              </div>
              <div class="confirm">
                <button type="button" class="record risk-record" disabled>${
                  ui.risk_record}</button>
              </div>
              <p class="note problem" hidden></p>
            </div>` : ""}

          <p class="small">${p.risk_caveat}</p>
        </section>` : ""}

      <section class="panel reg">
        <h2 class="panel-head">${p.ties_heading}</h2>
        ${p.ties_none ? h`<p class="readonly">${p.ties_none}</p>` : ""}
        ${p.ties.map(function (t) {
          return h`<button type="button" class="tie-row" data-party="${t.ref}">
                     <span class="tie-dir">${t.direction}</span>
                     <span class="tie-who">${t.who}</span>
                     <span class="tie-share">${t.share}</span>
                     <span class="tie-basis">${t.basis}</span>
                   </button>`;
        })}
      </section>

      <section class="panel reg">
        <h2 class="panel-head">${p.money_heading}</h2>
        ${p.money_none
          ? h`<p class="readonly">${p.money_none}</p>`
          : h`<p class="reg-lead">${p.money_summary}</p>`}
        ${p.movements.map(function (m) {
          return h`<div class="move-row" data-tone="${m.tone}">
                     <span class="move-when">${m.when}</span>
                     <span class="move-what">${m.what}</span>
                     <span class="move-amount">${m.amount}</span>
                     <span class="move-note">${m.note}</span>
                   </div>`;
        })}
      </section>

      ${p.open_files.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${p.open_heading}</h2>
          ${fileRows(p.open_files)}
        </section>` : ""}

      ${p.settled_files.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${p.settled_heading}</h2>
          ${fileRows(p.settled_files)}
        </section>` : ""}

      <section class="panel reg">
        <h2 class="panel-head">${p.timeline_heading}</h2>
        <ol class="timeline">
          ${p.timeline.map(function (m) {
            return h`<li data-tone="${m.tone}">
                       <span class="moment-when">${m.when}</span>
                       <span class="moment-what">${m.what}</span>
                       <span class="moment-who">${m.who}</span>
                     </li>`;
          })}
        </ol>
      </section>`);

    looking("party", p.entity_id, p.name);
    var check = document.getElementById("check");
    if (check) {
      check.addEventListener("click", function () { openCheck(p.entity_id); });
    }
    var record = document.getElementById("record");
    if (record) {
      record.addEventListener("click", function () {
        openRecord(p.entity_id);
      });
    }
    wireParty();
  }

  /* Every route out of a party page: another party, or one of its files. */
  /* Categorising a customer. The band is a choice, not a computation --
     clause 4.2 says in terms that the factors do not add up to an answer --
     so nothing is pre-selected and the record button stays dead until a
     person has picked one and written why. */
  function wireRisk() {
    var panel = root.querySelector(".risk-set");
    if (!panel) { return; }
    var chosen = "";
    var record = panel.querySelector(".risk-record");
    var why = panel.querySelector("#risk-why");
    var problem = panel.querySelector(".problem");

    function ready() {
      record.disabled = !(chosen && why.value.trim());
    }
    why.addEventListener("input", ready);

    panel.querySelectorAll(".band").forEach(function (button) {
      button.addEventListener("click", function () {
        panel.querySelectorAll(".band").forEach(function (b) {
          b.setAttribute("aria-pressed", "false");
        });
        button.setAttribute("aria-pressed", "true");
        chosen = button.getAttribute("data-band");
        ready();
      });
    });

    record.addEventListener("click", function () {
      record.disabled = true;
      problem.hidden = true;
      var answers = {};
      panel.querySelectorAll(".open-row").forEach(function (row) {
        var said = row.querySelector(".open-answer").value;
        if (!said) { return; }        /* left unestablished, so not answered */
        answers[row.getAttribute("data-ref")] = {
          present: said === "yes",
          because: row.querySelector(".open-note").value
        };
      });
      post("/api/risk", {
        person: person,
        party: panel.getAttribute("data-party"),
        category: chosen,
        reason: why.value,
        answers: answers
      }).then(function () {
        openParty(panel.getAttribute("data-party"));
      }).catch(function (error) {
        record.disabled = false;
        problem.textContent = error.handled ? error.message : ui.record_failed;
        problem.hidden = false;
      });
    });
  }

  function wireParty() {
    wireRisk();
    root.querySelector(".back").addEventListener("click", function () { load(); });
    Array.prototype.forEach.call(
      root.querySelectorAll(".tie-row"), function (el) {
        el.addEventListener("click", function () {
          openParty(el.getAttribute("data-party"));
        });
      });
    Array.prototype.forEach.call(
      root.querySelectorAll(".file-row"), function (el) {
        el.addEventListener("click", function () {
          openCase(el.getAttribute("data-file"));
        });
      });
  }

  /* ---------- finding a party by name ---------- */

  function searchParties(query) {
    get("/api/parties?q=" + encodeURIComponent(query))
      .then(renderSearch)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function renderSearch(r) {
    ui = r.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${r.workspace}</div>
      </header>

      <button type="button" class="back">${ui.back_to_queue}</button>
      <h1 class="greeting">${ui.find_heading}</h1>

      <form class="finder" id="finder">
        <input type="search" id="q" name="q" autocomplete="off"
               placeholder="${ui.find_placeholder}" value="${lastQuery}">
        <button type="submit">${ui.find_go}</button>
      </form>

      <p class="reg-lead">${r.found}</p>
      <section class="panel reg">
        ${r.parties.map(function (party) {
          return h`<button type="button" class="tie-row" data-party="${party.ref}">
                     <span class="tie-dir">${party.kind}</span>
                     <span class="tie-who">${party.name}</span>
                   </button>`;
        })}
      </section>`);

    root.querySelector(".back").addEventListener("click", function () { load(); });
    Array.prototype.forEach.call(
      root.querySelectorAll(".tie-row"), function (el) {
        el.addEventListener("click", function () {
          openParty(el.getAttribute("data-party"));
        });
      });
    var form = document.getElementById("finder");
    var box = document.getElementById("q");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      lastQuery = box.value;
      searchParties(lastQuery);
    });
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  }


  /* ---------- who has been checked against the watchlists ---------- */

  /* A match already reaches the officer as a Case. A clean check reaches
     nothing -- it opens no Case by design -- so before this page there was
     nowhere in the product it could be seen. That is the wrong way round:
     the clean result is the evidence the check was ever performed.        */
  function openScreening() {
    mount(root, h`<p class="loading">${ui.loading}</p>`);
    get("/api/screening")
      .then(renderScreening)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function checkRows(rows) {
    return rows.map(function (c) {
      return h`<button type="button" class="check-row" data-tone="${c.tone}"
                       data-party="${c.ref}">
                 <span class="check-who">${c.who}</span>
                 <span class="check-kind">${c.kind}</span>
                 <span class="check-when">${c.when}</span>
                 <span class="check-result">${c.result}</span>
               </button>`;
    });
  }

  function renderScreening(s) {
    ui = s.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${s.workspace}</div>
      </header>

      <button type="button" class="back">${s.back}</button>
      <h1 class="greeting">${s.heading}</h1>

      <section class="panel reg">
        <p class="cover" data-tone="${s.coverage_tone}">${s.coverage_summary}</p>
        <p class="small">${s.scope_note}</p>
      </section>

      <section class="panel reg">
        <h2 class="panel-head">${s.rule_heading}</h2>
        <p class="reg-lead">${s.rule_says}</p>
        <p class="readonly">${s.rule_caveat}</p>
        ${s.link ? h`<a class="clause-link" href="${s.link}"
             target="_blank" rel="noopener noreferrer">${
             s.rule_clause} \u2014 ${ui.read_clause}</a>` : ""}
      </section>

      ${s.unchecked.length ? h`
        <section class="panel reg">
          <h2 class="panel-head">${s.unchecked_heading}</h2>
          ${s.unchecked_more ? h`<p class="small">${s.unchecked_more}</p>` : ""}
          ${checkRows(s.unchecked)}
        </section>` : ""}

      <section class="panel reg">
        <h2 class="panel-head">${s.checked_heading}</h2>
        ${s.checked_none ? h`<p class="readonly">${s.checked_none}</p>` : ""}
        ${checkRows(s.checked)}
      </section>`);

    root.querySelector(".back").addEventListener("click", function () { load(); });
    Array.prototype.forEach.call(
      root.querySelectorAll(".check-row"), function (el) {
        el.addEventListener("click", function () {
          openParty(el.getAttribute("data-party"));
        });
      });
    looking("screening", "coverage", ui.ask_here_screening);
  }


  /* ---------- a qualified person signing off a clause ---------- */

  /* The register is the foundation everything else stands on, and until
     someone qualified has read a clause the product says so on every file
     that cites it. This is how that person says otherwise -- in their own
     name, against the exact wording they were shown.                      */
  function wireConfirm(r) {
    Array.prototype.forEach.call(
      root.querySelectorAll(".confirm-open"), function (button) {
        button.addEventListener("click", function () {
          var row = button.closest(".clause-row");
          if (row.querySelector(".confirm-panel")) { return; }
          button.hidden = true;
          var panel = document.createElement("div");
          panel.className = "confirm-panel";
          mount(panel, h`
            <p class="confirm-lead">${ui.confirm_lead}</p>
            <label class="confirm-field">
              <span>${ui.confirm_who}</span>
              <input type="text" class="confirm-qual"
                     placeholder="${ui.confirm_who_hint}">
            </label>
            <label class="confirm-field">
              <span>${ui.confirm_note}</span>
              <input type="text" class="confirm-text"
                     placeholder="${ui.confirm_note_hint}">
            </label>
            <div class="confirm-actions">
              <button type="button" class="confirm-do">${ui.confirm_go}</button>
              <button type="button" class="confirm-cancel">${ui.cancel}</button>
            </div>
            <p class="confirm-said"></p>`);
          row.appendChild(panel);
          panel.querySelector(".confirm-qual").focus();

          panel.querySelector(".confirm-cancel")
            .addEventListener("click", function () {
              panel.remove();
              button.hidden = false;
            });

          panel.querySelector(".confirm-do")
            .addEventListener("click", function () {
              var said = panel.querySelector(".confirm-said");
              var qualification = panel.querySelector(".confirm-qual").value.trim();
              var note = panel.querySelector(".confirm-text").value.trim();
              if (!qualification || !note) {
                said.textContent = ui.confirm_needs_both;
                said.className = "confirm-said bad";
                return;
              }
              said.textContent = "";
              post("/api/confirmations", {
                person: r.person,
                clause: button.getAttribute("data-clause"),
                qualification: qualification,
                note: note
              }).then(function () {
                openRegulatory();
              }).catch(function (error) {
                said.textContent = error.handled ? error.message : ui.load_failed;
                said.className = "confirm-said bad";
              });
            });
        });
      });
  }


  /* ---------- asking the workspace a question ---------- */

  /* It sits on every screen rather than on one of its own, because the
     question an officer has is almost always about what is in front of them.
     Two consequences shape the code.

     It lives outside `root`. Every view replaces root wholesale, so a panel
     inside it would be destroyed mid-answer by any navigation, and the
     conversation would not survive opening the file being discussed.

     It knows what is on screen. `looking_at` is set by each view and travels
     with the question, so "why is this open" resolves to the file the officer
     is reading without them having to name it. Only an identifier travels;
     the assistant still has to fetch the record through the same tools as
     ever, and still cannot change it.                                     */
  var asked = [];
  var lookingAt = null;
  var helperOpen = false;
  var helperBusy = "";

  function looking(kind, id, label) {
    lookingAt = id ? { kind: kind, id: id, label: label } : null;
    drawHelper();
  }

  function helperRoot() {
    var node = document.getElementById("helper");
    if (!node) {
      node = document.createElement("div");
      node.id = "helper";
      document.body.appendChild(node);
    }
    return node;
  }

  function drawHelper() {
    if (!person || !ui.ask_open) {
      var existing = document.getElementById("helper");
      if (existing) { existing.remove(); }
      return;
    }
    var node = helperRoot();

    if (!helperOpen) {
      mount(node, h`<button type="button" class="helper-open"
                            aria-expanded="false">${ui.ask_open}</button>`);
      node.querySelector(".helper-open").addEventListener("click", function () {
        helperOpen = true;
        drawHelper();
      });
      return;
    }

    mount(node, h`
      <section class="helper-panel" role="dialog" aria-label="${ui.ask_heading}">
        <header class="helper-head">
          <span class="helper-title">${ui.ask_heading}</span>
          <button type="button" class="helper-close" aria-label="${ui.cancel}">
            &times;</button>
        </header>

        ${lookingAt ? h`<p class="helper-context">${ui.ask_about} ${
          lookingAt.label}</p>` : ""}

        <div class="helper-scroll">
          ${!asked.length && !helperBusy ? h`
            <p class="helper-lead">${ui.ask_lead}</p>
            <div class="helper-examples">
              ${(ui.ask_examples || []).map(function (example) {
                return h`<button type="button" class="example">${example}</button>`;
              })}
            </div>` : ""}

          ${helperBusy ? h`
            <div class="turn">
              <p class="q">${helperBusy}</p>
              <p class="thinking">${ui.ask_thinking}</p>
            </div>` : ""}

          ${asked.map(function (turn) {
            return h`<div class="turn">
                       <p class="q">${turn.question}</p>
                       ${turn.answer
                         ? h`<p class="a">${turn.answer}</p>`
                         : h`<p class="a bad">${turn.refused}</p>`}
                       ${turn.steps.length ? h`
                         <p class="read">${ui.ask_looked_at} ${
                           turn.steps.map(function (s) {
                             return s.shown || s.tool;
                           }).join(", ")}</p>` : ""}
                     </div>`;
          })}
        </div>

        <form class="helper-ask">
          <input type="text" class="helper-q" autocomplete="off"
                 placeholder="${ui.ask_placeholder}"
                 ${helperBusy ? "disabled" : ""}>
          <button type="submit" ${helperBusy ? "disabled" : ""}>${
            ui.ask_go}</button>
        </form>
      </section>`);

    node.querySelector(".helper-close").addEventListener("click", function () {
      helperOpen = false;
      drawHelper();
    });
    Array.prototype.forEach.call(
      node.querySelectorAll(".example"), function (button) {
        button.addEventListener("click", function () { send(button.textContent); });
      });

    var form = node.querySelector(".helper-ask");
    var box = node.querySelector(".helper-q");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = box.value.trim();
      if (text) { box.value = ""; send(text); }
    });
    if (!helperBusy) { box.focus(); }
  }

  function send(question) {
    helperBusy = question;
    drawHelper();
    post("/api/ask", {
      person: person,
      question: question,
      context_kind: lookingAt ? lookingAt.kind : "",
      context_id: lookingAt ? lookingAt.id : "",
      context_label: lookingAt ? lookingAt.label : ""
    }).then(function (reply) {
      asked.unshift({
        question: reply.question || question,
        answer: reply.answer || "",
        refused: reply.refused || "",
        steps: reply.steps || []
      });
      helperBusy = "";
      drawHelper();
    }).catch(function (error) {
      asked.unshift({
        question: question, answer: "",
        refused: error.handled ? error.message : ui.load_failed, steps: []
      });
      helperBusy = "";
      drawHelper();
    });
  }


  /* ---------- one check, told as it happened ---------- */

  /* The investigation view. Every entry corresponds to something that
     actually happened on the server -- the query sent, the candidates
     returned, the comparison computed, the draft prepared -- and the
     durations shown are measured, not staged. The reveal is a single fast
     cascade (a record composing itself), never a re-enactment: research and
     taste agree that replaying finished work as live is theatre, and in a
     compliance product theatre in the trail poisons every real number
     beside it.                                                            */
  function openCheck(ref) {
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${person}</div>
      </header>
      <p class="loading">${ui.check_wait}</p>`);
    post("/api/checks", { person: person, party: ref })
      .then(renderCheckView)
      .catch(function (error) {
        mount(root, h`<p class="note bad">${
          error.handled ? error.message : ui.load_failed
        }</p>`);
      });
  }

  function checkStep(step) {
    return h`
      <li class="inv-step" data-kind="${step.kind}">
        <div class="step-head">
          <span class="step-title">${step.title}</span>
          ${step.took ? h`<span class="step-took">${step.took}</span>` : ""}
        </div>
        ${step.body.map(function (p) { return h`<p class="step-body">${p}</p>`; })}
        ${step.facts.length ? h`
          <div class="step-facts">
            ${step.facts.map(function (f) {
              return h`<div class="check-fact">
                         <span class="fact-label">${f.label}</span>
                         <span class="fact-value">${f.value}</span>
                       </div>`;
            })}
          </div>` : ""}
        ${step.candidates.length ? h`
          <div class="step-cands">
            ${step.candidates.map(function (c) {
              return h`<div class="cand-row" data-tone="${c.tone}">
                         <span class="cand-name">${c.name}</span>
                         <span class="cand-close">${c.closeness}</span>
                         <span class="cand-standing">${c.standing}</span>
                       </div>`;
            })}
          </div>` : ""}
        ${step.side_by_side.length ? comparison(step) : ""}
        ${step.suggestion ? h`
          <div class="inv-suggest">
            <p class="suggest-label">${step.suggestion.heading}</p>
            <p class="suggest-verdict">${step.suggestion.verdict}</p>
            <p class="suggest-why">${step.suggestion.reasoning}</p>
            ${step.suggestion.checks.length ? h`
              <ul class="suggest-checks">
                ${step.suggestion.checks.map(function (c) {
                  return h`<li>${c}</li>`;
                })}
              </ul>` : ""}
            <p class="small">${step.suggestion.caveat}</p>
          </div>` : ""}
      </li>`;
  }

  function renderCheckView(inv) {
    ui = inv.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${inv.workspace}</div>
      </header>

      <button type="button" class="back">${inv.back}</button>
      <h1 class="greeting">${inv.heading}</h1>

      <ol class="inv">
        ${inv.steps.map(checkStep)}
        <li class="inv-verdict" data-tone="${inv.tone}">
          <p class="verdict-line">${inv.verdict}</p>
          ${inv.explanation.map(function (p) {
            return h`<p class="verdict-why">${p}</p>`;
          })}
          ${inv.files.length ? h`
            <h2 class="sub">${inv.next_heading}</h2>
            ${fileRows(inv.files)}` : ""}
        </li>
      </ol>`);

    looking("party", inv.entity_id, inv.who);
    root.querySelector(".back").addEventListener("click", function () {
      openParty(inv.entity_id);
    });
    Array.prototype.forEach.call(
      root.querySelectorAll(".file-row"), function (el) {
        el.addEventListener("click", function () {
          openCase(el.getAttribute("data-file"));
        });
      });
  }


  /* ---------- bringing a spreadsheet in ---------- */

  /* Refusal-first, one page, one write. The server reads the file and
     answers with everything it understood -- columns used, columns left
     alone, rows that would be rejected and why -- and nothing is written
     until the person confirms a sentence that restates the consequence.
     There is no mapping UI on purpose: a mapping that can be fiddled until
     the errors disappear is a guess wearing a interface, and the remedy
     for a misread column is the file itself. */
  function openImport() {
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${person}</div>
      </header>
      <button type="button" class="back">${ui.back_to_queue}</button>
      <h1 class="greeting">${ui.import_heading}</h1>
      <p class="import-lead">${ui.import_lead}</p>
      <div class="dropzone">
        <input type="file" id="sheet-file"
               accept=".csv,.xlsx,.txt,text/csv" hidden>
        <button type="button" class="choose">${ui.import_choose}</button>
        <p class="small drop-hint">${ui.import_drop}</p>
        <p class="small templates">${ui.import_templates}
          <a href="/api/imports/template?sheet=parties" download>${
            ui.import_template_parties}</a> \u00b7
          <a href="/api/imports/template?sheet=payments" download>${
            ui.import_template_payments}</a>
        </p>
      </div>
      <p class="note problem" hidden></p>`);

    root.querySelector(".back").addEventListener("click", function () {
      load();
    });
    var input = document.getElementById("sheet-file");
    root.querySelector(".choose").addEventListener("click", function () {
      input.click();
    });
    input.addEventListener("change", function () {
      if (input.files.length) { uploadSheet(input.files[0], ""); }
      /* Cleared so that choosing the same file again after a refusal still
         raises a change event: the browser fires nothing when the chosen
         path has not changed, and the officer's second attempt at the file
         they just fixed would appear to do nothing at all. */
      input.value = "";
    });

    /* A page that looks like a drop target has to be one. Without these the
       browser navigates away from the workspace to display the dropped
       spreadsheet, which loses the officer's place entirely. */
    var zone = root.querySelector(".dropzone");
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.add("over");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.remove("over");
      });
    });
    zone.addEventListener("drop", function (event) {
      var dropped = event.dataTransfer && event.dataTransfer.files;
      if (dropped && dropped.length) { uploadSheet(dropped[0], ""); }
    });
  }

  function uploadSheet(file, sheet) {
    /* The last .problem on the page: the refusal view and the report view
       each carry their own, and an error raised from the second must not
       be written into the first, where nobody would see it. */
    function sayProblem(text) {
      var all = root.querySelectorAll(".problem");
      var line = all[all.length - 1];
      if (line) {
        line.textContent = text;
        line.hidden = false;
      }
    }

    var all = root.querySelectorAll(".problem");
    if (all.length) {
      all[all.length - 1].hidden = true;
      all[all.length - 1].textContent = "";
    }
    var choose = root.querySelector(".choose");
    if (choose) {
      choose.disabled = true;
      choose.textContent = ui.import_reading;
    }
    fetch("/api/imports" + (sheet ? "?sheet=" + sheet : ""), {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Vinzor-Filename": encodeURIComponent(file.name)
      },
      body: file
    }).then(read).then(function (report) {
      renderImportReport(report, file);
    }).catch(function (error) {
      if (choose) {
        choose.disabled = false;
        choose.textContent = ui.import_choose;
      }
      sayProblem(error.handled ? error.message : ui.import_failed);
    });
  }

  function renderImportReport(report, file) {
    ui = report.ui || ui;
    var undecided = Boolean(report.undecided);

    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${person}</div>
      </header>
      <button type="button" class="back">${ui.back_to_queue}</button>

      ${report.refusals.length ? h`
        <h1 class="greeting">${ui.import_refused_heading}</h1>
        <p class="import-lead">${ui.import_refused_lead}</p>
        <div class="refusals">
          ${report.refusals.map(function (r) {
            return h`<p class="refusal">${r}</p>`;
          })}
        </div>
        ${undecided ? h`
          <div class="confirm">
            <button type="button" class="as-parties">${
              ui.import_as_parties}</button>
            <button type="button" class="as-payments">${
              ui.import_as_payments}</button>
          </div>` : h`
          <div class="confirm">
            <button type="button" class="again">${ui.import_another}</button>
          </div>`}
        <p class="note problem" hidden></p>
      ` : h`
        <h1 class="greeting">${report.file}</h1>
        <p class="import-lead">${report.reads_as}</p>

        ${report.notes.length ? h`
          <h3 class="sub">${ui.import_notes_heading}</h3>
          <ul class="todo">${report.notes.map(function (n) {
            return h`<li>${n}</li>`;
          })}</ul>` : ""}

        <h3 class="sub">${ui.import_columns_heading}</h3>
        <div class="map">
          ${report.columns.map(function (c) {
            return h`<div class="map-row">
                       <span class="map-col">${c.column}</span>
                       <span class="map-means">${c.meaning}</span>
                     </div>`;
          })}
        </div>

        ${report.ignored.length ? h`
          <h3 class="sub">${ui.import_ignored_heading}</h3>
          <p class="ignored">${report.ignored.join(" \u00b7 ")}</p>` : ""}

        ${report.rejected.length ? h`
          <h3 class="sub">${ui.import_rejected_heading}</h3>
          <div class="map">
            ${report.rejected.map(function (r) {
              return h`<div class="map-row">
                         <span class="map-col">${ui.import_row} ${
                           r.row}</span>
                         <span class="map-means">${r.because}</span>
                       </div>`;
            })}
          </div>
          ${report.rejected_more
            ? h`<p class="small">${report.rejected_more}</p>` : ""}` : ""}

        <p class="consequence">${report.consequence}</p>
        <div class="confirm">
          <button type="button" class="record" ${report.counts.usable ? "" : "disabled"}>${
            report.confirm_label}</button>
          <button type="button" class="cancel">${ui.cancel}</button>
        </div>
        <p class="note problem" hidden></p>
      `}`);

    root.querySelector(".back").addEventListener("click", function () {
      load();
    });
    var again = root.querySelector(".again");
    if (again) { again.addEventListener("click", openImport); }
    var asParties = root.querySelector(".as-parties");
    if (asParties && file) {
      asParties.addEventListener("click", function () {
        uploadSheet(file, "parties");
      });
    }
    var asPayments = root.querySelector(".as-payments");
    if (asPayments && file) {
      asPayments.addEventListener("click", function () {
        uploadSheet(file, "payments");
      });
    }
    var cancel = root.querySelector(".cancel");
    if (cancel) { cancel.addEventListener("click", openImport); }
    var record = root.querySelector(".record");
    if (record) {
      record.addEventListener("click", function () {
        record.disabled = true;
        record.textContent = ui.import_working;
        post("/api/imports/apply", {
          person: person,
          digest: report.digest,
          sheet: report.kind,
          kind: ""
        }).then(renderImportReceipt).catch(function (error) {
          record.disabled = false;
          record.textContent = report.confirm_label;
          var lines = root.querySelectorAll(".problem");
          var last = lines[lines.length - 1];
          if (last) {
            last.textContent = error.handled ? error.message : ui.record_failed;
            last.hidden = false;
          }
        });
      });
    }
  }

  function renderImportReceipt(result) {
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${person}</div>
      </header>
      <h1 class="greeting">${ui.import_heading}</h1>
      <p class="note good">${result.message}</p>
      <p class="progress-line" id="screen-progress"></p>
      <div class="confirm">
        <button type="button" class="back back-main">${ui.back_to_queue}</button>
        <button type="button" class="again cancel">${ui.import_another}</button>
      </div>`);

    root.querySelector(".back-main").addEventListener("click", function () {
      load();
    });
    root.querySelector(".again").addEventListener("click", openImport);
    if (result.progress) { followScreening(result.progress); }
  }

  /* An updating sentence with counts, never a spinner: the run is real
     work over real records, and the officer may leave -- matches land in
     the queue whether anyone watches or not. */
  function followScreening(ref, missed) {
    var line = document.getElementById("screen-progress");
    /* Gone means the officer has moved on; the run continues on the server
       and its matches land in the queue either way, so there is nothing to
       keep polling for. */
    if (!line) { return; }
    get("/api/imports/progress?ref=" + encodeURIComponent(ref))
      .then(function (progress) {
        line.textContent = progress.sentence;
        if (progress.state === "running") {
          setTimeout(function () { followScreening(ref, 0); }, 1200);
        }
      })
      .catch(function () {
        /* A restarted server forgets which runs were in flight. After a few
           silent tries, say so once rather than asking forever. */
        var tries = (missed || 0) + 1;
        if (tries > 4) {
          line.textContent = ui.import_lost_progress;
          return;
        }
        setTimeout(function () { followScreening(ref, tries); }, 2500);
      });
  }


  /* ---------- what the firm can show for itself ---------- */

  /* A report rather than a dashboard: no gauges, no dials, no score. Every
     section is a lead sentence over ruled rows, because that is what
     survives being printed and handed to a board or an inspector -- and
     printing it is the point, so the stylesheet has a print rule and the
     page has a button that reaches it. */
  function openReports(since) {
    get("/api/reports" + (since ? "?since=" + encodeURIComponent(since) : ""))
      .then(function (r) { renderReports(r, since); })
      .catch(function () {
        mount(root, h`<p class="note bad">${ui.load_failed}</p>`);
      });
  }

  function reportSection(section) {
    return h`
      <section class="rep-section">
        <h2 class="rep-head">${section.heading}</h2>
        <p class="rep-lead">${section.lead}</p>
        ${section.rows.length ? h`
          <div class="rep-rows">
            ${section.rows.map(function (row) {
              return h`<div class="rep-row" data-tone="${row.tone}">
                         <span class="rep-what">${row.what}</span>
                         <span class="rep-count">${row.count}</span>
                         <span class="rep-note">${row.note}</span>
                       </div>`;
            })}
          </div>` : ""}
        ${section.tail ? h`<p class="rep-tail">${section.tail}</p>` : ""}
      </section>`;
  }

  function renderReports(r, since) {
    ui = r.ui || ui;
    mount(root, h`
      <header class="masthead">
        <div class="wordmark">${ui.wordmark}</div>
        <div class="whoami">${person} · ${r.workspace}</div>
      </header>

      <button type="button" class="back no-print">${r.back}</button>

      <article class="report">
        <h1 class="rep-title">${r.title}</h1>
        <p class="rep-covering">${r.workspace} · ${r.covering}</p>

        <div class="rep-periods no-print">
          <span class="rep-periods-label">${ui.report_period_heading}</span>
          ${r.periods.map(function (p) {
            return h`<button type="button" class="rep-period"
                             aria-pressed="${String(p.since === since)}"
                             data-since="${p.since}">${p.label}</button>`;
          })}
        </div>

        <div class="rep-summary">
          ${r.summary.map(function (line) { return h`<p>${line}</p>`; })}
        </div>

        ${r.sections.map(reportSection)}

        <p class="rep-assurance">${r.assurance}</p>
        <p class="rep-printed">${r.printed}</p>

        <div class="confirm no-print">
          <button type="button" class="record print">${r.print_label}</button>
          <button type="button" class="record ghost export"
                  data-export="">${ui.export_book}</button>
        </div>
        <p class="rep-printed no-print">${ui.export_note}</p>
      </article>`);

    root.querySelector(".back").addEventListener("click", function () {
      load();
    });
    root.querySelector(".print").addEventListener("click", function () {
      window.print();
    });
    wireExport(root);
    root.querySelectorAll(".rep-period").forEach(function (button) {
      button.addEventListener("click", function () {
        openReports(button.getAttribute("data-since"));
      });
    });
    looking("reports", "the report", ui.open_reports.toLowerCase());
  }

  /* ---------- behaviour ---------- */

  function wire(brief) {
    looking("queue", "the list", ui.ask_here_queue);

    var finder = document.getElementById("find");
    if (finder) {
      finder.addEventListener("click", function () { searchParties(lastQuery); });
    }

    var screen = document.getElementById("screening");
    if (screen) { screen.addEventListener("click", openScreening); }

    var importer = document.getElementById("import-sheet");
    if (importer) { importer.addEventListener("click", openImport); }

    var toAgents = document.getElementById("agents");
    if (toAgents) {
      toAgents.addEventListener("click", function () { openAgents(); });
    }

    var reports = document.getElementById("reports");
    if (reports) {
      reports.addEventListener("click", function () { openReports(""); });
    }

    var reg = document.getElementById("regulatory");
    if (reg) { reg.addEventListener("click", openRegulatory); }

    var swap = document.getElementById("switch");
    if (swap) {
      swap.addEventListener("click", function () {
        openGroups = {};
        signOut();
      });
    }

    root.querySelectorAll(".group").forEach(function (g) {
      var index = g.getAttribute("data-index");
      g.querySelector(".head").addEventListener("click", function () {
        var isOpen = g.classList.toggle("open");
        openGroups[index] = isOpen;
        g.querySelector(".head").setAttribute("aria-expanded", String(isOpen));
      });

      /* Fetch the rest of THIS group, not the whole queue. The group stays
         open across the reload because openGroups is keyed by position and
         the buckets sort identically for the same data.                     */
      var showAll = g.querySelector(".show-all");
      if (showAll) {
        showAll.addEventListener("click", function () {
          openGroups[index] = true;
          showAll.disabled = true;
          load(showAll.getAttribute("data-ref"));
        });
      }
    });

    root.querySelectorAll(".item").forEach(function (el) {
      wireItem(el, brief);
    });
  }

  /* Shared by the queue and the file page. On the queue the panel sits
     inside the item; on a file it sits above the decision block, so it is
     wired by case id rather than by position -- which is also why "Use this
     wording" silently did nothing on the file page the first time it shipped.
  */
  function wirePanel(panel, file) {
    if (!panel) { return; }
    var use = panel.querySelector(".use");
    var own = panel.querySelector(".own");
    var wording = panel.querySelector(".wording").textContent;
    use.addEventListener("click", function () {
      drafts[file] = { wording: wording, used: "ACCEPTED" };
      use.setAttribute("aria-pressed", "true");
      own.setAttribute("aria-pressed", "false");
      panel.classList.add("taken");
    });
    own.addEventListener("click", function () {
      drafts[file] = { wording: "", used: "REJECTED" };
      own.setAttribute("aria-pressed", "true");
      use.setAttribute("aria-pressed", "false");
      panel.classList.remove("taken");
    });
  }

  function wireItem(el, brief) {
    var opener = el.querySelector(".open-file");
    if (opener) {
      opener.addEventListener("click", function () {
        openCase(opener.getAttribute("data-file"));
      });
    }
    var buttons = el.querySelectorAll(".choice");
    var pending = el.querySelector(".pending");
    var file = el.getAttribute("data-file");
    var panel = el.querySelector(".suggest");

    wirePanel(panel, file);

    if (!brief.can_decide) {
      buttons.forEach(function (b) { b.disabled = true; });
      if (panel) {
        panel.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
      }
      return;
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        buttons.forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
        button.setAttribute("aria-pressed", "true");
        openReason(el, pending, button, brief);
      });
    });
  }

  function openReason(el, pending, button, brief) {
    var choice = null;
    var fits = [];
    (brief.groups || []).forEach(function (g) {
      g.items.forEach(function (i) {
        if (i.case_id === el.getAttribute("data-file")) {
          i.choices.forEach(function (c) {
            if (c.outcome === button.getAttribute("data-outcome")) { choice = c; }
          });
          fits = (i.reasons || []).filter(function (r) {
            return r.when === button.getAttribute("data-outcome");
          });
        }
      });
    });

    /* The confirming click, not just the first one, is what actually closes
       a file -- permanently, per DESIGN.md, with no undo. A button that just
       says "Record it" asks for a second click of faith in whatever the
       first click was; restating the specific action here is exactly what
       NN/g's guidance on confirmation dialogs calls for ("restate the
       user's request... with specific information", "action-specific
       labels" over a generic yes/no) so a slip on the first click is still
       visible on the second. */
    var recordLabel = choice
      ? ui.confirm_prefix + " " + choice.label
      : ui.confirm_plain;
    mount(pending, h`
      <div class="reason">
        ${fits.length ? h`
          <label for="why-code">${ui.reason_pick}</label>
          <select id="why-code">
            <option value=""></option>
            ${fits.map(function (r) {
              return h`<option value="${r.code}">${r.label}</option>`;
            })}
          </select>` : ""}
        <label for="why">${ui.why}</label>
        <textarea id="why" rows="3"></textarea>
      </div>
      ${choice ? h`<p class="note">${choice.means}</p>` : ""}
      <div class="confirm">
        <button type="button" class="record">${recordLabel}</button>
        <button type="button" class="cancel">${ui.cancel}</button>
      </div>
      <p class="note problem" hidden></p>`);

    var box = pending.querySelector("textarea");
    var problem = pending.querySelector(".problem");
    var taken = drafts[el.getAttribute("data-file")];

    /* If they took the suggested wording, it starts in the box as theirs to
       change. The moment they change a character it stops being "accepted"
       and becomes "edited" — nobody is asked to self-report that.           */
    if (taken && taken.wording) {
      box.value = taken.wording;
      /* Recompute on every keystroke AND reset now. Cancelling the panel and
         reopening it used to leave "EDITED" behind from the previous attempt,
         so a decision that used the suggestion word for word was recorded
         permanently as an edit -- understating how often it was accepted. */
      taken.used = "ACCEPTED";
      box.addEventListener("input", function () {
        taken.used = box.value === taken.wording ? "ACCEPTED" : "EDITED";
      });
    }
    box.focus();

    pending.querySelector(".cancel").addEventListener("click", function () {
      pending.innerHTML = "";
      el.querySelectorAll(".choice").forEach(function (b) {
        b.setAttribute("aria-pressed", "false");
      });
    });

    pending.querySelector(".record").addEventListener("click", function () {
      var record = pending.querySelector(".record");
      record.disabled = true;
      problem.hidden = true;
      var draft = drafts[el.getAttribute("data-file")];
      post("/api/decisions", {
        person: brief.person,
        file: el.getAttribute("data-file"),
        outcome: button.getAttribute("data-outcome"),
        reason: box.value,
        used: draft ? draft.used : "NONE",
        code: (pending.querySelector("#why-code") || {}).value || ""
      }).then(function (result) {
        el.classList.add("done");
        el.querySelector(".choices").remove();
        mount(pending, h`<p class="note good">${result.message}</p>`);
        refreshCounts();
      }).catch(function (error) {
        record.disabled = false;
        problem.hidden = false;
        problem.className = "note problem bad";
        problem.textContent = error.handled ? error.message
          : ui.record_failed;
      });
    });
  }

  function refreshCounts() {
    get("/api/briefing?person=" + encodeURIComponent(person)).then(function (brief) {
      var tally = root.querySelector(".tally");
      var note = root.querySelector(".settled-note");
      if (tally) { mount(tally, statTiles(brief)); }
      if (note) { note.textContent = brief.nothing_needed; }
    });
  }

  if (person) { load(); } else { signIn(); }
})();
