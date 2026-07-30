import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";


test("review requests preserve session cookies and upstream Set-Cookie", async () => {
  let forwarded;
  globalThis.fetch = async (request) => {
    forwarded = request;
    return new Response("review", {
      status: 200,
      headers: {"set-cookie": "review_session=signed; Path=/; HttpOnly; Secure"},
    });
  };

  const response = await worker.fetch(new Request(
    "https://releasecraft-proxy.skillaz-release.workers.dev/review/DEV-46757",
    {headers: {cookie: "review_session=existing"}},
  ));

  assert.equal(response.status, 200);
  assert.equal(forwarded.headers.get("cookie"), "review_session=existing");
  assert.equal(
    response.headers.get("set-cookie"),
    "review_session=signed; Path=/; HttpOnly; Secure",
  );
});


test("review POST requests forward their method and body", async () => {
  let forwarded;
  globalThis.fetch = async (request) => {
    forwarded = request;
    return new Response(null, {status: 303, headers: {location: "/review/DEV-46757"}});
  };

  const response = await worker.fetch(new Request(
    "https://releasecraft-proxy.skillaz-release.workers.dev/review/DEV-46757/summary",
    {
      method: "POST",
      headers: {"content-type": "application/x-www-form-urlencoded"},
      body: "summary=Updated",
    },
  ));

  assert.equal(response.status, 303);
  assert.equal(forwarded.method, "POST");
  assert.equal(await forwarded.text(), "summary=Updated");
});


test("only Railway redirects are rewritten to the proxy origin", async () => {
  globalThis.fetch = async () => new Response(null, {
    status: 303,
    headers: {location: "https://skillaz-digest.up.railway.app/review/DEV-46757"},
  });
  const internal = await worker.fetch(new Request(
    "https://releasecraft-proxy.skillaz-release.workers.dev/auth/yandex/callback",
  ));
  assert.equal(
    internal.headers.get("location"),
    "https://releasecraft-proxy.skillaz-release.workers.dev/review/DEV-46757",
  );

  globalThis.fetch = async () => new Response(null, {
    status: 303,
    headers: {location: "https://oauth.yandex.ru/authorize?client_id=test"},
  });
  const external = await worker.fetch(new Request(
    "https://releasecraft-proxy.skillaz-release.workers.dev/auth/yandex/login",
  ));
  assert.equal(
    external.headers.get("location"),
    "https://oauth.yandex.ru/authorize?client_id=test",
  );
});


test("unrelated mutation endpoints remain blocked", async () => {
  globalThis.fetch = async () => {
    throw new Error("blocked requests must not reach Railway");
  };

  for (const path of ["/telegram/webhook", "/releases/import", "/releases/bootstrap"]) {
    const response = await worker.fetch(new Request(
      `https://releasecraft-proxy.skillaz-release.workers.dev${path}`,
      {method: "POST"},
    ));
    assert.equal(response.status, 404);
  }
});
