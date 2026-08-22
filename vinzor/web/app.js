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


  /* ---------- the mark ----------
     The brand's faceted V, inlined rather than served as a file.

     Inlined for two reasons. The server routes exactly two static paths --
     /app.css and /app.js -- so an .svg on disk would need a change in
     server.py, which another pair of hands is working in. And an inline
     mark takes its colour from `fill: currentColor`, so the same twelve
     paths do the ink sidebar and a bone-on-ink lockup without a second
     file.

     Each path keeps its own `transform`. The tracer emits twelve shards
     positioned by translate(), several of which start at negative
     coordinates -- so dropping the transforms, which the first version of
     this did, collapses the whole mark into a black splinter in the corner
     of its box. It shipped looking like that.

     Coordinates are rounded to one decimal place, sign included: this is a
     175x159 mark drawn at twenty-two pixels, and eight decimals of a traced
     curve is six kilobytes nobody can see. */
  var MARK_VIEWBOX = "0 0 175 159";
  var MARK_PATHS = "<path d=\"M0 0 C8.4 2.4 16.6 5.2 24.8 8.1 C27.1 8.9 29.3 9.7 31.6 10.5 C38.9 13.1 46 15.7 53 19 C52.4 21.7 51.8 24.4 51.1 27.1 C51 27.9 50.8 28.6 50.6 29.4 C49.6 33.7 48.5 37.9 47 42 C35.5 33.7 35.5 33.7 31 29 C31 28.3 31 27.7 31 27 C30.7 26.9 30.7 26.9 29.4 26.3 C25.3 24.1 22 21 18.7 17.7 C15.7 14.7 12.5 11.8 9.4 8.9 C8.2 7.8 7.1 6.8 6 5.7 C5.5 5.3 5 4.8 4.5 4.4 C2.9 2.9 1.5 1.5 0 0 Z \" transform=\"translate(1,2)\"/><path d=\"M0 0 C-5.1 5.1 -10.1 10.2 -15.6 14.9 C-19 17.9 -22.2 20.9 -25.5 24 C-40 37.6 -40 37.6 -45 40 C-46 36.7 -47 33.5 -48 30.2 C-48.1 29.7 -48.1 29.7 -48.9 27.4 C-49.1 26.5 -49.4 25.6 -49.7 24.7 C-49.9 23.8 -50.2 23 -50.4 22.2 C-51 20 -51 20 -51 17 C-44.2 14.4 -37.4 11.8 -30.7 9.3 C-28.3 8.4 -26 7.5 -23.7 6.6 C-20.4 5.3 -17.1 4.1 -13.8 2.8 C-12.8 2.4 -11.7 2 -10.7 1.6 C-9.7 1.3 -8.7 0.9 -7.7 0.5 C-6.9 0.2 -6.1 -0.1 -5.2 -0.4 C-3 -1 -3 -1 0 0 Z \" transform=\"translate(171,4)\"/><path d=\"M0 0 C3.6 2.1 6.9 4.2 10 7 C10 7.7 10 8.3 10 9 C10.3 9.1 10.3 9.1 11.8 9.8 C14.1 11 15.5 12.3 17.2 14.2 C20.3 17.3 23.4 20.1 26.7 23 C30.1 25.9 33.4 29 36.7 32.1 C38.9 34.1 41 36 43.5 37.5 C47.2 41.2 47.4 44.9 48.2 49.9 C48.4 50.8 48.6 51.8 48.8 52.8 C49.3 55.9 49.8 58.9 50.3 62 C50.7 64.1 51 66.1 51.4 68.2 C52.1 72 52.7 75.8 53.3 79.6 C53.5 80.3 53.6 81.1 53.7 81.9 C54 84 54 84 54 88 C52.2 87.5 50.5 87 48.7 86.6 C47.7 86.3 46.7 86 45.7 85.8 C40.1 84.2 40.1 84.2 38.9 82.4 C38.5 81.7 38.2 80.9 37.8 80.2 C37.4 79.4 37 78.6 36.6 77.8 C36.2 76.9 35.7 76 35.3 75.1 C34.8 74.2 34.4 73.3 33.9 72.3 C32.4 69.3 31 66.4 29.5 63.4 C28.5 61.3 27.5 59.3 26.5 57.3 C20.2 44.6 14 32 8.1 19.2 C7 17 5.9 14.7 4.8 12.4 C4.1 11 3.5 9.6 2.8 8.2 C2.3 7 1.7 5.9 1.1 4.7 C-0 2 -0 2 0 0 Z \" transform=\"translate(2,6)\"/><path d=\"M0 0 C0.7 0 1.3 0 2 0 C0.3 5.9 -2.4 11.3 -5.1 16.8 C-5.6 17.9 -6.2 19 -6.7 20.1 C-7.8 22.4 -9 24.8 -10.1 27.2 C-11.8 30.5 -13.4 33.9 -15 37.3 C-16.8 40.9 -18.5 44.5 -20.2 48.1 C-20.6 48.7 -20.9 49.4 -21.2 50.1 C-24.9 57.7 -28.6 65.2 -32.3 72.7 C-32.6 73.3 -32.9 74 -33.3 74.7 C-38.3 84.7 -38.3 84.7 -42.1 86.4 C-43.3 86.7 -44.5 87 -45.7 87.3 C-46.9 87.6 -48 88 -49.3 88.3 C-49.7 88.4 -49.7 88.4 -52 89 C-51.5 80 -49.9 71.3 -48.1 62.5 C-47.6 60.1 -47.2 57.7 -46.7 55.3 C-46.4 53.8 -46.1 52.3 -45.8 50.8 C-45.7 50.1 -45.5 49.3 -45.4 48.6 C-44 41.7 -41.3 37.9 -36.1 33.3 C-35.2 32.5 -34.4 31.8 -33.5 31 C-31 29 -31 29 -28.7 27.9 C-27 27 -27 27 -26 24 C-24.4 22.5 -24.4 22.5 -22.5 20.8 C-18.1 17.1 -13.8 13.2 -9.6 9.2 C-8.9 8.5 -8.2 7.9 -7.5 7.2 C-2.3 2.3 -2.3 2.3 0 0 Z \" transform=\"translate(170,6)\"/><path d=\"M0 0 C0.7 0 1.3 0 2 0 C2.4 1 2.8 2 3.3 3.1 C4.9 6.9 6.4 10.7 8 14.5 C8.7 16.1 9.4 17.8 10.1 19.4 C11.1 21.8 12 24.2 13 26.6 C13.2 27 13.2 27 14 28.9 C15.7 32.9 17.3 36.8 19.1 40.7 C19.3 41 19.3 41 20.1 42.9 C20.7 44.3 21.4 45.6 22 47 C24.1 51.7 24.1 51.7 23 55 C10.6 40.4 10.6 40.4 5.1 33.6 C3.7 31.9 2.3 30.2 0.9 28.6 C-3.8 23.3 -3.8 23.3 -4.3 19.9 C-4.1 17.5 -3.6 15.3 -3 13 C-2.7 11.9 -2.5 10.7 -2.2 9.5 C-1.5 6.4 -0.8 3.2 0 0 Z \" transform=\"translate(54,24)\"/><path d=\"M0 0 C0.7 0 1.3 0 2 0 C2.7 2.7 3.4 5.4 4.1 8.1 C4.3 8.8 4.5 9.6 4.7 10.3 C5.9 15.2 6.3 19.1 5 24 C3.5 26.3 3.5 26.3 1.5 28.2 C-6.2 36.4 -13 45.2 -20 54 C-21.2 50.4 -20.8 49.8 -19.3 46.4 C-19.1 45.9 -19.1 45.9 -18.1 43.6 C-17.6 42.6 -17.2 41.5 -16.8 40.5 C-15.8 38.3 -14.9 36.2 -14 34 C-13.5 32.9 -13 31.8 -12.5 30.6 C-9.9 24.4 -7.4 18.2 -4.9 12 C-4.4 10.8 -3.9 9.6 -3.4 8.4 C-2.3 5.6 -1.1 2.8 0 0 Z \" transform=\"translate(118,25)\"/><path d=\"M0 0 C5.2 5.1 9.8 10.5 14.4 16.1 C15.5 17.4 16.6 18.7 17.7 20.1 C19.5 22.2 21.2 24.3 23 26.4 C23.3 26.7 23.3 26.7 24.7 28.4 C31.6 36.7 32.8 44.5 34.2 55.1 C34.4 56.4 34.5 57.6 34.7 58.9 C36.1 69.1 36.1 69.1 36 74 C31.5 70.3 27.2 66.4 23.1 62.2 C22.6 61.8 22.1 61.3 21.6 60.8 C20.3 59.6 19.2 58.3 18 57 C18 56.3 18 55.7 18 55 C17.3 55 16.7 55 16 55 C14.7 53.6 13.5 52.1 12.3 50.6 C11 49 11 49 9.5 47.6 C7 44.9 6.8 41.2 6.2 37.7 C6.1 36.9 5.9 36 5.8 35.2 C5.3 32.6 4.8 29.9 4.4 27.3 C4.1 25.6 3.7 23.8 3.4 22.1 C2.1 14.7 0.9 7.4 0 0 Z \" transform=\"translate(50,49)\"/><path d=\"M0 0 C1.3 3.7 0.7 6.5 -0.1 10.3 C-0.4 11.6 -0.7 12.8 -0.9 14.1 C-1.2 15.4 -1.5 16.7 -1.8 18 C-2.4 20.5 -2.9 23.1 -3.5 25.6 C-3.7 26.9 -4 28.1 -4.3 29.4 C-5.1 33.7 -5.8 38.1 -6.4 42.5 C-7.5 47.2 -10.6 49.8 -14 53 C-15.7 54.6 -17.3 56.3 -18.9 57.9 C-20.1 59.1 -21.2 60.2 -22.4 61.3 C-24.9 63.8 -27.1 66.2 -29.3 68.9 C-29.8 69.6 -30.4 70.3 -31 71 C-31.7 71 -32.3 71 -33 71 C-33.3 72 -33.7 73 -34 74 C-34.3 74 -34.7 74 -35 74 C-32.1 36.3 -32.1 36.3 -20.5 25.5 C-17.8 22.8 -15.6 19.8 -13.3 16.8 C-12.4 15.6 -11.5 14.5 -10.6 13.3 C-10.2 12.8 -9.7 12.2 -9.3 11.6 C-6.2 7.7 -3.1 3.9 0 0 Z \" transform=\"translate(123,50)\"/><path d=\"M0 0 C2.1 0.6 4.2 1.2 6.3 1.8 C6.9 2 6.9 2 9.9 2.8 C12.9 4 14 4.6 16 7 C16.8 9 16.8 9 17.5 11.2 C17.8 12.1 18 12.9 18.3 13.8 C18.5 14.7 18.8 15.6 19.1 16.5 C19.3 17.5 19.6 18.4 19.9 19.4 C20.8 22.4 21.7 25.4 22.6 28.4 C23.4 31.4 24.3 34.4 25.2 37.4 C25.8 39.2 26.3 41.1 26.9 43 C27.9 46.4 28.9 49.7 30.2 52.9 C31 55 31 55 30 58 C29.6 57.2 29.2 56.5 28.8 55.7 C21.3 41 13.7 26.4 5.4 12.2 C0 2.9 0 2.9 0 0 Z \" transform=\"translate(44,92)\"/><path d=\"M0 0 C-3.8 7.7 -7.7 15.3 -12 22.7 C-15 27.9 -17.6 33.2 -20.3 38.6 C-22.9 43.9 -25.9 48.9 -29 54 C-30.3 51.4 -29.8 50.6 -28.9 47.8 C-28.6 46.9 -28.3 46.1 -28.1 45.2 C-27.8 44.3 -27.5 43.3 -27.1 42.4 C-26.8 41.4 -26.5 40.4 -26.2 39.4 C-25.6 37.4 -24.9 35.4 -24.3 33.3 C-23.3 30.2 -22.3 27.1 -21.3 24 C-20.7 22 -20 20 -19.4 18 C-19.1 17.1 -18.8 16.2 -18.5 15.2 C-14.9 4.1 -14.9 4.1 -10.6 1.6 C-9.8 1.3 -8.9 1 -8 0.6 C-7.1 0.3 -6.3 -0.1 -5.4 -0.4 C-3 -1 -3 -1 0 0 Z \" transform=\"translate(130,94)\"/><path d=\"M0 0 C3.9 2.8 6.8 6 9.8 9.6 C11.5 11.5 13.3 13.1 15.2 14.8 C23.7 22.4 23.7 22.4 24.5 26.4 C24 29.2 23.1 31.4 22 34 C21.6 35.4 21.2 36.8 20.8 38.1 C19.6 42.1 18.5 46.1 17 50 C16.7 50.2 16.7 50.2 15 51 C13 44.5 11 38.1 9.1 31.6 C8.4 29.4 7.7 27.2 7.1 25 C6.1 21.9 5.1 18.7 4.2 15.6 C4 15.1 4 15.1 3.2 12.6 C3 11.7 2.7 10.7 2.4 9.8 C2.3 9.4 2.3 9.4 1.7 7.3 C1 4.9 0.5 2.5 0 0 Z \" transform=\"translate(62,102)\"/><path d=\"M0 0 C1.2 3.7 0.6 5.1 -0.7 8.8 C-1 9.9 -1.4 11.1 -1.8 12.3 C-2.2 13.5 -2.6 14.8 -3.1 16.1 C-3.5 17.3 -3.9 18.6 -4.3 19.9 C-6.2 25.5 -8 31.1 -9.9 36.7 C-10.2 37.5 -10.5 38.3 -10.7 39.2 C-11.2 40.6 -11.7 42.1 -12.2 43.6 C-13.4 47.1 -14.3 50.4 -15 54 C-20.6 54 -26.2 54 -32 54 C-30.6 47.2 -28.7 40.7 -26.5 34.1 C-26.2 33.2 -25.9 32.3 -25.6 31.3 C-25.3 30.4 -25 29.5 -24.7 28.6 C-24.4 27.8 -24.1 27 -23.8 26.1 C-23 24 -23 24 -21 21 C-20.3 21 -19.7 21 -19 21 C-18.8 20.4 -18.5 19.8 -18.2 19.3 C-16.8 16.7 -15.2 15 -13.1 12.9 C-12.3 12.1 -11.6 11.4 -10.8 10.6 C-10 9.8 -9.2 9.1 -8.4 8.2 C-8 7.9 -8 7.9 -5.9 5.8 C-4 3.9 -2 1.9 0 0 Z \" transform=\"translate(111,103)\"/>";

  function mark(size, label) {
    return raw(
      '<svg class="mark" viewBox="' + MARK_VIEWBOX + '" width="' + size +
      '" height="' + Math.round(size * 159 / 175) + '" aria-hidden="true" ' +
      'focusable="false">' + MARK_PATHS + "</svg>"
    );
  }

  function frame(at) {
    mount(app, h`
      <nav class="rail">
        <div class="rail-mark">
          ${mark(30)}<span>${word("wordmark", "Vinzor")}</span>
        </div>
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
          <h1 class="lockup">
            ${mark(46)}<span>${word("wordmark", "Vinzor")}</span>
          </h1>
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
          <h1 class="lockup">
            ${mark(46)}<span>${word("wordmark", "Vinzor")}</span>
          </h1>
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

  /* The morning, on one screen and without a scroll: who you are and what day
     it is, the one thing this product is for, the assistant, five counts, the
     top of the list beside the shape of the book, and the bands underneath.

     Every figure below is a figure the server sent. There is no trend, no
     comparison with yesterday and no percentage this file worked out, because
     nothing here knows what yesterday held -- and a number nobody can defend,
     on the screen an officer answers to a regulator from, is the worst defect
     this product could ship. Where the server sends nothing, the block is
     left out rather than filled. */

  function home() {
    var where = frame("home");
    busy(where);
    theMorning().then(function (brief) {
      var dash = brief.dashboard || {};
      var beside = (dash.ageing || []).length > 0;
      /* The one screen that is supposed to end where the window does. Every
         other screen is a document and wants a foot to scroll into. */
      where.classList.add("sheet-home");
      mount(where, h`
        <div class="home">
          <div class="home-greeting">
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

          <div class="home-panels${beside ? "" : " alone"}">
            <div class="card pad" id="priority"></div>
            ${beside ? h`<div class="card pad" id="standing"></div>` : ""}
          </div>

          <div class="home-bands" id="bands"></div>
        </div>`);

      mount(document.getElementById("tally"), tallyTiles(brief));
      askCard(document.getElementById("ask-here"));
      mount(document.getElementById("priority"), prioritySlice(brief));
      if (beside) {
        mount(document.getElementById("standing"), standingPanel(dash));
        applyShares(document.getElementById("standing"));
      }
      mount(document.getElementById("bands"), bandStrip(dash));
      on(where, "[data-open-file]", "click", function (event) {
        go("#/queue/" + encodeURIComponent(
          event.currentTarget.getAttribute("data-open-file")));
      });
    }).catch(function (error) { failed(where, error); });
  }

  /* ---------- the five counts ----------

     One mark each, drawn here rather than fetched: the policy this page is
     served under admits no remote image, and an emoji would be a different
     typeface on every machine this is read on. Geometry only -- the stroke,
     the joins and the colour are classes in app.css, for the same reason the
     ownership drawing keeps its colours there.

     The marks are furniture and say nothing the label does not: a count with
     no mark is a count with a gap beside it, never a count with a meaning
     missing. They are held in the order briefing.py emits its counts in, and
     the last one stands in for anything that order grows. */
  var TALLY_MARKS = [
    /* what is open */
    '<path d="M3.5 5.5h5l2 2.5h10v10.5h-17Z"/>',
    /* what must stop */
    '<path d="M9 3.5h6l4.5 4.5v6L15 18.5H9L4.5 14V8Z"/><path d="M8.5 11h7"/>',
    /* what is due today */
    '<circle cx="12" cy="12" r="8"/><path d="M12 7.2V12l3.2 2"/>',
    /* what has never been looked at */
    '<path d="M3.5 12c2.8-4.4 14.2-4.4 17 0-2.8 4.4-14.2 4.4-17 0Z"/>' +
      '<circle cx="12" cy="12" r="2.3"/><path d="M5 19.5 19 4.5"/>',
    /* what is finished with */
    '<circle cx="12" cy="12" r="8"/><path d="M8.4 12.2 11 14.8 15.6 9.4"/>'
  ];

  function tallyMark(index) {
    var body = TALLY_MARKS[index] || TALLY_MARKS[TALLY_MARKS.length - 1];
    return raw('<svg class="tally-mark" viewBox="0 0 24 24" aria-hidden="true" ' +
               'focusable="false">' + body + "</svg>");
  }

  /* The small honest numbers. Every label and figure is the server's. */
  function tallyTiles(brief) {
    var stats = (brief.dashboard && brief.dashboard.stats) || [];
    if (!stats.length) {
      return (brief.headlines || []).map(function (line) {
        return h`<li><span class="label">${line}</span></li>`;
      });
    }
    return stats.map(function (stat, index) {
      var tone = stat.tone || "plain";
      return h`<li>
                 <span class="tally-head">
                   <span class="tally-icon" data-tone="${tone}">${
                     tallyMark(index)
                   }</span>
                   <span class="label">${stat.label}</span>
                 </span>
                 <span class="count" data-tone="${tone}">${stat.value}</span>
               </li>`;
    });
  }

  /* The top of the queue, and a way in. A few lines, not a second list — the
     list itself is one click away. */
  function prioritySlice(brief) {
    var groups = brief.groups || [];
    if (!groups.length) {
      return h`<p class="note good">${brief.all_clear || brief.nothing_needed || ""}</p>`;
    }
    var lines = [];
    var said = {};
    groups.forEach(function (group) {
      (group.items || []).forEach(function (item) {
        if (lines.length >= 4) { return; }
        /* The reason once, and then what tells the rest of them apart.
           Four lines that all read "Money arrived from a party that may be
           on a sanctions list" say one thing four times and never say which
           payment. Both sentences are the server's; which one a line gets,
           and whether it repeats a badge the line above it is already
           wearing, is furniture. The dot keeps the colour either way. */
        var reason = item.headline || "";
        var again = !!(reason && said[reason]);
        said[reason] = true;
        lines.push({
          tone: group.tone,
          who: item.who || item.line || "",
          why: again ? (shown(item.about) || reason) : (reason || shown(item.about)),
          urgency: again ? "" : (item.urgency || group.urgency),
          file: item.case_id
        });
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
                     <span class="what">
                       <span class="item-who">${line.who}</span>
                       <span class="item-why">${line.why}</span>
                     </span>
                     ${line.urgency ? h`<span class="badge" data-tone="${
                       line.tone || "later"
                     }">${line.urgency}</span>` : ""}
                     ${line.file ? h`<button type="button" class="btn-link small"
                                       data-open-file="${line.file}">${
                       word("open_file", "")
                     }</button>` : ""}
                   </li>`;
        })}
      </ul>`;
  }

  /* ---------- where the book stands ----------

     How long the open files have been waiting, which is the first question an
     inspector asks and the one a count of open files cannot answer. The
     heading, the band names and the closing sentence are the server's; the
     bar is the share briefing.py computed for exactly this, and carries no
     figure of its own because the count beside it already says it.

     Nothing is compared with yesterday, and nothing is a proportion this file
     worked out. There is no record of yesterday to compare against. */
  function standingPanel(dash) {
    var bands = dash.ageing || [];
    return h`
      <div class="section-head">
        <h2>${dash.ageing_heading || word("home_standing", "Where the book stands")}</h2>
      </div>
      <table class="grid standing"><tbody>${bands.map(function (band) {
        return h`<tr>
          <td class="standing-what">
            <span class="dot" data-tone="${band.tone || "plain"}"></span>${band.label}
          </td>
          <td class="standing-bar">
            <span class="bar"><i data-share="${Math.round((band.share || 0) * 100)}"
                                 data-tone="${band.tone || ""}"></i></span>
          </td>
          <td class="num standing-count">${band.count}</td>
        </tr>`;
      })}</tbody></table>
      ${dash.ageing_note ? h`<p class="tiny faint prose standing-note">${
        dash.ageing_note
      }</p>` : ""}`;
  }

  /* The quiet strip under everything: what the open files are actually about.
     Counts the server sent, each a way into the list. Muted on purpose — it
     is context for the five counts above it, not a sixth thing to read
     first. */
  function bandStrip(dash) {
    var rows = (dash.workload || []).slice(0, 4);
    if (!rows.length) { return ""; }
    return h`
      <p class="eyebrow">${dash.workload_heading || ""}</p>
      <ul class="bands">
        ${rows.map(function (row) {
          return h`<li><a href="#/queue">
                     <span class="count">${row.count}</span>
                     <span class="label">${row.label}</span>
                   </a></li>`;
        })}
      </ul>`;
  }

  /* ---------- asking ----------

     One conversation, not a box that answers once and forgets.

     The thread is not kept here. It is read back from the server, which
     assembles it out of the record rather than out of a store beside it — so
     an officer who signs in on another machine sees the same exchanges, and
     an inspector asking what was asked of the machine and what it did about
     it has one place to look rather than two to reconcile. Reloading this
     page is therefore not a way of losing anything.

     What this file keeps is the sitting: the turns already drawn, and the one
     question that is still in flight. Both are gone on reload, and neither is
     ever allowed to stand in for the record. */

  /* Turns as the screen has them, oldest first. Reloaded from the server
     every time the screen opens. */
  var thread = [];

  /* The question the officer typed on the home card, carried to this screen
     so the exchange lands in one place instead of two. */
  var carried = "";

  /* Openers the server offers on an empty thread, where it sends any. */
  var openers = [];

  /* ---------- the card on the home screen ----------
     It no longer answers where it stands. A question asked here opens the
     conversation and is asked there, so the officer has one thread rather
     than an answer on the home screen that nothing remembers. */
  function askCard(where) {
    if (!where) { return; }
    mount(where, h`
      <div class="spread">
        <h2>${word("ask_heading", "")}</h2>
      </div>
      <form class="ask-form">
        <input type="text" id="asked" autocomplete="off"
               placeholder="${word("ask_placeholder", "")}"
               aria-label="${word("ask_heading", "")}">
        <button type="submit" class="btn btn-primary">${word("ask_go", "")}</button>
      </form>
      <div class="ask-tries">
        ${(ui.ask_examples || []).slice(0, 2).map(function (example) {
          return h`<button type="button" data-try="${example}">${example}</button>`;
        })}
      </div>`);

    var form = where.querySelector(".ask-form");
    var box = where.querySelector("#asked");

    on(where, "[data-try]", "click", function (event) {
      box.value = event.currentTarget.getAttribute("data-try");
      box.focus();
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var asked = box.value.trim();
      if (!asked) { return; }
      box.value = "";
      carried = asked;
      go("#/ask");
    });
  }

  /* ---------- the conversation ---------- */

  function askScreen() {
    var where = frame("ask");
    mount(where, h`
      <div class="chat">
        <div class="chat-head">
          <h1>${word("ask_heading", "")}</h1>
          <p class="small soft prose">${word("ask_lead", "")}</p>
        </div>
        <div class="chat-thread" id="thread" aria-live="polite"></div>
        <div class="chat-foot">
          <form class="chat-form" id="chat-form">
            <textarea id="asked" rows="1" autocomplete="off"
                      placeholder="${word("ask_placeholder", "")}"
                      aria-label="${word("ask_heading", "")}"></textarea>
            <button type="submit" class="btn btn-primary">${word("ask_go", "")}</button>
          </form>
        </div>
      </div>`);

    var box = where.querySelector("#asked");
    var form = where.querySelector("#chat-form");
    var pending = null;

    /* Nothing here is drawn from memory. The thread is what the server has,
       and where the server has none — the route may not be there yet — the
       screen opens empty and says so with the openers rather than with an
       error about a route, which is not a thing an officer can act on. */
    thread = [];
    openers = [];
    drawThread();
    readThread().then(function (payload) {
      thread = shapeTurns(payload && payload.turns);
      openers = (payload && payload.openers) || [];
      drawThread();
      if (carried) {
        var first = carried;
        carried = "";
        send(first);
      }
    });

    function drawThread() {
      var box2 = document.getElementById("thread");
      if (!box2) { return; }
      if (!thread.length && !pending) {
        mount(box2, tries());
        on(box2, "[data-try]", "click", function (event) {
          box.value = event.currentTarget.getAttribute("data-try");
          grow();
          box.focus();
        });
        return;
      }
      mount(box2, h`${thread.map(turnBlock)}${pending ? waitingBlock(pending) : ""}`);
      box2.scrollTop = box2.scrollHeight;
    }

    /* What there is to ask, on a thread with nothing in it yet. The server's
       own suggestions where it sends them, and the examples it has always
       sent where it does not. */
    function tries() {
      var sets = openers.length
        ? openers
        : [{ heading: word("ask_examples_heading", ""),
             asks: ui.ask_examples || [] }];
      return h`<div class="chat-empty">
        ${sets.map(function (set) {
          if (!(set.asks || []).length) { return ""; }
          return h`<div class="chat-opener">
            ${set.heading ? h`<p class="eyebrow">${set.heading}</p>` : ""}
            <div class="ask-tries">
              ${(set.asks || []).map(function (one) {
                return h`<button type="button" data-try="${one}">${one}</button>`;
              })}
            </div>
          </div>`;
        })}
      </div>`;
    }

    /* The question goes up on the screen before anything is sent, and the
       answer beneath it says what is happening while it is happening.

       Only the question is sent. The last few exchanges do travel with it,
       but the server reads them out of its own record rather than taking
       them from here -- a conversation posted from a browser would be a way
       to hand the assistant an exchange that never happened, and the answer
       comes back with the firm's name on it. */
    function send(asked) {
      if (!asked || pending) { return; }
      pending = { asked: asked, asked_by: person };
      drawThread();
      post("/api/chat", { asked: asked })
        .then(function (reply) {
          pending = null;
          thread = thread.concat([{
            kind: reply.kind || "answer",
            asked: asked,
            asked_by: person,
            when: "",
            said: reply.said || "",
            withheld: reply.withheld || "",
            looked_at: reply.looked_at || reply.used || [],
            task_id: reply.task_id || (reply.task && reply.task.task_id) || "",
            task: reply.task || null,
            trouble: ""
          }]);
          drawThread();
        })
        .catch(function (error) {
          pending = null;
          thread = thread.concat([{
            kind: "answer", asked: asked, asked_by: person, when: "",
            said: "", withheld: "", looked_at: [], task_id: "", task: null,
            trouble: said(error) || word("load_failed", "")
          }]);
          drawThread();
        });
    }

    /* Enter sends it; Shift and Enter puts in a line. The box grows with what
       is typed into it and stops at a few lines, so a long question is
       readable without the thread above it disappearing. */
    function grow() {
      box.style.height = "auto";
      box.style.height = Math.min(box.scrollHeight, 132) + "px";
    }
    box.addEventListener("input", grow);
    box.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.dispatchEvent(new Event("submit", { cancelable: true }));
      }
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var asked = box.value.trim();
      if (!asked) { return; }
      box.value = "";
      grow();
      send(asked);
    });
    box.focus();
  }

  /* The thread as the server holds it, which is as the record holds it: every
     exchange is an event, so the conversation is read back out of the log
     rather than kept beside it. It is keyed on who asked rather than on this
     browser, which is why signing in somewhere else brings the same thread.

     A failure here is not shown. An empty conversation is a true statement
     about a workspace nobody has asked anything in yet, and an error about a
     route is not something an officer can act on. */
  function readThread() {
    return get("/api/chat").then(absorb).catch(function () { return null; });
  }

  /* Two shapes for one turn, because the route carries the job two ways: as
     an address, and as the job itself. Both are read, and neither is shown. */
  function shapeTurns(turns) {
    return (turns || []).map(function (turn) {
      return {
        kind: turn.kind || "answer",
        asked: turn.asked || "",
        asked_by: turn.asked_by || "",
        when: turn.when || "",
        said: turn.said || "",
        withheld: turn.withheld || "",
        looked_at: turn.looked_at || turn.used || [],
        task_id: turn.task_id || (turn.task && turn.task.task_id) || "",
        task: turn.task || null,
        trouble: ""
      };
    });
  }

  function askedBlock(turn) {
    var meta = [turn.asked_by, turn.when].filter(Boolean).join(" · ");
    return h`<div class="turn-asked">
      <p class="turn-said-text">${turn.asked}</p>
      ${meta ? h`<p class="turn-meta">${meta}</p>` : ""}
    </div>`;
  }

  /* What it read, under the answer. The whole of this product's claim is that
     an answer can be checked, and this is where that is said on the screen. */
  function readChips(steps) {
    if (!(steps || []).length) { return ""; }
    return h`<div class="chips-wrap">
      <p class="tiny faint">${word("ask_looked_at", "")}</p>
      <ul class="chips">${steps.map(function (step) {
        return h`<li>${step}</li>`;
      })}</ul>
    </div>`;
  }

  function turnBlock(turn) {
    return h`<div class="turn">
      ${askedBlock(turn)}
      <div class="turn-said">
        ${turn.trouble ? h`<p class="note bad">${turn.trouble}</p>` : ""}
        ${turn.said ? h`<p class="prose">${turn.said}</p>` : ""}
        ${turn.withheld ? h`<p class="note prose">${turn.withheld}</p>` : ""}
        ${turn.task_id ? h`
          <div class="turn-run">
            ${(turn.task && turn.task.step_count) ? h`<p class="tiny faint">${
              turn.task.done_count
            } / ${turn.task.step_count}</p>` : ""}
            <a class="btn" href="#/run/${encodeURIComponent(turn.task_id)}">${
              word("run_watch", "Watch it run")
            }</a>
          </div>` : ""}
        ${readChips(turn.looked_at)}
      </div>
    </div>`;
  }

  function waitingBlock(pending) {
    return h`<div class="turn">
      ${askedBlock(pending)}
      <div class="turn-said">
        <p class="faint small">${word("ask_thinking", "")}</p>
      </div>
    </div>`;
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
      /* "You have filed something for this" and "you have filed nothing"
         were told apart by the colour of a four-pixel dot and by nothing
         else. So an officer dragged a passport in, watched the row it was
         for stay exactly where it was, and concluded the upload had not
         worked. It had: clause 5.4.5 distinguishes holding a document from
         having verified what it proves, and the row was correctly still
         open on the second. That is a real distinction and worth keeping --
         but it has to be said in words, because nobody decodes a colour. */
      return h`<li>
        <span class="dot" data-tone="${unevidenced ? "today" : "later"}"></span>
        <div class="owed-body">
          <div class="owed-name">${need.asks_for || ""}</div>
          ${unevidenced
            ? h`<div class="owed-held">${
                word("onboard_held_unevidenced", "")
              }</div>`
            : h`<div class="owed-why">${need.because || ""}</div>`}
          ${need.basis
            ? h`<details class="owed-more">
                 <summary>${word("onboard_why_asked", "Why is this asked for?")}</summary>
                 ${unevidenced && need.because
                   ? h`<p class="owed-why">${need.because}</p>` : ""}
                 <p class="owed-basis">${need.basis}</p>
               </details>` : ""}
        </div>
        ${unevidenced
          ? h`<span class="badge" data-tone="today">${
              word("onboard_held_badge", "Filed")
            }</span>`
          : ""}
        ${need.mandatory === false ? h`<span class="badge" data-tone="later">${
          word("onboard_practice", "Practice")
        }</span>` : ""}
      </li>`;
    }

    /* What the document turned out to say, under the document that said it.

       This was being thrown away. The server has read every upload since the
       reader was written and the reply went into an empty `then`, so an
       officer filed a passport and then typed its date of birth in by hand
       from the same passport. Nothing was wrong with the reading; it simply
       never reached the screen.

       Every value carries the line it was read from, and which reader found
       it -- parsed off the page, or looked at by a model because the file was
       a photograph. An officer confirming a date of birth is entitled to know
       which, and the two are not equally strong. */
    function readingRows(file) {
      if (file.unreadable) {
        return h`<p class="filed-unread small">${file.unreadable}</p>`;
      }
      if (!(file.proposals || []).length) { return ""; }
      /* An expired document is still filed and still read -- what a firm
         holds is a fact about the firm. What changes is that this is said,
         above the fields rather than among them, because it is about the
         paper and not about the party. */
      var expired = file.expired
        ? h`<p class="filed-expired small">${file.expired}</p>` : "";
      return h`${expired}<ul class="filed-read">${file.proposals.map(function (one) {
        return h`<li>
          <span class="filed-field">${word("read_field_" + one.field, one.field)}</span>
          <span class="filed-value">${one.value}</span>
          ${one.on_record && !one.agrees
            ? h`<span class="badge" data-tone="today">${
                word("read_differs", "differs")
              } ${one.on_record}</span>`
            : ""}
          ${one.agrees
            ? h`<span class="badge" data-tone="good">${
                word("read_agrees", "agrees")
              }</span>` : ""}
          <span class="filed-seen tiny faint">${one.seen_as}</span>
          <span class="filed-by tiny faint">${one.read_by || ""}</span>
        </li>`;
      })}</ul>`;
    }

    function drawFiled() {
      mount(document.getElementById("filed"), added.map(function (file) {
        return h`<li>
                   <span class="filed-name">${file.name}</span>
                   <span class="filed-state" data-tone="${file.tone}">${file.state}</span>
                   ${readingRows(file)}
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
        postBytes("/api/onboarding/" + encodeURIComponent(partyId) +
                  "/documents?filename=" + encodeURIComponent(file.name), file)
          .then(function (reply) {
            row.state = word("onboard_added", "Added");
            row.tone = "good";
            var got = (reply && reply.read) || {};
            row.proposals = got.proposals || [];
            row.unreadable = got.unreadable || "";
            row.expired = got.expired || "";
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
    /* The party's permanent record, asked for as this screen opens rather
       than when the download is pressed. It is what the downloaded file
       opens with -- the warning about who may read it -- and it carries the
       decisions in the deciders' own words and the seal over the records
       cited. Nothing here waits for it: it is a second request running
       beside the first, and the report renders whether it arrives or not. */
    var recorded = get("/api/records/" + encodeURIComponent(partyId))
      .catch(function () { return null; });

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
      .then(function () { drawReport(where, record, files, run, recorded); })
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
                   /* Named two ways by the route during this rebuild, and
                      both are read. A check whose detail is dropped reads on
                      the page, and in the file downloaded off it, as a check
                      that found nothing. */
                   details: cleanLines(check.detail || check.details) };
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

  function drawReport(where, record, files, run, recorded) {
    var say = reportWords();
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
          <div class="take" id="take-report"></div>
        </div>

        <section>
          <h2 class="section-head">${say.checked}</h2>
          ${checked.rows.length ? h`
            <div class="table-wrap">
              <table class="grid">
                <thead><tr>
                  <th>${say.col_check}</th>
                  <th>${checked.middle}</th>
                  <th>${say.col_result}</th>
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
            </div>` : h`<p class="empty">${say.checked_none}</p>`}
        </section>

        <section>
          <h2 class="section-head">${say.outstanding}</h2>
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
          })}</ul>` : h`<p class="note good">${say.owed_none}</p>`}
          ${(record.not_modelled && record.not_modelled.length) ? h`
            <h3 class="section-head">${say.not_modelled}</h3>
            <ul class="bullets small prose">${record.not_modelled.map(function (line) {
              return h`<li>${line}</li>`;
            })}</ul>` : ""}
        </section>

        <section>
          <h2 class="section-head">${say.findings}</h2>
          ${findings.length ? findings.map(function (finding, index) {
            var file = (files || [])[index];
            /* The file's own headline first, and the evidence line only
               where there is no file. The evidence line is the record's
               own summary of what fired -- "SANCTIONS match for Kavya
               Singh" -- and the leading word there is a value out of the
               engine, not a word anybody says. It was reaching the screen:
               `cleanSentence` only drops a token with an underscore in it,
               so ADVERSE_MEDIA was caught and SANCTIONS was not. */
            return h`<div class="finding" data-tone="${severityTone(finding.severity)}">
              ${fileBlock({
                headline: (file && file.headline)
                  || cleanSentence(finding.summary) || "",
                rules_heading: rulesHeading(finding, file),
                clauses: clauseTags(finding, file),
                steps: (file && file.to_close_this) || [],
                detail: theDetail(file)
              })}
            </div>`;
          }) : h`<p class="note good">${say.findings_none}</p>`}
        </section>

        <section>
          <h2 class="section-head">${say.ownership}</h2>
          ${ownershipSaid(ownership) ? h`<p class="prose">${
            ownershipSaid(ownership)
          }</p>` : ""}
          ${ownershipTree(ownership, party, ownershipNote(record, files))}
          ${ownerRows(ownership).length
            ? h`<p class="tiny eyebrow">${
                word("report_ownership_in_words", "The same, in words")
              }</p>` : ""}
          ${ownerChain(ownership)}
          ${(!ownershipSaid(ownership) && !ownerRows(ownership).length
             && !((ownership && ownership.cycles) || []).length
             && !(ownership && ownership.conclusion))
            ? h`<p class="empty">${say.ownership_none}</p>` : ""}
          ${cycleLines(ownership).length ? h`
            <ul class="bullets small prose">${cycleLines(ownership).map(function (line) {
              return h`<li>${line}</li>`;
            })}</ul>` : ""}
          ${ownership && ownership.caveat ? h`<p class="note prose">${
            ownership.caveat
          }</p>` : ""}
        </section>

        <div id="ask-this-report"></div>

        <div id="the-decision"></div>
      </div>`);

    /* The eight checks establish; this interprets. It is given the party's
       identifier and nothing else -- everything it reads about them is
       fetched by the server out of the record, so the page cannot describe a
       party to the assistant, only name one. */
    reportAsk(document.getElementById("ask-this-report"), party);

    /* The same file from either place it can be asked for, built out of what
       this screen was given plus the party's permanent record -- so the
       document somebody sends to their board and the screen they read it on
       cannot say different things. */
    downloadAction(document.getElementById("take-report"), function () {
      return Promise.resolve(recorded).then(function (doc) {
        return documentFor(doc, record, files, run);
      });
    }, party && party.id);

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

  /* The ownership answer as a sentence, or nothing.

     The machine-readable conclusion beside it is a value the records are
     keyed by and is never printed. It used to be the fallback here, and
     `shown()` let it through: the sweep for implementation vocabulary looks
     for an underscore, and INCOMPLETE has none — so the word INCOMPLETE was
     on the report, in front of an officer, as the whole of what we had to
     say about who owns a company. Where the sentence does not survive, the
     drawing carries the product's own words instead (`ownershipNote`). */
  function ownershipSaid(ownership) {
    if (!ownership) { return ""; }
    return cleanSentence(ownership.explains);
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

  /* ---------- one file, in the order a person asks about it ----------

     A file has to answer three questions, and an officer with somebody
     sitting opposite them has about five seconds to get through all three:
     what is wrong, why does it matter, what do I do now. So they are the
     three things on the screen, in that order, and nothing else is -- the
     sentences behind the headline, the compared rows, the payment's own
     reference and the order things happened in all sit folded underneath,
     closed, because none of them is read until somebody is challenged.

     It used to be the other way round. The file opened on two paragraphs of
     explanation, then a table, and the three buttons that are the entire
     point of the screen were below all of it. Every sentence here is still
     the server's: what this decides is the order, and what is folded.

     The same block does the finding on an onboarding report and the file
     opened in the list, deliberately -- an officer should not have to learn
     two shapes for one thing. */
  function fileBlock(parts) {
    var steps = parts.steps || [];
    return h`
      <div class="file">
        <div class="file-what">
          <p class="eyebrow">${word("what_happened", "What happened")}</p>
          <p class="file-headline">${parts.headline || ""}</p>
        </div>

        ${parts.clauses ? h`
          <div class="file-why">
            <p class="eyebrow">${parts.rules_heading || ""}</p>
            ${parts.clauses}
          </div>` : ""}

        ${(steps.length || parts.decides) ? h`
          <div class="file-now">
            ${steps.length ? h`
              <p class="eyebrow">${word("to_close_heading", "")}</p>
              <ul class="bullets small prose">${steps.map(function (line) {
                return h`<li>${line}</li>`;
              })}</ul>` : ""}
            ${parts.decides ? h`<div class="file-decision"></div>` : ""}
          </div>` : ""}

        ${parts.detail ? h`
          <details class="fold">
            <summary>${word("the_detail", "The detail")}</summary>
            <div class="fold-body">${parts.detail}</div>
          </details>` : ""}
      </div>`;
  }

  /* Everything below the fold, out of a file or out of a list item -- the two
     carry the same fields under the same names, and the file adds the order
     things happened in. Empty means empty: a fold with nothing behind it is
     worse than no fold, so this returns nothing at all and `fileBlock` omits
     it. */
  function theDetail(source) {
    if (!source) { return ""; }
    var reference = shown(source.line || source.about || "");
    var because = source.because || [];
    var rows = source.side_by_side || [];
    var moments = (source.timeline || []).filter(function (moment) {
      return cleanSentence(moment && moment.what);
    });
    if (!reference && !because.length && !rows.length && !moments.length
        && !source.corroboration) {
      return "";
    }
    return h`
      ${reference ? h`<p class="file-ref">${reference}</p>` : ""}
      ${because.length ? h`<div class="prose small soft">${
        because.map(function (line) { return h`<p>${line}</p>`; })
      }</div>` : ""}
      ${rows.length ? h`
        <div class="table-wrap"><table class="grid">
          <thead><tr><th></th><th>${source.ours_label || ""}</th><th>${
            source.theirs_label || ""
          }</th><th></th></tr></thead>
          <tbody>${rows.map(function (line) {
            return h`<tr>
              <td>${line.what}</td><td class="num">${line.ours}</td>
              <td class="num">${line.theirs}</td>
              <td><span class="dot" data-tone="${
                line.tone === "differs" ? "stop"
                  : line.tone === "same" ? "good" : "later"
              }"></span> ${line.says}</td>
            </tr>`;
          })}</tbody>
        </table></div>` : ""}
      ${source.corroboration ? h`<p class="note">${source.corroboration}</p>` : ""}
      ${moments.length ? h`
        <p class="eyebrow">${source.timeline_heading || ""}</p>
        <ul class="timeline">${moments.map(function (moment) {
          return h`<li>
            <div class="when">${moment.when}</div>
            <div>${cleanSentence(moment.what)}</div>
          </li>`;
        })}</ul>` : ""}`;
  }

  /* One clause, out of whichever shape it arrived in.

     Two routes carry the same rule and disagree about the field names. The
     onboarding record sends the register's own row -- the regulator's
     verbatim extract, the edition it was read from, the page. A file sends
     the rule as briefing.py restates it in plain words, with the extract
     beside it and its own caution about who has checked it. Both are folded
     into one shape here so a clause is shown one way on every screen rather
     than two half-ways: the file route used to keep the number and the
     restatement and drop the regulator's own words, the page and the link
     on the floor.

     What arrives is the server's; the ordering is this file's. */
  function citedClause(source, fromRegister) {
    if (fromRegister) {
      return {
        clause: source.clause,
        plain: shown(source.heading || ""),
        quote: source.says || "",
        document: source.document || "",
        edition: source.edition || "",
        page: source.page || "",
        amended: source.amended || "",
        url: source.url || "",
        link_text: "",
        verified: !!source.verified,
        checked_on: source.checked_on || "",
        caution: ""
      };
    }
    return {
      clause: source.clause,
      plain: source.says || "",
      quote: source.quote || "",
      document: source.document || "",
      edition: "", page: "", amended: "",
      url: source.link || "",
      link_text: source.link_text || "",
      verified: !!source.checked_by_a_person,
      checked_on: "",
      caution: source.caution || ""
    };
  }

  /* Every clause behind one finding -- once each, however many pieces of
     evidence cited it. */
  function clausesOf(finding, file) {
    var cited = [];
    ((finding && finding.clauses) || []).forEach(function (clause) {
      if (typeof clause === "string") {
        cited.push(citedClause({ clause: clause }, true));
      } else if (clause && clause.clause) {
        cited.push(citedClause(clause, true));
      }
    });
    if (!cited.length && file && file.rules) {
      (file.rules || []).forEach(function (rule) {
        if (rule && rule.clause) { cited.push(citedClause(rule, false)); }
      });
    }
    var seen = {}, only = [];
    cited.forEach(function (one) {
      if (seen[one.clause]) { return; }
      seen[one.clause] = true;
      only.push(one);
    });
    return only;
  }

  /* Whether this rests on one rule or several. Both words are the server's;
     this only counts. */
  function rulesHeading(finding, file) {
    return clausesOf(finding, file).length > 1
      ? word("rules_heading", "") : word("rule_heading", "");
  }

  function clauseTags(finding, file) {
    // "Clause 5.4.2" and nothing else is the shape of an answer nobody can
    // check. The officer cannot tell whether the rule says what we claim it
    // says, and neither can the inspector they are answering to -- so the
    // number alone is a citation in the way a footnote with no book is a
    // citation. The register holds the regulator's own sentence, the edition
    // it was read from, the page and the link. All of it goes on the screen,
    // folded away until asked for: this is why a file matters, and it is the
    // part an officer opens only when somebody challenges them.
    var only = clausesOf(finding, file);
    if (!only.length) { return ""; }

    return h`<ul class="clauses">${only.map(function (one) {
      var where = [
        one.document,
        one.edition,
        one.page ? "page " + one.page : ""
      ].filter(Boolean).join(" · ");
      var named = h`<span class="clause">${word("clause_prefix", "")} ${
        one.clause
      }</span>${one.plain ? h`<span class="clause-plain">${one.plain}</span>` : ""}`;
      if (!one.quote && !where && !one.url && !one.amended && one.verified) {
        return h`<li>${named}</li>`;
      }
      return h`<li><details class="clause-source">
        <summary>${named}</summary>
        ${one.quote ? h`<blockquote class="clause-says">${one.quote}</blockquote>` : ""}
        ${one.amended ? h`<p class="clause-note">${one.amended}</p>` : ""}
        ${where ? h`<p class="clause-where">${where}</p>` : ""}
        ${one.url ? h`<p class="clause-where"><a href="${
          one.url
        }" rel="noreferrer noopener" target="_blank">${
          one.link_text || word("read_clause", "")
        }</a></p>` : ""}
        ${one.verified ? "" : h`<p class="clause-unverified">${
          one.caution || unverifiedCaution(one.checked_on)
        }</p>`}
      </details></li>`;
    })}</ul>`;
  }

  /* One decimal at most, and no trailing nought. The server rounded the
     arithmetic; this only decides how it is spelt. */
  function oneDecimal(value) {
    var rounded = Math.round(Number(value) * 10) / 10;
    return isFinite(rounded) ? String(rounded) : "";
  }

  /* The owners the server sent, in the one shape both the drawing and the
     list below it read. Nothing is computed here: `percentage` is the share
     the walk found reaching that person, already rounded. */
  function ownerRows(ownership) {
    return ((ownership && ownership.owners) || []).map(function (owner) {
      if (typeof owner === "string") {
        return { who: shown(owner), share: "", note: "", percent: null };
      }
      var percent = (typeof owner.percentage === "number" &&
                     isFinite(owner.percentage)) ? owner.percentage : null;
      var share = owner.share || owner.stake || owner.holding || "";
      if (!share && percent !== null) {
        /* A figure the server computed, given the sign it is measured in.
           Formatting a number is not the same as writing a sentence. */
        share = oneDecimal(percent) + "%";
      }
      return {
        who: shown(owner.name || owner.who || ""),
        share: shown(share),
        note: shown(owner.basis || owner.through || owner.says || ""),
        percent: percent
      };
    }).filter(function (owner) { return owner.who; });
  }

  /* The same owners as words, under the drawing. This is the fallback for a
     reader who cannot see the picture, and it is left visible rather than
     folded away: it also carries the figures in a form that can be copied. */
  function ownerChain(ownership) {
    var owners = ownerRows(ownership);
    if (!owners.length) { return ""; }
    return h`<ul class="chain">${owners.map(function (owner) {
      return h`<li>
                 <div class="chain-who">${owner.who}</div>
                 ${owner.share ? h`<div class="chain-share">${owner.share}</div>` : ""}
                 ${owner.note ? h`<div class="chain-share">${owner.note}</div>` : ""}
               </li>`;
    })}</ul>`;
  }

  /* ---------- ownership, drawn ----------

     Ownership reached this screen as a list of lines, and a list is the one
     shape that hides the two things an officer is actually looking for: where
     a holding chain turns back on itself, and where it stops before it
     reaches a person. Both are drawn here, at the size of the thing they are
     about, and neither is a footnote.

     Only what the server sent is drawn. `owners` carries a name and the
     percentage that reaches that person through the whole structure; the
     companies in between are not on this route, so no company is drawn. A
     tidy three-level tree assembled in the browser would be a picture of
     something nobody established, which is the one thing this drawing must
     not be. Where the walk did not finish, the drawing says so instead of
     closing the gap.

     Inline SVG, because the Content-Security-Policy this page is served
     under admits this origin and nothing else: no chart library, no canvas,
     no remote image. Geometry travels as attributes and every colour is a
     class in app.css, because that same policy admits no inline style — and
     a test asserts this file contains none. */

  /* IFSCA clause 1.3.3, transcribed from IFSCA_TESTS in vinzor/graph.py.
     Nothing is decided from it: it places one mark on a meter so that a
     holding sitting just over the line can be told from one sitting just
     under it. Where the kind of party is not one of these the mark is left
     off rather than guessed.

     1.3.3(a) says "more than ten per cent"; 1.3.3(d) says "ten per cent or
     more". The difference is in the regulator's text, so it is on the
     drawing. The wording goes through word() so briefing.py can take it
     over without this file changing. */
  var OWNERSHIP_TESTS = {
    COMPANY: { line: 10, orMore: false, clause: "1.3.3(a)" },
    FUND: { line: 10, orMore: false, clause: "1.3.3(a)" },
    PARTNERSHIP: { line: 10, orMore: false, clause: "1.3.3(b)" },
    UNINCORPORATED_BODY: { line: 15, orMore: false, clause: "1.3.3(c)" },
    TRUST: { line: 10, orMore: true, clause: "1.3.3(d)" }
  };

  /* Two routes spell the kind of party two ways — the value the records are
     keyed by on one, the word a person says on the other. Neither is printed
     from here; both have to find the same test. */
  function testFor(kind) {
    var key = String(kind || "").trim().toUpperCase().replace(/\s+/g, "_");
    return OWNERSHIP_TESTS[key] || null;
  }

  function thresholdWords(test) {
    var phrase = test.orMore
      ? word("ownership_test_or_more", "{n}% or more")
      : word("ownership_test_above", "more than {n}%");
    return word("ownership_test_lead", "Beneficial owner") + ": " +
           phrase.replace("{n}", oneDecimal(test.line)) + " · " +
           word("clause_prefix", "Clause") + " " + test.clause;
  }

  /* What to write on a branch that never arrives at a person. Which of the
     three it is, is the server's answer, read straight off the conclusion —
     this only chooses which label to hang on the mark. */
  function looseLabel(conclusion) {
    if (conclusion === "NOT_DECLARED") {
      return word("ownership_not_declared", "No ownership declared");
    }
    if (conclusion === "SENIOR_MANAGING_OFFICIAL_REQUIRED") {
      return word("ownership_none_meet", "Nobody meets the test");
    }
    return word("ownership_unfinished", "Stops before a person");
  }

  /* SVG text does not wrap and there is no way to measure a glyph before it
     is laid out, so this estimates: the system sans this page uses averages
     about 0.55 of its size per character. A name is only ever cut on the
     drawing — the whole of it is on the node as a tooltip, in the list under
     the drawing, and in the heading above it. */
  function fitLines(text, width, size, allowed) {
    var per = Math.max(4, Math.floor(width / (size * 0.55)));
    var words = String(text == null ? "" : text).split(/\s+/).filter(Boolean);
    var out = [], line = "";
    words.forEach(function (piece) {
      var next = line ? line + " " + piece : piece;
      if (!line || next.length <= per) { line = next; return; }
      out.push(line);
      line = piece;
    });
    if (line) { out.push(line); }
    if (out.length > allowed) {
      out = out.slice(0, allowed);
      out[allowed - 1] = out[allowed - 1] + "…";
    }
    return out.map(function (one) {
      return one.length > per ? one.slice(0, Math.max(1, per - 1)) + "…" : one;
    });
  }

  /* Every measurement on the drawing, in the units of its own viewBox. The
     box is 880 wide whatever the window is: the browser scales it to the
     column, so one set of numbers serves a 1440-wide screen and a sheet of
     A4 alike. Four to a row, and an even number on purpose — the spine runs
     down the middle of the box and would otherwise have to cross a node to
     reach the row below. */
  var TREE = {
    width: 880, gutter: 16, perRow: 4,
    nodeWidth: 190, nodeGap: 22, nodeHeight: 104, rowGap: 30,
    partyWidth: 470, partyHeight: 62,
    top: 12, trunk: 42, drop: 30, foot: 66
  };

  var TREE_COUNT = 0;

  function ownershipTree(ownership, party, note) {
    if (!ownership) { return ""; }

    var T = TREE;
    var people = ownerRows(ownership);
    var loops = ((ownership.cycles) || []).length;
    var conclusion = String(ownership.conclusion || "").toUpperCase();
    var resolved = conclusion === "IDENTIFIED";
    var test = testFor(party && party.kind);

    /* A loop is drawn as a loop, once per circle the walk came back with.
       The references it names are machine addresses and are never printed;
       the shape is the finding, and the sentence under the drawing is the
       product's own. */
    var items = [], i;
    for (i = 0; i < Math.min(loops, 3); i++) {
      items.push({ mark: "loop", label: word("ownership_loops", "Ownership loops back") });
    }
    if (!resolved && !loops && conclusion) {
      items.push({ mark: "loose", label: looseLabel(conclusion), open: true });
    }
    people.forEach(function (owner) { items.push({ owner: owner }); });
    if (!items.length) { return ""; }

    var mid = T.width / 2;
    var partyLeft = mid - T.partyWidth / 2;
    var partyBottom = T.top + T.partyHeight;

    var rows = [];
    for (i = 0; i < items.length; i += T.perRow) {
      rows.push(items.slice(i, i + T.perRow));
    }
    var band = T.drop + T.nodeHeight + T.rowGap;
    var firstBus = partyBottom + T.trunk;
    var lastBus = firstBus + (rows.length - 1) * band;
    /* Whether anything on this drawing carries a figure decides how much
       foot it needs: two lines of key where there are meters to read, one
       where there are not. */
    var measured = items.some(function (item) {
      return item.owner && item.owner.percent !== null;
    });
    var lastNodeBottom = lastBus + T.drop + T.nodeHeight;
    var height = lastNodeBottom + (measured ? T.foot : T.foot - 26);

    var ink = [], returns = [];
    function put(markup) { ink.push(raw(markup)); }
    function n(value) { return Math.round(value * 10) / 10; }
    function box(cls, x, y, w, hgt, r) {
      return '<rect class="' + cls + '" x="' + n(x) + '" y="' + n(y) +
             '" width="' + n(w) + '" height="' + n(hgt) + '" rx="' + r + '"/>';
    }

    /* the spine, and one bus per row */
    put('<path class="tree-edge" d="M ' + n(mid) + ' ' + n(partyBottom) +
        ' V ' + n(lastBus) + '"/>');

    rows.forEach(function (row, r) {
      var busY = firstBus + r * band;
      var topY = busY + T.drop;
      var span = row.length * T.nodeWidth + (row.length - 1) * T.nodeGap;
      var left = mid - span / 2;

      if (row.length > 1) {
        put('<path class="tree-edge" d="M ' + n(left + T.nodeWidth / 2) + ' ' +
            n(busY) + ' H ' + n(left + span - T.nodeWidth / 2) + '"/>');
      }

      row.forEach(function (item, c) {
        var nx = left + c * (T.nodeWidth + T.nodeGap);
        var centre = nx + T.nodeWidth / 2;

        put('<path class="tree-edge' + (item.open ? " tree-edge-open" : "") +
            '" d="M ' + n(centre) + ' ' + n(busY) + ' V ' + n(topY) + '"/>');

        /* the percentage rides the edge it belongs to, not the node */
        if (item.owner && item.owner.percent !== null) {
          var said = oneDecimal(item.owner.percent) + "%";
          var wide = 16 + said.length * 7.4;
          put(box("tree-pill", centre - wide / 2, busY + T.drop / 2 - 9, wide, 18, 9));
          ink.push(h`<text class="tree-pill-text" x="${n(centre)}" y="${
            n(busY + T.drop / 2 + 4)
          }" text-anchor="middle">${said}</text>`);
        }

        if (item.owner) {
          ink.push(personNode(nx, topY, item.owner, test, n, box));
        } else {
          ink.push(markNode(nx, topY, item, n, box));
          /* The grommet where an open branch meets its node, drawn after the
             node so it sits on the edge rather than under it. */
          if (item.open) {
            put('<circle class="tree-open-end" cx="' + n(centre) + '" cy="' +
                n(topY) + '" r="4.5"/>');
          }
          if (item.mark === "loop") {
            returns.push({ x: nx, y: topY + T.nodeHeight / 2,
                           under: topY + T.nodeHeight });
          }
        }
      });
    });

    /* the party, drawn over the spine that leaves it */
    ink.push(h`<g class="tree-node tree-party">
      <title>${(party && party.name) || ""}</title>
      ${raw(box("tree-box tree-box-party", partyLeft, T.top,
                T.partyWidth, T.partyHeight, 10))}
      <text class="tree-party-name" x="${n(mid)}" y="${n(T.top + 31)}"
            text-anchor="middle">${
              fitLines(party && party.name, T.partyWidth - 44, 17, 1)[0] || ""
            }</text>
      <text class="tree-party-kind" x="${n(mid)}" y="${n(T.top + 49)}"
            text-anchor="middle">${kindWord(party && party.kind)}</text>
    </g>`);

    /* and the arrow that makes a circle a circle: out of the marked node,
       down the left gutter and back into the party it started from */
    returns.forEach(function (from, k) {
      var lane = T.gutter + k * 13;
      var toY = T.top + T.partyHeight / 2 + (k - (returns.length - 1) / 2) * 10;
      /* The first circle leaves from the side of its node, which is the
         leftmost thing in its row, so the curve crosses nothing. A second
         one has the first sitting between it and the gutter, so it leaves
         from underneath and runs home along the gap below the row rather
         than straight through a node that is not part of it. */
      var start = k === 0
        ? 'M ' + n(from.x) + ' ' + n(from.y)
        : 'M ' + n(from.x + T.nodeWidth / 2) + ' ' + n(from.under) +
          ' V ' + n(from.under + 14 + k * 6);
      var leaveY = k === 0 ? from.y : from.under + 14 + k * 6;
      put('<path class="tree-return" d="' + start +
          ' C ' + n(lane) + ' ' + n(leaveY) + ' ' + n(lane) + ' ' + n(toY) +
          ' ' + n(partyLeft - 11) + ' ' + n(toY) + '"/>');
      put('<path class="tree-return-head" d="M ' + n(partyLeft) + ' ' + n(toY) +
          ' L ' + n(partyLeft - 12) + ' ' + n(toY - 5.5) +
          ' L ' + n(partyLeft - 12) + ' ' + n(toY + 5.5) + ' Z"/>');
    });

    /* The foot reads every meter above it: the scale it is drawn on at each
       end, the regulator's line where the mark falls, and what the figures
       are shares of. A key, not a sentence about this party. */
    var footY = lastNodeBottom + 28;
    var sentenceX = 28;
    if (test && measured) {
      /* The key only where there is a meter to read with it. On a drawing
         with no figures on it — a chain that only loops — a scale from
         nothing to twice the line is a legend for something that is not
         there. The test itself still gets said: it is what could not be
         applied. */
      var topOfScale = oneDecimal(test.line * 2) + "%";
      var keyX = 38, keyW = 88;
      ink.push(h`<text class="tree-foot tree-foot-note" x="28" y="${n(footY + 3)}"
                       text-anchor="start">0</text>`);
      put(box("tree-meter-track", keyX, footY - 4, keyW, 8, 4));
      put(box("tree-meter-halo", keyX + keyW / 2 - 3, footY - 9, 6, 18, 2));
      put(box("tree-meter-tick", keyX + keyW / 2 - 1, footY - 8, 2, 16, 1));
      ink.push(h`<text class="tree-foot tree-foot-note" x="${n(keyX + keyW + 6)}"
                       y="${n(footY + 3)}" text-anchor="start">${topOfScale}</text>`);
      sentenceX = keyX + keyW + 16 + topOfScale.length * 6.8;
    }
    if (test) {
      ink.push(h`<text class="tree-foot" x="${n(sentenceX)}" y="${n(footY + 3)}"
                       text-anchor="start">${thresholdWords(test)}</text>`);
    }
    if (measured) {
      ink.push(h`<text class="tree-foot tree-foot-note" x="28" y="${n(footY + 26)}"
                       text-anchor="start">${
        word("ownership_reach_note",
             "Each figure is the share that reaches that person through the " +
             "whole of the structure on record.")
      }</text>`);
    }

    var id = "tree" + (++TREE_COUNT);
    var spoken = items.map(function (item) {
      if (!item.owner) { return item.label; }
      return item.owner.percent === null
        ? item.owner.who
        : item.owner.who + " " + oneDecimal(item.owner.percent) + "%";
    }).join("; ");

    return h`<figure class="tree">
      <svg class="tree-svg" viewBox="0 0 ${n(T.width)} ${n(height)}"
           role="img" aria-labelledby="${id}-t ${id}-d" focusable="false"
           preserveAspectRatio="xMidYMid meet">
        <title id="${id}-t">${word("report_ownership", "Who is behind this party")}${
          (party && party.name) ? " — " + party.name : ""
        }</title>
        <desc id="${id}-d">${spoken}</desc>
        ${ink}
      </svg>
      ${note ? h`<figcaption class="tree-note prose">${note}</figcaption>` : ""}
    </figure>`;
  }

  /* The meter under each name, and the one decision in this drawing worth
     arguing about: it does not run from nothing to everything.

     Drawn 0–100%, the regulator's line lands an eighth of the way along and
     a holding of 10.4% ends four tenths of a millimetre past it — which is
     to say the two states this whole test distinguishes look identical, and
     10.4% and 9.6% look identical to each other. The line is where the
     reading happens, so the scale is built around it: nothing to twice the
     line, with the line itself dead centre of every meter on the page. A
     holding past the top of that scale fills the meter and is marked as
     running off the end, which is the true thing to say about it — that it
     is well clear — and the exact figure is set above it in full anyway.

     Below the line is where an eighth of a point decides the answer, and no
     bar of any scale reads that finely. That is the number's job, and it is
     the largest thing on the node. */
  function meterOf(owner, test, nx, my, n, box) {
    if (owner.percent === null || !test) { return ""; }
    var mx = nx + 18, mw = TREE.nodeWidth - 44;
    var top = test.line * 2;
    var share = Number(owner.percent);
    var meter = box("tree-meter-track", mx, my, mw, 8, 4) +
                box("tree-meter-fill", mx, my,
                    mw * Math.max(0, Math.min(1, share / top)), 8, 4) +
                box("tree-meter-halo", mx + mw / 2 - 3, my - 5, 6, 18, 2) +
                box("tree-meter-tick", mx + mw / 2 - 1, my - 4, 2, 16, 1);
    if (share > top) {
      meter += '<path class="tree-meter-over" d="M ' + n(mx + mw + 5) + ' ' +
               n(my) + ' L ' + n(mx + mw + 12) + ' ' + n(my + 4) + ' L ' +
               n(mx + mw + 5) + ' ' + n(my + 8) + ' Z"/>';
    }
    return meter;
  }

  /* One natural person: the name, the share that reaches them, and the
     meter, with the regulator's line marked on it. */
  function personNode(nx, ny, owner, test, n, box) {
    var T = TREE;
    var meter = meterOf(owner, test, nx, ny + 78, n, box);
    return h`<g class="tree-node tree-person">
      <title>${owner.who}</title>
      ${raw(box("tree-box", nx, ny, T.nodeWidth, T.nodeHeight, 9))}
      ${fitLines(owner.who, T.nodeWidth - 24, 14, 2).map(function (line, k) {
        return h`<text class="tree-name" x="${n(nx + T.nodeWidth / 2)}" y="${
          n(ny + 24 + k * 17)
        }" text-anchor="middle">${line}</text>`;
      })}
      ${owner.percent === null ? "" : h`<text class="tree-pct" x="${
        n(nx + T.nodeWidth / 2)
      }" y="${n(ny + 68)}" text-anchor="middle">${
        oneDecimal(owner.percent) + "%"
      }</text>`}
      ${raw(meter)}
    </g>`;
  }

  /* A branch that does not arrive: the circle drawn as a circle, or the open
     end drawn as an end. Both are marked in the colour the rest of the
     product uses for "this is the thing to look at". */
  function markNode(nx, ny, item, n, box) {
    var T = TREE;
    var gx = nx + T.nodeWidth / 2, gy = ny + 34;
    var glyph = item.mark === "loop"
      ? '<g class="tree-glyph-loop" transform="translate(' + n(gx) + ' ' +
        n(gy) + ')"><path class="tree-ring" d="M 4.5 -7.8 A 9 9 0 1 1 -4.5 -7.8"/>' +
        '<path class="tree-ring-head" d="M 0.3 -10.5 L -2.9 -5 L -6.1 -10.6 Z"/></g>'
      : '<g class="tree-glyph-open" transform="translate(' + n(gx) + ' ' +
        n(gy) + ')"><circle cx="-12" cy="0" r="2.8"/><circle cx="0" cy="0" r="2.8"/>' +
        '<circle cx="12" cy="0" r="2.8"/></g>';
    return h`<g class="tree-node tree-${item.mark}">
      <title>${item.label}</title>
      ${raw(box("tree-box", nx, ny, T.nodeWidth, T.nodeHeight, 9))}
      ${raw(glyph)}
      ${fitLines(item.label, T.nodeWidth - 20, 13, 2).map(function (line, k) {
        return h`<text class="tree-label" x="${n(nx + T.nodeWidth / 2)}" y="${
          n(ny + 66 + k * 17)
        }" text-anchor="middle">${line}</text>`;
      })}
    </g>`;
  }

  /* The sentence that goes under the drawing where the structure could not be
     resolved. Not written here: `explains` names the party by the reference
     the records are keyed by and so rarely survives the guard, and the file
     opened on the ownership finding says the same thing in words already
     written for a reader. Whichever is used is rendered whole. */
  function ownershipNote(record, files) {
    if (ownershipSaid(record && record.ownership)) { return ""; }
    var found = "";
    ((record && record.findings) || []).forEach(function (finding, index) {
      if (found) { return; }
      if (String(finding.case_type || "").toUpperCase().indexOf("UBO") < 0) { return; }
      var file = (files || [])[index];
      if (!file) { return; }
      found = cleanSentence(file.headline) || cleanLines(file.because)[0] || "";
    });
    return found;
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

  /* ---------- the file that leaves the building ---------- */

  /* An officer is not asked for a screen. They are asked for the file — by
     their own board, by a bank doing correspondent diligence, by an
     inspector reading it eighteen months from now. So the report is built
     here into one HTML document the browser saves: its styling travels
     inside it, it fetches nothing, and it opens on a machine that has never
     heard of this product.

     Built in the browser on purpose. No route is added — nothing about an
     investor is sent anywhere in order to produce a document out of
     sentences the server has already said — and nothing is added to a
     product whose core is standard library only.

     The order, the warning at the top and the seal at the bottom are
     dossier.py's, not this file's. Two of its decisions are carried over
     deliberately:

     * **The warning comes first, and in black on white.** A caution that
       exists only as a pale tint is the first thing a photocopier throws
       away, and this document's whole danger is that it travels.
     * **There is no shortened version.** dossier.py argues it at length: a
       redacted file would look safe to hand to the customer and would not
       be, because the disclosure is that the document exists at all. */

  var DOC_CSS = `
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; background: #fff; color: #000;
  font: 13.5px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
}
.doc { max-width: 186mm; margin: 0 auto; padding: 24px 20px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; line-height: 1.25; }
h2 { font-size: 12.5px; margin: 0 0 10px; letter-spacing: .07em;
     text-transform: uppercase; border-bottom: 1.5px solid #000;
     padding-bottom: 5px; }
