// Exercise native credential serialization and UI flows without opening a browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(new URL("../assets/passkeys.js", import.meta.url), "utf8");
class Element {
  constructor() { this.events = {}; this.children = []; this.value = ""; this.disabled = false; }
  addEventListener(type, fn) { this.events[type] = fn; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  querySelectorAll() { return this.children; }
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
for (const screen of ["login", "management"]) {
  const nodes = new Map();
  const ids = screen === "login" ? ["passkey-login", "passkey-login-status"] : ["passkeys-manage", "passkeys-name", "passkeys-dialog", "passkeys-form", "passkeys-password", "passkeys-status", "passkeys-list", "passkeys-close"];
  for (const id of ids) nodes.set(id, new Element());
  const calls = [];
  let registered = false;
  let assigned = null;
  const native = async (options, registration) => {
    assert.deepEqual([...options.publicKey.challenge], [251, 255, 0]);
    if (registration) assert.deepEqual([...options.publicKey.user.id], [251, 255, 0]);
    return credential(registration);
  };
  const context = vm.createContext({
    window: { isSecureContext: true, PublicKeyCredential: class {}, JobfindI18n: { t: (text) => text },
      confirm: () => true, dispatchEvent: (event) => { assert.equal(event.type, "jobfind:session-changed"); assert.equal(event.detail.csrf, "fresh-csrf-fixture"); },
      location: { assign: (url) => { assigned = url; } } },
    navigator: { onLine: true, credentials: { get: (options) => native(options, false), create: (options) => native(options, true) } },
    document: { getElementById: (id) => nodes.get(id) || null, createElement: () => new Element() },
    Uint8Array, atob, btoa, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    fetch: async (path, options = {}) => {
      calls.push([path, options]);
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
