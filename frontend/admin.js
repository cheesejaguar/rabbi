(function () {
  "use strict";

  const VIEW_META = {
    overview: {
      title: "Overview",
      description: "Usage, revenue, quality, and estimated model costs.",
    },
    users: {
      title: "Users",
      description: "Search accounts, review conversations, and make audited access changes.",
    },
    flagged: {
      title: "Crisis queue",
      description: "Messages marked for crisis, vulnerability, or human referral review.",
    },
    feedback: {
      title: "Feedback",
      description: "Review user ratings in the context of the response that received them.",
    },
    errors: {
      title: "Errors",
      description: "Inspect recent application failures and their seven day pattern.",
    },
    purchases: {
      title: "Purchases",
      description: "Review payment state and fulfilled credit packages across accounts.",
    },
    sponsorships: {
      title: "Sponsorships",
      description: "Review D'var Torah sponsorship payments and dedication details.",
    },
    analytics: {
      title: "Analytics",
      description: "Understand sessions, devices, referrers, and text to speech activity.",
    },
    audit: {
      title: "Audit log",
      description: "Trace privileged review and account actions recorded by the server.",
    },
  };

  const state = {
    currentTab: "overview",
    renderGeneration: 0,
    activeController: null,
    userSearch: "",
    userOffset: 0,
    feedbackType: "",
    errorType: "",
    purchaseStatus: "",
    sponsorshipStatus: "",
    analyticsDays: "7",
    mutation: null,
    conversationGeneration: 0,
    conversationController: null,
  };

  const content = document.getElementById("content");
  const banner = document.getElementById("errorBanner");
  const liveStatus = document.getElementById("adminStatus");
  const tabs = document.getElementById("tabs");
  const mobileViewSelect = document.getElementById("mobileViewSelect");
  const viewTitle = document.getElementById("viewTitle");
  const viewDescription = document.getElementById("viewDescription");
  const convoDialog = document.getElementById("convoDialog");
  const convoDialogTitle = document.getElementById("convoDialogTitle");
  const convoContent = document.getElementById("convoContent");
  const actionDialog = document.getElementById("actionDialog");
  const actionForm = document.getElementById("actionForm");
  const actionDialogTitle = document.getElementById("actionDialogTitle");
  const actionDialogDescription = document.getElementById("actionDialogDescription");
  const actionFields = document.getElementById("actionFields");
  const actionState = document.getElementById("actionState");
  const actionCancel = document.getElementById("actionCancel");
  const actionSubmit = document.getElementById("actionSubmit");
  const focusReturn = new WeakMap();

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function fmtDate(value) {
    if (!value) return "Not available";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  function fmtCents(value) {
    const cents = Number(value || 0);
    return `$${(Number.isFinite(cents) ? cents / 100 : 0).toFixed(2)}`;
  }

  function fmtNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number.toLocaleString() : "0";
  }

  function selected(value, expected) {
    return String(value) === String(expected) ? " selected" : "";
  }

  function announce(message) {
    liveStatus.textContent = "";
    window.requestAnimationFrame(() => {
      liveStatus.textContent = message;
    });
  }

  function showError(message) {
    banner.textContent = message;
    banner.hidden = false;
    announce(message);
  }

  function clearError() {
    banner.textContent = "";
    banner.hidden = true;
  }

  async function requestJSON(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: "include",
    });

    if (response.status === 401) {
      window.location.assign("/auth/login");
      const error = new Error("Your session has ended. Redirecting to sign in.");
      error.code = "unauthenticated";
      throw error;
    }

    let data = {};
    if (response.status !== 204) {
      data = await response.json().catch(() => ({}));
    }

    if (response.status === 403) {
      const message = data.detail || "You do not have administrator access.";
      showError(message);
      const error = new Error(message);
      error.code = "forbidden";
      throw error;
    }

    if (!response.ok) {
      const error = new Error(data.detail || `Request failed with status ${response.status}.`);
      error.code = `http_${response.status}`;
      throw error;
    }

    return data;
  }

  function api(path, signal) {
    return requestJSON(path, { signal });
  }

  function apiPost(path, body, signal) {
    return requestJSON(path, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function emptyState(message) {
    return `<div class="empty-state"><span>${esc(message)}</span></div>`;
  }

  function loadingState(label) {
    return `<div class="loading-state" role="status"><span class="loading-mark" aria-hidden="true"></span><span>${esc(label)}</span></div>`;
  }

  function desktopTable(caption, headings, rows, compact = false) {
    return `<div class="table-region desktop-results" role="region" aria-label="${esc(caption)}" tabindex="0">
      <table class="data-table${compact ? " compact" : ""}">
        <caption>${esc(caption)}</caption>
        <thead><tr>${headings.map((heading) => `<th scope="col">${esc(heading)}</th>`).join("")}</tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>`;
  }

  function mobileResults(items, label) {
    return `<div class="mobile-results" aria-label="${esc(label)}">${items.join("")}</div>`;
  }

  function mobileResult(title, badge, fields, actions = "") {
    return `<article class="mobile-result">
      <div class="mobile-result-header">
        <strong dir="auto">${esc(title)}</strong>
        ${badge || ""}
      </div>
      <dl>${fields.map(([term, value, raw]) => `<dt>${esc(term)}</dt><dd${raw ? "" : " dir=\"auto\""}>${raw ? value : esc(value)}</dd>`).join("")}</dl>
      ${actions ? `<div class="cell-actions">${actions}</div>` : ""}
    </article>`;
  }

  function statusPill(status) {
    const safeStatus = String(status || "unknown");
    let tone = "neutral";
    if (safeStatus === "completed") tone = "success";
    if (safeStatus === "failed") tone = "error";
    return `<span class="pill ${tone}">${esc(safeStatus)}</span>`;
  }

  function pagerMarkup(offset, pageSize, total) {
    if (total <= pageSize) return "";
    const start = total === 0 ? 0 : offset + 1;
    const end = Math.min(offset + pageSize, total);
    return `<nav class="pager" aria-label="User results pages">
      <button class="action" type="button" data-page-offset="${Math.max(0, offset - pageSize)}"${offset === 0 ? " disabled" : ""}>Previous</button>
      <span class="pager-status numeric">${start} to ${end} of ${total}</span>
      <button class="action" type="button" data-page-offset="${offset + pageSize}"${offset + pageSize >= total ? " disabled" : ""}>Next</button>
    </nav>`;
  }

  async function loadOverview(signal) {
    const [{ overview = {} }, { costs = [] }] = await Promise.all([
      api("/api/admin/overview", signal),
      api("/api/admin/costs?days=30", signal),
    ]);
    const totalCost = costs.reduce((sum, row) => sum + Number(row.estimated_cost_usd || 0), 0);
    const metrics = [
      ["Total users", fmtNumber(overview.total_users)],
      ["New users, 7 days", fmtNumber(overview.new_users_7d)],
      ["Active users, 7 days", fmtNumber(overview.active_users_7d)],
      ["Conversations", fmtNumber(overview.total_conversations)],
      ["Messages", fmtNumber(overview.total_messages)],
      ["Messages, 24 hours", fmtNumber(overview.messages_24h)],
      ["Credits outstanding", fmtNumber(overview.credits_outstanding)],
      ["Total revenue", fmtCents(overview.revenue_cents_total), "metric-accent"],
      ["Revenue, 30 days", fmtCents(overview.revenue_cents_30d), "metric-accent"],
      ["Sponsorship revenue", fmtCents(overview.sponsorship_revenue_cents_total), "metric-accent"],
      ["Model spend, 30 days", `$${totalCost.toFixed(2)}`],
      ["Errors, 24 hours", fmtNumber(overview.errors_24h), Number(overview.errors_24h) > 0 ? "metric-error" : ""],
      ["Errors, 7 days", fmtNumber(overview.errors_7d), Number(overview.errors_7d) > 0 ? "metric-error" : ""],
      ["Helpful ratings, 7 days", fmtNumber(overview.thumbs_up_7d)],
      ["Needs review, 7 days", fmtNumber(overview.thumbs_down_7d), Number(overview.thumbs_down_7d) > 0 ? "metric-error" : ""],
    ];

    const metricMarkup = `<div class="metric-grid">${metrics.map(([label, value, tone]) => `
      <article class="metric-card metric-wide ${tone || ""}">
        <p class="metric-label">${esc(label)}</p>
        <p class="metric-value numeric">${esc(value)}</p>
      </article>`).join("")}</div>`;

    if (!costs.length) {
      return metricMarkup + `<section class="section-block"><div class="section-heading"><div><h2>Estimated model cost by day</h2><p>Thirty day window</p></div></div>${emptyState("No cost data yet.")}</section>`;
    }

    const rows = costs.map((row) => `<tr>
      <td class="numeric">${esc(String(row.day || "").slice(0, 10))}</td>
      <td class="numeric">${esc(fmtNumber(row.messages))}</td>
      <td class="numeric">${esc(fmtNumber(row.input_tokens))}</td>
      <td class="numeric">${esc(fmtNumber(row.output_tokens))}</td>
      <td class="numeric">$${Number(row.estimated_cost_usd || 0).toFixed(4)}</td>
    </tr>`);
    const mobile = costs.map((row) => mobileResult(
      String(row.day || "").slice(0, 10) || "Date unavailable",
      "",
      [
        ["Messages", fmtNumber(row.messages)],
        ["Input tokens", fmtNumber(row.input_tokens)],
        ["Output tokens", fmtNumber(row.output_tokens)],
        ["Estimated cost", `$${Number(row.estimated_cost_usd || 0).toFixed(4)}`],
      ]
    ));

    return metricMarkup + `<section class="section-block">
      <div class="section-heading"><div><h2>Estimated model cost by day</h2><p>Thirty day window</p></div></div>
      ${desktopTable("Estimated model cost by day", ["Day", "Messages", "Input tokens", "Output tokens", "Estimated cost"], rows, true)}
      ${mobileResults(mobile, "Estimated model cost by day")}
    </section>`;
  }

  function userActions(user) {
    const id = esc(user.id);
    const email = esc(user.email);
    const isAdmin = Boolean(user.is_admin);
    return `<button class="action" type="button" data-act="credits" data-id="${id}" data-email="${email}">Credits</button>
      <button class="action" type="button" data-act="convos" data-id="${id}" data-email="${email}">Conversations</button>
      <button class="action" type="button" data-act="role" data-id="${id}" data-admin="${isAdmin ? "1" : "0"}" data-email="${email}">${isAdmin ? "Revoke admin" : "Make admin"}</button>`;
  }

  async function loadUsers(signal) {
    const params = new URLSearchParams({ limit: "50", offset: String(state.userOffset) });
    if (state.userSearch) params.set("search", state.userSearch);
    const { users = [], total = 0 } = await api(`/api/admin/users?${params.toString()}`, signal);
    const toolbar = `<form id="userSearchForm" class="toolbar" role="search">
      <div class="field grow">
        <label for="userSearchInput">Search by email or name</label>
        <input id="userSearchInput" name="search" type="search" maxlength="200" autocomplete="off" value="${esc(state.userSearch)}" placeholder="name@example.com">
      </div>
      <button class="button primary" type="submit"><span class="ph-icon ph-magnify" aria-hidden="true"></span>Search</button>
      <span class="toolbar-count numeric">${esc(fmtNumber(total))} user${Number(total) === 1 ? "" : "s"}</span>
    </form>`;

    if (!users.length) return toolbar + emptyState("No users match this search.");

    const rows = users.map((user) => {
      const name = [user.first_name, user.last_name].filter(Boolean).join(" ") || "Not provided";
      return `<tr>
        <td dir="auto">${esc(user.email)}</td>
        <td dir="auto">${esc(name)}</td>
        <td class="numeric">${esc(fmtNumber(user.credits))}</td>
        <td class="numeric">${esc(fmtNumber(user.conversation_count))}</td>
        <td class="numeric">${esc(fmtNumber(user.message_count))}</td>
        <td class="numeric">${esc(fmtCents(user.total_spent_cents))}</td>
        <td class="cell-muted numeric">${esc(fmtDate(user.created_at))}</td>
        <td>${user.is_admin ? '<span class="pill accent">admin</span>' : '<span class="pill neutral">user</span>'}</td>
        <td><div class="cell-actions">${userActions(user)}</div></td>
      </tr>`;
    });

    const mobile = users.map((user) => {
      const name = [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email || "User";
      return mobileResult(
        name,
        user.is_admin ? '<span class="pill accent">admin</span>' : '<span class="pill neutral">user</span>',
        [
          ["Email", user.email || "Not provided"],
          ["Credits", fmtNumber(user.credits)],
          ["Conversations", fmtNumber(user.conversation_count)],
          ["Messages", fmtNumber(user.message_count)],
          ["Spent", fmtCents(user.total_spent_cents)],
          ["Joined", fmtDate(user.created_at)],
        ],
        userActions(user)
      );
    });

    return toolbar + desktopTable(
      "User accounts",
      ["Email", "Name", "Credits", "Conversations", "Messages", "Spent", "Joined", "Role", "Actions"],
      rows
    ) + mobileResults(mobile, "User accounts") + pagerMarkup(state.userOffset, 50, Number(total));
  }

  function parseCrisisIndicators(value) {
    if (Array.isArray(value)) return value;
    if (!value) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function flaggedPills(item) {
    const pills = [];
    if (item.requires_human_referral) pills.push('<span class="pill error">human referral</span>');
    if (item.vulnerability_detected) pills.push('<span class="pill warning">vulnerability</span>');
    parseCrisisIndicators(item.crisis_indicators).forEach((indicator) => {
      pills.push(`<span class="pill error">${esc(indicator)}</span>`);
    });
    return pills.join("") || '<span class="pill neutral">review signal</span>';
  }

  async function loadFlagged(signal) {
    const { flagged = [] } = await api("/api/admin/flagged?limit=100", signal);
    if (!flagged.length) return emptyState("No messages currently need crisis or referral review.");
    const rows = flagged.map((item) => `<tr>
      <td class="cell-muted numeric">${esc(fmtDate(item.created_at))}</td>
      <td dir="auto">${esc(item.user_email || "Not available")}</td>
      <td>${flaggedPills(item)}</td>
      <td class="cell-muted" dir="auto">${esc(item.pastoral_mode || "Not set")} / ${esc(item.emotional_state || "Not set")}</td>
      <td class="cell-muted" dir="auto">${esc(item.message_excerpt || "No excerpt available")}</td>
      <td><button class="action" type="button" data-convo="${esc(item.conversation_id)}">Review</button></td>
    </tr>`);
    const mobile = flagged.map((item) => mobileResult(
      item.user_email || "User not available",
      flaggedPills(item),
      [
        ["When", fmtDate(item.created_at)],
        ["Mode", `${item.pastoral_mode || "Not set"} / ${item.emotional_state || "Not set"}`],
        ["Excerpt", item.message_excerpt || "No excerpt available"],
      ],
      `<button class="action" type="button" data-convo="${esc(item.conversation_id)}">Review conversation</button>`
    ));
    return desktopTable("Messages awaiting human review", ["When", "User", "Signals", "Mode and state", "Excerpt", "Action"], rows) + mobileResults(mobile, "Messages awaiting human review");
  }

  async function loadFeedback(signal) {
    const params = new URLSearchParams({ limit: "100" });
    if (state.feedbackType) params.set("feedback_type", state.feedbackType);
    const { feedback = [] } = await api(`/api/admin/feedback?${params.toString()}`, signal);
    const toolbar = `<div class="toolbar">
      <div class="field">
        <label for="feedbackTypeFilter">Rating</label>
        <select id="feedbackTypeFilter" data-filter="feedbackType">
          <option value=""${selected(state.feedbackType, "")}>All ratings</option>
          <option value="thumbs_down"${selected(state.feedbackType, "thumbs_down")}>Needs review</option>
          <option value="thumbs_up"${selected(state.feedbackType, "thumbs_up")}>Helpful</option>
        </select>
      </div>
      <span class="toolbar-count numeric">${feedback.length} result${feedback.length === 1 ? "" : "s"}</span>
    </div>`;
    if (!feedback.length) return toolbar + emptyState("No feedback matches this filter.");
    const rows = feedback.map((item) => {
      const rating = item.feedback_type === "thumbs_down"
        ? '<span class="pill error">needs review</span>'
        : '<span class="pill success">helpful</span>';
      return `<tr>
        <td class="cell-muted numeric">${esc(fmtDate(item.created_at))}</td>
        <td>${rating}</td>
        <td dir="auto">${esc(item.user_email || "Not available")}</td>
        <td class="cell-muted" dir="auto">${esc(item.message_excerpt || "No excerpt available")}</td>
        <td><button class="action" type="button" data-convo="${esc(item.conversation_id)}">Review</button></td>
      </tr>`;
    });
    const mobile = feedback.map((item) => {
      const needsReview = item.feedback_type === "thumbs_down";
      return mobileResult(
        item.user_email || "User not available",
        `<span class="pill ${needsReview ? "error" : "success"}">${needsReview ? "needs review" : "helpful"}</span>`,
        [["When", fmtDate(item.created_at)], ["Excerpt", item.message_excerpt || "No excerpt available"]],
        `<button class="action" type="button" data-convo="${esc(item.conversation_id)}">Review conversation</button>`
      );
    });
    return toolbar + desktopTable("Message feedback", ["When", "Rating", "User", "Message excerpt", "Action"], rows) + mobileResults(mobile, "Message feedback");
  }

  async function loadErrors(signal) {
    const params = new URLSearchParams({ limit: "50" });
    if (state.errorType) params.set("error_type", state.errorType);
    const { errors = [], stats = [] } = await api(`/api/admin/errors?${params.toString()}`, signal);
    const toolbar = `<form id="errorFilterForm" class="toolbar">
      <div class="field grow">
        <label for="errorTypeInput">Error type</label>
        <input id="errorTypeInput" name="error_type" type="search" maxlength="100" autocomplete="off" value="${esc(state.errorType)}" placeholder="Leave blank for all errors">
      </div>
      <button class="button primary" type="submit">Apply filter</button>
      <span class="toolbar-count numeric">${errors.length} recent record${errors.length === 1 ? "" : "s"}</span>
    </form>`;
    let statsMarkup = emptyState("No error counts in the seven day window.");
    if (stats.length) {
      const rows = stats.map((item) => `<tr><td class="numeric">${esc(String(item.day || "").slice(0, 10))}</td><td dir="auto">${esc(item.error_type)}</td><td class="numeric">${esc(fmtNumber(item.count))}</td></tr>`);
      const mobile = stats.map((item) => mobileResult(
        item.error_type || "Unclassified error",
        '<span class="pill error">error</span>',
        [["Day", String(item.day || "").slice(0, 10)], ["Count", fmtNumber(item.count)]]
      ));
      statsMarkup = desktopTable("Error counts by day", ["Day", "Type", "Count"], rows, true) + mobileResults(mobile, "Error counts by day");
    }
    const records = errors.length ? `<div class="error-stack">${errors.map((item) => `<article class="error-record">
      <div class="error-record-header">
        <span class="pill error">${esc(item.error_type || "error")}</span>
        <span class="muted numeric">${esc(fmtDate(item.created_at))}${item.user_id ? `, user ${esc(item.user_id)}` : ""}</span>
      </div>
      <p dir="auto">${esc(item.error_message || "No message recorded")}</p>
      ${item.stack_trace ? `<details><summary>View stack trace</summary><pre dir="auto">${esc(item.stack_trace)}</pre></details>` : ""}
    </article>`).join("")}</div>` : emptyState("No recent errors match this filter.");
    return toolbar + `<section class="section-block"><div class="section-heading"><div><h2>Error counts by day</h2><p>Seven day window</p></div></div>${statsMarkup}</section>
      <section class="section-block"><div class="section-heading"><div><h2>Recent errors</h2><p>Newest first</p></div></div>${records}</section>`;
  }

  function statusFilter(id, stateKey, value, label) {
    return `<div class="field">
      <label for="${id}">${esc(label)}</label>
      <select id="${id}" data-filter="${stateKey}">
        <option value=""${selected(value, "")}>All statuses</option>
        <option value="pending"${selected(value, "pending")}>Pending</option>
        <option value="completed"${selected(value, "completed")}>Completed</option>
        <option value="failed"${selected(value, "failed")}>Failed</option>
        <option value="refunded"${selected(value, "refunded")}>Refunded</option>
      </select>
    </div>`;
  }

  async function loadPurchases(signal) {
    const params = new URLSearchParams({ limit: "100" });
    if (state.purchaseStatus) params.set("status", state.purchaseStatus);
    const { purchases = [] } = await api(`/api/admin/purchases?${params.toString()}`, signal);
    const toolbar = `<div class="toolbar">${statusFilter("purchaseStatusFilter", "purchaseStatus", state.purchaseStatus, "Purchase status")}<span class="toolbar-count numeric">${purchases.length} purchase${purchases.length === 1 ? "" : "s"}</span></div>`;
    if (!purchases.length) return toolbar + emptyState("No purchases match this filter.");
    const rows = purchases.map((item) => `<tr>
      <td class="cell-muted numeric">${esc(fmtDate(item.created_at))}</td>
      <td dir="auto">${esc(item.user_email || "Not available")}</td>
      <td dir="auto">${esc(item.package_id || "Not available")}</td>
      <td class="numeric">${esc(fmtNumber(item.credits_purchased))}</td>
      <td class="numeric">${esc(fmtCents(item.amount_cents))}</td>
      <td>${statusPill(item.status)}</td>
    </tr>`);
    const mobile = purchases.map((item) => mobileResult(
      item.user_email || "User not available",
      statusPill(item.status),
      [
        ["When", fmtDate(item.created_at)],
        ["Package", item.package_id || "Not available"],
        ["Credits", fmtNumber(item.credits_purchased)],
        ["Amount", fmtCents(item.amount_cents)],
      ]
    ));
    return toolbar + desktopTable("Credit purchases", ["When", "User", "Package", "Credits", "Amount", "Status"], rows) + mobileResults(mobile, "Credit purchases");
  }

  async function loadSponsorships(signal) {
    const params = new URLSearchParams({ limit: "100" });
    if (state.sponsorshipStatus) params.set("status", state.sponsorshipStatus);
    const { sponsorships = [] } = await api(`/api/admin/sponsorships?${params.toString()}`, signal);
    const toolbar = `<div class="toolbar">${statusFilter("sponsorshipStatusFilter", "sponsorshipStatus", state.sponsorshipStatus, "Sponsorship status")}<span class="toolbar-count numeric">${sponsorships.length} sponsorship${sponsorships.length === 1 ? "" : "s"}</span></div>`;
    if (!sponsorships.length) return toolbar + emptyState("No sponsorships match this filter.");
    const rows = sponsorships.map((item) => `<tr>
      <td class="cell-muted numeric">${esc(fmtDate(item.created_at))}</td>
      <td dir="auto">${esc(item.user_email || "Not available")}</td>
      <td dir="auto">${esc(item.dedication_type || "Dedication")}: ${esc(item.dedication || "Not provided")}</td>
      <td dir="auto">${esc(item.parsha_name || "Not available")} ${esc(item.hebrew_year || "")}</td>
      <td class="numeric">${esc(fmtCents(item.amount_cents))}</td>
      <td>${statusPill(item.status)}</td>
    </tr>`);
    const mobile = sponsorships.map((item) => mobileResult(
      item.user_email || "Sponsor not available",
      statusPill(item.status),
      [
        ["When", fmtDate(item.created_at)],
        ["Dedication", `${item.dedication_type || "Dedication"}: ${item.dedication || "Not provided"}`],
        ["Parsha", `${item.parsha_name || "Not available"} ${item.hebrew_year || ""}`.trim()],
        ["Amount", fmtCents(item.amount_cents)],
      ]
    ));
    return toolbar + desktopTable("D'var Torah sponsorships", ["When", "Sponsor", "Dedication", "Parsha", "Amount", "Status"], rows) + mobileResults(mobile, "D'var Torah sponsorships");
  }

  async function loadAnalytics(signal) {
    const data = await api(`/api/admin/analytics?days=${encodeURIComponent(state.analyticsDays)}`, signal);
    const sessions = data.sessions || {};
    const tts = data.tts || {};
    const metrics = [
      ["Unique sessions", fmtNumber(sessions.unique_sessions)],
      ["Page views", fmtNumber(sessions.total_page_views)],
      ["Unique users", fmtNumber(sessions.unique_users)],
      ["Text to speech starts", fmtNumber(tts.total_starts)],
      ["Text to speech errors", fmtNumber(tts.total_errors), Number(tts.total_errors) > 0 ? "metric-error" : ""],
    ];
    const toolbar = `<div class="toolbar"><div class="field"><label for="analyticsDaysFilter">Time window</label><select id="analyticsDaysFilter" data-filter="analyticsDays">
      <option value="7"${selected(state.analyticsDays, "7")}>7 days</option>
      <option value="30"${selected(state.analyticsDays, "30")}>30 days</option>
      <option value="90"${selected(state.analyticsDays, "90")}>90 days</option>
    </select></div></div>`;
    const metricMarkup = `<div class="metric-grid">${metrics.map(([label, value, tone]) => `<article class="metric-card ${tone || ""}"><p class="metric-label">${esc(label)}, ${esc(state.analyticsDays)} days</p><p class="metric-value numeric">${esc(value)}</p></article>`).join("")}</div>`;
    const referrers = data.referrers || [];
    const devices = data.devices || [];
    const referrerMarkup = referrers.length
      ? desktopTable("Top referrers", ["Referrer", "Sessions"], referrers.map((item) => `<tr><td dir="auto">${esc(item.referrer || "Direct or unavailable")}</td><td class="numeric">${esc(fmtNumber(item.sessions))}</td></tr>`), true)
        + mobileResults(referrers.map((item) => mobileResult(item.referrer || "Direct or unavailable", "", [["Sessions", fmtNumber(item.sessions)]])), "Top referrers")
      : emptyState("No referrer data in this window.");
    const deviceMarkup = devices.length
      ? desktopTable("Device categories", ["Device", "Sessions"], devices.map((item) => `<tr><td dir="auto">${esc(item.device_type || "Unknown")}</td><td class="numeric">${esc(fmtNumber(item.sessions))}</td></tr>`), true)
        + mobileResults(devices.map((item) => mobileResult(item.device_type || "Unknown", "", [["Sessions", fmtNumber(item.sessions)]])), "Device categories")
      : emptyState("No device data in this window.");
    return toolbar + metricMarkup + `<section class="section-block"><div class="section-heading"><div><h2>Top referrers</h2><p>Session source</p></div></div>${referrerMarkup}</section>
      <section class="section-block"><div class="section-heading"><div><h2>Devices</h2><p>Session category</p></div></div>${deviceMarkup}</section>`;
  }

  async function loadAudit(signal) {
    const { audit_log: entries = [] } = await api("/api/admin/audit-log?limit=100", signal);
    if (!entries.length) return emptyState("No administrator actions have been recorded yet.");
    const rows = entries.map((item) => `<tr>
      <td class="cell-muted numeric">${esc(fmtDate(item.created_at))}</td>
      <td dir="auto">${esc(item.admin_email || "Not available")}</td>
      <td><span class="pill accent">${esc(item.action || "action")}</span></td>
      <td dir="auto">${esc(item.target_email || "Not applicable")}</td>
      <td class="cell-muted" dir="auto">${esc(JSON.stringify(item.details ?? {}))}</td>
    </tr>`);
    const mobile = entries.map((item) => mobileResult(
      item.action || "Admin action",
      '<span class="pill accent">audited</span>',
      [
        ["When", fmtDate(item.created_at)],
        ["Admin", item.admin_email || "Not available"],
        ["Target", item.target_email || "Not applicable"],
        ["Details", JSON.stringify(item.details ?? {})],
      ]
    ));
    return desktopTable("Administrator audit log", ["When", "Admin", "Action", "Target", "Details"], rows) + mobileResults(mobile, "Administrator audit log");
  }

  const LOADERS = {
    overview: loadOverview,
    users: loadUsers,
    flagged: loadFlagged,
    feedback: loadFeedback,
    errors: loadErrors,
    purchases: loadPurchases,
    sponsorships: loadSponsorships,
    analytics: loadAnalytics,
    audit: loadAudit,
  };

  function updateViewChrome() {
    const meta = VIEW_META[state.currentTab];
    viewTitle.textContent = meta.title;
    viewDescription.textContent = meta.description;
    mobileViewSelect.value = state.currentTab;
    document.querySelectorAll("#tabs [data-tab]").forEach((button) => {
      const active = button.dataset.tab === state.currentTab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    content.setAttribute("aria-labelledby", `tab-${state.currentTab}`);
  }

  function activateTab(tabName, focusTab = false) {
    if (!VIEW_META[tabName]) return;
    state.currentTab = tabName;
    updateViewChrome();
    if (focusTab) document.querySelector(`#tabs [data-tab="${tabName}"]`)?.focus();
    render();
  }

  async function render() {
    const generation = ++state.renderGeneration;
    state.activeController?.abort();
    const controller = new AbortController();
    state.activeController = controller;
    const meta = VIEW_META[state.currentTab];
    clearError();
    content.setAttribute("aria-busy", "true");
    content.innerHTML = loadingState(`Loading ${meta.title.toLowerCase()}`);
    announce(`Loading ${meta.title.toLowerCase()}.`);

    try {
      const markup = await LOADERS[state.currentTab](controller.signal);
      if (generation !== state.renderGeneration || controller.signal.aborted) return;
      content.innerHTML = markup;
      content.setAttribute("aria-busy", "false");
      announce(`${meta.title} loaded.`);
    } catch (error) {
      if (error.name === "AbortError" || generation !== state.renderGeneration) return;
      content.setAttribute("aria-busy", "false");
      if (error.code !== "forbidden" && error.code !== "unauthenticated") showError(error.message);
      content.innerHTML = `<div class="view-error-state"><strong>Could not load ${esc(meta.title.toLowerCase())}</strong><span>Check the connection and try again.</span><button class="button" type="button" data-retry>Try again</button></div>`;
    }
  }

  function dialogFocusables(dialog) {
    return Array.from(dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      .filter((element) => !element.hidden && element.getClientRects().length > 0);
  }

  function showDialog(dialog, preferredFocus) {
    if (!dialog.open) {
      focusReturn.set(dialog, document.activeElement);
      dialog.showModal();
    }
    window.requestAnimationFrame(() => {
      const target = preferredFocus || dialogFocusables(dialog)[0];
      target?.focus();
    });
  }

  function closeDialog(dialog) {
    if (dialog === actionDialog && state.mutation?.pending) return;
    if (dialog.open) dialog.close();
  }

  function bindDialog(dialog) {
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (dialog === actionDialog && state.mutation?.pending) {
          event.preventDefault();
          return;
        }
        event.preventDefault();
        closeDialog(dialog);
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = dialogFocusables(dialog);
      if (!focusables.length) {
        event.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.addEventListener("close", () => {
      const returnTarget = focusReturn.get(dialog);
      if (returnTarget?.isConnected) returnTarget.focus();
      else document.getElementById("adminMain")?.focus();
      if (dialog === convoDialog) {
        state.conversationController?.abort();
        state.conversationController = null;
      }
      if (dialog === actionDialog) state.mutation = null;
    });
  }

  function startConversationDialog(title) {
    state.conversationController?.abort();
    state.conversationController = new AbortController();
    state.conversationGeneration += 1;
    convoDialogTitle.textContent = title;
    convoContent.innerHTML = loadingState("Loading authorized conversation data");
    convoContent.setAttribute("aria-busy", "true");
    showDialog(convoDialog, convoDialog.querySelector("[data-dialog-close]"));
    return {
      generation: state.conversationGeneration,
      signal: state.conversationController.signal,
    };
  }

  function showConversationError(error) {
    if (error.name === "AbortError") return;
    convoContent.setAttribute("aria-busy", "false");
    convoContent.innerHTML = `<div class="view-error-state"><strong>Could not load this review</strong><span>${esc(error.message)}</span></div>`;
    announce(error.message);
  }

  async function viewUserConversations(userId, email) {
    const request = startConversationDialog(`Conversations for ${email || "this user"}`);
    try {
      const { conversations = [] } = await api(`/api/admin/users/${encodeURIComponent(userId)}/conversations`, request.signal);
      if (request.generation !== state.conversationGeneration || request.signal.aborted) return;
      convoContent.setAttribute("aria-busy", "false");
      if (!conversations.length) {
        convoContent.innerHTML = emptyState("No conversations are available for this account.");
        return;
      }
      convoContent.innerHTML = `<div class="conversation-list">${conversations.map((item) => `<article class="conversation-row">
        <div>
          <p class="conversation-title" dir="auto">${esc(item.title || "Untitled conversation")}</p>
          <p class="conversation-detail numeric">${esc(fmtNumber(item.message_count))} messages, updated ${esc(fmtDate(item.updated_at))}</p>
        </div>
        <button class="action" type="button" data-convo="${esc(item.id)}">View</button>
      </article>`).join("")}</div>`;
      announce(`${conversations.length} conversations loaded.`);
    } catch (error) {
      showConversationError(error);
    }
  }

  async function viewConversation(conversationId) {
    if (!conversationId) return;
    const request = startConversationDialog("Conversation review");
    try {
      const conversation = await api(`/api/admin/conversations/${encodeURIComponent(conversationId)}`, request.signal);
      if (request.generation !== state.conversationGeneration || request.signal.aborted) return;
      convoDialogTitle.textContent = conversation.title || "Untitled conversation";
      const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
      convoContent.setAttribute("aria-busy", "false");
      convoContent.innerHTML = `<p class="dialog-meta" dir="auto">${esc(conversation.user_email || "User not available")}, created ${esc(fmtDate(conversation.created_at))}</p>
        ${messages.length ? `<div class="transcript">${messages.map((message) => `<article class="message-transcript${message.role === "user" ? " user" : ""}">
          <p class="message-role">${esc(message.role || "message")}</p>
          <p class="message-copy" dir="auto">${esc(message.content || "")}</p>
        </article>`).join("")}</div>` : emptyState("This conversation has no messages.")}`;
      announce(`Conversation loaded with ${messages.length} messages.`);
    } catch (error) {
      showConversationError(error);
    }
  }

  function setActionDialogPending(pending) {
    state.mutation.pending = pending;
    actionDialog.setAttribute("aria-busy", String(pending));
    actionSubmit.disabled = pending;
    actionCancel.disabled = pending;
    actionDialog.querySelectorAll("[data-dialog-close]").forEach((button) => {
      button.disabled = pending;
    });
    actionFields.querySelectorAll("input, textarea, select").forEach((field) => {
      field.disabled = pending;
    });
  }

  function setActionState(message, tone = "") {
    actionState.className = `action-state${tone ? ` ${tone}` : ""}`;
    actionState.textContent = message;
  }

  function openMutationDialog(button) {
    const { act, id, email } = button.dataset;
    if (act !== "credits" && act !== "role") return;
    const isAdmin = button.dataset.admin === "1";
    state.mutation = {
      type: act,
      userId: id,
      email: email || "this user",
      makeAdmin: !isAdmin,
      pending: false,
      done: false,
    };
    actionState.className = "action-state";
    actionState.textContent = "";
    actionCancel.hidden = false;
    actionCancel.disabled = false;
    actionDialog.querySelectorAll("[data-dialog-close]").forEach((closeButton) => {
      closeButton.disabled = false;
    });

    if (act === "credits") {
      actionDialogTitle.textContent = "Adjust credit balance";
      actionDialogDescription.textContent = `Change the credit balance for ${state.mutation.email}. This action and its reason will be recorded in the audit log.`;
      actionFields.innerHTML = `<div class="field">
        <label for="creditDelta">Credit change</label>
        <input id="creditDelta" name="delta" type="number" min="-10000" max="10000" step="1" required inputmode="numeric" placeholder="For example, 5 or -2">
        <p class="field-hint">Use a positive number to grant credits or a negative number to deduct them. Zero is not accepted.</p>
      </div>
      <div class="field">
        <label for="creditReason">Reason for this change</label>
        <textarea id="creditReason" name="reason" minlength="1" maxlength="500" required placeholder="Explain why this balance is changing"></textarea>
      </div>`;
      actionSubmit.textContent = "Apply credit change";
    } else {
      const action = state.mutation.makeAdmin ? "Grant" : "Revoke";
      actionDialogTitle.textContent = `${action} administrator access`;
      actionDialogDescription.textContent = state.mutation.makeAdmin
        ? `Grant administrator access to ${state.mutation.email}. This gives the account access to every view and mutation on this page.`
        : `Revoke administrator access from ${state.mutation.email}. The account will no longer be able to open this workspace.`;
      actionFields.innerHTML = `<p class="field-hint">The server will enforce this role change immediately and record it in the audit log.</p>`;
      actionSubmit.textContent = state.mutation.makeAdmin ? "Grant admin access" : "Revoke admin access";
    }
    showDialog(actionDialog, actionFields.querySelector("input, textarea") || actionSubmit);
  }

  async function submitMutation() {
    const mutation = state.mutation;
    if (!mutation) return;
    if (mutation.done) {
      closeDialog(actionDialog);
      return;
    }

    let path;
    let body;
    if (mutation.type === "credits") {
      const deltaInput = document.getElementById("creditDelta");
      const reasonInput = document.getElementById("creditReason");
      const delta = Number(deltaInput.value);
      const reason = reasonInput.value.trim();
      deltaInput.setCustomValidity("");
      reasonInput.setCustomValidity("");
      if (!Number.isInteger(delta) || delta === 0 || delta < -10000 || delta > 10000) {
        deltaInput.setCustomValidity("Enter a whole number from -10000 to 10000, excluding zero.");
      }
      if (!reason) reasonInput.setCustomValidity("Enter a reason for this credit change.");
      if (!actionForm.reportValidity()) return;
      path = `/api/admin/users/${encodeURIComponent(mutation.userId)}/credits`;
      body = { delta, reason };
    } else {
      path = `/api/admin/users/${encodeURIComponent(mutation.userId)}/role`;
      body = { is_admin: mutation.makeAdmin };
    }

    setActionDialogPending(true);
    setActionState("Applying this change.");
    try {
      const result = await apiPost(path, body);
      mutation.done = true;
      setActionDialogPending(false);
      actionFields.querySelectorAll("input, textarea, select").forEach((field) => {
        field.disabled = true;
      });
      actionCancel.hidden = true;
      actionSubmit.textContent = "Done";
      const message = mutation.type === "credits"
        ? `Credit balance updated. New balance: ${fmtNumber(result.credits)}.`
        : `Administrator access ${mutation.makeAdmin ? "granted" : "revoked"}.`;
      setActionState(message, "success");
      announce(message);
      await render();
    } catch (error) {
      setActionDialogPending(false);
      if (error.code === "unauthenticated") return;
      setActionState(error.message, "error");
      announce(`Action failed. ${error.message}`);
    }
  }

  tabs.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (button) activateTab(button.dataset.tab);
  });

  tabs.addEventListener("keydown", (event) => {
    const buttons = Array.from(tabs.querySelectorAll("button[data-tab]"));
    const currentIndex = buttons.indexOf(document.activeElement);
    if (currentIndex < 0) return;
    let nextIndex = currentIndex;
    if (["ArrowDown", "ArrowRight"].includes(event.key)) nextIndex = (currentIndex + 1) % buttons.length;
    else if (["ArrowUp", "ArrowLeft"].includes(event.key)) nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = buttons.length - 1;
    else return;
    event.preventDefault();
    activateTab(buttons[nextIndex].dataset.tab, true);
  });

  mobileViewSelect.addEventListener("change", () => activateTab(mobileViewSelect.value));

  content.addEventListener("click", (event) => {
    const retry = event.target.closest("[data-retry]");
    if (retry) {
      render();
      return;
    }
    const pageButton = event.target.closest("[data-page-offset]");
    if (pageButton) {
      state.userOffset = Number(pageButton.dataset.pageOffset || 0);
      render();
      return;
    }
    const actionButton = event.target.closest("button[data-act]");
    if (actionButton) {
      if (actionButton.dataset.act === "convos") {
        viewUserConversations(actionButton.dataset.id, actionButton.dataset.email);
      } else {
        openMutationDialog(actionButton);
      }
      return;
    }
    const conversationButton = event.target.closest("button[data-convo]");
    if (conversationButton) viewConversation(conversationButton.dataset.convo);
  });

  content.addEventListener("submit", (event) => {
    if (event.target.id === "userSearchForm") {
      event.preventDefault();
      state.userSearch = document.getElementById("userSearchInput").value.trim();
      state.userOffset = 0;
      render();
    } else if (event.target.id === "errorFilterForm") {
      event.preventDefault();
      state.errorType = document.getElementById("errorTypeInput").value.trim();
      render();
    }
  });

  content.addEventListener("change", (event) => {
    const filter = event.target.dataset.filter;
    if (!filter || !(filter in state)) return;
    state[filter] = event.target.value;
    render();
  });

  convoContent.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-convo]");
    if (button) viewConversation(button.dataset.convo);
  });

  document.addEventListener("click", (event) => {
    const closeButton = event.target.closest("[data-dialog-close]");
    if (!closeButton) return;
    const dialog = document.getElementById(closeButton.dataset.dialogClose);
    if (dialog instanceof HTMLDialogElement) closeDialog(dialog);
  });

  actionForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMutation();
  });

  bindDialog(convoDialog);
  bindDialog(actionDialog);
  updateViewChrome();
  render();
})();