h3 { font-size: 14.5px; margin: 0 0 7px; }
p { margin: 0 0 8px; }
.meta { color: #333; font-size: 12.5px; margin: 0; }
.lede { margin: 0 0 14px; }
.aside { color: #333; font-size: 12.5px; }
.eyebrow { font-size: 10.5px; letter-spacing: .07em; text-transform: uppercase;
           color: #444; margin: 10px 0 3px; font-weight: 700; }
section { margin: 0 0 24px; }
h2, h3, .eyebrow { page-break-after: avoid; break-after: avoid; }

/* The warning. Black ink on white paper, a rule you can feel, and no tint
   anywhere: this is the one thing on the page that must survive a fax. */
.banner { border: 2.5px solid #000; padding: 13px 15px; margin: 0 0 22px;
          background: #fff; color: #000; }
.banner h2 { border-bottom: 0; padding-bottom: 0; margin-bottom: 6px; }

table { width: 100%; border-collapse: collapse; font-size: 12.5px;
        margin: 0 0 8px; }
th { text-align: left; border-bottom: 1.5px solid #000; padding: 0 10px 6px 0;
     font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase; }
td { border-bottom: 1px solid #bbb; padding: 7px 10px 7px 0;
     vertical-align: top; }
tr { page-break-inside: avoid; break-inside: avoid; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
ul { margin: 0 0 8px; padding-left: 18px; }
li { margin-bottom: 4px; }
ul.plain, ul.timeline { list-style: none; padding: 0; }
ul.plain > li, ul.timeline > li { border-bottom: 1px solid #ddd;
                                  padding: 8px 0; margin: 0; }
ul.plain > li:last-child, ul.timeline > li:last-child { border-bottom: 0; }
.when { font-size: 11.5px; color: #333; }
.file-ref { font-size: 12px; color: #333; }
/* A coloured dot says nothing on paper. The sentence beside it does. */
.dot { display: none; }

.finding { border: 1px solid #000; border-left-width: 5px; padding: 13px 15px;
           margin: 0 0 12px; page-break-inside: avoid; break-inside: avoid; }
.finding .eyebrow:first-child { margin-top: 0; }
.clause-block { margin: 10px 0 0; padding-top: 9px; border-top: 1px dashed #888;
                page-break-inside: avoid; break-inside: avoid; }
blockquote { margin: 7px 0; padding: 8px 13px; border-left: 3px solid #000;
             background: #f2f2f2; font-size: 12.5px; }
.where { font-size: 11.5px; color: #333; margin: 3px 0 0;
         word-break: break-word; }
.caution { font-size: 11.5px; line-height: 1.5; margin: 8px 0 0;
           padding: 7px 9px; border: 1px solid #000; }
.note { border-left: 2px solid #000; padding-left: 11px; font-size: 12.5px; }
dl.pairs { display: grid; grid-template-columns: minmax(120px, 45%) 1fr;
           gap: 5px 16px; font-size: 12.5px; margin: 0; }
dl.pairs dt { color: #333; }
dl.pairs dd { margin: 0; }
.foot { margin-top: 28px; }
a { color: #000; }

/* Ctrl-P, and nothing else to do. A4 with printer margins, no navigation to
   strip out because the file has none, and the quoted clause loses its grey
   so a mono printer does not return it as a smudge. */
@page { size: A4; margin: 15mm 14mm; }
@media print {
  body { font-size: 10.5pt; }
  .doc { max-width: none; padding: 0; }
  blockquote { background: transparent; border-left-width: 2px; }
  a { text-decoration: none; }
}
`;

  /* Which published document the words were read out of, and where in it.
     Composition, not wording: every piece is the register's own. */
  function clauseWhere(one) {
    return [one.document, one.edition, one.page ? "page " + one.page : ""]
      .filter(Boolean).join(" · ");
  }

  /* The one sentence in this file that is about the rules rather than about
     furniture, said where the route sends no caution of its own: every
     clause in the register was lifted out of the regulator's PDF by machine,
     and no qualified person has signed it off. It is said against each
     clause and once more at the foot of the document, so a reader who only
     ever sees the printout still sees it.

     TODO — the remedy is a key in briefing.py, where UNVERIFIED_CAUTION
     already carries this warning for the queue. */
  function unverifiedCaution(checkedOn) {
    return "Quoted from the published document and checked against it" +
      (checkedOn ? " on " + checkedOn : "") + ". No qualified person has " +
      "confirmed that this is the right rule to be citing here.";
  }

  function anythingUnconfirmed(findings, files) {
    var any = false;
    (findings || []).forEach(function (finding, index) {
      clausesOf(finding, (files || [])[index]).forEach(function (one) {
        if (!one.verified) { any = true; }
      });
    });
    return any;
  }

  /* A decision a person recorded, wherever the record keeps it. `tone` is a
     machine hint the document never prints; it is how an entry somebody
     wrote is told from an entry the rules wrote, without this file having to
     match on English. */
  function decisionEntries(parts) {
    var settled = [];
    (parts || []).forEach(function (part) {
      (part.entries || []).forEach(function (entry) {
        if (entry && entry.tone === "decision") { settled.push(entry); }
      });
    });
    return settled;
  }

  /* The watchlist history, for a party nobody has run the checks over from
     this screen. The report's own table covers a run; this covers the rest
     of the record, so a document downloaded from the party record does not
     say "nothing has been run" over a party that has been screened for
     years. Found by the clause every one of its lines answers to — a number
     out of the guidelines, which is stable in a way a heading is not. */
  function screeningPart(parts) {
    var found = null;
    (parts || []).forEach(function (part) {
      var entries = part.entries || [];
      if (!entries.length) { return; }
      if (found) { return; }
      if (entries.every(function (entry) { return entry.clause === "5.9"; })) {
        found = part;
      }
    });
    return found;
  }

  /* Every heading this report puts on a section, in one place, so the screen
     and the file downloaded off it cannot name the same section two
     different ways. Each prefers the server's word; the fallback is
     furniture — the name of a section or a column — and never a sentence
     about a finding, a rule or a risk. */
  function reportWords() {
    return {
      checked: word("report_checked", "What was checked, and against what"),
      checked_none: word("report_checked_none",
                         "Nothing has been run for this party yet."),
      col_check: word("report_col_check", "Check"),
      col_result: word("report_col_result", "What it found"),
      outstanding: word("report_outstanding", "What is still outstanding"),
      owed_none: word("onboard_owed_none", "Nothing further is outstanding."),
      not_modelled: word("onboard_not_modelled", "Not checked here"),
      findings: word("report_findings", "What was found"),
      findings_none: word("report_findings_none", "—"),
      ownership: word("report_ownership", "Who is behind this party"),
      ownership_none: word("report_ownership_none",
                           "Nothing about ownership is on the record."),
      decision: word("report_decision", "What only a person may now do"),
      download: word("report_download", "Download the report")
    };
  }

  /* The name the file lands under. Only the characters an operating system
     refuses are taken out — a name in any script survives, which a
     conservative filter would not have. */
  function fileNameFor(doc, record) {
    var party = (record && record.party) || {};
    var name = String(party.name || (doc && doc.title) || "").trim();
    var clean = name.replace(/[\\\/:*?"<>|]/g, " ")
                    .replace(/\s+/g, " ").trim().slice(0, 80);
    var now = new Date();
    var day = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 10);
    return "Vinzor report - " + clean + " - " + day + ".html";
  }

  /* The document itself: one string, and every sentence in it the server's.

     `doc` is the party's permanent record out of dossier.py and is required.
     It carries the warning about who may read this, and a report without
     that warning on it is precisely the artefact dossier.py refuses to
     produce — so where the record could not be read there is no download at
     all, and the officer is told rather than handed a file that is missing
     the only line on it that governs who may see it. */
  function documentFor(doc, record, files, run) {
    if (!doc || !doc.confidential) { throw new Error(""); }

    var say = reportWords();
    var party = (record && record.party) || {};
    var checked = checkRows(record || {}, run);
    var owed = (record && record.outstanding) || [];
    var notModelled = (record && record.not_modelled) || [];
    var findings = (record && record.findings) || [];
    var ownership = (record && record.ownership) || {};
    var owners = ownerRows(ownership);
    var explains = ownershipSaid(ownership);
    var cycles = cycleLines(ownership);
    var parts = doc.parts || [];
    var settled = decisionEntries(parts);
    var screened = checked.rows.length ? null : screeningPart(parts);
    var seal = parts.length ? parts[parts.length - 1] : null;
    var title = doc.title || party.name || "";

    var body = h`
      <article class="doc">
        <section class="banner">
          <h2>${word("record_confidential", "")}</h2>
          <p>${doc.confidential}</p>
        </section>

        <header class="lede">
          <h1>${title}</h1>
          <p class="meta">${
            [doc.kind, doc.workspace, doc.printed].filter(Boolean).join(" · ")
          }</p>
        </header>

        <section>
          <h2>${say.checked}</h2>
          ${checked.rows.length ? h`
            <table>
              <thead><tr>
                <th>${say.col_check}</th>
                <th>${checked.middle}</th>
                <th>${say.col_result}</th>
              </tr></thead>
              <tbody>${checked.rows.map(function (row) {
                return h`<tr>
                  <td>${row.what}</td>
                  <td>${row.middle}</td>
                  <td>${row.said}${row.details.length ? h`<ul>${
                    row.details.map(function (line) { return h`<li>${line}</li>`; })
                  }</ul>` : ""}</td>
                </tr>`;
              })}</tbody>
            </table>` : ""}
          ${screened ? h`
            <p class="lede">${screened.lead}</p>
            <ul class="plain">${(screened.entries || []).map(function (entry) {
              return h`<li>
                <div class="when">${entry.when}</div>
                <div>${entry.what}</div>
                ${entry.clause ? h`<div class="aside">${
                  word("clause_prefix", "")
                } ${entry.clause}</div>` : ""}
              </li>`;
            })}</ul>
            ${screened.tail ? h`<p class="aside">${screened.tail}</p>` : ""}` : ""}
          ${(!checked.rows.length && !screened)
            ? h`<p>${say.checked_none}</p>` : ""}
        </section>

        <section>
          <h2>${say.outstanding}</h2>
          ${owed.length ? h`<ul class="plain">${owed.map(function (item) {
            var need = item.requirement || item;
            return h`<li>
              <div>${need.asks_for || ""}</div>
              ${need.because ? h`<div class="aside">${need.because}</div>` : ""}
              ${need.basis ? h`<div class="aside">${need.basis}</div>` : ""}
            </li>`;
          })}</ul>` : h`<p>${say.owed_none}</p>`}
          ${notModelled.length ? h`
            <p class="eyebrow">${say.not_modelled}</p>
            <ul>${notModelled.map(function (line) {
              return h`<li>${line}</li>`;
            })}</ul>` : ""}
        </section>

        <section>
          <h2>${say.findings}</h2>
          ${findings.length ? findings.map(function (finding, index) {
            var file = (files || [])[index];
            var steps = (file && file.to_close_this) || [];
            var detail = theDetail(file);
            /* The same three questions the file answers on screen, in the
               same order — what happened, why it matters, what to do — and
               then everything the screen folds away, unfolded. Paper has no
               fold, and the reader this is for is the one who asked to see
               underneath it. */
            return h`<article class="finding">
              <p class="eyebrow">${word("what_happened", "What happened")}</p>
              <h3>${
                (file && file.headline) || cleanSentence(finding.summary) || ""
              }</h3>

              ${clausesOf(finding, file).length ? h`<p class="eyebrow">${
                rulesHeading(finding, file)
              }</p>` : ""}
              ${clausesOf(finding, file).map(function (one) {
                return h`<div class="clause-block">
                  <p><strong>${word("clause_prefix", "")} ${one.clause}</strong>${
                    one.plain ? " — " + one.plain : ""
                  }</p>
                  ${one.quote ? h`<blockquote>${one.quote}</blockquote>` : ""}
                  ${clauseWhere(one) ? h`<p class="where">${
                    clauseWhere(one)
                  }</p>` : ""}
                  ${one.amended ? h`<p class="where">${one.amended}</p>` : ""}
                  ${one.url ? h`<p class="where"><a href="${one.url}">${
                    one.url
                  }</a></p>` : ""}
                  ${one.verified ? "" : h`<p class="caution">${
                    one.caution || unverifiedCaution(one.checked_on)
                  }</p>`}
                </div>`;
              })}

              ${steps.length ? h`
                <p class="eyebrow">${word("to_close_heading", "")}</p>
                <ul>${steps.map(function (line) {
                  return h`<li>${line}</li>`;
                })}</ul>` : ""}
              ${detail ? h`
                <p class="eyebrow">${word("the_detail", "The detail")}</p>
                ${detail}` : ""}
            </article>`;
          }) : h`<p>${say.findings_none}</p>`}
        </section>

        <section>
          <h2>${say.ownership}</h2>
          ${explains ? h`<p>${explains}</p>` : ""}
          ${owners.length ? h`<ul class="plain">${owners.map(function (owner) {
            return h`<li>
              <div>${owner.who}${owner.share ? " — " + owner.share : ""}</div>
              ${owner.note ? h`<div class="aside">${owner.note}</div>` : ""}
            </li>`;
          })}</ul>` : ""}
          ${cycles.length ? h`<ul>${cycles.map(function (line) {
            return h`<li>${line}</li>`;
          })}</ul>` : ""}
          ${(!explains && !owners.length && !cycles.length)
            ? h`<p>${say.ownership_none}</p>` : ""}
          ${ownership && ownership.caveat ? h`<p class="note">${
            ownership.caveat
          }</p>` : ""}
        </section>

        ${settled.length ? h`
          <section>
            <h2>${word("decided_heading", "")}</h2>
            <ul class="plain">${settled.map(function (entry) {
              return h`<li>
                <div class="when">${entry.when}</div>
                <div>${entry.what}</div>
                ${entry.who ? h`<div class="aside">${entry.who}</div>` : ""}
                ${entry.why ? h`<blockquote>${entry.why}</blockquote>` : ""}
              </li>`;
            })}</ul>
          </section>` : ""}

        ${(seal && (seal.facts || []).length) ? h`
          <section>
            <h2>${seal.heading}</h2>
            <p class="lede">${seal.lead}</p>
            <dl class="pairs">${seal.facts.map(function (fact) {
              return h`<dt>${fact.label}</dt><dd>${fact.value}${
                fact.note ? " · " + fact.note : ""
              }</dd>`;
            })}</dl>
            ${seal.tail ? h`<p class="where">${seal.tail}</p>` : ""}
          </section>` : ""}

        ${anythingUnconfirmed(findings, files)
          ? h`<p class="caution foot">${unverifiedCaution("")}</p>` : ""}
      </article>`;

    return {
      name: fileNameFor(doc, record),
      html: "<!doctype html>\n<html lang=\"en\">\n<head>\n" +
            "<meta charset=\"utf-8\">\n" +
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "<title>" + esc(title) + "</title>\n<style>" + DOC_CSS +
            "</style>\n</head>\n<body>\n" + flatten(body) + "\n</body>\n</html>\n"
    };
  }

  /* The browser's own save, which is the only one there is: this page may
     reach no origin but its own, and a compliance document has no business
     travelling to a third party in order to become a file. */
  function saveFile(name, html) {
    var blob = new Blob([html], { type: "text/html;charset=utf-8" });
    var address = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = address;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    /* Freed on a later turn of the loop. Revoking it in the same tick
       cancels the download in more than one browser. */
    setTimeout(function () { URL.revokeObjectURL(address); }, 20000);
  }

  /* The action, wherever it sits. `gather` returns the document or a promise
     of it, and is allowed to fail: a report whose permanent record could not
     be read is not saved quietly without the warning that governs who may
     read it. */
  /* Ask about the party in front of you.

     The eight checks are deterministic and stay that way: they decide what is
     true, and this decides nothing. What it adds is the reading -- which of
     eight findings matters most, what they mean together, and what the
     officer should do next -- which is a judgement, and judgement is the one
     thing a model is allowed to do here.

     Only the identifier travels. Everything the assistant is told about this
     party is read by the server out of the record, because a page that could
     post the *contents* of a report could tell our own assistant that a
     sanctioned party had been cleared. */
  function reportAsk(where, party) {
    if (!where || !party || !party.id) { return; }
    var tries = [
      word("report_ask_try_one", "What matters most here, and what should I do next?"),
      word("report_ask_try_two", "What is stopping this file from being settled?")
    ];
    mount(where, h`<section class="card pad stack-tight report-ask">
      <h2 class="section-head">${word("ask_open", "Ask about this")}</h2>
      <p class="small faint prose">${
        word("report_ask_lead", "")
      }</p>
      <div class="ask-tries">${tries.map(function (one) {
        return h`<button type="button" data-try="${one}">${one}</button>`;
      })}</div>
      <form class="ask-form">
        <input type="text" name="asked" autocomplete="off"
               placeholder="${word("ask_placeholder", "")}"
               aria-label="${word("ask_open", "Ask about this")}">
        <button type="submit" class="btn btn-primary">${word("ask_go", "Ask")}</button>
      </form>
      <div class="report-ask-said" hidden></div>
    </section>`);

    var form = where.querySelector("form");
    var box = where.querySelector("input[name=asked]");
    var said = where.querySelector(".report-ask-said");
    var busy = false;

    function put(html) { said.hidden = false; mount(said, html); }

    function send(asked) {
      if (!asked || busy) { return; }
      busy = true;
      put(h`<p class="turn-said-text">${asked}</p>
            <p class="small faint">${word("ask_thinking", "")}</p>`);
      post("/api/chat", { asked: asked, looking_at: { id: party.id } })
        .then(function (reply) {
          busy = false;
          var text = reply.said || reply.withheld || "";
          put(h`<p class="turn-said-text">${asked}</p>
            <div class="turn-said"><p class="prose">${text}</p>
            ${(reply.looked_at || []).length ? h`<div class="chips-wrap">
              <p class="tiny eyebrow">${word("ask_looked_at", "It read:")}</p>
              <ul class="chips">${(reply.looked_at || []).map(function (one) {
                return h`<li>${one}</li>`;
              })}</ul></div>` : ""}</div>`);
        })
        .catch(function () {
          busy = false;
          put(h`<p class="problem">${word("ask_failed", "")}</p>`);
        });
    }

    where.querySelectorAll("[data-try]").forEach(function (button) {
      button.addEventListener("click", function () {
        box.value = button.getAttribute("data-try");
        send(box.value);
      });
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var asked = (box.value || "").trim();
      box.value = "";
      send(asked);
    });
  }

  /* `party` is an entity id. Given one, the download is a PDF built on the
     server from the same record this screen was drawn from; the HTML that
     `gather` builds stays as the fallback for a screen that has no party to
     name.

     PDF because of where the file goes. A compliance record is attached to
     an email to a board, an auditor or the regulator, and an HTML file
     arrives looking like a saved web page, opens differently on every
     machine, and gives the recipient no way to tell whether the copy they
     were sent is the copy that was written. */
  function downloadAction(where, gather, party) {
    if (!where) { return; }
    mount(where, h`
      <button type="button" class="btn btn-primary" data-download>${
        word("report_download", "Download the report")
      }</button>
      ${party ? h`<span class="tiny faint">${
        word("report_download_kind", "")
      }</span>` : ""}
      <span class="problem" hidden></span>`);

    var button = where.querySelector("[data-download]");
    var problem = where.querySelector(".problem");
    var label = button.textContent;

    button.addEventListener("click", function () {
      if (party) {
        /* Straight at the route. The browser saves what the server sends,
           so the bytes on disk are the bytes that were rendered and nothing
           in this page had a chance to change them. */
        window.location.href =
          "/api/report.pdf?party=" + encodeURIComponent(party);
        return;
      }
      button.disabled = true;
      problem.hidden = true;
      button.textContent = word("agents_watching", label);
      Promise.resolve().then(gather).then(function (file) {
        saveFile(file.name, file.html);
      }).catch(function (error) {
        problem.hidden = false;
        problem.textContent = said(error) || word("load_failed", "");
      }).then(function () {
        button.disabled = false;
        button.textContent = label;
      });
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
    var items = group.items || [];
    /* Whether these rows differ from one another at all.

       A group is work that shares an explanation, so in most of them every
       row is the same finding about a different party -- four payments, one
       reason. Printing that reason on all four, under a heading that has
       just said it, is four copies of a sentence and nothing that tells one
       row from another. Where the rows are alike the second line says where
       each one came from instead; where they are not -- the files grouped
       only by how long they have waited -- it says what each is about,
       which is the whole reason that group is hard to read.

       Both sentences are the server's. The choice between them is furniture. */
    var varied = items.some(function (item) {
      return (item.headline || "") !== ((items[0] || {}).headline || "");
    });
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
          ${(group.rules || []).length ? h`
            <div class="group-why">
              <p class="eyebrow">${rulesHeading(null, group)}</p>
              ${clauseTags(null, group)}
            </div>` : ""}
          <ul class="items">
            ${(group.items || []).map(function (item) {
              /* The party first, then the one line that says what is wrong
                 with them, then how urgent it is. It used to be one
                 sentence -- "Yuki Ghosh — USD 1,222,462 received 31 May
                 2026, reference TX-737609" -- which is a row you have to
                 read rather than scan, and which never says what the file
                 is actually about. The amount and the reference are still
                 on the file, under the fold, where somebody looking a
                 payment up in the bank portal will want them. */
              var why = varied
                ? (item.headline || shown(item.about))
                : (shown(item.about) || item.headline);
              /* The badge only where this row is more or less pressing than
                 the group it sits in. Four identical badges under a heading
                 that carries the same one is a wall of colour that says
                 nothing; on the aged files, where every row was opened by a
                 different rule, it is the only thing that ranks them. */
              var urgency = (item.urgency && item.urgency !== group.urgency)
                ? item.urgency : "";
              return h`<li data-file="${item.case_id}">
                <div class="item-line">
                  <span class="item-what">
                    <span class="item-who">${item.who || item.line || ""}</span>
                    <span class="item-why">${why || ""}</span>
                  </span>
                  ${urgency ? h`<span class="badge" data-tone="${
                    group.tone || "later"
                  }">${urgency}</span>` : ""}
                  <button type="button" class="btn-link small" data-open>${
                    word("open_file", "")
                  }</button>
                </div>
                <div class="item-open" hidden></div>
              </li>`;
            })}
          </ul>
          ${group.more ? h`<p class="tiny faint">${group.more}</p>` : ""}
          ${((group.because || []).length || (group.to_close_this || []).length) ? h`
            <details class="fold">
              <summary>${word("the_detail", "The detail")}</summary>
              <div class="fold-body">
                ${(group.because || []).length ? h`<div class="prose small soft">${
                  group.because.map(function (line) { return h`<p>${line}</p>`; })
                }</div>` : ""}
                ${(group.to_close_this || []).length ? h`
                  <p class="eyebrow">${word("to_close_heading", "")}</p>
                  <ul class="bullets small prose">${group.to_close_this.map(function (line) {
                    return h`<li>${line}</li>`;
                  })}</ul>` : ""}
              </div>
            </details>` : ""}
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
      mount(panel, fileBlock({
        headline: item.headline || item.line || "",
        rules_heading: rulesHeading(null, item),
        clauses: clauseTags(null, item),
        steps: item.to_close_this || [],
        decides: true,
        detail: theDetail(item)
      }));

      decisionBlock(panel.querySelector(".file-decision"), {
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
          <div class="take">
            <a class="btn" href="#/record/${encodeURIComponent(entityId)}">${
              word("open_record", "")
            }</a>
          </div>
        </div>

        ${party.ownership ? h`
          <div class="card pad tree-card">
            <h2 class="section-head">${
              word("report_ownership", "Who is behind this party")
            }</h2>
            ${ownershipTree(party.ownership,
                            { name: party.name, kind: party.kind }, "")}
          </div>` : ""}

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

  /* ---------- the party record ---------- */

  /* dossier.py's document, on a screen. A screen is the wrong artefact for
     the question this answers — *show me everything you have on this
     investor* — which is why the download beside it exists, and why the two
     are built from the same payload. Every sentence here is the server's,
     including the warning at the top and the sentence under the seal; this
     lays them out and does nothing else.

     Reads only, and reachable by everybody including a viewer: this document
     creates nothing and decides nothing, and a compliance function where
     only two people can produce the file an inspector asked for is a
     compliance function with a bottleneck. */
  function recordScreen(entityId) {
    var where = frame("parties");
    busy(where);

    var record = null;
    var files = [];

    get("/api/records/" + encodeURIComponent(entityId)).then(function (doc) {
      absorb(doc);
      if (doc.refusal) {
        mount(where, h`<p class="note bad prose">${doc.refusal}</p>`);
        return;
      }

      mount(where, h`
        <div class="report">
          <div class="card pad confidential">
            <p class="eyebrow">${word("record_confidential", "")}</p>
            <p class="prose">${doc.confidential}</p>
          </div>

          <div class="head">
            <p class="eyebrow">${doc.kind || ""}</p>
            <h1>${doc.title || ""}</h1>
            <p class="small faint">${
              [doc.workspace, doc.printed].filter(Boolean).join(" · ")
            }</p>
            <div class="take">
              <div id="take-record" class="take-part"></div>
              ${doc.print_label ? h`<button type="button" class="btn btn-quiet"
                        id="print-record">${doc.print_label}</button>` : ""}
            </div>
          </div>

          ${doc.opening ? h`<p class="prose soft">${doc.opening}</p>` : ""}
          ${doc.opening_withheld ? h`<p class="note prose">${
            doc.opening_withheld
          }</p>` : ""}

          <div class="prose small soft stack-tight">${
            (doc.summary || []).map(function (line) { return h`<p>${line}</p>`; })
          }</div>

          ${(doc.parts || []).map(recordPart)}

          <p><a class="btn" href="#/party/${encodeURIComponent(entityId)}">${
            doc.back || ""
          }</a></p>
        </div>`);

      /* Built from this record and from what the checks left on the party,
         which is the same pair the report screen builds it from. Both are
         fetched here only when the officer asks for the file. */
      downloadAction(document.getElementById("take-record"), function () {
        if (record) { return documentFor(doc, record, files, null); }
        return get("/api/onboarding/" + encodeURIComponent(entityId))
          .then(function (payload) {
            record = payload;
            return Promise.all((payload.findings || []).map(function (finding) {
              if (!finding.case_id) { return Promise.resolve(null); }
              return get("/api/cases/" + encodeURIComponent(finding.case_id))
                .catch(function () { return null; });
            }));
          })
          .then(function (fetched) {
            files = fetched || [];
            return documentFor(doc, record, files, null);
          });
      }, entityId);

      var printer = document.getElementById("print-record");
      if (printer) {
        printer.addEventListener("click", function () { window.print(); });
      }
    }).catch(function (error) { failed(where, error); });
  }

  function recordPart(part) {
    return h`
      <section class="card pad">
        <h2 class="section-head">${part.heading}</h2>
        ${part.lead ? h`<p class="prose soft small">${part.lead}</p>` : ""}
        ${(part.facts || []).length ? h`<dl class="pairs">${
          part.facts.map(function (fact) {
            return h`<dt>${fact.tone ? h`<span class="dot" data-tone="${
                       fact.tone
                     }"></span> ` : ""}${fact.label}</dt>
                     <dd>${fact.value}${fact.note ? h`
                       <span class="faint"> ${fact.note}</span>` : ""}</dd>`;
          })
        }</dl>` : ""}
        ${(part.entries || []).length ? h`<ul class="timeline">${
          part.entries.map(function (entry) {
            return h`<li>
              ${entry.when ? h`<div class="when">${entry.when}</div>` : ""}
              <div>${entry.tone ? h`<span class="dot" data-tone="${
                entry.tone === "decision" ? "good" : entry.tone
              }"></span> ` : ""}${entry.what}</div>
              ${entry.who ? h`<div class="small faint">${entry.who}</div>` : ""}
              ${entry.why ? h`<blockquote class="quote">${entry.why}</blockquote>` : ""}
              ${entry.clause ? h`<div><span class="clause">${
                word("clause_prefix", "")
              } ${entry.clause}</span></div>` : ""}
            </li>`;
          })
        }</ul>` : ""}
        ${part.tail ? h`<p class="tiny faint prose">${part.tail}</p>` : ""}
      </section>`;
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
    if (at.name === "record" && at.a) { recordScreen(at.a); return; }
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
