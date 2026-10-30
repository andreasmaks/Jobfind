// Native WebAuthn, no third-party frontend bundle or externally loaded code.
(() => {
  const { t } = window.JobfindI18n;
  const supported = window.isSecureContext && !!window.PublicKeyCredential && !!navigator.credentials;
  const decode = (value) => Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/")), (char) => char.charCodeAt(0));
  const encode = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const optionsFor = (options, registration) => {
    const result = { ...options, challenge: decode(options.challenge) };
    if (registration) result.user = { ...options.user, id: decode(options.user.id) };
    for (const field of ["excludeCredentials", "allowCredentials"]) {
      if (options[field]) result[field] = options[field].map((item) => ({ ...item, id: decode(item.id) }));
    }
    return result;
  };
  const credentialJSON = (credential) => {
    const response = credential.response;
    const result = { id: credential.id, rawId: encode(credential.rawId), type: credential.type,
      response: { clientDataJSON: encode(response.clientDataJSON) }, clientExtensionResults: credential.getClientExtensionResults() };
    if (response.attestationObject) {
      result.response.attestationObject = encode(response.attestationObject);
      result.response.transports = response.getTransports?.() || [];
    } else {
      result.response.authenticatorData = encode(response.authenticatorData);
      result.response.signature = encode(response.signature);
      result.response.userHandle = response.userHandle ? encode(response.userHandle) : null;
    }
    return result;
  };
  const request = async (path, payload, protectedAction = false) => {
    const headers = { "Content-Type": "application/json" };
    if (protectedAction) {
      const response = await fetch("/api/csrf", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("auth_required");
      headers["X-CSRF-Token"] = (await response.json()).token;
    }
    const response = await fetch(path, { method: "POST", credentials: "same-origin", cache: "no-store", headers, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "passkey_failed");
    return data;
  };
  const errorText = (error) => {
    if (error.name === "NotAllowedError" || error.name === "AbortError") return t("Vorgang abgebrochen oder Zeit abgelaufen. Du kannst es erneut versuchen.");
    if (error.name === "InvalidStateError") return t("Dieser Passkey ist bereits registriert.");
    if (error.message === "password_required") return t("Das Jobfind-Passwort wurde nicht akzeptiert. Verwende dein Passwort für die Jobfind-Anmeldeseite, nicht den Gerätecode.");
    if (error.message === "invalid_csrf" || error.message === "auth_required") return t("Deine Anmeldung hat sich geändert. Bitte lade die Seite neu und melde dich bei Bedarf erneut an.");
    if (error.message === "invalid_origin") return t("Die Webadresse wurde nicht akzeptiert. Öffne Jobfind über seine übliche HTTPS-Adresse.");
    if (error.message === "rate_limited") return t("Zu viele Versuche. Bitte warte kurz und versuche es erneut.");
    return t("Passkey-Vorgang fehlgeschlagen. Bitte versuche es erneut oder nutze dein Passwort.");
  };
  const login = document.getElementById("passkey-login");
  if (login) {
    login.hidden = !supported;
    login.addEventListener("click", async () => {
      const message = document.getElementById("passkey-login-status");
      login.disabled = true;
      message.textContent = t("Passkey wird geprüft …");
      try {
        const { options } = await request("/api/passkeys/auth/options", {});
        const credential = await navigator.credentials.get({ publicKey: optionsFor(options, false) });
        if (!credential) throw new Error("passkey_failed");
        await request("/api/passkeys/auth/verify", { credential: credentialJSON(credential) });
        window.location.assign("/");
      } catch (error) {
        message.textContent = errorText(error);
        login.disabled = false;
      }
    });
  }
  const manage = document.getElementById("passkeys-manage");
  if (!manage) return;
  document.getElementById("passkeys-name").value = t("Mein Passkey");
  const dialog = document.getElementById("passkeys-dialog");
  const form = document.getElementById("passkeys-form");
  const password = document.getElementById("passkeys-password");
  const message = document.getElementById("passkeys-status");
  const fields = document.getElementById("passkeys-confirmation-fields");
  const submit = document.getElementById("passkeys-submit");
  let busy = false;
  let pendingRegistration = null;
  const stage = () => {
    fields.hidden = !!pendingRegistration;
    password.required = !pendingRegistration;
    submit.textContent = t(pendingRegistration ? "Passkey auf diesem Gerät erstellen" : "Passwort bestätigen");
  };
  const showMessage = (text, failed = false) => {
    message.setAttribute("role", failed ? "alert" : "status");
    message.setAttribute("aria-live", failed ? "assertive" : "polite");
    message.classList.toggle("has-error", failed);
    message.textContent = text;
    if (failed) {
      message.focus({ preventScroll: true });
      message.scrollIntoView({ block: "nearest" });
    }
  };
  const setBusy = (value) => {
    busy = value;
    form.querySelectorAll("button").forEach((item) => { item.disabled = value; });
    form.querySelectorAll("input").forEach((item) => { item.readOnly = value; });
    document.getElementById("passkeys-list").querySelectorAll("button").forEach((item) => { item.disabled = value; });
  };
  const load = async () => {
    const response = await fetch("/api/passkeys", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("auth_required");
    const { passkeys } = await response.json();
    const list = document.getElementById("passkeys-list");
    list.replaceChildren();
    if (!passkeys.length) {
      const empty = document.createElement("li");
      empty.textContent = t("Noch kein Passkey eingerichtet.");
      list.append(empty);
    }
    for (const key of passkeys) {
      const row = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = key.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "theme-toggle";
      remove.textContent = t("Passkey entfernen");
      remove.addEventListener("click", async () => {
        if (busy) return;
        if (!password.value) { password.focus(); message.textContent = t("Bitte bestätige dein aktuelles Jobfind-Passwort."); return; }
        if (!window.confirm(t("Diesen Passkey entfernen? Die Anmeldung mit Passwort bleibt möglich."))) return;
        const enteredPassword = password.value;
        setBusy(true);
        try {
          const result = await request("/api/passkeys/delete", { id: key.id, password: enteredPassword }, true);
          window.dispatchEvent(new CustomEvent("jobfind:session-changed", { detail: { csrf: result.csrf } }));
          password.value = "";
          await load();
          showMessage(t("Passkey entfernt."));
        } catch (error) { showMessage(errorText(error), true); }
        finally { setBusy(false); }
      });
      row.append(label, remove);
      list.append(row);
    }
  };
  manage.addEventListener("click", async () => {
    dialog.showModal();
    password.value = "";
    pendingRegistration = null;
    stage();
    showMessage("");
    if (!supported || !navigator.onLine) {
      showMessage(t("Passkeys benötigen eine sichere Internetverbindung und einen unterstützten Browser."), true);
      setBusy(true);
      return;
    }
    setBusy(false);
    try { await load(); } catch (error) { showMessage(errorText(error), true); }
  });
  dialog.addEventListener("close", () => { password.value = ""; pendingRegistration = null; stage(); manage.focus(); });
  document.getElementById("passkeys-close").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !supported) return;
    if (!pendingRegistration) {
      // Read autofilled values before changing input state or awaiting network calls.
      const enteredPassword = password.value;
      const enteredName = document.getElementById("passkeys-name").value;
      setBusy(true);
      showMessage(t("Jobfind-Passwort wird geprüft …"));
      try {
        const { options } = await request("/api/passkeys/register/options", { password: enteredPassword, name: enteredName }, true);
        pendingRegistration = options;
        password.value = "";
        stage();
        showMessage(t("Passwort bestätigt. Tippe jetzt auf „Passkey auf diesem Gerät erstellen“."));
        submit.focus();
      } catch (error) { showMessage(errorText(error), true); }
      finally { setBusy(false); }
      return;
    }
    setBusy(true);
    showMessage(t("Bestätige die Passkey-Erstellung auf deinem Gerät."));
    try {
      // No fetch/await before this call: it runs directly inside the second tap.
      const credential = await navigator.credentials.create({ publicKey: optionsFor(pendingRegistration, true) });
      if (!credential) throw new Error("passkey_failed");
      await request("/api/passkeys/register/verify", { credential: credentialJSON(credential) }, true);
      await load();
      showMessage(t("Passkey eingerichtet. Du kannst dich damit künftig anmelden."));
    } catch (error) { showMessage(errorText(error), true); }
    finally { password.value = ""; pendingRegistration = null; stage(); setBusy(false); }
  });
})();
