const cfg = window.WUSOM_CONFIG;
const ID_TOKEN_KEY = "wusom_id_token";
const USER_EMAIL_KEY = "wusom_user_email";

function loginUrl() {
  const params = new URLSearchParams({
    response_type: "token",
    client_id: cfg.userPoolClientId,
    redirect_uri: cfg.redirectUri,
    scope: "email openid profile",
  });
  return `${cfg.cognitoDomain}/login?${params.toString()}`;
}

function logoutUrl() {
  const params = new URLSearchParams({
    client_id: cfg.userPoolClientId,
    logout_uri: cfg.redirectUri,
  });
  return `${cfg.cognitoDomain}/logout?${params.toString()}`;
}

// Cognito Hosted UI (implicit flow) returns id_token in the URL fragment.
function captureTokenFromRedirect() {
  if (!window.location.hash) return;
  const params = new URLSearchParams(window.location.hash.substring(1));
  const idToken = params.get("id_token");
  if (idToken) {
    localStorage.setItem(ID_TOKEN_KEY, idToken);
    const payload = JSON.parse(atob(idToken.split(".")[1]));
    localStorage.setItem(USER_EMAIL_KEY, payload.email || "");
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

function getIdToken() {
  return localStorage.getItem(ID_TOKEN_KEY);
}

function getUserEmail() {
  return localStorage.getItem(USER_EMAIL_KEY);
}

function isSignedIn() {
  return !!getIdToken();
}

function signOut() {
  localStorage.removeItem(ID_TOKEN_KEY);
  localStorage.removeItem(USER_EMAIL_KEY);
  window.location.href = logoutUrl();
}

function updateAuthUI() {
  const loginBtn = document.getElementById("loginBtn");
  const logoutBtn = document.getElementById("logoutBtn");
  const userEmail = document.getElementById("userEmail");
  const postHint = document.getElementById("postHint");
  const postSubmit = document.getElementById("postSubmit");

  if (isSignedIn()) {
    loginBtn.classList.add("hidden");
    logoutBtn.classList.remove("hidden");
    userEmail.classList.remove("hidden");
    userEmail.textContent = getUserEmail();
    postHint.classList.add("hidden");
    postSubmit.disabled = false;
  } else {
    loginBtn.classList.remove("hidden");
    logoutBtn.classList.add("hidden");
    userEmail.classList.add("hidden");
    postHint.classList.remove("hidden");
    postSubmit.disabled = true;
  }
}

async function fetchItems(category) {
  const url = new URL(`${cfg.apiUrl}/items`);
  if (category) url.searchParams.set("category", category);
  const res = await fetch(url);
  const data = await res.json();
  renderItems(data.items || []);
}

function renderItems(items) {
  const list = document.getElementById("itemsList");
  list.innerHTML = "";
  if (items.length === 0) {
    list.innerHTML = '<li class="empty">Nothing posted in this category yet.</li>';
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "item-card";
    const claimed = item.status === "claimed";
    li.innerHTML = `
      <div class="item-main">
        <span class="item-title">${escapeHtml(item.title)}</span>
        <span class="item-category">${escapeHtml(item.category)}</span>
      </div>
      <p class="item-desc">${escapeHtml(item.description || "")}</p>
      <div class="item-footer">
        <span class="item-status ${claimed ? "claimed" : "available"}">${claimed ? "Claimed" : "Available"}</span>
        ${claimed ? "" : `<button class="btn btn-small claim-btn" data-id="${item.item_id}">Claim</button>`}
      </div>`;
    list.appendChild(li);
  }
  list.querySelectorAll(".claim-btn").forEach((btn) => {
    btn.addEventListener("click", () => claimItem(btn.dataset.id));
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function claimItem(itemId) {
  if (!isSignedIn()) {
    alert("Sign in with your WUSTL email first.");
    return;
  }
  const res = await fetch(`${cfg.apiUrl}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: getIdToken() },
    body: JSON.stringify({ action: "claim", item_id: itemId }),
  });
  if (res.ok) {
    fetchItems(document.getElementById("categoryFilter").value);
  } else {
    const err = await res.json();
    alert(err.error || "Could not claim item.");
  }
}

async function postItem(e) {
  e.preventDefault();
  const title = document.getElementById("title").value;
  const category = document.getElementById("category").value;
  const description = document.getElementById("description").value;

  const res = await fetch(`${cfg.apiUrl}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: getIdToken() },
    body: JSON.stringify({ action: "create", title, category, description }),
  });
  if (res.ok) {
    document.getElementById("postForm").reset();
    fetchItems(document.getElementById("categoryFilter").value);
  } else {
    alert("Could not post item. Make sure you're signed in.");
  }
}

async function subscribe() {
  if (!isSignedIn()) {
    alert("Sign in with your WUSTL email first.");
    return;
  }
  const res = await fetch(`${cfg.apiUrl}/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: getIdToken() },
  });
  const statusEl = document.getElementById("subscribeStatus");
  statusEl.textContent = res.ok
    ? "You're subscribed. Look for the weekly digest in your inbox."
    : "Something went wrong subscribing - try signing in again.";
}

document.addEventListener("DOMContentLoaded", () => {
  captureTokenFromRedirect();
  updateAuthUI();
  fetchItems();

  document.getElementById("loginBtn").addEventListener("click", () => {
    window.location.href = loginUrl();
  });
  document.getElementById("logoutBtn").addEventListener("click", signOut);
  document.getElementById("postForm").addEventListener("submit", postItem);
  document.getElementById("subscribeBtn").addEventListener("click", subscribe);
  document.getElementById("categoryFilter").addEventListener("change", (e) => {
    fetchItems(e.target.value);
  });
});
