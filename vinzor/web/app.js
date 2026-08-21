/* Vinzor — the browser side.

   This file renders and posts. It holds no compliance wording of its own:
   every sentence about a party, a finding, a rule or a decision arrives from
   the server, out of briefing.py, so the screen and the file handed to a
   regulator cannot drift apart. What this file is allowed to name is its own
   furniture — a nav item, a column heading, an empty state — and even those
   prefer the server's word where the server has one (see `word` below).

   Rendering is done with the `h` tagged template, and that choice is
   load-bearing rather than stylistic: escaping is what happens by default and
   `raw()` is the explicit, greppable exception. One forgotten escape on a
   screen that renders watchlist captions and investor names is a script
   injection into a compliance record.

   Nothing here animates over a wait. The live run shows the state the server
   reports for each step and nothing else: a step with no recorded outcome is
   shown as not yet run, however long it has been sitting there. */

(function () {
  "use strict";

  var app = document.getElementById("app");

  /* Every label the server owns. Populated before anything renders — both
     read routes carry it. Never edited here. */
  var ui = {};

  var person = sessionStorage.getItem("vinzor.person") || "";
  var guarded = false;
  var workspace = "";
  var canDecide = false;
  var readOnlyBecause = "";

  /* The morning, fetched once and shared by the home strip and the list. */
  var morning = null;

  /* What the officer has typed into the wizard during this sitting. Nothing
     more: it is cleared on reload and never stands in for a record. */
  var proposal = { name: "", kind: "" };

  /* The one live poll. Cleared on every route change. */
  var poller = null;

  /* ---------- rendering ---------- */

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Markup that is already safe because `h` produced it. The only way to get
     an unescaped value into the page. */
  function raw(html) { return { __html: String(html) }; }

  function flatten(value) {
    if (value === null || value === undefined || value === false) { return ""; }
    if (Array.isArray(value)) { return value.map(flatten).join(""); }
    if (typeof value === "object" && typeof value.__html === "string") {
      return value.__html;
    }
    return esc(value);
  }

  function h(strings) {
    var out = strings[0];
    for (var i = 1; i < arguments.length; i++) {
      out += flatten(arguments[i]) + strings[i];
    }
    return raw(out);
  }

  function mount(element, node) { if (element) { element.innerHTML = flatten(node); } }

  function on(scope, selector, event, handler) {
    (scope || document).querySelectorAll(selector).forEach(function (el) {
      el.addEventListener(event, handler);
    });
  }

  /* Bar widths are applied through the DOM rather than as an attribute in
     the markup: the page's Content-Security-Policy admits no attribute
     styling, and a bar that silently renders at zero width is worse than no
     bar at all. */
  function applyShares(scope) {
    (scope || document).querySelectorAll("[data-share]").forEach(function (bar) {
      bar.style.width = bar.getAttribute("data-share") + "%";
    });
  }

  /* ---------- the server's words, and this file's own furniture ---------- */

  /* A label the server has a word for uses the server's word. Where it has
     none yet, the fallback here is furniture — the name of a button or a
     column — and never a sentence about compliance, a finding, a rule or a
     risk. Those may only ever be rendered, never composed. */
  function word(key, fallback) {
    var value = ui[key];
    return (typeof value === "string" && value) ? value : fallback;
  }

  /* A defence against implementation vocabulary reaching a reader. Values
     that arrive inside an open-ended structure (an ownership row, a check
     result) are passed through this before being shown: an identifier, an
     enum value or a digest is dropped rather than printed. */
  function machineish(value) {
    var text = String(value == null ? "" : value).trim();
    if (!text) { return true; }
    if (/^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/.test(text)) { return true; }
    if (/^[a-z0-9]+(_[a-z0-9]+)+$/.test(text)) { return true; }
    if (/^[0-9a-f]{8,}$/i.test(text)) { return true; }
    if (/^[a-z]{2,4}[_-][A-Za-z0-9]{2,}$/.test(text)) { return true; }
    return false;
  }

  function shown(value) { return machineish(value) ? "" : String(value); }

  /* A whole sentence, or nothing.

     Everything a person reads is supposed to come out of briefing.py, where a
     test sweeps it for leaked identifiers. One sentence on the onboarding
     record does not: the ownership walk explains itself in its own words and
     names the party by the reference the records are keyed by. Printing that
     would put a machine address in front of an officer, so a sentence with
     one in it is dropped here rather than shown or, worse, quietly edited.

     TODO — the remedy is in briefing.py: word the ownership conclusion there,
     naming the party, and this guard becomes dead code. */
  function cleanLines(lines) {
    var kept = [];
    (lines || []).forEach(function (line) {
      var text = cleanSentence(line);
      if (text) { kept.push(text); }
    });
    return kept;
  }

  function cleanSentence(text) {
    var sentence = String(text == null ? "" : text).trim();
    if (!sentence) { return ""; }
    var tokens = sentence.split(/\s+/);
    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i].replace(/^[^\w]+|[^\w]+$/g, "");
      if (!token) { continue; }
      if (token.indexOf("_") >= 0) { return ""; }
      if (/^[0-9a-f]{12,}$/i.test(token)) { return ""; }
    }
    return sentence;
  }

  /* Machine hints for colour. Never shown as text — the sentence beside them
     is what a person reads. */
  var TONE_OF_SEVERITY = {
    CRITICAL: "stop", HIGH: "today", MEDIUM: "week", LOW: "later"
  };
  var TONE_OF_OUTCOME = {
    found: "today", failed: "stop", skipped: "later", done: "good"
  };

  function severityTone(value) {
    return TONE_OF_SEVERITY[String(value || "").toUpperCase()] || "later";
  }
  function outcomeTone(value) {
    return TONE_OF_OUTCOME[String(value || "").toLowerCase()] || "plain";
  }

  /* Some routes hand back the kind of party as the value the records are
     keyed by. That is not a word anybody says, so it is turned back into one
     here and never printed as it arrived. */
  function kindWord(value) {
    var key = String(value || "").toUpperCase();
    for (var i = 0; i < KINDS.length; i++) {
      if (KINDS[i].value === key) {
        return word("party_kind_" + key, KINDS[i].name);
      }
    }
    return shown(value);
  }

  /* ---------- talking to the server ---------- */

  function get(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(readReply);
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(readReply);
  }

  /* A file goes up as its own bytes rather than wrapped in JSON: a scan is
     megabytes and the JSON route is capped far below that. Raw bytes are
     also a shape no plain cross-site form can send, which is the same CSRF
     property the spreadsheet import route relies on. */
  function postBytes(url, file) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file
    }).then(readReply);
  }

  function readReply(response) {
    return response.json()
      .catch(function () { return {}; })
      .then(function (data) {
        if (response.ok) { return data; }
        var error = new Error(data.message || "");
        error.handled = Boolean(data.message);
        error.status = response.status;
        throw error;
      });
  }

  function said(error) {
    return error && error.handled ? error.message : word("load_failed", "");
  }

  function absorb(payload) {
    if (!payload) { return payload; }
    if (payload.ui) { ui = payload.ui; }
    if (payload.workspace) { workspace = payload.workspace; }
    if (typeof payload.can_decide === "boolean") { canDecide = payload.can_decide; }
    if (typeof payload.read_only_because === "string") {
      readOnlyBecause = payload.read_only_because;
    }
    return payload;
  }

  /* ---------- where we are ---------- */

  function here() {
    var parts = (location.hash || "").replace(/^#\/?/, "").split("/");
    var cleaned = [];
    for (var i = 0; i < parts.length; i++) {
      if (parts[i]) { cleaned.push(decodeURIComponent(parts[i])); }
    }
    return { name: cleaned[0] || "home", a: cleaned[1] || "", b: cleaned[2] || "" };
  }

  function go(hash) {
    if (location.hash === hash) { show(); } else { location.hash = hash; }
  }

  function stopPolling() {
    if (poller) { clearTimeout(poller); poller = null; }
  }

  /* ---------- the frame ---------- */

  var NAV = [
    { at: "home", hash: "#/", key: "nav_home", fallback: "Home" },
    { at: "onboard", hash: "#/onboard", key: "onboard_start",
      fallback: "Onboard an investor" },
    { at: "queue", hash: "#/queue", key: "nav_queue", fallback: "Your list" },
    { at: "parties", hash: "#/parties", key: "find_party", fallback: "Parties" },
    { at: "ask", hash: "#/ask", key: "ask_go", fallback: "Ask" }
  ];

  function frame(at) {
    mount(app, h`
      <nav class="rail">
        <div class="rail-mark">${word("wordmark", "Vinzor")}</div>
        <div class="rail-place">${workspace}</div>
        <div class="rail-nav">
          ${NAV.map(function (entry) {
            var current = entry.at === at;
            return h`<a href="${entry.hash}"${
              current ? raw(' aria-current="page"') : ""
            }>${word(entry.key, entry.fallback)}</a>`;
          })}
        </div>
        <div class="rail-foot">
          <div class="rail-who">${person}</div>
          <button type="button" class="btn-link tiny" id="leave">${
            guarded ? word("sign_out", "") : word("switch_user", "")
          }</button>
        </div>
      </nav>
      <main class="sheet" id="sheet" tabindex="-1"></main>`);
    var leave = document.getElementById("leave");
    if (leave) { leave.addEventListener("click", leaveTheDesk); }
    return document.getElementById("sheet");
  }

  function sheet() { return document.getElementById("sheet"); }

  function busy(where) {
    mount(where, h`<p class="loading">${word("loading", "")}</p>`);
  }

  function failed(where, error) {
    mount(where, h`<p class="note bad">${said(error)}</p>`);
  }

  /* ---------- the door ---------- */

  /* Whether the person at this desk may settle a file is the enrolment's
     answer, not a guess: it decides whether the three decision buttons can
     be pressed at all. Read at the door so that every screen has it,
     including one reached before any file has been opened. */
  function markDecider(session) {
    (session.people || []).forEach(function (entry) {
      if (entry.name === person) { canDecide = !!entry.can_decide; }
    });
  }

  function openDoor() {
    get("/api/session").then(function (session) {
      absorb(session);
      guarded = !!session.needs_password;
      if (session.signed_in_as) {
        person = session.signed_in_as;
        sessionStorage.setItem("vinzor.person", person);
        markDecider(session);
        show();
        return;
      }
      if (guarded) { askForPassword(session); } else { pickAName(session); }
    }).catch(function (error) { failed(app, error); });
  }

  function beginAs(name) {
    person = name;
    sessionStorage.setItem("vinzor.person", person);
    get("/api/session").then(function (session) {
      absorb(session);
      markDecider(session);
      show();
    }).catch(function () { show(); });
  }

  function pickAName(session) {
    mount(app, h`
      <div class="doorway-page">
        <div class="doorway">
          <h1>${word("wordmark", "Vinzor")}</h1>
          <p class="faint small">${session.workspace}</p>
          <div class="who">
            ${(session.people || []).map(function (p) {
              return h`<button type="button" data-person="${p.name}">
                         <span>${p.name}</span>
                         <span class="role">${p.title}</span>
                       </button>`;
            })}
          </div>
          <p class="note bad small prose">${word("no_password_yet", "")}</p>
        </div>
      </div>`);
    on(app, "[data-person]", "click", function (event) {
      beginAs(event.currentTarget.getAttribute("data-person"));
    });
  }

  function askForPassword(session) {
    mount(app, h`
      <div class="doorway-page">
        <div class="doorway card pad">
          <h1>${word("wordmark", "Vinzor")}</h1>
          <p class="faint small">${session.workspace}</p>
          <form autocomplete="on">
            <h2>${word("sign_in_heading", "")}</h2>
            <div>
              <label class="field" for="who">${word("sign_in_name", "")}</label>
              <input id="who" name="username" type="text" autocomplete="username"
                     autocapitalize="words" required>
            </div>
            <div>
              <label class="field" for="secret">${word("sign_in_password", "")}</label>
              <input id="secret" name="password" type="password"
                     autocomplete="current-password" required>
            </div>
            <p class="problem" hidden></p>
            <button type="submit" class="btn btn-primary">${
              word("sign_in_button", "")
            }</button>
          </form>
        </div>
      </div>`);

    var form = app.querySelector("form");
    var problem = form.querySelector(".problem");
    var button = form.querySelector("button");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      problem.hidden = true;
      button.disabled = true;
      button.textContent = word("sign_in_working", "");
      post("/api/sign-in", {
        person: form.querySelector("#who").value,
        password: form.querySelector("#secret").value
      }).then(function (result) {
        beginAs(result.person);
      }).catch(function (error) {
        button.disabled = false;
        button.textContent = word("sign_in_button", "");
        form.querySelector("#secret").value = "";
        problem.textContent = said(error);
        problem.hidden = false;
      });
    });
    form.querySelector("#who").focus();
  }

  function leaveTheDesk() {
    stopPolling();
    morning = null;
    post("/api/sign-out", {}).catch(function () {}).then(function () {
      person = "";
      sessionStorage.removeItem("vinzor.person");
      openDoor();
    });
  }

  /* ---------- the morning, fetched once ---------- */

  function theMorning() {
    if (morning) { return Promise.resolve(morning); }
    return get("/api/briefing?person=" + encodeURIComponent(person))
      .then(function (payload) {
        morning = absorb(payload);
        return morning;
      });
  }

  /* ---------- home ---------- */

  function home() {
    var where = frame("home");
    busy(where);
    theMorning().then(function (brief) {
      mount(where, h`
        <div class="head">
          <h1 class="greeting">${brief.greeting}</h1>
        </div>

        <div class="begin">
          <div class="card begin-primary">
            <p class="eyebrow">${word("onboard_eyebrow", "Start here")}</p>
            <a class="btn btn-primary btn-big" href="#/onboard">${
              word("onboard_start", "Onboard an investor")
            }</a>
            <p class="small soft prose">${
              word("onboard_lead",
                   "One party at a time, in three steps. Nothing is decided for you.")
            }</p>
          </div>
          <div class="card ask-card" id="ask-here"></div>
        </div>

        <ul class="tally" id="tally"></ul>

        <div class="card pad" id="priority"></div>`);

      mount(document.getElementById("tally"), tallyTiles(brief));
      askBox(document.getElementById("ask-here"), false);
      mount(document.getElementById("priority"), prioritySlice(brief));
      on(where, "[data-open-file]", "click", function (event) {
        go("#/queue/" + encodeURIComponent(
          event.currentTarget.getAttribute("data-open-file")));
      });
    }).catch(function (error) { failed(where, error); });
  }

  /* The small honest numbers. Every label and figure is the server's. */
  function tallyTiles(brief) {
    var stats = (brief.dashboard && brief.dashboard.stats) || [];
    if (!stats.length) {
      return (brief.headlines || []).map(function (line) {
        return h`<li><span class="label">${line}</span></li>`;
      });
    }
    return stats.map(function (stat) {
      return h`<li>
                 <span class="count" data-tone="${stat.tone || "plain"}">${stat.value}</span>
                 <span class="label">${stat.label}</span>
               </li>`;
    });
  }

  /* The bottom strip: what is nearest the front of the queue, and a way in.
     Three lines, not a dashboard — the list itself is one click away. */
  function prioritySlice(brief) {
    var groups = brief.groups || [];
    if (!groups.length) {
      return h`<p class="note good">${brief.all_clear || brief.nothing_needed || ""}</p>`;
    }
    var lines = [];
    groups.forEach(function (group) {
      (group.items || []).forEach(function (item) {
        if (lines.length < 4) {
          lines.push({ tone: group.tone, line: item.line || item.headline,
                       urgency: item.urgency || group.urgency, file: item.case_id });
        }
      });
    });
    return h`
      <div class="section-head">
        <h2>${word("nav_queue", "Your list")}</h2>
        <a href="#/queue" class="small">${word("open_queue", "See all of it")}</a>
      </div>
      <ul class="strip">
        ${lines.map(function (line) {
          return h`<li>
                     <span class="dot" data-tone="${line.tone || "later"}"></span>
                     <span class="what">${line.line}</span>
                     <span class="badge" data-tone="${line.tone || "later"}">${line.urgency}</span>
                     ${line.file ? h`<button type="button" class="btn-link small"
                                       data-open-file="${line.file}">${
                       word("open_file", "")
                     }</button>` : ""}
                   </li>`;
        })}
      </ul>`;
  }

  /* ---------- the ask box ---------- */

  function askBox(where, roomy) {
    mount(where, h`
      <div class="spread">
        <h2>${word("ask_heading", "")}</h2>
      </div>
      ${roomy ? h`<p class="small soft prose">${word("ask_lead", "")}</p>` : ""}
      <form class="ask-form">
        <input type="text" id="asked" autocomplete="off"
               placeholder="${word("ask_placeholder", "")}"
               aria-label="${word("ask_heading", "")}">
        <button type="submit" class="btn btn-primary">${word("ask_go", "")}</button>
      </form>
      <div class="ask-tries">
        ${(ui.ask_examples || []).slice(0, roomy ? 4 : 2).map(function (example) {
          return h`<button type="button" data-try="${example}">${example}</button>`;
        })}
      </div>
      <div class="ask-answer" hidden></div>`);

    var form = where.querySelector(".ask-form");
    var box = where.querySelector("#asked");
    var answer = where.querySelector(".ask-answer");

    on(where, "[data-try]", "click", function (event) {
      box.value = event.currentTarget.getAttribute("data-try");
      box.focus();
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var asked = box.value.trim();
      if (!asked) { return; }
      answer.hidden = false;
      mount(answer, h`<p class="faint small">${word("ask_thinking", "")}</p>`);
      post("/api/chat", { asked: asked }).then(function (reply) {
        if (reply.kind === "work" && reply.task_id) {
          mount(answer, h`
            <p class="prose">${reply.said}</p>
            <p><a class="btn" href="#/run/${encodeURIComponent(reply.task_id)}">${
              word("run_watch", "Watch it run")
            }</a></p>`);
          return;
        }
        mount(answer, h`
          <p class="prose">${reply.said}</p>
          ${reply.withheld ? h`<p class="note prose">${reply.withheld}</p>` : ""}
          ${(reply.looked_at && reply.looked_at.length) ? h`
            <p class="tiny faint">${word("ask_looked_at", "")}</p>
            <ul class="bullets tiny">${reply.looked_at.map(function (step) {
              return h`<li>${step}</li>`;
            })}</ul>` : ""}`);
      }).catch(function (error) {
        mount(answer, h`<p class="note bad">${said(error)}</p>`);
      });
    });
  }

  function askScreen() {
    var where = frame("ask");
    mount(where, h`<div class="card ask-card" id="ask-here"></div>`);
    askBox(document.getElementById("ask-here"), true);
  }

  /* ---------- onboarding: step one, who is this ---------- */

  /* The six kinds a party may be. The value is the server's vocabulary and
     is never shown; the name and the line under it prefer the server's word
     and fall back to furniture that describes the choice, not the rules. */
  var KINDS = [
    { value: "PERSON", name: "Person",
      note: "One named individual, investing in their own name." },
    { value: "COMPANY", name: "Company",
      note: "Incorporated, with shareholders behind it." },
    { value: "TRUST", name: "Trust",
      note: "Held by trustees for somebody else's benefit." },
    { value: "PARTNERSHIP", name: "Partnership",
      note: "A firm or LLP, with partners behind it." },
    { value: "FUND", name: "Fund",
      note: "A pooled vehicle investing on behalf of its own investors." },
    { value: "UNINCORPORATED_BODY", name: "Unincorporated body",
      note: "An association, society or club with no separate legal form." }
  ];

  function stepBar(at) {
    var steps = [
      word("onboard_step_who", "Who is this?"),
      word("onboard_step_papers", "What have you got?"),
      word("onboard_step_checks", "The checks")
    ];
    return h`<ul class="steps">
      ${steps.map(function (label, index) {
        var state = index === at ? "now" : (index < at ? "done" : "next");
        return h`<li data-at="${state}">${index + 1}. ${label}</li>`;
      })}
    </ul>`;
  }

  function onboardWho() {
    var where = frame("onboard");
    mount(where, h`
      <div class="wizard ask-one">
        ${stepBar(0)}
        <h1>${word("onboard_step_who", "Who is this?")}</h1>

        <div class="card pad" >
          <label class="field" for="party-name">${word("onboard_name", "Their name")}</label>
          <input type="text" id="party-name" autocomplete="off" value="${proposal.name}">
        </div>

        <h2 class="section-head" >${word("onboard_kind", "What kind of party is this?")}</h2>
        <div class="kinds">
          ${KINDS.map(function (kind) {
            return h`<button type="button" class="kind" data-kind="${kind.value}"
                       aria-pressed="${proposal.kind === kind.value ? "true" : "false"}">
                       <span class="kind-name">${
                         word("party_kind_" + kind.value, kind.name)
                       }</span>
                       <span class="kind-note">${
                         word("party_kind_note_" + kind.value, kind.note)
                       }</span>
                     </button>`;
          })}
        </div>

        <div class="wizard-foot">
          <span class="spacer"></span>
          <p class="problem" hidden></p>
          <button type="button" class="btn btn-primary" id="onward" disabled>${
            word("onboard_next", "Next")
          }</button>
        </div>
      </div>`);

    var name = where.querySelector("#party-name");
    var onward = where.querySelector("#onward");
    var problem = where.querySelector(".problem");

    function settle() {
      onward.disabled = !(name.value.trim() && proposal.kind);
    }
    name.addEventListener("input", function () {
      proposal.name = name.value;
      settle();
    });
    on(where, "[data-kind]", "click", function (event) {
      proposal.kind = event.currentTarget.getAttribute("data-kind");
      where.querySelectorAll("[data-kind]").forEach(function (button) {
        button.setAttribute("aria-pressed",
          button === event.currentTarget ? "true" : "false");
      });
      settle();
    });
    settle();
    name.focus();

    onward.addEventListener("click", function () {
      onward.disabled = true;
      problem.hidden = true;
      /* The party is proposed here, which is what makes the next screen
         possible: what a party owes is a fact about a party, and there is
         nothing to attach a document to until one exists. */
      post("/api/onboarding", {
        name: name.value.trim(),
        kind: proposal.kind
      }).then(function (started) {
        go("#/onboard/" + encodeURIComponent(started.party_id || "") +
           "/" + encodeURIComponent(started.task_id || ""));
      }).catch(function (error) {
        onward.disabled = false;
        problem.hidden = false;
        problem.textContent = said(error);
      });
    });
  }

  /* ---------- onboarding: step two, what have you got ---------- */

  function onboardPapers(partyId, taskId) {
    var where = frame("onboard");
    busy(where);
    var added = [];

    function draw(record) {
      var party = record.party || {};
      var owed = record.outstanding || [];
      mount(where, h`
        <div class="wizard">
          ${stepBar(1)}
          <div class="head">
            <h1>${word("onboard_step_papers", "What have you got?")}</h1>
            <p class="soft">${party.name || ""}</p>
          </div>

          <div class="card pad">
            <div class="drop" id="drop">
              <p>${word("onboard_drop", "Drop documents here")}</p>
              <p class="small">
                <label class="btn" for="pick">${
                  word("onboard_choose", "Choose files")
                }<input type="file" id="pick" multiple></label>
              </p>
            </div>
            <ul class="filed" id="filed"></ul>
          </div>

          <div class="card pad" >
            <div class="section-head">
              <h2>${word("onboard_owed", "Still outstanding")}</h2>
              <span class="badge" data-tone="${owed.length ? "today" : "good"}">${owed.length}</span>
            </div>
            ${owed.length ? h`<ul class="owed">${owed.map(owedRow)}</ul>`
                          : h`<p class="note good">${
                              word("onboard_owed_none",
                                   "Nothing further is outstanding.")
                            }</p>`}
          </div>

          ${(record.not_modelled && record.not_modelled.length) ? h`
            <div class="card pad">
              <h2 class="section-head">${
                word("onboard_not_modelled", "Not checked here")
              }</h2>
              <ul class="bullets small prose">${record.not_modelled.map(function (line) {
                return h`<li>${line}</li>`;
              })}</ul>
            </div>` : ""}

          <div class="wizard-foot">
            <a class="btn" href="#/onboard">${word("onboard_back", "Back")}</a>
            <span class="spacer"></span>
            <a class="btn btn-primary" href="#/checks/${encodeURIComponent(partyId)}/${
              encodeURIComponent(taskId)
            }">${word("onboard_next", "Next")}</a>
          </div>
        </div>`);

      drawFiled();
      wireDrop();
    }

    function owedRow(item) {
      /* The route may hand these back flat or still wrapped around the
         requirement they came from. Both are read the same way. */
      var need = item.requirement || item;
      var unevidenced = item.held_but_unevidenced || need.held_but_unevidenced;
      return h`<li>
        <span class="dot" data-tone="${unevidenced ? "today" : "later"}"></span>
        <div class="owed-body">
          <div class="owed-name">${need.asks_for || ""}</div>
          <div class="owed-why">${need.because || ""}</div>
          ${need.basis ? h`<div class="owed-basis">${need.basis}</div>` : ""}
        </div>
        ${need.mandatory === false ? h`<span class="badge" data-tone="later">${
          word("onboard_practice", "Practice")
        }</span>` : ""}
      </li>`;
    }

    function drawFiled() {
      mount(document.getElementById("filed"), added.map(function (file) {
        return h`<li>
                   <span class="filed-name">${file.name}</span>
                   <span class="filed-state" data-tone="${file.tone}">${file.state}</span>
                 </li>`;
      }));
    }

    function wireDrop() {
      var drop = document.getElementById("drop");
      var pick = document.getElementById("pick");
      if (!drop) { return; }
      ["dragenter", "dragover"].forEach(function (name) {
        drop.addEventListener(name, function (event) {
          event.preventDefault();
          drop.classList.add("over");
        });
      });
      ["dragleave", "drop"].forEach(function (name) {
        drop.addEventListener(name, function () { drop.classList.remove("over"); });
      });
      drop.addEventListener("drop", function (event) {
        event.preventDefault();
        take(event.dataTransfer ? event.dataTransfer.files : []);
      });
      pick.addEventListener("change", function () { take(pick.files); });
    }

    /* Each file is sent, and then the whole record is read back from the
       server. The outstanding list shrinks because the server says it has,
       never because this file counted something. */
    function take(files) {
      var list = Array.prototype.slice.call(files || []);
      if (!list.length) { return; }
      list.forEach(function (file) {
        var row = { name: file.name, state: word("onboard_sending", "…"), tone: "plain" };
        added.push(row);
        drawFiled();
        /* TODO — this route is not yet built. It is the one thing the
           onboarding contract does not yet name: where a document goes.
           Until it exists the reply is a refusal in a sentence, which is
           shown against the file, and nothing on the outstanding list moves. */
        postBytes("/api/onboarding/" + encodeURIComponent(partyId) +
                  "/documents?filename=" + encodeURIComponent(file.name), file)
          .then(function () {
            row.state = word("onboard_added", "Added");
            row.tone = "good";
            drawFiled();
            return reread();
          })
          .catch(function (error) {
            row.state = (error && error.status === 404)
              ? word("onboard_cannot_file", "Not recorded — nothing here can file it yet.")
              : said(error);
            row.tone = "stop";
            drawFiled();
          });
      });
    }

    function reread() {
      return get("/api/onboarding/" + encodeURIComponent(partyId))
        .then(function (record) { draw(absorb(record)); })
        .catch(function () {});
    }

    get("/api/onboarding/" + encodeURIComponent(partyId))
      .then(function (record) { draw(absorb(record)); })
      .catch(function (error) { failed(where, error); });
  }

  /* ---------- onboarding: step three, start the checks ---------- */

  /* One button, and it does what it says: it starts a run, over this party,
     with whatever is now on their file. Pressing it is what makes the next
     screen worth watching — the eight checks are carried out after the
     documents were added, not before. */
  function onboardChecks(partyId, taskId) {
    var where = frame("onboard");
    mount(where, h`
      <div class="wizard ask-one">
        ${stepBar(2)}
        <h1>${word("onboard_step_checks", "The checks")}</h1>
        <p class="prose soft">${word("agents_lead", "")}</p>
        <div class="wizard-foot">
          <a class="btn" href="#/onboard/${encodeURIComponent(partyId)}/${
            encodeURIComponent(taskId)
          }">${word("onboard_back", "Back")}</a>
          <span class="spacer"></span>
          <p class="problem" hidden></p>
          <button type="button" class="btn btn-primary btn-big" id="run-them">${
            word("onboard_run", "Start the checks")
          }</button>
        </div>
      </div>`);

    var button = where.querySelector("#run-them");
    var problem = where.querySelector(".problem");
    button.addEventListener("click", function () {
      button.disabled = true;
      problem.hidden = true;
      button.textContent = word("agents_watching", "");
      /* "onboard" is the name of the job, not a word anybody reads. It is
         sent, never shown. */
      post("/api/tasks", { job: "onboard", party: partyId })
        .then(function (started) {
          go("#/run/" + encodeURIComponent(started.task_id || taskId) +
             "/" + encodeURIComponent(partyId));
        })
        .catch(function (error) {
          button.disabled = false;
          button.textContent = word("onboard_run", "Start the checks");
          problem.hidden = false;
          problem.textContent = said(error);
        });
    });
    button.focus();
  }

  /* ---------- the live run ---------- */

  function runScreen(taskId, partyId) {
    var where = frame("onboard");
    busy(where);
    var first = true;

    function draw(task) {
      var steps = task.plan || [];
      /* Which row is happening now is the server's answer, not a guess: it
         reports the sentence of the step it is on. A step with no recorded
         outcome has not run, and says so however long it has been sitting. */
      var doing = task.running ? (task.now_doing || "") : "";
      var reached = false;

      mount(where, h`
        <div class="run">
          ${partyId ? stepBar(2) : ""}
          <div class="run-head">
            <h1>${task.asked || ""}</h1>
            ${task.about ? h`<p class="soft prose">${task.about}</p>` : ""}
            <div class="run-progress">
              <div class="bar"><i data-share="${task.how_far || 0}"
                                  data-tone="${task.running ? "" : "good"}"></i></div>
              <p class="tiny faint">${task.done_count} / ${task.step_count}</p>
            </div>
          </div>

          <ul class="run-steps">
            ${steps.map(function (step) {
              var finished = !!step.how;
              var running = false;
              if (!finished && !reached && doing && step.says === doing) {
                running = true;
                reached = true;
              }
              var state = finished ? "finished" : (running ? "running" : "waiting");
              var tone = finished ? outcomeTone(step.how)
                                  : (running ? "running" : "waiting");
              return h`<li class="run-step" data-state="${state}">
                <span class="run-mark"><span class="dot" data-tone="${tone}"></span></span>
                <div>
                  <div class="run-agent">${step.agent || ""}</div>
                  <div class="run-says">${step.says || ""}</div>
                  ${finished ? h`
                    <div class="run-found">${cleanSentence(step.headline)}</div>
                    ${cleanLines(step.details).length ? h`
                      <ul class="run-details">${cleanLines(step.details).map(function (line) {
                        return h`<li>${line}</li>`;
                      })}</ul>` : ""}`
                  : h`<div class="run-state">${
                      running ? word("agents_watching", "")
                              : word("run_waiting", "Not started")
                    }</div>`}
                </div>
              </li>`;
            })}
          </ul>

          ${task.running ? "" : h`
            <div class="run-done">
              ${task.outcome ? h`<p class="note prose">${task.outcome}</p>` : ""}
              ${partyId ? h`<p><a class="btn btn-primary btn-big"
                    href="#/report/${encodeURIComponent(partyId)}/${
                      encodeURIComponent(taskId)
                    }">${
                word("run_see_report", "See the report")
              }</a></p>` : ""}
            </div>`}
        </div>`);
      applyShares(where);
      if (first) { first = false; }
    }

    function tick() {
      get("/api/tasks/" + encodeURIComponent(taskId)).then(function (payload) {
        absorb(payload);
        var task = payload.task || {};
        draw(task);
        if (task.running) {
          poller = setTimeout(tick, 1200);
        } else {
          stopPolling();
        }
      }).catch(function (error) {
        stopPolling();
        failed(where, error);
      });
    }

    tick();
  }

  /* ---------- the report ---------- */

  function reportScreen(partyId, taskId) {
    var where = frame("onboard");
    busy(where);

    var record = null;
    var files = [];
    var run = null;

    get("/api/onboarding/" + encodeURIComponent(partyId))
      .then(function (payload) {
        record = absorb(payload);
        var findings = record.findings || [];
        /* Each finding's own file carries the evidence and the clause behind
           it, already written for a reader. Fetched alongside the report
           rather than composed here, because this file may not write a
           sentence about a finding. */
        return Promise.all(findings.map(function (finding) {
          if (!finding.case_id) { return Promise.resolve(null); }
          return get("/api/cases/" + encodeURIComponent(finding.case_id))
            .catch(function () { return null; });
        }));
      })
      .then(function (fetched) {
        files = fetched || [];
        /* What was checked, and against what — including the checks that
           found nothing, which is the part an inspector asks for. Where the
           record states it, that is used. Where it does not, it is read off
           the run that produced this report: the same eight steps, and the
           same sentences they recorded as they finished. */
        if ((record.checks || []).length || !taskId) { return null; }
        return get("/api/tasks/" + encodeURIComponent(taskId))
          .catch(function () { return null; });
      })
      .then(function (payload) {
        run = (payload && payload.task) ? payload.task : null;
        /* The three things only a person may do, and the sentence about
           permanence above them, are the product's own words wherever it has
           already written them. Never composed here. */
        if (wordsForDeciding(record, files).options.length) { return null; }
        return theMorning().catch(function () { return null; });
      })
      .then(function () { drawReport(where, record, files, run); })
      .catch(function (error) { failed(where, error); });
  }

  /* The three choices and the permanence sentence, taken from whichever file
     the server has already written them into: this one, an open file on this
     party, or the list. This browser never writes them. */
  function wordsForDeciding(record, files) {
    var decision = (record && record.decision) || {};
    var options = asOptions(decision.options);
    var permanence = decision.recorded_as || "";

    (files || []).forEach(function (file) {
      if (!file) { return; }
      if (!options.length) { options = asOptions(file.choices); }
      if (!permanence && file.recorded_as) { permanence = file.recorded_as; }
    });
    if ((!options.length || !permanence) && morning) {
      (morning.groups || []).forEach(function (group) {
        (group.items || []).forEach(function (item) {
          if (!options.length) { options = asOptions(item.choices); }
          if (!permanence && item.recorded_as) { permanence = item.recorded_as; }
        });
      });
    }
    return { options: options, permanence: permanence };
  }

  function asOptions(choices) {
    return (choices || []).filter(function (choice) {
      return choice && choice.label && choice.outcome;
    }).map(function (choice) {
      return { label: choice.label, means: choice.explains || choice.means || "",
               outcome: choice.outcome };
    });
  }

  /* Everything that ran, including what it found nothing in. */
  function checkRows(record, run) {
    if ((record.checks || []).length) {
      return {
        middle: word("report_col_source", "Against"),
        rows: record.checks.map(function (check) {
          return { what: shown(check.what), middle: shown(check.source),
                   said: cleanSentence(check.said), tone: outcomeTone(check.outcome),
                   details: [] };
        })
      };
    }
    if (!run) { return { middle: "", rows: [] }; }
    return {
      middle: word("report_col_did", "What it did"),
      rows: (run.plan || []).filter(function (step) {
        return !!step.how;
      }).map(function (step) {
        return { what: step.agent || "", middle: step.says || "",
                 said: cleanSentence(step.headline), tone: outcomeTone(step.how),
                 details: cleanLines(step.details) };
      })
    };
  }

  function drawReport(where, record, files, run) {
    var party = record.party || {};
    var checked = checkRows(record, run);
    var owed = record.outstanding || [];
    var findings = record.findings || [];
    var ownership = record.ownership || {};
    var deciding = wordsForDeciding(record, files);

    mount(where, h`
      <div class="report">
        <div class="head">
          <h1>${party.name || ""}</h1>
          <p class="soft">${kindWord(party.kind)}</p>
        </div>

        <section>
          <h2 class="section-head">${
            word("report_checked", "What was checked, and against what")
          }</h2>
          ${checked.rows.length ? h`
            <div class="table-wrap">
              <table class="grid">
                <thead><tr>
                  <th>${word("report_col_check", "Check")}</th>
                  <th>${checked.middle}</th>
                  <th>${word("report_col_result", "What it found")}</th>
                </tr></thead>
                <tbody>${checked.rows.map(function (row) {
                  return h`<tr>
                    <td>${row.what}</td>
                    <td>${row.middle}</td>
                    <td><span class="dot" data-tone="${row.tone}"></span>
                        ${row.said}
                        ${row.details.length ? h`<ul class="run-details">${
                          row.details.map(function (line) { return h`<li>${line}</li>`; })
                        }</ul>` : ""}</td>
                  </tr>`;
                })}</tbody>
              </table>
            </div>` : h`<p class="empty">${
              word("report_checked_none", "Nothing has been run for this party yet.")
            }</p>`}
        </section>

        <section>
          <h2 class="section-head">${
            word("report_outstanding", "What is still outstanding")
          }</h2>
          ${owed.length ? h`<ul class="owed">${owed.map(function (item) {
            var need = item.requirement || item;
            var unevidenced = item.held_but_unevidenced || need.held_but_unevidenced;
            return h`<li>
              <span class="dot" data-tone="${unevidenced ? "today" : "later"}"></span>
              <div class="owed-body">
                <div class="owed-name">${need.asks_for || ""}</div>
                <div class="owed-why">${need.because || ""}</div>
                ${need.basis ? h`<div class="owed-basis">${need.basis}</div>` : ""}
              </div>
            </li>`;
          })}</ul>` : h`<p class="note good">${
            word("onboard_owed_none", "Nothing further is outstanding.")
          }</p>`}
          ${(record.not_modelled && record.not_modelled.length) ? h`
            <h3 class="section-head">${
              word("onboard_not_modelled", "Not checked here")
            }</h3>
            <ul class="bullets small prose">${record.not_modelled.map(function (line) {
              return h`<li>${line}</li>`;
            })}</ul>` : ""}
        </section>

        <section>
          <h2 class="section-head">${word("report_findings", "What was found")}</h2>
          ${findings.length ? findings.map(function (finding, index) {
            var file = (files || [])[index];
            return h`<div class="finding" data-tone="${severityTone(finding.severity)}">
              <h3>${cleanSentence(finding.summary) || (file && file.headline) || ""}</h3>
              ${(file && file.because) ? h`<div class="because prose">${
                file.because.map(function (line) { return h`<p>${line}</p>`; })
              }</div>` : ""}
              ${(file && file.to_close_this && file.to_close_this.length) ? h`
                <p class="tiny eyebrow">${word("to_close_heading", "")}</p>
                <ul class="bullets small prose">${file.to_close_this.map(function (line) {
                  return h`<li>${line}</li>`;
                })}</ul>` : ""}
              ${clauseTags(finding, file)}
            </div>`;
          }) : h`<p class="note good">${
            word("report_findings_none", "—")
          }</p>`}
        </section>

        <section>
          <h2 class="section-head">${
            word("report_ownership", "Who is behind this party")
          }</h2>
          ${ownershipSaid(ownership) ? h`<p class="prose">${
            ownershipSaid(ownership)
          }</p>` : ""}
          ${ownerChain(ownership)}
          ${(!ownershipSaid(ownership) && !((ownership && ownership.owners) || []).length)
            ? h`<p class="empty">${
                word("report_ownership_none", "Nothing about ownership is on the record.")
              }</p>` : ""}
          ${cycleLines(ownership).length ? h`
            <ul class="bullets small prose">${cycleLines(ownership).map(function (line) {
              return h`<li>${line}</li>`;
            })}</ul>` : ""}
          ${ownership && ownership.caveat ? h`<p class="note prose">${
            ownership.caveat
          }</p>` : ""}
        </section>

        <div id="the-decision"></div>
      </div>`);

    decisionBlock(document.getElementById("the-decision"), {
      heading: word("report_decision", "What only a person may now do"),
      permanence: deciding.permanence,
      options: deciding.options,
      reasons: [],
      record: function (outcome, reason, code) {
        return recordOnboardingDecision(record, record.decision || {},
                                        outcome, reason, code);
      }
    });
  }

  /* The ownership answer as a sentence. The machine-readable conclusion beside
     it is a value the records are keyed by and is never printed. */
  function ownershipSaid(ownership) {
    if (!ownership) { return ""; }
    return cleanSentence(ownership.explains) || shown(ownership.conclusion);
  }

  /* A circular holding, where the walk found one, and only where it came back
     as something a person can read. A list of references is not. */
  function cycleLines(ownership) {
    var lines = [];
    ((ownership && ownership.cycles) || []).forEach(function (cycle) {
      var text = "";
      if (typeof cycle === "string") {
        text = shown(cycle);
      } else if (cycle && typeof cycle === "object" && !Array.isArray(cycle)) {
        text = shown(cycle.summary || cycle.said || cycle.says || "");
      }
      if (text) { lines.push(text); }
    });
    return lines;
  }

  function clauseTags(finding, file) {
    var tags = [];
    (finding.clauses || []).forEach(function (clause) {
      var text = typeof clause === "string" ? clause : (clause.clause || "");
      if (text) { tags.push(text); }
    });
    if (!tags.length && file && file.rules) {
      file.rules.forEach(function (rule) { if (rule.clause) { tags.push(rule.clause); } });
    }
    if (!tags.length) { return ""; }
    return h`<div class="clauses">${tags.map(function (tag) {
      return h`<span class="clause">${word("clause_prefix", "")} ${tag}</span>`;
    })}</div>`;
  }

  function ownerChain(ownership) {
    var owners = ((ownership && ownership.owners) || []).map(function (owner) {
      if (typeof owner === "string") { return { who: shown(owner), share: "", note: "" }; }
      var share = owner.share || owner.stake || owner.holding || "";
      if (!share && typeof owner.percentage === "number") {
        /* A figure the server computed, given the sign it is measured in.
           Formatting a number is not the same as writing a sentence. */
        share = owner.percentage + "%";
      }
      return {
        who: shown(owner.name || owner.who || ""),
        share: shown(share),
        note: shown(owner.basis || owner.through || owner.says || "")
      };
    }).filter(function (owner) { return owner.who; });
    if (!owners.length) { return ""; }
    return h`<ul class="chain">${owners.map(function (owner) {
      return h`<li>
                 <div class="chain-who">${owner.who}</div>
                 ${owner.share ? h`<div class="chain-share">${owner.share}</div>` : ""}
                 ${owner.note ? h`<div class="chain-share">${owner.note}</div>` : ""}
               </li>`;
    })}</ul>`;
  }

  /* One judgement, recorded against every open file it settles. The contract
     names no single file for an onboarding, so where the server states one it
     is used, and where it does not the same outcome and the same reason are
     written to each finding's file — which is what pressing one of these
     buttons means. */
  function recordOnboardingDecision(record, decision, outcome, reason, code) {
    var files = [];
    if (decision.case_id) {
      files.push(decision.case_id);
    } else {
      (record.findings || []).forEach(function (finding) {
        if (finding.case_id) { files.push(finding.case_id); }
      });
    }
    if (!files.length) {
      return Promise.reject(new Error(""));
    }
    var last = null;
    return files.reduce(function (chain, file) {
      return chain.then(function () {
        return recordDecision(file, outcome, reason, code).then(function (result) {
          last = result;
        });
      });
    }, Promise.resolve()).then(function () { return last; });
  }

  /* The one write this screen makes. Both spellings of each field travel: the
     route has been named two ways during this rebuild and a decision that
     fails to record because of a key name is not an acceptable failure. */
  function recordDecision(file, outcome, reason, code) {
    return post("/api/decisions", {
      person: person,
      file: file,
      case_id: file,
      outcome: outcome,
      reason: reason,
      rationale: reason,
      code: code || "",
      reason_code: code || "",
      used: "NONE"
    });
  }

  /* ---------- the decision, wherever it is made ---------- */

  /* Deliberately the same component on the report and in the list, and
     deliberately the plainest thing on either screen. Nothing above it is
     styled as a verdict; nothing here suggests which button to press. The
     reason is required before any of the three can be pressed at all. */
  function decisionBlock(where, spec) {
    if (!where) { return; }
    var options = spec.options || [];
    if (!options.length) { return; }

    mount(where, h`
      <div class="decision">
        <h2>${spec.heading}</h2>
        ${spec.permanence ? h`<p class="permanence">${spec.permanence}</p>` : ""}
        ${(!canDecide && readOnlyBecause) ? h`<p class="note prose">${
          readOnlyBecause
        }</p>` : ""}
        <div class="reason-box">
          <label class="field" for="why">${word("why", "")}</label>
          <textarea id="why" rows="3"></textarea>
        </div>
        <div class="choices">
          ${options.map(function (option, index) {
            return h`<button type="button" class="btn choice" data-choice="${index}"
                       aria-pressed="false" disabled>
                       <span class="choice-label">${option.label}</span>
                       <span class="choice-means">${option.means || ""}</span>
                     </button>`;
          })}
        </div>
        <div class="confirm-bar" hidden></div>
        <p class="problem" hidden></p>
      </div>`);

    var box = where.querySelector("#why");
    var buttons = where.querySelectorAll(".choice");
    var bar = where.querySelector(".confirm-bar");
    var problem = where.querySelector(".problem");

    function settle() {
      var ready = canDecide && box.value.trim().length > 0;
      buttons.forEach(function (button) { button.disabled = !ready; });
      if (!ready) {
        bar.hidden = true;
        buttons.forEach(function (button) { button.setAttribute("aria-pressed", "false"); });
      }
    }
    box.addEventListener("input", settle);
    box.disabled = !canDecide;
    settle();

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var choice = options[Number(button.getAttribute("data-choice"))];
        buttons.forEach(function (other) {
          other.setAttribute("aria-pressed", other === button ? "true" : "false");
        });
        openConfirm(choice);
      });
    });

    /* The confirming click, not the first one, is what makes a decision
       permanent. It restates the officer's own choice rather than offering a
       second click of faith in whatever the first one was. */
    function openConfirm(choice) {
      var fits = (spec.reasons || []).filter(function (reason) {
        return reason.when === choice.outcome;
      });
      bar.hidden = false;
      mount(bar, h`
        ${fits.length ? h`
          <span>
            <label class="field" for="why-code">${word("reason_pick", "")}</label>
            <select id="why-code">
              <option value=""></option>
              ${fits.map(function (reason) {
                return h`<option value="${reason.code}">${reason.label}</option>`;
              })}
            </select>
          </span>` : ""}
        <button type="button" class="btn btn-primary" id="do-record">${
          ui.confirm_prefix ? ui.confirm_prefix + " " + choice.label
                            : word("confirm_plain", choice.label)
        }</button>
        <button type="button" class="btn" id="do-drop">${word("cancel", "")}</button>`);

      bar.querySelector("#do-drop").addEventListener("click", function () {
        bar.hidden = true;
        buttons.forEach(function (button) { button.setAttribute("aria-pressed", "false"); });
        box.focus();
      });

      bar.querySelector("#do-record").addEventListener("click", function () {
        var record = bar.querySelector("#do-record");
        var picker = bar.querySelector("#why-code");
        record.disabled = true;
        problem.hidden = true;
        spec.record(choice.outcome, box.value, picker ? picker.value : "")
          .then(function (result) {
            mount(where, h`<div class="decision">
              <p class="note good">${(result && result.message) || ""}</p>
            </div>`);
            morning = null;
          })
          .catch(function (error) {
            record.disabled = false;
            problem.hidden = false;
            problem.textContent = said(error) || word("record_failed", "");
          });
      });
    }
  }

  /* ---------- the list ---------- */

  function queueScreen(openFile) {
    var where = frame("queue");
    busy(where);
    theMorning().then(function (brief) {
      var groups = brief.groups || [];
      mount(where, h`
        <div class="head">
          <h1>${word("nav_queue", "Your list")}</h1>
          ${brief.ordered_for ? h`<p class="small soft prose">${brief.ordered_for}</p>` : ""}
        </div>
        ${readOnlyBecause ? h`<p class="note prose">${readOnlyBecause}</p>` : ""}
        ${groups.length ? groups.map(groupCard)
                        : h`<p class="note good">${
                            brief.all_clear || brief.nothing_needed || ""
                          }</p>`}
        <p class="small faint prose">${brief.assurance || ""}</p>`);

      groups.forEach(function (group) {
        (group.items || []).forEach(function (item) {
          wireItem(where, group, item);
        });
      });
      if (openFile) {
        var target = where.querySelector('[data-file="' + cssEscape(openFile) + '"]');
        if (target) {
          var opener = target.querySelector("[data-open]");
          if (opener) { opener.click(); }
          target.scrollIntoView({ block: "center" });
        }
      }
    }).catch(function (error) { failed(where, error); });
  }

  function cssEscape(value) {
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function groupCard(group) {
    return h`
      <div class="group">
        <div class="group-head">
          <span class="dot" data-tone="${group.tone}"></span>
          <div class="group-title">
            <h2>${group.title}</h2>
            <p class="small faint">${group.urgency}</p>
          </div>
          <span class="badge" data-tone="${group.tone}">${group.total}</span>
        </div>
        <div class="group-body">
          ${(group.because || []).length ? h`<div class="prose small soft">${
            group.because.map(function (line) { return h`<p>${line}</p>`; })
          }</div>` : ""}
          ${(group.to_close_this || []).length ? h`
            <p class="tiny eyebrow">${word("to_close_heading", "")}</p>
            <ul class="bullets small prose">${group.to_close_this.map(function (line) {
              return h`<li>${line}</li>`;
            })}</ul>` : ""}
          ${(group.rules || []).length ? h`
            <p class="tiny eyebrow">${
              group.rules.length === 1 ? word("rule_heading", "") : word("rules_heading", "")
            }</p>
            ${group.rules.map(function (rule) {
              return h`<p class="quote">${word("clause_prefix", "")} ${rule.clause} — ${
                rule.says
              }</p>`;
            })}` : ""}
          <ul class="items">
            ${(group.items || []).map(function (item) {
              return h`<li data-file="${item.case_id}">
                <div class="item-line">
                  <span class="what">${item.line || item.headline}</span>
                  <button type="button" class="btn-link small" data-open>${
                    word("open_file", "")
                  }</button>
                </div>
                <div class="item-open" hidden></div>
              </li>`;
            })}
          </ul>
          ${group.more ? h`<p class="tiny faint">${group.more}</p>` : ""}
        </div>
      </div>`;
  }

  function wireItem(where, group, item) {
    var row = where.querySelector('[data-file="' + cssEscape(item.case_id) + '"]');
    if (!row) { return; }
    var opener = row.querySelector("[data-open]");
    var panel = row.querySelector(".item-open");
    var drawn = false;
    opener.addEventListener("click", function () {
      if (drawn) {
        panel.hidden = !panel.hidden;
        return;
      }
      drawn = true;
      panel.hidden = false;
      mount(panel, h`
        <h3>${item.headline}</h3>
        <div class="prose small soft">${(item.because || []).map(function (line) {
          return h`<p>${line}</p>`;
        })}</div>
        ${(item.to_close_this || []).length ? h`
          <p class="tiny eyebrow">${word("to_close_heading", "")}</p>
          <ul class="bullets small prose">${item.to_close_this.map(function (line) {
            return h`<li>${line}</li>`;
          })}</ul>` : ""}
        ${(item.side_by_side || []).length ? h`
          <div class="table-wrap"><table class="grid">
            <thead><tr><th></th><th>${item.ours_label}</th><th>${
              item.theirs_label
            }</th><th></th></tr></thead>
            <tbody>${item.side_by_side.map(function (line) {
              return h`<tr>
                <td>${line.what}</td><td class="num">${line.ours}</td>
                <td class="num">${line.theirs}</td>
                <td><span class="dot" data-tone="${
                  line.tone === "differs" ? "stop" : line.tone === "same" ? "good" : "later"
                }"></span> ${line.says}</td>
              </tr>`;
            })}</tbody>
          </table></div>` : ""}
        ${item.corroboration ? h`<p class="note">${item.corroboration}</p>` : ""}
        <div class="item-decision"></div>`);

      decisionBlock(panel.querySelector(".item-decision"), {
        heading: word("report_decision", "What only a person may now do"),
        permanence: item.recorded_as,
        options: (item.choices || []).map(function (choice) {
          return { label: choice.label, means: choice.means, outcome: choice.outcome };
        }),
        reasons: item.reasons || [],
        record: function (outcome, reason, code) {
          return recordDecision(item.case_id, outcome, reason, code);
        }
      });
    });
  }

  /* ---------- parties ---------- */

  function partiesScreen() {
    var where = frame("parties");
    mount(where, h`
      <div class="head"><h1>${word("find_heading", "")}</h1></div>
      <div class="card pad">
        <form class="ask-form">
          <input type="search" id="q" autocomplete="off"
                 placeholder="${word("find_placeholder", "")}"
                 aria-label="${word("find_heading", "")}">
          <button type="submit" class="btn btn-primary">${word("find_go", "")}</button>
        </form>
        <p class="small faint" id="found"></p>
        <ul class="hits" id="hits"></ul>
      </div>`);

    var form = where.querySelector("form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var query = where.querySelector("#q").value.trim();
      get("/api/parties?q=" + encodeURIComponent(query)).then(function (payload) {
        absorb(payload);
        document.getElementById("found").textContent = payload.found || "";
        mount(document.getElementById("hits"), (payload.parties || []).map(function (hit) {
          return h`<li><button type="button" data-ref="${hit.ref}">
                     <span class="hit-name">${hit.name}</span>
                     <span class="hit-kind">${hit.kind}</span>
                   </button></li>`;
        }));
        on(where, "[data-ref]", "click", function (event) {
          go("#/party/" + encodeURIComponent(
            event.currentTarget.getAttribute("data-ref")));
        });
      }).catch(function (error) { failed(document.getElementById("hits"), error); });
    });
    where.querySelector("#q").focus();
  }

  function partyScreen(entityId) {
    var where = frame("parties");
    busy(where);
    get("/api/parties/" + encodeURIComponent(entityId)).then(function (party) {
      absorb(party);
      mount(where, h`
        <div class="party-head">
          <p class="eyebrow">${party.kind || ""}</p>
          <h1>${party.name || ""}</h1>
          <p class="soft prose">${party.standing || ""}</p>
          ${party.unknown ? h`<p class="note prose">${party.unknown}</p>` : ""}
        </div>

        <div class="panels">
          ${(party.traits || []).length ? h`
            <div class="card pad">
              <h2 class="section-head">${party.traits_heading}</h2>
              <dl class="pairs">${party.traits.map(function (trait) {
                return h`<dt>${trait.label}</dt><dd>${trait.value}</dd>`;
              })}</dl>
              <p class="tiny faint prose">${party.traits_caveat || ""}</p>
            </div>` : ""}

          ${(party.papers || []).length ? h`
            <div class="card pad">
              <h2 class="section-head">${party.papers_heading}</h2>
              <table class="grid"><tbody>${party.papers.map(function (paper) {
                return h`<tr>
                  <td><span class="dot" data-tone="${paper.tone || "plain"}"></span>
                      ${paper.called}</td>
                  <td>${paper.supports}</td>
                  <td>${paper.when}</td>
                </tr>`;
              })}</tbody></table>
              ${party.papers_note ? h`<p class="tiny faint prose">${
                party.papers_note
              }</p>` : ""}
            </div>` : party.papers_none ? h`
            <div class="card pad">
              <h2 class="section-head">${party.papers_heading}</h2>
              <p class="empty">${party.papers_none}</p>
            </div>` : ""}

          ${(party.ties || []).length ? h`
            <div class="card pad">
              <h2 class="section-head">${party.ties_heading}</h2>
              <ul class="chain">${party.ties.map(function (tie) {
                return h`<li>
                  <div class="chain-who">${tie.who}</div>
                  <div class="chain-share">${tie.direction} ${tie.share}</div>
                  ${tie.basis ? h`<div class="chain-share">${tie.basis}</div>` : ""}
                </li>`;
              })}</ul>
            </div>` : ""}

          ${(party.movements || []).length ? h`
            <div class="card pad">
              <h2 class="section-head">${party.money_heading}</h2>
              <p class="small soft prose">${party.money_summary || ""}</p>
              <table class="grid"><tbody>${party.movements.map(function (move) {
                return h`<tr>
                  <td>${move.when}</td><td>${move.what}</td>
                  <td class="num">${move.amount}</td>
                  <td><span class="dot" data-tone="${move.tone || "plain"}"></span>
                      ${move.note}</td>
                </tr>`;
              })}</tbody></table>
            </div>` : ""}
        </div>

        ${(party.open_files || []).length ? h`
          <div class="card pad" >
            <h2 class="section-head">${party.open_heading}</h2>
            <ul class="strip">${party.open_files.map(function (file) {
              return h`<li>
                <span class="dot" data-tone="${file.tone}"></span>
                <span class="what">${file.headline}</span>
                <span class="badge" data-tone="${file.tone}">${file.urgency}</span>
                <button type="button" class="btn-link small"
                        data-open-file="${file.case_id}">${word("open_file", "")}</button>
              </li>`;
            })}</ul>
          </div>` : ""}

        ${(party.timeline || []).length ? h`
          <div class="card pad">
            <h2 class="section-head">${party.timeline_heading}</h2>
            <ul class="timeline">${party.timeline.map(function (moment) {
              return h`<li>
                <div class="when">${moment.when}</div>
                <div>${moment.what}</div>
              </li>`;
            })}</ul>
          </div>` : ""}`);

      on(where, "[data-open-file]", "click", function (event) {
        go("#/queue/" + encodeURIComponent(
          event.currentTarget.getAttribute("data-open-file")));
      });
    }).catch(function (error) { failed(where, error); });
  }

  /* ---------- the router ---------- */

  function show() {
    stopPolling();
    if (!person) { openDoor(); return; }
    var at = here();
    if (at.name === "onboard" && at.a) { onboardPapers(at.a, at.b); return; }
    if (at.name === "onboard") { onboardWho(); return; }
    if (at.name === "checks" && at.a) { onboardChecks(at.a, at.b); return; }
    if (at.name === "run" && at.a) { runScreen(at.a, at.b); return; }
    if (at.name === "report" && at.a) { reportScreen(at.a, at.b); return; }
    if (at.name === "queue") { queueScreen(at.a); return; }
    if (at.name === "party" && at.a) { partyScreen(at.a); return; }
    if (at.name === "parties") { partiesScreen(); return; }
    if (at.name === "ask") { askScreen(); return; }
    home();
  }

  window.addEventListener("hashchange", show);

  /* The labels have to be in hand before the first screen renders, so the
     session is read first whatever the address bar says. */
  get("/api/session").then(function (session) {
    absorb(session);
    guarded = !!session.needs_password;
    if (session.signed_in_as) {
      person = session.signed_in_as;
      sessionStorage.setItem("vinzor.person", person);
    }
    markDecider(session);
    if (person) { show(); } else { openDoor(); }
  }).catch(function (error) { failed(app, error); });
})();
