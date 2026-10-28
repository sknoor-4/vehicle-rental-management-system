(() => {
  const search = document.querySelector("#vehicle-search");
  const filter = document.querySelector("#status-filter");
  const cards = [...document.querySelectorAll(".vehicle-card")];
  const empty = document.querySelector("#no-results");

  function updateVehicles() {
    const query = (search?.value || "").trim().toLowerCase();
    const status = filter?.value || "all";
    let visible = 0;
    cards.forEach((card) => {
      const matchesText = card.dataset.search.includes(query);
      const matchesStatus = status === "all" || card.dataset.status === status;
      card.hidden = !(matchesText && matchesStatus);
      if (!card.hidden) visible += 1;
    });
    if (empty) empty.hidden = visible !== 0 || cards.length === 0;
  }
  search?.addEventListener("input", updateVehicles);
  filter?.addEventListener("change", updateVehicles);

  document.querySelectorAll(".delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const name = form.dataset.vehicle || "this vehicle";
      if (!window.confirm(`Delete ${name}? If rental or maintenance history is linked, it will be kept safely.`)) event.preventDefault();
    });
  });
  document.querySelectorAll(".flash button").forEach((button) => button.addEventListener("click", () => button.closest(".flash")?.remove()));

  const panels = [...document.querySelectorAll(".quick-panel")];
  document.querySelectorAll("[data-panel]").forEach((button) => button.addEventListener("click", (event) => {
    if (button.tagName === "A") event.preventDefault();
    const target = document.getElementById(button.dataset.panel);
    if (!target) return;
    const shouldOpen = target.hidden;
    panels.forEach((panel) => { panel.hidden = true; });
    target.hidden = !shouldOpen;
    if (shouldOpen) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  document.querySelectorAll(".panel-close").forEach((button) => button.addEventListener("click", () => {
    const panel = button.closest(".quick-panel");
    if (panel) panel.hidden = true;
  }));

  const launcher = document.querySelector("#help-launcher");
  const helpPanel = document.querySelector("#help-panel");
  const closeHelp = document.querySelector("#help-close");
  const messagesNode = document.querySelector("#help-messages");
  const chatForm = document.querySelector("#help-chat-form");
  const chatInput = document.querySelector("#help-chat-input");
  const conversation = [];
  const setHelpOpen = (open) => {
    if (!helpPanel || !launcher) return;
    helpPanel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    if (open) chatInput?.focus();
  };
  launcher?.addEventListener("click", () => setHelpOpen(helpPanel?.hidden));
  closeHelp?.addEventListener("click", () => setHelpOpen(false));

  function addMessage(text, who) {
    if (!messagesNode) return;
    const node = document.createElement("div");
    node.className = `help-message ${who}`;
    node.textContent = text;
    messagesNode.append(node);
    messagesNode.scrollTop = messagesNode.scrollHeight;
    return node;
  }
  async function sendMessage(text) {
    const prompt = text.trim();
    if (!prompt || !chatInput) return;
    conversation.push({ role: "user", content: prompt });
    addMessage(prompt, "user");
    chatInput.value = "";
    const pending = addMessage("Checking that for you…", "assistant");
    try {
      const response = await fetch("/api/help/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: prompt })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Help is temporarily unavailable.");
      pending.textContent = data.reply;
      conversation.push({ role: "assistant", content: data.reply });
    } catch (error) {
      pending.textContent = error.message || "I couldn't reach the help service. Please try again.";
    }
  }
  chatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage(chatInput?.value || "");
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
    setHelpOpen(true);
    void sendMessage(button.dataset.prompt || "");
  }));

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    document.querySelectorAll(".section-block, .customer-vehicle, .stat-card").forEach((section) => observer.observe(section));
  }
})();
