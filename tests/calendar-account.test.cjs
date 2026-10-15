const test = require("node:test");
const assert = require("node:assert/strict");
const account = require("../web/calendar-account.js");

const loggedIn = {user: {id: 1}, csrf_token: "fresh-token"};
const loggedOut = {user: null, csrf_token: "new-token"};
function fixture(responses) {
  const calls = [];
  const fetcher = async (path, options) => {
    calls.push({path, options});
    const next = responses.shift();
    if (next instanceof Error) throw next;
    assert.ok(next, "unexpected request");
    return {ok: next.ok ?? true, json: async () => next.body};
  };
  return {fetcher, calls};
}

test("logout uses a fresh account token, revokes session, and verifies logout", async () => {
  const {fetcher, calls} = fixture([{body: loggedIn}, {body: loggedOut}, {body: loggedOut}]);
  await account.logout(fetcher);
  assert.deepEqual(calls.map(call => call.path), ["/api/session", "/api/logout", "/api/session"]);
  assert.equal(calls[1].options.headers["X-CSRF-Token"], "fresh-token");
  assert.equal(calls[1].options.method, "POST");
  assert.ok(calls.every(call => call.options.cache === "no-store" && call.options.credentials === "same-origin"));
});
test("expired or already logged-out sessions may leave without a failing logout POST", async () => {
  const {fetcher, calls} = fixture([{body: loggedOut}]);
  await account.logout(fetcher);
  assert.equal(calls.length, 1);
});
test("logout failure never reports success", async () => {
  const {fetcher} = fixture([{body: loggedIn}, {ok: false, body: {error: "denied"}}]);
  await assert.rejects(account.logout(fetcher), /denied/);
});
test("a session that remains authenticated is not reported as logged out", async () => {
  const {fetcher} = fixture([{body: loggedIn}, {body: loggedOut}, {body: loggedIn}]);
  await assert.rejects(account.logout(fetcher), /尚未退出/);
});
test("network failures and malformed sessions are not treated as anonymous sessions", async () => {
  await assert.rejects(account.logout(fixture([new Error("offline")]).fetcher), /offline/);
  await assert.rejects(account.logout(fixture([{body: {}}]).fetcher), /响应无效/);
});
