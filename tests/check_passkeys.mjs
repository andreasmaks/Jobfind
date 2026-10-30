// Exercise native credential serialization and UI flows without opening a browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(new URL("../assets/passkeys.js", import.meta.url), "utf8");
class Element {
  constructor(kind = "") { this.kind = kind; this.events = {}; this.children = []; this.value = ""; this.disabled = false; this.attributes = {}; this.classList = { toggle() {} }; }
  addEventListener(type, fn) { this.events[type] = fn; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  querySelectorAll(selector) { return this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)]).filter((child) => child.kind === selector); }
  setAttribute(key, value) { this.attributes[key] = value; }
  scrollIntoView() { this.scrolled = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  focus() { this.focused = true; }
}
const bytes = new Uint8Array([251, 255, 0]).buffer;
const encoded = "-_8A";
const credential = (registration) => ({
  id: encoded, rawId: bytes, type: "public-key", getClientExtensionResults: () => ({}),
  response: registration ? { clientDataJSON: bytes, attestationObject: bytes, getTransports: () => ["internal"] }
    : { clientDataJSON: bytes, authenticatorData: bytes, signature: bytes, userHandle: bytes },
});
for (const screen of ["login", "management", "rejected"]) {
  const nodes = new Map();
  const ids = screen === "login" ? ["passkey-login", "passkey-login-status"] : ["passkeys-manage", "passkeys-name", "passkeys-dialog", "passkeys-form", "passkeys-password", "passkeys-status", "passkeys-list", "passkeys-close", "passkeys-submit", "passkeys-confirmation-fields"];
  for (const id of ids) nodes.set(id, new Element());
  if (screen !== "login") {
    nodes.get("passkeys-name").kind = nodes.get("passkeys-password").kind = "input";
    nodes.get("passkeys-submit").kind = "button";
    nodes.get("passkeys-form").children = [nodes.get("passkeys-name"), nodes.get("passkeys-password"), nodes.get("passkeys-submit")];
  }
  const calls = [];
  let registered = false;
  let assigned = null;
  let nativeCalls = 0;
  const native = async (options, registration) => {
    nativeCalls += 1;
    assert.deepEqual([...options.publicKey.challenge], [251, 255, 0]);
    if (registration) assert.deepEqual([...options.publicKey.user.id], [251, 255, 0]);
    return credential(registration);
  };
  const context = vm.createContext({
    window: { isSecureContext: true, PublicKeyCredential: class {}, JobfindI18n: { t: (text) => text },
      confirm: () => true, dispatchEvent: (event) => { assert.equal(event.type, "jobfind:session-changed"); assert.equal(event.detail.csrf, "fresh-csrf-fixture"); },
      location: { assign: (url) => { assigned = url; } } },
    navigator: { onLine: true, credentials: { get: (options) => native(options, false), create: (options) => native(options, true) } },
    document: { getElementById: (id) => nodes.get(id) || null, createElement: (tag) => new Element(tag) },
    Uint8Array, atob, btoa, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    fetch: async (path, options = {}) => {
      calls.push([path, options]);
      if (path === "/api/passkeys/register/options") {
        assert.equal(JSON.parse(options.body).password, "fictional password", "Read autofill before mutating field state");
        assert.equal(nodes.get("passkeys-password").disabled, false, "Do not disable autofilled password fields");
        if (screen === "rejected") return { ok: false, json: async () => ({ ok: false, error: "password_required" }) };
      }
      let data;
      if (path === "/api/csrf") data = { token: "csrf-fixture" };
      else if (path === "/api/passkeys") data = { passkeys: registered ? [{ id: encoded, name: "Example device" }] : [] };
      else if (path.endsWith("/options")) data = { options: { challenge: encoded, user: { id: encoded } } };
      else {
        const body = JSON.parse(options.body);
        if (path.endsWith("/verify")) {
          assert.equal(body.credential.rawId, encoded);
          assert.equal(body.credential.response.clientDataJSON, encoded);
          if (screen === "management") {
            assert.equal(body.credential.response.attestationObject, encoded);
            assert.equal(options.headers["X-CSRF-Token"], "csrf-fixture");
            registered = true;
          } else assert.equal(body.credential.response.userHandle, encoded);
        } else if (path.endsWith("/delete")) registered = false;
        data = { ok: true, csrf: "fresh-csrf-fixture" };
      }
      return { ok: true, json: async () => ({ ok: true, ...data }) };
    },
  });
  vm.runInContext(source, context);
  if (screen === "login") {
    await nodes.get("passkey-login").events.click();
    assert.equal(assigned, "/");
    assert(calls.every(([, options]) => options.credentials === "same-origin"));
  } else {
    await nodes.get("passkeys-manage").events.click();
    nodes.get("passkeys-password").value = "fictional password";
    await nodes.get("passkeys-form").events.submit({ preventDefault() {} });
    assert.equal(nativeCalls, 0, "Password verification must precede the device step");
    if (screen === "rejected") {
      assert.equal(nodes.get("passkeys-password").value, "fictional password", "Keep rejected input available for correction");
      assert.equal(nodes.get("passkeys-status").attributes.role, "alert");
      assert.equal(nodes.get("passkeys-status").scrolled, true);
      assert.equal(nodes.get("passkeys-status").focused, true);
      assert.match(nodes.get("passkeys-status").textContent, /nicht akzeptiert/);
      assert.equal(registered, false);
      continue;
    }
    assert.equal(nodes.get("passkeys-password").value, "");
    assert.equal(nodes.get("passkeys-confirmation-fields").hidden, true);
    const requestCount = calls.length;
    const deviceStep = nodes.get("passkeys-form").events.submit({ preventDefault() {} });
    assert.equal(nativeCalls, 1, "Open the native device prompt directly from the second tap");
    assert.equal(calls.length, requestCount, "No network await may consume the device-step user gesture");
    await deviceStep;
    assert.equal(registered, true);
    assert.equal(nodes.get("passkeys-password").value, "");
    nodes.get("passkeys-password").value = "fictional password";
    await nodes.get("passkeys-list").children[0].children[1].events.click();
    assert.equal(registered, false);
    assert.equal(nodes.get("passkeys-password").value, "");
    assert(calls.filter(([path]) => path === "/api/csrf").length >= 3);
  }
}
console.log("Passkey client checks passed: login, registration, removal, base64url, CSRF, password cleanup.");
